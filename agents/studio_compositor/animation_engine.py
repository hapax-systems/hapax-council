"""Ward animation engine — easing + transition evaluation.

Turns the static :class:`WardProperties` override into a moving target.
A :class:`Transition` declares "ward W's property P should reach value V
over D seconds, easing E, starting at T". The engine evaluates active
transitions per frame and produces interpolated values the compositor's
Compile phase folds into the merged property envelope.

Persisted state lives at
``/dev/shm/hapax-compositor/ward-animation-state.json``. Writers
(``compositional_consumer.dispatch_ward_choreography`` and the foreground
director loop) append transitions; the engine prunes expired entries on
each read.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

WARD_ANIMATION_STATE_PATH = Path("/dev/shm/hapax-compositor/ward-animation-state.json")

# Same hot-path TTL as ward_properties so a 200ms cache budget covers
# both files together.
_CACHE_TTL_S = 0.2

# Properties the engine knows how to interpolate. Anything outside this
# set is rejected at write time so a typo doesn't silently no-op.
SUPPORTED_PROPERTIES: frozenset[str] = frozenset(
    {
        "alpha",
        "scale",
        "scale_bump_pct",
        "glow_radius_px",
        "border_pulse_hz",
        "position_offset_x",
        "position_offset_y",
        "border_radius_px",
    }
)


@dataclass
class Transition:
    """One pending property animation."""

    ward_id: str
    property: str
    from_value: float
    to_value: float
    duration_s: float
    easing: str
    started_at: float


# ── Easing functions ───────────────────────────────────────────────────────


def _linear(p: float) -> float:
    return p


def _ease_in_quad(p: float) -> float:
    return p * p


def _ease_out_quad(p: float) -> float:
    return 1.0 - (1.0 - p) * (1.0 - p)


def _ease_in_out_cubic(p: float) -> float:
    if p < 0.5:
        return 4.0 * p * p * p
    return 1.0 - pow(-2.0 * p + 2.0, 3.0) / 2.0


def _elastic(p: float) -> float:
    if p == 0.0 or p == 1.0:
        return p
    c4 = (2.0 * math.pi) / 3.0
    return -pow(2.0, 10.0 * p - 10.0) * math.sin((p * 10.0 - 10.75) * c4)


def _bounce(p: float) -> float:
    n1 = 7.5625
    d1 = 2.75
    if p < 1.0 / d1:
        return n1 * p * p
    if p < 2.0 / d1:
        p -= 1.5 / d1
        return n1 * p * p + 0.75
    if p < 2.5 / d1:
        p -= 2.25 / d1
        return n1 * p * p + 0.9375
    p -= 2.625 / d1
    return n1 * p * p + 0.984375


_EASINGS: dict[str, Callable[[float], float]] = {
    "linear": _linear,
    "ease-in-quad": _ease_in_quad,
    "ease-out-quad": _ease_out_quad,
    "ease-in-out-cubic": _ease_in_out_cubic,
    "elastic": _elastic,
    "bounce": _bounce,
}


def evaluate_transition(transition: Transition, now: float) -> float:
    """Return the interpolated value at ``now``.

    ``now`` is wall-clock seconds (``time.time()``). Returns the
    eased-interpolated value while progress is in [0, 1) and
    ``to_value`` at or past progress=1.0. Use :func:`is_expired` to
    decide whether to drop a transition entirely; this function always
    returns a usable float so consumers can read the resting target
    after the animation completes (until :func:`is_expired` allows a
    cleanup pass to prune).
    """
    if transition.duration_s <= 0:
        return transition.to_value
    progress = (now - transition.started_at) / transition.duration_s
    if progress < 0.0:
        return transition.from_value
    if progress >= 1.0:
        return transition.to_value
    easer = _EASINGS.get(transition.easing, _linear)
    eased = easer(progress)
    return transition.from_value + (transition.to_value - transition.from_value) * eased


def is_expired(transition: Transition, now: float, grace_s: float = 0.5) -> bool:
    """True if the transition finished more than ``grace_s`` seconds ago.

    The grace window keeps a transition alive long enough for any
    consumer reading on a slow tick to still observe its final value
    before the engine prunes it.
    """
    end = transition.started_at + transition.duration_s
    return now > (end + grace_s)


# ── State I/O ──────────────────────────────────────────────────────────────


_cache: tuple[float, list[Transition]] | None = None


def append_transitions(transitions: list[Transition]) -> None:
    """Atomic upsert: extend the on-disk transition list.

    Caller is responsible for not appending a duplicate transition
    (same ward + property + started_at). The engine itself does no
    deduplication — overlapping transitions on the same property
    produce an effectively-last-write-wins outcome via the natural
    sort order at evaluation time.
    """
    if not transitions:
        return
    rejected = [t for t in transitions if t.property not in SUPPORTED_PROPERTIES]
    if rejected:
        log.warning(
            "animation engine: rejecting %d transitions targeting unsupported properties: %s",
            len(rejected),
            sorted({t.property for t in rejected}),
        )
        transitions = [t for t in transitions if t.property in SUPPORTED_PROPERTIES]
        if not transitions:
            return
    try:
        WARD_ANIMATION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        current = _safe_load_raw()
        existing = current.get("transitions") or []
        if not isinstance(existing, list):
            existing = []
        now = time.time()
        # Drop expired entries during write so the file doesn't grow without bound.
        kept: list[dict] = []
        for entry in existing:
            try:
                t = _dict_to_transition(entry)
            except Exception:
                continue
            if not is_expired(t, now):
                kept.append(entry)
        kept.extend(asdict(t) for t in transitions)
        out = {"transitions": kept, "updated_at": now}
        tmp = WARD_ANIMATION_STATE_PATH.with_suffix(WARD_ANIMATION_STATE_PATH.suffix + ".tmp")
        tmp.write_text(json.dumps(out), encoding="utf-8")
        tmp.replace(WARD_ANIMATION_STATE_PATH)
    except Exception:
        log.warning("append_transitions write failed", exc_info=True)


def evaluate_all(now: float | None = None) -> dict[str, dict[str, float]]:
    """Return per-ward, per-property interpolated values for active transitions.

    Output shape: ``{ward_id: {property: value, …}, …}``. Wards with no
    active transitions are omitted. When the same (ward, property) has
    multiple active transitions the engine returns the value of the
    transition with the latest ``started_at`` — operators should treat
    overlapping transitions on the same property as a coordination bug.

    The animation file is re-read on every call so the engine returns
    a value that reflects ``now``, not the cached evaluation timestamp.
    The 200ms cache covers the *parsed transition list*; per-frame
    evaluation against the current clock is cheap (one float per
    transition).
    """
    snapshot_pairs = _refresh_cache_if_stale()
    if now is None:
        now = time.time()
    by_key: dict[tuple[str, str], tuple[float, float]] = {}
    for transition in snapshot_pairs:
        value = evaluate_transition(transition, now)
        key = (transition.ward_id, transition.property)
        existing = by_key.get(key)
        if existing is None or transition.started_at >= existing[0]:
            by_key[key] = (transition.started_at, value)
    out: dict[str, dict[str, float]] = {}
    for (ward_id, prop), (_, value) in by_key.items():
        out.setdefault(ward_id, {})[prop] = value
    return out


def clear_animation_cache() -> None:
    """Drop the in-process cache. Tests + layout swaps call this."""
    global _cache
    _cache = None


# ── Internals ──────────────────────────────────────────────────────────────


def _refresh_cache_if_stale() -> list[Transition]:
    global _cache
    now_monotonic = time.monotonic()
    if _cache is not None and (now_monotonic - _cache[0]) < _CACHE_TTL_S:
        return _cache[1]
    parsed = _parse_transitions()
    _cache = (now_monotonic, parsed)
    return parsed


def _parse_transitions() -> list[Transition]:
    raw = _safe_load_raw()
    entries = raw.get("transitions") or []
    if not isinstance(entries, list):
        return []
    out: list[Transition] = []
    for entry in entries:
        try:
            out.append(_dict_to_transition(entry))
        except Exception:
            continue
    return out


def _safe_load_raw() -> dict:
    """Load ``ward-animation-state.json`` as a dict, or {} on any failure.

    Validates the JSON root is a mapping. Two callers
    (``publish_transitions`` line 180, ``_load_active_transitions`` line
    254) call ``raw.get(\"transitions\")`` immediately on the returned
    value; a writer producing valid JSON whose root is null, a list, a
    string, or a number previously raised AttributeError. Same
    corruption-class as the other recent SHM-read fixes.
    """
    try:
        if WARD_ANIMATION_STATE_PATH.exists():
            data = json.loads(WARD_ANIMATION_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            log.debug(
                "ward-animation-state.json root is %s, expected mapping",
                type(data).__name__,
            )
    except Exception:
        log.debug("ward-animation-state.json read failed", exc_info=True)
    return {}


def _dict_to_transition(entry: dict) -> Transition:
    return Transition(
        ward_id=str(entry["ward_id"]),
        property=str(entry["property"]),
        from_value=float(entry["from_value"]),
        to_value=float(entry["to_value"]),
        duration_s=float(entry["duration_s"]),
        easing=str(entry.get("easing", "linear")),
        started_at=float(entry["started_at"]),
    )


__all__ = [
    "SUPPORTED_PROPERTIES",
    "Transition",
    "WARD_ANIMATION_STATE_PATH",
    "append_transitions",
    "clear_animation_cache",
    "evaluate_all",
    "evaluate_transition",
    "is_expired",
]
