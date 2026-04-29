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

    observations, malformed = _load_observations(source_path)
    decisions = discover_candidates(observations, now=now, policy=policy)

    if decisions:
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        with candidate_path.open("a", encoding="utf-8") as fh:
            for decision in decisions:
                fh.write(json.dumps(decision.model_dump(mode="json"), sort_keys=True) + "\n")

    audit_rows = [
        {
            "type": "malformed_observation",
            "source": str(source_path),
            "line": item["line"],
            "error": item["error"],
            "observed_at": now.isoformat(),
        }
        for item in malformed
    ]
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
    }
    health = {
        "daemon_id": policy.daemon_id,
        "checked_at": now.isoformat(),
        "source_observation_path": str(source_path),
        "source_observation_path_exists": source_path.exists(),
        "candidate_output_path": str(candidate_path),
        "audit_output_path": str(audit_log_path),
        "counts": counts,
        "schedules_programmes_directly": False,
    }
    health_json_path.parent.mkdir(parents=True, exist_ok=True)
    health_json_path.write_text(
        json.dumps(health, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return health


def _load_observations(path: Path) -> tuple[list[ContentSourceObservation], list[dict[str, str]]]:
    observations: list[ContentSourceObservation] = []
    malformed: list[dict[str, str]] = []
    if not path.exists():
        return observations, malformed

    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            observations.append(ContentSourceObservation.model_validate_json(stripped))
        except (ValueError, ValidationError) as exc:
            malformed.append({"line": str(line_number), "error": str(exc).splitlines()[0]})
    return observations, malformed


__all__ = ["run_once"]
