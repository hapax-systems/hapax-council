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
        if isinstance(model, str) and model:
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
    skipped, never raised. The result's ``models`` includes both the model of each
    assistant turn AND the ``to_model`` of every fallback (the model that actually served
    the retried turn).
    """
    p = Path(path)
    models: set[str] = set()
    fallbacks: list[FallbackEvent] = []
    turns = 0
    malformed = 0

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
                # The fallback target actually served a turn — it is part of observed set.
                models.add(fallback.to_model)

    return ObservedExecution(
        models=frozenset(models),
        fallback_events=tuple(fallbacks),
        turn_count=turns,
        source_path=str(p),
        malformed_lines=malformed,
    )
