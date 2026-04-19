"""Scene classifier — Task #150 Phase 1 (vision classification pipeline).

The video/image classification pipeline (Gemini Flash 2.5 multimodal) is
underused in the livestream. This module samples the current hero-camera
JPEG at 1 Hz, calls gemini-flash through the existing LiteLLM gateway
with a short classification prompt, and publishes the result to
``/dev/shm/hapax-compositor/scene-classification.json``.

The downstream consumer is :mod:`agents.studio_compositor.preset_family_selector`
which biases preset picks within a recruited family toward presets whose
``tags`` metadata matches the current scene (see ``pick_with_scene_bias``).

Budget:
  * ≤1 gemini-flash call per second
  * 5-second in-process cache — repeated ``classify()`` calls within the
    TTL reuse the last classification without re-calling the LLM

Feature flag:
  * ``HAPAX_SCENE_CLASSIFIER_ACTIVE`` — default OFF. The classifier does
    not run unless this is ``1`` / ``true`` / ``yes`` / ``on``.

Prometheus:
  * ``hapax_scene_classifications_total{scene=...}`` — Counter

The design follows ``director_loop._call_activity_llm`` for LiteLLM
invocation (OpenAI-compatible ``image_url`` content with a base64-encoded
JPEG, explicit ``budget_tokens: 0`` per CLAUDE.md §Tauri-Only Runtime for
Gemini Flash 2.5 vision).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────

SHM_DIR = Path("/dev/shm/hapax-compositor")
HERO_OVERRIDE_PATH = SHM_DIR / "hero-camera-override.json"
CLASSIFICATION_PATH = SHM_DIR / "scene-classification.json"

# LiteLLM gateway (same URL the director uses).
LITELLM_URL = "http://localhost:4000/v1/chat/completions"
SCENE_MODEL = "gemini-flash"

# Cache TTL in seconds; repeated calls within this window reuse the last
# classification.
CACHE_TTL_S = 5.0

# Maximum wait for the LiteLLM call. Scene classification is a ~1-token
# JSON response off gemini-flash, so even on a degraded day the wall-clock
# target is <3 s. 10 s is the hard ceiling to keep the background thread
# from stalling the compositor shutdown.
LLM_TIMEOUT_S = 10.0

# Canonical scene labels the classifier must choose from. Keep this
# in sync with the bias table in ``preset_family_selector``.
SCENE_LABELS: tuple[str, ...] = (
    "person-face-closeup",
    "hands-manipulating-gear",
    "room-wide-ambient",
    "turntables-playing",
    "outboard-synth-detail",
    "screen-only",
    "empty-room",
    "mixed-activity",
)

FALLBACK_SCENE = "mixed-activity"

_PROMPT = (
    "Classify the scene in this frame into one of: "
    f"[{', '.join(SCENE_LABELS)}]. "
    'Return JSON: {"scene": ..., "confidence": 0-1, "evidence": <short string>}.'
)


# ── Feature flag ──────────────────────────────────────────────────────────


def classifier_active() -> bool:
    """True when ``HAPAX_SCENE_CLASSIFIER_ACTIVE`` is truthy.

    Default is OFF. Truthy values: ``1``, ``true``, ``yes``, ``on``
    (case-insensitive). Anything else, including a missing env var,
    disables the classifier.
    """
    val = os.environ.get("HAPAX_SCENE_CLASSIFIER_ACTIVE", "").strip().lower()
    return val in {"1", "true", "yes", "on"}


# ── Prometheus counter ────────────────────────────────────────────────────


_PROM_COUNTER: Any = None
try:
    from prometheus_client import Counter

    # Module-global counter. Registration is process-wide; pytest can
    # tolerate a repeat-import thanks to prometheus_client's global
    # default registry. We key only by ``scene`` so cardinality stays
    # bounded by :data:`SCENE_LABELS`.
    _PROM_COUNTER = Counter(
        "hapax_scene_classifications_total",
        "Scene classifications emitted by the scene_classifier (Phase 1 of #150)",
        ["scene"],
    )
except Exception:  # pragma: no cover — prom unavailable in some contexts
    _PROM_COUNTER = None


def _count(scene: str) -> None:
    if _PROM_COUNTER is None:
        return
    try:
        _PROM_COUNTER.labels(scene=scene).inc()
    except Exception:
        log.debug("prometheus counter inc failed", exc_info=True)


# ── Data model ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Classification:
    """One scene classification emitted by the classifier."""

    scene: str
    confidence: float
    evidence: str
    ts: float  # epoch seconds when the classification was produced

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene": self.scene,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "ts": self.ts,
        }


# ── Hero camera resolution ────────────────────────────────────────────────


def _hero_camera_role(override_path: Path = HERO_OVERRIDE_PATH) -> str | None:
    """Return the current hero camera role, or None when unknown.

    The compositor writes the hero camera override to
    ``/dev/shm/hapax-compositor/hero-camera-override.json`` with shape
    ``{"camera_role": "c920-desk", ...}``. Stale entries (TTL expired)
    are still honored here — the scene classifier is a low-stakes signal
    and a slightly-stale hero pick is fine.
    """
    if not override_path.exists():
        return None
    try:
        payload = json.loads(override_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    role = payload.get("camera_role") if isinstance(payload, dict) else None
    if isinstance(role, str) and role:
        return role
    return None


def _hero_snapshot_path(role: str, shm_dir: Path = SHM_DIR) -> Path:
    """Map a camera role to its JPEG snapshot under ``/dev/shm/hapax-compositor/``."""
    return shm_dir / f"{role}.jpg"


# ── LiteLLM key helper ────────────────────────────────────────────────────


_LITELLM_KEY_CACHE: dict[str, str] = {}


def _get_litellm_key() -> str:
    """Fetch the LiteLLM master key via ``pass``. Cached process-wide."""
    if "key" in _LITELLM_KEY_CACHE:
        return _LITELLM_KEY_CACHE["key"]
    try:
        result = subprocess.run(
            ["pass", "show", "litellm/master-key"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        key = result.stdout.strip()
    except Exception:
        log.debug("pass show litellm/master-key failed", exc_info=True)
        key = ""
    _LITELLM_KEY_CACHE["key"] = key
    return key


# ── Writer ────────────────────────────────────────────────────────────────


def _atomic_write_json(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        log.warning("atomic write to %s failed", path, exc_info=True)


def _publish(classification: Classification, path: Path = CLASSIFICATION_PATH) -> None:
    _atomic_write_json(path, classification.to_dict())


# ── LLM call ──────────────────────────────────────────────────────────────


def _call_gemini_flash(image_b64: str, *, timeout: float = LLM_TIMEOUT_S) -> str:
    """Send one classification request to gemini-flash via LiteLLM.

    Returns the raw response text (expected to be a JSON blob).
    Raises ``RuntimeError`` on transport failure so the caller can fall
    back to :data:`FALLBACK_SCENE`.
    """
    key = _get_litellm_key()
    if not key:
        raise RuntimeError("no litellm key")

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                },
                {"type": "text", "text": _PROMPT},
            ],
        }
    ]
    body = json.dumps(
        {
            "model": SCENE_MODEL,
            "messages": messages,
            "max_tokens": 128,
            "temperature": 0.0,
            # CLAUDE.md §Tauri-Only Runtime — Gemini Flash 2.5 requires
            # budget_tokens: 0 for vision. LiteLLM forwards this verbatim.
            "budget_tokens": 0,
        }
    ).encode()

    req = urllib.request.Request(
        LITELLM_URL,
        body,
        {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"litellm call failed: {exc}") from exc

    try:
        payload = json.loads(raw)
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"litellm response shape unexpected: {exc}") from exc


def _parse_classification(raw: str, now: float) -> Classification:
    """Parse the model's JSON response into a :class:`Classification`.

    Accepts raw text like ``{"scene": "...", "confidence": 0.8, "evidence": "..."}``,
    optionally wrapped in markdown fence. Anything malformed or out-of-range
    falls back to ``mixed-activity`` at confidence 0.0 so the downstream
    bias selector still sees a well-formed record.
    """
    text = raw.strip()
    # Strip ```json ... ``` fence if present.
    if text.startswith("```"):
        # Remove opening fence line + closing fence.
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.error("scene_classifier: malformed JSON from LLM: %r", raw[:200])
        return Classification(scene=FALLBACK_SCENE, confidence=0.0, evidence="parse-error", ts=now)

    if not isinstance(data, dict):
        log.error("scene_classifier: non-object response: %r", raw[:200])
        return Classification(scene=FALLBACK_SCENE, confidence=0.0, evidence="shape-error", ts=now)

    scene = data.get("scene", FALLBACK_SCENE)
    if scene not in SCENE_LABELS:
        log.warning("scene_classifier: unknown scene label %r, falling back", scene)
        scene = FALLBACK_SCENE

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    evidence = str(data.get("evidence", ""))[:200]

    return Classification(scene=scene, confidence=confidence, evidence=evidence, ts=now)


# ── Classifier core ───────────────────────────────────────────────────────


class SceneClassifier:
    """Samples the hero-camera JPEG and publishes scene classifications.

    The classifier maintains a 5-second in-process cache — repeated
    ``classify_once()`` calls within the TTL return the cached result
    without re-calling the LLM. This keeps the steady-state cost at
    ≤1 gemini-flash call per second even when the compositor polls
    faster than that.
    """

    def __init__(
        self,
        *,
        shm_dir: Path = SHM_DIR,
        override_path: Path | None = None,
        classification_path: Path | None = None,
        cache_ttl_s: float = CACHE_TTL_S,
        call_llm: Any = None,
    ) -> None:
        self._shm_dir = shm_dir
        self._override_path = override_path or (shm_dir / "hero-camera-override.json")
        self._classification_path = classification_path or (shm_dir / "scene-classification.json")
        self._cache_ttl_s = cache_ttl_s
        # Injection point for tests — defaults to the real LiteLLM call.
        self._call_llm = call_llm or _call_gemini_flash
        self._last: Classification | None = None
        self._lock = threading.Lock()

    @property
    def last(self) -> Classification | None:
        return self._last

    def classify_once(self, *, now: float | None = None) -> Classification | None:
        """Sample + classify the current hero frame.

        Returns the resulting :class:`Classification`, or ``None`` when
        the hero camera could not be resolved or the snapshot is missing.
        """
        if now is None:
            now = time.time()

        with self._lock:
            if self._last is not None and (now - self._last.ts) < self._cache_ttl_s:
                return self._last

        role = _hero_camera_role(self._override_path)
        if not role:
            log.debug("scene_classifier: no hero camera role available")
            return None

        snapshot = _hero_snapshot_path(role, self._shm_dir)
        if not snapshot.exists():
            log.debug("scene_classifier: hero snapshot missing: %s", snapshot)
            return None

        try:
            image_b64 = base64.b64encode(snapshot.read_bytes()).decode("ascii")
        except OSError:
            log.warning("scene_classifier: failed to read snapshot %s", snapshot, exc_info=True)
            return None

        try:
            raw = self._call_llm(image_b64)
        except Exception as exc:
            log.warning("scene_classifier: LLM call failed: %s", exc)
            classification = Classification(
                scene=FALLBACK_SCENE,
                confidence=0.0,
                evidence=f"llm-error: {exc}"[:200],
                ts=now,
            )
        else:
            classification = _parse_classification(raw, now)

        with self._lock:
            self._last = classification
        _count(classification.scene)
        _publish(classification, self._classification_path)
        return classification


# ── Background runner ─────────────────────────────────────────────────────


class SceneClassifierThread(threading.Thread):
    """1-Hz background thread driving :class:`SceneClassifier`.

    Does not run unless :func:`classifier_active` returns True at start
    time. The compositor main loop is expected to construct and start
    this thread once during ``StudioCompositor.start()``.
    """

    def __init__(
        self,
        classifier: SceneClassifier | None = None,
        *,
        interval_s: float = 1.0,
    ) -> None:
        super().__init__(name="hapax-scene-classifier", daemon=True)
        self._classifier = classifier or SceneClassifier()
        self._interval_s = interval_s
        self._stop_event = threading.Event()

    def classifier(self) -> SceneClassifier:
        return self._classifier

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:  # pragma: no cover — wall-clock integration path
        log.info("scene_classifier thread starting (interval=%.2fs)", self._interval_s)
        while not self._stop_event.wait(self._interval_s):
            try:
                self._classifier.classify_once()
            except Exception:
                log.exception("scene_classifier tick failed")
        log.info("scene_classifier thread stopped")


def maybe_start_scene_classifier(*, interval_s: float = 1.0) -> SceneClassifierThread | None:
    """Start the scene classifier thread iff the feature flag is on.

    Returns the running thread when started, or ``None`` when the
    feature flag is off or startup failed. Safe to call from the
    compositor's single-threaded startup path.
    """
    if not classifier_active():
        log.info("scene_classifier inactive (HAPAX_SCENE_CLASSIFIER_ACTIVE off)")
        return None
    try:
        thread = SceneClassifierThread(interval_s=interval_s)
        thread.start()
        return thread
    except Exception:
        log.exception("scene_classifier failed to start")
        return None


def read_published_scene(
    path: Path = CLASSIFICATION_PATH, *, max_age_s: float = 30.0
) -> str | None:
    """Read the most recently published scene, or None if stale/missing.

    Used by :mod:`preset_family_selector` to pull the current scene
    without a tight coupling to the classifier thread. ``max_age_s`` is
    a safety cutoff — if nothing has been written within the window
    (classifier is off, or has crashed), no bias is applied.
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    scene = data.get("scene")
    ts = data.get("ts", 0)
    if not isinstance(scene, str) or scene not in SCENE_LABELS:
        return None
    try:
        if (time.time() - float(ts)) > max_age_s:
            return None
    except (TypeError, ValueError):
        return None
    return scene


__all__ = [
    "CACHE_TTL_S",
    "CLASSIFICATION_PATH",
    "Classification",
    "FALLBACK_SCENE",
    "HERO_OVERRIDE_PATH",
    "SCENE_LABELS",
    "SceneClassifier",
    "SceneClassifierThread",
    "classifier_active",
    "maybe_start_scene_classifier",
    "read_published_scene",
]
