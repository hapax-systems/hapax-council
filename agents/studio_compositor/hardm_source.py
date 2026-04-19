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

from agents.studio_compositor.homage import get_active_package
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)


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
    """16×16 signal-bound dot-matrix avatar ward.

    Each row is bound to one signal. Every column in that row is a
    repeated stamp of the same signal state — the grid reads as 16
    horizontal signal-bars, but the raster grammar (square cells, no
    gutters, no anti-aliasing) is preserved so the avatar looks like a
    CP437 stamp rather than a progress bar.

    When row 15 (``homage_package``) is bound, the cell cycles accent
    hue per registered package; other rows stay locked to their family
    accent.
    """

    def __init__(self) -> None:
        super().__init__(source_id="hardm_dot_matrix")

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

        # Flat background so cells sit on the CP437 skeleton rather than
        # floating against the shader surface. Uses the package's
        # ``background`` role — no hardcoded hex.
        bg_rgba = pkg.resolve_colour("background")
        cr.save()
        cr.set_source_rgba(*bg_rgba)
        cr.rectangle(0, 0, SURFACE_W, SURFACE_H)
        cr.fill()
        cr.restore()

        # Task #160 — emphasis-driven brightness multiplier. Speaking
        # cells brighten so the viewer's gaze is drawn to whatever cells
        # are currently communicating, not to the whole grid. Idle
        # (``muted``) cells are deliberately excluded so wholesale pulse
        # doesn't overwrite per-cell information content.
        emphasis = _read_emphasis_state()
        speaking = emphasis == "speaking"

        # Paint 256 cells. Row-major: cell_0 = top-left.
        for row in range(GRID_ROWS):
            signal_name = _signal_for_row(row)
            value = signals.get(signal_name) if signal_name else None
            role, alpha = _classify_cell(signal_name, value)
            r, g, b, a = pkg.resolve_colour(role)  # type: ignore[arg-type]
            if speaking and role != "muted":
                r = min(1.0, r * SPEAKING_BRIGHTNESS_MULT)
                g = min(1.0, g * SPEAKING_BRIGHTNESS_MULT)
                b = min(1.0, b * SPEAKING_BRIGHTNESS_MULT)
            cell_alpha = a * alpha
            for col in range(GRID_COLS):
                x = col * CELL_SIZE_PX
                y = row * CELL_SIZE_PX
                # 1 px muted-grey rule between cells (CP437-thin, §2).
                cr.set_source_rgba(r, g, b, cell_alpha)
                cr.rectangle(
                    x + 1,
                    y + 1,
                    CELL_SIZE_PX - 2,
                    CELL_SIZE_PX - 2,
                )
                cr.fill()


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
