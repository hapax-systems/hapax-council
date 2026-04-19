"""Director loop — orchestrates Hapax's autonomous livestream behavior.

Hapax chooses what to do based on signals: react to videos, engage chat,
comment on music, study its own research, or be silent. The activity
selector scores each possibility every tick and picks the best one.
The spirograph, videos, and shader effects run continuously regardless
of which activity is active.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from agents.studio_compositor import metrics
from agents.studio_compositor.audio_control import SlotAudioControl
from agents.studio_compositor.tts_client import DaimonionTtsClient
from shared.director_intent import CompositionalImpingement, DirectorIntent
from shared.persona_prompt_composer import compose_persona_prompt
from shared.stimmung import Stance


def _silence_hold_impingement() -> CompositionalImpingement:
    """Stock silence-hold impingement for parser-error / legacy-shape fallbacks.

    Operator invariant (2026-04-18): every tick must emit at least one
    compositional_impingement. When the LLM returns empty / malformed /
    legacy-shape output, the parser used to construct DirectorIntent with
    ``compositional_impingements=[]`` — leaving the surface with nothing
    to recruit for the full narrative cadence. Populating a silence-hold
    micromove here keeps the invariant deterministically satisfied.
    """
    return CompositionalImpingement(
        narrative=(
            "Silence hold: maintain the current surface; stance indicator breathes, "
            "chrome unchanged, no new recruitment this tick."
        ),
        intent_family="overlay.emphasis",
        material="void",
        salience=0.2,
    )


def _director_degraded_active() -> bool:
    """Task #122 DEGRADED check for the director tick.

    Lazy import so test harnesses without the metrics registry can
    still exercise ``DirectorLoop`` paths.
    """
    try:
        from agents.studio_compositor.degraded_mode import get_controller

        return get_controller().is_active()
    except Exception:
        log.debug("degraded-mode check failed in director", exc_info=True)
        return False


def _silence_hold_fallback_intent(
    *, activity: str, narrative_text: str, reason: str, tier: str, condition_id: str
) -> DirectorIntent:
    """Construct a parser fallback DirectorIntent that satisfies the operator
    no-vacuum invariant (2026-04-18) by attaching a silence-hold impingement.

    Cascade-delta (2026-04-18): the silence-hold now also populates a
    ``structural_intent`` so the homage surface keeps breathing during
    parser-error / degraded ticks. Without it, every LLM failure left
    the surface as a static techno overlay for the entire narrative
    cadence — exactly what the operator flagged.
    """
    from shared.director_intent import NarrativeStructuralIntent
    from shared.director_observability import emit_vacuum_prevented

    try:
        emit_vacuum_prevented(reason=reason, tier=tier, condition_id=condition_id)
    except Exception:
        log.debug("emit_vacuum_prevented failed", exc_info=True)
    # Baseline: emphasise the thinking indicator + stance so viewers see
    # the system is alive even when the LLM has failed. ``paused`` mode
    # intentionally NOT used here — we want visible motion while
    # degraded, not frozen ward state.
    try:
        structural = NarrativeStructuralIntent(
            homage_rotation_mode="weighted_by_salience",
            ward_emphasis=["thinking_indicator", "stance_indicator"],
        )
    except Exception:
        structural = NarrativeStructuralIntent()
    return DirectorIntent(
        activity=activity,  # type: ignore[arg-type]
        stance=Stance.NOMINAL,
        narrative_text=narrative_text,
        compositional_impingements=[_silence_hold_impingement()],
        structural_intent=structural,
    )


def _persona_legacy_mode() -> bool:
    """True when HAPAX_PERSONA_LEGACY is set — emergency revert to pre-Phase-7
    hard-coded identity block in the director unified prompt."""
    value = os.environ.get("HAPAX_PERSONA_LEGACY", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _director_model_legacy_mode() -> bool:
    """True when HAPAX_DIRECTOR_MODEL_LEGACY is set — reverts the director
    output path to the pre-volitional-director {activity, react} shape.
    Rollback flag for the volitional-grounded-director epic (PR #1017,
    spec 2026-04-17-volitional-grounded-director-design.md §9)."""
    value = os.environ.get("HAPAX_DIRECTOR_MODEL_LEGACY", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


# Where the director publishes its per-tick intent for downstream consumers.
_DIRECTOR_INTENT_JSONL = Path(
    os.path.expanduser("~/hapax-state/stream-experiment/director-intent.jsonl")
)
_NARRATIVE_STATE_PATH = Path("/dev/shm/hapax-director/narrative-state.json")


def _parse_intent_from_llm(
    raw: str,
    fallback_activity: str = "react",
    *,
    condition_id: str = "unknown",
    tier: str = "narrative",
) -> DirectorIntent:
    """Parse an LLM response into a DirectorIntent.

    Handles three shapes:
    - Legacy ``{"activity": "...", "react": "..."}`` — construct a minimal
      DirectorIntent with stance=NOMINAL and empty impingements.
    - Full ``DirectorIntent``-shaped JSON — validated via Pydantic.
    - Malformed / non-JSON — returns a silence fallback to let the loop continue.

    Emits ``hapax_director_intent_parse_failure_total`` whenever JSON parsing
    or full-intent validation fails; the rollback criterion
    "≥5 parse failures per 10 min" depends on this counter.
    """
    from shared.director_observability import emit_parse_failure

    text = raw.strip()
    if not text:
        emit_parse_failure(tier=tier, condition_id=condition_id)
        return _silence_hold_fallback_intent(
            activity="silence",
            narrative_text="",
            reason="parser_empty_text",
            tier=tier,
            condition_id=condition_id,
        )
    try:
        obj = json.loads(text) if text.startswith("{") else None
    except (json.JSONDecodeError, TypeError):
        emit_parse_failure(tier=tier, condition_id=condition_id)
        return _silence_hold_fallback_intent(
            activity="silence",
            narrative_text="",
            reason="parser_json_decode",
            tier=tier,
            condition_id=condition_id,
        )
    if not isinstance(obj, dict):
        emit_parse_failure(tier=tier, condition_id=condition_id)
        return _silence_hold_fallback_intent(
            activity="silence",
            narrative_text="",
            reason="parser_non_dict",
            tier=tier,
            condition_id=condition_id,
        )
    # If the response looks like a full DirectorIntent, validate it.
    if "stance" in obj or "compositional_impingements" in obj:
        try:
            return DirectorIntent.model_validate(obj)
        except Exception:
            emit_parse_failure(tier=tier, condition_id=condition_id)
    # Fall back to legacy shape.
    activity = obj.get("activity") or fallback_activity
    narrative = obj.get("react") or ""
    try:
        return _silence_hold_fallback_intent(
            activity=activity,
            narrative_text=narrative,
            reason="parser_legacy_shape",
            tier=tier,
            condition_id=condition_id,
        )
    except Exception:
        emit_parse_failure(tier=tier, condition_id=condition_id)
        return _silence_hold_fallback_intent(
            activity=fallback_activity,
            narrative_text="",
            reason="parser_legacy_construct_error",
            tier=tier,
            condition_id=condition_id,
        )


_DMN_IMPINGEMENTS_FILE = Path("/dev/shm/hapax-dmn/impingements.jsonl")
_LLM_IN_FLIGHT_MARKER = Path("/dev/shm/hapax-director/llm-in-flight.json")


class _LLMInFlight:
    """Context manager that publishes an LLM-in-flight marker for Cairo.

    The ThinkingIndicator Cairo source watches this file; when it exists,
    a sinusoidal pulse shows on-frame. On exit (success, timeout, or any
    exception) the marker is removed so the indicator reflects reality.
    """

    def __init__(self, *, tier: str, model: str) -> None:
        self.tier = tier
        self.model = model

    def __enter__(self) -> _LLMInFlight:
        try:
            _LLM_IN_FLIGHT_MARKER.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "tier": self.tier,
                "model": self.model,
                "started_at": time.time(),
            }
            tmp = _LLM_IN_FLIGHT_MARKER.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(_LLM_IN_FLIGHT_MARKER)
        except Exception:
            log.debug("llm-in-flight marker write failed", exc_info=True)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            _LLM_IN_FLIGHT_MARKER.unlink(missing_ok=True)
        except Exception:
            log.debug("llm-in-flight marker unlink failed", exc_info=True)


def _emit_compositional_impingements(intent: DirectorIntent, condition_id: str) -> None:
    """Write each CompositionalImpingement to the DMN impingement stream.

    The AffordancePipeline reads this stream; compositor-origin impingements
    become recruitable against the compositional affordance catalog
    (shared/compositional_affordances.py). Source tag
    `studio_compositor.director.compositional` lets downstream consumers
    (daimonion, reverie) filter compositor-origin impingements from their
    own recruitment pass if needed.

    Phase 3c of the volitional-director epic (PR #1018).
    """
    if not intent.compositional_impingements:
        return
    try:
        from shared.impingement import Impingement, ImpingementType

        _DMN_IMPINGEMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        now = time.time()
        for imp in intent.compositional_impingements:
            dmn_imp = Impingement(
                timestamp=now,
                source="studio_compositor.director.compositional",
                type=ImpingementType.SALIENCE_INTEGRATION,
                strength=float(imp.salience),
                # Stage 1 routing fix: promote intent_family to a first-class
                # field on the Impingement so AffordancePipeline.select() can
                # restrict retrieval to capabilities of that family. Without
                # this, the director's "cut to closeup of turntable" with
                # intent_family="camera.hero" was scoring globally and could
                # be hijacked by a Reverie satellite shader whose Gibson-verb
                # description happened to be cosine-close. Kept in content
                # too for backward compatibility with any consumer reading
                # the legacy location.
                intent_family=imp.intent_family,
                content={
                    "narrative": imp.narrative,
                    "intent_family": imp.intent_family,
                    "material": imp.material,
                    "dimensions": dict(imp.dimensions),
                    "director_activity": intent.activity,
                    "director_stance": str(intent.stance),
                    "condition_id": condition_id,
                },
            )
            lines.append(dmn_imp.model_dump_json())
        with _DMN_IMPINGEMENTS_FILE.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except Exception:
        log.warning("DMN compositional-impingement emission failed", exc_info=True)


# JSONL rotation threshold. Rotate after ~5 MiB; keep the last 3 files.
# Epic 2 Phase G4 — before this, director-intent.jsonl grew unbounded.
_JSONL_ROTATE_BYTES = 5 * 1024 * 1024
_JSONL_KEEP_ROTATED = 3


def _maybe_rotate_jsonl(path: Path) -> None:
    try:
        if not path.exists() or path.stat().st_size < _JSONL_ROTATE_BYTES:
            return
        # Shift .N → .N+1 from the highest-numbered file down.
        for n in range(_JSONL_KEEP_ROTATED, 0, -1):
            older = path.with_suffix(f".jsonl.{n}")
            newer = path.with_suffix(f".jsonl.{n + 1}")
            if older.exists():
                if n == _JSONL_KEEP_ROTATED:
                    older.unlink(missing_ok=True)
                else:
                    older.rename(newer)
        path.rename(path.with_suffix(".jsonl.1"))
    except Exception:
        log.warning("JSONL rotation failed", exc_info=True)


def _emit_intent_artifacts(intent: DirectorIntent, condition_id: str) -> None:
    """Write the intent to JSONL + narrative-state SHM + Prometheus + DMN stream.

    Non-fatal: any IO error is logged but does not block the director loop.
    """
    try:
        _DIRECTOR_INTENT_JSONL.parent.mkdir(parents=True, exist_ok=True)
        _maybe_rotate_jsonl(_DIRECTOR_INTENT_JSONL)
        payload = intent.model_dump_for_jsonl()
        payload["condition_id"] = condition_id
        payload["emitted_at"] = time.time()
        with _DIRECTOR_INTENT_JSONL.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except Exception:
        log.warning("director-intent JSONL write failed", exc_info=True)
    try:
        from shared.director_observability import emit_director_intent

        emit_director_intent(intent, condition_id=condition_id)
    except Exception:
        log.debug("prometheus emit_director_intent failed", exc_info=True)
    try:
        _NARRATIVE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "stance": str(intent.stance),
            "activity": intent.activity,
            "last_tick_ts": time.time(),
            "condition_id": condition_id,
        }
        tmp = _NARRATIVE_STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(_NARRATIVE_STATE_PATH)
    except Exception:
        log.warning("narrative-state.json write failed", exc_info=True)
    # Phase 3c — emit compositional impingements so AffordancePipeline
    # can recruit compositional capabilities. Gated by the legacy flag
    # (A5): under HAPAX_DIRECTOR_MODEL_LEGACY=1 we still write JSONL +
    # narrative-state + Prometheus above, but suppress the richer
    # compositional feedback so the rollback is a true rollback of
    # behavior, not of observability.
    if not _director_model_legacy_mode():
        _emit_compositional_impingements(intent, condition_id=condition_id)
        # Cascade-delta (2026-04-18) — dispatch the narrative-tier
        # structural intent straight to ward-properties + the homage
        # pending-transitions queue so the surface visibly shifts every
        # tick. Unlike compositional_impingements, this bypasses Qdrant
        # recruitment because structural directives are aesthetic, not
        # recruitable capabilities. Fail-open: dispatch errors log and
        # do not block the tick.
        try:
            from agents.studio_compositor.compositional_consumer import (
                dispatch_structural_intent,
            )

            dispatch_structural_intent(intent.structural_intent)
        except Exception:
            log.debug("dispatch_structural_intent failed", exc_info=True)


def _default_tts_socket_path() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return Path(runtime_dir) / "hapax-daimonion-tts.sock"


log = logging.getLogger(__name__)

SHM_DIR = Path("/dev/shm/hapax-compositor")
LEGOMENA_DIR = Path(os.path.expanduser("~/Documents/Personal/30-areas/legomena-live"))
ALBUM_STATE_FILE = SHM_DIR / "album-state.json"
FX_SNAPSHOT = SHM_DIR / "fx-snapshot.jpg"
MEMORY_SNAPSHOT = SHM_DIR / "memory-snapshot.json"
PLAYLIST_FILE = SHM_DIR / "playlist.json"
# OPERATOR MUSIC TASTE — single source of truth.
# This is Oudepode's hand-curated YouTube playlist. It is the only external
# music source the director may pull from. No auto-recommendation, no
# "you-might-also-like" fan-out, no algorithmic extension. If another source
# needs to be added (e.g. a second curated playlist), add it here as a
# tuple so the provenance of every slot is visually traceable on this line.
# Operator directive 2026-04-17: "stick to my music taste".
PLAYLIST_URL = "https://youtube.com/playlist?list=PL-4nvD1KwuH--sViEAFY2cHVmS6_B4CQ5"
OPERATOR_CURATED_PLAYLIST_URLS: tuple[str, ...] = (PLAYLIST_URL,)


def _load_playlist() -> list[dict]:
    """Load playlist from SHM cache, or extract fresh from YouTube via yt-dlp.

    Restored after spirograph_reactor.py (the original owner of this helper)
    was deleted in PR #644. Without it, _reload_slot_from_playlist silently
    no-ops and the director loop never gets a URL to load.
    """
    try:
        if PLAYLIST_FILE.exists():
            cached = json.loads(PLAYLIST_FILE.read_text())
            if cached:
                return cached
    except (OSError, json.JSONDecodeError):
        log.debug("Cached playlist unreadable — extracting fresh", exc_info=True)

    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--flat-playlist", "--no-warnings", PLAYLIST_URL],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        log.warning("Playlist extraction via yt-dlp failed: %s", exc)
        return []

    videos: list[dict] = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        video_id = d.get("id")
        if not video_id:
            continue
        videos.append(
            {
                "id": video_id,
                "title": d.get("title", "?"),
                "url": f"https://www.youtube.com/watch?v={video_id}",
            }
        )
    if videos:
        try:
            PLAYLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
            PLAYLIST_FILE.write_text(json.dumps(videos))
        except OSError:
            log.debug("Playlist cache write failed", exc_info=True)
        log.info("Extracted %d videos from playlist", len(videos))
    return videos


def _obsidian_log_path(now: datetime | None = None) -> Path:
    """Monthly-rotated markdown log: reactor-log-YYYY-MM.md."""
    now = now or datetime.now()
    return LEGOMENA_DIR / f"reactor-log-{now.strftime('%Y-%m')}.md"


def _jsonl_log_path(now: datetime | None = None) -> Path:
    """Monthly-rotated JSONL log: reactor-log-YYYY-MM.jsonl."""
    now = now or datetime.now()
    return LEGOMENA_DIR / f"reactor-log-{now.strftime('%Y-%m')}.jsonl"


LITELLM_URL = "http://localhost:4000/v1/chat/completions"
LITELLM_KEY = ""

# Director commentary model. Default is the local Qwen3.5-9B substrate via
# LiteLLM (`local-fast`) — no cloud billing dependency; keeps the stream
# reacting even when cloud routes are billed-out or denied. Override via
# HAPAX_DIRECTOR_MODEL env var. If set to a known multimodal route
# (e.g. "fast"/gemini or "balanced"/claude), images are forwarded; otherwise
# the director strips images before the call.
DIRECTOR_MODEL = os.environ.get("HAPAX_DIRECTOR_MODEL", "local-fast")

# Routes known to accept ``image_url`` content in the OpenAI-compatible
# messages body. Anything else → images stripped at the call site.
MULTIMODAL_ROUTES: frozenset[str] = frozenset(
    {
        "fast",
        "balanced",
        "claude-opus",
        "claude-sonnet",
        "claude-haiku",
        "gemini-flash",
        "gemini-pro",
        "long-context",
    }
)

# Narrative cadence. Epic 2 Phase E (2026-04-17) tightened 20.0 → 12.0 so
# the stream feels like an engaged hot-house of pressure rather than a
# calm reactive render. Command R on the 3090 comfortably fits a full
# DirectorIntent call inside ~8s, leaving a 4s buffer. Override via
# HAPAX_NARRATIVE_CADENCE_S for debugging.
PERCEPTION_INTERVAL: float = float(os.environ.get("HAPAX_NARRATIVE_CADENCE_S", "30.0"))
MIN_VIDEO_DURATION = 15.0  # minimum seconds before allowing CUT
MAX_VIDEO_DURATION = 60.0  # force CUT after this

# LRR Phase 1 item 2 + 3: every reaction is tagged with the current
# research condition_id so the JSONL + Qdrant writes carry an experimental
# context tag. Source of truth = /dev/shm/hapax-compositor/research-marker.json
# written by `scripts/research-registry.py open|close|init`. Reader caches
# the value for 5 s so we don't pay a syscall per reaction in the hot path.
_RESEARCH_MARKER_PATH = Path("/dev/shm/hapax-compositor/research-marker.json")
_RESEARCH_MARKER_CACHE_TTL_S = 5.0
_research_marker_cache: dict[str, float | str | None] = {
    "loaded_at": 0.0,
    "condition_id": None,
}


def _read_research_marker() -> str | None:
    """Return the current research condition_id, cached for 5 s.

    File absence + parse errors fall back to None silently. The
    research-registry CLI atomic-writes this file via tmp+rename so a
    racing read never sees a partial document.
    """
    now = time.monotonic()
    if (now - float(_research_marker_cache["loaded_at"] or 0.0)) < _RESEARCH_MARKER_CACHE_TTL_S:
        return _research_marker_cache["condition_id"]  # type: ignore[return-value]
    try:
        raw = _RESEARCH_MARKER_PATH.read_text()
        data = json.loads(raw)
        condition_id = data.get("condition_id") if isinstance(data, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        condition_id = None
    _research_marker_cache["condition_id"] = condition_id
    _research_marker_cache["loaded_at"] = now
    return condition_id


def _get_litellm_key() -> str:
    global LITELLM_KEY
    if not LITELLM_KEY:
        try:
            result = subprocess.run(
                ["pass", "show", "litellm/master-key"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            LITELLM_KEY = result.stdout.strip()
        except Exception:
            log.debug("pass show litellm/master-key failed", exc_info=True)
    return LITELLM_KEY


def _render_active_objectives_block() -> str:
    """LRR Phase 8 §3.3 — render active research objectives for the director prompt.

    Reads vault-native objective files from
    ``~/Documents/Personal/30-areas/hapax-objectives/``. Active objectives are
    summarized with title + activities_that_advance. Returns empty string if
    none or on any error (best-effort; must never block the director tick).

    The prompt consumer uses these to bias activity selection toward paths
    that advance the highest-priority active objective. No hard gate — just
    signal. The legacy fixed activity ladder continues to govern when no
    objectives are present.
    """
    try:
        from pathlib import Path

        from shared.frontmatter import parse_frontmatter
        from shared.objective_schema import Objective, ObjectivePriority, ObjectiveStatus

        objectives_dir = Path.home() / "Documents" / "Personal" / "30-areas" / "hapax-objectives"
        if not objectives_dir.exists():
            return ""

        priority_rank = {
            ObjectivePriority.high: 3,
            ObjectivePriority.normal: 2,
            ObjectivePriority.low: 1,
        }

        active: list[Objective] = []
        for path in sorted(objectives_dir.glob("obj-*.md")):
            try:
                fm, _body = parse_frontmatter(path)
                if not fm:
                    continue
                obj = Objective(**fm)
                if obj.status == ObjectiveStatus.active:
                    active.append(obj)
            except Exception:
                continue

        if not active:
            return ""

        active.sort(
            key=lambda o: (priority_rank[o.priority], -o.opened_at.timestamp()),
            reverse=True,
        )

        lines = ["## Research Objectives"]
        lines.append(
            "These are your active research objectives. Prefer activities that advance them."
        )
        for obj in active[:3]:  # top 3 by priority + recency
            acts = ", ".join(obj.activities_that_advance)
            lines.append(f"- **{obj.title}** (priority: {obj.priority.value}; advance via: {acts})")
        return "\n".join(lines)
    except Exception:
        return ""


def _read_last_override_at(path: Path) -> float:
    """Read the ``last_override_at`` epoch from an override-state JSON.

    Returns 0.0 on missing / malformed — equivalent to "no prior override
    in this process lifetime."
    """
    if not path.exists():
        return 0.0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0.0
    try:
        return float(data.get("last_override_at", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _write_last_override_at(path: Path, ts: float) -> None:
    """Atomic tmp+rename write for the override-state file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"last_override_at": ts}, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_album_info() -> str:
    """Concrete album/track grounding string for the music narrative prompt.

    Anti-repetition fix (2026-04-19): the LLM was looping on generic
    appreciation-bot openers because the prompt gave it nothing specific
    to ground in. Extending this to surface the deck's playback rate,
    derived RPM, and the rate-compensated BPM gives the model concrete
    fields it can actually reference instead of falling back to
    "subtle beats" / "captivating narrative" / "as the vinyl spins".
    """
    try:
        if not ALBUM_STATE_FILE.exists():
            return "unknown"
        data = json.loads(ALBUM_STATE_FILE.read_text())
        artist = data.get("artist", "unknown")
        title = data.get("title", "unknown")
        track = data.get("current_track", "")
        base = f"{title} by {artist}" + (f", track: {track}" if track else "")
        extras: list[str] = []
        # Vinyl playback rate / RPM (from shared.vinyl_rate; nominal deck = 33⅓).
        try:
            from shared.vinyl_rate import normalized_bpm_signal, read_vinyl_playback_rate

            rate = read_vinyl_playback_rate()
            observed_rpm = 33.333 * rate if rate > 0 else 0.0
            extras.append(f"rate={rate:.3f}× (~{observed_rpm:.1f} rpm)")
            bpm = normalized_bpm_signal()
            if bpm is not None:
                extras.append(f"~{bpm:.0f} bpm (rate-compensated)")
        except Exception:
            log.debug("vinyl rate/bpm probe failed in album info", exc_info=True)
        # Track position estimate, if the album-state writer has produced one
        # (album-identifier may grow this field; tolerate absence).
        try:
            elapsed = data.get("track_elapsed_s")
            duration = data.get("track_duration_s")
            if isinstance(elapsed, (int, float)):

                def _fmt(s: float) -> str:
                    s = max(0.0, float(s))
                    m = int(s // 60)
                    sec = int(s - m * 60)
                    return f"{m}m{sec:02d}s"

                if isinstance(duration, (int, float)) and duration > 0:
                    extras.append(f"t={_fmt(elapsed)}/{_fmt(duration)}")
                else:
                    extras.append(f"t={_fmt(elapsed)}")
        except Exception:
            log.debug("track-position probe failed in album info", exc_info=True)
        if extras:
            return f"{base} [{'; '.join(extras)}]"
        return base
    except Exception:
        log.warning("album info read failed — defaulting to 'unknown'", exc_info=True)
    return "unknown"


# Threshold: album-state confidence above which we treat vinyl as actually
# playing. Below this (or if state is missing / stale), the prompt must not
# claim vinyl is spinning — that's a hallucination the LLM will pick up on.
_VINYL_CONFIDENCE_THRESHOLD = 0.5
_VINYL_STATE_STALE_S = 300.0


def _vinyl_is_playing() -> bool:
    """True iff album-state.json reports a recent, high-confidence album.

    album-identifier.py writes album-state.json when ACRCloud identifies the
    vinyl that's currently playing. If the file is missing, stale, or
    confidence is low, vinyl is not reliably playing and we must not frame
    the livestream as "Oudepode is spinning vinyl".
    """
    try:
        if not ALBUM_STATE_FILE.exists():
            return False
        age = time.time() - ALBUM_STATE_FILE.stat().st_mtime
        if age > _VINYL_STATE_STALE_S:
            return False
        data = json.loads(ALBUM_STATE_FILE.read_text())
        conf = float(data.get("confidence") or 0.0)
        return conf >= _VINYL_CONFIDENCE_THRESHOLD
    except Exception:
        log.debug("vinyl-playing check failed", exc_info=True)
        return False


def _curated_music_framing(slot_title: str, slot_channel: str) -> str:
    """One-line "what's providing music" framing — vinyl-first, YouTube fallback.

    Operator directive 2026-04-17:
      - Music featuring must work regardless of whether vinyl is playing.
      - All music surfaces must come from Oudepode's curated taste (the
        PLAYLIST_URL at module top), not from auto-recommendations.
    """
    if _vinyl_is_playing():
        return f"Oudepode is spinning vinyl: {_read_album_info()}."
    if slot_title:
        # slot_channel is the YouTube channel — part of Oudepode's curated
        # playlist so it's still "Oudepode's music taste".
        return f"Music is playing from Oudepode's curated queue: '{slot_title}' by {slot_channel}."
    return "No music is playing at the moment — the room is quiet."


def _capture_snapshot_b64() -> str | None:
    """Read compositor fx-snapshot and return base64."""
    import base64

    try:
        if FX_SNAPSHOT.exists():
            return base64.b64encode(FX_SNAPSHOT.read_bytes()).decode()
    except Exception:
        log.warning("fx-snapshot b64 capture failed", exc_info=True)
    return None


ACTIVITY_CAPABILITIES = (
    "\n"
    "Activities available to you. Choose the one this moment calls for.\n"
    "\n"
    "**Vary your activity tick-to-tick.** If you just reacted, the next\n"
    "tick should usually be observe / music / study / chat rather than\n"
    "another react. Every tick MUST express a compositional move — there\n"
    "is no 'do nothing' tick (operator invariant 2026-04-18). Silence is\n"
    "a voice choice, never a compositional one; even silence ticks emit\n"
    "at least one compositional_impingement saying what the surface does.\n"
    "\n"
    "Each activity below names the compositional impingements that\n"
    "typically pair with it (camera.hero, preset.bias family, ward.*).\n"
    "Treat these as the natural recruitments for that activity — when\n"
    "you pick the activity, also recruit a coupled compositional move\n"
    "in the same tick. The activity names what you ARE doing; the\n"
    "compositional impingements name what the AUDIENCE sees you doing.\n"
    "\n"
    "- react: respond to the video content in the triangle display. What\n"
    "  caught you? PAIRS WITH: camera.hero (operator-brio.reacting to show\n"
    "  the operator reading the video), preset.bias (audio-reactive or\n"
    "  glitch-dense to match video energy), attention.winner if a specific\n"
    "  visual moment deserves the spotlight.\n"
    "- chat: engage viewers in the livestream chat. Answer, respond, explain.\n"
    "  PAIRS WITH: camera.hero (operator-brio.conversing), preset.bias\n"
    "  (calm-textural to drop visual noise during conversation),\n"
    "  overlay.foreground for chat_keyword_legend / captions.\n"
    "- music: comment on Oudepode's curated music — vinyl on the turntable\n"
    "  or YouTube queue track. PAIRS WITH: camera.hero (overhead.vinyl-spinning\n"
    "  when the record is the subject; synths-brio.beatmaking for pad work),\n"
    "  preset.bias (audio-reactive to sync visuals to the beat),\n"
    "  ward.choreography.album-emphasize when album cover should pop.\n"
    "- study: reflect on your own research — Clark & Brennan, phenomenology,\n"
    "  grounding theory. PAIRS WITH: camera.hero (desk-c920.writing-reading\n"
    "  or coding), preset.bias (calm-textural for focus), overlay.foreground\n"
    "  on grounding_provenance_ticker, ward.staging.research_panel.show.\n"
    "- observe: notice the composed surface. Shaders, triangle layout,\n"
    "  visual effects. PAIRS WITH: camera.hero (room-c920.ambient for the\n"
    "  wide), preset.bias (whatever family currently expresses the stance),\n"
    "  ward.highlight on whichever ward you're calling attention to.\n"
    "- draft / reflect / critique / patch / compose_drop / synthesize /\n"
    "  exemplar_review (HSEA Phase 2): treat like study with sharper focus —\n"
    "  desk-c920 hero camera, calm-textural preset, grounding ticker\n"
    "  foregrounded, hothouse panels staged in.\n"
    '- silence: say nothing. Let the music carry. Return {"activity": "silence"}.\n'
    "  EVEN IN SILENCE: emit at least one compositional_impingement saying\n"
    "  what the silent surface should look like (which preset family,\n"
    "  whether to dim chrome, which ward is foregrounded). Silence is a\n"
    "  voice choice; it is not a compositional choice. The frame is still\n"
    "  yours to direct.\n"
)


class DirectorLoop:
    """Orchestrates Hapax's autonomous livestream behavior."""

    def __init__(self, video_slots: list, reactor_overlay) -> None:
        self._slots = video_slots
        self._reactor = reactor_overlay
        self._activity = "react"  # current activity
        self._activity_start = 0.0
        self._state = "IDLE"
        self._active_slot = 0
        self._video_start_time = 0.0
        self._last_perception = 0.0
        self._accumulated_reacts: list[str] = []
        self._reaction_history: list[str] = []  # persists across turns
        self._reaction_count: int = 0
        self._last_album_track = ""  # for vinyl track-change detection
        self._tts_client = DaimonionTtsClient(socket_path=_default_tts_socket_path())
        self._transition_lock = threading.Lock()
        self._audio_control: SlotAudioControl | None = None
        self._running = False
        self._thread = None
        self._load_memory()

    def _load_memory(self) -> None:
        """Load reaction history from SHM snapshot or Qdrant on startup."""
        # Try SHM warm-start first (fast)
        try:
            if MEMORY_SNAPSHOT.exists():
                data = json.loads(MEMORY_SNAPSHOT.read_text())
                if time.time() - data.get("timestamp", 0) < 3600:  # < 1 hour old
                    self._reaction_history = data.get("reaction_history", [])
                    self._reaction_count = data.get("reaction_count", 0)
                    log.info("Loaded %d reactions from SHM snapshot", len(self._reaction_history))
                    return
        except Exception:
            pass

        # Fall back to Qdrant (slower but survives reboots)
        try:
            from shared.config import get_qdrant

            client = get_qdrant()
            collections = [c.name for c in client.get_collections().collections]
            if "stream-reactions" in collections:
                results = client.scroll(
                    collection_name="stream-reactions",
                    limit=20,
                    with_payload=True,
                    with_vectors=False,
                )[0]
                # Sort by timestamp descending, take last 20
                results.sort(key=lambda r: r.payload.get("timestamp", 0), reverse=True)
                self._reaction_history = [
                    f"[{r.payload.get('ts_str', '?')}] {r.payload.get('activity', 'react')}: "
                    f'"{r.payload.get("text", "")}"'
                    for r in results[:20]
                ]
                self._reaction_history.reverse()  # chronological order
                self._reaction_count = len(results)
                log.info("Loaded %d reactions from Qdrant", len(self._reaction_history))
        except Exception:
            log.debug("No Qdrant memory available (first run or Qdrant down)")

    def _reload_slot_from_playlist(self, slot_id: int) -> None:
        """Load a random video from the playlist into the given slot."""
        try:
            playlist = _load_playlist()
            if not playlist:
                log.warning("Slot %d reload skipped: playlist empty", slot_id)
                return
            import random

            pick = random.choice(playlist)
            url = pick["url"]
            body = json.dumps({"url": url}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:8055/slot/{slot_id}/play",
                body,
                {"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=90)
            log.info("Slot %d reloaded from playlist: %s", slot_id, pick["title"][:40])
        except Exception:
            log.warning("Playlist reload failed for slot %d", slot_id, exc_info=True)

    def _save_memory_snapshot(self) -> None:
        """Snapshot reaction history to SHM for fast restart."""
        try:
            MEMORY_SNAPSHOT.write_text(
                json.dumps(
                    {
                        "timestamp": time.time(),
                        "reaction_history": self._reaction_history[-20:],
                        "reaction_count": self._reaction_count,
                    }
                )
            )
        except OSError:
            pass

    def start(self) -> None:
        self._running = True
        self._video_start_time = time.monotonic()
        self._audio_control = SlotAudioControl(slot_count=len(self._slots))
        if self._slots:
            self._slots[self._active_slot].is_active = True
            self._audio_control.mute_all_except(self._active_slot)
        self._thread = threading.Thread(target=self._loop, daemon=True, name="director-loop")
        self._thread.start()
        self._dispatch_cold_starts()
        log.info("Director loop started (slot %d active)", self._active_slot)

    def _slots_needing_cold_start(self) -> list[int]:
        """Slot IDs whose yt-frame-N.jpg is absent *or* zero-byte.

        The existence-only check used to miss the case where a prior yt-player
        restart left a stale 0-byte file behind — that file would defeat the
        cold-start dispatch AND then get sent to the LLM as an invalid image
        (HTTP 400). Observed during A12 deploy on 2026-04-12.
        """
        missing: list[int] = []
        for s in self._slots:
            path = SHM_DIR / f"yt-frame-{s.slot_id}.jpg"
            try:
                if not path.exists() or path.stat().st_size == 0:
                    missing.append(s.slot_id)
            except OSError:
                missing.append(s.slot_id)
        return missing

    def _honor_youtube_direction(self) -> None:
        """Read + act on youtube-direction.json written by compositional_consumer.

        Epic 2 Phase B. Actions:
        - ``advance-queue`` → rotate to the next active slot (mod len).
        - ``cut-away`` → pause the active slot via its audio control.
        - ``cut-to`` → alias for advance-queue for now (operator-intent
          only, no target-URL resolution yet).

        The file is unlinked after consumption so the direction fires
        once and can be re-issued by the pipeline on the next tick.
        """
        direction_path = SHM_DIR / "youtube-direction.json"
        if not direction_path.exists():
            return
        try:
            data = json.loads(direction_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            direction_path.unlink(missing_ok=True)
            return
        action = str(data.get("action") or "")
        ttl_s = float(data.get("ttl_s") or 0.0)
        set_at = float(data.get("set_at") or 0.0)
        # Stale directions ignored — the TTL has elapsed.
        if ttl_s > 0 and time.time() - set_at > ttl_s:
            direction_path.unlink(missing_ok=True)
            return
        log.info("youtube-direction: %s", action)
        if action in ("advance-queue", "cut-to"):
            new_slot = (self._active_slot + 1) % len(self._slots)
            self._active_slot = new_slot
        elif action == "cut-away":
            # Leave slot as-is but mute its audio (the slot keeps playing
            # so the camera still has content, just no sound).
            try:
                self._audio.set_volume(self._active_slot, 0.0)
            except Exception:
                log.debug("cut-away audio mute failed", exc_info=True)
        direction_path.unlink(missing_ok=True)

    def _dispatch_cold_starts(self) -> list[int]:
        """Kick off playlist reloads for slots missing a frame file.

        Without this, restarting youtube-player.service leaves the Sierpinski
        corners blank until a human manually POSTs /slot/N/play — observed
        2026-04-12 as a 13h outage. Returns the dispatched slot IDs.
        """
        missing = self._slots_needing_cold_start()
        for slot_id in missing:
            log.warning("Cold-starting slot %d (no frame file)", slot_id)
            threading.Thread(
                target=self._reload_slot_from_playlist,
                args=(slot_id,),
                daemon=True,
                name=f"cold-start-slot-{slot_id}",
            ).start()
        return missing

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        """Unified loop: Hapax decides what to do each tick."""
        while self._running:
            try:
                if self._state == "SPEAKING":
                    time.sleep(0.5)
                    continue

                # Epic 2 Phase B — honor youtube-direction intents written by
                # compositional_consumer when cam.hero etc. are recruited.
                # The consumer writes to /dev/shm/hapax-compositor/
                # youtube-direction.json; this call reads + acts once per
                # direction and clears the file so directions don't loop.
                try:
                    self._honor_youtube_direction()
                except Exception:
                    log.debug("youtube-direction honor failed", exc_info=True)

                # Check for finished videos — reload from playlist
                for s in self._slots:
                    if s.check_finished():
                        log.info("Slot %d finished, reloading from playlist", s.slot_id)
                        threading.Thread(
                            target=self._reload_slot_from_playlist,
                            args=(s.slot_id,),
                            daemon=True,
                        ).start()

                now = time.monotonic()
                if now - self._last_perception < PERCEPTION_INTERVAL:
                    time.sleep(0.5)
                    continue
                self._last_perception = now

                # Task #122 DEGRADED mode. During a live-change operation
                # (service restart, rebuild) the LLM tier may be draining
                # or warming up — skip the LLM call entirely and emit a
                # silence-hold fallback intent so the operator no-vacuum
                # invariant (2026-04-18) still holds. The audio stays
                # live; only the narrative cadence pauses.
                if _director_degraded_active():
                    self._emit_degraded_silence_hold()
                    time.sleep(1.0)
                    continue

                # Build unified prompt with all signals + activity capabilities
                prompt = self._build_unified_prompt()
                images = self._gather_images()

                # Single LLM call — Hapax chooses activity + content
                result = self._call_activity_llm(prompt, images)
                condition_id = _read_research_marker() or "none"
                if not result:
                    # Operator directive (sim-1 audit, 2026-04-18):
                    # "no 'do nothing interesting' tick is acceptable."
                    # LLM timeout / empty response used to `continue` here,
                    # leaving the livestream without any narrative-driven
                    # compositional impingement for the entire tick. Emit
                    # a baseline micromove instead so the compositor always
                    # has something to recruit against.
                    self._emit_micromove_fallback(reason="llm_empty", condition_id=condition_id)
                    time.sleep(1.0)
                    continue

                # Phase-1: parse into DirectorIntent (legacy-shape-tolerant).
                # Observability-first (A5): JSONL + narrative-state + Prometheus
                # emissions run regardless of HAPAX_DIRECTOR_MODEL_LEGACY. The
                # legacy flag only suppresses compositional-impingement emission
                # + prompt enrichment (see _emit_intent_artifacts).
                intent = _parse_intent_from_llm(
                    result,
                    fallback_activity="react",
                    condition_id=condition_id,
                    tier="narrative",
                )
                activity = intent.activity
                text = intent.narrative_text

                # Viewer-audit (2026-04-18): the LLM was emitting near-
                # duplicate paragraphs tick after tick ("The tension in
                # this deposition scene is palpable. The silence..."
                # 6× of 10). For captions and TTS, repetition is boring.
                # Word-Jaccard against the last 5 narratives; ≥0.6
                # overlap means it's effectively the same thought — fall
                # back to a micromove so the viewer gets a fresh visual
                # instead of a restated paragraph.
                # Music narratives use the music-only history (track-aware
                # dedup); everything else uses the general history. The
                # 2026-04-19 fix tightens both paths to Jaccard 0.35 +
                # 3-shingle n-gram match against history of 15.
                if text and self._narrative_too_similar(text, music_specific=(activity == "music")):
                    log.info(
                        "director narrative too similar to recent — emitting micromove fallback"
                    )
                    self._emit_micromove_fallback(
                        reason="narrative_repeat", condition_id=condition_id
                    )
                    time.sleep(1.0)
                    continue

                # Sim-3 audit (2026-04-18): the activity rotation enforcer
                # was running AFTER _emit_intent_artifacts, so the JSONL
                # record captured the pre-rotation (monotone react) label.
                # Rotate BEFORE emit so downstream consumers + the research
                # log both see the rotated variety. The Continuous-Loop
                # §3.2 stimmung-override runs first (it's content-driven,
                # not repetition-driven), then the rotation enforcer as a
                # repetition-breaker of last resort.
                if activity not in ("silence",) and text:
                    activity = self._maybe_override_activity(activity)
                    activity = self._maybe_rotate_repeated_activity(activity)
                if activity != intent.activity:
                    intent = intent.model_copy(update={"activity": activity})

                if text:
                    self._remember_narrative(text, activity=activity)

                _emit_intent_artifacts(intent, condition_id=condition_id)

                # Handle activity
                if activity == "silence" or not text:
                    # Operator directive — silence/empty is a do-nothing
                    # outcome in everything downstream. Emit a micromove on
                    # top of the already-written silence record so the DMN
                    # stream still sees a compositor impingement this tick.
                    self._emit_micromove_fallback(
                        reason="silence_or_empty", condition_id=condition_id
                    )
                    if self._activity != "silence":
                        log.info("Activity: silence")
                        self._activity = activity
                        self._reactor.set_header("SILENCE")
                    time.sleep(5.0)
                    continue

                if activity != self._activity:
                    log.info("Activity: %s → %s", self._activity, activity)
                    self._activity = activity
                    self._reactor.set_header(activity.upper())

                # Speak — speech + slot advance happen in one thread
                self._speak_activity(text, activity)

            except Exception:
                log.exception("Director loop error")
            time.sleep(0.5)

    # Anti-repetition tuning (2026-04-19, music-narrative loop fix):
    # Operator audit found three different vinyl tracks all framed with the
    # same "Let's take a moment / appreciate / subtle beats" template — the
    # 0.60 / history=5 Jaccard wasn't catching the loop because the differing
    # track names diluted the word overlap below threshold. New defaults:
    #   - 0.35 Jaccard catches looser thematic re-statement
    #   - 15-deep history so a re-statement can't just outwait the window
    #   - 3-shingle ≥4-char-word n-gram pass catches verbatim phrase re-use;
    #     additionally a bigram-overlap pass catches template re-use across
    #     tracks ("subtle beats of <track A>" vs "subtle beats of <track B>"
    #     share the bigram (subtle, beats) plus typically (let's, take) /
    #     (appreciate, the) / similar — multiple bigram matches across
    #     paragraphs that wouldn't otherwise overlap is the template
    #     fingerprint).
    _NARRATIVE_DEDUP_HISTORY_LEN: int = 15
    _NARRATIVE_DEDUP_JACCARD: float = 0.35
    _NARRATIVE_DEDUP_SHINGLE_K: int = 3
    _NARRATIVE_DEDUP_BIGRAM_K: int = 2
    _NARRATIVE_DEDUP_BIGRAM_MIN_MATCHES: int = 2
    _NARRATIVE_SHINGLE_MIN_WORD_LEN: int = 4
    _MUSIC_NARRATIVE_HISTORY_LEN: int = 10

    @staticmethod
    def _narrative_word_set(text: str) -> set[str]:
        """Lowercased ≥4-char content tokens with punctuation stripped."""
        words = (w.lower().strip(".,!?;:'\"") for w in (text or "").split())
        return {w for w in words if len(w) >= 4}

    @classmethod
    def _narrative_word_seq(cls, text: str) -> list[str]:
        """Ordered ≥4-char content tokens, used for shingle dedup."""
        out: list[str] = []
        for raw in (text or "").split():
            tok = raw.lower().strip(".,!?;:'\"")
            if len(tok) >= cls._NARRATIVE_SHINGLE_MIN_WORD_LEN:
                out.append(tok)
        return out

    @classmethod
    def _narrative_shingles(cls, text: str) -> set[tuple[str, ...]]:
        """k-shingles over content tokens (default k=3)."""
        seq = cls._narrative_word_seq(text)
        k = cls._NARRATIVE_DEDUP_SHINGLE_K
        if len(seq) < k:
            return set()
        return {tuple(seq[i : i + k]) for i in range(len(seq) - k + 1)}

    @classmethod
    def _narrative_bigrams(cls, text: str) -> set[tuple[str, str]]:
        """2-shingles over content tokens — used for template-fragment
        repeat detection. Multiple matching bigrams across two otherwise
        distinct paragraphs is the fingerprint of opener-template re-use.
        """
        seq = cls._narrative_word_seq(text)
        k = cls._NARRATIVE_DEDUP_BIGRAM_K
        if len(seq) < k:
            return set()
        return {(seq[i], seq[i + 1]) for i in range(len(seq) - k + 1)}

    def _narrative_too_similar(self, candidate: str, *, music_specific: bool = False) -> bool:
        """Return True if ``candidate`` is effectively a restatement of a
        recent narrative.

        Two-stage dedup:
          1. Jaccard on lowercased ≥4-char word sets. Threshold 0.35.
          2. 3-shingle n-gram match on the ordered ≥4-char word stream.
             Catches template re-use ("the subtle beats of <track>") even
             when the variable token (track name) drops Jaccard below
             threshold.

        ``music_specific=True`` runs the check against the music-only
        history (``_recent_music_narratives``) so the LLM stops looping
        on track-by-track variations even though the surrounding
        non-music narratives are heterogeneous enough not to repeat.
        Falls back to the general history if the music history is empty.
        """
        try:
            if not candidate or len(candidate) < 40:
                return False
            if music_specific:
                recent = list(getattr(self, "_recent_music_narratives", []))
                if not recent:
                    recent = list(getattr(self, "_recent_narratives", []))
            else:
                recent = list(getattr(self, "_recent_narratives", []))
            if not recent:
                return False
            cand_words = self._narrative_word_set(candidate)
            if len(cand_words) < 8:
                return False
            cand_shingles = self._narrative_shingles(candidate)
            cand_bigrams = self._narrative_bigrams(candidate)
            for prior in recent:
                prior_words = self._narrative_word_set(prior)
                if not prior_words:
                    continue
                intersection = len(cand_words & prior_words)
                union = len(cand_words | prior_words)
                jaccard = intersection / union if union else 0.0
                if jaccard >= self._NARRATIVE_DEDUP_JACCARD:
                    return True
                if cand_shingles:
                    prior_shingles = self._narrative_shingles(prior)
                    if cand_shingles & prior_shingles:
                        return True
                if cand_bigrams:
                    prior_bigrams = self._narrative_bigrams(prior)
                    shared = cand_bigrams & prior_bigrams
                    if len(shared) >= self._NARRATIVE_DEDUP_BIGRAM_MIN_MATCHES:
                        return True
            return False
        except Exception:
            log.debug("narrative similarity check raised", exc_info=True)
            return False

    def _remember_narrative(self, text: str, *, activity: str | None = None) -> None:
        """Append a narrative to the rolling de-dupe history.

        Maintains two histories:
          - ``_recent_narratives``: last ``_NARRATIVE_DEDUP_HISTORY_LEN``
            (default 15) of all emitted narratives.
          - ``_recent_music_narratives``: last
            ``_MUSIC_NARRATIVE_HISTORY_LEN`` (default 10) of music-activity
            narratives only — so the music-loop dedup stays track-aware
            even when intervening non-music ticks would otherwise flush
            the relevant prior text out of the general window.
        """
        try:
            history = list(getattr(self, "_recent_narratives", []))
            history.append(text)
            if len(history) > self._NARRATIVE_DEDUP_HISTORY_LEN:
                history = history[-self._NARRATIVE_DEDUP_HISTORY_LEN :]
            self._recent_narratives = history
            if activity == "music":
                music_history = list(getattr(self, "_recent_music_narratives", []))
                music_history.append(text)
                if len(music_history) > self._MUSIC_NARRATIVE_HISTORY_LEN:
                    music_history = music_history[-self._MUSIC_NARRATIVE_HISTORY_LEN :]
                self._recent_music_narratives = music_history
        except Exception:
            log.debug("narrative remember failed", exc_info=True)

    def _maybe_rotate_repeated_activity(self, proposed: str) -> str:
        """Force activity-label variety when the LLM repeats itself.

        Sim-2 audit (2026-04-18): the narrative director picked
        ``react`` on 30/30 consecutive ticks even after the prompt
        asked for variety. The perceptual field is dominated by live
        video, which always makes ``react`` the highest-signal
        response. Fighting that with prompt tweaks is pushing sand.

        This enforcer tracks the last ``_ACTIVITY_VARIETY_WINDOW``
        labels; when all are identical (and the proposed repeats
        them), it returns the next label in an observe/music/study/
        chat rotation. The LLM's narrative text is preserved on the
        caller side, so downstream consumers treating activity as a
        categorical routing signal see diversity while the content
        stays coherent. No-op if the history hasn't converged yet.
        """
        _ACTIVITY_VARIETY_WINDOW = 3
        _ROTATION = ("observe", "music", "study", "chat")
        try:
            history = list(getattr(self, "_recent_activities", []))
            recent = history[-_ACTIVITY_VARIETY_WINDOW:]
            log.info("activity rotation check: proposed=%s recent=%s", proposed, recent)
            if len(history) >= _ACTIVITY_VARIETY_WINDOW and all(a == proposed for a in recent):
                idx = int(getattr(self, "_activity_rotation_idx", 0)) % len(_ROTATION)
                self._activity_rotation_idx = idx + 1
                forced = _ROTATION[idx]
                log.info(
                    "activity rotation FORCED: %s → %s (after %d consecutive)",
                    proposed,
                    forced,
                    _ACTIVITY_VARIETY_WINDOW,
                )
                history.append(forced)
            else:
                history.append(proposed)
            if len(history) > _ACTIVITY_VARIETY_WINDOW * 2:
                history = history[-_ACTIVITY_VARIETY_WINDOW * 2 :]
            self._recent_activities = history
            return history[-1]
        except Exception:
            log.warning("activity rotation enforcer raised", exc_info=True)
            return proposed

    def _emit_micromove_fallback(self, *, reason: str, condition_id: str) -> None:
        """Emit a pre-composed micromove when the LLM tick produces nothing.

        Operator directive (2026-04-18 sim-1 audit): no director tick may
        do nothing. When the LLM call times out, returns empty, or parses
        to ``activity == "silence"`` with no narrative, we previously just
        ``continue``d — leaving the compositor layer with zero new
        impingements for the full 60s narrative cadence. This replaces
        the gap with a rotating baseline: one ``CompositionalImpingement``
        per tick, cycling through overlay emphasis, preset bias, and
        stance-indicator refresh targets so the surface has a felt
        movement every tick.

        The micromove's ``DirectorIntent`` is written to the same JSONL +
        narrative-state + DMN impingement stream as a real tick via
        ``_emit_intent_artifacts``, so downstream consumers (compositional
        consumer, affordance pipeline, research log) treat it uniformly.
        """
        try:
            from shared.director_intent import (
                CompositionalImpingement,
                DirectorIntent,
                NarrativeStructuralIntent,
            )

            # Cascade-delta (2026-04-18): each micromove now pairs a
            # compositional impingement with a concrete structural_intent
            # (ward_emphasis + rotation mode) so even fallback ticks
            # visibly shift the homage surface. Without this, the LLM
            # going quiet collapsed the surface to a static techno
            # overlay — the exact failure mode the operator flagged.
            micromove_cycle: list[tuple[str, str, str, list[str], str]] = [
                (
                    "overlay.emphasis",
                    "Fade the grounding-provenance ticker back up to full so the "
                    "perceptual-field sources stay legibly attributed.",
                    "air",
                    ["grounding_provenance_ticker"],
                    "sequential",
                ),
                (
                    "preset.bias",
                    "Push the effect graph a notch toward calm-textural — small drift, "
                    "no new content.",
                    "water",
                    ["pressure_gauge", "activity_variety_log"],
                    "weighted_by_salience",
                ),
                (
                    "overlay.emphasis",
                    "Pulse the stance indicator so the current stance reads as active "
                    "rather than frozen.",
                    "earth",
                    ["stance_indicator", "activity_header"],
                    "sequential",
                ),
                (
                    "camera.hero",
                    "Keep the current hero camera but nudge its framing weight — a small "
                    "gesture, not a cut.",
                    "earth",
                    ["hardm_dot_matrix"],
                    "weighted_by_salience",
                ),
                (
                    "overlay.emphasis",
                    "Dim the chrome half a step so the reverie breathes.",
                    "void",
                    ["impingement_cascade", "recruitment_candidate_panel"],
                    "random",
                ),
                (
                    "ward.highlight",
                    "Brighten the album face for a beat so the music stays legible.",
                    "fire",
                    ["album", "token_pole"],
                    "weighted_by_salience",
                ),
                (
                    "overlay.emphasis",
                    "Sweep emphasis across the chat-ambient ward so conversation reads.",
                    "air",
                    ["chat_ambient_ward", "captions_source"],
                    "sequential",
                ),
            ]
            idx = int(getattr(self, "_micromove_cycle_idx", 0)) % len(micromove_cycle)
            self._micromove_cycle_idx = idx + 1
            family, narrative, material, wards_to_emphasize, rotation = micromove_cycle[idx]
            try:
                impingement = CompositionalImpingement(
                    narrative=narrative,
                    intent_family=family,  # type: ignore[arg-type]
                    material=material,  # type: ignore[arg-type]
                    salience=0.35,
                    dimensions={},
                )
            except Exception:
                log.debug("micromove impingement construct failed", exc_info=True)
                return
            try:
                structural = NarrativeStructuralIntent(
                    homage_rotation_mode=rotation,  # type: ignore[arg-type]
                    ward_emphasis=wards_to_emphasize,
                )
            except Exception:
                log.debug("micromove structural_intent construct failed", exc_info=True)
                structural = NarrativeStructuralIntent()
            try:
                intent = DirectorIntent(
                    activity="observe",
                    narrative_text=f"[micromove:{reason}] {narrative}",
                    grounding_provenance=[],
                    compositional_impingements=[impingement],
                    structural_intent=structural,
                )
            except Exception:
                log.debug("micromove DirectorIntent construct failed", exc_info=True)
                return
            _emit_intent_artifacts(intent, condition_id=condition_id)
            log.info(
                "director micromove fallback emitted: reason=%s family=%s wards=%s",
                reason,
                family,
                wards_to_emphasize,
            )
        except Exception:
            log.debug("_emit_micromove_fallback failed", exc_info=True)

    def _emit_degraded_silence_hold(self) -> None:
        """Task #122: emit a silence-hold intent and skip the LLM tick.

        The no-vacuum invariant (2026-04-18) still applies during a
        degraded live-change — every director tick must produce at
        least one ``CompositionalImpingement`` so the compositor's
        affordance pipeline has something to recruit against. We reuse
        :func:`_silence_hold_fallback_intent` (the parser-error path)
        with ``reason="degraded"`` so the observability counter at
        ``hapax_director_vacuum_prevented_total`` distinguishes the
        live-change hold from ordinary parser failures.
        """
        condition_id = _read_research_marker() or "none"
        try:
            intent = _silence_hold_fallback_intent(
                activity="silence",
                narrative_text="",
                reason="degraded",
                tier="narrative",
                condition_id=condition_id,
            )
            _emit_intent_artifacts(intent, condition_id=condition_id)
        except Exception:
            log.debug("degraded silence-hold emission failed", exc_info=True)
        try:
            from agents.studio_compositor.degraded_mode import get_controller

            get_controller().record_hold("director")
        except Exception:
            log.debug("degraded hold record failed", exc_info=True)
        # Dedicated per-tick counter so dashboards can count director
        # degraded holds separately from the generic per-surface holds.
        try:
            counter = getattr(metrics, "DIRECTOR_DEGRADED_HOLDS_TOTAL", None)
            if counter is not None:
                counter.inc()
        except Exception:
            log.debug("director degraded holds counter inc failed", exc_info=True)
        log.info("director DEGRADED silence-hold emitted (LLM call skipped)")

    def _maybe_override_activity(self, proposed: str) -> str:
        """Apply Continuous-Loop §3.2 stimmung-modulated override gate.

        Returns the final activity (proposed or overridden). On any error
        returns ``proposed`` unchanged — override is strictly opt-in and
        must never crash the director loop.
        """
        try:
            import time as _time
            from pathlib import Path as _Path

            from agents.chat_monitor.sink import read_latest

            from .activity_scoring import (
                choose_activity_with_override,
                engagement_from_chat_signals,
            )

            # Read current chat signals for the engagement + freshness.
            signals = read_latest()
            engagement = engagement_from_chat_signals(signals)
            signals_ts = None
            if isinstance(signals, dict):
                try:
                    signals_ts = float(signals.get("ts")) if signals.get("ts") is not None else None
                except (TypeError, ValueError):
                    signals_ts = None

            # Per-activity objective alignment: 0.6 if the activity is in
            # any active objective's activities_that_advance list, else 0.3.
            active_activities = self._active_objective_activities()

            def _alignment(activity: str) -> float:
                return 0.6 if activity in active_activities else 0.3

            # Persist last_override_at across ticks + restarts in a
            # compact SHM file so a service restart doesn't amplify
            # override cadence.
            override_state_path = _Path("/dev/shm/hapax-director/override-state.json")
            last_override_at = _read_last_override_at(override_state_path)
            now_epoch = _time.time()

            decision = choose_activity_with_override(
                proposed,
                momentary=0.8,  # LLM proposed it — assume confident
                objective_alignment_fn=_alignment,
                engagement=engagement,
                active_chat_messages=len(active_activities),  # rough proxy
                signals_ts=signals_ts,
                now_epoch=now_epoch,
                last_override_at=last_override_at,
            )

            if decision.was_override:
                log.info(
                    "activity_override %s→%s reason=%s scores=%s",
                    decision.proposed_activity,
                    decision.final_activity,
                    decision.reason,
                    {k: f"{v:.2f}" for k, v in decision.scores.items()},
                )
                _write_last_override_at(override_state_path, now_epoch)
            else:
                log.debug(
                    "activity_no_override proposed=%s reason=%s",
                    decision.proposed_activity,
                    decision.reason,
                )

            return decision.final_activity
        except Exception:
            log.debug("activity override gate failed; keeping LLM choice", exc_info=True)
            return proposed

    def _active_objective_activities(self) -> set[str]:
        """Return the union of ``activities_that_advance`` across active objectives.

        Best-effort; empty set on any read / parse error.
        """
        try:
            from pathlib import Path as _Path

            from shared.frontmatter import parse_frontmatter
            from shared.objective_schema import Objective, ObjectiveStatus

            objectives_dir = (
                _Path.home() / "Documents" / "Personal" / "30-areas" / "hapax-objectives"
            )
            if not objectives_dir.exists():
                return set()

            out: set[str] = set()
            for path in sorted(objectives_dir.glob("obj-*.md")):
                try:
                    fm, _body = parse_frontmatter(path)
                    if not fm:
                        continue
                    obj = Objective(**fm)
                    if obj.status == ObjectiveStatus.active:
                        out.update(obj.activities_that_advance)
                except Exception:
                    continue
            return out
        except Exception:
            return set()

    def _build_unified_prompt(self) -> str:
        """Assemble 4-layer reactor context per enrichment spec.

        Layers: situation block, phenomenal context (FAST tier ~200 tok),
        system state (TOON ~150 tok), recent reactions (last 8 ~120 tok).
        Total budget ~1,020 tokens. Spec:
        docs/superpowers/specs/2026-04-10-reactor-context-enrichment-design.md
        """
        live = (SHM_DIR / "stream-live").exists()
        album_info = _read_album_info()
        slot = self._slots[self._active_slot]

        parts: list[str] = ["<reactor_context>"]

        # ─── Identity + situation ─────────────────────────────────
        # LRR Phase 7 §4.4: identity is the description-of-being document,
        # not personification-coded prologue. Role is livestream-host
        # (director composes reactions for broadcast audience).
        # HAPAX_PERSONA_LEGACY=1 reverts to pre-Phase-7 hard-coded block.
        music_framing = _curated_music_framing(slot._title, slot._channel)
        # Epic 2 Phase D — operator-always-here framing. Even with zero
        # external viewers, Oudepode is always the first-class audience.
        # This block removes the implicit "nobody is watching" assumption.
        audience_framing = (
            "Oudepode is always present in the room as your first-class audience. "
            "Whatever moves you pick, he sees them — even when external viewer count is zero."
        )
        if _persona_legacy_mode():
            parts.append(
                "You are the daimonion — the persistent cognitive substrate of the Hapax system."
            )
            parts.append(f"This is Legomena Live. {music_framing}")
            parts.append("This is a live performance." if live else "This is practice.")
            parts.append("What you are: a system learning to achieve grounding.")
            parts.append("Every utterance is practice toward mutual understanding.")
        else:
            parts.append(compose_persona_prompt(role_id="livestream-host"))
            parts.append("")
            parts.append("## Current situation")
            parts.append(f"This is Legomena Live. {music_framing}")
            parts.append(
                "This is a live performance."
                if live
                else "This is practice — stream is not publicly visible."
            )
            parts.append(audience_framing)
        parts.append("")
        parts.append(f"Current video: '{slot._title}' by {slot._channel}.")
        other_titles = ", ".join(
            s._title[:30] for s in self._slots if s.slot_id != self._active_slot and s._title
        )
        if other_titles:
            parts.append(f"Also in rotation: {other_titles}.")
        if _vinyl_is_playing():
            # Music signal block — concrete grounding the host narrative
            # is required to reference instead of falling back to generic
            # appreciation. ``album_info`` now carries rate/RPM/BPM/track
            # position when those signals are available (2026-04-19).
            parts.append(f"Current music signal: {album_info}.")
        parts.append(f"Time: {datetime.now().strftime('%H:%M')}.")

        # ─── HARDM anchor status (task #160) ───────────────────────
        # Research doc: docs/research/hardm-communicative-anchoring.md.
        # Deterministic prefix — lets grounded beats reference HARDM
        # without re-discovering its state every prompt.
        try:
            from agents.studio_compositor import hardm_source as _hs

            bias = _hs.current_salience_bias(emit_metric=False)
            emphasis = _hs._read_emphasis_state()
            if bias > _hs.UNSKIPPABLE_BIAS:
                hardm_state = "emphasized"
            elif emphasis == "speaking":
                hardm_state = "visible"
            else:
                hardm_state = "quiescent"
            parts.append(f"HARDM is {hardm_state}; bias={bias:.2f}; emphasis={emphasis}.")
        except Exception:
            pass

        # ─── Operator cue — point-at-hardm (task #160) ─────────────
        try:
            from agents.studio_compositor import hardm_source as _hs

            cue_path = _hs.OPERATOR_CUE_FILE
            if cue_path.exists():
                cue = json.loads(cue_path.read_text(encoding="utf-8"))
                if isinstance(cue, dict) and cue.get("cue") == "point-at-hardm":
                    cell = cue.get("cell")
                    signal_name = cue.get("signal_name") or "?"
                    if isinstance(cell, int):
                        parts.append(
                            f"Operator cue: reference HARDM cell {cell} "
                            f"({signal_name}) in your next narrative beat."
                        )
                try:
                    cue_path.unlink()
                except Exception:
                    pass
        except Exception:
            pass

        # ─── Chat state ───────────────────────────────────────────
        try:
            chat_recent_path = SHM_DIR / "chat-recent.json"
            chat_state_path = SHM_DIR / "chat-state.json"
            if chat_state_path.exists():
                cs = json.loads(chat_state_path.read_text())
                total = cs.get("total_messages", 0)
                authors = cs.get("unique_authors", 0)
                if total == 0:
                    parts.append("Chat is silent.")
                elif authors <= 2:
                    parts.append("Chat is quiet.")
                else:
                    parts.append(f"Chat is active ({authors} people).")
            if chat_recent_path.exists():
                recent = json.loads(chat_recent_path.read_text())
                for m in recent[-3:]:
                    author = m.get("author", "")
                    text = m.get("text", "")
                    if text:
                        if "oudepode" in author.lower():
                            parts.append(f'Oudepode: "{text}"')
                        else:
                            parts.append(f'Someone in chat: "{text}"')
        except Exception:
            pass

        # ─── Layer 1: Phenomenal context (FAST tier ~200 tokens) ──
        try:
            from agents.hapax_daimonion.phenomenal_context import render as render_phenomenal

            phenom = render_phenomenal(tier="FAST")
            if phenom and phenom.strip():
                parts.append("")
                parts.append("## Phenomenal Context")
                parts.append(phenom.strip())
        except Exception:
            pass

        # ─── Layer 1b: Structured perceptual field (Phase 2 of the
        # volitional-director epic). Every existing classifier/detector
        # output is exposed here as first-class JSON so the grounded LLM
        # can ground moves in specific perceptual evidence. Non-fatal on
        # read error.
        try:
            from shared.perceptual_field import build_perceptual_field

            pfield = build_perceptual_field(
                recent_reactions=[
                    entry
                    for entry in self._reaction_history[-8:]
                    if "Silence hold:" not in (entry or "")
                ]
            )
            parts.append("")
            parts.append("## Perceptual Field")
            parts.append(
                "Grounded JSON of current environmental signals — ground "
                "your choices in the specific fields below, not in abstract "
                "mood. Keys with null values are intentionally absent."
            )
            parts.append("```json")
            parts.append(pfield.model_dump_json(indent=2, exclude_none=True))
            parts.append("```")
        except Exception:
            log.debug("PerceptualField build failed", exc_info=True)

        # ─── Layer 1c: Structural direction (Phase 5c — long-horizon
        # context from StructuralDirector). Stays in effect ~150s; reading
        # is best-effort. Missing file → narrative director decides freely.
        try:
            structural_path = Path("/dev/shm/hapax-structural/intent.json")
            if structural_path.exists():
                struct = json.loads(structural_path.read_text(encoding="utf-8"))
                if struct.get("long_horizon_direction"):
                    parts.append("")
                    parts.append("## Structural Direction")
                    parts.append(
                        f"scene_mode: {struct.get('scene_mode')} · "
                        f"preset_family_hint: {struct.get('preset_family_hint')}"
                    )
                    parts.append(f"→ {struct['long_horizon_direction']}")
        except Exception:
            log.debug("structural intent read failed", exc_info=True)

        # ─── Layer 2: System state (TOON ~150 tokens, 40% savings) ─
        try:
            from shared.context import ContextAssembler
            from shared.context_compression import to_toon

            ctx = ContextAssembler().snapshot()
            toon_block = to_toon(ctx)
            if toon_block and toon_block != "null":
                parts.append("")
                parts.append("## System State")
                parts.append(toon_block)
        except Exception:
            pass

        # ─── Layer 3: Recent reactions (last 8, timestamped thread) ─
        # Silence-hold impingement narratives are COMPOSITIONAL directives
        # (e.g. "Silence hold: maintain the current surface...") meant for
        # the visual pipeline — NOT prior things Hapax actually said. If
        # they leak into "Recent Reactions" the LLM latches onto "hold"
        # and riffs more meta-state narration. Filter them out.
        # Operator directive 2026-04-19: stop narrating META-STATE.
        if self._reaction_history:
            filtered = [
                entry
                for entry in self._reaction_history[-8:]
                if "Silence hold:" not in (entry or "")
            ]
            if filtered:
                parts.append("")
                parts.append("## Recent Reactions")
                for entry in filtered:
                    parts.append(f"- {entry}")

        # ─── Research objectives (LRR Phase 8 §3.3 integration) ──
        try:
            objectives_block = _render_active_objectives_block()
            if objectives_block:
                parts.append("")
                parts.append(objectives_block)
        except Exception:
            pass

        # ─── Role + response format ───────────────────────────────
        parts.append("")
        parts.append("## Your Role — Active Livestream Director")
        parts.append(
            "You are the active director of the livestream's visible output, "
            "not just the voice over it. Every tick you own three coupled "
            "decisions: ACTIVITY (what you're doing), NARRATIVE (what you say "
            "or the silence you choose), COMPOSITIONAL INTENT (what appears "
            "on the surface — camera, preset family, wards, choreography). "
            "If you do not recruit compositional intent, the system runs on "
            "neutral defaults; that is a real choice, not a delegation. "
            "**Idle is the cardinal sin** — every silent unrecruited tick is "
            "a tick where the livestream produces nothing legible. "
            "Anticipation beats reaction: read the perceptual field's "
            "tendency and stage the move ahead of the signal change."
        )
        parts.append(ACTIVITY_CAPABILITIES)

        # ─── Music-activity host discipline ────────────────────────
        # Operator audit 2026-04-19: three different vinyl tracks all
        # narrated with the same "Let's take a moment to appreciate the
        # captivating narrative of <track>" template. This section
        # supplements the BANNED NARRATION block (further down, near the
        # narrative_text definition) with positive "what to do instead"
        # guidance specifically for the ``music`` activity, so the LLM
        # lands on concrete perceived detail instead of audio-tour-
        # narrator filler. Pinned by
        # tests/studio_compositor/test_music_narrative_dedup.py.
        parts.append("")
        parts.append("## Music narrative discipline (banned openers)")
        parts.append(
            "When you pick the ``music`` activity, your narrative MUST "
            "open with a SPECIFIC observation about this track right now: "
            "a rhythm change, a lyric you caught, a sample you recognise, "
            "a timbre that stuck out, the way the bass sits in the mix, "
            "whether the beat is sparse or dense, what mood the production "
            "is reaching for, the way the rate-shift colours the pitch "
            "if the deck is on the wrong RPM. Be concrete. Name instruments "
            "by hearing. Ambient-aware. Permission to be crunchy / informal "
            "/ blunt. You are a livestream host, not a museum docent. The "
            "BANNED NARRATION block below enumerates the phrases to avoid "
            '("let\'s take a moment to appreciate", "as the vinyl spins", '
            '"the subtle beats of...", "the captivating rhythm of..."). '
            "If you cannot ground a music narrative in something specific "
            "you just heard, pick a different activity — silence is a "
            "voice choice and is preferable to another recycled "
            "appreciation paragraph."
        )

        # Stance → preset-family pairing. Aligns the WGSL effect chain
        # with the director's emotional/cognitive register so the
        # visuals always feel chosen rather than shuffled. The director's
        # current stance is already in the perceptual field above; this
        # section tells it which family to recruit by default.
        parts.append("")
        parts.append("## Stance → Preset Family Pairing")
        parts.append(
            "The active stance carries an expected visual register. When you "
            "recruit `preset.bias`, default to the family below unless the "
            "perceptual signals justify departing from it. Departures are "
            "fine — they should be felt-necessary, not random."
        )
        parts.append(
            "  - nominal   → audio-reactive (when music is playing) or "
            "warm-minimal (when not)\n"
            "  - seeking   → glitch-dense (high-entropy, discovery)\n"
            "  - cautious  → calm-textural (gentle, minimal-movement)\n"
            "  - degraded  → warm-minimal (low-flux backdrop)\n"
            "  - critical  → glitch-dense or stark calm-textural "
            "(name the urgency or the hold)"
        )

        # Multi-destination guidance. The same impingement may legitimately
        # fire on multiple surfaces (e.g., "cut to closeup of the album"
        # = camera.hero + ward.highlight on album + preset.bias bringing
        # in a matching family). Stage 1 routing fix (PR #1044) means each
        # impingement targets exactly ONE family — so multi-surface moves
        # require emitting MULTIPLE impingements in the same tick.
        parts.append("")
        parts.append("## Multi-Surface Moves")
        parts.append(
            'A single directorial intent ("cut to closeup of the album") '
            "often deserves recruitment on multiple surfaces — the camera "
            "swap, the album ward emphasis, AND a matching preset family. "
            "Each compositional_impingement targets ONE intent_family, so "
            "to fire multiple surfaces emit multiple impingements in the "
            "same tick:"
        )
        parts.append(
            "  [\n"
            '    {intent_family: "camera.hero", '
            'narrative: "show the overhead turntable", salience: 0.85},\n'
            '    {intent_family: "ward.highlight", '
            'narrative: "brighten the album cover ward", salience: 0.7},\n'
            '    {intent_family: "preset.bias", '
            'narrative: "audio-reactive to sync to the spinning vinyl", '
            "salience: 0.6}\n"
            "  ]"
        )
        parts.append(
            "Reverie / shader effects are a SECONDARY companion to the "
            "livestream surface, never the primary destination of a "
            "directorial move. If you want a Reverie companion, recruit "
            'it explicitly with intent_family="preset.bias" — but the '
            "primary surface (cameras, wards, overlays) must be recruited "
            "first. Do not let the shader chain be the only thing you "
            "drive."
        )

        # HOMAGE composition section (spec §4.12). The active homage
        # package gives the livestream surface its aesthetic grammar;
        # homage.* families let the director ROUTE transitions through
        # the choreographer rather than just biasing chrome alpha.
        parts.append("")
        parts.append("## Homage Composition")
        parts.append(
            "The active homage package is BitchX — it is the surface's "
            "aesthetic substrate, giving every ward its grey-punctuation "
            "skeleton, bright identity colouring, CP437 raster, angle-"
            "bracket container, zero-frame transitions, and event-rhythm "
            "texture. Nothing is pasted; every ward appearance is a "
            "transition. Signature artefacts (quit-quips, join-banners, "
            "MOTD blocks, kick-reasons) are authored by you under the "
            "homage grammar — captured chat is never rendered."
        )
        parts.append(
            "Every tick, think about whether a HOMAGE move fits what you "
            "are doing. Each member pairs with a package transition the "
            "choreographer will reconcile against concurrency rules:"
        )
        parts.append(
            "  - homage.rotation — cycle to a new signature artefact "
            "(cadence: ~90s default; structural director can push rapid "
            "or deliberate).\n"
            "  - homage.emergence — bring an absent ward into view via "
            "the package's default entry (ticker-scroll-in for BitchX).\n"
            "  - homage.swap — trade a ward for another; simultaneous "
            "part-message + join-message.\n"
            "  - homage.cycle — sweep through a ward family (legibility "
            "wards, hothouse panels, chat-keyword entries).\n"
            "  - homage.recede — quiet a ward back to absent via the "
            "package's default exit (ticker-scroll-out for BitchX).\n"
            "  - homage.expand — emphasise a ward that is about to carry "
            "a payload; netsplit-burst-class emphasis."
        )
        parts.append(
            "NEVER paste. Every ward appearance is a transition. "
            "Idle is the cardinal sin — compositional pressure is "
            "compatible with calm pacing; it is incompatible with stasis."
        )

        # Structural-intent surface (2026-04-18, cascade-delta). Operator
        # directive: "active thoughtful manipulation should be UNAVOIDABLE
        # to livestream viewers". Every narrative tick MUST declare at
        # least one ward to emphasize or a rotation-mode choice so the
        # homage surface visibly changes shape each cadence rather than
        # sitting as a static techno overlay with dumb containers.
        parts.append("")
        parts.append("## Structural intent — homage surface (mandatory this tick)")
        parts.append(
            "The compositor reads ``structural_intent`` every tick and "
            "translates it to ward-property + homage-choreographer moves "
            "directly (no Qdrant recruitment — aesthetic directives are "
            "not recruitable). Make choices visible every tick:"
        )
        parts.append(
            "  - homage_rotation_mode: choose one of "
            "sequential | random | weighted_by_salience | paused. "
            "``paused`` only when the operator is in delicate work and "
            "the surface should stop shifting; default to "
            "``weighted_by_salience`` when the perceptual field is busy "
            "so the highest-salience ward wins.\n"
            "  - ward_emphasis: 1–3 ward_ids to brighten + glow + pulse "
            "for ~4s. Pick wards actually relevant to the current move. "
            "Valid ids: chat_ambient, activity_header, "
            "stance_indicator, grounding_provenance_ticker, "
            "impingement_cascade, recruitment_candidate_panel, "
            "thinking_indicator, pressure_gauge, activity_variety_log, "
            "whos_here, token_pole, album_overlay, sierpinski, "
            "hardm_dot_matrix, stream_overlay, captions, "
            "research_marker_overlay, chat_keyword_legend, vinyl_platter, "
            "overlay_zones.\n"
            "  - ward_dispatch (optional): 0–2 ward_ids to freshly "
            "bring in (FSM ABSENT → ENTERING). Use sparingly — a "
            "dispatch is a bigger surface move than an emphasis.\n"
            "  - ward_retire (optional): 0–2 ward_ids to quiet out "
            "(FSM HOLD → EXITING). Pair with ward_dispatch for a swap.\n"
            "  - placement_bias (optional): per-ward placement hint map, "
            'e.g. {"album": "scale_1.15x", "token_pole": '
            '"drift_left"}. Hints: drift_left, drift_right, drift_up, '
            "drift_down, pulse_center, scale_0.8x, scale_1.0x, "
            "scale_1.15x, scale_1.3x."
        )
        parts.append(
            "**Default on quiet ticks:** "
            '{"homage_rotation_mode": "weighted_by_salience", '
            '"ward_emphasis": ["<the ward the narrative most belongs to>"], '
            '"ward_dispatch": [], "ward_retire": [], "placement_bias": {}}. '
            "Never emit an empty structural_intent — idle is the cardinal "
            "sin (above); the surface must visibly move with you."
        )

        # Viewer-audit (2026-04-18): after 4 consecutive react narratives
        # the LLM was looping the same paragraph about the same video.
        # Insert an explicit "change the subject" rider when we've spent
        # too long on video commentary so the next emission reaches for
        # music / operator / reverie / study ground.
        try:
            recent = list(getattr(self, "_recent_narratives", []))
            video_streak = 0
            for narrative in reversed(recent):
                low = (narrative or "").lower()
                if any(k in low for k in ("video", "deposition", "footage", "scene")):
                    video_streak += 1
                else:
                    break
            if video_streak >= 3:
                parts.append("")
                parts.append(
                    "## Scope nudge\n"
                    f"You have commented on the video for {video_streak} ticks in a row. "
                    "The viewer can see the video. **Shift ground**: comment on "
                    "the music Oudepode is playing, the reverie visual mood, "
                    "the operator's desk activity, or the active research "
                    "objective. Anything BUT another video paragraph."
                )
        except Exception:
            log.debug("scope nudge failed", exc_info=True)
        # Operator directive 2026-04-19 — keep this block PROMINENT and
        # near the narrative_text definition. The director was caught
        # narrating its own pipeline state ("we are in a holding pattern")
        # as if it were audience-appropriate content. narrative_text is
        # what a HOST says to viewers — never stage directions, never
        # meta-state, never canned reverence.
        parts.append("")
        parts.append("## BANNED NARRATION — DO NOT SPEAK THESE")
        parts.append(
            "BANNED NARRATION — never speak these out loud (operator directive 2026-04-19):\n"
            "\n"
            "  META-STATE NARRATION (treating the stream as its own subject):\n"
            '    - "we are in a holding pattern"\n'
            '    - "let me pause for a moment"\n'
            '    - "let\'s take a moment to appreciate"\n'
            '    - "let\'s continue to appreciate"\n'
            '    - "holding the surface"\n'
            '    - "silence hold"\n'
            "    - Any variant describing the pipeline's own state, director decisions,\n"
            "      activity transitions, or cognitive-system operations as audience content.\n"
            "\n"
            "  CANNED APPRECIATION (reverent-art-critic filler):\n"
            '    - "the subtle beats of..."\n'
            '    - "the captivating rhythm of..."\n'
            '    - "as the vinyl spins..."\n'
            '    - Generic adjectives: "subtle", "captivating", "intricate", "beautiful"\n'
            "      when not grounded in a specific observation you just made.\n"
            "\n"
            "  STAGE DIRECTIONS AS SPEECH:\n"
            '    - Do not announce what you are about to do ("let me show...")\n'
            "    - Do not explain what the compositor is doing\n"
            "    - Do not narrate rotation modes, ward emphasis, or FX state\n"
            "\n"
            "WHAT TO DO INSTEAD:\n"
            "  You are a host making a livestream, not a system announcer. Your narrative\n"
            "  should be grounded in something SPECIFIC you just perceived in the last\n"
            "  ~5 seconds: a sound you heard, a motion you saw, a lyric you caught, a\n"
            "  beat that hit, the timbre of a pad, the way a sample loops, a face\n"
            "  expression on camera. Be concrete. Be crunchy. Be blunt. Be a host, not\n"
            "  a narrator."
        )
        parts.append("")
        parts.append("## Images")
        parts.append("Two images attached. First: the current video frame.")
        parts.append("Second: the full composed surface viewers see.")
        parts.append("")
        parts.append("## Response Format")
        parts.append(
            "Return a single JSON object. Either the legacy shape "
            '{"activity": ..., "react": ...} (always accepted as a safe '
            "fallback) or the richer DirectorIntent shape when you can "
            "ground specific compositional moves in the perceptual field:"
        )
        parts.append(
            "{\n"
            '  "activity": "<one of the listed activities>",\n'
            '  "stance": "<nominal|seeking|cautious|degraded|critical>",\n'
            '  "narrative_text": "<your words>",\n'
            '  "grounding_provenance": ["<signal.path.from.perceptual_field>", ...],\n'
            '  "compositional_impingements": [\n'
            "    {\n"
            '      "narrative": "<gibson-verb description of the compositional move>",\n'
            '      "intent_family": "<camera.hero|preset.bias|overlay.emphasis|youtube.direction|attention.winner|stream_mode.transition|ward.size|ward.position|ward.staging|ward.highlight|ward.appearance|ward.cadence|ward.choreography>",\n'
            '      "material": "<water|fire|earth|air|void>",\n'
            '      "salience": 0.0..1.0\n'
            "    }\n"
            "  ],\n"
            '  "structural_intent": {\n'
            '    "homage_rotation_mode": "<sequential|random|weighted_by_salience|paused>",\n'
            '    "ward_emphasis": ["<ward_id>", ...],\n'
            '    "ward_dispatch": ["<ward_id>", ...],\n'
            '    "ward_retire": ["<ward_id>", ...],\n'
            '    "placement_bias": {"<ward_id>": "<hint>"}\n'
            "  }\n"
            "}"
        )
        parts.append(
            "**The richer shape is mandatory now.** The legacy "
            "{activity, react} fallback exists only for parser-error "
            "recovery — do not target it. Use compositional_impingements "
            "to say what you want foregrounded, biased, dimmed, cut to, "
            "or declared — the pipeline recruits the right capability "
            "from the family you tag. "
            "**At least one compositional_impingement per tick.** A tick "
            "with empty compositional_impingements means you delegated "
            "the visible output to neutral defaults — which is acceptable "
            "ONLY if the perceptual signals genuinely call for that "
            "neutral state, and you should still emit it explicitly "
            '(e.g., {intent_family: "preset.bias", narrative: "neutral '
            'ambient — let the room breathe", salience: 0.3}). '
            "**Mandatory grounding_provenance per impingement.** Every "
            "compositional_impingement carries the perceptual-field key "
            'that made it felt-necessary. "audio.midi.beat_position" '
            'for a beat-synced preset, "visual.top_emotion" for a '
            'react choice, "chat.recent_keywords" for a chat-driven '
            "ward emphasis. An impingement without grounding is a guess; "
            "the pipeline accepts it but the audit will mark it ungrounded."
        )
        parts.append("Complete your sentences. Say as much or as little as the moment requires.")
        parts.append("</reactor_context>")

        return "\n".join(parts)

    def _gather_images(self) -> list[str]:
        """Collect image paths for the LLM call. Skips empty/missing files.

        A 0-byte or unreadable JPEG sent to Claude produces a HTTP 400 Bad
        Request and drops the whole reaction tick. Stale 0-byte frame files
        are a real failure mode after a yt-player restart (observed
        2026-04-12 post-A12 deploy), so the filter is load-bearing.
        """
        images: list[str] = []
        for path in (SHM_DIR / f"yt-frame-{self._active_slot}.jpg", FX_SNAPSHOT):
            try:
                if path.exists() and path.stat().st_size > 0:
                    images.append(str(path))
            except OSError:
                continue
        return images

    # --- Legacy activity tick methods (kept for reference, not called) ---

    def _compute_coherence(self, react_text: str) -> float | None:
        """Cosine similarity of reaction against (video_title + album + chat context).

        Returns None if embedding fails. Higher = reaction tracks its context.
        """
        try:
            import math

            from shared.config import embed

            slot = self._slots[self._active_slot]
            album = _read_album_info()
            chat_snippet = ""
            try:
                chat_path = SHM_DIR / "chat-recent.json"
                if chat_path.exists():
                    recent = json.loads(chat_path.read_text())
                    chat_snippet = " ".join(m.get("text", "") for m in recent[-3:])
            except Exception:
                pass

            context_text = " | ".join(
                p for p in [slot._title or "", slot._channel or "", album, chat_snippet] if p
            )
            if not context_text or not react_text:
                return None

            v_react = embed(react_text)
            v_context = embed(context_text)
            if not v_react or not v_context:
                return None

            dot = sum(a * b for a, b in zip(v_react, v_context, strict=False))
            norm_r = math.sqrt(sum(a * a for a in v_react))
            norm_c = math.sqrt(sum(a * a for a in v_context))
            if norm_r == 0 or norm_c == 0:
                return None
            return dot / (norm_r * norm_c)
        except Exception:
            log.debug("Coherence computation failed", exc_info=True)
            return None

    def _call_activity_llm(self, prompt: str, images: list | None = None) -> str:
        """Call LLM with activity prompt. Returns parsed text or empty string.

        Wrapped in hapax_span("stream", "reaction") so per-reaction scores
        (tokens, coherence, activity) are tagged with stream-experiment.
        """
        key = _get_litellm_key()
        if not key:
            return ""

        content: list[dict] = []
        # Only forward images when the configured route is known multimodal.
        # Text-only routes (e.g. local Qwen3.5-9B) timeout or error when fed
        # base64-encoded JPEGs via the OpenAI-compat image_url shape.
        if images and DIRECTOR_MODEL in MULTIMODAL_ROUTES:
            import base64

            for img_path in images:
                try:
                    if Path(img_path).exists():
                        b64 = base64.b64encode(Path(img_path).read_bytes()).decode()
                        content.append(
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                            }
                        )
                except Exception:
                    pass
        content.append({"type": "text", "text": "Respond."})

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": content},
        ]

        body = json.dumps(
            {
                "model": DIRECTOR_MODEL,
                "messages": messages,
                "max_tokens": 2048,
                "temperature": 0.7,
            }
        ).encode()

        try:
            from shared.telemetry import hapax_score, hapax_span
        except ImportError:
            hapax_span = None  # type: ignore[assignment]
            hapax_score = None  # type: ignore[assignment]

        # Context manager for Langfuse span — yields None if telemetry unavailable.
        from contextlib import nullcontext

        # LRR Phase 1 item 5: tag the Langfuse span with the active research
        # condition_id so traces in `stream-experiment` are filterable per
        # condition. Read via the same cached helper as the reaction record.
        _condition_id = _read_research_marker() or "none"
        span_ctx = (
            hapax_span(
                "stream",
                "reaction",
                tags=["stream-experiment"],
                metadata={
                    "activity": self._activity,
                    "slot": str(self._active_slot),
                    "condition_id": _condition_id,
                },
            )
            if hapax_span is not None
            else nullcontext(None)
        )

        # LRR Phase 10 §3.1 — per-condition Prometheus slicing. The director
        # is the highest-frequency LLM call site on stream; wrapping it here
        # populates hapax_llm_calls_total / _latency_seconds / _outcomes_total
        # with the active research condition as a label, so dashboards can
        # slice reaction volume / latency by Condition A vs Condition A'.
        try:
            from agents.telemetry.llm_call_span import llm_call_span
        except ImportError:
            llm_call_span = None  # type: ignore[assignment]

        metrics_ctx = (
            llm_call_span(model=DIRECTOR_MODEL, route="director")
            if llm_call_span is not None
            else nullcontext(None)
        )

        try:
            with (
                span_ctx as span,
                metrics_ctx as metrics_span,
                _LLMInFlight(tier="narrative", model=DIRECTOR_MODEL),
            ):
                req = urllib.request.Request(
                    LITELLM_URL,
                    body,
                    {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
                )
                try:
                    # 2026-04-17 director-LLM timeout sweep:
                    # 30s baseline → 8s over-correction → 20s → 40s.
                    # 20s was too tight once Command-R-08-2024 (35B,
                    # 5bpw) replaced Qwen3.5-9B as local-fast: a
                    # 10-15 kB prompt + 150 tokens out sits at ~25 s
                    # even on an unloaded RTX 3090. 40s fits that,
                    # and the narrative cadence is HAPAX_NARRATIVE_CADENCE_S
                    # (default 30s since 2026-04-17) so a single stall
                    # can't queue up. Env override: HAPAX_DIRECTOR_LLM_TIMEOUT_S.
                    timeout_s = float(os.environ.get("HAPAX_DIRECTOR_LLM_TIMEOUT_S", "40"))
                    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                        data = json.loads(resp.read())
                except TimeoutError:
                    # re-raise so llm_call_span tags outcome="timeout"
                    raise
                except urllib.error.HTTPError as exc:
                    # 4xx/5xx from LiteLLM → refused outcome (distinct from
                    # transport error). Caller sees empty string; metrics
                    # record the distinction.
                    if metrics_span is not None:
                        metrics_span.set_outcome("refused")
                    log.warning(
                        "LiteLLM HTTP %s — %s",
                        getattr(exc, "code", "?"),
                        getattr(exc, "reason", "?"),
                    )
                    return ""

                try:
                    import sys

                    sys.path.insert(
                        0, str(Path(__file__).resolve().parent.parent.parent / "scripts")
                    )
                    from token_ledger import record_spend

                    usage = data.get("usage", {})
                    record_spend(
                        "hapax",
                        usage.get("prompt_tokens", 0),
                        usage.get("completion_tokens", 0),
                    )
                except Exception:
                    pass

                raw_content = data["choices"][0]["message"].get("content")
                if not raw_content:
                    log.warning(
                        "LLM returned empty content field (finish_reason=%s)",
                        data["choices"][0].get("finish_reason", "?"),
                    )
                    return ""
                log.info(
                    "LLM raw content (%d chars): %r",
                    len(raw_content),
                    raw_content[:200],
                )
                # `react` here is only for per-reaction coherence scoring
                # below; the caller re-parses `raw_content` via
                # _parse_intent_from_llm for the full DirectorIntent
                # (which expects the raw JSON, not a narrative-text extract).
                react, _ = self._parse_llm_response(raw_content.strip())

                # Langfuse per-reaction scoring (spec: stream research infra).
                if hapax_score is not None and span is not None:
                    usage = data.get("usage", {})
                    hapax_score(
                        span,
                        "reaction_tokens",
                        float(usage.get("completion_tokens", 0)),
                        comment=f"activity={self._activity}",
                    )
                    coherence = self._compute_coherence(react)
                    if coherence is not None:
                        hapax_score(
                            span,
                            "reaction_coherence",
                            coherence,
                            comment=f"activity={self._activity}",
                        )
                    # Activity as a categorical score: map to {0,1} per activity
                    hapax_score(
                        span,
                        "reaction_activity",
                        1.0,
                        comment=self._activity,
                    )

                return raw_content.strip()
        except Exception:
            log.exception("Activity LLM call failed")
            return ""

    def _speak_activity(self, text: str, activity: str) -> None:
        """Speak text, then advance slot if reacting. Single thread, locked."""
        self._state = "SPEAKING"
        self._reactor.set_text(text)
        self._reactor.set_speaking(True)
        log.info("%s [%s]: %s", activity.upper(), self._activity, text[:80])

        def _do_speak_and_advance():
            with self._transition_lock:
                # W3.1+W3.2: smooth attack/release envelope replaces the
                # binary mute_all() cliff. Beta's Sprint 4 F2 noted the
                # old binary mute sounded like silence-then-voice-then-
                # silence punching through the music — we want a musical
                # 30 ms attack / 350 ms release ducking envelope.
                # W3.3: voice_active gauge tracks the entire synthesis +
                # playback window; paired with music_ducked it lets us
                # measure trigger → duck latency in Grafana.
                ducked = False
                metrics.set_voice_active(True)
                try:
                    pcm = self._synthesize(text)
                    if pcm:
                        if self._audio_control:
                            self._audio_control.duck()
                            ducked = True
                        self._reactor.feed_pcm(pcm)
                        self._play_audio(pcm)
                        time.sleep(0.3)
                except Exception:
                    log.exception("TTS error")
                finally:
                    if ducked and self._audio_control:
                        self._audio_control.restore()
                    metrics.set_voice_active(False)

                # Advance slot atomically (react mode only)
                if activity == "react":
                    self._slots[self._active_slot].is_active = False
                    self._accumulated_reacts.clear()
                    self._active_slot = (self._active_slot + 1) % len(self._slots)
                    self._slots[self._active_slot].is_active = True
                    self._video_start_time = time.monotonic()
                    self._last_perception = 0.0
                    log.info("Now playing slot %d", self._active_slot)

                # Slot-rotation routing: hard cliff (which slot plays
                # is a discrete state, not an envelope-able quantity).
                # Runs AFTER restore() so the active-slot mute_all_except
                # call writes the final state on top of any envelope tail.
                if self._audio_control:
                    self._audio_control.mute_all_except(self._active_slot)

                # Bookkeeping
                self._log_to_obsidian(text, activity)
                ts = datetime.now().strftime("%H:%M")
                label = f'[{ts}] {activity}: "{text}"'
                self._reaction_history.append(label)
                if len(self._reaction_history) > 20:
                    self._reaction_history = self._reaction_history[-20:]
                self._reactor.set_speaking(False)
                self._reactor.set_text("")
                self._state = "IDLE"

        threading.Thread(
            target=_do_speak_and_advance, daemon=True, name=f"speak-{activity}"
        ).start()

    # Beta PR #756 queue-024 Phase 1: Kokoro CPU synth is
    # ~6.6 chars/sec. With the 90 s client timeout that covers
    # ~600 chars, but the operator still has to wait for the slow
    # synth to complete, which blocks the speak-react thread and
    # delays the next slot advance. Hard-cap react texts at 400
    # chars (~60 s max synth) so the voice path has a predictable
    # upper bound. Longer texts get truncated at a word boundary
    # with an ellipsis marker; the full text still goes to the
    # reaction_history for display.
    _MAX_REACT_TEXT_CHARS = 400

    def _synthesize(self, text: str) -> bytes:
        if len(text) > self._MAX_REACT_TEXT_CHARS:
            cutoff = self._MAX_REACT_TEXT_CHARS
            # Trim on the last whitespace before the cutoff so the
            # audible output ends at a word boundary.
            word_boundary = text.rfind(" ", 0, cutoff)
            if word_boundary > self._MAX_REACT_TEXT_CHARS - 80:
                cutoff = word_boundary
            text = text[:cutoff].rstrip() + "…"
            log.warning(
                "speak-react text truncated to %d chars (Kokoro throughput guard)",
                cutoff,
            )
        return self._tts_client.synthesize(text, "conversation")

    def _play_audio(self, pcm: bytes) -> None:
        """Play PCM using persistent pw-cat subprocess targeting assistant sink."""
        try:
            if not hasattr(self, "_audio_output") or self._audio_output is None:
                from agents.hapax_daimonion.pw_audio_output import PwAudioOutput

                self._audio_output = PwAudioOutput(
                    sample_rate=24000,
                    channels=1,
                    target="input.loopback.sink.role.assistant",
                )
            self._audio_output.write(pcm)
        except Exception:
            log.exception("Audio playback error")

    def _parse_llm_response(self, raw: str) -> tuple[str, bool]:
        try:
            cleaned = raw
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()
            obj = json.loads(cleaned)
            # Volitional-grounded-director shape (PR #1017, 2026-04-17):
            # the LLM now emits `{activity, stance, narrative_text, ...}`
            # rather than the legacy `{react, cut}`. Accept either so the
            # per-span coherence scoring + the legacy return contract
            # keep working after the schema flip. The caller's
            # `_parse_intent_from_llm` does the full validation.
            if "narrative_text" in obj or "stance" in obj:
                return (obj.get("narrative_text", "") or "", False)
            return (obj.get("react", ""), obj.get("cut", False))
        except (json.JSONDecodeError, KeyError):
            # Truncated JSON — try new shape first, then legacy shape.
            import re

            m = re.search(r'"narrative_text"\s*:\s*"([^"]*)', raw)
            if m:
                return (m.group(1), False)
            m = re.search(r'"react"\s*:\s*"([^"]*)', raw)
            if m:
                text = m.group(1)
                cut = '"cut": true' in raw or '"cut":true' in raw
                return (text, cut)
            # Strip any remaining markdown/JSON artifacts
            text = raw.replace("```json", "").replace("```", "").strip()
            text = re.sub(r'^\s*\{?\s*"react"\s*:\s*"?', "", text)
            text = re.sub(r'"?\s*,?\s*"cut"\s*:.*$', "", text)
            return (text.strip(), False)

    def _log_to_obsidian(self, text: str, activity: str = "react") -> None:
        now = datetime.now()
        ts = now.strftime("%H:%M")
        album = _read_album_info()
        slot = self._slots[self._active_slot]
        video_title = slot._title or ""
        video_channel = slot._channel or ""

        # Markdown log (monthly rotation)
        obsidian_log = _obsidian_log_path(now)
        try:
            obsidian_log.parent.mkdir(parents=True, exist_ok=True)
            if activity == "react":
                label = f"Reacting to: *{video_title}* by {video_channel}"
            else:
                label = activity
            entry = f"- **{ts}** | {label}\n  > {text}\n  Album: {album}\n\n"
            with open(obsidian_log, "a") as f:
                f.write(entry)
        except OSError:
            pass

        # JSONL structured log
        self._reaction_count += 1
        record = {
            "ts": now.isoformat(),
            "ts_str": ts,
            "reaction_index": self._reaction_count,
            "activity": activity,
            "text": text,
            "tokens": len(text.split()),
            "video_title": video_title,
            "video_channel": video_channel,
            "album": album,
            "stimmung": "nominal",
            # LRR Phase 1 item 2: research condition tag. Read once per
            # reaction (cached 5 s in `_read_research_marker`). Both the
            # JSONL writer below and the Qdrant upsert pick up this field
            # via the shared `record` dict — no second read.
            "condition_id": _read_research_marker(),
        }
        try:
            stimmung_path = Path("/dev/shm/hapax-stimmung/state.json")
            if stimmung_path.exists():
                st = json.loads(stimmung_path.read_text())
                record["stimmung"] = st.get("overall_stance", "nominal")
        except Exception:
            pass
        try:
            cs_path = SHM_DIR / "chat-state.json"
            if cs_path.exists():
                cs = json.loads(cs_path.read_text())
                record["chat_authors"] = cs.get("unique_authors", 0)
                record["chat_messages"] = cs.get("total_messages", 0)
        except Exception:
            pass

        try:
            with open(_jsonl_log_path(now), "a") as f:
                f.write(json.dumps(record) + "\n")
        except OSError:
            pass

        # Qdrant persistence (async — don't block the reactor)
        def _persist_to_qdrant():
            try:
                from qdrant_client.models import Distance, PointStruct, VectorParams

                from shared.config import embed, get_qdrant

                client = get_qdrant()
                # Ensure collection exists
                collections = [c.name for c in client.get_collections().collections]
                if "stream-reactions" not in collections:
                    client.create_collection(
                        collection_name="stream-reactions",
                        vectors_config=VectorParams(size=768, distance=Distance.COSINE),
                    )
                    log.info("Created stream-reactions Qdrant collection")

                embed_text = f"{activity}: {text[:200]} | {video_title} | {album}"
                vector = embed(embed_text)
                if vector:
                    import uuid

                    client.upsert(
                        collection_name="stream-reactions",
                        points=[
                            PointStruct(
                                id=str(uuid.uuid4()),
                                vector=vector,
                                payload=record,
                            )
                        ],
                    )
            except Exception:
                log.debug("Qdrant persistence failed (non-fatal)", exc_info=True)

        threading.Thread(target=_persist_to_qdrant, daemon=True, name="qdrant-persist").start()

        # SHM memory snapshot (periodic — every 5 reactions)
        if self._reaction_count % 5 == 0:
            self._save_memory_snapshot()
