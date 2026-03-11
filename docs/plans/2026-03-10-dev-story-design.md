# Dev Story — Development Archaeology Agent

**Date:** 2026-03-10
**Status:** Design approved
**Agent:** `agents/dev_story/`

## Purpose

Reconstruct and analyze the "development story" by correlating Claude Code conversation logs with git history. Answer questions like:

- How does LLM-assisted development mirror or differ from traditional patterns?
- What conversation and tool patterns work best?
- What were the critical beneficial vs damaging moments?
- How do different development surfaces (work type, interaction mode, environmental topology) affect efficiency?
- Where are the inefficiencies?

## Architecture

Two-phase system: **offline indexer** builds a structured SQLite database from raw artifacts, **query agent** translates natural language questions into SQL + content retrieval and synthesizes narrative answers with evidence.

### Why SQLite (not Qdrant-only)

The questions are fundamentally analytical — comparing patterns, measuring efficiency, computing survival rates across dimensions. RAG over text chunks can tell stories but can't compute "code survival rate by interaction mode." Structured storage enables:

- Precomputed metrics too expensive for per-query calculation
- SQL for precise analytical queries ("commits within 60s of a tool_use=Edit event")
- Message-level correlation as first-class joins
- Qdrant still used for semantic search over conversation content

## Data Model

### Core Tables

```sql
-- Session-level metadata
sessions (
  id TEXT PRIMARY KEY,           -- UUID from sessionId
  project_path TEXT,
  project_name TEXT,
  git_branch TEXT,
  started_at TEXT,               -- ISO 8601
  ended_at TEXT,
  message_count INTEGER,
  total_tokens_in INTEGER,
  total_tokens_out INTEGER,
  total_cost_estimate REAL,
  model_primary TEXT              -- most-used model in session
)

-- Individual conversation turns
messages (
  id TEXT PRIMARY KEY,            -- UUID from uuid field
  session_id TEXT REFERENCES sessions,
  parent_id TEXT,                 -- uuid chain for threading
  role TEXT,                      -- user | assistant
  timestamp TEXT,
  content_text TEXT,              -- stripped of tool_use blocks
  model TEXT,
  tokens_in INTEGER,
  tokens_out INTEGER
)

-- Tool invocations from assistant messages
tool_calls (
  id INTEGER PRIMARY KEY,
  message_id TEXT REFERENCES messages,
  tool_name TEXT,                 -- Read, Edit, Bash, Grep, Glob, Agent, etc.
  arguments_summary TEXT,         -- file path, command, pattern
  duration_ms INTEGER,
  success INTEGER,                -- 0 or 1
  sequence_position INTEGER       -- order within message (for chain detection)
)

-- File state changes tracked by Claude Code
file_changes (
  id INTEGER PRIMARY KEY,
  message_id TEXT REFERENCES messages,
  file_path TEXT,
  version INTEGER,                -- from backup metadata
  change_type TEXT,               -- created | modified | deleted
  timestamp TEXT
)

-- Git commits
commits (
  hash TEXT PRIMARY KEY,
  author_date TEXT,
  message TEXT,
  branch TEXT,
  files_changed INTEGER,
  insertions INTEGER,
  deletions INTEGER
)

-- Files touched per commit
commit_files (
  commit_hash TEXT REFERENCES commits,
  file_path TEXT,
  operation TEXT                   -- A | M | D
)

-- The correlation layer: joins conversations to commits
correlations (
  id INTEGER PRIMARY KEY,
  message_id TEXT REFERENCES messages,
  commit_hash TEXT REFERENCES commits,
  confidence REAL,                -- 0.0-1.0
  method TEXT                     -- timestamp_window | file_match | file_and_timestamp | content_match
)
```

### Correlation Logic

Computed by the indexer, scored by evidence quality:

1. **File + timestamp match** (confidence 0.9+): A `file_changes` entry for path X at time T, and a `commit_files` entry for path X with `author_date` within +/-30min of T.
2. **File match only** (confidence 0.5-0.7): Same file path in both streams, timestamps don't align closely.
3. **Timestamp window only** (confidence 0.2-0.4): Session active when commit was made, but no file overlap.
4. **Content match** (supplementary): Commit message references something discussed in conversation. Boosts existing correlation confidence.

### Derived Tables

```sql
-- How long does code survive before being replaced?
code_survival (
  file_path TEXT,
  introduced_by_commit TEXT REFERENCES commits,
  introduced_by_session TEXT REFERENCES sessions,
  survived_days REAL,
  replacement_commit TEXT REFERENCES commits  -- NULL if still alive
)

-- Precomputed session-level analytics
session_metrics (
  session_id TEXT PRIMARY KEY REFERENCES sessions,
  tool_call_count INTEGER,
  tool_diversity INTEGER,         -- unique tool names
  edit_count INTEGER,
  bash_count INTEGER,
  agent_dispatch_count INTEGER,
  avg_response_time_ms REAL,
  user_steering_ratio REAL,       -- short user msgs / total user msgs
  phase_sequence TEXT              -- e.g., "explore>implement>test>debug"
)

-- Files ranked by development activity concentration
hotspots (
  file_path TEXT PRIMARY KEY,
  change_frequency INTEGER,
  session_count INTEGER,           -- distinct sessions that touched it
  churn_rate REAL                  -- lines added then removed within N days
)

-- Multi-dimensional session tags
session_tags (
  session_id TEXT REFERENCES sessions,
  dimension TEXT,                  -- work_type | interaction_mode | env_topology | codebase_context | session_scale
  value TEXT,
  confidence REAL
)

-- Notable moments (good and bad)
critical_moments (
  id INTEGER PRIMARY KEY,
  moment_type TEXT,                -- churn | wrong_path | cascade | efficient | unblocking
  severity REAL,                   -- 0.0-1.0
  session_id TEXT REFERENCES sessions,
  message_id TEXT REFERENCES messages,
  commit_hash TEXT REFERENCES commits,
  description TEXT,                -- human-readable summary
  evidence TEXT                    -- JSON: related commits, sessions, metrics
)
```

## Phase Detection

Detected by sliding window over tool_call sequences per session:

| Phase | Signal |
|-------|--------|
| explore | High ratio of Read + Grep + Glob, low Edit |
| implement | High Edit + Write, moderate Bash |
| test | Bash commands containing "pytest" / "test" / "uv run" |
| debug | Cycles of Read -> Edit -> Bash(test fail) -> Read on same files |
| refactor | Edit on many files, low new file creation |
| design | High Agent dispatches, long assistant messages, few tool calls |
| review | Read-heavy with minimal edits, often at session end |

Stored as `phase_sequence` on `session_metrics`.

## Session Classification

Multi-dimensional tagging computed during indexing:

| Dimension | Detection Method |
|-----------|-----------------|
| **work_type** (feature/bugfix/refactor/docs) | Correlated commit message prefixes |
| **interaction_mode** (high-steering/autonomous/parallel/sequential) | User message lengths + frequency. Parallel = overlapping session timestamps |
| **env_topology** (containerized/host-side/cross-project/single-repo) | File paths: Dockerfile = containerized, multiple project_paths = cross-project, systemd/ = host-side |
| **codebase_context** (familiar/greenfield/well-tested/untested) | File in hotspots = familiar, new file = greenfield, correlated test files = well-tested |
| **session_scale** (single-file/single-module/cross-module/cross-repo) | Distinct file path prefixes |

## Critical Moment Detection

Three tiers, concrete to abstract:

### Tier A: Code Churn (directly measurable from git)

Code introduced and significantly rewritten within N days. Detected by comparing `code_survival` entries with short `survived_days` values, traced back to source sessions via correlations.

### Tier B: Wrong-Path Detection (measurable from transcripts)

Heuristics applied during indexing:

- **Revert patterns**: Edit to file X, then later Edit reverting same file to near-original state
- **Retry loops**: Same Bash command executed 3+ times with failures between
- **Debugging spirals**: >10 consecutive tool calls on same file(s) with alternating Edit -> Bash(fail)
- **Token waste**: Sessions with high token spend but low commit correlation
- **Abandoned branches**: Commits on a branch with no merge and no subsequent activity

### Tier C: Cascade Detection (cross-session inference)

When a Tier A churn event occurs, trace backward:

1. Find the original commit and its correlated session
2. Find the replacement commit and its correlated session
3. Look at the replacement session's conversation content
4. LLM pass: "does this session appear to be fixing a problem introduced by [summary of original session]?"

Only runs on Tier A candidates (small subset). Uses `balanced` model via LiteLLM.

### Beneficial Moments (inverted signals)

- Code with high survival rate from a specific session
- Sessions with high commit correlation and low subsequent churn
- Efficient tool chains (few calls -> successful outcome)
- Sessions that unblocked multiple subsequent sessions (file overlap + temporal sequence)

## Indexer Architecture

Batch job that builds/updates the SQLite database.

### Pipeline Stages

1. **Discover sessions**: Scan `~/.claude/projects/*/` for `*.jsonl` files. Compare mtime against last indexed timestamp. Process new/modified only (incremental mode).

2. **Parse sessions**: Stream JSONL line-by-line. Extract `type=user/assistant` -> messages. Extract `tool_use` blocks -> tool_calls. Extract `file-history-snapshot` -> file_changes. Compute session-level metrics.

3. **Parse git history**: For each `project_path` found in sessions, run `git log --format --numstat`. Incremental: only commits after last indexed hash.

4. **Correlate**: For each file_change, find commit_files with same path within +/-30min window. Score and insert into correlations table.

5. **Compute derived tables**: code_survival (git blame based), session_metrics (aggregate tool_calls), hotspots (change_frequency x session_count), session_tags, critical_moments (Tiers A, B, C).

### Performance

- Streaming JSONL parser (not full file load)
- SQLite WAL mode for concurrent read during index
- Batch inserts (1000 rows at a time)
- Full reindex: ~100 sessions x avg 5MB = ~500MB raw, estimated < 5 minutes
- Tier C LLM passes: only on Tier A churn candidates, bounded cost

## Query Agent

Pydantic-ai agent with tools for SQL execution and content retrieval.

### Tools

```python
sql_query(query: str) -> str
    # Execute read-only SQL against dev-story.db

session_content(session_id: str, around_message_id: str = None) -> str
    # Retrieve conversation text. With message_id: +/-10 messages context.
    # Without: summary (first/last messages, key tool calls)

git_diff(commit_hash: str) -> str
    # Show actual diff for a commit

file_history(file_path: str, since: str = None) -> str
    # Commit + session history for a file

compare_patterns(dimension: str, group_a: str, group_b: str) -> str
    # Prebuilt analytical comparisons across session dimensions
```

### System Prompt

Describes schema, provides example queries for different question types:

- **Story questions** -> retrieve correlated sessions + commits, narrate chronologically
- **Pattern questions** -> SQL aggregations, compare across dimensions
- **Critical moment questions** -> query critical_moments table, retrieve context
- **Efficiency questions** -> token spend, time-to-commit, tool call patterns

### Model

Routes through LiteLLM, uses `balanced` (claude-sonnet).

## Project Structure

```
agents/dev_story/
  __init__.py
  __main__.py          # CLI: --index, --interactive, positional query
  indexer.py            # Batch indexer: sessions + git -> SQLite
  parser.py             # JSONL session transcript parser (streaming)
  git_extractor.py      # Git log/diff/blame extraction
  correlator.py         # File + timestamp correlation engine
  phase_detector.py     # Tool sequence -> phase classification
  classifier.py         # Session tagging across dimensions
  critical_moments.py   # Churn, wrong-path, cascade detection
  survival.py           # Code survival curve computation
  query.py              # Pydantic-ai query agent
  schema.py             # SQLite schema + migrations
  models.py             # Pydantic models
```

## Integration

- **Database**: `profiles/dev-story.db` (gitignored)
- **Dependencies**: No new deps. sqlite3 stdlib, pydantic-ai existing, git via subprocess
- **pyproject.toml**: Falls under existing `core` extra
- **No systemd timer**: On-demand indexing and querying
- **No cockpit integration** for MVP
- **Scope**: All repos with Claude Code session data (ai-agents, hapaxromana, cockpit-web, distro-work, etc.)

## CLI

```bash
# Indexing
uv run python -m agents.dev_story --index
uv run python -m agents.dev_story --index --incremental
uv run python -m agents.dev_story --index --stats

# Querying
uv run python -m agents.dev_story "how was the fix pipeline built?"
uv run python -m agents.dev_story --interactive

# Diagnostics
uv run python -m agents.dev_story --correlations
uv run python -m agents.dev_story --hotspots
```

## Example Queries

```
"How was the fix pipeline built?"
-> Finds sessions correlated with fix_capabilities/ commits on March 9,
   narrates the chronological story with conversation excerpts + diffs

"Which sessions produced code that got rewritten fastest?"
-> Queries code_survival JOIN correlations, ranks by survived_days ASC,
   retrieves source session context

"Compare parallel vs sequential session efficiency"
-> Tags sessions by interaction_mode, compares metrics: tokens/commit,
   code survival rate, churn rate, phase distribution

"What development surface works best for Claude Code?"
-> Cross-dimensional analysis: group sessions by work_type x env_topology,
   compare commit correlation, survival, and efficiency metrics

"Show me the worst wrong-path moments"
-> Queries critical_moments WHERE moment_type IN ('wrong_path', 'cascade'),
   retrieves conversation context showing where things went off track
```
