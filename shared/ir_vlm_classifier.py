"""IR VLM classifier — rich-vocabulary replacement for the fixed
``ir_hand_zone`` enum.

Phase 1 of cc-task `ir-perception-replace-zones-with-vlm-classification`.
Operator directive (2026-05-01): "There should be no ZONES we should
rely only on extremely intelligent classification that has a vast
vocabulary." This module ships the **pure-logic + HTTP boundary** for
the replacement classifier. Pi-edge daemon wiring + consumer migration
land as separate slices.

Pipeline
--------

The Pi-side daemon captures one IR JPEG per cadence tick, hands the
bytes to :func:`classify_hand_via_vlm`, and emits the resulting
:class:`HandSemantics` record alongside (or eventually instead of) the
existing fixed-zone classification. Downstream consumers
(``_vinyl_probably_playing``, ``contact_mic_ir``, perceptual-field
populator) interrogate the structured description for true vinyl-
handling semantics rather than a single noisy zone-enum bit.

The boundary is split so the parsing and message-shape logic is
testable offline:

- :data:`VLM_SYSTEM_PROMPT` — the fixed instruction the multimodal
  model receives.
- :func:`build_vlm_messages` — composes the OpenAI-compat ``messages``
  payload from a base64 JPEG.
- :func:`parse_vlm_response` — parses the model's text response into a
  :class:`HandSemantics` (or ``None`` on a malformed reply).
- :func:`classify_hand_via_vlm` — orchestrates the HTTP call against
  LiteLLM (router-injectable for tests).

Out of scope (deferred to follow-up slices)
-------------------------------------------

- Pi-edge daemon ``hapax_ir_edge`` wiring (replacing the ``_classify_zone``
  call in ``pi-edge/ir_hands.py``).
- Cache / motion-gating budget enforcement (the spec cap is one VLM
  call per ~15 s; Phase 1 ships the helper but not the cache).
- Consumer migration (``_vinyl_probably_playing``,
  ``vinyl_spinning_engine``, perceptual-field populator).
- Removal of the ``ir_hand_zone`` enum (will land once all consumers
  read ``HandSemantics``).
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

#: System prompt the multimodal classifier receives. Asks for a single
#: JSON object per frame so the response is machine-parseable. The
#: vocabulary is intentionally open ("describe in your own words") for
#: the ``intent`` and ``surface`` fields — the operator's directive is
#: that the classifier must NOT collapse into a fixed enum.
VLM_SYSTEM_PROMPT: Final[str] = (
    "You are classifying what a single operator's hands are doing in an "
    "infrared (NIR) studio frame. Output ONE JSON object with these "
    "fields and no other text:\n"
    '  - "intent": short phrase describing what the operator appears '
    'to be doing (e.g. "typing on keyboard", "cueing a record on the '
    'turntable", "adjusting a synth knob", "resting hands on desk", '
    '"reaching for a record sleeve")\n'
    '  - "surface": noun phrase naming what the hands are touching or '
    'near (e.g. "laptop keyboard", "turntable platter", "MPC pads", '
    '"vinyl sleeve", "synth panel", "empty desk")\n'
    '  - "hand_position": short phrase like "centered", "left half", '
    '"right edge", "near top", or "out of frame"\n'
    '  - "confidence": float in [0.0, 1.0] expressing how sure you are\n'
    "Refuse to invent activity that you cannot see. If the frame is "
    'too ambiguous to interpret, set "intent" to "unclear" and '
    '"confidence" below 0.3.'
)


class HandSemantics(BaseModel):
    """Structured semantic description of operator hand activity.

    Replaces the fixed ``ir_hand_zone`` enum. Consumers that need a
    coarse zone for backward-compat can derive one from
    :attr:`surface` (e.g. ``"turntable platter" -> "turntable"``) until
    they migrate fully to the structured form.

    Validation rules:

    - ``intent``, ``surface``, ``hand_position`` must be non-empty after
      stripping; the system prompt instructs the model to use
      ``"unclear"`` for ambiguous frames rather than empty strings, so
      empties indicate an upstream parse error.
    - ``confidence`` is clamped to ``[0.0, 1.0]`` by Pydantic; out-of-
      range inputs raise.
    """

    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1, description="Verb phrase: what the operator is doing.")
    surface: str = Field(
        min_length=1,
        description="Noun phrase: what the hands are touching or near.",
    )
    hand_position: str = Field(
        min_length=1,
        description="Short phrase locating the hands within the frame.",
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Model self-report 0..1.")


def build_vlm_messages(jpeg_bytes: bytes) -> list[dict[str, Any]]:
    """Compose the OpenAI-compat messages list for one IR frame.

    The system prompt fixes the JSON contract; the user message
    carries the base64 JPEG via the ``image_url`` content shape that
    LiteLLM forwards to multimodal routes (Claude, Gemini Flash, etc.)
    """
    b64 = base64.b64encode(jpeg_bytes).decode("ascii")
    return [
        {"role": "system", "content": VLM_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                },
                {
                    "type": "text",
                    "text": "Classify the hand activity in this NIR frame. JSON only.",
                },
            ],
        },
    ]


def _strip_code_fence(raw: str) -> str:
    """Strip a leading/trailing markdown code fence if the model added one."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def parse_vlm_response(raw: str) -> HandSemantics | None:
    """Parse the model's text response into :class:`HandSemantics`.

    Returns ``None`` for any of: empty response, code-fence-only with
    no JSON, JSON decode failure, or schema validation failure. The
    caller treats ``None`` as "no semantic signal this tick" and
    falls back to whichever default the consumer prefers.
    """
    if not raw or not raw.strip():
        return None
    cleaned = _strip_code_fence(raw)
    if not cleaned:
        return None
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        log.debug("VLM response failed JSON decode: %r", raw[:200])
        return None
    if not isinstance(data, dict):
        log.debug("VLM response is not a JSON object: %r", raw[:200])
        return None
    try:
        return HandSemantics.model_validate(data)
    except Exception:
        log.debug("VLM response failed HandSemantics validation: %r", raw[:200])
        return None


def classify_hand_via_vlm(
    jpeg_bytes: bytes,
    *,
    runner,  # type: ignore[no-untyped-def]  — caller-supplied HTTP/LLM dispatcher
    model: str = "fast",
) -> HandSemantics | None:
    """Run a multimodal classification against the supplied runner.

    ``runner`` is any callable matching
    ``runner(messages: list[dict], *, model: str) -> str | None``. The
    Pi-edge daemon (Phase 2 slice) supplies a LiteLLM-backed runner;
    tests inject a stub. ``runner`` returning ``None`` (network error,
    quota) propagates to ``None`` here without raising.
    """
    if not jpeg_bytes:
        return None
    messages = build_vlm_messages(jpeg_bytes)
    try:
        raw = runner(messages, model=model)
    except Exception:
        log.debug("VLM runner raised", exc_info=True)
        return None
    if raw is None:
        return None
    return parse_vlm_response(raw)
