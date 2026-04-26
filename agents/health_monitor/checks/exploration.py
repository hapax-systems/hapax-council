"""Exploration writer liveness checks.

Each of the 13 wired components (see `Unified Semantic Recruitment §
Exploration -> SEEKING`) publishes an ExplorationSignal JSON to
`/dev/shm/hapax-exploration/{component}.json`. When a writer stalls, the
VLA-consumed aggregate boredom stops updating and the SEEKING stance
transition gate degrades silently. This check catches per-file staleness
> 120s and emits a degraded/failed CheckResult with a targeted remediation.

REGRESSION-2 (2026-04-18): the canonical `stimmung` writer had stalled for
~22h because VLA owned the only StimmungCollector but had
`enable_exploration=False`. The expected-writer map below is the contract
that would have caught it.
"""

from __future__ import annotations

import time
from pathlib import Path

from shared.exploration_writer import publish_exploration_signal

from ..models import CheckResult, Status
from ..registry import check_group

EXPLORATION_DIR = Path("/dev/shm/hapax-exploration")

# Max acceptable age in seconds before a writer is considered stalled.
STALE_THRESHOLD_S = 120.0
# Absolute death threshold - file has not been touched for this long.
DEAD_THRESHOLD_S = 600.0

# Component -> systemd user service responsible for the writer. Used to
# produce targeted remediation on stall. The map is intentionally explicit
# (rather than dynamic) so missing writers surface as a DEGRADED result
# rather than silently absent.
COMPONENT_OWNERS: dict[str, str] = {
    "stimmung": "visual-layer-aggregator",
    "temporal_bands": "visual-layer-aggregator",
    "dmn_pulse": "hapax-dmn",
    "dmn_imagination": "hapax-imagination-loop",
    "visual_chain": "hapax-reverie",
    "affordance_pipeline": "hapax-daimonion",
    "salience_router": "hapax-daimonion",
    "contact_mic": "hapax-daimonion",
    "ir_presence": "hapax-daimonion",
    "input_activity": "hapax-daimonion",
    "content_resolver": "hapax-content-resolver",
    "apperception": "visual-layer-aggregator",
    # `voice_state` was registered in PR #1070 (2026-04-18) without the
    # corresponding writer in agents/hapax_daimonion/. The probe's
    # missing-file branch issued ``systemctl --user restart
    # hapax-daimonion`` every 15 min via the health-monitor timer, which
    # cost daimonion 80–150 s of cold-start (Kokoro preload + bridge
    # phrases) on each cycle and prevented it from ever reaching
    # steady-state TTS production — voice silence on stream for hours.
    # Re-add this entry once a daimonion module actually calls
    # `publish_exploration_signal("voice_state", ...)`.
}


def _age_s(path: Path) -> float | None:
    """Return seconds since last mtime, or None if file missing."""
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return None


@check_group("perception")
async def check_exploration_writers() -> list[CheckResult]:
    """Check that each expected exploration writer has written < 120s ago.

    Emits one CheckResult per expected component. Missing files produce a
    DEGRADED result with a restart remediation for the owning service.
    """
    results: list[CheckResult] = []

    if not EXPLORATION_DIR.exists():
        results.append(
            CheckResult(
                name="exploration_dir",
                group="perception",
                status=Status.FAILED,
                message=f"{EXPLORATION_DIR} missing - no writers are running",
                remediation="systemctl --user restart visual-layer-aggregator",
            )
        )
        return results

    for component, owner in COMPONENT_OWNERS.items():
        path = EXPLORATION_DIR / f"{component}.json"
        age = _age_s(path)
        if age is None:
            # Missing file: some components (voice_state) may legitimately
            # be absent when their subsystem is disabled, so use DEGRADED
            # not FAILED. Aggregate absence is caught by the dir check above.
            results.append(
                CheckResult(
                    name=f"exploration_{component}",
                    group="perception",
                    status=Status.DEGRADED,
                    message=f"Writer absent ({component}.json not present)",
                    remediation=f"systemctl --user restart {owner}",
                )
            )
        elif age > DEAD_THRESHOLD_S:
            results.append(
                CheckResult(
                    name=f"exploration_{component}",
                    group="perception",
                    status=Status.FAILED,
                    message=f"Writer dead ({age:.0f}s since last write)",
                    remediation=f"systemctl --user restart {owner}",
                )
            )
        elif age > STALE_THRESHOLD_S:
            results.append(
                CheckResult(
                    name=f"exploration_{component}",
                    group="perception",
                    status=Status.DEGRADED,
                    message=f"Writer stalled ({age:.0f}s since last write)",
                    remediation=f"Check {owner} - writer tick should be < 120s",
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"exploration_{component}",
                    group="perception",
                    status=Status.HEALTHY,
                    message=f"Writer fresh ({age:.0f}s)",
                )
            )

    return results


def emit_degraded_signal(component: str, reason: str = "writer_stall") -> bool:
    """Publish a degraded ExplorationSignal for a stalled component.

    Used by monitoring tools (or by the health check itself in a future
    iteration) to unblock downstream consumers of aggregate boredom so
    they can degrade gracefully rather than treating stale data as fresh.

    Returns True on successful write, False on any I/O error.
    """
    from shared.exploration import ExplorationSignal

    sig = ExplorationSignal(
        component=component,
        timestamp=time.time(),
        mean_habituation=0.0,
        max_novelty_edge=reason,
        max_novelty_score=0.0,
        error_improvement_rate=0.0,
        chronic_error=1.0,  # fully unhealthy
        mean_trace_interest=0.0,
        stagnation_duration=0.0,
        local_coherence=0.0,
        dwell_time_in_coherence=0.0,
        boredom_index=0.0,
        curiosity_index=0.0,
    )
    try:
        publish_exploration_signal(sig)
    except OSError:
        return False
    return True
