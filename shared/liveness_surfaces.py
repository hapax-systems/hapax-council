"""Support-only adapters for liveness observation surfaces.

The surface registry names frozen symbolic effect adapters. It contains no
executable argv and cannot launch, resume, reap, or re-arm anything. A scan may
project a generic protected-action HOLD for those symbolic candidates.
"""

from __future__ import annotations

import sys
from pathlib import Path

from shared.liveness import EffectAdapterDescriptor, LivenessSpec, emit_heartbeat, register

LANE_PROGRESS_STALL_T_S = 900.0
DEPLOY_LAG_BUDGET_S = 1800.0


def lane_progress_op_id(role: str) -> str:
    return f"lane:{role}:progress"


def lane_progress_spec(role: str) -> LivenessSpec:
    return LivenessSpec(
        op_id=lane_progress_op_id(role),
        adapter=EffectAdapterDescriptor(
            adapter_id="hapax.lane.resume.v1",
            action_kind="lane.resume",
            target_id=role,
        ),
        max_quiet_s=LANE_PROGRESS_STALL_T_S,
        lineage=role,
        description="output progress observation; resume candidate remains held",
    )


def lane_progress_heartbeat(
    role: str,
    *,
    output_mtime: float,
    output_lines: int,
    beat_dir: Path | None = None,
) -> Path:
    return emit_heartbeat(
        lane_progress_op_id(role),
        output_lines,
        ts=output_mtime,
        beat_dir=beat_dir,
    )


def legacy_lane_progress_stalled(
    output_mtime: float,
    now: float,
    *,
    stall_t: float = LANE_PROGRESS_STALL_T_S,
) -> bool:
    """Historical predicate retained for read-only comparative conformance."""
    return (now - output_mtime) > stall_t


def reaper_op_id(role: str) -> str:
    return f"reaper:{role}"


def reaper_spec(role: str) -> LivenessSpec:
    return LivenessSpec(
        op_id=reaper_op_id(role),
        adapter=EffectAdapterDescriptor(
            adapter_id="hapax.lane.reap.v1",
            action_kind="lane.reap",
            target_id=role,
        ),
        max_quiet_s=None,
        lineage=role,
        description="measured-tau observation; reap candidate remains held",
    )


def reaper_heartbeat(
    role: str,
    *,
    last_progress_ts: float,
    progress_token: str | int,
    beat_dir: Path | None = None,
) -> Path:
    return emit_heartbeat(
        reaper_op_id(role),
        progress_token,
        ts=last_progress_ts,
        beat_dir=beat_dir,
    )


def legacy_reaper_stalled(progress_age_s: float, tau_s: float) -> bool:
    """Historical predicate retained for read-only comparative conformance."""
    return progress_age_s > tau_s


def deploy_op_id() -> str:
    return "deploy:post-merge"


def deploy_spec() -> LivenessSpec:
    return LivenessSpec(
        op_id=deploy_op_id(),
        adapter=EffectAdapterDescriptor(
            adapter_id="hapax.deploy.rearm.v1",
            action_kind="deploy.rearm",
            target_id="post-merge",
        ),
        max_quiet_s=DEPLOY_LAG_BUDGET_S,
        lineage="deploy",
        description="deployment freshness observation; re-arm candidate remains held",
    )


def deploy_heartbeat(
    *,
    last_deployed_ts: float,
    last_deployed_sha: str,
    beat_dir: Path | None = None,
) -> Path:
    return emit_heartbeat(
        deploy_op_id(),
        last_deployed_sha,
        ts=last_deployed_ts,
        beat_dir=beat_dir,
    )


def legacy_deploy_stalled(
    last_deployed_ts: float,
    now: float,
    *,
    budget: float = DEPLOY_LAG_BUDGET_S,
) -> bool:
    """Historical predicate retained for read-only comparative conformance."""
    return (now - last_deployed_ts) > budget


def proof_surface_specs(roles: list[str]) -> list[LivenessSpec]:
    """Build immutable declarations without reading or writing registry state."""
    specs: list[LivenessSpec] = []
    for role in roles:
        specs.extend((lane_progress_spec(role), reaper_spec(role)))
    specs.append(deploy_spec())
    return specs


def register_proof_surfaces(
    roles: list[str],
    *,
    registry_dir: Path | None = None,
) -> list[LivenessSpec]:
    """Persist explicit support-only declarations; never register executable data."""
    specs = proof_surface_specs(roles)
    for spec in specs:
        register(spec, registry_dir=registry_dir)
    return specs


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(
            "usage: liveness_surfaces list <role...> | install <role...> | "
            "beat-lane-progress <role> <mtime> <lines> | "
            "beat-reaper <role> <ts> <token> | beat-deploy <ts> <sha>",
            file=sys.stderr,
        )
        return 2
    command, rest = argv[0], argv[1:]
    if command == "list":
        for spec in proof_surface_specs(rest or ["alpha", "beta"]):
            assert spec.adapter is not None
            print(
                f"{spec.op_id}\t{spec.adapter.adapter_id}\t"
                f"{spec.adapter.action_kind}\theld_not_admitted"
            )
        return 0
    if command == "install":
        for spec in register_proof_surfaces(rest or ["alpha", "beta"]):
            print(f"{spec.op_id}\tsupport-only")
        return 0
    if command == "beat-lane-progress":
        role, mtime, lines = rest[0], float(rest[1]), int(rest[2])
        lane_progress_heartbeat(role, output_mtime=mtime, output_lines=lines)
        return 0
    if command == "beat-reaper":
        role, ts, token = rest[0], float(rest[1]), rest[2]
        reaper_heartbeat(role, last_progress_ts=ts, progress_token=token)
        return 0
    if command == "beat-deploy":
        ts, sha = float(rest[0]), rest[1]
        deploy_heartbeat(last_deployed_ts=ts, last_deployed_sha=sha)
        return 0
    print(f"unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
