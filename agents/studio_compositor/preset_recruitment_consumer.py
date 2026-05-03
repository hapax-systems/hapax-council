"""Preset recruitment consumer — closes the director→chain mutation loop.

The compositor's director loop emits ``compositional_impingement`` events with
``preset.bias`` payloads (e.g. ``preset.bias = audio-reactive``). The
``AffordancePipeline`` recruits a matching ``fx.family.<family>`` capability
and records the family in ``/dev/shm/hapax-compositor/recent-recruitment.json``
under the ``preset.bias`` key.

Without a consumer that reads that recruitment and mutates the chain, the
recruitment is observable but inert. ``random_mode.py`` was the historical
bridge but is dead code — never wired into a service or compositor invocation
site. The director-driven recruitment of fx-presets is the operator's stated
architecture (per 2026-04-20 directive: "no random_mode; all effects recruited
by Hapax via director loop and content programming").

This module is the bridge: read the recruited family, pick a preset within it
via ``preset_family_selector.pick_and_load_mutated``, and dispatch a transition
primitive (Phase 7 of #166) that writes a sequence of mutated graphs to
``MUTATION_FILE`` over the next ~1-2 s. The primitive runs on a daemon
thread so the consumer call from the state-reader tick returns immediately;
a single-flight lock prevents two transitions from interleaving their
writes when recruitments arrive faster than the primitive runtime.

Cooldown: 8 s minimum between activations even when recruitment ticks every
second — preset.bias TTL is ~8 s, the next director compositional impingement
will refresh + we re-check at the next state-reader tick. Without cooldown the
chain would thrash visibly to viewers.
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from pathlib import Path

from .preset_family_selector import (
    family_names,
    pick_and_load_mutated,
    pick_family_with_role_bias,
)
from .random_mode import MUTATION_FILE
from .transition_primitives import PRIMITIVES, TRANSITION_NAMES, TransitionFn, fade_smooth

log = logging.getLogger(__name__)

RECRUITMENT_FILE = Path("/dev/shm/hapax-compositor/recent-recruitment.json")
COOLDOWN_S = 8.0
"""Minimum seconds between consecutive consumer activations.

Matches the director's preset.bias TTL — recruitments that re-fire within
the cooldown window represent the same compositional moment, not a new
intent. Without cooldown the chain mutation thrashes visibly when the
director loop ticks at sub-cooldown intervals.
"""

_TRANSITION_BIAS_COOLDOWN_S = 20.0
"""How fresh a ``transition.*`` recruitment must be to override the uniform
sample. Mirrors the existing ``preset.bias`` lifetime so the director can
nudge a transition with one impingement and have it land on the next
chain change."""

_last_activation_t: float = 0.0
_last_family_activated: str | None = None
_last_graph_activated: dict | None = None
_last_recruitment_ts_seen: float = 0.0

# Single-flight lock so a primitive in flight cannot be interrupted by a
# second one that started before it finished — interleaved brightness
# writes would collide on MUTATION_FILE and produce visible flicker.
_transition_lock = threading.Lock()


def _write_mutation(graph: dict) -> None:
    """Primitive callback — write a graph dict to the SHM mutation file."""
    MUTATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    MUTATION_FILE.write_text(json.dumps(graph))


def _read_recruited_transition() -> str | None:
    """Return the recently-recruited transition capability name, or None.

    Same shape as the read in ``random_mode._read_recruited_transition``
    so behaviour stays consistent if both paths are ever active. Newest
    fresh ``transition.*`` entry within the cooldown wins.
    """
    if not RECRUITMENT_FILE.exists():
        return None
    try:
        data = json.loads(RECRUITMENT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    families = data.get("families") or {}
    best: tuple[float, str] | None = None
    for fam_name, entry in families.items():
        if not isinstance(fam_name, str) or not fam_name.startswith("transition."):
            continue
        ts = entry.get("last_recruited_ts") if isinstance(entry, dict) else None
        if not isinstance(ts, (int, float)):
            continue
        if time.time() - float(ts) >= _TRANSITION_BIAS_COOLDOWN_S:
            continue
        if best is None or float(ts) > best[0]:
            best = (float(ts), fam_name)
    if best is None:
        return None
    name = best[1]
    return name if name in PRIMITIVES else None


def _select_transition() -> tuple[str, TransitionFn]:
    """Pick a transition: recruitment-bias first, uniform sample second."""
    recruited = _read_recruited_transition()
    if recruited is not None:
        return recruited, PRIMITIVES[recruited]
    name = random.choice(TRANSITION_NAMES)
    return name, PRIMITIVES[name]


def _run_transition_async(
    transition_name: str,
    transition_fn: TransitionFn,
    out_graph: dict | None,
    in_graph: dict,
) -> None:
    """Background-thread runner — the primitive sleeps, so the state-reader
    tick that called us doesn't block.

    Single-flight via ``_transition_lock``: a second activation that
    races ahead of an in-flight primitive degrades to a hard cut so the
    new family lands without two primitives fighting over the mutation
    file. The lock is acquired with ``blocking=False`` for that reason.
    """

    def _runner() -> None:
        if not _transition_lock.acquire(blocking=False):
            log.info(
                "preset recruitment: transition %s skipped (in-flight) — cutting in",
                transition_name,
            )
            try:
                _write_mutation(in_graph)
            except OSError:
                log.warning("hard-cut fallback write failed", exc_info=True)
            return
        try:
            transition_fn(out_graph, in_graph, _write_mutation)
            try:
                from shared.director_observability import emit_transition_pick

                emit_transition_pick(transition_name)
            except Exception:
                pass
        finally:
            _transition_lock.release()

    threading.Thread(target=_runner, name="preset-transition", daemon=True).start()


def process_preset_recruitment() -> bool:
    """Read recent recruitment, dispatch a transition primitive on a fresh
    fx.family recruitment.

    Returns True iff a transition was dispatched this tick. Idempotent —
    repeated calls within the cooldown window are no-ops. The actual
    chain mutation is written by the background-thread primitive over
    the next ~0.4–1.4 s; this function returns immediately.
    """
    global _last_activation_t, _last_family_activated, _last_recruitment_ts_seen
    global _last_graph_activated
    if not RECRUITMENT_FILE.exists():
        return False
    try:
        payload = json.loads(RECRUITMENT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    bias = payload.get("families", {}).get("preset.bias")
    if not isinstance(bias, dict):
        return False
    family = bias.get("family")
    last_recruited_ts = bias.get("last_recruited_ts")
    if not isinstance(family, str) or not isinstance(last_recruited_ts, (int, float)):
        return False
    if family not in family_names():
        log.debug("preset recruitment family unknown: %r", family)
        return False
    # Two short-circuits before doing the picker work:
    # 1) Already saw and consumed this exact recruitment ts → no-op.
    if last_recruited_ts <= _last_recruitment_ts_seen:
        return False
    # 2) Cooldown gate. Fresh recruitments that arrive within the cooldown
    #    window after a previous activation are dropped. This protects the
    #    chain from thrashing when the director loop ticks faster than the
    #    cooldown allows.
    now = time.monotonic()
    if (now - _last_activation_t) < COOLDOWN_S:
        return False
    seed = int(last_recruited_ts) ^ os.getpid()

    # Programme role bias — soft prior reweighting (audit-3-fix-4).
    # When HAPAX_SEGMENT_BIAS_DISABLED=1, the original family passes
    # through unchanged (preserves current behavior as kill-switch).
    if os.environ.get("HAPAX_SEGMENT_BIAS_DISABLED") != "1":
        try:
            from shared.programme_store import default_store

            active = default_store().active_programme()
            if active is not None:
                role = active.role.value
                rng_bias = random.Random(seed)
                family = pick_family_with_role_bias(family, role, rng=rng_bias)
        except Exception:
            log.debug("programme role bias failed (continuing)", exc_info=True)

    hit = pick_and_load_mutated(family, last=_last_family_activated, seed=seed)
    if hit is None:
        log.debug("preset_family_selector returned no preset for family=%r", family)
        return False
    preset_name, graph = hit
    transition_name, transition_fn = _select_transition()
    _run_transition_async(transition_name, transition_fn, _last_graph_activated, graph)
    _last_activation_t = now
    _last_family_activated = preset_name
    _last_graph_activated = graph
    _last_recruitment_ts_seen = float(last_recruited_ts)
    log.info(
        "preset recruitment: family=%r preset=%r transition=%r (recruitment_ts=%.3f)",
        family,
        preset_name,
        transition_name,
        last_recruited_ts,
    )
    return True


def _reset_state_for_tests() -> None:
    """Test helper — clears module-level state between cases.

    Production code never calls this; the state machine is intentionally
    process-lifetime so the consumer's cooldown survives across recruitment
    spikes.
    """
    global _last_activation_t, _last_family_activated, _last_recruitment_ts_seen
    global _last_graph_activated
    _last_activation_t = 0.0
    _last_family_activated = None
    _last_graph_activated = None
    _last_recruitment_ts_seen = 0.0
    # Best-effort lock release in case a previous test left it held.
    if _transition_lock.locked():
        try:
            _transition_lock.release()
        except RuntimeError:
            pass


# Quiet the import-time linter — ``fade_smooth`` is re-exported as the
# documented default-fallback primitive for callers that want to bypass
# selection.
_ = fade_smooth
