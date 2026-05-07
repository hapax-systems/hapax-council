"""Runner helpers for the content candidate discovery daemon."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from shared.content_candidate_discovery import (
    ContentSourceObservation,
    DiscoveryPolicy,
    discover_candidates,
    load_policy,
)


def run_once(
    *,
    policy: DiscoveryPolicy | None = None,
    policy_path: Path | None = None,
    input_path: Path | None = None,
    output_path: Path | None = None,
    audit_path: Path | None = None,
    health_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read source observations, append candidate decisions, and write health."""

    if policy is None:
        policy = load_policy(policy_path) if policy_path is not None else load_policy()
    now = (now or datetime.now(UTC)).astimezone(UTC)
    source_path = input_path or Path(policy.paths.source_observations_jsonl)
    candidate_path = output_path or Path(policy.paths.candidate_jsonl)
    audit_log_path = audit_path or Path(policy.paths.audit_jsonl)
    health_json_path = health_path or Path(policy.paths.health_json)

    observations, malformed, source_metadata = _load_observations(source_path)
    decisions = discover_candidates(observations, now=now, policy=policy)

    if decisions:
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        with candidate_path.open("a", encoding="utf-8") as fh:
            for decision in decisions:
                fh.write(json.dumps(decision.model_dump(mode="json"), sort_keys=True) + "\n")

    audit_rows = [
        {
            "type": "malformed_observation",
            "diagnostic_only": True,
            "release_boundary": "closed",
            "runtime_boundary": "closed",
            "manifest_eligible": False,
            "qdrant_eligible": False,
            "loadable": False,
            "source": str(source_path),
            "line": item["line"],
            "error": item["error"],
            "observed_at": now.isoformat(),
        }
        for item in malformed
    ]
    no_candidate_reason = _no_candidate_reason(source_metadata, malformed)
    if not decisions:
        audit_rows.append(
            {
                "type": "no_candidate_diagnostic",
                "diagnostic_only": True,
                "release_boundary": "closed",
                "runtime_boundary": "closed",
                "manifest_eligible": False,
                "qdrant_eligible": False,
                "loadable": False,
                "observed_at": now.isoformat(),
                "source": str(source_path),
                "source_observation_path_exists": source_metadata["exists"],
                "raw_line_count": source_metadata["raw_line_count"],
                "nonempty_line_count": source_metadata["nonempty_line_count"],
                "observation_count": len(observations),
                "malformed_count": len(malformed),
                "candidate_count": 0,
                "no_candidate_reason": no_candidate_reason,
                "scheduler_action": "none",
                "scheduled_show_created": False,
                "runtime_actionable": False,
                "release_eligible": False,
            }
        )
    if audit_rows:
        audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_log_path.open("a", encoding="utf-8") as fh:
            for row in audit_rows:
                fh.write(json.dumps(row, sort_keys=True) + "\n")

    counts = {
        "emitted": sum(1 for decision in decisions if decision.status == "emitted"),
        "held": sum(1 for decision in decisions if decision.status == "held"),
        "blocked": sum(1 for decision in decisions if decision.status == "blocked"),
        "malformed": len(malformed),
        "no_candidate": 1 if not decisions else 0,
    }
    health = {
        "daemon_id": policy.daemon_id,
        "checked_at": now.isoformat(),
        "source_observation_path": str(source_path),
        "source_observation_path_exists": source_metadata["exists"],
        "source_observation_raw_line_count": source_metadata["raw_line_count"],
        "source_observation_nonempty_line_count": source_metadata["nonempty_line_count"],
        "candidate_output_path": str(candidate_path),
        "audit_output_path": str(audit_log_path),
        "counts": counts,
        "no_candidate_reason": no_candidate_reason,
        "schedules_programmes_directly": False,
    }
    health_json_path.parent.mkdir(parents=True, exist_ok=True)
    health_json_path.write_text(
        json.dumps(health, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return health


def _load_observations(
    path: Path,
) -> tuple[list[ContentSourceObservation], list[dict[str, str]], dict[str, int | bool]]:
    observations: list[ContentSourceObservation] = []
    malformed: list[dict[str, str]] = []
    metadata: dict[str, int | bool] = {
        "exists": path.exists(),
        "raw_line_count": 0,
        "nonempty_line_count": 0,
    }
    if not path.exists():
        return observations, malformed, metadata

    lines = path.read_text(encoding="utf-8").splitlines()
    metadata["raw_line_count"] = len(lines)
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        metadata["nonempty_line_count"] = int(metadata["nonempty_line_count"]) + 1
        try:
            observations.append(ContentSourceObservation.model_validate_json(stripped))
        except (ValueError, ValidationError) as exc:
            malformed.append({"line": str(line_number), "error": str(exc).splitlines()[0]})
    return observations, malformed, metadata


def _no_candidate_reason(
    source_metadata: dict[str, int | bool],
    malformed: list[dict[str, str]],
) -> str | None:
    if source_metadata["exists"] is False:
        return "source_observation_path_missing"
    if int(source_metadata["nonempty_line_count"]) == 0:
        return "source_observation_jsonl_empty"
    if malformed and int(source_metadata["nonempty_line_count"]) == len(malformed):
        return "source_observations_malformed_only"
    return None


__all__ = ["run_once"]
