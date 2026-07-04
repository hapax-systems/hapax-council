"""Dispatch launch redemption substrate.

This module replaces wrapper-side trust in same-user launch files with a live
authority check. It does not claim user authentication; the boundary is that a
governed dispatcher or coordinator owns an in-memory one-time grant table and
the wrapper redeems an opaque token over a fixed socket.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import socket
import stat
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast


def dispatch_launch_redemption_socket() -> Path:
    """Fixed production socket for launch redemption.

    Callers must not select this path through env/config. A caller-selectable
    socket is equivalent to letting a same-UID launcher run its own authority.
    """

    return Path("/run/hapax/coord/dispatch-redemption.sock")


@dataclass(frozen=True)
class LaunchRedemptionContext:
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
            profile=self.profile.strip().lower().replace("_", "-"),
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
    grant_id: str
    token: str
    expires_at: float


@dataclass(frozen=True)
class LaunchRedemptionRequest:
    token: str
    context: LaunchRedemptionContext
    wrapper: str
    wrapper_pid: int
    observed_at: float


@dataclass(frozen=True)
class LaunchRedemptionResponse:
    ok: bool
    reason: str
    grant_id: str | None = None
    consumed_at: float | None = None
    dispatch_message_id: str | None = None
    route_decision_ref: str | None = None


@dataclass(frozen=True)
class LaunchMintRequest:
    context: LaunchRedemptionContext
    requester: str
    requester_pid: int
    ttl_s: float
    observed_at: float


@dataclass(frozen=True)
class LaunchMintResponse:
    ok: bool
    reason: str
    grant_id: str | None = None
    token: str | None = None
    expires_at: float | None = None


@dataclass(frozen=True)
class LaunchPeerCredentials:
    pid: int
    uid: int
    gid: int


@dataclass(frozen=True)
class LaunchRedemptionEvent:
    event_type: Literal["grant_minted", "grant_redeemed", "grant_refused", "mint_refused"]
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
    peer_pid: int | None = None
    peer_uid: int | None = None
    peer_gid: int | None = None
    requester: str | None = None
    requester_pid: int | None = None
    wrapper: str | None = None
    wrapper_pid: int | None = None


class LaunchMintRefusedError(RuntimeError):
    """Mint policy refused the launch context (recorded as a mint_refused event)."""


@dataclass
class _StoredGrant:
    grant_id: str
    token_digest: str
    context: LaunchRedemptionContext
    expires_at: float
    consumed_at: float | None = None


class DispatchLaunchRedemptionAuthority:
    """In-memory, one-time launch grant authority."""

    def __init__(
        self,
        *,
        now: Callable[[], float] | None = None,
        policy_check: Callable[[LaunchRedemptionContext], str | None] | None = None,
        mint_policy_check: Callable[[LaunchRedemptionContext], str | None] | None = None,
        event_sink: Callable[[LaunchRedemptionEvent], None] | None = None,
    ) -> None:
        self._now = now or time.time
        self._policy_check = policy_check
        self._mint_policy_check = mint_policy_check
        self._event_sink = event_sink
        self._grants: dict[str, _StoredGrant] = {}
        self._events: list[LaunchRedemptionEvent] = []

    def mint(
        self,
        context: LaunchRedemptionContext,
        *,
        ttl_s: float = 600.0,
        peer: LaunchPeerCredentials | None = None,
        requester: str | None = None,
        requester_pid: int | None = None,
    ) -> LaunchRedemptionGrant:
        if ttl_s <= 0:
            raise ValueError("ttl_s must be positive")
        normalized = context.normalized()
        normalized.validate()
        if self._mint_policy_check is not None:
            refusal = self._mint_policy_check(normalized)
            if refusal:
                self._append_event(
                    "mint_refused",
                    grant_id=None,
                    context=normalized,
                    reason=f"mint_policy_refused:{refusal}",
                    observed_at=float(self._now()),
                    peer=peer,
                    requester=requester,
                    requester_pid=requester_pid,
                )
                raise LaunchMintRefusedError(refusal)
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
            peer=peer,
            requester=requester,
            requester_pid=requester_pid,
        )
        return LaunchRedemptionGrant(grant_id=grant_id, token=token, expires_at=expires_at)

    def redeem(
        self, request: LaunchRedemptionRequest, *, peer: LaunchPeerCredentials | None = None
    ) -> LaunchRedemptionResponse:
        now = float(self._now())
        token = request.token.strip()
        if not token:
            return self._response(
                False,
                "missing_token",
                None,
                now,
                peer=peer,
                wrapper=request.wrapper,
                wrapper_pid=request.wrapper_pid,
            )
        stored = self._grants.get(_token_digest(token))
        if stored is None:
            return self._response(
                False,
                "unknown_token",
                None,
                now,
                peer=peer,
                wrapper=request.wrapper,
                wrapper_pid=request.wrapper_pid,
            )
        if stored.consumed_at is not None:
            return self._response(
                False,
                "already_consumed",
                stored,
                now,
                peer=peer,
                wrapper=request.wrapper,
                wrapper_pid=request.wrapper_pid,
            )
        if now > stored.expires_at:
            return self._response(
                False,
                "expired_token",
                stored,
                now,
                peer=peer,
                wrapper=request.wrapper,
                wrapper_pid=request.wrapper_pid,
            )
        try:
            observed = request.context.normalized()
            observed.validate()
        except ValueError:
            return self._response(
                False,
                "invalid_context",
                stored,
                now,
                peer=peer,
                wrapper=request.wrapper,
                wrapper_pid=request.wrapper_pid,
            )
        if observed != stored.context:
            return self._response(
                False,
                "context_mismatch",
                stored,
                now,
                peer=peer,
                wrapper=request.wrapper,
                wrapper_pid=request.wrapper_pid,
            )
        if self._policy_check is not None:
            refusal = self._policy_check(stored.context)
            if refusal:
                return self._response(
                    False,
                    f"policy_refused:{refusal}",
                    stored,
                    now,
                    peer=peer,
                    wrapper=request.wrapper,
                    wrapper_pid=request.wrapper_pid,
                )
        stored.consumed_at = now
        return self._response(
            True,
            "redeemed",
            stored,
            now,
            peer=peer,
            wrapper=request.wrapper,
            wrapper_pid=request.wrapper_pid,
        )

    def events(self) -> tuple[LaunchRedemptionEvent, ...]:
        return tuple(self._events)

    def purge_expired(self) -> int:
        """Drop expired or consumed grants from the in-memory table.

        Redemption outcomes are unchanged (redeem checks expiry itself);
        this only bounds table growth in a long-running authority.
        """

        now = float(self._now())
        dead = [
            digest
            for digest, stored in self._grants.items()
            if stored.consumed_at is not None or now > stored.expires_at
        ]
        for digest in dead:
            del self._grants[digest]
        return len(dead)

    def record_mint_refusal(
        self,
        context: LaunchRedemptionContext | None,
        *,
        reason: str,
        peer: LaunchPeerCredentials | None = None,
        requester: str | None = None,
        requester_pid: int | None = None,
    ) -> None:
        normalized: LaunchRedemptionContext | None = None
        if context is not None:
            try:
                normalized = context.normalized()
                normalized.validate()
            except ValueError:
                normalized = None
        self._append_event(
            "mint_refused",
            grant_id=None,
            context=normalized,
            reason=reason,
            observed_at=float(self._now()),
            peer=peer,
            requester=requester,
            requester_pid=requester_pid,
        )

    def _response(
        self,
        ok: bool,
        reason: str,
        stored: _StoredGrant | None,
        observed_at: float,
        *,
        peer: LaunchPeerCredentials | None = None,
        wrapper: str | None = None,
        wrapper_pid: int | None = None,
    ) -> LaunchRedemptionResponse:
        response = LaunchRedemptionResponse(
            ok=ok,
            reason=reason,
            grant_id=stored.grant_id if stored else None,
            consumed_at=stored.consumed_at if stored else None,
            dispatch_message_id=stored.context.dispatch_message_id if stored else None,
            route_decision_ref=stored.context.route_decision_ref if stored else None,
        )
        self._append_event(
            "grant_redeemed" if ok else "grant_refused",
            grant_id=response.grant_id,
            context=stored.context if stored else None,
            reason=reason,
            observed_at=observed_at,
            peer=peer,
            wrapper=wrapper,
            wrapper_pid=wrapper_pid,
        )
        return response

    def _append_event(
        self,
        event_type: Literal["grant_minted", "grant_redeemed", "grant_refused", "mint_refused"],
        *,
        grant_id: str | None,
        context: LaunchRedemptionContext | None,
        reason: str,
        observed_at: float,
        peer: LaunchPeerCredentials | None = None,
        requester: str | None = None,
        requester_pid: int | None = None,
        wrapper: str | None = None,
        wrapper_pid: int | None = None,
    ) -> None:
        event = LaunchRedemptionEvent(
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
            peer_pid=peer.pid if peer else None,
            peer_uid=peer.uid if peer else None,
            peer_gid=peer.gid if peer else None,
            requester=requester,
            requester_pid=requester_pid,
            wrapper=wrapper,
            wrapper_pid=wrapper_pid,
        )
        self._events.append(event)
        if self._event_sink is not None:
            # Evidence emission must never turn a mint/redeem decision into a
            # crash (NEVER-FREEZE): sink failures are the sink's problem to
            # surface (journal/stderr), not a reason to refuse a launch.
            try:
                self._event_sink(event)
            except Exception:  # noqa: BLE001 - witnessed by the daemon's own logging.
                pass


class DispatchLaunchRedemptionServer:
    """Small Unix-socket server around a redemption authority."""

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
                response = handle_authority_bytes(
                    self._authority,
                    _recv_line(conn, max_bytes=65536),
                    peer=_peer_credentials(conn),
                    require_mint_peer=True,
                )
                conn.sendall(_encode_payload(response))

    def serve_forever(
        self,
        *,
        should_stop: Callable[[], bool] | None = None,
        poll_timeout_s: float = 1.0,
        on_error: Callable[[BaseException], None] | None = None,
    ) -> None:
        """Bind the fixed socket once and answer mint/redeem requests until stopped.

        Per-connection failures are contained (reported via ``on_error``) so one
        malformed caller cannot take the grant authority down; the socket is
        unlinked on exit so wrappers fail closed on connect instead of talking
        to a dead inode.
        """

        with self._bound_socket(timeout_s=poll_timeout_s) as server:
            try:
                while not (should_stop is not None and should_stop()):
                    try:
                        conn, _addr = server.accept()
                    except TimeoutError:
                        continue
                    except OSError as exc:
                        if on_error is not None:
                            on_error(exc)
                        continue
                    try:
                        with conn:
                            conn.settimeout(poll_timeout_s)
                            peer = _peer_credentials(conn)
                            response = handle_authority_bytes(
                                self._authority,
                                _recv_line(conn, max_bytes=65536),
                                peer=peer,
                                require_mint_peer=True,
                            )
                            conn.sendall(_encode_payload(response))
                    except Exception as exc:  # noqa: BLE001 - one bad conn must not kill the authority.
                        if on_error is not None:
                            on_error(exc)
            finally:
                try:
                    self._socket_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _bound_socket(self, *, timeout_s: float | None = None) -> socket.socket:
        _prepare_socket_path(self._socket_path, directory_mode=self._directory_mode)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_PASSCRED"):
                server.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            server.bind(str(self._socket_path))
            self._socket_path.chmod(self._socket_mode)
            server.listen(32)
            if timeout_s is not None:
                server.settimeout(timeout_s)
            return server
        except Exception:
            server.close()
            raise


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
    return LaunchRedemptionRequest(
        token=str(payload.get("token", "")),
        context=LaunchRedemptionContext(
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
        ),
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


def mint_request_payload(request: LaunchMintRequest) -> dict[str, object]:
    context = request.context.normalized()
    return {
        "schema": "hapax.dispatch_launch_mint.v1",
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
        "requester": request.requester,
        "requester_pid": request.requester_pid,
        "ttl_s": request.ttl_s,
        "observed_at": request.observed_at,
    }


def parse_mint_request(payload: dict[str, object]) -> LaunchMintRequest:
    if payload.get("schema") != "hapax.dispatch_launch_mint.v1":
        raise ValueError("unsupported dispatch launch mint schema")
    requester = str(payload.get("requester", "")).strip()
    requester_pid = int(payload.get("requester_pid", 0) or 0)
    if not requester:
        raise ValueError("launch mint request missing requester")
    if requester_pid <= 0:
        raise ValueError("launch mint request missing requester_pid")
    ttl_s = float(payload.get("ttl_s", 0.0) or 0.0)
    if ttl_s <= 0:
        raise ValueError("launch mint request missing ttl_s")
    return LaunchMintRequest(
        context=LaunchRedemptionContext(
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
        ),
        requester=requester,
        requester_pid=requester_pid,
        ttl_s=ttl_s,
        observed_at=float(payload.get("observed_at", 0.0) or 0.0),
    )


def mint_response_payload(response: LaunchMintResponse) -> dict[str, object]:
    return {
        "schema": "hapax.dispatch_launch_mint_response.v1",
        "ok": response.ok,
        "reason": response.reason,
        "grant_id": response.grant_id,
        "token": response.token,
        "expires_at": response.expires_at,
    }


def parse_mint_response(payload: dict[str, object]) -> LaunchMintResponse:
    if payload.get("schema") != "hapax.dispatch_launch_mint_response.v1":
        raise ValueError("unsupported dispatch launch mint response schema")
    return LaunchMintResponse(
        ok=bool(payload.get("ok", False)),
        reason=str(payload.get("reason", "")),
        grant_id=_optional_str(payload.get("grant_id")),
        token=_optional_str(payload.get("token")),
        expires_at=_optional_float(payload.get("expires_at")),
    )


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
        "peer_pid": event.peer_pid,
        "peer_uid": event.peer_uid,
        "peer_gid": event.peer_gid,
        "requester": event.requester,
        "requester_pid": event.requester_pid,
        "wrapper": event.wrapper,
        "wrapper_pid": event.wrapper_pid,
    }


def handle_redemption_payload(
    authority: DispatchLaunchRedemptionAuthority,
    payload: dict[str, object],
    *,
    peer: LaunchPeerCredentials | None = None,
) -> dict[str, object]:
    try:
        request = parse_redemption_request(payload)
    except Exception as exc:  # noqa: BLE001 - bad launch requests fail closed.
        return redemption_response_payload(
            LaunchRedemptionResponse(ok=False, reason=f"invalid_request:{type(exc).__name__}")
        )
    return redemption_response_payload(authority.redeem(request, peer=peer))


def handle_redemption_bytes(
    authority: DispatchLaunchRedemptionAuthority,
    data: bytes,
    *,
    peer: LaunchPeerCredentials | None = None,
) -> dict[str, object]:
    try:
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("redemption request must be a JSON object")
    except Exception as exc:  # noqa: BLE001 - malformed launch requests fail closed.
        return redemption_response_payload(
            LaunchRedemptionResponse(ok=False, reason=f"invalid_request:{type(exc).__name__}")
        )
    return handle_redemption_payload(authority, payload, peer=peer)


def handle_mint_payload(
    authority: DispatchLaunchRedemptionAuthority,
    payload: dict[str, object],
    *,
    peer: LaunchPeerCredentials | None = None,
    require_peer: bool = False,
) -> dict[str, object]:
    try:
        request = parse_mint_request(payload)
    except Exception as exc:  # noqa: BLE001 - bad mint requests fail closed.
        return mint_response_payload(
            LaunchMintResponse(ok=False, reason=f"invalid_request:{type(exc).__name__}")
        )
    peer_refusal = _mint_peer_refusal(request, peer, require_peer=require_peer)
    if peer_refusal is not None:
        authority.record_mint_refusal(
            request.context,
            reason=peer_refusal,
            peer=peer,
            requester=request.requester,
            requester_pid=request.requester_pid,
        )
        return mint_response_payload(LaunchMintResponse(ok=False, reason=peer_refusal))
    try:
        grant = authority.mint(
            request.context,
            ttl_s=request.ttl_s,
            peer=peer,
            requester=request.requester,
            requester_pid=request.requester_pid,
        )
    except LaunchMintRefusedError as exc:
        return mint_response_payload(
            LaunchMintResponse(ok=False, reason=f"mint_policy_refused:{exc}")
        )
    except Exception as exc:  # noqa: BLE001 - invalid contexts fail closed.
        return mint_response_payload(
            LaunchMintResponse(ok=False, reason=f"invalid_context:{type(exc).__name__}")
        )
    return mint_response_payload(
        LaunchMintResponse(
            ok=True,
            reason="minted",
            grant_id=grant.grant_id,
            token=grant.token,
            expires_at=grant.expires_at,
        )
    )


def handle_authority_bytes(
    authority: DispatchLaunchRedemptionAuthority,
    data: bytes,
    *,
    peer: LaunchPeerCredentials | None = None,
    require_mint_peer: bool = False,
) -> dict[str, object]:
    """Route one wire request (mint or redeem) to the authority, failing closed.

    The mint response is the ONLY surface where a token value crosses the wire;
    it goes back to the requesting dispatcher and never into events or ledgers.
    """

    try:
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("authority request must be a JSON object")
    except Exception as exc:  # noqa: BLE001 - malformed requests fail closed.
        return redemption_response_payload(
            LaunchRedemptionResponse(ok=False, reason=f"invalid_request:{type(exc).__name__}")
        )
    schema = payload.get("schema")
    if schema == "hapax.dispatch_launch_mint.v1":
        return handle_mint_payload(authority, payload, peer=peer, require_peer=require_mint_peer)
    if schema == "hapax.dispatch_launch_redeem.v1":
        return handle_redemption_payload(authority, payload, peer=peer)
    return redemption_response_payload(
        LaunchRedemptionResponse(ok=False, reason="invalid_request:unsupported_schema")
    )


def mint_launch_via_socket(
    request: LaunchMintRequest,
    *,
    socket_path: Path | None = None,
    timeout_s: float = 2.0,
) -> LaunchMintResponse:
    """Ask the fixed governor to mint a one-time launch grant.

    Only the governed dispatcher should call this; the returned token is handed
    to the wrapper via env and redeemed exactly once. Fails closed on any
    socket/parse error so an absent or unhealthy governor refuses launches.
    """

    path = socket_path or dispatch_launch_redemption_socket()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout_s)
            client.connect(str(path))
            client.sendall(_encode_payload(mint_request_payload(request)))
            data = _recv_line(client, max_bytes=65536)
        return parse_mint_response(json.loads(data.decode("utf-8")))
    except Exception as exc:  # noqa: BLE001 - mint fails closed.
        return LaunchMintResponse(ok=False, reason=f"socket_unavailable:{type(exc).__name__}")


def redeem_launch_via_socket(
    request: LaunchRedemptionRequest,
    *,
    socket_path: Path | None = None,
    timeout_s: float = 2.0,
) -> LaunchRedemptionResponse:
    path = socket_path or dispatch_launch_redemption_socket()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout_s)
            client.connect(str(path))
            client.sendall(_encode_payload(redemption_request_payload(request)))
            data = _recv_line(client, max_bytes=65536)
        response = parse_redemption_response(json.loads(data.decode("utf-8")))
        mismatch = _response_mismatch(response, request)
        if mismatch:
            return LaunchRedemptionResponse(ok=False, reason=f"invalid_response:{mismatch}")
        return response
    except Exception as exc:  # noqa: BLE001 - launch authorization fails closed.
        return LaunchRedemptionResponse(ok=False, reason=f"socket_unavailable:{type(exc).__name__}")


def _response_mismatch(
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


def _peer_credentials(client: socket.socket) -> LaunchPeerCredentials | None:
    if not hasattr(socket, "SO_PEERCRED"):
        return None
    try:
        raw = client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, uid, gid = struct.unpack("3i", raw)
    except OSError:
        return None
    return LaunchPeerCredentials(pid=pid, uid=uid, gid=gid)


def _mint_peer_refusal(
    request: LaunchMintRequest,
    peer: LaunchPeerCredentials | None,
    *,
    require_peer: bool = False,
) -> str | None:
    if peer is None:
        if require_peer:
            return "peer_unavailable"
        return None
    # This is provenance/witnessing, not user authentication: same-UID callers
    # can still speak the socket protocol, but they cannot claim a different
    # requester pid/uid without a token-free refusal event.
    if peer.uid != os.getuid():
        return f"peer_uid_mismatch:{peer.uid}"
    if request.requester_pid != peer.pid:
        return f"peer_pid_mismatch:{request.requester_pid}!={peer.pid}"
    return None


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _encode_payload(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


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
        before, sep, _after = chunk.partition(b"\n")
        chunks.append(before)
        if sep:
            break
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
    "LaunchMintRefusedError",
    "LaunchMintRequest",
    "LaunchMintResponse",
    "LaunchPeerCredentials",
    "LaunchRedemptionContext",
    "LaunchRedemptionEvent",
    "LaunchRedemptionGrant",
    "LaunchRedemptionRequest",
    "LaunchRedemptionResponse",
    "dispatch_launch_redemption_socket",
    "handle_authority_bytes",
    "handle_mint_payload",
    "handle_redemption_bytes",
    "handle_redemption_payload",
    "mint_launch_via_socket",
    "mint_request_payload",
    "mint_response_payload",
    "parse_mint_request",
    "parse_mint_response",
    "parse_redemption_request",
    "parse_redemption_response",
    "redeem_launch_via_socket",
    "redemption_event_payload",
    "redemption_request_payload",
    "redemption_response_payload",
]
