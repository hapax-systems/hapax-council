"""Pi-edge VLM hand-semantics client.

Phase 3 of cc-task `ir-perception-replace-zones-with-vlm-classification`.
Pi-side companion to the council-side Phase 1 helper
(``shared/ir_vlm_classifier.py``); duplicates the small system-prompt
+ parse logic so this module can ship without a `shared/` dep on the
Pi's flat namespace.

Wired into ``hapax_ir_edge.py`` to replace the fixed five-zone enum
output with rich semantic descriptions per IR frame. The motion gate
+ cache machinery from the Phase 2 council runner is duplicated here
so the Pi calls the LiteLLM gateway (over LAN to the council host) at
most once per ~minute on a static desk, well within token budget.

Why duplicate rather than import from `shared/`
-----------------------------------------------

Pi-edge ships as a flat namespace under ``~/hapax-edge/`` on each Pi
(see ``pi-edge/setup.sh``). It does not have a ``shared/`` package
mirrored over from the council host, and adding such a sync would
broaden the Pi's deploy surface considerably for one helper. The
duplication here is small (~80 LOC) and the schemas stay structurally
identical to ``shared.ir_vlm_classifier.HandSemantics`` so council-side
deserialization on the receiving end (``shared/ir_models.py``) works
without translation.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Final

log = logging.getLogger(__name__)

#: System prompt the multimodal classifier receives. Mirrors the
#: prompt in ``shared/ir_vlm_classifier.py`` so the response shape is
#: identical regardless of which side runs the call.
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

#: Default LiteLLM gateway URL — the Pi reaches the council host over
#: LAN. Override via ``LITELLM_URL`` env var.
DEFAULT_LITELLM_URL: Final[str] = "http://192.168.68.81:4000/v1/chat/completions"

#: Default Hamming threshold for the motion gate. 12 of 256 bits ≈ 5%
#: of bits flipped — catches typing/desk-shift while ignoring sensor
#: noise. Mirrors the council-side runner default.
DEFAULT_MOTION_THRESHOLD: Final[int] = 12

#: Default cache TTL — at the Pi's ~3 s capture cadence this caps the
#: classifier at one VLM call per ~5 frames even on continuous motion.
DEFAULT_CACHE_TTL_S: Final[float] = 15.0

_PHASH_BITS: Final[int] = 256


def _strip_code_fence(raw: str) -> str:
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def _validate_semantics(data: Any) -> dict[str, Any] | None:
    """Validate the parsed VLM response into a sanitized dict.

    The Pi-side validation is intentionally lighter-weight than the
    council-side Pydantic model because the Pi reports the dict as-is
    in its outgoing JSON; council-side ``shared/ir_models.py``
    re-validates with the strict schema. We only enforce the minimum
    here so a malformed response cannot poison the report.
    """
    if not isinstance(data, dict):
        return None
    intent = data.get("intent")
    surface = data.get("surface")
    hand_position = data.get("hand_position")
    confidence = data.get("confidence")
    if not isinstance(intent, str) or not intent.strip():
        return None
    if not isinstance(surface, str) or not surface.strip():
        return None
    if not isinstance(hand_position, str) or not hand_position.strip():
        return None
    if not isinstance(confidence, int | float):
        return None
    if not (0.0 <= float(confidence) <= 1.0):
        return None
    return {
        "intent": intent.strip(),
        "surface": surface.strip(),
        "hand_position": hand_position.strip(),
        "confidence": float(confidence),
    }


def parse_vlm_response(raw: str) -> dict[str, Any] | None:
    """Parse the model's text response into a sanitized dict or None."""
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
    return _validate_semantics(data)


def _build_messages(jpeg_bytes: bytes) -> list[dict[str, Any]]:
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


def call_litellm(
    jpeg_bytes: bytes,
    *,
    url: str | None = None,
    api_key: str | None = None,
    model: str = "fast",
    timeout_s: float = 20.0,
    opener=urllib.request.urlopen,  # type: ignore[no-untyped-def]
) -> str | None:
    """Post the IR frame to LiteLLM and return the raw response text.

    Returns ``None`` on any HTTP / network / JSON-shape error so the
    motion-gated runner counts the failure rather than crashing the
    Pi-edge daemon. ``api_key`` defaults to ``LITELLM_API_KEY`` env
    var; ``url`` defaults to ``LITELLM_URL`` env var or the council's
    LAN gateway.
    """
    if not jpeg_bytes:
        return None
    target = url or os.environ.get("LITELLM_URL", DEFAULT_LITELLM_URL)
    key = api_key if api_key is not None else os.environ.get("LITELLM_API_KEY", "")
    body = json.dumps({"model": model, "messages": _build_messages(jpeg_bytes)}).encode("utf-8")
    req = urllib.request.Request(
        target,
        body,
        {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with opener(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read())
    except Exception:
        log.debug("LiteLLM HTTP call failed at %s", target, exc_info=True)
        return None
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None


def _perceptual_hash(jpeg_bytes: bytes) -> bytes | None:
    """16×16 grayscale + mean-threshold phash. Returns None on decode error."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover — Pillow expected on Pi-edge
        return None
    try:
        img = Image.open(io.BytesIO(jpeg_bytes)).convert("L").resize((16, 16))
    except Exception:
        return None
    pixels = list(img.getdata())
    avg = sum(pixels) / len(pixels) if pixels else 0
    bits = 0
    for i, p in enumerate(pixels):
        if p > avg:
            bits |= 1 << i
    return bits.to_bytes(_PHASH_BITS // 8, "big")


def _hamming(a: bytes, b: bytes) -> int:
    if len(a) != len(b):
        return _PHASH_BITS  # max distance — treat as motion
    return sum(bin(x ^ y).count("1") for x, y in zip(a, b, strict=True))


@dataclass
class _RunnerState:
    last_phash: bytes | None = None
    last_call_ts: float | None = None
    cached: dict[str, Any] | None = None
    fingerprint: str | None = None


@dataclass
class TickResult:
    """One-tick outcome for the Pi-edge daemon's outgoing report.

    ``semantics`` is the dict to attach to the outgoing JSON, or None
    when neither this tick nor any prior tick produced a value.
    ``reason`` tags the decision for log lines.
    """

    semantics: dict[str, Any] | None
    reason: str


class MotionGatedVlmRunner:
    """Pi-edge motion-gated VLM runner.

    Mirrors the council-side ``agents.ir_vlm_runner.MotionGatedVlmRunner``
    so the budget machinery is identical regardless of which side runs
    the call. Pi-edge uses this directly because it cannot import
    ``shared/`` modules.
    """

    def __init__(
        self,
        *,
        runner=call_litellm,  # type: ignore[no-untyped-def]
        motion_threshold: int = DEFAULT_MOTION_THRESHOLD,
        cache_ttl_s: float = DEFAULT_CACHE_TTL_S,
        model: str = "fast",
    ) -> None:
        if motion_threshold < 0:
            raise ValueError(f"motion_threshold must be >= 0, got {motion_threshold}")
        if cache_ttl_s <= 0:
            raise ValueError(f"cache_ttl_s must be > 0, got {cache_ttl_s}")
        self._runner = runner
        self._motion_threshold = motion_threshold
        self._cache_ttl_s = cache_ttl_s
        self._model = model
        self._state = _RunnerState()
        self.calls_made = 0
        self.calls_skipped_cache = 0
        self.calls_skipped_motion = 0
        self.calls_failed = 0

    @property
    def cached(self) -> dict[str, Any] | None:
        return self._state.cached

    def tick(self, jpeg_bytes: bytes, *, now: float | None = None) -> TickResult:
        ts_now = now if now is not None else time.time()
        if not jpeg_bytes:
            self.calls_failed += 1
            return TickResult(semantics=self._state.cached, reason="no-frame")

        phash = _perceptual_hash(jpeg_bytes)
        if phash is None:
            self.calls_failed += 1
            return TickResult(semantics=self._state.cached, reason="decode-failed")

        if (
            self._state.last_call_ts is not None
            and ts_now - self._state.last_call_ts < self._cache_ttl_s
        ):
            self.calls_skipped_cache += 1
            self._state.last_phash = phash
            return TickResult(semantics=self._state.cached, reason="cache-hit")

        if self._state.last_phash is not None:
            dist = _hamming(phash, self._state.last_phash)
            if dist < self._motion_threshold:
                self.calls_skipped_motion += 1
                self._state.last_phash = phash
                return TickResult(semantics=self._state.cached, reason="no-motion")

        raw = self._runner(jpeg_bytes, model=self._model) if self._runner else None
        if raw is None:
            self.calls_failed += 1
            self._state.last_phash = phash
            return TickResult(semantics=self._state.cached, reason="call-failed")

        parsed = parse_vlm_response(raw)
        if parsed is None:
            self.calls_failed += 1
            self._state.last_phash = phash
            return TickResult(semantics=self._state.cached, reason="parse-failed")

        self._state.cached = parsed
        self._state.last_call_ts = ts_now
        self._state.last_phash = phash
        self._state.fingerprint = hashlib.md5(jpeg_bytes, usedforsecurity=False).hexdigest()[:8]
        self.calls_made += 1
        return TickResult(semantics=parsed, reason="call-made")
