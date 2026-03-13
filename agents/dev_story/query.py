"""Pydantic-ai query agent for the dev-story database."""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass

from pydantic_ai import Agent

from shared.config import get_model

log = logging.getLogger(__name__)

_READ_ONLY_PREFIXES = ("select", "with", "explain", "pragma")
_COMMIT_HASH_RE = re.compile(r"^[0-9a-f]{4,40}$")


def build_system_prompt() -> str:
    """Build the system prompt describing the schema and query patterns."""
    return """You are a development archaeology analyst. You write as an analytical historian:
precise, evidence-driven, neutral. No superlatives, no marketing language, no editorializing.
Let evidence speak for itself. When the evidence is thin, say so.

## Schema

### Core Tables
- sessions(id, project_path, project_name, started_at, ended_at, git_branch, message_count, total_tokens_in, total_tokens_out, total_cost_estimate, model_primary)
  - started_at/ended_at: ISO 8601 timestamps (e.g., '2026-03-01T10:00:00Z')
- messages(id, session_id, parent_id, role, timestamp, content_text, model, tokens_in, tokens_out)
- tool_calls(id, message_id, tool_name, arguments_summary, duration_ms, success, sequence_position)
- file_changes(id, message_id, file_path, version, change_type, timestamp)
- commits(hash, author_date, message, branch, files_changed, insertions, deletions)
  - author_date format: 'YYYY-MM-DD HH:MM:SS ±HHMM' (e.g., '2026-03-10 16:33:22 -0500'). SQLite DATE() returns NULL for this format. Use substr(author_date, 1, 10) for date grouping.
- commit_files(commit_hash, file_path, operation)
- correlations(id, message_id, commit_hash, confidence, method)

### Key Join Patterns
- **Arc → Sessions** (for per-arc metrics): commits WHERE message LIKE 'feat:%topic%' → correlations ON commit_hash → messages ON message_id → sessions ON session_id → session_tags/session_metrics ON session_id
- **Date grouping**: Always use substr(author_date, 1, 10) for commits, substr(started_at, 1, 10) for sessions

### Derived Tables
- session_metrics(session_id, tool_call_count, tool_diversity, edit_count, bash_count, agent_dispatch_count, avg_response_time_ms, user_steering_ratio, phase_sequence)
- session_tags(session_id, dimension, value, confidence)
- critical_moments(id, moment_type, severity, session_id, message_id, commit_hash, description, evidence)
- hotspots(file_path, change_frequency, session_count, churn_rate)
- code_survival(file_path, introduced_by_commit, introduced_by_session, survived_days, replacement_commit)

## How to Answer

### Before answering any question (internal research — do not narrate these steps in your output)
1. Query session distribution across projects (SELECT project_name, COUNT(*) FROM sessions GROUP BY project_name).
2. Query correlation confidence distribution. Distinguish findings backed by high-confidence correlations (>= 0.85, file_and_timestamp) from low-confidence ones (< 0.7, file_match only).

### Story questions
Follow this sequence:
1. **Enumerate features first**: Query all feat: commits (GROUP BY scope or topic keyword). List all major feature areas with commit counts. Weight narrative coverage proportionally — features with more commits deserve more space.
2. **Confidence filtering**: When joining through correlations, prefer high-confidence links (confidence >= 0.85, method='file_and_timestamp'). Flag findings that rely solely on low-confidence correlations (< 0.7, method='file_match').
3. **Quantitative overview**: Run these two queries separately and present a combined table. Do NOT join them — cross-joining inflates counts.
   - Sessions: `SELECT substr(started_at, 1, 10) as day, COUNT(*) FROM sessions WHERE started_at != '' GROUP BY day ORDER BY day`
   - Commits: `SELECT substr(author_date, 1, 10) as day, COUNT(*), SUM(insertions + deletions) FROM commits GROUP BY day ORDER BY day`
4. **One arc per major feature area** identified in step 1. Do not artificially compress unrelated features into one arc. Each arc should cover a coherent feature track (e.g., voice pipeline, axiom governance, demo system — not "recent work").
5. **Per-arc metrics box**: For each arc, find its sessions by joining feat: commits through correlations to messages to sessions (see Key Join Patterns above). Then query session_tags and session_metrics for those session IDs. Include: work_type distribution, interaction_mode, average tool_call_count, steering_ratio, and a representative phase_sequence. Format as a visible data block in the output.
   Example per-arc metrics query:
   ```sql
   SELECT st.dimension, st.value, COUNT(*) as sessions
   FROM session_tags st
   WHERE st.session_id IN (
     SELECT DISTINCT m.session_id FROM commits c
     JOIN correlations cor ON cor.commit_hash = c.hash
     JOIN messages m ON m.id = cor.message_id
     WHERE c.message LIKE '%voice%'
   )
   GROUP BY st.dimension, st.value
   ```
   Then for those same session_ids, query session_metrics:
   ```sql
   SELECT AVG(tool_call_count), AVG(user_steering_ratio),
          GROUP_CONCAT(DISTINCT phase_sequence)
   FROM session_metrics WHERE session_id IN (...)
   ```
6. **Trace actual code destinations**: Sessions are tagged by where Claude Code launched (often hapaxromana for specs), but commits may land in different repos. Check commit_files paths to identify where code actually went.
   Call file_history() for 2-3 key files from high-confidence correlations to trace where code actually landed.
7. Call session_content() for at least 3-5 pivotal sessions. Quote what was actually said — the conversations are the richest evidence.
   For the 2-3 most impactful commits per arc (highest insertions+deletions), call git_diff(commit_hash) and include the stat summary.
8. **Critical moments**: Query the critical_moments table with filtering:
   ```sql
   SELECT moment_type, severity, session_id, message_id, description
   FROM critical_moments WHERE severity > 0.3
   ORDER BY severity DESC LIMIT 15
   ```
   For the top 3-5 by severity, call session_content(session_id, around_message_id=message_id) to show the conversation context.
   Cite exact counts from query results — never estimate or round.
9. **Tool usage patterns**: For each arc's most representative session, query tool usage:
   ```sql
   SELECT tool_name, COUNT(*) as uses, SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes
   FROM tool_calls WHERE message_id IN (
     SELECT id FROM messages WHERE session_id = '...'
   )
   GROUP BY tool_name ORDER BY uses DESC
   ```
10. Explain WHY each arc led to the next: what problems triggered new work, what decisions shaped direction.

**Output constraints:**
- Begin your response directly with the first content heading (e.g., "## Feature Enumeration"). Your FIRST character must be '#'. Do not narrate your query process, announce what you are about to do, or include transition sentences between sections.
- Produce ONLY the sections above. Do NOT add synthesis sections, architectural insights, lessons learned, or conclusions beyond what is directly evidenced.
- End with the final arc, not a summary.
- **Show your data**: Include SQL query result tables (or formatted summaries) before each narrative section. Your counts must come directly from these visible results. If a number appears in prose, it must appear in a preceding data table.
- All counts must come from SQL query results. Never estimate or use round numbers when exact data is available.
- Your output should be LONG and DETAILED. Each arc should be 300-600 words with quoted conversation evidence. A complete story answer should be 2000-5000 words. Do not compress or summarize — the user wants the full narrative with evidence.

### Pattern questions
- Use SQL aggregations, GROUP BY session dimensions (session_tags)
- Use session_metrics for phase sequences and tool patterns
- Compare across dimensions with concrete numbers

### Critical moment questions
- Query critical_moments table. Moment types: churn (file rewritten many times), wrong_path (Edit→Bash debugging loops), token_waste (high token spend, low commit output)
- Retrieve conversation context showing where things went off track
- Include both harmful moments (high churn, retry loops, wasted tokens) and beneficial ones (efficient sessions, high-survival code)

### Efficiency questions
- Compare token spend, time-to-commit, tool patterns across dimensions
- Use session_metrics for tool call counts and phase sequences
- Cite specific numbers, not vague comparisons

## Evidence standards
- Always cite: session IDs, commit hashes, timestamps, confidence scores
- When a conclusion rests on low-confidence correlations (< 0.7), flag it explicitly
- When data is sparse for a project or time period, say so rather than speculating
- Prefer quoting actual conversation text over summarizing

## Diagram generation
When your answer involves relationships, flows, timelines, or architecture,
include Mermaid diagrams using fenced code blocks:

    ```mermaid
    graph TD
      A[SharedConfig] --> B[HealthMonitor]
      A --> C[Profiler]
    ```

Useful diagram types:
- Feature dependency flows: graph TD (top-down directed)
- Architecture relationships: graph LR (left-right)
- Development timelines: gantt
- Session/commit correlations: flowchart

Keep diagrams focused — max 15-20 nodes. Split complex relationships into
multiple smaller diagrams rather than one massive graph. Use descriptive
node labels, not abbreviations.

## When Data is Unavailable

If the database has no sessions or commits (queries return "No results." for all tables),
do not produce analysis that implies data exists. Instead:
- State: "The dev-story database has not been populated yet."
- Explain: "Run the git-extractor to build development history: uv run python -m agents.dev_story"
- Note: "After first run, data covers the full git history of the repository."
Answer only what you can from the data that IS available.
"""


@dataclass
class QueryDeps:
    """Runtime dependencies for the query agent."""

    db_path: str


def _sql_query(conn: sqlite3.Connection, query: str) -> str:
    """Execute a read-only SQL query and return formatted results."""
    stripped = query.strip().lower()
    if not any(stripped.startswith(p) for p in _READ_ONLY_PREFIXES):
        return "Error: Only SELECT/WITH/EXPLAIN/PRAGMA queries are allowed."

    try:
        cursor = conn.execute(query)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()

        if not rows:
            return "No results."

        # Format as table
        lines = [" | ".join(columns)]
        lines.append("-" * len(lines[0]))
        for row in rows[:100]:  # Limit output
            lines.append(" | ".join(str(v) for v in row))

        if len(rows) > 100:
            lines.append(f"... ({len(rows)} total rows, showing first 100)")

        return "\n".join(lines)
    except Exception as e:
        return f"SQL error: {e}"


def _session_content(
    conn: sqlite3.Connection,
    session_id: str,
    around_message_id: str | None = None,
) -> str:
    """Retrieve conversation text from a session."""
    if around_message_id:
        cursor = conn.execute(
            "SELECT role, timestamp, content_text FROM messages WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        )
        rows = cursor.fetchall()

        if not rows:
            return f"Session {session_id} not found."

        msg_ids_cursor = conn.execute(
            "SELECT id FROM messages WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        )
        msg_ids = [r[0] for r in msg_ids_cursor.fetchall()]
        try:
            target_idx = msg_ids.index(around_message_id)
        except ValueError:
            target_idx = len(rows) // 2

        start = max(0, target_idx - 10)
        end = min(len(rows), target_idx + 11)
        rows = rows[start:end]
    else:
        cursor = conn.execute(
            "SELECT role, timestamp, content_text FROM messages WHERE session_id = ? ORDER BY timestamp LIMIT 40",
            (session_id,),
        )
        rows = cursor.fetchall()

    if not rows:
        return f"Session {session_id} not found."

    lines = []
    for role, ts, text in rows:
        preview = text[:500] + "..." if len(text) > 500 else text
        lines.append(f"## {role.title()} ({ts})\n{preview}\n")

    return "\n".join(lines)


def _file_history(conn: sqlite3.Connection, file_path: str, since: str | None = None) -> str:
    """Show commit + session history for a file."""
    query = """
        SELECT
            c.hash, c.author_date, c.message, c.insertions, c.deletions,
            cor.confidence, cor.method,
            s.id AS session_id, s.project_name
        FROM commit_files cf
        JOIN commits c ON c.hash = cf.commit_hash
        LEFT JOIN correlations cor ON cor.commit_hash = c.hash
        LEFT JOIN messages m ON m.id = cor.message_id
        LEFT JOIN sessions s ON s.id = m.session_id
        WHERE cf.file_path = ?
        ORDER BY c.author_date DESC
        LIMIT 50
    """
    cursor = conn.execute(query, (file_path,))
    rows = cursor.fetchall()

    if not rows:
        return f"No history found for {file_path}"

    lines = [f"History for {file_path}:\n"]
    for hash, date, msg, ins, dels, conf, _method, sess_id, proj in rows:
        line = f"- {hash[:8]} ({date}) {msg} [+{ins}/-{dels}]"
        if sess_id:
            line += f" <- session {sess_id[:8]} ({proj}, confidence={conf:.2f})"
        lines.append(line)

    return "\n".join(lines)


def create_agent() -> Agent:
    """Create the dev-story query agent."""
    agent = Agent(
        get_model("balanced"),
        system_prompt=build_system_prompt(),
        deps_type=QueryDeps,
        model_settings={"max_tokens": 32768},
    )

    @agent.tool
    async def sql_query(ctx, query: str) -> str:
        """Execute read-only SQL against the dev-story database.

        Use this for all data queries — session counts, commit history, correlation analysis,
        tool_call patterns, file_change sequences, and session_tags/session_metrics lookups.
        """
        conn = sqlite3.connect(ctx.deps.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return _sql_query(conn, query)
        finally:
            conn.close()

    @agent.tool
    async def session_content(ctx, session_id: str, around_message_id: str = "") -> str:
        """Retrieve conversation text from a session. Optionally center around a specific message.

        Use this to quote what was actually said in pivotal sessions. When investigating a
        critical_moment, pass around_message_id to see the context around the issue.
        Example: session_content("abc-123", around_message_id="msg-456")
        """
        conn = sqlite3.connect(ctx.deps.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return _session_content(conn, session_id, around_message_id or None)
        finally:
            conn.close()

    @agent.tool
    async def file_history(ctx, file_path: str) -> str:
        """Trace the full development history of a specific file — every commit that touched it, which sessions drove each change (via correlation), and confidence scores.

        Use this to trace where specs became code and to understand rewrite patterns.
        Call for 2-3 key files per arc identified from high-confidence correlations.
        Example: file_history("agents/voice/pipeline.py")
        """
        conn = sqlite3.connect(ctx.deps.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return _file_history(conn, file_path)
        finally:
            conn.close()

    @agent.tool
    async def git_diff(ctx, commit_hash: str) -> str:
        """Show the stat summary for a git commit (files changed, insertions, deletions).

        Use this for the 2-3 most impactful commits per arc to show concrete code evidence.
        Quote the stat summary in your narrative. Validates commit hash format (4-40 hex chars).
        Example: git_diff("a1b2c3d4")
        """
        import subprocess

        if not _COMMIT_HASH_RE.match(commit_hash):
            return f"Invalid commit hash: {commit_hash!r}. Must be 4-40 hex characters."

        conn = sqlite3.connect(ctx.deps.db_path)
        cursor = conn.execute(
            """SELECT DISTINCT s.project_path FROM correlations cor
               JOIN messages m ON m.id = cor.message_id
               JOIN sessions s ON s.id = m.session_id
               WHERE cor.commit_hash = ? LIMIT 1""",
            (commit_hash,),
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return f"No project path found for commit {commit_hash}"

        result = subprocess.run(
            ["git", "-C", row[0], "show", "--stat", commit_hash],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return (
            result.stdout[:3000]
            if result.returncode == 0
            else f"git show failed: {result.stderr[:200]}"
        )

    return agent


def extract_full_output(result) -> str:
    """Extract all narrative text from an agent result.

    The agent interleaves text with tool calls, so result.output only
    captures the final text part. This collects all substantial text
    parts from the full message history.
    """
    parts = []
    for msg in result.all_messages():
        if not hasattr(msg, "parts"):
            continue
        for part in msg.parts:
            if type(part).__name__ == "TextPart" and hasattr(part, "content"):
                text = part.content.strip()
                if len(text) > 30:
                    parts.append(text)
    return "\n\n".join(parts) if parts else result.output
