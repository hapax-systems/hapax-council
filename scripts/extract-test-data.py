#!/usr/bin/env python3
"""Extract curated test data slices from live profiles.

Run: uv run python scripts/extract-test-data.py
Writes to: test-data/
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "profiles"
OUT = ROOT / "test-data"


def _tail_jsonl(path: Path, n: int) -> list[dict]:
    """Read the last N entries from a JSONL file."""
    if not path.is_file():
        print(f"  SKIP (not found): {path.name}")
        return []
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                entries.append(obj)
        except json.JSONDecodeError:
            continue
    # If line-by-line didn't work, try as single JSON
    if not entries:
        try:
            text = path.read_text().strip()
            parsed = json.loads(text)
            if isinstance(parsed, list):
                entries = [e for e in parsed if isinstance(e, dict)]
            elif isinstance(parsed, dict):
                entries = [parsed]
        except json.JSONDecodeError:
            pass
    # Fallback: concatenated pretty-printed JSON
    if not entries:
        try:
            text = path.read_text().strip()
            wrapped = "[" + text.replace("}\n{", "},\n{") + "]"
            parsed = json.loads(wrapped)
            entries = [e for e in parsed if isinstance(e, dict)]
        except json.JSONDecodeError:
            pass
    result = entries[-n:]
    print(f"  {path.name}: {len(result)}/{len(entries)} entries")
    return result


def _copy_json(src: Path, dst: Path) -> None:
    """Copy a JSON file if it exists."""
    if src.is_file():
        shutil.copy2(src, dst)
        print(f"  {src.name}: copied")
    else:
        print(f"  SKIP (not found): {src.name}")


def extract_profiles_populated():
    """Extract curated profile data slices."""
    dst = OUT / "profiles-populated"
    dst.mkdir(parents=True, exist_ok=True)

    # JSONL files — take last N entries
    for name, n in [
        ("health-history.jsonl", 20),
        ("drift-history.jsonl", 10),
        ("digest-history.jsonl", 10),
        ("knowledge-maint-history.jsonl", 5),
    ]:
        entries = _tail_jsonl(PROFILES / name, n)
        if entries:
            (dst / name).write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    # JSON files — copy as-is
    for name in [
        "drift-report.json",
        "infra-snapshot.json",
        "manifest.json",
        "briefing.json",
        "digest.json",
        "scout-report.json",
        "operator.json",
    ]:
        _copy_json(PROFILES / name, dst / name)


def extract_dev_story_populated():
    """Create a small dev-story DB from the real one."""
    src = PROFILES / "dev-story.db"
    dst = OUT / "dev-story-populated.db"

    if not src.is_file():
        print("  SKIP: dev-story.db not found")
        return

    shutil.copy2(src, dst)
    conn = sqlite3.connect(str(dst))

    # Disable FK for pruning
    conn.execute("PRAGMA foreign_keys=OFF")

    # Keep most recent 50 commits
    conn.execute("""
        DELETE FROM commit_files WHERE commit_hash NOT IN (
            SELECT hash FROM commits ORDER BY author_date DESC LIMIT 50
        )
    """)
    conn.execute("""
        DELETE FROM correlations WHERE commit_hash NOT IN (
            SELECT hash FROM commits ORDER BY author_date DESC LIMIT 50
        )
    """)
    conn.execute("""
        DELETE FROM code_survival WHERE introduced_by_commit NOT IN (
            SELECT hash FROM commits ORDER BY author_date DESC LIMIT 50
        )
    """)
    conn.execute("""
        DELETE FROM critical_moments WHERE commit_hash IS NOT NULL AND commit_hash NOT IN (
            SELECT hash FROM commits ORDER BY author_date DESC LIMIT 50
        )
    """)
    conn.execute("""
        DELETE FROM commits WHERE hash NOT IN (
            SELECT hash FROM commits ORDER BY author_date DESC LIMIT 50
        )
    """)

    # Keep most recent 10 sessions
    keep_sessions = """SELECT id FROM sessions ORDER BY started_at DESC LIMIT 10"""
    conn.execute(f"""
        DELETE FROM session_metrics WHERE session_id NOT IN ({keep_sessions})
    """)
    conn.execute(f"""
        DELETE FROM session_tags WHERE session_id NOT IN ({keep_sessions})
    """)
    conn.execute(f"""
        DELETE FROM critical_moments WHERE session_id IS NOT NULL AND session_id NOT IN ({keep_sessions})
    """)
    # Delete correlations referencing messages from deleted sessions
    conn.execute(f"""
        DELETE FROM correlations WHERE message_id IN (
            SELECT id FROM messages WHERE session_id NOT IN ({keep_sessions})
        )
    """)
    conn.execute(f"""
        DELETE FROM file_changes WHERE message_id IN (
            SELECT id FROM messages WHERE session_id NOT IN ({keep_sessions})
        )
    """)
    conn.execute(f"""
        DELETE FROM tool_calls WHERE message_id IN (
            SELECT id FROM messages WHERE session_id NOT IN ({keep_sessions})
        )
    """)
    conn.execute(f"""
        DELETE FROM messages WHERE session_id NOT IN ({keep_sessions})
    """)
    conn.execute(f"""
        DELETE FROM sessions WHERE id NOT IN ({keep_sessions})
    """)

    # Rebuild hotspots from remaining data
    conn.execute("DELETE FROM hotspots")

    conn.commit()
    conn.close()

    # VACUUM must run outside any transaction (reconnect)
    conn2 = sqlite3.connect(str(dst))
    conn2.execute("VACUUM")
    conn2.close()

    size_mb = dst.stat().st_size / (1024 * 1024)
    print(f"  dev-story-populated.db: {size_mb:.1f}MB")


def extract_dev_story_empty():
    """Create an empty dev-story DB with schema only."""
    dst = OUT / "dev-story-empty.db"
    conn = sqlite3.connect(str(dst))

    # Import and run the schema DDL
    from agents.dev_story.schema import create_tables

    create_tables(conn)
    conn.close()
    print("  dev-story-empty.db: schema only")


def create_profiles_empty():
    """Create the empty profiles directory."""
    dst = OUT / "profiles-empty"
    dst.mkdir(parents=True, exist_ok=True)
    (dst / ".gitkeep").touch()
    print("  profiles-empty/: created with .gitkeep")


def validate_schema():
    """Validate schema compatibility between live and test DBs."""
    live = PROFILES / "dev-story.db"
    test = OUT / "dev-story-populated.db"

    if not live.is_file() or not test.is_file():
        print("  SKIP schema validation (missing DB)")
        return

    live_conn = sqlite3.connect(str(live))
    test_conn = sqlite3.connect(str(test))

    live_tables = {
        row[0]
        for row in live_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    test_tables = {
        row[0]
        for row in test_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }

    if live_tables != test_tables:
        print(
            f"  WARNING: Table mismatch! Live-only: {live_tables - test_tables}, Test-only: {test_tables - live_tables}"
        )

    for table in live_tables & test_tables:
        live_cols = {row[1] for row in live_conn.execute(f"PRAGMA table_info({table})").fetchall()}
        test_cols = {row[1] for row in test_conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if live_cols != test_cols:
            print(
                f"  WARNING: Column mismatch in {table}! Live-only: {live_cols - test_cols}, Test-only: {test_cols - live_cols}"
            )

    live_conn.close()
    test_conn.close()
    print("  Schema validation complete")


if __name__ == "__main__":
    print("Extracting test data from live profiles...\n")

    print("[1/5] Profiles (populated)")
    extract_profiles_populated()

    print("\n[2/5] Dev-story DB (populated)")
    extract_dev_story_populated()

    print("\n[3/5] Dev-story DB (empty)")
    extract_dev_story_empty()

    print("\n[4/5] Profiles (empty)")
    create_profiles_empty()

    print("\n[5/5] Schema validation")
    validate_schema()

    print(f"\nDone! Test data written to {OUT}/")
