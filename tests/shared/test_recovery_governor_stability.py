"""Stability acceptance test — the simulation IS the proof.

A discrete-time model of the recovery loop on a 16-core box. Each recovery
action costs ~1.5 cores for U(60,180)s. Staleness is *latency-coupled*: when load
per core crosses a threshold, even healthy/recovered targets APPEAR stale and the
loop re-fires recovery on them — the Bronson metastable *sustaining effect*.

  - WITHOUT the governor: seeding 50 simultaneously-stale targets makes load blow
    past the ceiling and STAY pinned (reproduces the load-30 coordinator death).
  - WITH the governor: the token-bucket + in-flight concurrency cap hold load far
    below the ceiling, so it never crosses the false-staleness threshold, the
    positive feedback never ignites, and all 50 targets still recover (queued,
    never dropped) → final_stale == 0.
  - WITH the governor in PSI-unreadable DEGRADED mode (MF1): the *tightened*
    bucket (burst 1, 1/30s) is ALSO safe standalone — load stays under the ceiling
    and all targets still drain. This bounds the verified fail-open path.

The model is fully seeded → deterministic, so the HARD_CEIL assertion can be a
hard CI gate without flaking.
"""

from __future__ import annotations

import random
import types
from pathlib import Path

from shared import recovery_governor as rg

CORES = 16
RECOVERY_COST = 1.5  # cores per in-flight relaunch
HARD_CEIL = 20.0  # load units — the incident blew past this; the governor must not
N_TARGETS = 50
STALE_LPC = 1.0  # load-per-core above which staleness becomes latency-coupled
DT = 1.0


def _state_from_lpc(lpc: float) -> str:
    """Real #3850 research-mode bands (paced 1.5/core, closed 3.0/core)."""
    if lpc >= 3.0:
        return "closed"
    if lpc >= 1.5:
        return "paced"
    return "open"


def _make_governor(tmp: Path, box: dict, *, readable: bool = True) -> rg.RecoveryGovernor:
    return rg.RecoveryGovernor(
        state_dir=tmp,
        admission_fn=lambda: types.SimpleNamespace(state=_state_from_lpc(box["lpc"])),
        psi_readable_fn=lambda: readable,
        jitter_fn=lambda d: d,  # deterministic
        critical_validator_fn=lambda target: False,
        notify_fn=lambda *a, **k: None,
        mint_fn=lambda target, detail: tmp / "esc.md",
        shielded_fn=lambda: True,
        mode="enforce",
    )


def _simulate(governor: rg.RecoveryGovernor | None, *, horizon: float, seed: int, box: dict):
    """Run the loop. Returns (peak_load, final_stale, end_load)."""
    rng = random.Random(seed)
    broken: set[int] = set(range(N_TARGETS))  # genuinely needs recovery
    active: dict[int, float] = {}  # target -> recovery end time
    peak = 0.0
    t = 0.0
    while t < horizon and (broken or active):
        # 1. complete finished recoveries (success → target recovered).
        for tg in [tg for tg, end in active.items() if end <= t]:
            del active[tg]
            broken.discard(tg)
            if governor is not None:
                governor.record_outcome(f"lane:{tg}", success=True, now=t)

        # 2. load + the latency coupling that drives false staleness.
        load = RECOVERY_COST * len(active)
        peak = max(peak, load)
        box["lpc"] = load / CORES
        false_stale = box["lpc"] > STALE_LPC

        # 3. who appears stale this tick (broken + everyone, under high load).
        candidates = [tg for tg in broken if tg not in active]
        if false_stale:
            candidates += [tg for tg in range(N_TARGETS) if tg not in broken and tg not in active]

        # 4. fire recovery for apparently-stale targets.
        if governor is None:
            for tg in candidates:  # unthrottled storm — the status quo
                active[tg] = t + rng.uniform(60.0, 180.0)
        else:
            slots = max(0, governor._params.max_concurrent_relaunch - len(active))
            for tg in candidates[:slots]:  # a real loop relaunches up to free slots
                if governor.permit(f"lane:{tg}", now=t).permitted:
                    active[tg] = t + rng.uniform(60.0, 180.0)

        t += DT

    return peak, len(broken), RECOVERY_COST * len(active)


# ── The two control cases in one test (design § Stability argument) ──────────


def test_without_governor_load_diverges_past_the_ceiling() -> None:
    # Reproduces the incident: 50 stale targets → load blows past HARD_CEIL and
    # stays pinned (metastable — does not drain on its own).
    peak, _, end_load = _simulate(None, horizon=300.0, seed=1, box={"lpc": 0.0})
    assert peak > HARD_CEIL
    assert end_load > HARD_CEIL  # still pinned — the sustaining effect persists


def test_with_governor_load_stays_below_ceiling_and_all_recover(tmp_path: Path) -> None:
    box = {"lpc": 0.0}
    gov = _make_governor(tmp_path, box)
    peak, final_stale, _ = _simulate(gov, horizon=6000.0, seed=1, box=box)
    assert peak < HARD_CEIL  # the bucket + concurrency cap hold the line
    assert final_stale == 0  # queue-never-drop: every target eventually recovered


def test_degraded_psi_unreadable_bucket_is_also_safe_standalone(tmp_path: Path) -> None:
    # MF1: the verified fail-open path (PSI unreadable → tightened bucket, no PSI
    # term) must itself stay under the ceiling and still drain.
    box = {"lpc": 0.0}
    gov = _make_governor(tmp_path, box, readable=False)
    peak, final_stale, _ = _simulate(gov, horizon=8000.0, seed=1, box=box)
    assert peak < HARD_CEIL
    assert final_stale == 0


def test_governor_peak_is_bounded_by_concurrency_times_cost(tmp_path: Path) -> None:
    # The analytic bound the sim confirms: peak ≤ max_concurrent × cost ≪ ceiling.
    box = {"lpc": 0.0}
    gov = _make_governor(tmp_path, box)
    peak, _, _ = _simulate(gov, horizon=6000.0, seed=7, box=box)
    assert peak <= rg.RecoveryParams().max_concurrent_relaunch * RECOVERY_COST
