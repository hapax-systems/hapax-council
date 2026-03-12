"""Health Connect SQLite parser — extracts daily summaries from backup ZIPs.

Parses Health Connect backup ZIPs (containing SQLite databases) into
markdown files with YAML frontmatter for the RAG pipeline.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import zipfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from shared.config import RAG_SOURCES_DIR

OUTPUT_DIR: Path = RAG_SOURCES_DIR / "health-connect"


def extract_zip(zip_path: Path | str, dest_dir: Path | str) -> Path | None:
    """Unzip a Health Connect backup, find the .db file, return its Path or None."""
    zip_path = Path(zip_path)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)

    # Find the first .db file in extracted contents
    for p in dest_dir.rglob("*.db"):
        return p
    return None


def parse_health_db(db_path: Path | str) -> list[dict]:
    """Open SQLite DB and aggregate health data per day.

    Queries heart_rate_record, steps_record, and sleep_session_record tables.
    Gracefully skips missing tables. Returns list of day dicts.
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Discover which tables exist
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing_tables = {row[0] for row in cursor.fetchall()}

    daily: dict[str, dict] = defaultdict(
        lambda: {
            "heart_rates": [],
            "steps": 0,
            "sleep_sessions": [],
        }
    )

    # Heart rate records
    if "heart_rate_record" in existing_tables:
        for row in conn.execute("SELECT time, bpm FROM heart_rate_record"):
            ts, bpm = row
            dt = datetime.fromtimestamp(ts, tz=UTC)
            date_str = dt.strftime("%Y-%m-%d")
            daily[date_str]["heart_rates"].append(bpm)

    # Steps records
    if "steps_record" in existing_tables:
        for row in conn.execute("SELECT start_time, count FROM steps_record"):
            ts, count = row
            dt = datetime.fromtimestamp(ts, tz=UTC)
            date_str = dt.strftime("%Y-%m-%d")
            daily[date_str]["steps"] += count

    # Sleep session records
    if "sleep_session_record" in existing_tables:
        for row in conn.execute("SELECT start_time, end_time FROM sleep_session_record"):
            start_ts, end_ts = row
            daily_date = datetime.fromtimestamp(end_ts, tz=UTC).strftime("%Y-%m-%d")
            daily[daily_date]["sleep_sessions"].append((start_ts, end_ts))

    conn.close()

    if not daily:
        return []

    # Aggregate into day dicts
    result: list[dict] = []
    for date_str in sorted(daily):
        d = daily[date_str]
        day_data: dict = {"date": date_str}

        hrs = d["heart_rates"]
        if hrs:
            day_data["resting_hr"] = min(hrs)
            day_data["hr_min"] = min(hrs)
            day_data["hr_max"] = max(hrs)
            day_data["hr_mean"] = round(sum(hrs) / len(hrs), 1)

        day_data["steps"] = d["steps"]

        sessions = d["sleep_sessions"]
        if sessions:
            # Use the first session for simplicity
            start_ts, end_ts = sessions[0]
            start_dt = datetime.fromtimestamp(start_ts, tz=UTC)
            end_dt = datetime.fromtimestamp(end_ts, tz=UTC)
            day_data["sleep_start"] = start_dt.strftime("%H:%M")
            day_data["sleep_end"] = end_dt.strftime("%H:%M")
            day_data["sleep_duration_min"] = round((end_ts - start_ts) / 60)

        result.append(day_data)

    return result


def format_daily_summary(day_data: dict) -> str:
    """Render markdown with YAML frontmatter for a single day's health data."""
    date = day_data["date"]
    ts = f"{date}T00:00:00+00:00"

    lines = [
        "---",
        "content_type: daily_health_summary",
        "source_service: health_connect",
        "device: pixel_watch_4",
        f"date: {date}",
        f"timestamp: {ts}",
        "modality_tags:",
        "  - health",
        "  - biometric",
        "  - wearable",
        "---",
        "",
        f"# Daily Health Summary — {date}",
        "",
    ]

    # Heart rate section
    if "resting_hr" in day_data:
        lines.append("## Heart Rate")
        lines.append("")
        lines.append(f"- **Resting HR**: {day_data['resting_hr']} bpm")
        if "hr_min" in day_data:
            lines.append(f"- **Min**: {day_data['hr_min']} bpm")
        if "hr_max" in day_data:
            lines.append(f"- **Max**: {day_data['hr_max']} bpm")
        if "hr_mean" in day_data:
            lines.append(f"- **Mean**: {day_data['hr_mean']} bpm")
        lines.append("")

    # Steps section
    if "steps" in day_data:
        lines.append("## Steps")
        lines.append("")
        lines.append(f"- **Steps**: {day_data['steps']}")
        lines.append("")

    # Sleep section
    if "sleep_start" in day_data or "sleep_duration_min" in day_data:
        lines.append("## Sleep")
        lines.append("")
        if "sleep_start" in day_data:
            lines.append(f"- **Sleep start**: {day_data['sleep_start']}")
        if "sleep_end" in day_data:
            lines.append(f"- **Sleep end**: {day_data['sleep_end']}")
        if "sleep_duration_min" in day_data:
            hours = day_data["sleep_duration_min"] // 60
            mins = day_data["sleep_duration_min"] % 60
            lines.append(f"- **Duration**: {hours}h {mins}m ({day_data['sleep_duration_min']} min)")
        lines.append("")

    return "\n".join(lines)


def _is_phone_posted(filepath: Path) -> bool:
    """Check if a health markdown file was posted by the phone (has device: pixel_10)."""
    if not filepath.exists():
        return False
    try:
        content = filepath.read_text()
        # Check frontmatter for phone device marker
        return "device: pixel_10" in content
    except OSError:
        return False


def write_rag_documents(days: list[dict], output_dir: Path | str, *, force: bool = False) -> None:
    """Write health-YYYY-MM-DD.md files, skip if content unchanged.

    Skips dates already covered by phone-posted data (device: pixel_10 in
    frontmatter) unless force=True.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for day_data in days:
        content = format_daily_summary(day_data)
        filename = f"health-{day_data['date']}.md"
        filepath = output_dir / filename

        # Skip if phone already posted this date (phone data is fresher)
        if not force and _is_phone_posted(filepath):
            continue

        content_hash = hashlib.sha256(content.encode()).hexdigest()

        if filepath.exists():
            existing_hash = hashlib.sha256(filepath.read_bytes()).hexdigest()
            if existing_hash == content_hash:
                continue

        filepath.write_text(content)


def run_parse(
    zip_path: Path | str, output_dir: Path | str | None = None, *, force: bool = False
) -> list[dict]:
    """Orchestrate: extract -> parse -> format -> write."""
    zip_path = Path(zip_path)
    out = Path(output_dir) if output_dir else OUTPUT_DIR

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db_path = extract_zip(zip_path, Path(tmp))
        if db_path is None:
            return []
        days = parse_health_db(db_path)

    write_rag_documents(days, out, force=force)
    return days


def _watch(scan_dir: Path | None = None) -> None:
    """Scan gdrive directory for Health Connect zips and process them."""
    scan_dir = scan_dir or (RAG_SOURCES_DIR / "gdrive")
    if not scan_dir.exists():
        print(f"Watch directory does not exist: {scan_dir}")
        return

    patterns = ["*Health Connect*", "*health_connect*"]
    found: list[Path] = []
    for pat in patterns:
        found.extend(scan_dir.rglob(pat))

    zips = [f for f in found if f.suffix == ".zip"]
    if not zips:
        print("No Health Connect zip files found.")
        return

    for zp in zips:
        print(f"Processing: {zp}")
        days = run_parse(zp)
        print(f"  -> {len(days)} daily summaries written")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Parse Health Connect backup ZIPs into RAG markdown"
    )
    parser.add_argument(
        "--parse",
        metavar="ZIP_PATH",
        help="Parse a single Health Connect backup zip",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Scan gdrive directory for Health Connect zips",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Override skip for phone-covered dates (backfill mode)",
    )
    args = parser.parse_args()

    if args.parse:
        days = run_parse(args.parse, force=args.force)
        print(f"Wrote {len(days)} daily summaries to {OUTPUT_DIR}")
    elif args.watch:
        _watch()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
