"""Dispatch launch redemption core.

This module is the pure, testable substrate for replacing standalone same-user
``DispatchCapability`` files. It intentionally does not claim user
authentication. In Hapax's single-user model, the useful boundary is a governed
control path: a fixed authority owns an in-memory grant table, validates launch
context at redemption time, and emits auditable decisions. Wrappers must not
accept caller-selected socket paths or standalone same-user-signed files as
authority.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import socket
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast


def dispatch_launch_redemption_socket() -> Path:
    """Return the fixed runtime socket path wrappers should use.

    This path is deliberately not configurable by caller environment and is not
    under ``/run/user/<uid>``. The production socket must be owned by the
    governor/coord service in a runtime directory the launching user cannot
    create or replace; otherwise a same-UID direct caller could bind a fake
    fixed-path server while the real authority is down. Test code can pass a
    custom socket path to code under test.
    """

    return Path("/run") / "hapax" / "coord" / "dispatch-redemption.sock"


@dataclass(frozen=True)
class LaunchRedemptionContext:
    """Launch context bound to a one-time redemption token."""

    task_id: str
    lane: str
    platform: str
    mode: str
    profile: str
    worktree: str
    purpose: Literal["dispatch_launch", "external_launch"]
    dispatch_message_id: str
    route_decision_ref: str
    authority_case: str
    parent_spec: str | None = None

    def normalized(self) -> LaunchRedemptionContext:
        return LaunchRedemptionContext(
            task_id=self.task_id.strip(),
            lane=self.lane.strip().lower().replace("_", "-"),
            platform=self.platform.strip().lower(),
            mode=self.mode.strip().lower(),
            profile=self.profile.strip().lower(),
            worktree=str(Path(self.worktree).resolve()),
            purpose=self.purpose,
            dispatch_message_id=self.dispatch_message_id.strip(),
            route_decision_ref=self.route_decision_ref.strip(),
            authority_case=self.authority_case.strip(),
            parent_spec=self.parent_spec.strip() if self.parent_spec else None,
        )

    def validate(self) -> None:
        required = {
            "task_id": self.task_id,
            "lane": self.lane,
            "platform": self.platform,
            "mode": self.mode,
            "profile": self.profile,
            "worktree": self.worktree,
            "dispatch_message_id": self.dispatch_message_id,
            "route_decision_ref": self.route_decision_ref,
            "authority_case": self.authority_case,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError(f"launch redemption context missing: {', '.join(missing)}")


@dataclass(frozen=True)
class LaunchRedemptionGrant:
    """Opaque one-time grant returned by the authority to the dispatcher."""

    grant_id: str
    token: str
    expires_at: float


@dataclass(frozen=True)
class LaunchRedemptionRequest:
    """Observed wrapper context plus the opaque token."""

    token: str
    context: LaunchRedemptionContext
    wrapper: str
    wrapper_pid: int
    observed_at: float


@dataclass(frozen=True)
class LaunchRedemptionResponse:
    """Authority decision for one wrapper redemption attempt."""

    ok: bool
    reason: str
    grant_id: str | None = None
    consumed_at: float | None = None
    dispatch_message_id: str | None = None
    route_decision_ref: str | None = None


@dataclass(frozen=True)
class LaunchRedemptionEvent:
    """Token-free event suitable for Reins/status projection."""

    event_type: Literal["grant_minted", "grant_redeemed", "grant_refused"]
    grant_id: str | None
    task_id: str | None
    lane: str | None
    platform: str | None
    mode: str | None
    profile: str | None
    dispatch_message_id: str | None
    route_decision_ref: str | None
    reason: str
    observed_at: float


@dataclass
class _StoredGrant:
    grant_id: str
    token_digest: str
    context: LaunchRedemptionContext
    expires_at: float
    consumed_at: float | None = None


class DispatchLaunchRedemptionAuthority:
    """In-memory one-time launch-grant table.

    A long-lived coord/governor daemon should own one instance of this class and
    expose it at ``dispatch_launch_redemption_socket()``. Keeping the table
    in-memory is load-bearing: a same-UID caller cannot mint authority by
    writing a file that the wrapper later trusts.
    """

    def __init__(
        self,
        *,
        now: Callable[[], float] | None = None,
        policy_check: Callable[[LaunchRedemptionContext], str | None] | None = None,
    ) -> None:
        self._now = now or time.time
        self._policy_check = policy_check
        self._grants: dict[str, _StoredGrant] = {}
        self._events: list[LaunchRedemptionEvent] = []

    def mint(
        self, context: LaunchRedemptionContext, *, ttl_s: float = 600.0
    ) -> LaunchRedemptionGrant:
        if ttl_s <= 0:
            raise ValueError("ttl_s must be positive")
        normalized = context.normalized()
        normalized.validate()
        token = secrets.token_urlsafe(32)
        grant_id = secrets.token_hex(16)
        expires_at = float(self._now()) + ttl_s
        self._grants[_token_digest(token)] = _StoredGrant(
            grant_id=grant_id,
            token_digest=_token_digest(token),
            context=normalized,
            expires_at=expires_at,
        )
        self._append_event(
            "grant_minted",
            grant_id=grant_id,
            context=normalized,
            reason="minted",
            observed_at=float(self._now()),
        )
        return LaunchRedemptionGrant(grant_id=grant_id, token=token, expires_at=expires_at)

    def redeem(self, request: LaunchRedemptionRequest) -> LaunchRedemptionResponse:
        now = float(self._now())
        token = request.token.strip()
        if not token:
            response = LaunchRedemptionResponse(ok=False, reason="missing_token")
            self._append_response_event(response, None, observed_at=now)
            return response
        stored = self._grants.get(_token_digest(token))
        if stored is None:
            response = LaunchRedemptionResponse(ok=False, reason="unknown_token")
            self._append_response_event(response, None, observed_at=now)
            return response
        if stored.consumed_at is not None:
            response = LaunchRedemptionResponse(
                ok=False,
                reason="already_consumed",
                grant_id=stored.grant_id,
                consumed_at=stored.consumed_at,
                dispatch_message_id=stored.context.dispatch_message_id,
                route_decision_ref=stored.context.route_decision_ref,
            )
            self._append_response_event(response, stored.context, observed_at=now)
            return response
        if now > stored.expires_at:
            response = LaunchRedemptionResponse(
                ok=False,
                reason="expired_token",
                grant_id=stored.grant_id,
                dispatch_message_id=stored.context.dispatch_message_id,
                route_decision_ref=stored.context.route_decision_ref,
            )
            self._append_response_event(response, stored.context, observed_at=now)
            return response
        try:
            observed = request.context.normalized()
            observed.validate()
        except ValueError:
            response = LaunchRedemptionResponse(
                ok=False,
                reason="invalid_context",
                grant_id=stored.grant_id,
            )
            self._append_response_event(response, stored.context, observed_at=now)
            return response
        if observed != stored.context:
            response = LaunchRedemptionResponse(
                ok=False,
                reason="context_mismatch",
                grant_id=stored.grant_id,
                dispatch_message_id=stored.context.dispatch_message_id,
                route_decision_ref=stored.context.route_decision_ref,
            )
            self._append_response_event(response, stored.context, observed_at=now)
            return response
        if self._policy_check is not None:
            refusal = self._policy_check(stored.context)
            if refusal:
                response = LaunchRedemptionResponse(
                    ok=False,
                    reason=f"policy_refused:{refusal}",
                    grant_id=stored.grant_id,
                    dispatch_message_id=stored.context.dispatch_message_id,
                    route_decision_ref=stored.context.route_decision_ref,
                )
                self._append_response_event(response, stored.context, observed_at=now)
                return response
        stored.consumed_at = now
        response = LaunchRedemptionResponse(
            ok=True,
            reason="redeemed",
            grant_id=stored.grant_id,
            consumed_at=stored.consumed_at,
            dispatch_message_id=stored.context.dispatch_message_id,
            route_decision_ref=stored.context.route_decision_ref,
        )
        self._append_response_event(response, stored.context, observed_at=now)
        return response

    def events(self) -> tuple[LaunchRedemptionEvent, ...]:
        return tuple(self._events)

    def _append_response_event(
        self,
        response: LaunchRedemptionResponse,
        context: LaunchRedemptionContext | None,
        *,
        observed_at: float,
    ) -> None:
        event_type: Literal["grant_redeemed", "grant_refused"] = (
            "grant_redeemed" if response.ok else "grant_refused"
        )
        self._append_event(
            event_type,
            grant_id=response.grant_id,
            context=context,
            reason=response.reason,
            observed_at=observed_at,
        )

    def _append_event(
        self,
        event_type: Literal["grant_minted", "grant_redeemed", "grant_refused"],
        *,
        grant_id: str | None,
        context: LaunchRedemptionContext | None,
        reason: str,
        observed_at: float,
    ) -> None:
        self._events.append(
            LaunchRedemptionEvent(
                event_type=event_type,
                grant_id=grant_id,
                task_id=context.task_id if context else None,
                lane=context.lane if context else None,
                platform=context.platform if context else None,
                mode=context.mode if context else None,
                profile=context.profile if context else None,
                dispatch_message_id=context.dispatch_message_id if context else None,
                route_decision_ref=context.route_decision_ref if context else None,
                reason=reason,
                observed_at=observed_at,
            )
        )


class DispatchLaunchRedemptionServer:
    """Unix-socket server for a live launch-redemption authority.

    This class is deliberately small: it owns socket lifecycle and request I/O,
    while ``DispatchLaunchRedemptionAuthority`` owns grant state and policy
    decisions. Production callers should use the default socket path; tests may
    pass a temporary path.
    """

    def __init__(
        self,
        authority: DispatchLaunchRedemptionAuthority,
        *,
        socket_path: Path | None = None,
        socket_mode: int = 0o660,
        directory_mode: int = 0o750,
    ) -> None:
        self._authority = authority
        self._socket_path = socket_path or dispatch_launch_redemption_socket()
        self._socket_mode = socket_mode
        self._directory_mode = directory_mode

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    def serve_once(self, *, timeout_s: float | None = None) -> None:
        with self._bound_socket(timeout_s=timeout_s) as server:
            conn, _addr = server.accept()
            with conn:
                response = handle_redemption_bytes(
                    self._authority, _recv_line(conn, max_bytes=65536)
                )
                conn.sendall(_encode_response_payload(response))

    def _bound_socket(self, *, timeout_s: float | None = None) -> socket.socket:
        path = self._socket_path
        _prepare_socket_path(path, directory_mode=self._directory_mode)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(path))
            path.chmod(self._socket_mode)
            server.listen(32)
            if timeout_s is not None:
                server.settimeout(timeout_s)
            return server
        except Exception:
            server.close()
            raise


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def redemption_request_payload(request: LaunchRedemptionRequest) -> dict[str, object]:
    context = request.context.normalized()
    return {
        "schema": "hapax.dispatch_launch_redeem.v1",
        "token": request.token,
        "task_id": context.task_id,
        "lane": context.lane,
        "platform": context.platform,
        "mode": context.mode,
        "profile": context.profile,
        "worktree": context.worktree,
        "purpose": context.purpose,
        "dispatch_message_id": context.dispatch_message_id,
        "route_decision_ref": context.route_decision_ref,
        "authority_case": context.authority_case,
        "parent_spec": context.parent_spec,
        "wrapper": request.wrapper,
        "wrapper_pid": request.wrapper_pid,
        "observed_at": request.observed_at,
    }


def parse_redemption_request(payload: dict[str, object]) -> LaunchRedemptionRequest:
    if payload.get("schema") != "hapax.dispatch_launch_redeem.v1":
        raise ValueError("unsupported dispatch launch redemption schema")
    wrapper = str(payload.get("wrapper", "")).strip()
    wrapper_pid = int(payload.get("wrapper_pid", 0) or 0)
    if not wrapper:
        raise ValueError("launch redemption request missing wrapper")
    if wrapper_pid <= 0:
        raise ValueError("launch redemption request missing wrapper_pid")
    context = LaunchRedemptionContext(
        task_id=str(payload.get("task_id", "")),
        lane=str(payload.get("lane", "")),
        platform=str(payload.get("platform", "")),
        mode=str(payload.get("mode", "")),
        profile=str(payload.get("profile", "")),
        worktree=str(payload.get("worktree", "")),
        purpose=_purpose(str(payload.get("purpose", ""))),
        dispatch_message_id=str(payload.get("dispatch_message_id", "")),
        route_decision_ref=str(payload.get("route_decision_ref", "")),
        authority_case=str(payload.get("authority_case", "")),
        parent_spec=_optional_str(payload.get("parent_spec")),
    )
    return LaunchRedemptionRequest(
        token=str(payload.get("token", "")),
        context=context,
        wrapper=wrapper,
        wrapper_pid=wrapper_pid,
        observed_at=float(payload.get("observed_at", 0.0) or 0.0),
    )


def redemption_response_payload(response: LaunchRedemptionResponse) -> dict[str, object]:
    return {
        "schema": "hapax.dispatch_launch_redeem_response.v1",
        "ok": response.ok,
        "reason": response.reason,
        "grant_id": response.grant_id,
        "consumed_at": response.consumed_at,
        "dispatch_message_id": response.dispatch_message_id,
        "route_decision_ref": response.route_decision_ref,
    }


def redemption_event_payload(event: LaunchRedemptionEvent) -> dict[str, object]:
    return {
        "schema": "hapax.dispatch_launch_redemption_event.v1",
        "event_type": event.event_type,
        "grant_id": event.grant_id,
        "task_id": event.task_id,
        "lane": event.lane,
        "platform": event.platform,
        "mode": event.mode,
        "profile": event.profile,
        "dispatch_message_id": event.dispatch_message_id,
        "route_decision_ref": event.route_decision_ref,
        "reason": event.reason,
        "observed_at": event.observed_at,
    }


def parse_redemption_response(payload: dict[str, object]) -> LaunchRedemptionResponse:
    if payload.get("schema") != "hapax.dispatch_launch_redeem_response.v1":
        raise ValueError("unsupported dispatch launch redemption response schema")
    return LaunchRedemptionResponse(
        ok=bool(payload.get("ok", False)),
        reason=str(payload.get("reason", "")),
        grant_id=_optional_str(payload.get("grant_id")),
        consumed_at=_optional_float(payload.get("consumed_at")),
        dispatch_message_id=_optional_str(payload.get("dispatch_message_id")),
        route_decision_ref=_optional_str(payload.get("route_decision_ref")),
    )


def handle_redemption_payload(
    authority: DispatchLaunchRedemptionAuthority, payload: dict[str, object]
) -> dict[str, object]:
    """Validate one decoded request payload and return a decoded response payload.

    The eventual daemon should call this before writing the JSON response. Bad
    request shape is still an explicit authorization refusal, not an exception
    path that can accidentally let a wrapper proceed.
    """

    try:
        request = parse_redemption_request(payload)
    except Exception as exc:  # noqa: BLE001 - bad launch requests fail closed.
        return redemption_response_payload(
            LaunchRedemptionResponse(
                ok=False,
                reason=f"invalid_request:{type(exc).__name__}",
            )
        )
    return redemption_response_payload(authority.redeem(request))


def handle_redemption_bytes(
    authority: DispatchLaunchRedemptionAuthority, data: bytes
) -> dict[str, object]:
    try:
        payload = _decode_request_bytes(data)
    except Exception as exc:  # noqa: BLE001 - malformed launch requests fail closed.
        return redemption_response_payload(
            LaunchRedemptionResponse(
                ok=False,
                reason=f"invalid_request:{type(exc).__name__}",
            )
        )
    return handle_redemption_payload(authority, payload)


def redeem_launch_via_socket(
    request: LaunchRedemptionRequest,
    *,
    socket_path: Path | None = None,
    timeout_s: float = 2.0,
) -> LaunchRedemptionResponse:
    """Redeem a launch grant through the fixed authority socket.

    Wrappers should call this without ``socket_path``. The parameter exists for
    tests and for daemon internals; production launch adapters must not expose it
    as caller-controlled env/config.
    """

    path = socket_path or dispatch_launch_redemption_socket()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout_s)
            client.connect(str(path))
            client.sendall(_encode_request_payload(redemption_request_payload(request)))
            data = _recv_line(client, max_bytes=65536)
        response = parse_redemption_response(_decode_response_bytes(data))
        invalid = _redemption_response_mismatch(response, request)
        if invalid:
            return LaunchRedemptionResponse(ok=False, reason=f"invalid_response:{invalid}")
        return response
    except Exception as exc:  # noqa: BLE001 - launch authorization fails closed.
        return LaunchRedemptionResponse(ok=False, reason=f"socket_unavailable:{type(exc).__name__}")


def _redemption_response_mismatch(
    response: LaunchRedemptionResponse, request: LaunchRedemptionRequest
) -> str | None:
    if not response.ok:
        return None
    context = request.context.normalized()
    if not response.grant_id:
        return "missing_grant_id"
    if response.consumed_at is None:
        return "missing_consumed_at"
    if response.dispatch_message_id != context.dispatch_message_id:
        return "dispatch_message_id_mismatch"
    if response.route_decision_ref != context.route_decision_ref:
        return "route_decision_ref_mismatch"
    return None


def _prepare_socket_path(path: Path, *, directory_mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(directory_mode)
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(mode):
        raise FileExistsError(f"refusing to replace non-socket path: {path}")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.05)
            probe.connect(str(path))
    except OSError:
        path.unlink()
        return
    raise OSError(f"redemption socket already active: {path}")


def _encode_request_payload(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def _encode_response_payload(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def _decode_request_bytes(data: bytes) -> dict[str, object]:
    payload = json.loads(data.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("redemption request must be a JSON object")
    return payload


def _decode_response_bytes(data: bytes) -> dict[str, object]:
    payload = json.loads(data.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("redemption response must be a JSON object")
    return payload


def _recv_line(client: socket.socket, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = client.recv(4096)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValueError("redemption response too large")
        if b"\n" in chunk:
            before, _sep, _after = chunk.partition(b"\n")
            chunks.append(before)
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _purpose(value: str) -> Literal["dispatch_launch", "external_launch"]:
    if value not in {"dispatch_launch", "external_launch"}:
        raise ValueError("invalid launch redemption purpose")
    return cast("Literal['dispatch_launch', 'external_launch']", value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


__all__ = [
    "DispatchLaunchRedemptionAuthority",
    "DispatchLaunchRedemptionServer",
    "LaunchRedemptionContext",
    "LaunchRedemptionEvent",
    "LaunchRedemptionGrant",
    "LaunchRedemptionRequest",
    "LaunchRedemptionResponse",
    "dispatch_launch_redemption_socket",
    "handle_redemption_bytes",
    "handle_redemption_payload",
    "parse_redemption_request",
    "parse_redemption_response",
    "redeem_launch_via_socket",
    "redemption_event_payload",
    "redemption_request_payload",
    "redemption_response_payload",
]
