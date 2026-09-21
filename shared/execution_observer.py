"""CapabilityExecutionInvariant — observed-execution observer (CEI SLICE 4).

Extracts what model(s) actually ran in a Claude Code session from its transcript, plus
any silent ``model_refusal_fallback`` remaps (e.g. claude-fable-5 -> claude-opus-4-8).
This is the OBSERVED half of ``observed ⊆ sanctioned`` — consumed by the close-gate and
by the Yard Crow's recomposition attestation.

The client transcript is not provider-side truth (``endpoint_attested`` is False here);
a provider gateway / usage API is the authenticated source. But the transcript is where
Claude Code's own refusal-fallback events surface, so it is the drift signal we have.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def observe_native_lifecycle(
    path: Path,
    *,
    platform: str,
    offset: int = 0,
    process_returncode: int | None = None,
    cancellation_requested: bool = False,
    expected_resume_id: str | None = None,
) -> dict[str, Any]:
    """Translate native stream events; never promote launcher exit to completion.

    `offset` must be captured before this launch, since lane output files append
    across sessions. `process_returncode` is supplied only after waiting for the
    owned native process (not an interactive launcher or remote SSH transport).
    Readiness of instructions/services remains separately unobserved. This is
    support evidence, not task acceptance or a provider-side attestation.
    """
    result: dict[str, Any] = {
        "platform": platform,
        "phase": "unobserved",
        "session_id": None,
        "session_identity": "unobserved",
        "readiness": "unobserved",
        "complete": False,
        "cancel_requested": cancellation_requested,
        "cancel_confirmed": False,
        "resume": "unobserved",
        "process_returncode": process_returncode,
        "evidence": [],
        "malformed_lines": 0,
        "may_authorize": False,
    }
    if platform not in {"claude", "codex"}:
        result["reason"] = "native_lifecycle_mapping_unimplemented"
        return result
    if offset < 0:
        raise ValueError("native stream offset must be nonnegative")
    try:
        with path.open("rb") as stream:
            if stream.seek(0, 2) < offset:
                result["reason"] = "native_stream_truncated"
                return result
            stream.seek(offset)
            lines = stream.readlines()
    except OSError:
        result["reason"] = "native_stream_unavailable"
        return result
    terminal_success = False
    native_failed = False
    session_ids: set[str] = set()
    for number, line in enumerate(lines):
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            result["malformed_lines"] += 1
            continue
        if not isinstance(event, dict):
            result["malformed_lines"] += 1
            continue
        kind = event.get("type")
        phase = None
        session_id = None
        if platform == "codex":
            if kind == "thread.started":
                session_id = event.get("thread_id")
                phase = "initialized"
            elif kind in {"turn.started", "item.started", "item.updated", "item.completed"}:
                phase = "running"
            elif kind == "turn.completed":
                phase, terminal_success = "turn_complete", True
            elif kind in {"turn.failed", "error"}:
                phase, native_failed = "failed", True
        else:
            if kind == "system" and event.get("subtype") == "init":
                session_id = event.get("session_id")
                phase = "initialized"
            elif kind in {"assistant", "stream_event"}:
                phase = "running"
            elif kind == "result":
                terminal_success = event.get("subtype") == "success" and not event.get("is_error")
                native_failed = not terminal_success
                phase = "turn_complete" if terminal_success else "failed"
        if phase:
            if phase in {"initialized", "running"}:
                terminal_success = False
            result["phase"] = phase
            result["evidence"].append({"offset": offset, "line": number + 1, "type": kind})
        if isinstance(session_id, str) and session_id:
            session_ids.add(session_id)
            result["session_id"] = session_id
    result["session_identity"] = (
        "single_native_session"
        if len(session_ids) == 1
        else "ambiguous"
        if session_ids
        else "unobserved"
    )
    if expected_resume_id is not None:
        result["resume"] = (
            "unobserved"
            if len(session_ids) != 1
            else "same_native_session"
            if result["session_id"] == expected_resume_id
            else "session_mismatch"
        )
    # subprocess wait's negative signal return code witnesses termination. An
    # arbitrary positive failure after a cancel request does not prove cancellation.
    if cancellation_requested and process_returncode is not None and process_returncode < 0:
        result["cancel_confirmed"] = True
        result["phase"] = "cancelled"
    elif process_returncode is not None:
        result["complete"] = (
            process_returncode == 0
            and terminal_success
            and not native_failed
            and len(session_ids) == 1
            and result["malformed_lines"] == 0
            and result["resume"] != "session_mismatch"
        )
        result["phase"] = (
            "complete"
            if result["complete"]
            else "failed"
            if process_returncode
            else "exited_unverified"
        )
    return result


@dataclass(frozen=True)
class FallbackEvent:
    """A ``type:system / subtype:model_refusal_fallback`` record: the runtime silently
    retried on a different model. ``to_model`` != ``from_model`` is an execution drift."""

    from_model: str
    to_model: str
    trigger: str | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class ObservedExecution:
    """The observed execution set of a session: every model that actually ran + every
    silent fallback. ``models`` with >1 member, or any ``fallback_events``, is drift."""

    models: frozenset[str] = frozenset()
    fallback_events: tuple[FallbackEvent, ...] = ()
    turn_count: int = 0
    source_path: str = ""
    #: The client transcript is NOT provider-side attestation; a gateway/usage API is.
    endpoint_attested: bool = False
    #: Lines that could not be parsed as JSON (a corrupt/truncated transcript is common).
    malformed_lines: int = 0

    @property
    def drifted(self) -> bool:
        """True when execution left a single sanctioned model: >1 model observed, or any
        silent fallback occurred."""
        return len(self.models) > 1 or bool(self.fallback_events)


def _model_of_assistant_turn(record: dict) -> str | None:
    """The served model of an assistant turn, if present. Claude Code stores it at
    ``message.model`` on ``type:"assistant"`` records."""
    if record.get("type") != "assistant":
        return None
    message = record.get("message")
    if isinstance(message, dict):
        model = message.get("model")
        # Skip placeholder pseudo-models (e.g. "<synthetic>" on hook/tool-injected turns):
        # they are not a served model identity and must not register as execution drift.
        if isinstance(model, str) and model and not model.startswith("<"):
            return model
    return None


def _fallback_of_record(record: dict) -> FallbackEvent | None:
    """A ``model_refusal_fallback`` system event, if this record is one."""
    if record.get("type") != "system" or record.get("subtype") != "model_refusal_fallback":
        return None
    frm = record.get("originalModel") or record.get("from_model")
    to = record.get("fallbackModel") or record.get("to_model")
    if not isinstance(frm, str) or not isinstance(to, str) or not frm or not to:
        return None
    return FallbackEvent(
        from_model=frm,
        to_model=to,
        trigger=record.get("trigger") if isinstance(record.get("trigger"), str) else None,
        request_id=record.get("requestId") if isinstance(record.get("requestId"), str) else None,
    )


def observe_claude_transcript(path: str | Path) -> ObservedExecution:
    """Parse a Claude Code session transcript (JSONL) into its :class:`ObservedExecution`.

    Fail-safe: a missing file yields an empty observation; malformed lines are counted and
    skipped, never raised. The result's ``models`` includes the model of each assistant turn
    AND BOTH ends of every fallback — the ``to_model`` that served the retry and the
    ``from_model`` that was invoked (it produced the refusal that triggered the remap).
    Including ``from_model`` is load-bearing: omitting it fails open when an unsanctioned
    source remaps to a sanctioned target with no assistant turn of its own.
    """
    p = Path(path)
    models: set[str] = set()
    fallbacks: list[FallbackEvent] = []
    turns = 0
    malformed = 0

    try:
        if not p.is_file():
            return ObservedExecution(source_path=str(p))

        with p.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (ValueError, TypeError):
                    malformed += 1
                    continue
                if not isinstance(record, dict):
                    continue
                model = _model_of_assistant_turn(record)
                if model is not None:
                    models.add(model)
                    turns += 1
                fallback = _fallback_of_record(record)
                if fallback is not None:
                    fallbacks.append(fallback)
                    # BOTH ends of a fallback actually ran and are part of the observed set: the
                    # target served the retried turn, and the SOURCE was invoked with session
                    # content — it produced the refusal that triggered the remap. Omitting
                    # from_model fails open: an unsanctioned source that remapped to a sanctioned
                    # target (with no assistant turn of its own) would otherwise pass the invariant.
                    models.add(fallback.from_model)
                    models.add(fallback.to_model)
    except OSError:
        return ObservedExecution(source_path=str(p))

    return ObservedExecution(
        models=frozenset(models),
        fallback_events=tuple(fallbacks),
        turn_count=turns,
        source_path=str(p),
        malformed_lines=malformed,
    )


def _model_of_codex_turn(record: dict) -> str | None:
    """The model of a Codex rollout ``turn_context`` record: ``payload.model``."""
    if record.get("type") != "turn_context":
        return None
    payload = record.get("payload")
    if isinstance(payload, dict):
        model = payload.get("model")
        if isinstance(model, str) and model and not model.startswith("<"):
            return model
    return None


def observe_codex_rollout(path: str | Path) -> ObservedExecution:
    """Parse a Codex session rollout (``~/.codex/sessions/.../rollout-*.jsonl``) into its
    :class:`ObservedExecution`. Codex records the served model per turn on the
    ``turn_context`` record's ``payload.model``. Codex has no ``model_refusal_fallback``
    (that is Claude-specific), so drift here surfaces as >1 model in the observed set (a
    silent model change across the session). Same fail-safe contract as the Claude observer.
    """
    p = Path(path)
    models: set[str] = set()
    turns = 0
    malformed = 0

    try:
        if not p.is_file():
            return ObservedExecution(source_path=str(p))

        with p.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (ValueError, TypeError):
                    malformed += 1
                    continue
                if not isinstance(record, dict):
                    continue
                model = _model_of_codex_turn(record)
                if model is not None:
                    models.add(model)
                    turns += 1
    except OSError:
        return ObservedExecution(source_path=str(p))

    return ObservedExecution(
        models=frozenset(models),
        turn_count=turns,
        source_path=str(p),
        malformed_lines=malformed,
    )


#: The five CEI terminal states (capability-execution-invariant-spec §terminal states).
EXECUTION_INVARIANT_SATISFIED = "execution_invariant_satisfied"
EXECUTION_OBSERVATION_MISSING = "execution_observation_missing"
EXECUTION_DRIFT_OBSERVED = "execution_drift_observed"
UNSANCTIONED_FALLBACK_OBSERVED = "unsanctioned_fallback_observed"
UNSUPPORTED_EXECUTION_OBSERVER = "unsupported_execution_observer"


@dataclass(frozen=True)
class ExecutionInvariantVerdict:
    """The verdict of ``observed ⊆ sanctioned``. Only ``execution_invariant_satisfied`` is
    admissible — every other state fails closed (governed use must not proceed / a work
    product is tainted) until a reauthorization receipt sanctions the observed execution."""

    status: str
    observed_models: frozenset[str] = frozenset()
    sanctioned_models: frozenset[str] = frozenset()
    unsanctioned_models: frozenset[str] = frozenset()
    unsanctioned_fallbacks: tuple[FallbackEvent, ...] = ()

    @property
    def admissible(self) -> bool:
        return self.status == EXECUTION_INVARIANT_SATISFIED


def check_execution_invariant(
    observed: ObservedExecution, sanctioned: frozenset[str] | set[str] | tuple[str, ...]
) -> ExecutionInvariantVerdict:
    """Evaluate ``observed ⊆ sanctioned`` into one of the five CEI terminal states.

    Fail-closed precedence: MISSING (nothing observed — cannot attest) > UNSANCTIONED
    FALLBACK (a silent remap served an unsanctioned model) > DRIFT (an unsanctioned model
    ran without a recorded fallback) > SATISFIED. An empty ``sanctioned`` set means nothing
    is sanctioned, so any observed model is drift (fail-closed)."""
    sanctioned_set = frozenset(sanctioned)
    unsanctioned_models = frozenset(observed.models - sanctioned_set)
    # A fallback is unsanctioned if EITHER end left the sanctioned set: the target served a
    # turn, and the source was invoked (it produced the refusal). Checking only to_model
    # fails open on an unsanctioned source that remapped to a sanctioned target.
    unsanctioned_fallbacks = tuple(
        event
        for event in observed.fallback_events
        if event.to_model not in sanctioned_set or event.from_model not in sanctioned_set
    )

    if not observed.models and observed.turn_count == 0:
        status = EXECUTION_OBSERVATION_MISSING
    elif unsanctioned_fallbacks:
        status = UNSANCTIONED_FALLBACK_OBSERVED
    elif unsanctioned_models:
        status = EXECUTION_DRIFT_OBSERVED
    else:
        status = EXECUTION_INVARIANT_SATISFIED

    return ExecutionInvariantVerdict(
        status=status,
        observed_models=observed.models,
        sanctioned_models=sanctioned_set,
        unsanctioned_models=unsanctioned_models,
        unsanctioned_fallbacks=unsanctioned_fallbacks,
    )


def _native_receipt_main() -> int:
    import argparse
    import hashlib
    import socket

    parser = argparse.ArgumentParser(description="Observe an owned native headless process exit")
    parser.add_argument("--stream", type=Path, required=True)
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--returncode", type=int, required=True)
    parser.add_argument("--local-child", action="store_true")
    parser.add_argument("--cancel-signal", type=int, default=0)
    parser.add_argument("--execution-descriptor")
    parser.add_argument("--execution-route")
    parser.add_argument("--native-home", type=Path)
    parser.add_argument("--workdir", type=Path)
    parser.add_argument("--launch-started-at")
    args = parser.parse_args()
    # Bash wait conflates signal termination with an explicit exit(128+signal).
    # Do not manufacture a negative subprocess wait witness from that value.
    observed = observe_native_lifecycle(
        args.stream,
        platform="codex",
        process_returncode=args.returncode if args.local_child else None,
        cancellation_requested=bool(args.cancel_signal),
    )
    observed.update(
        {
            "receipt_path": str(args.receipt),
            "stream_path": str(args.stream),
            "stream_sha256": hashlib.sha256(args.stream.read_bytes()).hexdigest(),
            "diagnostics_path": str(args.diagnostics),
            "observer_host": socket.gethostname(),
            "owned_native_process": args.local_child,
            "wait_status_kind": "shell_wait",
            "cancel_signal_requested": args.cancel_signal or None,
            "owned_exit_after_cancel": bool(args.cancel_signal and args.local_child),
        }
    )
    identity = {
        "status": "unverified",
        "may_authorize": False,
        "reason_codes": ["native_launch_descriptor_unavailable"],
    }
    if not args.local_child:
        identity["reason_codes"] = ["remote_native_identity_unobserved"]
    elif all(
        (
            args.execution_descriptor,
            args.execution_route,
            args.native_home,
            args.workdir,
            args.launch_started_at,
        )
    ):
        try:
            # This file is selected from the activated source release. -I
            # isolates ambient paths; use that same explicit root for imports.
            import sys

            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from shared.codex_execution_receipt import observe_codex_run_identity
            from shared.platform_capability_registry import ExecutionDescriptor

            descriptor = ExecutionDescriptor.model_validate_json(args.execution_descriptor)
            identity = observe_codex_run_identity(
                descriptor,
                route_id=args.execution_route,
                session_id=observed["session_id"],
                native_home=args.native_home,
                workdir=args.workdir,
                launch_started_at=args.launch_started_at,
            )
        except Exception as exc:
            # Evidence failure cannot overwrite the waited native exit status.
            identity["reason_codes"] = [f"native_identity_observer_failed:{type(exc).__name__}"]
    observed["execution_identity"] = identity
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    with args.receipt.open("x") as out:
        out.write(json.dumps(observed, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_native_receipt_main())
