"""Grammar for phone-push control messages.

A message is a single line of text typed by the operator on their phone
and sent via KDEConnect's "send text" action. The grammar is a small
verb-first prefix language — one word per capability, plus a payload
tail. Unknown commands do **not** raise; they return a structured
``unknown`` result so the caller can ACK back to the phone with a
helpful error instead of silently dropping.

Commands
--------

``hero <role>``           → ``studio.hero.set {camera_role: <role>}``
``hero clear``            → ``studio.hero.clear``
``vinyl <preset>``        → ``audio.vinyl.rate_preset {preset: <preset>}``
    where ``<preset>`` ∈ ``{45-on-33, 33, 45}`` or ``custom:<float>``
``fx <chain>``            → ``fx.chain.set {chain: <chain>}``
``mode <mode>``           → ``mode.set {mode: <mode>}`` (research|rnd)
``ward next``             → ``studio.ward.next``
``ward pause``            → ``studio.ward.pause``
``ward resume``           → ``studio.ward.resume``
``safe``                  → ``degraded.activate``
``safe off``              → ``degraded.deactivate``
``sidechat <message>``    → sidechat JSONL append (dispatched separately)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

_VINYL_ENUM = {"45-on-33", "33", "45"}
_MODES = {"research", "rnd"}
_WARD_SUBS = {"next", "pause", "resume"}

# Kind discriminant for downstream dispatch routing. ``command`` goes to
# the WS relay; ``sidechat`` is a filesystem append; ``unknown`` is an
# error tag the caller echoes back to the phone.
ParsedKind = Literal["command", "sidechat", "unknown"]


@dataclass(frozen=True)
class Parsed:
    """Structured result of parsing a single phone-push message."""

    kind: ParsedKind
    command: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    sidechat_text: str = ""
    error: str = ""
    # Echo of the raw input for ACK / logging.
    source: str = ""


def parse(message: str) -> Parsed:
    """Parse a single phone-push message into a structured ``Parsed``.

    Returns ``Parsed(kind="unknown", error=...)`` for malformed input;
    never raises. The caller is expected to ACK the error back to the
    phone and drop the message.
    """
    raw = (message or "").strip()
    if not raw:
        return Parsed(kind="unknown", error="empty message", source=raw)

    verb, _, tail = raw.partition(" ")
    verb = verb.lower()
    tail = tail.strip()

    if verb == "hero":
        if not tail:
            return Parsed(kind="unknown", error="hero requires a role or 'clear'", source=raw)
        if tail.lower() == "clear":
            return Parsed(kind="command", command="studio.hero.clear", source=raw)
        return Parsed(
            kind="command",
            command="studio.hero.set",
            args={"camera_role": tail},
            source=raw,
        )

    if verb == "vinyl":
        if not tail:
            return Parsed(kind="unknown", error="vinyl requires a preset", source=raw)
        preset = tail.strip()
        if preset in _VINYL_ENUM:
            return Parsed(
                kind="command",
                command="audio.vinyl.rate_preset",
                args={"preset": preset},
                source=raw,
            )
        if preset.startswith("custom:"):
            try:
                float(preset.split(":", 1)[1])
            except ValueError:
                return Parsed(
                    kind="unknown",
                    error=f"vinyl custom rate must be numeric: {preset!r}",
                    source=raw,
                )
            return Parsed(
                kind="command",
                command="audio.vinyl.rate_preset",
                args={"preset": preset},
                source=raw,
            )
        return Parsed(kind="unknown", error=f"unknown vinyl preset {preset!r}", source=raw)

    if verb == "fx":
        if not tail:
            return Parsed(kind="unknown", error="fx requires a chain name", source=raw)
        return Parsed(
            kind="command",
            command="fx.chain.set",
            args={"chain": tail},
            source=raw,
        )

    if verb == "mode":
        if tail not in _MODES:
            return Parsed(
                kind="unknown",
                error=f"unknown mode {tail!r}; expected research|rnd",
                source=raw,
            )
        return Parsed(kind="command", command="mode.set", args={"mode": tail}, source=raw)

    if verb == "ward":
        sub = tail.lower()
        if sub not in _WARD_SUBS:
            return Parsed(
                kind="unknown",
                error=f"unknown ward action {tail!r}; expected next|pause|resume",
                source=raw,
            )
        return Parsed(kind="command", command=f"studio.ward.{sub}", source=raw)

    if verb == "safe":
        # ``safe`` → activate; ``safe off`` → deactivate. Any other
        # trailing text is treated as the activate form (terse panic
        # trigger; operator intent is unambiguous).
        if tail.lower() == "off":
            return Parsed(kind="command", command="degraded.deactivate", source=raw)
        return Parsed(kind="command", command="degraded.activate", source=raw)

    if verb == "sidechat":
        if not tail:
            return Parsed(kind="unknown", error="sidechat requires a message body", source=raw)
        return Parsed(kind="sidechat", sidechat_text=tail, source=raw)

    return Parsed(kind="unknown", error=f"unknown command {verb!r}", source=raw)
