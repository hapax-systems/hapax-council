"""Adaptive threshold tuning for health checks.

Allows LLM-assisted or manual threshold overrides for noisy checks.
Persists to profiles/health-thresholds.json.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC
from pathlib import Path

from pydantic import BaseModel

from shared.config import PROFILES_DIR

THRESHOLDS_FILE = PROFILES_DIR / "health-thresholds.json"


class ThresholdOverride(BaseModel):
    """Override for a specific check's threshold or behavior."""

    check_name: str
    threshold_value: float | None = None  # e.g. latency ms, budget $
    suppress: bool = False  # suppress notifications entirely
    reason: str = ""
    updated_at: str = ""


def load_thresholds(path: Path | None = None) -> dict[str, ThresholdOverride]:
    """Load threshold overrides from JSON file."""
    path = path or THRESHOLDS_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return {name: ThresholdOverride.model_validate(entry) for name, entry in data.items()}
    except (json.JSONDecodeError, OSError):
        return {}


def save_thresholds(
    overrides: dict[str, ThresholdOverride],
    path: Path | None = None,
) -> None:
    """Save threshold overrides to JSON file."""
    path = path or THRESHOLDS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {name: o.model_dump() for name, o in overrides.items()}
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".json")
    try:
        with open(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def get_threshold(check_name: str, default: float, path: Path | None = None) -> float:
    """Get threshold for a check, returning override value or default."""
    overrides = load_thresholds(path)
    override = overrides.get(check_name)
    if override and override.threshold_value is not None:
        return override.threshold_value
    return default


def is_suppressed(check_name: str, path: Path | None = None) -> bool:
    """Check if a check's notifications are suppressed."""
    overrides = load_thresholds(path)
    override = overrides.get(check_name)
    return override.suppress if override else False


async def tune_thresholds(
    noisy_checks: list[dict],
    history_summary: str = "",
) -> list[ThresholdOverride]:
    """LLM-assisted threshold tuning for noisy checks.

    Args:
        noisy_checks: Checks that flip frequently [{name, current_threshold, failure_rate}].
        history_summary: Summary of recent health history patterns.
    """
    from datetime import datetime

    from pydantic_ai import Agent

    from shared.config import get_model

    agent = Agent(
        get_model("fast"),
        output_type=list[ThresholdOverride],
        system_prompt=(
            "You are tuning health check thresholds. For each noisy check, recommend "
            "either a new threshold value (if the current one is too aggressive) or "
            "suppression (if the check is not meaningful). Provide a reason for each."
        ),
    )

    checks_text = "\n".join(
        f"- {c['name']}: threshold={c.get('current_threshold', '?')}, "
        f"failure_rate={c.get('failure_rate', '?')}"
        for c in noisy_checks
    )
    prompt = f"## Noisy Checks\n{checks_text}"
    if history_summary:
        prompt += f"\n\n## History Context\n{history_summary}"

    result = await agent.run(prompt)
    now = datetime.now(UTC).isoformat()
    for o in result.output:
        o.updated_at = now
    return result.output
