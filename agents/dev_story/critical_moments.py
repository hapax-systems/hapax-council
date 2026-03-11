"""Critical moment detection — churn, wrong paths, cascades."""

from __future__ import annotations

import logging
import sqlite3

from agents.dev_story.models import CriticalMoment

log = logging.getLogger(__name__)


def detect_churn_moments(
    conn: sqlite3.Connection,
    max_survived_days: int = 7,
) -> list[CriticalMoment]:
    """Detect files with high churn — introduced then significantly rewritten quickly.

    Groups by file to avoid combinatorial explosion (demo.py with 50 commits
    would generate thousands of pairs otherwise). Reports the file-level churn
    pattern with the earliest introduction and count of rewrites.
    """
    cursor = conn.execute(
        """
        SELECT
            cf1.file_path,
            COUNT(DISTINCT cf2.commit_hash) AS rewrite_count,
            MIN(c1.author_date) AS first_intro,
            MAX(c2.author_date) AS last_rewrite,
            MIN(c1.hash) AS first_intro_hash,
            MAX(c2.hash) AS last_rewrite_hash,
            MIN(c1.message) AS first_msg,
            cor.message_id,
            AVG(cor.confidence) AS avg_confidence
        FROM commit_files cf1
        JOIN commits c1 ON c1.hash = cf1.commit_hash
        JOIN commit_files cf2 ON cf2.file_path = cf1.file_path AND cf2.commit_hash != cf1.commit_hash
        JOIN commits c2 ON c2.hash = cf2.commit_hash AND c2.author_date > c1.author_date
        LEFT JOIN correlations cor ON cor.commit_hash = c1.hash
        WHERE julianday(substr(c2.author_date, 1, 10)) - julianday(substr(c1.author_date, 1, 10)) <= ?
          AND c2.deletions > 0
        GROUP BY cf1.file_path
        HAVING COUNT(DISTINCT cf2.commit_hash) >= 3
        ORDER BY COUNT(DISTINCT cf2.commit_hash) DESC
        LIMIT 50
        """,
        (max_survived_days,),
    )

    moments: list[CriticalMoment] = []
    for row in cursor.fetchall():
        (
            file_path,
            rewrite_count,
            first_intro,
            last_rewrite,
            intro_hash,
            rewrite_hash,
            first_msg,
            message_id,
            avg_conf,
        ) = row

        # Severity scales with rewrite count: 3 rewrites = 0.3, 10 = 0.6, 50+ = 0.95
        severity = min(rewrite_count * 0.06, 0.95)

        moments.append(
            CriticalMoment(
                moment_type="churn",
                severity=severity,
                session_id=_session_for_message(conn, message_id) or "",
                message_id=message_id,
                commit_hash=intro_hash,
                description=(
                    f"{file_path}: {rewrite_count} rewrites between "
                    f"{first_intro[:10]} and {last_rewrite[:10]}, "
                    f"first introduced in '{first_msg}'"
                ),
                evidence=f'{{"file": "{file_path}", "rewrite_count": {rewrite_count}, '
                f'"intro": "{intro_hash}", "last_rewrite": "{rewrite_hash}"}}',
            )
        )

    return moments


def detect_wrong_path_moments(conn: sqlite3.Connection) -> list[CriticalMoment]:
    """Detect wrong-path patterns from tool call sequences.

    Since tool success/failure is not tracked in the current parser,
    detects Edit→Bash→Edit→Bash cycles on the same file — a signal of
    iterative debugging where each edit attempts to fix a problem.
    """
    cursor = conn.execute(
        """
        SELECT
            m.session_id,
            tc.tool_name,
            tc.arguments_summary,
            m.id AS message_id,
            m.timestamp
        FROM tool_calls tc
        JOIN messages m ON m.id = tc.message_id
        ORDER BY m.session_id, m.timestamp, tc.sequence_position
        """
    )

    rows = cursor.fetchall()
    if not rows:
        return []

    moments: list[CriticalMoment] = []
    current_session: str | None = None
    # Track Edit→Bash cycles per file
    cycle_file: str | None = None
    cycle_count = 0
    cycle_first_msg: str | None = None

    def _flush_cycle(session_id: str) -> CriticalMoment | None:
        nonlocal cycle_count, cycle_file, cycle_first_msg
        if cycle_count < 3 or not cycle_file:
            cycle_count = 0
            cycle_file = None
            cycle_first_msg = None
            return None
        moment = CriticalMoment(
            moment_type="wrong_path",
            severity=min(cycle_count * 0.12, 0.95),
            session_id=session_id,
            message_id=cycle_first_msg,
            description=f"Edit-test loop: {cycle_count} Edit→Bash cycles on '{cycle_file}'",
        )
        cycle_count = 0
        cycle_file = None
        cycle_first_msg = None
        return moment

    prev_was_edit = False
    prev_edit_file: str | None = None

    for row in rows:
        session_id, tool_name, args, message_id, timestamp = row

        if session_id != current_session:
            if current_session is not None:
                m = _flush_cycle(current_session)
                if m:
                    moments.append(m)
            current_session = session_id
            prev_was_edit = False
            prev_edit_file = None
            cycle_file = None
            cycle_count = 0
            cycle_first_msg = None

        if tool_name in ("Edit", "Write", "MultiEdit"):
            prev_was_edit = True
            prev_edit_file = args
        elif tool_name == "Bash" and prev_was_edit:
            # Edit→Bash transition detected
            edit_target = prev_edit_file or ""
            if cycle_file is None:
                cycle_file = edit_target
                cycle_first_msg = message_id
                cycle_count = 1
            elif edit_target == cycle_file or not edit_target:
                cycle_count += 1
            else:
                # Different file — flush old cycle, start new
                m = _flush_cycle(session_id)
                if m:
                    moments.append(m)
                cycle_file = edit_target
                cycle_first_msg = message_id
                cycle_count = 1
            prev_was_edit = False
        elif tool_name == "Bash":
            # Bash without preceding Edit — doesn't break the cycle
            pass
        elif tool_name in ("Read", "Grep", "Glob"):
            # Reading between edit cycles is normal debugging
            pass
        else:
            # Other tool breaks the cycle
            m = _flush_cycle(session_id)
            if m:
                moments.append(m)
            prev_was_edit = False

    # Flush trailing cycle
    if current_session is not None:
        m = _flush_cycle(current_session)
        if m:
            moments.append(m)

    return moments


def detect_high_token_sessions(conn: sqlite3.Connection) -> list[CriticalMoment]:
    """Detect sessions with high token spend but low commit correlation.

    These represent potentially wasteful sessions — lots of LLM work
    that didn't produce lasting code.
    """
    cursor = conn.execute(
        """
        SELECT
            s.id,
            s.total_tokens_in + s.total_tokens_out AS total_tokens,
            s.message_count,
            COUNT(DISTINCT cor.commit_hash) AS correlated_commits
        FROM sessions s
        LEFT JOIN messages m ON m.session_id = s.id
        LEFT JOIN correlations cor ON cor.message_id = m.id AND cor.confidence >= 0.85
        GROUP BY s.id
        HAVING total_tokens > 100000
        ORDER BY total_tokens DESC
        LIMIT 20
        """
    )

    moments: list[CriticalMoment] = []
    for row in cursor.fetchall():
        session_id, total_tokens, msg_count, correlated_commits = row

        tokens_per_commit = total_tokens / max(correlated_commits, 1)
        # Flag sessions where token spend is very high relative to output
        if correlated_commits == 0 or tokens_per_commit > 200000:
            severity = min(total_tokens / 1000000, 0.95)
            moments.append(
                CriticalMoment(
                    moment_type="token_waste",
                    severity=severity,
                    session_id=session_id,
                    description=(
                        f"High token spend: {total_tokens:,} tokens, "
                        f"{msg_count} messages, "
                        f"{correlated_commits} correlated commits"
                    ),
                )
            )

    return moments


def _session_for_message(conn: sqlite3.Connection, message_id: str | None) -> str | None:
    """Look up session_id for a message."""
    if not message_id:
        return None
    cursor = conn.execute("SELECT session_id FROM messages WHERE id = ?", (message_id,))
    row = cursor.fetchone()
    return row[0] if row else None
