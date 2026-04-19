"""HARDM (Hapax Avatar Representational Dot-Matrix) — 16×16 signal grid.

HOMAGE follow-on #121. Spec:
``docs/superpowers/specs/2026-04-18-hardm-dot-matrix-design.md``.

A 256×256 px CP437-raster avatar-readout. Each of the 256 cells is a
16×16 px dot bound to a real-time system signal. Cells colour-code
their signal state using the **active HomagePackage's palette** (BitchX
mIRC-16 by default): grey idle skeleton, family-keyed accent on
activity, accent-red for stress / overflow / staleness.

The consumer here reads
``/dev/shm/hapax-compositor/hardm-cell-signals.json``. The publisher
lives in ``scripts/hardm-publish-signals.py`` (systemd-timer driven).
If the file is absent or malformed every cell falls back to idle.

Package-invariant geometry: the grid never changes shape. Palette
swaps with :func:`set_active_package` and recolour immediately.

Source id: ``hardm_dot_matrix``. Placement via Layout JSON; the
canonical assignment is upper-right (x=1600, y=20, 256×256).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from agents.studio_compositor.homage import get_active_package
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource
from agents.studio_compositor.text_render import TextStyle, render_text

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)


# ── Render grammar (aesthetic rework 2026-04-20) ──────────────────────────
# Rewrite replaces the radial-halo pointillism grammar (which composited
# to a grey wash at 16 px pitch / 9 px halo) with BBS-authentic CP437
# block characters. Bloom is handed to the Reverie postprocess shader;
# HARDM itself renders crisp edges. See
# ``docs/research/2026-04-20-hardm-aesthetic-rehab.md``.

# CP437 block characters in ascending fill order. Index 0 is "nothing",
# index 1..4 are the four shade levels. These glyphs are exactly the
# width of an 8×16 VGA cell so they align to our 16 px grid perfectly.
_BLOCK_CHARS: tuple[str, ...] = (" ", "░", "▒", "▓", "█")

# Font size (pt) for the CP437 glyphs at 16 px cell. Px437 IBM VGA 8x16
# renders one glyph cell per 8 px width / 16 px height at size 12, so
# we centre the 8-wide glyph horizontally inside each 16 px cell.
_BLOCK_FONT_SIZE_PT: int = 12
_BLOCK_GLYPH_W_PX: float = 8.0
_BLOCK_GLYPH_H_PX: float = 16.0

# Per-cell decay envelope. A cell's brightness decays exponentially once
# its signal falls idle; ``τ`` is modulated downstream by stimmung.
# Default gives a ~2 s half-life so the field always has trailing motion.
DECAY_TAU_DEFAULT_S: float = 1.5
# Ripple wavefront duration. When a cell transitions false→true we
# enqueue a ripple whose amplitude decays over this window.
RIPPLE_LIFETIME_S: float = 0.4
# Neighbourhood offsets for ripple propagation (8-neighbour).
_RIPPLE_NEIGHBOURS: tuple[tuple[int, int, float], ...] = (
    (-1, 0, 0.05),
    (1, 0, 0.05),
    (0, -1, 0.05),
    (0, 1, 0.05),
    (-1, -1, 0.10),
    (-1, 1, 0.10),
    (1, -1, 0.10),
    (1, 1, 0.10),
)

# Reaction-diffusion underlay (Gray-Scott). The V field oscillates in the
# 0..1 range producing slow blob-and-spot patterns; cells blend the V
# value into their level so the grid always has internal motion, even
# when every signal is idle. Defaults are in the pattern-forming regime
# (spots-and-stripes); stimmung's `diffusion` + `tension` dimensions
# modulate them downstream.
_RD_DU: float = 0.16
_RD_DV: float = 0.08
_RD_F: float = 0.04
_RD_K: float = 0.06
# Number of Euler steps per render tick. One step per tick at 10–30 fps
# gives visibly-moving patterns without saturating CPU.
_RD_STEPS_PER_TICK: int = 1

# Path to the affordance pipeline's recent-recruitment state file. When
# a new family is recruited, the signal for the corresponding row gets
# a ripple event. The publisher writes this file; reader is best-effort.
RECENT_RECRUITMENT_FILE: Path = Path("/dev/shm/hapax-compositor/recent-recruitment.json")
RECRUITMENT_FAMILY_TO_ROW: dict[str, int] = {
    # Best-effort mapping of affordance families → HARDM rows. The row
    # is the ripple origin; adjacent cells inherit the wavefront.
    "preset.bias": 11,  # stimmung_energy
    "overlay.emphasis": 12,  # shader_energy
    "camera.hero": 3,  # ir_person_detected
    "youtube.direction": 13,  # reverie_pass (proxy)
    "attention.bid": 9,  # director_stance
}


# ── Grid geometry (package-invariant per spec §2) ─────────────────────────

CELL_SIZE_PX: int = 16
GRID_ROWS: int = 16
GRID_COLS: int = 16
TOTAL_CELLS: int = GRID_ROWS * GRID_COLS  # 256
SURFACE_W: int = CELL_SIZE_PX * GRID_COLS  # 256
SURFACE_H: int = CELL_SIZE_PX * GRID_ROWS  # 256


# ── Signal inventory (spec §3). 16 primary signals, one per row. ──────────

SIGNAL_NAMES: tuple[str, ...] = (
    "midi_active",
    "vad_speech",
    "room_occupancy",
    "ir_person_detected",
    "watch_hr",
    "bt_phone",
    "kde_connect",
    "ambient_sound",
    "screen_focus",
    "director_stance",
    "consent_gate",
    "stimmung_energy",
    "shader_energy",
    "reverie_pass",
    "degraded_stream",
    "homage_package",
)


# ── Signal → family accent role mapping (spec §5). ────────────────────────
# The 16 primary signals are grouped into five HOMAGE palette families.
# Cell hue stays locked to the family; intensity is expressed via alpha.

_SIGNAL_FAMILY_ROLE: dict[str, str] = {
    # timing
    "midi_active": "accent_cyan",
    # operator
    "vad_speech": "accent_green",
    "watch_hr": "accent_green",
    "bt_phone": "accent_green",
    "kde_connect": "accent_green",
    "screen_focus": "accent_green",
    # perception
    "room_occupancy": "accent_yellow",
    "ir_person_detected": "accent_yellow",
    "ambient_sound": "accent_yellow",
    # cognition
    "director_stance": "accent_magenta",
    "stimmung_energy": "accent_magenta",
    "shader_energy": "accent_magenta",
    "reverie_pass": "accent_magenta",
    # governance
    "consent_gate": "bright",
    "degraded_stream": "bright",
    "homage_package": "bright",
}


# ── Signal-state vocabulary ────────────────────────────────────────────────
# A signal's raw value collapses into one of three render states:
#   - idle     → palette.muted (grey skeleton)
#   - active   → family accent role (with alpha modulation)
#   - stress   → palette.accent_red (override, regardless of family)
# Multi-level signals (level3/level4) vary alpha inside ``active`` state.

SIGNAL_FILE: Path = Path("/dev/shm/hapax-compositor/hardm-cell-signals.json")

# Staleness cutoff for the signal payload. The publisher timer fires every
# 2 s (``hapax-hardm-publisher.timer``); this 3 s cutoff gives a 50 %
# margin for publisher cold-start / IO latency so cells don't flicker to
# stress during routine scheduling jitter. See beta audit F-AUDIT-1062-2.
STALENESS_CUTOFF_S: float = 3.0

# ── Task #160 — communicative-anchoring state files ─────────────────────
#
# Full rationale: ``docs/research/hardm-communicative-anchoring.md``. The
# following constants wire HARDM into voice / stance / consent / director
# as a weighted presence term.

# Voice VAD publisher path (same file the compositor ducking controller
# reads). ``operator_speech_active`` there is the OPERATOR's VAD; we use a
# separate ``hardm-emphasis.json`` for Hapax's TTS output (§4 of the
# research doc) so the operator and Hapax voice states can't alias.
VOICE_STATE_FILE: Path = Path("/dev/shm/hapax-compositor/voice-state.json")
HARDM_EMPHASIS_FILE: Path = Path("/dev/shm/hapax-compositor/hardm-emphasis.json")
STIMMUNG_STATE_FILE: Path = Path("/dev/shm/hapax-stimmung/state.json")
# Per ``shared/perceptual_field.py::_CONSENT_CONTRACTS_DIR``. Any YAML file
# with ``guest`` in its name counts as an active-guest contract.
CONSENT_CONTRACTS_DIR: Path = Path(os.path.expanduser("~/projects/hapax-council/axioms/contracts"))
DIRECTOR_INTENT_JSONL: Path = Path(
    os.path.expanduser("~/hapax-state/stream-experiment/director-intent.jsonl")
)
# Written by the sidechat ``point-at-hardm <cell>`` handler; consumed by
# the narrative director loop on the next prompt-build tick.
OPERATOR_CUE_FILE: Path = Path("/dev/shm/hapax-director/operator-cue.json")

# Staleness window for the Hapax TTS emphasis file. Matches the voice
# register bridge's 2 s cutoff so both sides of the wire treat "fresh"
# identically.
EMPHASIS_STALENESS_S: float = 2.0

# Bias contributions (research doc §2). These are the single source of
# truth — tests pin them so a production tweak without a test update is
# caught.
BIAS_VOICE_ACTIVE: float = 0.5
BIAS_SELF_REFERENCE: float = 0.3
BIAS_CONSENT_GUEST: float = 0.2
BIAS_STANCE_SEEKING: float = 0.2

# Unskippable threshold (research doc §2.5).
UNSKIPPABLE_BIAS: float = 0.7

# Brightness multiplier applied to non-idle cells while Hapax TTS is
# speaking. A restrained bump so the grid signal-content stays legible.
SPEAKING_BRIGHTNESS_MULT: float = 1.18

# Self-reference markers scanned in the latest ``director-intent.jsonl``
# records. Small, literal, conservative — expansion requires updating the
# test expectations in ``test_hardm_anchoring.py``.
_SELF_REFERENCE_MARKERS: tuple[str, ...] = (
    "hapax thinks",
    "hapax sees",
    "hapax is",
    "i notice",
    "i'm watching",
    "watching the",
    "let me",
)


# ── Consumer ──────────────────────────────────────────────────────────────


def _read_signals(path: Path | None = None, now: float | None = None) -> dict[str, Any]:
    """Read the signal payload. Returns ``{}`` on any failure.

    Default path resolves from ``SIGNAL_FILE`` at *call time* so tests
    (and any runtime override) can monkeypatch the module-level constant
    without having to thread a path through the render call.

    Staleness: if the payload's ``generated_at`` is older than
    :data:`STALENESS_CUTOFF_S`, return ``{}`` (all cells render idle)
    rather than surfacing arbitrarily old values. ``now`` is injectable
    for deterministic tests; defaults to ``time.time()``.
    """
    target = path if path is not None else SIGNAL_FILE
    try:
        if not target.exists():
            return {}
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        log.debug("hardm-cell-signals read failed", exc_info=True)
        return {}
    if not isinstance(data, dict):
        return {}
    generated_at = data.get("generated_at")
    if isinstance(generated_at, (int, float)):
        current = now if now is not None else time.time()
        if current - float(generated_at) > STALENESS_CUTOFF_S:
            return {}
    signals = data.get("signals")
    if not isinstance(signals, dict):
        return {}
    return signals


def _classify_cell(signal_name: str, value: Any) -> tuple[str, float]:
    """Return ``(role, alpha)`` for a (signal, value) tuple.

    ``role`` is one of:
      - ``"muted"`` (idle)
      - a family accent role (``accent_cyan`` / ``_green`` / ``_yellow`` /
        ``_magenta`` / ``bright``)
      - ``"accent_red"`` (stress)

    ``alpha`` scales family-accent intensity 0.4–1.0 so multi-level signals
    read as graduated glow without breaking BitchX hue lock (spec §5).

    Stress conditions:
      * numeric overflow (``>= 1.0`` where the signal is level4-bucketed
        meaningfully — we treat ``stress`` / ``error`` string values as
        the explicit signal)
      * the value ``{"stress": True}`` / ``"stress"``
      * signal not present in payload for ``consent_gate`` (fail-closed)
    """
    if value is None:
        # Missing signal — governance signals fail closed.
        if signal_name == "consent_gate":
            return ("accent_red", 1.0)
        return ("muted", 1.0)

    # Explicit stress markers
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in ("stress", "error", "overflow", "blocked", "stale"):
            return ("accent_red", 1.0)

    if isinstance(value, dict):
        if value.get("stress") is True or value.get("error") is True:
            return ("accent_red", 1.0)

    family_role = _SIGNAL_FAMILY_ROLE.get(signal_name, "bright")

    # Boolean-like signals
    if isinstance(value, bool):
        if value:
            return (family_role, 1.0)
        return ("muted", 1.0)

    # Numeric signals — interpret as intensity 0.0..1.0 (clamped). Values
    # strictly greater than 1.0 are treated as stress (overflow).
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        v = float(value)
        if v > 1.0:
            return ("accent_red", 1.0)
        if v <= 0.0:
            return ("muted", 1.0)
        # Quantise into 4 alpha levels for graduated glow.
        if v < 0.25:
            return (family_role, 0.30)
        if v < 0.55:
            return (family_role, 0.55)
        if v < 0.80:
            return (family_role, 0.80)
        return (family_role, 1.00)

    # String categorical (e.g. "nominal" / "cautious" / "critical"). Map
    # stance-like values to roles; everything else renders active.
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in ("nominal", "ok", "idle", "off"):
            return ("muted", 1.0)
        if lowered in ("cautious", "seeking", "warn"):
            return (family_role, 0.7)
        if lowered in ("critical", "overflow", "degraded"):
            return ("accent_red", 1.0)
        return (family_role, 1.0)

    # Fallback — paint as active.
    return (family_role, 1.0)


def _signal_for_row(row: int) -> str:
    """Return the signal name bound to ``row`` (row-major layout)."""
    if 0 <= row < len(SIGNAL_NAMES):
        return SIGNAL_NAMES[row]
    return ""


# ── Task #160 — communicative-anchoring readers ──────────────────────────


def _voice_active(path: Path | None = None) -> bool:
    """Return True when Hapax TTS emphasis is ``speaking`` (or when the
    operator VAD says speech is active — viewer gaze still needs an
    anchor during operator utterance).

    Fail-open: any read error, missing file, or stale payload resolves to
    False. The 2 s staleness cutoff matches
    :data:`EMPHASIS_STALENESS_S`.
    """
    target = path if path is not None else HARDM_EMPHASIS_FILE
    now = time.time()
    try:
        if target.exists():
            data = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                ts = data.get("ts")
                if isinstance(ts, (int, float)) and now - float(ts) <= EMPHASIS_STALENESS_S:
                    if data.get("emphasis") == "speaking":
                        return True
    except Exception:
        log.debug("hardm-emphasis read failed", exc_info=True)
    # Fallback to operator VAD. Speech on either side of the wire is
    # enough to anchor the viewer's gaze to HARDM.
    try:
        if VOICE_STATE_FILE.exists():
            vad = json.loads(VOICE_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(vad, dict) and bool(vad.get("operator_speech_active")):
                return True
    except Exception:
        log.debug("voice-state read failed", exc_info=True)
    return False


def _stance_is_seeking(path: Path | None = None) -> bool:
    """Return True when ``overall_stance`` in stimmung state is seeking."""
    target = path if path is not None else STIMMUNG_STATE_FILE
    try:
        if not target.exists():
            return False
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return False
        stance = data.get("overall_stance")
        if isinstance(stance, str) and stance.lower() == "seeking":
            return True
    except Exception:
        log.debug("stimmung stance read failed", exc_info=True)
    return False


def _guest_consent_active(contracts_dir: Path | None = None) -> bool:
    """Return True when any active consent contract names a guest.

    Convention (per research doc §2.3): a contract filename containing
    ``guest`` (case-insensitive) is a guest contract. This keeps the
    lookup ignorant of contract-YAML schema details.
    """
    target = contracts_dir if contracts_dir is not None else CONSENT_CONTRACTS_DIR
    try:
        if not target.exists():
            return False
        for p in target.glob("*.yaml"):
            if "guest" in p.stem.lower():
                return True
    except Exception:
        log.debug("consent contracts listing failed", exc_info=True)
    return False


def _director_intent_has_self_reference(
    path: Path | None = None,
    *,
    n: int = 5,
) -> bool:
    """Scan the last ``n`` lines of ``director-intent.jsonl`` for any of
    the self-reference markers. ``False`` on missing / malformed file.
    """
    target = path if path is not None else DIRECTOR_INTENT_JSONL
    try:
        if not target.exists():
            return False
        size = target.stat().st_size
        window = min(size, 16 * 1024)
        with target.open("rb") as fh:
            fh.seek(max(0, size - window))
            tail = fh.read().decode("utf-8", errors="ignore")
        lines = [line for line in tail.splitlines() if line.strip()][-n:]
        for line in lines:
            try:
                record = json.loads(line)
            except Exception:
                continue
            if not isinstance(record, dict):
                continue
            narrative = str(record.get("narrative_text") or record.get("narrative") or "")
            haystack = narrative.lower()
            if any(marker in haystack for marker in _SELF_REFERENCE_MARKERS):
                return True
    except Exception:
        log.debug("director-intent self-reference scan failed", exc_info=True)
    return False


def current_salience_bias(
    *,
    voice_state_file: Path | None = None,
    stimmung_file: Path | None = None,
    contracts_dir: Path | None = None,
    director_intent_file: Path | None = None,
    emit_metric: bool = True,
) -> float:
    """Return the HARDM salience bias in ``[0.0, 1.0]`` (task #160).

    The four contributions (voice active, self-reference, guest consent,
    SEEKING stance) are summed and clamped at 1.0. See
    :doc:`docs/research/hardm-communicative-anchoring.md` for rationale.

    Reads four SHM/disk paths; injection points are kept so the tests
    can monkeypatch each input independently.
    """
    bias = 0.0

    # Voice: Hapax TTS emphasis OR operator VAD. We can't pass the
    # VAD path through because ``_voice_active`` falls through to the
    # global ``VOICE_STATE_FILE``; tests isolate via monkeypatch on
    # the module-level constants.
    if voice_state_file is not None:
        # Allow explicit override in tests that want to pin the emphasis
        # file separately from the VAD file.
        if _voice_active(voice_state_file):
            bias += BIAS_VOICE_ACTIVE
    elif _voice_active():
        bias += BIAS_VOICE_ACTIVE

    if _director_intent_has_self_reference(director_intent_file):
        bias += BIAS_SELF_REFERENCE

    if _guest_consent_active(contracts_dir):
        bias += BIAS_CONSENT_GUEST

    if _stance_is_seeking(stimmung_file):
        bias += BIAS_STANCE_SEEKING

    bias = min(1.0, bias)

    if emit_metric:
        _emit_bias_gauge(bias)

    return bias


def _emit_bias_gauge(value: float) -> None:
    """Best-effort Prometheus gauge emission for the bias value."""
    try:
        from shared.director_observability import emit_hardm_salience_bias

        emit_hardm_salience_bias(value)
    except Exception:
        log.debug("emit_hardm_salience_bias failed", exc_info=True)


# ── Task #160 — TTS emphasis emission (called from CPAL) ─────────────────


def write_emphasis(state: str, path: Path | None = None) -> None:
    """Atomically publish ``{"emphasis": state, "ts": now}``.

    ``state`` should be ``"speaking"`` or ``"quiescent"``. Any other
    value is written as-is — callers are responsible for the vocabulary.
    Best-effort: errors are logged and swallowed so a TTS path never
    blocks on SHM write failures.
    """
    target = path if path is not None else HARDM_EMPHASIS_FILE
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {"emphasis": state, "ts": time.time()}
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(target)
    except Exception:
        log.debug("write_emphasis failed for %s", state, exc_info=True)


def _read_emphasis_state(path: Path | None = None) -> str:
    """Return ``"speaking"`` or ``"quiescent"``; default ``"quiescent"``.

    Stale payloads (age > :data:`EMPHASIS_STALENESS_S`), missing files,
    and malformed JSON all resolve to quiescent.
    """
    target = path if path is not None else HARDM_EMPHASIS_FILE
    try:
        if not target.exists():
            return "quiescent"
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return "quiescent"
        ts = data.get("ts")
        if isinstance(ts, (int, float)) and time.time() - float(ts) > EMPHASIS_STALENESS_S:
            return "quiescent"
        emphasis = data.get("emphasis")
        if emphasis == "speaking":
            return "speaking"
    except Exception:
        log.debug("hardm emphasis read failed", exc_info=True)
    return "quiescent"


# ── Task #160 — sidechat ``point-at-hardm <cell>`` parser ────────────────


def parse_point_at_hardm(text: str) -> int | None:
    """Return the cell index (0..255) if ``text`` is a valid
    ``point-at-hardm <cell>`` command, else ``None``.

    Lenient: accepts leading/trailing whitespace, is case-insensitive on
    the command prefix, and accepts ``point-at-hardm`` / ``point at
    hardm`` spellings. Cell index must parse as an integer in
    ``[0, 255]``; anything else returns ``None``.
    """
    if not text:
        return None
    stripped = text.strip().lower()
    # Accept both hyphenated and space-separated forms.
    for prefix in ("point-at-hardm", "point at hardm"):
        if stripped.startswith(prefix):
            remainder = stripped[len(prefix) :].strip()
            if not remainder:
                return None
            token = remainder.split()[0]
            try:
                cell = int(token)
            except ValueError:
                return None
            if 0 <= cell < TOTAL_CELLS:
                return cell
            return None
    return None


def write_operator_cue(cell: int, path: Path | None = None) -> None:
    """Write the ``point-at-hardm`` operator cue for the director loop.

    Payload::

        {"cue": "point-at-hardm", "cell": <int>, "signal_name": <str>,
         "ts": <float>}

    Signal name is the row-bound signal for ``cell // GRID_COLS`` (see
    :func:`_signal_for_row`). The director is expected to consume and
    delete the file on the next prompt build.
    """
    target = path if path is not None else OPERATOR_CUE_FILE
    row = cell // GRID_COLS
    signal_name = _signal_for_row(row)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cue": "point-at-hardm",
            "cell": int(cell),
            "signal_name": signal_name,
            "ts": time.time(),
        }
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(target)
    except Exception:
        log.debug("write_operator_cue failed", exc_info=True)


# ── Task #160 — choreographer hook: unskippable HARDM enqueue ────────────


def should_force_hardm_in_rotation(bias: float | None = None) -> bool:
    """Return True when HARDM should be forcibly enqueued every tick.

    The choreographer calls this before its concurrency slice. When
    True, and no HARDM entry is already in the pending-transitions
    queue, the choreographer synthesises one at the current salience
    score (see research doc §5.1).
    """
    if bias is None:
        bias = current_salience_bias(emit_metric=False)
    return bias > UNSKIPPABLE_BIAS


# ── Cairo source ──────────────────────────────────────────────────────────


class HardmDotMatrix(HomageTransitionalSource):
    """16×16 signal-bound CP437 block-matrix avatar ward.

    Each row is bound to one signal; every column in that row stamps the
    same signal state so the field reads as 16 horizontal signal-bars.
    Cells render as CP437 block glyphs (``░▒▓█``) at the BBS-authentic
    Px437 IBM VGA font. A Gray-Scott reaction-diffusion field underlays
    every cell so the grid always carries internal motion — idle signals
    do not flatten the avatar to a dead grid. Per-cell decay envelopes
    and ripple events driven by ``recent-recruitment.json`` turn signal
    transitions into legible animations.

    No Cairo bloom. The Reverie postprocess shader pass owns the bloom
    for the whole composite; HARDM renders crisp edges and lets the GPU
    do the optical glow at composite time.
    """

    def __init__(self) -> None:
        super().__init__(source_id="hardm_dot_matrix")
        # Reaction-diffusion state (U, V). V oscillates in ~0..1 once
        # the initial condition settles. Seed with small perturbations
        # so the pattern develops immediately rather than sitting flat.
        self._rd_u: np.ndarray = np.ones((GRID_ROWS, GRID_COLS), dtype=np.float32)
        self._rd_v: np.ndarray = np.zeros((GRID_ROWS, GRID_COLS), dtype=np.float32)
        rng = np.random.default_rng(seed=0x4841_5041_58)
        seeds = rng.integers(0, GRID_ROWS * GRID_COLS, size=12)
        for s in seeds:
            r, c = int(s) // GRID_COLS, int(s) % GRID_COLS
            self._rd_v[r, c] = 0.5

        # Per-cell history. Index = row * GRID_COLS + col. Each entry is
        # (last_active_ts, last_level) where level is the 0..1 signal
        # intensity at the last non-idle tick. Decay reads from here.
        self._cell_last_active: list[float] = [0.0] * TOTAL_CELLS
        self._cell_last_level: list[float] = [0.0] * TOTAL_CELLS
        # Active ripples: list of (origin_cell, enqueue_ts). Pruned to
        # RIPPLE_LIFETIME_S window every tick.
        self._ripples: list[tuple[int, float]] = []
        # Last-seen recruitment timestamps per family — only newer ones
        # enqueue a ripple, so a long-lived recruitment doesn't spam.
        self._last_ripple_ts: dict[str, float] = {}

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        pkg = get_active_package()
        if pkg is None:
            # Consent-safe layout — HOMAGE disabled. Render transparent.
            return

        signals = _read_signals()
        now = time.time()

        # 1. Advance the RD substrate. Pattern-forming Gray-Scott with
        # constants in the spots-and-stripes regime; one Euler step per
        # tick keeps the visual motion slow enough to read.
        for _ in range(_RD_STEPS_PER_TICK):
            self._rd_step()

        # 2. Pull ripple events from the affordance pipeline's recent-
        # recruitment log. New entries enqueue a per-cell ripple.
        self._ingest_ripples(now)

        # 3. Drop expired ripples so the in-flight list stays small.
        self._ripples = [(c, ts) for c, ts in self._ripples if (now - ts) <= RIPPLE_LIFETIME_S]

        # 4. Background — package-governed so consent-safe / package
        # swaps recolour instantly. No more hardcoded Gruvbox bg0.
        bg_r, bg_g, bg_b, bg_a = pkg.resolve_colour("background")
        cr.save()
        cr.set_source_rgba(bg_r, bg_g, bg_b, bg_a)
        cr.rectangle(0, 0, SURFACE_W, SURFACE_H)
        cr.fill()
        cr.restore()

        # 5. Task #160 emphasis — gently brightens active cells so the
        # viewer's gaze is drawn to whatever is currently communicating.
        emphasis = _read_emphasis_state()
        speaking = emphasis == "speaking"

        # 6. Render each cell as a CP437 block character. The block
        # character's fill-level encodes the cell's combined intensity
        # (signal level × RD modulation × ripple boost × decay). The
        # glyph colour is the active package's family-accent role.
        font_description = f"{pkg.typography.primary_font_family} {_BLOCK_FONT_SIZE_PT}"
        for row in range(GRID_ROWS):
            signal_name = _signal_for_row(row)
            value = signals.get(signal_name) if signal_name else None
            role, role_alpha = _classify_cell(signal_name, value)
            base_level = self._role_to_level(role, role_alpha, value)
            r, g, b, a = pkg.resolve_colour(role)  # type: ignore[arg-type]
            if speaking and role != "muted":
                r = min(1.0, r * SPEAKING_BRIGHTNESS_MULT)
                g = min(1.0, g * SPEAKING_BRIGHTNESS_MULT)
                b = min(1.0, b * SPEAKING_BRIGHTNESS_MULT)

            for col in range(GRID_COLS):
                cell_idx = row * GRID_COLS + col
                level = self._compose_cell_level(
                    base_level=base_level,
                    row=row,
                    col=col,
                    cell_idx=cell_idx,
                    now=now,
                )
                # Update per-cell history so decay survives signal drops.
                if base_level > 0.05:
                    self._cell_last_active[cell_idx] = now
                    self._cell_last_level[cell_idx] = base_level

                block_idx = self._level_to_block_index(level)
                if block_idx == 0:
                    continue  # blank cell; bg already painted
                glyph = _BLOCK_CHARS[block_idx]
                # Position glyph centred in cell. Pango renders from
                # top-left of its layout; 8×16 glyph in 16×16 cell → +4
                # offset horizontally, +0 vertically.
                x = col * CELL_SIZE_PX + (CELL_SIZE_PX - _BLOCK_GLYPH_W_PX) / 2.0
                y = row * CELL_SIZE_PX
                style = TextStyle(
                    text=glyph,
                    font_description=font_description,
                    color_rgba=(r, g, b, a * level),
                    outline_offsets=(),
                )
                render_text(cr, style, x=x, y=y)

    # ── Per-cell composition helpers ────────────────────────────────────

    @staticmethod
    def _role_to_level(role: str, role_alpha: float, value: Any) -> float:
        """Collapse the ``(role, alpha)`` classify-output to a 0..1 level.

        ``role_alpha`` carries the level for multi-level numeric signals
        (0.30/0.55/0.80/1.00 per ``_classify_cell``). Muted cells are
        always level 0. Stress cells saturate at 1.0. Boolean-true with
        role_alpha=1.0 reads as level 1.0 (fully active).
        """
        if role == "muted":
            return 0.0
        if role == "accent_red":
            return 1.0
        return float(role_alpha)

    def _compose_cell_level(
        self,
        *,
        base_level: float,
        row: int,
        col: int,
        cell_idx: int,
        now: float,
    ) -> float:
        """Combine base signal level + decay + ripples + RD underlay.

        The combination is additive-with-clamp at 1.0: every contribution
        can only brighten a cell, never darken it past the base signal.
        """
        # Decay contribution: if the cell has been active recently but
        # the current signal is idle, we keep some brightness proportional
        # to the exponential decay of the last-seen level.
        decay_contribution = 0.0
        if base_level < 0.05:
            since = now - self._cell_last_active[cell_idx]
            if since >= 0.0:
                falloff = np.exp(-since / DECAY_TAU_DEFAULT_S)
                decay_contribution = float(self._cell_last_level[cell_idx] * falloff)

        # Ripple contribution: in-flight ripple wavefronts boost cells
        # within a +neighbourhood of the origin. Amplitude decays over
        # the ripple lifetime.
        ripple_contribution = 0.0
        for origin_idx, ts in self._ripples:
            age = now - ts
            if age < 0.0 or age > RIPPLE_LIFETIME_S:
                continue
            envelope = 1.0 - (age / RIPPLE_LIFETIME_S)  # 1 → 0 linear
            origin_row, origin_col = divmod(origin_idx, GRID_COLS)
            if origin_row == row and origin_col == col:
                ripple_contribution = max(ripple_contribution, 0.6 * envelope)
                continue
            for dr, dc, amp in _RIPPLE_NEIGHBOURS:
                if origin_row + dr == row and origin_col + dc == col:
                    ripple_contribution = max(ripple_contribution, amp * 4.0 * envelope)

        # RD underlay: V field modulates the cell by up to ±0.25. This is
        # the source of "internal motion always present".
        rd_contribution = 0.25 * float(self._rd_v[row, col])

        combined = base_level + decay_contribution + ripple_contribution + rd_contribution
        return max(0.0, min(1.0, combined))

    @staticmethod
    def _level_to_block_index(level: float) -> int:
        """Map a 0..1 level to an index into :data:`_BLOCK_CHARS`.

        Quantises into 5 bands (blank/░/▒/▓/█). The thresholds are
        chosen so the RD-only floor (~0.05) renders as a sparse ``░``
        dither, giving the grid perpetual low-level life even when every
        signal is idle.
        """
        if level < 0.05:
            return 0
        if level < 0.30:
            return 1
        if level < 0.55:
            return 2
        if level < 0.80:
            return 3
        return 4

    # ── Reaction-diffusion substrate ────────────────────────────────────

    def _rd_step(self) -> None:
        """Advance the Gray-Scott field one Euler step.

        Standard 5-point Laplacian with periodic boundary. The stencil
        is 16×16 so it's ``O(256)`` — effectively free.
        """
        u = self._rd_u
        v = self._rd_v
        lap_u = (
            np.roll(u, 1, axis=0)
            + np.roll(u, -1, axis=0)
            + np.roll(u, 1, axis=1)
            + np.roll(u, -1, axis=1)
            - 4.0 * u
        )
        lap_v = (
            np.roll(v, 1, axis=0)
            + np.roll(v, -1, axis=0)
            + np.roll(v, 1, axis=1)
            + np.roll(v, -1, axis=1)
            - 4.0 * v
        )
        uvv = u * v * v
        self._rd_u = u + (_RD_DU * lap_u - uvv + _RD_F * (1.0 - u))
        self._rd_v = v + (_RD_DV * lap_v + uvv - (_RD_F + _RD_K) * v)
        # Clamp so the field stays bounded; prevents runaway on edge
        # numerical conditions (still possible with rough constants).
        np.clip(self._rd_u, 0.0, 1.0, out=self._rd_u)
        np.clip(self._rd_v, 0.0, 1.0, out=self._rd_v)

    # ── Recruitment-event ripple reader ────────────────────────────────

    def _ingest_ripples(self, now: float) -> None:
        """Poll ``recent-recruitment.json`` and enqueue new-event ripples.

        Each family in the payload maps to a HARDM row via
        :data:`RECRUITMENT_FAMILY_TO_ROW`. We fire one ripple per family
        per tick-window: if the family's ``last_recruited_ts`` advances,
        we enqueue a ripple at a cell in that row (column 7/8, mid-row).
        """
        try:
            if not RECENT_RECRUITMENT_FILE.exists():
                return
            data = json.loads(RECENT_RECRUITMENT_FILE.read_text(encoding="utf-8"))
        except Exception:
            log.debug("recent-recruitment read failed", exc_info=True)
            return

        families = data.get("families") if isinstance(data, dict) else None
        if not isinstance(families, dict):
            return

        for family, row in RECRUITMENT_FAMILY_TO_ROW.items():
            entry = families.get(family)
            if not isinstance(entry, dict):
                continue
            ts = entry.get("last_recruited_ts")
            if not isinstance(ts, (int, float)):
                continue
            ts = float(ts)
            if ts <= self._last_ripple_ts.get(family, 0.0):
                continue
            if (now - ts) > RIPPLE_LIFETIME_S * 4:
                # Too old to fire — record so we don't fire on next tick.
                self._last_ripple_ts[family] = ts
                continue
            origin_col = GRID_COLS // 2  # centre of the row
            origin_cell = row * GRID_COLS + origin_col
            self._ripples.append((origin_cell, now))
            self._last_ripple_ts[family] = ts


__all__ = [
    "BIAS_CONSENT_GUEST",
    "BIAS_SELF_REFERENCE",
    "BIAS_STANCE_SEEKING",
    "BIAS_VOICE_ACTIVE",
    "CELL_SIZE_PX",
    "CONSENT_CONTRACTS_DIR",
    "DIRECTOR_INTENT_JSONL",
    "EMPHASIS_STALENESS_S",
    "GRID_COLS",
    "GRID_ROWS",
    "HARDM_EMPHASIS_FILE",
    "HardmDotMatrix",
    "OPERATOR_CUE_FILE",
    "SIGNAL_FILE",
    "SIGNAL_NAMES",
    "SPEAKING_BRIGHTNESS_MULT",
    "STALENESS_CUTOFF_S",
    "STIMMUNG_STATE_FILE",
    "SURFACE_H",
    "SURFACE_W",
    "TOTAL_CELLS",
    "UNSKIPPABLE_BIAS",
    "VOICE_STATE_FILE",
    "_classify_cell",
    "_director_intent_has_self_reference",
    "_guest_consent_active",
    "_read_emphasis_state",
    "_read_signals",
    "_signal_for_row",
    "_stance_is_seeking",
    "_voice_active",
    "current_salience_bias",
    "parse_point_at_hardm",
    "should_force_hardm_in_rotation",
    "write_emphasis",
    "write_operator_cue",
]
