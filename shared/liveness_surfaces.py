"""shared/liveness_surfaces.py — first surfaces migrated onto the liveness substrate.

Each legacy per-surface watchdog is re-expressed as (a) a :class:`LivenessSpec`
registration and (b) a heartbeat adapter mapping its existing liveness signal onto
a substrate :class:`~shared.liveness.Heartbeat`. The accompanying ``legacy_*``
decision functions are the *exact* staleness predicate each bespoke watchdog uses
today; ``tests/shared/test_liveness_surfaces.py`` asserts the substrate's verdict
equals the legacy decision across representative inputs, so each cutover is
behavior-preserving (the bespoke loop is retired only once its regression is
green — no silent dual-run).

The recovery *bound* is NOT mirrored here — it stays the shared
:class:`~shared.recovery_governor.RecoveryGovernor`'s. Only the surface's own
*staleness threshold* (which it already owns) is carried over.

Proof surfaces (design doc §Migration):
- ``lane:<role>:progress`` — the #3852 output-stall watchdog (resume/nudge).
- ``reaper:<role>``        — the measured-tau bounded reaper (kill + re-offer).
- ``deploy:post-merge``    — the #3840 deploy-staleness alarm (re-arm).
"""

from __future__ import annotations

import sys
from pathlib import Path

from shared.dispatch_service_time import should_reap
from shared.liveness import LivenessSpec, emit_heartbeat, register

# Staleness thresholds carried over verbatim from each legacy surface. The bound
# (max_attempts/backoff) is the governor's; only the threshold is the surface's.
LANE_PROGRESS_STALL_T_S = 900.0  # hapax-lane-supervisor STALL_T default (15 min)
DEPLOY_LAG_BUDGET_S = 1800.0  # post-merge-deploy staleness budget (30 min)


# ── lane-progress: output-stall (#3852) ──────────────────────────────────────


def lane_progress_op_id(role: str) -> str:
    return f"lane:{role}:progress"


def lane_progress_spec(role: str, *, resume_cmd: list[str]) -> LivenessSpec:
    """The lane's natural progress (``output.jsonl`` growth) is its heartbeat;
    stalling past ``STALL_T`` with no new output triggers ``resume_cmd``."""
    return LivenessSpec(
        op_id=lane_progress_op_id(role),
        recovery_cmd=resume_cmd,
        max_quiet_s=LANE_PROGRESS_STALL_T_S,
        lineage=role,
        description="output.jsonl stall → resume/nudge (was hapax-lane-supervisor progress_guard)",
    )


def lane_progress_heartbeat(
    role: str, *, output_mtime: float, output_lines: int, beat_dir: Path | None = None
) -> Path:
    """``ts`` = last ``output.jsonl`` write (mtime); ``token`` = cumulative line
    count (the monotonic progress token — growth means the turn is progressing)."""
    return emit_heartbeat(
        lane_progress_op_id(role), output_lines, ts=output_mtime, beat_dir=beat_dir
    )


def legacy_lane_progress_stalled(
    output_mtime: float, now: float, *, stall_t: float = LANE_PROGRESS_STALL_T_S
) -> bool:
    """The legacy ``hapax-lane-supervisor`` staleness predicate: the lane is a
    stall candidate iff ``output.jsonl`` has been silent longer than ``STALL_T``."""
    return (now - output_mtime) > stall_t


# ── reaper: measured-tau bounded reap ────────────────────────────────────────


def reaper_op_id(role: str) -> str:
    return f"reaper:{role}"


def reaper_spec(role: str, *, kill_cmd: list[str]) -> LivenessSpec:
    """No explicit threshold → the watchdog uses the measured per-lineage tau from
    ``dispatch_service_time`` (the same oracle the legacy reaper reads)."""
    return LivenessSpec(
        op_id=reaper_op_id(role),
        recovery_cmd=kill_cmd,
        max_quiet_s=None,  # measured tau
        lineage=role,
        description="silent past measured tau → bounded reap (was hapax-lane-reaper)",
    )


def reaper_heartbeat(
    role: str, *, last_progress_ts: float, progress_token: str | int, beat_dir: Path | None = None
) -> Path:
    """``ts`` = last tool-call/progress time; ``token`` = a monotonic progress
    counter so a long-but-progressing turn is never reaped (the Gittins move)."""
    return emit_heartbeat(
        reaper_op_id(role), progress_token, ts=last_progress_ts, beat_dir=beat_dir
    )


def legacy_reaper_stalled(progress_age_s: float, tau_s: float) -> bool:
    """The legacy ``dispatch_service_time.should_reap`` predicate: reap candidate
    iff silent longer than the measured tau."""
    return should_reap(progress_age_s, tau_s)


# ── deploy: post-merge staleness alarm (#3840) ───────────────────────────────


def deploy_op_id() -> str:
    return "deploy:post-merge"


def deploy_spec(*, rearm_cmd: list[str]) -> LivenessSpec:
    return LivenessSpec(
        op_id=deploy_op_id(),
        recovery_cmd=rearm_cmd,
        max_quiet_s=DEPLOY_LAG_BUDGET_S,
        lineage="deploy",
        description="last-deployed-sha lag → re-arm deploy (was post-merge-deploy alarm)",
    )


def deploy_heartbeat(
    *, last_deployed_ts: float, last_deployed_sha: str, beat_dir: Path | None = None
) -> Path:
    """``ts`` = last successful deploy time; ``token`` = last-deployed sha (advances
    every time the chain ships, so a keeping-up deploy reads ``alive``)."""
    return emit_heartbeat(deploy_op_id(), last_deployed_sha, ts=last_deployed_ts, beat_dir=beat_dir)


def legacy_deploy_stalled(
    last_deployed_ts: float, now: float, *, budget: float = DEPLOY_LAG_BUDGET_S
) -> bool:
    """The legacy deploy-staleness alarm: the chain is stalled iff the last
    successful deploy is older than the budget (commits pending past it)."""
    return (now - last_deployed_ts) > budget


# ── registration ──────────────────────────────────────────────────────────────

# Cutover wiring — the entrypoint each surface's recovery dispatches to. These are
# the existing fleet scripts; the substrate drives them, it does not reimplement
# them. Verify each flag against the script before enabling the surface in prod.
SURFACE_RECOVERY: dict[str, list[str]] = {
    "lane_progress": ["scripts/hapax-lane-supervisor", "--resume-lane"],  # + role appended
    "reaper": ["scripts/hapax-lane-reaper", "--reap-lineage"],  # + role appended
    "deploy": ["scripts/hapax-post-merge-deploy", "--rearm"],
}


def register_proof_surfaces(
    roles: list[str],
    *,
    registry_dir: Path | None = None,
    recovery: dict[str, list[str]] | None = None,
) -> list[LivenessSpec]:
    """Register the three proof surfaces for ``roles`` (idempotent). Returns the
    specs registered. ``recovery`` overrides the default cutover entrypoints."""
    recovery = recovery or SURFACE_RECOVERY
    specs: list[LivenessSpec] = []
    for role in roles:
        specs.append(lane_progress_spec(role, resume_cmd=[*recovery["lane_progress"], role]))
        specs.append(reaper_spec(role, kill_cmd=[*recovery["reaper"], role]))
    specs.append(deploy_spec(rearm_cmd=list(recovery["deploy"])))
    for spec in specs:
        register(spec, registry_dir=registry_dir)
    return specs


# ── CLI — the cutover entrypoints the bash surfaces call ─────────────────────


def main(argv: list[str] | None = None) -> int:
    """Install the proof surfaces, or emit a surface heartbeat. These are the
    cutover entrypoints a live (bash) surface invokes — ``install`` registers the
    specs once; ``beat-*`` maps a surface's existing signal onto a heartbeat."""
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(
            "usage: liveness_surfaces install <role...> | "
            "beat-lane-progress <role> <mtime> <lines> | "
            "beat-reaper <role> <ts> <token> | beat-deploy <ts> <sha>",
            file=sys.stderr,
        )
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "install":
        for spec in register_proof_surfaces(rest or ["alpha", "beta"]):
            print(spec.op_id)
        return 0
    if cmd == "beat-lane-progress":
        role, mtime, lines = rest[0], float(rest[1]), int(rest[2])
        lane_progress_heartbeat(role, output_mtime=mtime, output_lines=lines)
        return 0
    if cmd == "beat-reaper":
        role, ts, token = rest[0], float(rest[1]), rest[2]
        reaper_heartbeat(role, last_progress_ts=ts, progress_token=token)
        return 0
    if cmd == "beat-deploy":
        ts, sha = float(rest[0]), rest[1]
        deploy_heartbeat(last_deployed_ts=ts, last_deployed_sha=sha)
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
