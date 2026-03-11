"""CLI entry point for the dev-story agent."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from shared.config import PROFILES_DIR, CLAUDE_CONFIG_DIR

DB_PATH = str(PROFILES_DIR / "dev-story.db")
CLAUDE_PROJECTS_DIR = CLAUDE_CONFIG_DIR / "projects"


async def cmd_index(incremental: bool = False) -> None:
    """Run the indexing pipeline."""
    from agents.dev_story.indexer import full_index

    print(f"Indexing sessions from {CLAUDE_PROJECTS_DIR}")
    print(f"Database: {DB_PATH}")
    stats = full_index(DB_PATH, CLAUDE_PROJECTS_DIR)
    print(f"\nIndex complete:")
    print(f"  Sessions: {stats['sessions_indexed']}")
    print(f"  Commits:  {stats['commits_indexed']}")
    print(f"  Correlations: {stats['correlations_created']}")


async def cmd_stats() -> None:
    """Show index statistics."""
    from agents.dev_story.schema import open_db

    conn = open_db(DB_PATH)
    tables = ["sessions", "messages", "tool_calls", "file_changes",
              "commits", "commit_files", "correlations", "session_metrics",
              "session_tags", "critical_moments", "hotspots"]
    print("Dev Story Index Statistics\n")
    for table in tables:
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        if count > 0:
            print(f"  {table:20s} {count:>8,}")

    cursor = conn.execute("SELECT value FROM index_state WHERE key='last_indexed'")
    row = cursor.fetchone()
    if row:
        print(f"\n  Last indexed: {row[0]}")
    conn.close()


async def cmd_query(prompt: str) -> None:
    """Run a single query."""
    from agents.dev_story.query import create_agent, QueryDeps

    agent = create_agent()
    result = await agent.run(prompt, deps=QueryDeps(db_path=DB_PATH))
    print(result.output)


async def cmd_interactive() -> None:
    """Interactive query REPL."""
    from agents.dev_story.query import create_agent, QueryDeps

    agent = create_agent()
    deps = QueryDeps(db_path=DB_PATH)
    print("Dev Story — Interactive Mode")
    print("Type your questions. Ctrl+D to exit.\n")

    while True:
        try:
            prompt = input("? ")
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not prompt.strip():
            continue
        result = await agent.run(prompt, deps=deps)
        print(f"\n{result.output}\n")


async def cmd_hotspots() -> None:
    """Show top hotspot files."""
    from agents.dev_story.schema import open_db

    conn = open_db(DB_PATH)
    cursor = conn.execute(
        "SELECT file_path, change_frequency, session_count, churn_rate FROM hotspots ORDER BY change_frequency DESC LIMIT 20"
    )
    rows = cursor.fetchall()
    if not rows:
        print("No hotspot data. Run --index first.")
        return
    print(f"{'File':<50} {'Changes':>8} {'Sessions':>9} {'Churn':>6}")
    print("-" * 75)
    for path, freq, sess, churn in rows:
        print(f"{path:<50} {freq:>8} {sess:>9} {churn:>6.2f}")
    conn.close()


async def cmd_correlations() -> None:
    """Show correlation quality stats."""
    from agents.dev_story.schema import open_db

    conn = open_db(DB_PATH)
    cursor = conn.execute(
        """SELECT method, COUNT(*), AVG(confidence), MIN(confidence), MAX(confidence)
           FROM correlations GROUP BY method ORDER BY COUNT(*) DESC"""
    )
    rows = cursor.fetchall()
    if not rows:
        print("No correlations. Run --index first.")
        return
    print(f"{'Method':<25} {'Count':>6} {'Avg Conf':>9} {'Min':>6} {'Max':>6}")
    print("-" * 55)
    for method, count, avg, mn, mx in rows:
        print(f"{method:<25} {count:>6} {avg:>9.3f} {mn:>6.3f} {mx:>6.3f}")
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dev Story — development archaeology agent",
        prog="python -m agents.dev_story",
    )
    parser.add_argument("query", nargs="?", help="Natural language query")
    parser.add_argument("--index", action="store_true", help="Run the indexing pipeline")
    parser.add_argument("--incremental", action="store_true", help="Only index new/changed data")
    parser.add_argument("--interactive", action="store_true", help="Interactive query REPL")
    parser.add_argument("--stats", action="store_true", help="Show index statistics")
    parser.add_argument("--hotspots", action="store_true", help="Show top hotspot files")
    parser.add_argument("--correlations", action="store_true", help="Show correlation quality")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if args.index:
        asyncio.run(cmd_index(incremental=args.incremental))
    elif args.stats:
        asyncio.run(cmd_stats())
    elif args.hotspots:
        asyncio.run(cmd_hotspots())
    elif args.correlations:
        asyncio.run(cmd_correlations())
    elif args.interactive:
        asyncio.run(cmd_interactive())
    elif args.query:
        asyncio.run(cmd_query(args.query))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
