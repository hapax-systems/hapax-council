#!/usr/bin/env python3
"""Summarize merged GitHub PRs for an explicit time window."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_LIMIT = 300


@dataclass(frozen=True)
class MergeWindow:
    since: datetime
    until: datetime
    timezone: str


def _parse_date_or_datetime(value: str, tz: ZoneInfo) -> tuple[datetime, bool]:
    if "T" not in value and len(value) == 10:
        parsed_date = datetime.strptime(value, "%Y-%m-%d").date()
        return datetime.combine(parsed_date, time.min, tzinfo=tz), True

    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz), False


def parse_window(since: str, until: str | None, timezone: str) -> MergeWindow:
    tz = ZoneInfo(timezone)
    since_dt, since_was_date = _parse_date_or_datetime(since, tz)
    if until is None:
        until_dt = since_dt + timedelta(days=1) if since_was_date else datetime.now(tz)
    else:
        until_dt, until_was_date = _parse_date_or_datetime(until, tz)
        if until_was_date:
            until_dt += timedelta(days=1)

    if until_dt <= since_dt:
        raise ValueError("--until must be after --since")

    return MergeWindow(
        since=since_dt.astimezone(UTC),
        until=until_dt.astimezone(UTC),
        timezone=timezone,
    )


def build_gh_command(repo: str | None, limit: int) -> list[str]:
    command = [
        "gh",
        "pr",
        "list",
        "--state",
        "merged",
        "--limit",
        str(limit),
        "--json",
        "number,title,mergedAt,author,url,headRefName,baseRefName",
    ]
    if repo:
        command.extend(["--repo", repo])
    return command


def load_prs(json_file: Path | None, repo: str | None, limit: int) -> list[dict[str, Any]]:
    if json_file is not None:
        data = json.loads(json_file.read_text(encoding="utf-8"))
    else:
        output = subprocess.check_output(build_gh_command(repo, limit), text=True)
        data = json.loads(output)

    if not isinstance(data, list):
        raise ValueError("GitHub PR JSON must be a list")
    return [item for item in data if isinstance(item, dict)]


def _parse_merged_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def filter_merged_prs(prs: list[dict[str, Any]], window: MergeWindow) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for pr in prs:
        merged_at = _parse_merged_at(pr.get("mergedAt"))
        if merged_at is None:
            continue
        if window.since <= merged_at < window.until:
            selected.append(pr)
    return sorted(selected, key=lambda item: str(item.get("mergedAt", "")))


def _author_login(pr: dict[str, Any]) -> str:
    author = pr.get("author")
    if isinstance(author, dict) and isinstance(author.get("login"), str):
        return author["login"]
    return "unknown"


def render_json(prs: list[dict[str, Any]], window: MergeWindow) -> str:
    payload = {
        "since": window.since.isoformat().replace("+00:00", "Z"),
        "until": window.until.isoformat().replace("+00:00", "Z"),
        "timezone": window.timezone,
        "count": len(prs),
        "by_author": dict(sorted(Counter(_author_login(pr) for pr in prs).items())),
        "prs": prs,
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def render_markdown(prs: list[dict[str, Any]], window: MergeWindow) -> str:
    local_tz = ZoneInfo(window.timezone)
    since_local = window.since.astimezone(local_tz).isoformat()
    until_local = window.until.astimezone(local_tz).isoformat()
    lines = [
        "# GitHub Merged PR Tally",
        "",
        f"- Window: `{since_local}` to `{until_local}`",
        f"- Count: `{len(prs)}`",
        "",
        "## By Author",
    ]
    by_author = Counter(_author_login(pr) for pr in prs)
    if by_author:
        for author, count in sorted(by_author.items()):
            lines.append(f"- `{author}`: {count}")
    else:
        lines.append("- No merged PRs in window.")
    lines.extend(["", "## Merged PRs"])
    for pr in prs:
        number = pr.get("number", "?")
        title = str(pr.get("title") or "").strip() or "(untitled)"
        url = str(pr.get("url") or "").strip()
        merged_at = str(pr.get("mergedAt") or "").strip()
        author = _author_login(pr)
        link = f"[#{number}]({url})" if url else f"#{number}"
        lines.append(f"- {link} `{merged_at}` `{author}` {title}")
    if not prs:
        lines.append("- No merged PRs in window.")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, help="ISO instant or YYYY-MM-DD start.")
    parser.add_argument(
        "--until",
        help="ISO instant or YYYY-MM-DD end. Date values are inclusive calendar days.",
    )
    parser.add_argument(
        "--timezone",
        default=os.environ.get("TZ", "UTC"),
        help="Timezone for YYYY-MM-DD windows and markdown display.",
    )
    parser.add_argument("--repo", help="GitHub repo for live gh lookup, e.g. owner/name.")
    parser.add_argument("--json-file", type=Path, help="Read gh PR JSON from a file.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    window = parse_window(args.since, args.until, args.timezone)
    prs = filter_merged_prs(load_prs(args.json_file, args.repo, args.limit), window)
    if args.format == "json":
        print(render_json(prs, window))
    else:
        print(render_markdown(prs, window), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
