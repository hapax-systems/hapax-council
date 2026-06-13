"""Platform session contract v1 helpers.

The trainyard consumes this contract vocabulary only. Platform-native stream
shapes stay below adapter boundaries and are normalized here before a session is
considered visible on the coordination plane.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class PlatformSessionContractError(ValueError):
    """Raised when native or contract events fail the v1 contract."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LifecycleState(StrEnum):
    SPAWN = "spawn"
    ANNOUNCE = "announce"
    IDENTIFY = "identify"
    CLAIM = "claim"
    WORK = "work"
    YIELD = "yield"
    PARK = "park"
    RESUME = "resume"
    CLOSE = "close"


class SessionEventKind(StrEnum):
    TOOL_CALL = "tool_call"
    FILE_WRITE = "file_write"
    CLAIM = "claim"
    PUSH = "push"
    DOSSIER_WRITE = "dossier_write"
    TASK_MENTION = "task_mention"
    STATUS = "status"
    ERROR = "error"
    HEARTBEAT = "heartbeat"


class ControlVerb(StrEnum):
    CONTEXT_INJECT = "context_inject"
    INTERRUPT = "interrupt"
    ACK = "ack"
    TAKE_CONTROLS = "take_controls"
    RELEASE_CONTROLS = "release_controls"


CONTRACT_EVENT_KINDS: tuple[str, ...] = tuple(kind.value for kind in SessionEventKind)
_LIFECYCLE_STATES: tuple[str, ...] = tuple(state.value for state in LifecycleState)

_CONTROL_ENVELOPE_KEY = "hapax_platform_session_control_v1"
_CODEX_CONTROL_MARKER = "HAPAX_PLATFORM_SESSION_CONTROL_V1"
_TASK_ID_RE = re.compile(r"\b[A-Za-z0-9][A-Za-z0-9_.:-]*-[0-9]{8,}\b")
_FILE_WRITE_TOOLS = frozenset(
    {
        "Edit",
        "MultiEdit",
        "NotebookEdit",
        "Write",
        "apply_patch",
        "codex.apply_patch",
        "file_write",
    }
)


class PlatformSessionEvent(StrictModel):
    """The only event shape the trainyard may consume."""

    ts: datetime
    session_id: str = Field(min_length=1)
    kind: SessionEventKind
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ts")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def to_json_line(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True) + "\n"


class ControlMessage(StrictModel):
    ts: datetime
    session_id: str = Field(min_length=1)
    verb: ControlVerb
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ts")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class SessionIdentity(StrictModel):
    adapter: str
    session_name: str
    session_id: str
    slot: str | None = None
    claim_key: str


class AdapterShim(StrictModel):
    divergence: str
    native_surface: str
    contract_surface: str
    shim: str
    test_id: str


class AdapterContract(StrictModel):
    adapter: Literal["adapter-claude", "adapter-codex"]
    platform: Literal["claude", "codex"]
    lifecycle_source: str
    output_format: str
    control_transport: str
    role_resolution: str
    dispatch_flags: tuple[str, ...]
    shims: tuple[AdapterShim, ...]


class AdapterArtifacts(StrictModel):
    adapter: str
    session_name: str
    claim_file: str
    output_stream: str | None
    control_endpoint: str
    pid_file: str | None
    native_input_format: str
    native_output_format: str


class ConformanceResult(StrictModel):
    adapter: str
    checks: dict[str, bool]
    projection: dict[str, Any]
    event_count: int

    @property
    def ok(self) -> bool:
        return all(self.checks.values())


_ADAPTERS: dict[str, AdapterContract] = {
    "adapter-claude": AdapterContract(
        adapter="adapter-claude",
        platform="claude",
        lifecycle_source="hapax-claude-headless birth artifacts plus session.announced ledger event",
        output_format="claude stream-json normalized to contract JSONL",
        control_transport="FIFO carrying Claude stdin-json user messages",
        role_resolution="HAPAX_AGENT_NAME/CLAUDE_ROLE role, HAPAX_SESSION_ID session uuid",
        dispatch_flags=(
            "--input-format stream-json",
            "--output-format stream-json",
            "--dangerously-skip-permissions",
        ),
        shims=(
            AdapterShim(
                divergence="control_transport",
                native_surface="lane FIFO receives Claude stdin-json",
                contract_surface="ControlMessage verb+payload",
                shim="render_control_message(adapter-claude, ...) wraps the control envelope as a Claude stream-json user message",
                test_id="test_control_roundtrip_for_claude_fifo_stdin_json",
            ),
            AdapterShim(
                divergence="role_resolution",
                native_surface="greek role + per-spawn HAPAX_SESSION_ID",
                contract_surface="SessionIdentity(session_name, session_id, claim_key)",
                shim="resolve_identity(adapter-claude, env) prefers HAPAX_AGENT_NAME then CLAUDE_ROLE",
                test_id="test_role_resolution_shims_cover_claude_and_codex",
            ),
            AdapterShim(
                divergence="output_format",
                native_surface="Claude Code stream-json messages",
                contract_surface="{ts, session_id, kind, payload} JSONL with closed kind enum",
                shim="normalize_native_event(adapter-claude, ...) maps tool_use/result/error lines",
                test_id="test_claude_headless_fixture_passes_contract_conformance",
            ),
        ),
    ),
    "adapter-codex": AdapterContract(
        adapter="adapter-codex",
        platform="codex",
        lifecycle_source="hapax-codex session identity, claim file, bootstrap/runner artifacts, and session.announced ledger event",
        output_format="Codex --json JSONL or interactive session projection normalized to contract JSONL",
        control_transport="tmux buffer text for interactive Codex; codex exec prompt for headless; file-bus inbox fallback for MCP-less control",
        role_resolution="cx-* session name plus Greek slot, HAPAX_SESSION_ID session uuid",
        dispatch_flags=(
            "exec",
            "--json",
            "--cd",
            "--dangerously-bypass-approvals-and-sandbox",
        ),
        shims=(
            AdapterShim(
                divergence="control_transport",
                native_surface="Codex lacks Claude stdin-json; interactive control enters as tmux-buffer text and headless control enters the codex exec prompt",
                contract_surface="ControlMessage verb+payload",
                shim="render_control_message(adapter-codex, ...) emits a marked JSON envelope that hapax-codex-send/file-bus delivery can carry verbatim",
                test_id="test_control_roundtrip_for_codex_text_transport",
            ),
            AdapterShim(
                divergence="role_resolution",
                native_surface="cx-* session identity and separate alpha|beta|delta|epsilon worktree slot",
                contract_surface="SessionIdentity(session_name, session_id, slot, claim_key)",
                shim="resolve_identity(adapter-codex, env) keeps session and slot distinct",
                test_id="test_role_resolution_shims_cover_claude_and_codex",
            ),
            AdapterShim(
                divergence="dispatch_flags",
                native_surface="Codex launcher composes --json/--cd/trust/hooks flags instead of Claude stream-json flags",
                contract_surface="adapter declares its native launch flags without leaking them to the yard",
                shim="adapter_contract(adapter-codex).dispatch_flags is the only place the suite asserts native Codex flags",
                test_id="test_codex_adapter_declares_every_known_divergence_shim",
            ),
            AdapterShim(
                divergence="output_format",
                native_surface="Codex --json JSONL and interactive projection events",
                contract_surface="{ts, session_id, kind, payload} JSONL with closed kind enum",
                shim="normalize_native_event(adapter-codex, ...) maps Codex JSONL/file_write/tool_call/status lines",
                test_id="test_codex_fixture_projects_onto_same_plane_as_claude",
            ),
            AdapterShim(
                divergence="relay_exclusion_visibility",
                native_surface="historical Codex interactive sessions could exist without a rails-plane event stream",
                contract_surface="claim + announce + normalized contract events make the session visible identically to Claude",
                shim="run_conformance_fixture(adapter-codex, ...) requires native artifact rows for spawn/announce/identify/claim projection",
                test_id="test_codex_fixture_passes_contract_conformance",
            ),
        ),
    ),
}


def _unknown_adapter_error(adapter: str) -> PlatformSessionContractError:
    return PlatformSessionContractError(
        "unknown_adapter",
        (
            f"unsupported platform session adapter {adapter!r}; "
            f"supported adapters: {', '.join(sorted(_ADAPTERS))}. "
            "Next action: add an adapter contract before routing this platform."
        ),
    )


def adapter_contract(adapter: str) -> AdapterContract:
    try:
        return _ADAPTERS[adapter]
    except KeyError as exc:
        raise _unknown_adapter_error(adapter) from exc


def adapter_contracts() -> tuple[AdapterContract, ...]:
    return tuple(_ADAPTERS.values())


def validate_contract_event(payload: Mapping[str, Any]) -> PlatformSessionEvent:
    """Validate a contract event and fail honestly on off-vocabulary kinds."""

    kind = payload.get("kind")
    if kind is not None and kind not in CONTRACT_EVENT_KINDS:
        raise PlatformSessionContractError(
            "off_vocabulary_event",
            (
                f"kind {kind!r} is outside platform session contract v1; "
                f"valid kinds: {', '.join(CONTRACT_EVENT_KINDS)}. "
                "Next action: normalize native output to one of those kinds."
            ),
        )
    lifecycle_state = None
    event_payload = payload.get("payload")
    if kind == SessionEventKind.STATUS.value and isinstance(event_payload, Mapping):
        lifecycle_state = event_payload.get("lifecycle_state")
    if lifecycle_state is not None and lifecycle_state not in _LIFECYCLE_STATES:
        raise PlatformSessionContractError(
            "off_vocabulary_lifecycle",
            (
                f"lifecycle_state {lifecycle_state!r} is outside platform session contract v1; "
                f"valid lifecycle states: {', '.join(_LIFECYCLE_STATES)}. "
                "Next action: normalize lifecycle evidence before emitting status."
            ),
        )
    try:
        return PlatformSessionEvent.model_validate(dict(payload))
    except ValidationError as exc:
        raise PlatformSessionContractError(
            "invalid_contract_event",
            f"{exc}. Next action: emit a contract event with ts, session_id, kind, and payload.",
        ) from exc


def parse_jsonl_events(path: Path) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PlatformSessionContractError(
                "invalid_jsonl",
                (
                    f"{path}:{line_no}: {exc.msg}; "
                    "Next action: fix the fixture to contain one JSON object per line"
                ),
            ) from exc
        if not isinstance(value, dict):
            raise PlatformSessionContractError(
                "invalid_jsonl",
                (
                    f"{path}:{line_no}: expected JSON object; "
                    "Next action: wrap primitive values in an object"
                ),
            )
        rows.append(value)
    return tuple(rows)


def normalize_native_events(
    adapter: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    session_id: str,
) -> tuple[PlatformSessionEvent, ...]:
    events: list[PlatformSessionEvent] = []
    for row in rows:
        events.extend(normalize_native_event(adapter, row, session_id=session_id))
    return tuple(events)


def normalize_native_event(
    adapter: str,
    row: Mapping[str, Any],
    *,
    session_id: str,
) -> tuple[PlatformSessionEvent, ...]:
    """Normalize one platform-native event into contract events."""

    adapter_contract(adapter)
    raw = dict(row)
    if {"ts", "session_id", "kind", "payload"}.issubset(raw):
        return (validate_contract_event(raw),)
    if adapter == "adapter-claude":
        return _normalize_claude_event(raw, session_id=session_id)
    if adapter == "adapter-codex":
        return _normalize_codex_event(raw, session_id=session_id)
    raise _unknown_adapter_error(adapter)


def render_control_message(adapter: str, message: ControlMessage) -> dict[str, Any] | str:
    """Render the common control channel into a native adapter input."""

    adapter_contract(adapter)
    envelope = {_CONTROL_ENVELOPE_KEY: message.model_dump(mode="json")}
    encoded = json.dumps(envelope, sort_keys=True)
    if adapter == "adapter-claude":
        return {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": encoded}],
            },
        }
    if adapter == "adapter-codex":
        return f"{_CODEX_CONTROL_MARKER} {encoded}"
    raise _unknown_adapter_error(adapter)


def parse_control_message(adapter: str, native: Mapping[str, Any] | str) -> ControlMessage:
    """Parse an adapter-rendered control message back to the common envelope."""

    adapter_contract(adapter)
    if adapter == "adapter-claude":
        if not isinstance(native, Mapping):
            raise PlatformSessionContractError(
                "invalid_control_message",
                (
                    "expected Claude stdin-json mapping with message.content[0].text. "
                    "Next action: render with render_control_message."
                ),
            )
        native_message = native.get("message")
        message = native_message if isinstance(native_message, Mapping) else {}
        content = message.get("content", [])
        if not isinstance(content, list) or not content or not isinstance(content[0], Mapping):
            raise PlatformSessionContractError(
                "invalid_control_message",
                "missing Claude message.content. Next action: render with render_control_message.",
            )
        text = content[0].get("text", "")
    elif adapter == "adapter-codex":
        if not isinstance(native, str) or not native.startswith(f"{_CODEX_CONTROL_MARKER} "):
            raise PlatformSessionContractError(
                "invalid_control_message",
                (
                    f"missing Codex marker {_CODEX_CONTROL_MARKER}. "
                    "Next action: render with render_control_message."
                ),
            )
        text = native.split(" ", 1)[1]
    else:
        raise _unknown_adapter_error(adapter)
    try:
        envelope = json.loads(text)
        payload = envelope[_CONTROL_ENVELOPE_KEY]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PlatformSessionContractError(
            "invalid_control_message",
            f"{exc}; expected control envelope key {_CONTROL_ENVELOPE_KEY}. Next action: re-render the envelope.",
        ) from exc
    try:
        return ControlMessage.model_validate(payload)
    except ValidationError as exc:
        raise PlatformSessionContractError(
            "invalid_control_message",
            f"{exc}; expected fields ts, session_id, verb, payload. Next action: correct the control payload.",
        ) from exc


def resolve_identity(adapter: str, env: Mapping[str, str]) -> SessionIdentity:
    """Resolve platform-native identity variables into the contract identity."""

    adapter_contract(adapter)
    session_id = env.get("HAPAX_SESSION_ID") or env.get("CLAUDE_CODE_SESSION_ID")
    if not session_id:
        raise PlatformSessionContractError(
            "missing_session_id",
            (
                "HAPAX_SESSION_ID or CLAUDE_CODE_SESSION_ID required in launcher environment. "
                "Next action: export one before adapter startup."
            ),
        )
    if adapter == "adapter-claude":
        role = env.get("HAPAX_AGENT_NAME") or env.get("CLAUDE_ROLE") or env.get("HAPAX_AGENT_ROLE")
        if not role:
            raise PlatformSessionContractError(
                "missing_session_name",
                (
                    "Claude identity requires HAPAX_AGENT_NAME, CLAUDE_ROLE, or HAPAX_AGENT_ROLE. "
                    "Next action: launch through hapax-claude-headless."
                ),
            )
        return SessionIdentity(
            adapter=adapter,
            session_name=role,
            session_id=session_id,
            slot=role,
            claim_key=f"cc-active-task-{role}",
        )
    if adapter == "adapter-codex":
        session = (
            env.get("HAPAX_AGENT_NAME") or env.get("CODEX_THREAD_NAME") or env.get("CODEX_ROLE")
        )
        if not session:
            raise PlatformSessionContractError(
                "missing_session_name",
                (
                    "Codex identity requires HAPAX_AGENT_NAME, CODEX_THREAD_NAME, or CODEX_ROLE. "
                    "Next action: launch through hapax-codex or hapax-codex-headless."
                ),
            )
        return SessionIdentity(
            adapter=adapter,
            session_name=session,
            session_id=session_id,
            slot=env.get("HAPAX_AGENT_SLOT") or env.get("HAPAX_WORKTREE_ROLE"),
            claim_key=f"cc-active-task-{session}",
        )
    raise _unknown_adapter_error(adapter)


def adapter_artifacts(
    adapter: str,
    session_name: str,
    *,
    home: Path,
    runtime_dir: Path = Path("/run/user/1000"),
    mode: Literal["interactive", "headless"] = "headless",
) -> AdapterArtifacts:
    """Return the adapter's current native artifact layout."""

    adapter_contract(adapter)
    cache = home / ".cache" / "hapax"
    if adapter == "adapter-claude":
        pipe_dir = runtime_dir / "hapax-claude"
        return AdapterArtifacts(
            adapter=adapter,
            session_name=session_name,
            claim_file=str(cache / f"cc-active-task-{session_name}"),
            output_stream=str(cache / "claude-headless" / session_name / "output.jsonl"),
            control_endpoint=str(pipe_dir / f"{session_name}.stdin"),
            pid_file=str(pipe_dir / f"{session_name}.pid"),
            native_input_format="Claude stdin-json over FIFO",
            native_output_format="Claude stream-json",
        )
    if adapter == "adapter-codex":
        if mode == "interactive":
            return AdapterArtifacts(
                adapter=adapter,
                session_name=session_name,
                claim_file=str(cache / f"cc-active-task-{session_name}"),
                output_stream=None,
                control_endpoint=f"tmux:hapax-codex-{session_name}",
                pid_file=None,
                native_input_format="tmux buffer text via hapax-codex-send",
                native_output_format="session projection events plus optional transcript capture",
            )
        return AdapterArtifacts(
            adapter=adapter,
            session_name=session_name,
            claim_file=str(cache / f"cc-active-task-{session_name}"),
            output_stream=str(cache / "codex-headless" / session_name / "output.jsonl"),
            control_endpoint="codex exec prompt / file-bus inbox fallback",
            pid_file=str(runtime_dir / "hapax-codex" / f"{session_name}.pid"),
            native_input_format="Codex exec prompt text",
            native_output_format="Codex --json JSONL",
        )
    raise _unknown_adapter_error(adapter)


def artifact_projection_rows(
    adapter: str,
    artifacts: AdapterArtifacts,
    *,
    task_id: str,
    require_observed: bool = True,
    observed_control_endpoints: Collection[str] = (),
) -> tuple[dict[str, Any], ...]:
    """Project launcher artifacts into adapter-native evidence rows."""

    adapter_contract(adapter)
    if require_observed:
        _require_observed_artifacts(
            artifacts,
            task_id=task_id,
            observed_control_endpoints=observed_control_endpoints,
        )
    lifecycle_base = {
        "type": "hapax_lifecycle",
        "source": artifacts.adapter,
        "task_id": task_id,
        "claim_file": artifacts.claim_file,
        "control_endpoint": artifacts.control_endpoint,
    }
    if artifacts.output_stream:
        lifecycle_base["output_stream"] = artifacts.output_stream
    return (
        {**lifecycle_base, "state": LifecycleState.SPAWN.value},
        {
            **lifecycle_base,
            "state": LifecycleState.ANNOUNCE.value,
            "event_type": "session.announced",
        },
        {
            "type": "hapax_claim",
            "source": "claim_file",
            "claim_file": artifacts.claim_file,
            "task_id": task_id,
        },
    )


def _require_observed_artifacts(
    artifacts: AdapterArtifacts,
    *,
    task_id: str,
    observed_control_endpoints: Collection[str],
) -> None:
    claim_path = Path(artifacts.claim_file)
    if not claim_path.is_file():
        raise PlatformSessionContractError(
            "artifact_not_observed",
            f"claim file not observed: {claim_path}. Next action: wait for cc-claim before projection.",
        )
    claimed = claim_path.read_text(encoding="utf-8").strip()
    if claimed != task_id:
        raise PlatformSessionContractError(
            "artifact_not_observed",
            (
                f"claim file {claim_path} contains {claimed!r}, expected {task_id!r}. "
                "Next action: project only the active task claim."
            ),
        )
    if artifacts.output_stream and not Path(artifacts.output_stream).is_file():
        raise PlatformSessionContractError(
            "artifact_not_observed",
            (
                f"output stream not observed: {artifacts.output_stream}. "
                "Next action: wait for the launcher output file before projection."
            ),
        )
    endpoint = artifacts.control_endpoint
    if endpoint.startswith("/"):
        endpoint_path = Path(endpoint)
        if not endpoint_path.exists():
            raise PlatformSessionContractError(
                "artifact_not_observed",
                (
                    f"control endpoint not observed: {endpoint_path}. "
                    "Next action: wait for the launcher control endpoint before projection."
                ),
            )
    elif endpoint.startswith("tmux:") and endpoint not in observed_control_endpoints:
        raise PlatformSessionContractError(
            "artifact_not_observed",
            (
                f"tmux control endpoint not observed: {endpoint}. "
                "Next action: verify the tmux session before projection."
            ),
        )


def lifecycle_event(
    *,
    session_id: str,
    state: LifecycleState,
    ts: datetime,
    payload: Mapping[str, Any] | None = None,
) -> PlatformSessionEvent:
    merged = {"lifecycle_state": state.value}
    if payload:
        merged.update(dict(payload))
    return PlatformSessionEvent(
        ts=ts,
        session_id=session_id,
        kind=SessionEventKind.STATUS,
        payload=merged,
    )


def coordination_plane_projection(
    events: Sequence[PlatformSessionEvent],
) -> dict[str, Any]:
    """Fold contract events into the minimal visibility facts the trainyard needs."""

    lifecycle = {
        str(event.payload.get("lifecycle_state"))
        for event in events
        if event.kind == SessionEventKind.STATUS and event.payload.get("lifecycle_state")
    }
    claimed_task_ids = {
        str(event.payload.get("task_id"))
        for event in events
        if event.kind == SessionEventKind.CLAIM and event.payload.get("task_id")
    }
    mentioned_task_ids = {
        str(event.payload.get("task_id"))
        for event in events
        if event.kind == SessionEventKind.TASK_MENTION and event.payload.get("task_id")
    }
    file_paths = sorted(
        {
            str(event.payload.get("path") or event.payload.get("file_path"))
            for event in events
            if event.kind == SessionEventKind.FILE_WRITE
            and (event.payload.get("path") or event.payload.get("file_path"))
        }
    )
    return {
        "spawned": LifecycleState.SPAWN.value in lifecycle,
        "announced": LifecycleState.ANNOUNCE.value in lifecycle,
        "identified": LifecycleState.IDENTIFY.value in lifecycle,
        "claimed_tasks": sorted(claimed_task_ids),
        "mentioned_tasks": sorted(mentioned_task_ids),
        "event_kinds": sorted({event.kind.value for event in events}),
        "file_paths": file_paths,
    }


def run_conformance_fixture(
    adapter: str,
    native_rows: Iterable[Mapping[str, Any]],
    *,
    session_id: str,
    task_id: str,
    ts: datetime | None = None,
) -> ConformanceResult:
    """Run the v1 fixture suite checks for one adapter."""

    checked_at = ts or datetime.now(UTC)
    rows = tuple(native_rows)
    events = normalize_native_events(adapter, rows, session_id=session_id)
    projection = coordination_plane_projection(events)
    control = ControlMessage(
        ts=checked_at,
        session_id=session_id,
        verb=ControlVerb.ACK,
        payload={"task_id": task_id},
    )
    rendered = render_control_message(adapter, control)
    parsed = parse_control_message(adapter, rendered)
    checks = {
        "spawn_announce": _artifact_lifecycle_evidence_visible(events),
        "identity_visible": projection["identified"],
        "event_vocabulary": _raw_and_normalized_vocabulary_is_closed(rows, events),
        "control_roundtrip": parsed == control,
        "claim_visible": _claim_file_evidence_visible(events, task_id),
    }
    result = ConformanceResult(
        adapter=adapter,
        checks=checks,
        projection=projection,
        event_count=len(events),
    )
    if not result.ok:
        failed = ", ".join(name for name, ok in checks.items() if not ok)
        raise PlatformSessionContractError(
            "conformance_failed",
            (
                f"failed checks: {failed}. "
                "Next action: rerun the adapter fixture and inspect projection."
            ),
        )
    return result


def _normalize_claude_event(
    raw: Mapping[str, Any],
    *,
    session_id: str,
) -> tuple[PlatformSessionEvent, ...]:
    ts = _event_ts(raw)
    native_type = str(raw.get("type") or raw.get("event") or "unknown")
    events: list[PlatformSessionEvent] = []

    if native_type == "hapax_lifecycle":
        return _normalize_lifecycle_artifact(raw, session_id=session_id, adapter="adapter-claude")
    if native_type == "hapax_claim":
        return (_claim_event(ts, session_id, raw),)
    if native_type == "system" and raw.get("subtype") == "init":
        return (
            _event(
                ts,
                session_id,
                SessionEventKind.STATUS,
                {"lifecycle_state": LifecycleState.IDENTIFY.value, "native_type": native_type},
            ),
        )
    if native_type == "result":
        return (
            _event(
                ts,
                session_id,
                SessionEventKind.STATUS,
                {"native_type": native_type, "subtype": raw.get("subtype")},
            ),
        )
    if native_type == "error":
        return (_event(ts, session_id, SessionEventKind.ERROR, {"message": raw.get("message")}),)

    message = raw.get("message") if isinstance(raw.get("message"), Mapping) else {}
    content = message.get("content", []) if isinstance(message, Mapping) else []
    for item in content if isinstance(content, list) else []:
        if not isinstance(item, Mapping):
            continue
        if item.get("type") == "tool_use":
            tool_name = str(item.get("name") or "unknown")
            tool_payload = dict(item.get("input") or {})
            events.append(
                _event(
                    ts,
                    session_id,
                    SessionEventKind.TOOL_CALL,
                    {"tool": tool_name, "input": tool_payload},
                )
            )
            path = _extract_file_path(tool_payload)
            if tool_name in _FILE_WRITE_TOOLS and path:
                events.append(
                    _event(
                        ts,
                        session_id,
                        SessionEventKind.FILE_WRITE,
                        {"tool": tool_name, "path": path},
                    )
                )
        elif item.get("type") == "text":
            task_id = _extract_task_id(str(item.get("text") or ""))
            if task_id:
                events.append(
                    _event(ts, session_id, SessionEventKind.TASK_MENTION, {"task_id": task_id})
                )
    if events:
        return tuple(events)
    return (
        _event(
            ts,
            session_id,
            SessionEventKind.ERROR,
            {"code": "native_event_unmapped", "native_type": native_type},
        ),
    )


def _normalize_codex_event(
    raw: Mapping[str, Any],
    *,
    session_id: str,
) -> tuple[PlatformSessionEvent, ...]:
    ts = _event_ts(raw)
    native_type = str(raw.get("type") or raw.get("event") or "unknown")

    if native_type == "hapax_lifecycle":
        return _normalize_lifecycle_artifact(raw, session_id=session_id, adapter="adapter-codex")
    if native_type == "hapax_claim":
        return (_claim_event(ts, session_id, raw),)
    if native_type in {"session_configured", "thread.started"}:
        return (
            _event(
                ts,
                session_id,
                SessionEventKind.STATUS,
                {"lifecycle_state": LifecycleState.IDENTIFY.value, "native_type": native_type},
            ),
        )
    if native_type in {"task_started", "turn.started"}:
        return (
            _event(
                ts,
                session_id,
                SessionEventKind.STATUS,
                {"lifecycle_state": LifecycleState.WORK.value, "native_type": native_type},
            ),
        )
    if native_type == "claim":
        return (_claim_event(ts, session_id, raw),)
    if native_type == "tool_call":
        tool = str(raw.get("tool") or raw.get("name") or "unknown")
        args = raw.get("arguments") if isinstance(raw.get("arguments"), Mapping) else {}
        events = [
            _event(
                ts,
                session_id,
                SessionEventKind.TOOL_CALL,
                {"tool": tool, "arguments": dict(args)},
            )
        ]
        paths = _extract_paths(args)
        if tool in _FILE_WRITE_TOOLS:
            events.extend(
                _event(ts, session_id, SessionEventKind.FILE_WRITE, {"tool": tool, "path": path})
                for path in paths
            )
        return tuple(events)
    if native_type == "file_write":
        return (
            _event(
                ts,
                session_id,
                SessionEventKind.FILE_WRITE,
                {"path": raw.get("path") or raw.get("file_path")},
            ),
        )
    if native_type == "push":
        return (_event(ts, session_id, SessionEventKind.PUSH, {"remote": raw.get("remote")}),)
    if native_type == "status":
        return (
            _event(
                ts,
                session_id,
                SessionEventKind.STATUS,
                dict(raw.get("payload") or {"status": raw.get("status")}),
            ),
        )
    if native_type == "error":
        return (_event(ts, session_id, SessionEventKind.ERROR, {"message": raw.get("message")}),)
    return (
        _event(
            ts,
            session_id,
            SessionEventKind.ERROR,
            {"code": "native_event_unmapped", "native_type": native_type},
        ),
    )


def _normalize_lifecycle_artifact(
    raw: Mapping[str, Any],
    *,
    session_id: str,
    adapter: str,
) -> tuple[PlatformSessionEvent, ...]:
    ts = _event_ts(raw)
    state = raw.get("state") or raw.get("lifecycle_state")
    if state not in _LIFECYCLE_STATES:
        return (
            _event(
                ts,
                session_id,
                SessionEventKind.ERROR,
                {"code": "invalid_lifecycle_state", "lifecycle_state": state, "adapter": adapter},
            ),
        )
    payload = {
        "adapter": adapter,
        "native_type": "hapax_lifecycle",
        "source": raw.get("source"),
    }
    for key in ("event_type", "task_id", "claim_file", "output_stream", "control_endpoint"):
        if raw.get(key):
            payload[key] = raw[key]
    return (
        lifecycle_event(
            session_id=session_id,
            state=LifecycleState(str(state)),
            ts=ts,
            payload=payload,
        ),
    )


def _event_ts(raw: Mapping[str, Any]) -> datetime:
    value = raw.get("ts") or raw.get("timestamp")
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    return datetime.now(UTC)


def _event(
    ts: datetime,
    session_id: str,
    kind: SessionEventKind,
    payload: Mapping[str, Any],
) -> PlatformSessionEvent:
    return validate_contract_event(
        {
            "ts": ts,
            "session_id": session_id,
            "kind": kind.value,
            "payload": dict(payload),
        }
    )


def _claim_event(
    ts: datetime,
    session_id: str,
    raw: Mapping[str, Any],
) -> PlatformSessionEvent:
    payload = {"task_id": raw.get("task_id")}
    for key in ("source", "claim_file"):
        if raw.get(key):
            payload[key] = raw[key]
    return _event(ts, session_id, SessionEventKind.CLAIM, payload)


def _extract_file_path(payload: Mapping[str, Any]) -> str | None:
    for key in ("file_path", "path", "target_file"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_paths(payload: Mapping[str, Any]) -> tuple[str, ...]:
    path = _extract_file_path(payload)
    if path:
        return (path,)
    files = payload.get("files")
    if isinstance(files, list):
        return tuple(str(item) for item in files if item)
    return ()


def _extract_task_id(text: str) -> str | None:
    match = _TASK_ID_RE.search(text)
    return match.group(0) if match else None


def _raw_and_normalized_vocabulary_is_closed(
    rows: Sequence[Mapping[str, Any]],
    events: Sequence[PlatformSessionEvent],
) -> bool:
    raw_contract_kinds = (
        row.get("kind") for row in rows if {"ts", "session_id", "kind", "payload"}.issubset(row)
    )
    return all(kind in CONTRACT_EVENT_KINDS for kind in raw_contract_kinds) and all(
        event.kind.value in CONTRACT_EVENT_KINDS for event in events
    )


def _artifact_lifecycle_evidence_visible(events: Sequence[PlatformSessionEvent]) -> bool:
    states = {
        str(event.payload.get("lifecycle_state"))
        for event in events
        if event.kind == SessionEventKind.STATUS
        and event.payload.get("native_type") == "hapax_lifecycle"
        and (event.payload.get("output_stream") or event.payload.get("control_endpoint"))
    }
    return LifecycleState.SPAWN.value in states and LifecycleState.ANNOUNCE.value in states


def _claim_file_evidence_visible(events: Sequence[PlatformSessionEvent], task_id: str) -> bool:
    return any(
        event.kind == SessionEventKind.CLAIM
        and event.payload.get("task_id") == task_id
        and event.payload.get("source") == "claim_file"
        and bool(event.payload.get("claim_file"))
        for event in events
    )
