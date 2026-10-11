"""One sensing pass over the declared sources.

Only sources whose cadence has elapsed are fetched. New items are recorded
once each to the desk's scan intake, keyed by canonical URL plus content
hash; items older than the bootstrap window are marked seen without being
recorded. Reach is reported per source: unreachable stays unreachable.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agents.discourse_sensing.fetch import fetch_url
from agents.discourse_sensing.intake import append_items, write_run_report
from agents.discourse_sensing.parsers import parse_bluesky_feed, parse_feed, parse_hn_search
from agents.discourse_sensing.sources import load_sources
from agents.discourse_sensing.state import load_state, save_state, state_path

if TYPE_CHECKING:
    from pathlib import Path

    from agents.discourse_sensing.parsers import SensedItem
    from agents.discourse_sensing.sources import SourceSpec
    from agents.discourse_sensing.state import SensingState

BOOTSTRAP_SECONDS = 86400


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_new(state: SensingState, item: SensedItem) -> bool:
    return state.seen.get(item.canonical_url) != item.content_hash


def _older_than_bootstrap(item: SensedItem, now_epoch: int, bootstrap_seconds: int) -> bool:
    if not item.published_at:
        return False
    try:
        published = datetime.strptime(item.published_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    published = published.replace(tzinfo=UTC)
    return (now_epoch - int(published.timestamp())) > bootstrap_seconds


def _parse_items(spec: SourceSpec, body: bytes) -> list[SensedItem]:
    if spec.kind == "bluesky_author_feed":
        return parse_bluesky_feed(json.loads(body), spec.id, spec.actor or "")
    if spec.kind == "rss_feed":
        return parse_feed(body, spec.id, spec.url or "")
    return parse_hn_search(json.loads(body), spec.id, spec.query or "")


def run_once(
    sources_path: str | Path,
    intake_dir: str | Path,
    now_epoch: int | None = None,
    timeout_s: float = 20.0,
    limit: int = 100,
    bootstrap_seconds: int = BOOTSTRAP_SECONDS,
) -> dict:
    """Run one sensing pass and return the per-run, per-source report."""
    now = int(now_epoch if now_epoch is not None else time.time())
    started_iso = _iso(now)
    since_epoch = now - bootstrap_seconds
    specs = load_sources(sources_path)
    state = load_state(state_path(intake_dir))

    rows: list[dict] = []
    for spec in specs:
        last = state.last_success.get(spec.id)
        if last is not None and now - last < spec.cadence_minutes * 60:
            continue
        url = spec.request_url(since_epoch, limit)
        result = fetch_url(url, timeout_s=timeout_s)
        row: dict = {
            "source_id": spec.id,
            "venue": spec.venue,
            "source": spec.address(),
            "url": url,
            "unreachable": not result.reached,
            "http_status": result.http_status,
            "items_returned": 0,
            "new_items": 0,
            "newest_at": None,
            "error": result.error,
        }
        if result.reached:
            state.last_success[spec.id] = now
            try:
                items = _parse_items(spec, result.body)
            except ValueError as exc:
                row["error"] = f"parse failed: {exc}"
                rows.append(row)
                continue
            row["items_returned"] = len(items)
            fresh: list[SensedItem] = []
            for item in items:
                if not _is_new(state, item):
                    continue
                if _older_than_bootstrap(item, now, bootstrap_seconds):
                    state.seen[item.canonical_url] = item.content_hash
                    continue
                fresh.append(item)
            append_items(intake_dir, fresh, started_iso)
            for item in fresh:
                state.seen[item.canonical_url] = item.content_hash
            row["new_items"] = len(fresh)
            dates = [item.published_at for item in items if item.published_at]
            row["newest_at"] = max(dates) if dates else None
        rows.append(row)

    save_state(state_path(intake_dir), state)
    report = {
        "started_at": started_iso,
        "bootstrap_seconds": bootstrap_seconds,
        "sources": rows,
        "new_items_total": sum(row["new_items"] for row in rows),
    }
    write_run_report(intake_dir, report, started_iso.replace("-", "").replace(":", ""))
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI entry: one pass over the vault source list; reach failures exit 0."""
    parser = argparse.ArgumentParser(
        prog="agents.discourse_sensing",
        description="Read-only discourse sensing producer (slice 1)",
    )
    parser.add_argument(
        "--sources",
        default=os.environ.get("DISCOURSE_SENSING_SOURCES"),
        help="path to the vault-side SOURCES.yaml",
    )
    parser.add_argument(
        "--intake",
        default=os.environ.get("DISCOURSE_SENSING_INTAKE"),
        help="intake directory for sensed records and run reports",
    )
    parser.add_argument("--timeout", type=float, default=20.0, help="per-request timeout seconds")
    parser.add_argument("--limit", type=int, default=100, help="per-request item limit")
    parser.add_argument(
        "--bootstrap-seconds",
        type=int,
        default=BOOTSTRAP_SECONDS,
        help="items older than this are marked seen without being recorded",
    )
    args = parser.parse_args(argv)
    if not args.sources or not args.intake:
        parser.error(
            "--sources and --intake are required: pass them or set "
            "DISCOURSE_SENSING_SOURCES and DISCOURSE_SENSING_INTAKE (the vault "
            "source list is 30-areas/hapax/lanebus/hieh-field/SOURCES.yaml)"
        )
    report = run_once(
        args.sources,
        args.intake,
        timeout_s=args.timeout,
        limit=args.limit,
        bootstrap_seconds=args.bootstrap_seconds,
    )
    for row in report["sources"]:
        reach = "unreachable" if row["unreachable"] else "ok"
        print(
            f"{row['source_id']}: {reach} http={row['http_status']} "
            f"items={row['items_returned']} new={row['new_items']}"
        )
    return 0
