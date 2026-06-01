"""Daily Velocity:Quality Observatory feeder.

CASE-VELOCITY-QUALITY-OBSERVATORY-001. Aggregates OBJECTIVE velocity and quality
signals into a daily observation note written to the vault under the OQ-9 governed
writer (:mod:`shared.vault_ownership`). Per the observatory ISAP anti-gaming
constraint every metric is derived from immutable sources — git history, the
``hapax-velocity-report`` CI/PR JSON, and ``/dev/shm`` hook-rejection
instrumentation — never self-reported by an agent.

The note is a daemon-generated ``observatory`` type: the operator never hand-edits
it, so writing it through ``governed_note_write`` is a no-op on ownership (every key
is daemon-owned) while still going through the single governed vault egress.

Run daily (systemd timer, deploy step) via::

    uv run python -m shared.velocity_quality_observatory
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from shared.code_churn import compute_churn
from shared.vault_ownership import governed_note_write

log = logging.getLogger(__name__)

VAULT_DIR = Path.home() / "Documents" / "Personal"
OBSERVATORY_DIR = VAULT_DIR / "20-projects" / "hapax-observatory"
COUNCIL_REPO = Path.home() / "projects" / "hapax-council"
# Phase-1 instrumentation target from the observatory ISAP.
HOOK_REJECTIONS_FILE = Path("/dev/shm/hapax-observatory/hook-rejections.jsonl")

NOTE_TYPE = "observatory"


@dataclass(frozen=True)
class Observation:
    """A day's objective velocity/quality observation. ``None`` = source absent."""

    date: str
    commits: int
    lines_added: int
    lines_deleted: int
    churn_ratio: float
    hook_rejections: int | None
    prs_merged: int | None


def count_hook_rejections(
    path: Path = HOOK_REJECTIONS_FILE, *, date: str | None = None
) -> int | None:
    """Count hook-rejection JSONL records, optionally for one ``date`` (YYYY-MM-DD).

    Returns ``None`` when the instrumentation file is absent — distinguishing "not
    yet instrumented" from a true zero, so the report never claims a clean day it
    cannot actually verify.
    """
    if not path.exists():
        return None
    count = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if date is not None:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not str(record.get("ts", record.get("timestamp", ""))).startswith(date):
                continue
        count += 1
    return count


def read_velocity_report(date: str, *, observatory_dir: Path = OBSERVATORY_DIR) -> dict | None:
    """Read the JSON ``hapax-velocity-report`` already writes for ``date``, if any."""
    path = observatory_dir / f"{date}-velocity.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def collect_observation(
    date: str,
    *,
    repo: Path = COUNCIL_REPO,
    observatory_dir: Path = OBSERVATORY_DIR,
    hook_path: Path = HOOK_REJECTIONS_FILE,
) -> Observation:
    """Assemble the day's observation from objective sources only."""
    churn = compute_churn(repo, since=f"{date} 00:00:00", until=f"{date} 23:59:59")
    velocity = read_velocity_report(date, observatory_dir=observatory_dir) or {}
    prs_merged = velocity.get("velocity", {}).get("prs_merged")
    return Observation(
        date=date,
        commits=churn.commits,
        lines_added=churn.lines_added,
        lines_deleted=churn.lines_deleted,
        churn_ratio=round(churn.churn_ratio, 3),
        hook_rejections=count_hook_rejections(hook_path, date=date),
        prs_merged=prs_merged if isinstance(prs_merged, int) else None,
    )


def build_frontmatter(obs: Observation) -> dict:
    """Daemon-owned frontmatter for the observation note."""
    return {
        "type": NOTE_TYPE,
        "date": obs.date,
        "commits": obs.commits,
        "lines_added": obs.lines_added,
        "lines_deleted": obs.lines_deleted,
        "churn_ratio": obs.churn_ratio,
        "hook_rejections": obs.hook_rejections,
        "prs_merged": obs.prs_merged,
        "generated_by": "velocity_quality_observatory",
    }


def build_body(obs: Observation) -> str:
    """Render the human-readable observation body (honest about absent sources)."""
    rej = "n/a (uninstrumented)" if obs.hook_rejections is None else str(obs.hook_rejections)
    prs = "n/a" if obs.prs_merged is None else str(obs.prs_merged)
    return (
        f"# Velocity:Quality Observation — {obs.date}\n\n"
        "All metrics computed from immutable git history and CI artifacts "
        "(no self-reported figures).\n\n"
        "## Velocity\n"
        f"- Commits: {obs.commits}\n"
        f"- PRs merged: {prs}\n"
        f"- Lines added: {obs.lines_added}\n\n"
        "## Quality\n"
        f"- Lines deleted: {obs.lines_deleted}\n"
        f"- Churn ratio (deletions/additions): {obs.churn_ratio}\n"
        f"- Hook rejections: {rej}\n"
    )


def write_observation(obs: Observation, *, observatory_dir: Path = OBSERVATORY_DIR) -> Path:
    """Write the daily observation via the governed (OQ-9) vault writer."""
    path = observatory_dir / f"{obs.date}-velocity-quality.md"
    governed_note_write(
        path, frontmatter=build_frontmatter(obs), note_type=NOTE_TYPE, body=build_body(obs)
    )
    return path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    date = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    obs = collect_observation(date)
    path = write_observation(obs)
    log.info(
        "Wrote observation %s (commits=%d churn=%.3f rejections=%s)",
        path,
        obs.commits,
        obs.churn_ratio,
        obs.hook_rejections,
    )


if __name__ == "__main__":
    main()
