"""Gates that decide whether to emit a narrative on this tick.

Five gates in priority order:

1. **Hard rate-limit** — never emit faster than ``min_gap_s`` since the
   last emission, regardless of cadence. Spec: 2 min.
2. **Operator presence** — never talk over the operator. Suppresses
   when presence_score >= ``presence_threshold`` OR when an operator
   utterance is being processed.
3. **Programme role exclusion** — programmes whose role explicitly
   prefers silence (RITUAL, WIND_DOWN, INTERLUDE) skip emission unless
   the operator overrides.
4. **Stimmung ceiling** — high-pressure stances (HOTHOUSE, FORTRESS)
   skip autonomous narration; the operator's working mode signals
   they don't want background chatter.
5. **Cadence** — spec cadence (default 150s with ±30s jitter) gates
   emission frequency; rate-limit handles the floor.

Each gate returns True (allow) or False (skip), with a ``reason``
string for the metric label so the operator can see WHY a tick was
suppressed.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# Defaults — all configurable via env vars per spec.
DEFAULT_INTERVAL_S: float = 150.0  # 2.5 min base cadence
DEFAULT_MIN_GAP_S: float = 120.0  # spec: max 1 emission per 2 min
DEFAULT_PRESENCE_THRESHOLD: float = 0.3  # below = considered absent

# Programme roles where autonomous narration is off by default. Operator
# can override per-programme via Programme.allow_autonomous_narrative
# field in a future iteration.
_QUIET_ROLES: frozenset[str] = frozenset({"ritual", "wind_down", "interlude"})

# Stimmung stances where autonomous narration is suppressed.
_QUIET_STANCES: frozenset[str] = frozenset({"hothouse", "fortress", "hothouse_pressure"})


@dataclass(frozen=True)
class GateResult:
    """Outcome of evaluating all gates for one tick."""

    allow: bool
    reason: str  # one of: "ok", "rate_limit", "operator_present",
    #                       "programme_quiet", "stimmung_quiet", "cadence"


def env_interval_s() -> float:
    """Read cadence from ``HAPAX_AUTONOMOUS_NARRATIVE_INTERVAL_S`` env."""
    raw = os.environ.get("HAPAX_AUTONOMOUS_NARRATIVE_INTERVAL_S")
    if not raw:
        return DEFAULT_INTERVAL_S
    try:
        v = float(raw)
        if v <= 0:
            return DEFAULT_INTERVAL_S
        return v
    except ValueError:
        return DEFAULT_INTERVAL_S


def env_enabled() -> bool:
    """Default OFF. Operator enables via ``HAPAX_AUTONOMOUS_NARRATIVE_ENABLED=1``."""
    return os.environ.get("HAPAX_AUTONOMOUS_NARRATIVE_ENABLED", "0") == "1"


def evaluate(
    daemon: Any,
    context: Any,  # NarrativeContext — typed as Any to break import cycle
    *,
    last_emission_ts: float,
    now: float | None = None,
    min_gap_s: float = DEFAULT_MIN_GAP_S,
    interval_s: float | None = None,
    presence_threshold: float = DEFAULT_PRESENCE_THRESHOLD,
) -> GateResult:
    """Run all gates; return ``GateResult(allow=True, reason="ok")`` only when
    every gate permits emission.

    ``daemon`` is the live ``VoiceDaemon`` — used to read perception state
    and the in-flight utterance flag. ``context`` is the assembled
    ``NarrativeContext`` snapshot.
    """
    now = now if now is not None else time.time()
    interval_s = interval_s if interval_s is not None else env_interval_s()

    # Gate 1: hard rate-limit
    if (now - last_emission_ts) < min_gap_s:
        return GateResult(allow=False, reason="rate_limit")

    # Gate 2: operator presence
    if _operator_present(daemon, presence_threshold):
        return GateResult(allow=False, reason="operator_present")

    # Gate 3: programme-role exclusion
    if _programme_is_quiet(context):
        return GateResult(allow=False, reason="programme_quiet")

    # Gate 4: stimmung ceiling
    if _stimmung_is_quiet(context):
        return GateResult(allow=False, reason="stimmung_quiet")

    # Gate 5: cadence — skip if we just emitted within the cadence window
    # (rate-limit catches the hard floor; cadence is the soft target). On
    # tick frequency higher than cadence, this prevents bursting once
    # rate-limit clears.
    if (now - last_emission_ts) < interval_s:
        return GateResult(allow=False, reason="cadence")

    return GateResult(allow=True, reason="ok")


# ── gate predicates ───────────────────────────────────────────────────────


def _operator_present(daemon: Any, threshold: float) -> bool:
    """True when the operator is actively present or speaking."""
    try:
        latest = getattr(getattr(daemon, "perception", None), "latest", None)
        score = getattr(latest, "presence_score", None) if latest else None
        if isinstance(score, (int, float)) and score >= threshold:
            return True
    except Exception:
        pass
    try:
        if getattr(getattr(daemon, "session", None), "is_active", False):
            return True
    except Exception:
        pass
    try:
        if getattr(daemon, "_processing_utterance", False):
            return True
    except Exception:
        pass
    return False


def _programme_is_quiet(context: Any) -> bool:
    prog = getattr(context, "programme", None)
    if prog is None:
        return False
    role = getattr(prog, "role", None)
    if role is None:
        return False
    role_value = str(getattr(role, "value", role)).lower()
    return role_value in _QUIET_ROLES


def _stimmung_is_quiet(context: Any) -> bool:
    tone = getattr(context, "stimmung_tone", "") or ""
    return tone.lower() in _QUIET_STANCES
