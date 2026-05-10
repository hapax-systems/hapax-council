"""Daily velocity digest: summarize git activity as a public event.

Runs as a systemd oneshot timer at 23:00 CDT. Reads the day's git log
(commits, merged PRs, reverts), asks local-fast for a 280-char summary,
and writes a ResearchVehiclePublicEvent to the public event bus.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from shared.research_vehicle_public_event import (
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
    Surface,
)

log = logging.getLogger(__name__)

PUBLIC_EVENT_PATH = Path(
    os.environ.get(
        "HAPAX_RESEARCH_VEHICLE_PUBLIC_EVENT_PATH",
        "/dev/shm/hapax-public-events/events.jsonl",
    )
)
REPO_DIR = Path(
    os.environ.get("HAPAX_COUNCIL_DIR", str(Path.home() / "projects" / "hapax-council"))
)
TASK_ANCHOR = "velocity-digest-producer"

_ALLOWED_SURFACES: list[Surface] = [
    "omg_statuslog",
    "discord",
    "github_readme",
]
_ALL_OTHER_SURFACES: list[Surface] = [
    "youtube_description",
    "youtube_cuepoints",
    "youtube_chapters",
    "youtube_captions",
    "youtube_shorts",
    "youtube_channel_sections",
    "youtube_channel_trailer",
    "arena",
    "omg_weblog",
    "omg_now",
    "mastodon",
    "bluesky",
    "archive",
    "replay",
    "github_profile",
    "github_release",
    "github_package",
    "github_pages",
    "zenodo",
    "captions",
    "cuepoints",
    "health",
    "monetization",
]


@dataclass(frozen=True)
class GitStats:
    total_commits: int
    prs_merged: int
    reverts: int
    subjects: list[str]
    files_changed: int
    areas: list[str]


def gather_git_stats(repo_dir: Path, day: date) -> GitStats:
    since = day.isoformat()
    until = (day.isoformat()) + "T23:59:59"

    result = subprocess.run(
        ["git", "log", "--oneline", "--since", since, "--until", until, "origin/main"],
        capture_output=True,
        text=True,
        cwd=repo_dir,
        timeout=30,
    )
    lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
    subjects = [line.split(" ", 1)[1] if " " in line else line for line in lines]

    merge_pat = re.compile(r"Merge pull request|merge.*#\d+|\(#\d+\)", re.IGNORECASE)
    prs_merged = sum(1 for s in subjects if merge_pat.search(s))

    revert_pat = re.compile(r"\brevert\b", re.IGNORECASE)
    reverts = sum(1 for s in subjects if revert_pat.search(s))

    diff_result = subprocess.run(
        [
            "git",
            "log",
            "--name-only",
            "--pretty=format:",
            "--since",
            since,
            "--until",
            until,
            "origin/main",
        ],
        capture_output=True,
        text=True,
        cwd=repo_dir,
        timeout=30,
    )
    changed_files = {f for f in diff_result.stdout.strip().splitlines() if f.strip()}

    area_set: set[str] = set()
    for f in changed_files:
        parts = f.split("/")
        if len(parts) >= 2:
            area_set.add(parts[0] + "/" + parts[1])
        else:
            area_set.add(parts[0])
    areas = sorted(area_set)[:10]

    return GitStats(
        total_commits=len(lines),
        prs_merged=prs_merged,
        reverts=reverts,
        subjects=subjects[:20],
        files_changed=len(changed_files),
        areas=areas,
    )


async def compose_summary(stats: GitStats) -> str:
    from pydantic_ai import Agent

    from shared.config import get_model

    if stats.total_commits == 0:
        return "Quiet day. No commits landed on main."

    area_str = ", ".join(stats.areas[:5]) if stats.areas else "various"
    prompt = (
        "Summarize this day's development activity in under 280 characters. "
        "Be factual, specific, terse. Include key numbers. No hashtags.\n\n"
        f"Commits: {stats.total_commits}\n"
        f"PRs merged: {stats.prs_merged}\n"
        f"Reverts: {stats.reverts}\n"
        f"Files changed: {stats.files_changed}\n"
        f"Areas: {area_str}\n\n"
        "Recent subjects:\n" + "\n".join(f"- {s}" for s in stats.subjects[:12])
    )

    agent: Agent[None, str] = Agent(get_model("local-fast"), output_type=str)
    result = await agent.run(prompt)
    summary = result.output.strip()
    if len(summary) > 280:
        summary = summary[:277] + "..."
    return summary


def _fallback_summary(stats: GitStats) -> str:
    parts = [f"{stats.total_commits} commits"]
    if stats.prs_merged:
        parts.append(f"{stats.prs_merged} PRs merged")
    if stats.reverts:
        parts.append(f"{stats.reverts} reverts")
    parts.append(f"{stats.files_changed} files changed")
    if stats.areas:
        parts.append(f"in {', '.join(stats.areas[:3])}")
    return ". ".join(parts) + "."


def build_velocity_digest_event(
    summary: str,
    stats: GitStats,
    day: date,
    now: datetime,
) -> ResearchVehiclePublicEvent:
    event_id = f"rvpe:velocity_digest:{day.isoformat()}"
    occurred_at = now.astimezone(UTC).isoformat().replace("+00:00", "Z")
    generated_at = occurred_at

    return ResearchVehiclePublicEvent(
        schema_version=1,
        event_id=event_id,
        event_type="velocity.digest",
        occurred_at=occurred_at,
        broadcast_id=None,
        programme_id=None,
        condition_id=None,
        source=PublicEventSource(
            producer="agents.velocity_digest_public_event_producer",
            substrate_id="git_log",
            task_anchor=TASK_ANCHOR,
            evidence_ref=f"git log --since {day.isoformat()} origin/main",
            freshness_ref=None,
        ),
        salience=0.45,
        state_kind="research_observation",
        rights_class="operator_original",
        privacy_class="public_safe",
        provenance=PublicEventProvenance(
            token=f"velocity_digest:{day.isoformat()}",
            generated_at=generated_at,
            producer="agents.velocity_digest_public_event_producer",
            evidence_refs=[
                "git.log.main.daily",
                f"commits:{stats.total_commits}",
                f"prs:{stats.prs_merged}",
            ],
            rights_basis="operator git activity summary",
            citation_refs=[],
        ),
        public_url=None,
        frame_ref=None,
        chapter_ref=None,
        attribution_refs=[],
        surface_policy=PublicEventSurfacePolicy(
            allowed_surfaces=_ALLOWED_SURFACES,
            denied_surfaces=_ALL_OTHER_SURFACES,
            claim_live=False,
            claim_archive=True,
            claim_monetizable=False,
            requires_egress_public_claim=False,
            requires_audio_safe=False,
            requires_provenance=True,
            requires_human_review=False,
            rate_limit_key="velocity.digest:daily",
            redaction_policy="none",
            fallback_action="hold",
            dry_run_reason=None,
        ),
    )


def _event_already_written(event_id: str, path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    for line in text.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("event_id") == event_id:
            return True
    return False


def _append_event(event: ResearchVehiclePublicEvent, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(event.to_json_line())


async def _run(day: date, repo_dir: Path, output_path: Path) -> int:
    subprocess.run(
        ["git", "fetch", "origin", "main", "--quiet", "--no-tags"],
        cwd=repo_dir,
        timeout=30,
        check=False,
    )

    stats = gather_git_stats(repo_dir, day)
    log.info(
        "git stats for %s: %d commits, %d PRs, %d reverts, %d files",
        day,
        stats.total_commits,
        stats.prs_merged,
        stats.reverts,
        stats.files_changed,
    )

    event_id = f"rvpe:velocity_digest:{day.isoformat()}"
    if _event_already_written(event_id, output_path):
        log.info("event %s already written, skipping", event_id)
        return 0

    try:
        summary = await compose_summary(stats)
    except Exception:
        log.warning("LLM summary failed, using fallback", exc_info=True)
        summary = _fallback_summary(stats)

    log.info("summary (%d chars): %s", len(summary), summary)

    now = datetime.now(UTC)
    event = build_velocity_digest_event(summary, stats, day, now)
    _append_event(event, output_path)
    log.info("wrote event %s", event.event_id)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--day",
        type=date.fromisoformat,
        default=None,
        help="Date to summarize (default: today)",
    )
    parser.add_argument("--repo-dir", type=Path, default=REPO_DIR)
    parser.add_argument("--output", type=Path, default=PUBLIC_EVENT_PATH)
    args = parser.parse_args(argv)

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    day = args.day or date.today()
    return 0 if asyncio.run(_run(day, args.repo_dir, args.output)) >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "GitStats",
    "build_velocity_digest_event",
    "compose_summary",
    "gather_git_stats",
    "main",
]
