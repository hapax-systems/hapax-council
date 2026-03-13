"""Index orchestrator — builds the dev-story SQLite database."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

from agents.dev_story.classifier import (
    classify_env_topology,
    classify_interaction_mode,
    classify_session_scale,
    classify_work_type,
)
from agents.dev_story.correlator import correlate
from agents.dev_story.critical_moments import (
    detect_churn_moments,
    detect_high_token_sessions,
    detect_wrong_path_moments,
)
from agents.dev_story.git_extractor import (
    discover_bundles,
    extract_commits,
    extract_commits_from_bundle,
)
from agents.dev_story.models import CommitFile, FileChange
from agents.dev_story.parser import (
    discover_archived_sessions,
    extract_project_path,
    parse_session,
)
from agents.dev_story.phase_detector import detect_phase_sequence

log = logging.getLogger(__name__)

# Default paths for external history sources (configurable via env vars)
import os

BUNDLES_DIR = Path(os.environ.get("DEV_STORY_BUNDLES_DIR", os.path.expanduser("~/backups")))
CONVERSATIONS_ARCHIVE_DIR = Path(
    os.environ.get(
        "DEV_STORY_CONVERSATIONS_ARCHIVE_DIR",
        os.path.expanduser("~/backups/claude-conversations"),
    )
)


@dataclass
class SessionFile:
    """A discovered session JSONL file."""

    path: Path
    session_id: str
    project_path: str
    project_encoded: str


def discover_sessions(projects_dir: Path) -> list[SessionFile]:
    """Scan Claude Code projects directory for session JSONL files."""
    results: list[SessionFile] = []
    if not projects_dir.is_dir():
        log.warning("Projects directory not found: %s", projects_dir)
        return results

    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        project_encoded = project_dir.name
        project_path = extract_project_path(project_encoded)
        for jsonl_file in sorted(project_dir.glob("*.jsonl")):
            session_id = jsonl_file.stem
            results.append(
                SessionFile(
                    path=jsonl_file,
                    session_id=session_id,
                    project_path=project_path,
                    project_encoded=project_encoded,
                )
            )
    return results


def index_session(conn: sqlite3.Connection, sf: SessionFile) -> None:
    """Parse and insert a single session into the database."""
    parsed = parse_session(sf.path, sf.project_path)
    s = parsed.session

    conn.execute(
        """INSERT OR REPLACE INTO sessions
           (id, project_path, project_name, started_at, ended_at, git_branch,
            message_count, total_tokens_in, total_tokens_out, total_cost_estimate,
            model_primary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            s.id,
            s.project_path,
            s.project_name,
            s.started_at,
            s.ended_at,
            s.git_branch,
            s.message_count,
            s.total_tokens_in,
            s.total_tokens_out,
            s.total_cost_estimate,
            s.model_primary,
        ),
    )

    # Clear existing data for this session (for re-indexing)
    # Order matters: delete children before parents to satisfy FK constraints
    # correlations and critical_moments reference messages, so delete those first
    conn.execute(
        "DELETE FROM correlations WHERE message_id IN (SELECT id FROM messages WHERE session_id = ?)",
        (s.id,),
    )
    conn.execute(
        "DELETE FROM critical_moments WHERE session_id = ?",
        (s.id,),
    )
    conn.execute(
        "DELETE FROM session_metrics WHERE session_id = ?",
        (s.id,),
    )
    conn.execute(
        "DELETE FROM session_tags WHERE session_id = ?",
        (s.id,),
    )
    conn.execute(
        "DELETE FROM file_changes WHERE message_id IN (SELECT id FROM messages WHERE session_id = ?)",
        (s.id,),
    )
    conn.execute(
        "DELETE FROM tool_calls WHERE message_id IN (SELECT id FROM messages WHERE session_id = ?)",
        (s.id,),
    )
    conn.execute("DELETE FROM messages WHERE session_id = ?", (s.id,))

    for msg in parsed.messages:
        conn.execute(
            """INSERT OR REPLACE INTO messages
               (id, session_id, parent_id, role, timestamp, content_text, model,
                tokens_in, tokens_out)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                msg.id,
                msg.session_id,
                msg.parent_id,
                msg.role,
                msg.timestamp,
                msg.content_text,
                msg.model,
                msg.tokens_in,
                msg.tokens_out,
            ),
        )

    for tc in parsed.tool_calls:
        conn.execute(
            """INSERT INTO tool_calls
               (message_id, tool_name, arguments_summary, duration_ms, success,
                sequence_position)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                tc.message_id,
                tc.tool_name,
                tc.arguments_summary,
                tc.duration_ms,
                1 if tc.success else 0,
                tc.sequence_position,
            ),
        )

    # Only insert file_changes whose message_id exists in our messages
    known_msg_ids = {msg.id for msg in parsed.messages}
    for fc in parsed.file_changes:
        if fc.message_id not in known_msg_ids:
            continue
        conn.execute(
            """INSERT INTO file_changes
               (message_id, file_path, version, change_type, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (fc.message_id, fc.file_path, fc.version, fc.change_type, fc.timestamp),
        )

    conn.commit()


def _insert_commits(
    conn: sqlite3.Connection,
    commits: list,
    commit_files: list,
    source_label: str,
) -> None:
    """Insert commits and commit_files into the database."""
    for c in commits:
        conn.execute(
            """INSERT OR IGNORE INTO commits
               (hash, author_date, message, branch, files_changed, insertions, deletions, source_repo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                c.hash,
                c.author_date,
                c.message,
                c.branch,
                c.files_changed,
                c.insertions,
                c.deletions,
                c.source_repo,
            ),
        )

    for cf in commit_files:
        conn.execute(
            """INSERT OR IGNORE INTO commit_files
               (commit_hash, file_path, operation, source_repo)
               VALUES (?, ?, ?, ?)""",
            (cf.commit_hash, cf.file_path, cf.operation, cf.source_repo),
        )

    conn.commit()
    log.info(
        "Indexed %d commits, %d file records from %s",
        len(commits),
        len(commit_files),
        source_label,
    )


def index_git(conn: sqlite3.Connection, repo_path: str, since: str | None = None) -> None:
    """Extract and insert git history for a repository."""
    commits, commit_files = extract_commits(repo_path, since=since)
    _insert_commits(conn, commits, commit_files, repo_path)


def index_bundles(conn: sqlite3.Connection, bundles_dir: Path) -> int:
    """Discover and index git bundles from a directory.

    Returns:
        Total number of commits indexed from bundles.
    """
    bundles = discover_bundles(bundles_dir)
    if not bundles:
        log.info("No bundles found in %s", bundles_dir)
        return 0

    total = 0
    for bundle_path, repo_name in bundles:
        try:
            commits, commit_files = extract_commits_from_bundle(bundle_path, repo_name)
            _insert_commits(conn, commits, commit_files, f"bundle:{repo_name}")
            total += len(commits)
        except Exception:
            log.exception("Failed to index bundle %s", bundle_path)

    log.info("Indexed %d total commits from %d bundles", total, len(bundles))
    return total


def run_correlations(conn: sqlite3.Connection) -> int:
    """Compute correlations between file changes and commits."""
    # Clear existing correlations
    conn.execute("DELETE FROM correlations")

    # Load file changes
    cursor = conn.execute(
        "SELECT message_id, file_path, version, change_type, timestamp FROM file_changes"
    )
    file_changes = [
        FileChange(message_id=r[0], file_path=r[1], version=r[2], change_type=r[3], timestamp=r[4])
        for r in cursor.fetchall()
    ]

    # Load commit files
    cursor = conn.execute("SELECT commit_hash, file_path, operation FROM commit_files")
    commit_files_list = [
        CommitFile(commit_hash=r[0], file_path=r[1], operation=r[2]) for r in cursor.fetchall()
    ]

    # Load commit dates
    cursor = conn.execute("SELECT hash, author_date FROM commits")
    commit_dates = {r[0]: r[1] for r in cursor.fetchall()}

    # Run correlation
    correlations = correlate(file_changes, commit_files_list, commit_dates)

    for cor in correlations:
        conn.execute(
            "INSERT INTO correlations (message_id, commit_hash, confidence, method) VALUES (?, ?, ?, ?)",
            (cor.message_id, cor.commit_hash, cor.confidence, cor.method),
        )

    conn.commit()
    log.info("Created %d correlations", len(correlations))
    return len(correlations)


def _compute_session_metrics(conn: sqlite3.Connection) -> int:
    """Compute session_metrics from tool_calls for each session."""
    conn.execute("DELETE FROM session_metrics")

    cursor = conn.execute("SELECT id FROM sessions")
    session_ids = [r[0] for r in cursor.fetchall()]
    count = 0

    for session_id in session_ids:
        tc_cursor = conn.execute(
            """SELECT tc.tool_name, tc.arguments_summary
               FROM tool_calls tc
               JOIN messages m ON m.id = tc.message_id
               WHERE m.session_id = ?
               ORDER BY m.timestamp, tc.sequence_position""",
            (session_id,),
        )
        tool_rows = tc_cursor.fetchall()
        if not tool_rows:
            continue

        tool_names = [r[0] for r in tool_rows]
        tool_args = [f"{r[0]}:{r[1] or ''}" for r in tool_rows]

        unique_tools = set(tool_names)
        edit_count = sum(1 for t in tool_names if t in ("Edit", "Write", "MultiEdit"))
        bash_count = sum(1 for t in tool_names if t == "Bash")
        agent_count = sum(1 for t in tool_names if t == "Agent")

        # User steering ratio: short user messages / total user messages
        msg_cursor = conn.execute(
            "SELECT content_text FROM messages WHERE session_id = ? AND role = 'user'",
            (session_id,),
        )
        user_msgs = [r[0] for r in msg_cursor.fetchall()]
        if user_msgs:
            short = sum(1 for m in user_msgs if len(m) < 20)
            steering_ratio = short / len(user_msgs)
        else:
            steering_ratio = 0.0

        phase_seq = detect_phase_sequence(tool_args)

        conn.execute(
            """INSERT INTO session_metrics
               (session_id, tool_call_count, tool_diversity, edit_count, bash_count,
                agent_dispatch_count, user_steering_ratio, phase_sequence)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                len(tool_names),
                len(unique_tools),
                edit_count,
                bash_count,
                agent_count,
                steering_ratio,
                phase_seq,
            ),
        )
        count += 1

    conn.commit()
    log.info("Computed metrics for %d sessions", count)
    return count


def _compute_session_tags(conn: sqlite3.Connection) -> int:
    """Classify sessions across dimensions and insert tags."""
    conn.execute("DELETE FROM session_tags")

    cursor = conn.execute("SELECT id FROM sessions")
    session_ids = [r[0] for r in cursor.fetchall()]
    count = 0

    for session_id in session_ids:
        # Work type: from correlated commit messages
        commit_cursor = conn.execute(
            """SELECT DISTINCT c.message FROM correlations cor
               JOIN messages m ON m.id = cor.message_id
               JOIN commits c ON c.hash = cor.commit_hash
               WHERE m.session_id = ? AND cor.confidence >= 0.7""",
            (session_id,),
        )
        commit_msgs = [r[0] for r in commit_cursor.fetchall()]

        # Interaction mode: from user message lengths
        msg_cursor = conn.execute(
            "SELECT content_text FROM messages WHERE session_id = ? AND role = 'user'",
            (session_id,),
        )
        user_msg_lengths = [len(r[0]) for r in msg_cursor.fetchall()]

        # File paths: from file_changes and correlated commit_files
        file_cursor = conn.execute(
            """SELECT DISTINCT file_path FROM (
                   SELECT fc.file_path FROM file_changes fc
                   JOIN messages m ON m.id = fc.message_id WHERE m.session_id = ?
                   UNION
                   SELECT cf.file_path FROM correlations cor
                   JOIN messages m ON m.id = cor.message_id
                   JOIN commit_files cf ON cf.commit_hash = cor.commit_hash
                   WHERE m.session_id = ? AND cor.confidence >= 0.7
               )""",
            (session_id, session_id),
        )
        file_paths = [r[0] for r in file_cursor.fetchall()]

        tags = [
            classify_work_type(commit_msgs),
            classify_interaction_mode(user_msg_lengths),
            classify_env_topology(file_paths),
            classify_session_scale(file_paths),
        ]

        for tag in tags:
            if tag.confidence > 0.0:
                conn.execute(
                    "INSERT INTO session_tags (session_id, dimension, value, confidence) VALUES (?, ?, ?, ?)",
                    (session_id, tag.dimension, tag.value, tag.confidence),
                )
                count += 1

    conn.commit()
    log.info("Created %d session tags", count)
    return count


def _compute_critical_moments(conn: sqlite3.Connection) -> int:
    """Detect and store critical moments (churn + wrong-path)."""
    conn.execute("DELETE FROM critical_moments")

    churn = detect_churn_moments(conn)
    wrong_path = detect_wrong_path_moments(conn)
    token_waste = detect_high_token_sessions(conn)

    # Get valid session IDs and message IDs for FK safety
    valid_sessions = {r[0] for r in conn.execute("SELECT id FROM sessions").fetchall()}
    valid_messages = {r[0] for r in conn.execute("SELECT id FROM messages").fetchall()}

    all_moments = churn + wrong_path + token_waste
    inserted = 0
    for m in all_moments:
        # Nullify references that would violate FK constraints
        sid = m.session_id if m.session_id in valid_sessions else None
        mid = m.message_id if m.message_id in valid_messages else None
        conn.execute(
            """INSERT INTO critical_moments
               (moment_type, severity, session_id, message_id, commit_hash, description, evidence)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (m.moment_type, m.severity, sid, mid, m.commit_hash, m.description, m.evidence),
        )
        inserted += 1

    conn.commit()
    log.info(
        "Detected %d critical moments (%d churn, %d wrong-path, %d token-waste), inserted %d",
        len(all_moments),
        len(churn),
        len(wrong_path),
        len(token_waste),
        inserted,
    )
    return inserted


def _compute_hotspots(conn: sqlite3.Connection) -> int:
    """Compute file hotspots from commit_files aggregation.

    Metrics per file (only files with change_frequency >= 2):
    - change_frequency: total commits touching the file
    - session_count: distinct sessions correlated to those commits
    - churn_rate: ratio of (adds + deletes) to total operations
    """
    conn.execute("DELETE FROM hotspots")

    cursor = conn.execute(
        """SELECT
               cf.file_path,
               COUNT(DISTINCT cf.commit_hash) AS change_frequency,
               COUNT(DISTINCT s.id) AS session_count,
               CAST(SUM(CASE WHEN cf.operation IN ('A', 'D') THEN 1 ELSE 0 END) AS REAL)
                   / COUNT(*) AS churn_rate
           FROM commit_files cf
           LEFT JOIN correlations cor ON cor.commit_hash = cf.commit_hash
           LEFT JOIN messages m ON m.id = cor.message_id
           LEFT JOIN sessions s ON s.id = m.session_id
           GROUP BY cf.file_path
           HAVING change_frequency >= 2
        """
    )
    rows = cursor.fetchall()

    for row in rows:
        conn.execute(
            "INSERT INTO hotspots (file_path, change_frequency, session_count, churn_rate) VALUES (?, ?, ?, ?)",
            (row[0], row[1], row[2], row[3]),
        )

    conn.commit()
    log.info("Computed hotspots for %d files", len(rows))
    return len(rows)


def _compute_code_survival(conn: sqlite3.Connection) -> int:
    """Compute code survival records for files in commit_files.

    For each file, find:
    - The first commit that introduced it (operation='A', or earliest appearance)
    - If/when it was deleted (operation='D') or last modified
    - survived_days: days between introduction and deletion/last modification (or now)
    - introduced_by_session: session correlated to the introducing commit
    - replacement_commit: the commit that deleted it, or NULL if still alive
    """
    conn.execute("DELETE FROM code_survival")

    # Get all files with their commits ordered by date
    cursor = conn.execute(
        """SELECT cf.file_path, cf.commit_hash, cf.operation, c.author_date
           FROM commit_files cf
           JOIN commits c ON c.hash = cf.commit_hash
           ORDER BY cf.file_path, c.author_date ASC"""
    )
    rows = cursor.fetchall()

    # Group by file_path
    from collections import defaultdict

    file_commits: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for file_path, commit_hash, operation, author_date in rows:
        file_commits[file_path].append((commit_hash, operation, author_date))

    from datetime import datetime

    now = datetime.now()  # naive, matching parsed dates
    count = 0

    for file_path, commits in file_commits.items():
        # Find introduction commits (operation='A', or first appearance if no 'A')
        add_commits = [(h, op, d) for h, op, d in commits if op == "A"]
        if not add_commits:
            # No explicit add — treat first appearance as introduction
            add_commits = [commits[0]]

        # Find deletion commit if any
        delete_commits = [(h, op, d) for h, op, d in commits if op == "D"]
        replacement_hash = delete_commits[-1][0] if delete_commits else None
        end_date_str = delete_commits[-1][2] if delete_commits else None

        for intro_hash, _intro_op, intro_date_str in add_commits:
            # Parse dates — format is 'YYYY-MM-DD HH:MM:SS ±HHMM'
            try:
                intro_date = datetime.strptime(intro_date_str[:19], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue

            if end_date_str:
                try:
                    end_date = datetime.strptime(end_date_str[:19], "%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    end_date = now
            else:
                end_date = now

            survived_days = max((end_date - intro_date).total_seconds() / 86400.0, 0.0)

            # Find session correlated to the introducing commit
            sess_cursor = conn.execute(
                """SELECT DISTINCT m.session_id
                   FROM correlations cor
                   JOIN messages m ON m.id = cor.message_id
                   WHERE cor.commit_hash = ?
                   LIMIT 1""",
                (intro_hash,),
            )
            sess_row = sess_cursor.fetchone()
            intro_session = sess_row[0] if sess_row else None

            # Don't set replacement_commit to the same as introduced_by_commit
            repl = replacement_hash if replacement_hash != intro_hash else None

            conn.execute(
                """INSERT OR IGNORE INTO code_survival
                   (file_path, introduced_by_commit, introduced_by_session, survived_days, replacement_commit)
                   VALUES (?, ?, ?, ?, ?)""",
                (file_path, intro_hash, intro_session, survived_days, repl),
            )
            count += 1

    conn.commit()
    log.info("Computed code survival for %d file-commit pairs", count)
    return count


def _discover_archived_session_files(archive_dir: Path) -> list[SessionFile]:
    """Convert archived conversation JSONL files into SessionFile entries."""
    archived_paths = discover_archived_sessions(archive_dir)
    results: list[SessionFile] = []
    for jsonl_path in archived_paths:
        # Archived conversations live in dirs like 'ai-agents-conversations/'
        # The parent dir name encodes the source project
        parent_name = jsonl_path.parent.name  # e.g. 'ai-agents-conversations'
        # Strip '-conversations' suffix to get project name
        project_name = parent_name
        if project_name.endswith("-conversations"):
            project_name = project_name[: -len("-conversations")]
        # Use the parent dir name as the encoded project path
        # (these are archived, so the real project path may not exist)
        results.append(
            SessionFile(
                path=jsonl_path,
                session_id=jsonl_path.stem,
                project_path=f"(archived)/{project_name}",
                project_encoded=parent_name,
            )
        )
    return results


def full_index(db_path: str, claude_projects_dir: Path) -> dict:
    """Run the full indexing pipeline.

    Returns:
        Dict with stats: sessions_indexed, commits_indexed, correlations_created.
    """
    from agents.dev_story.schema import open_db

    conn = open_db(db_path)
    stats = {"sessions_indexed": 0, "commits_indexed": 0, "correlations_created": 0}

    # 1. Discover and index sessions (current + archived)
    session_files = discover_sessions(claude_projects_dir)
    log.info("Discovered %d current session files", len(session_files))

    # Also discover archived conversation sessions
    archived_session_files = _discover_archived_session_files(CONVERSATIONS_ARCHIVE_DIR)
    if archived_session_files:
        log.info("Discovered %d archived session files", len(archived_session_files))
        session_files.extend(archived_session_files)

    # Track unique project paths for git extraction
    project_paths: set[str] = set()

    for sf in session_files:
        try:
            index_session(conn, sf)
            stats["sessions_indexed"] += 1
            project_paths.add(sf.project_path)
        except Exception:
            log.exception("Failed to index session %s", sf.session_id)

    # 2. Index git history for each project (current repos only)
    for project_path in sorted(project_paths):
        if Path(project_path).is_dir() and (Path(project_path) / ".git").exists():
            try:
                index_git(conn, project_path)
                cursor = conn.execute("SELECT COUNT(*) FROM commits WHERE source_repo IS NULL")
                stats["commits_indexed"] = cursor.fetchone()[0]
            except Exception:
                log.exception("Failed to index git for %s", project_path)

    # 3. Index git bundles (archived repo histories)
    if BUNDLES_DIR.is_dir():
        stats["bundle_commits_indexed"] = index_bundles(conn, BUNDLES_DIR)
    else:
        stats["bundle_commits_indexed"] = 0

    # Update total commit count
    cursor = conn.execute("SELECT COUNT(*) FROM commits")
    stats["commits_indexed"] = cursor.fetchone()[0]

    # 4. Run correlations
    stats["correlations_created"] = run_correlations(conn)

    # 5. Compute session metrics (phase detection + tool aggregation)
    stats["sessions_with_metrics"] = _compute_session_metrics(conn)

    # 6. Compute session tags (classification across dimensions)
    stats["sessions_with_tags"] = _compute_session_tags(conn)

    # 7. Detect critical moments (churn + wrong-path patterns)
    stats["critical_moments"] = _compute_critical_moments(conn)

    # 8. Compute file hotspots (change frequency, session count, churn rate)
    stats["hotspots"] = _compute_hotspots(conn)

    # 9. Compute code survival (file lifespan tracking)
    stats["code_survival"] = _compute_code_survival(conn)

    # Store index timestamp
    from datetime import datetime

    conn.execute(
        "INSERT OR REPLACE INTO index_state (key, value) VALUES ('last_indexed', ?)",
        (datetime.now(UTC).isoformat(),),
    )
    conn.commit()
    conn.close()

    return stats
