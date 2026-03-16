"""profiler_sources.py — Data source discovery, reading, and chunking for the profiler agent.

Scans local config files, Claude Code transcripts, shell history, git repos,
memory files, and Langfuse telemetry to produce text chunks for LLM-based
profile extraction.

Includes mtime-based change detection for zero-cost incremental updates.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

log = logging.getLogger("profiler")


# ── Constants ────────────────────────────────────────────────────────────────

CHUNK_SIZE = 4000  # ~1000 tokens per chunk

# Source types with deterministic profiler bridges — their facts are loaded
# via load_structured_facts() at zero LLM cost, so they should be excluded
# from LLM extraction by default.
BRIDGED_SOURCE_TYPES = {
    "proton",
    "takeout",
    "management",
    "gcalendar",
    "gmail",
    "youtube",
    "claude-code",
    "obsidian",
    "chrome",
    "ambient-audio",
    "health-connect",
    "watch",
}

# Per-source-type chunk caps. When a source type produces more chunks than
# its cap, files are sorted by mtime (newest first) and only the most recent
# files are read. This prevents volume-heavy sources from dominating extraction.
SOURCE_TYPE_CHUNK_CAPS: dict[str, int] = {
    "llm-export": 200,
    "proton": 100,
    "takeout": 100,
    "transcript": 100,
    "config": 50,
    "memory": 50,
    "management": 50,
    "gcalendar": 50,
    "gmail": 100,
    "youtube": 50,
    "claude-code": 200,
    "obsidian": 200,
    "chrome": 50,
    "shell-history": 20,
    "git": 20,
    "drift": 10,
    "conversation": 10,
    "decisions": 10,
    "langfuse": 10,
    "ambient-audio": 100,
    "health-connect": 50,
}
from shared.config import (
    CLAUDE_CONFIG_DIR,
    HAPAX_HOME,
    RAG_SOURCES_DIR,
)
from shared.config import (
    VAULT_PATH as _VAULT_PATH,
)

HOME = HAPAX_HOME
CLAUDE_DIR = CLAUDE_CONFIG_DIR
PROJECTS_DIR = CLAUDE_DIR / "projects"
LLM_EXPORT_DIR = RAG_SOURCES_DIR / "llm-conversations"
TAKEOUT_DIR = RAG_SOURCES_DIR / "takeout"
PROTON_DIR = RAG_SOURCES_DIR / "proton"

# Roles and block types to keep from JSONL transcripts
KEEP_ROLES = {"user", "assistant"}
KEEP_BLOCK_TYPES = {"text"}
# Top-level JSONL types that carry conversation messages
CONVERSATION_TYPES = {"user", "assistant"}


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class SourceChunk:
    """A chunk of text from a data source, ready for LLM extraction."""

    text: str
    source_id: str  # e.g. "config:~/.claude/CLAUDE.md"
    source_type: str  # config, transcript, shell-history, git, memory
    char_count: int = 0

    def __post_init__(self):
        self.char_count = len(self.text)


@dataclass
class DiscoveredSources:
    """All discovered data sources grouped by type."""

    config_files: list[Path] = field(default_factory=list)
    transcript_files: list[Path] = field(default_factory=list)
    shell_history: Path | None = None
    git_repos: list[Path] = field(default_factory=list)
    memory_files: list[Path] = field(default_factory=list)
    llm_export_files: list[Path] = field(default_factory=list)
    takeout_files: list[Path] = field(default_factory=list)
    proton_files: list[Path] = field(default_factory=list)
    management_files: list[Path] = field(default_factory=list)
    langfuse_available: bool = False
    drift_report: Path | None = None
    pending_facts: Path | None = None
    decisions_log: Path | None = None


# ── Discovery ────────────────────────────────────────────────────────────────


def discover_sources() -> DiscoveredSources:
    """Scan the filesystem for all available data sources."""
    sources = DiscoveredSources()

    # Config files: ~/.claude/CLAUDE.md + rules/*.md
    global_claude_md = CLAUDE_DIR / "CLAUDE.md"
    if global_claude_md.exists():
        sources.config_files.append(global_claude_md)

    rules_dir = CLAUDE_DIR / "rules"
    if rules_dir.is_dir():
        sources.config_files.extend(sorted(rules_dir.glob("*.md")))

    # Project CLAUDE.md files across all known project dirs
    for project_dir in sorted(HOME.glob("projects/*/CLAUDE.md")):
        sources.config_files.append(project_dir)

    # Architecture docs in hapaxromana
    arch_doc = HOME / "projects" / "hapaxromana" / "agent-architecture.md"
    if arch_doc.exists():
        sources.config_files.append(arch_doc)

    # Claude Code transcripts: scan ALL project directories
    if PROJECTS_DIR.is_dir():
        for project_path in sorted(PROJECTS_DIR.iterdir()):
            if not project_path.is_dir():
                continue
            # Main session transcripts (not subagents)
            for jsonl in sorted(project_path.glob("*.jsonl")):
                sources.transcript_files.append(jsonl)

    # Shell history
    zsh_hist = HOME / ".zsh_history"
    if zsh_hist.exists():
        sources.shell_history = zsh_hist

    # Git repos
    for repo_dir in [HOME / "projects" / "ai-agents"]:
        git_dir = repo_dir / ".git"
        if git_dir.exists():
            sources.git_repos.append(repo_dir)

    # Memory files
    for mem_dir in sorted(PROJECTS_DIR.glob("*/memory")):
        if mem_dir.is_dir():
            sources.memory_files.extend(sorted(mem_dir.glob("*.md")))

    # Drift report
    drift_path = HOME / "projects" / "ai-agents" / "profiles" / "drift-report.json"
    if drift_path.exists():
        sources.drift_report = drift_path

    # Pending conversational facts
    pending_path = HOME / ".cache" / "cockpit" / "pending-facts.jsonl"
    if pending_path.exists():
        sources.pending_facts = pending_path

    # Decision log
    decisions_path = HOME / ".cache" / "cockpit" / "decisions.jsonl"
    if decisions_path.exists():
        sources.decisions_log = decisions_path

    # LLM conversation exports (markdown from platform data exports)
    if LLM_EXPORT_DIR.is_dir():
        for md_file in sorted(LLM_EXPORT_DIR.rglob("*.md")):
            sources.llm_export_files.append(md_file)

    # Takeout exports (markdown from Google Takeout processing)
    if TAKEOUT_DIR.is_dir():
        for md_file in sorted(TAKEOUT_DIR.rglob("*.md")):
            sources.takeout_files.append(md_file)

    # Proton Mail exports (markdown from Proton export processing)
    if PROTON_DIR.is_dir():
        for md_file in sorted(PROTON_DIR.rglob("*.md")):
            sources.proton_files.append(md_file)

    # Management notes (people, meetings from Obsidian vault)
    vault_path = _VAULT_PATH
    for subdir in ["10-work/people", "10-work/meetings"]:
        mgmt_dir = vault_path / subdir
        if mgmt_dir.is_dir():
            for md_file in sorted(mgmt_dir.glob("*.md")):
                sources.management_files.append(md_file)

    # Langfuse telemetry (API-based, not file-based)
    sources.langfuse_available = _check_langfuse_available()

    return sources


def list_source_ids(sources: DiscoveredSources) -> list[str]:
    """Return all source IDs that would be processed."""
    ids: list[str] = []
    for f in sources.config_files:
        ids.append(f"config:{_short_path(f)}")
    for f in sources.transcript_files:
        ids.append(f"transcript:{_short_path(f)}")
    if sources.shell_history:
        ids.append("shell-history:~/.zsh_history")
    for r in sources.git_repos:
        ids.append(f"git:{_short_path(r)}")
    for f in sources.memory_files:
        ids.append(f"memory:{_short_path(f)}")
    for f in sources.llm_export_files:
        ids.append(f"llm-export:{_short_path(f)}")
    for f in sources.takeout_files:
        ids.append(f"takeout:{_short_path(f)}")
    for f in sources.proton_files:
        ids.append(f"proton:{_short_path(f)}")
    for f in sources.management_files:
        ids.append(f"management:{_short_path(f)}")
    if sources.drift_report:
        ids.append(f"drift:{_short_path(sources.drift_report)}")
    if sources.pending_facts:
        ids.append(f"conversation:{_short_path(sources.pending_facts)}")
    if sources.decisions_log:
        ids.append(f"decisions:{_short_path(sources.decisions_log)}")
    if sources.langfuse_available:
        ids.append("langfuse:telemetry")
    return ids


# ── Readers ──────────────────────────────────────────────────────────────────


def read_config_file(path: Path) -> list[SourceChunk]:
    """Read a config/markdown file and chunk it."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.warning("Failed to read config %s: %s", path, exc)
        return []
    source_id = f"config:{_short_path(path)}"
    return _chunk_text(text, source_id, "config")


def read_transcript(path: Path) -> list[SourceChunk]:
    """Read a JSONL transcript, filter to user/assistant text content, and chunk."""
    texts: list[str] = []

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Only process conversation messages
            top_type = obj.get("type", "")
            if top_type not in CONVERSATION_TYPES:
                continue

            msg = obj.get("message", {})
            if not isinstance(msg, dict):
                continue

            role = msg.get("role", "")
            if role not in KEEP_ROLES:
                continue

            content = msg.get("content", "")
            extracted = _extract_text_content(content, role)
            if extracted:
                texts.append(extracted)

    if not texts:
        return []

    combined = "\n\n".join(texts)
    source_id = f"transcript:{_short_path(path)}"
    return _chunk_text(combined, source_id, "transcript")


def read_shell_history(path: Path) -> list[SourceChunk]:
    """Read shell history file and return as a single chunk."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    # zsh history lines may have timestamps like ": 1234567890:0;command"
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith(": ") and ";" in line:
            # Strip zsh timestamp prefix
            cmd = line.split(";", 1)[1] if ";" in line else line
            lines.append(cmd)
        else:
            lines.append(line)

    cleaned = "\n".join(lines[-500:])  # Last 500 commands
    source_id = "shell-history:~/.zsh_history"
    return _chunk_text(cleaned, source_id, "shell-history")


def read_git_info(repo_path: Path) -> list[SourceChunk]:
    """Extract git author info and recent commit messages."""
    texts: list[str] = []

    try:
        # Author info
        result = subprocess.run(
            ["git", "-C", str(repo_path), "log", "--format=%an <%ae>", "-1"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            texts.append(f"Git author: {result.stdout.strip()}")

        # Recent commits (last 20)
        result = subprocess.run(
            ["git", "-C", str(repo_path), "log", "--format=%s", "-20"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            texts.append(f"Recent commits in {repo_path.name}:\n{result.stdout.strip()}")
    except (subprocess.TimeoutExpired, OSError):
        pass

    if not texts:
        return []

    combined = "\n\n".join(texts)
    source_id = f"git:{_short_path(repo_path)}"
    return [SourceChunk(text=combined, source_id=source_id, source_type="git")]


def read_memory_file(path: Path) -> list[SourceChunk]:
    """Read a memory markdown file and chunk it."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.warning("Failed to read memory %s: %s", path, exc)
        return []
    source_id = f"memory:{_short_path(path)}"
    return _chunk_text(text, source_id, "memory")


def read_llm_export(path: Path) -> list[SourceChunk]:
    """Read an LLM conversation export markdown file and chunk it."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.warning("Failed to read LLM export %s: %s", path, exc)
        return []
    source_id = f"llm-export:{_short_path(path)}"
    return _chunk_text(text, source_id, "llm-export")


def read_takeout(path: Path) -> list[SourceChunk]:
    """Read a Takeout markdown file and chunk it."""
    text = path.read_text(encoding="utf-8", errors="replace")
    source_id = f"takeout:{_short_path(path)}"
    return _chunk_text(text, source_id, "takeout")


def read_proton(path: Path) -> list[SourceChunk]:
    """Read a Proton Mail markdown file and chunk it."""
    text = path.read_text(encoding="utf-8", errors="replace")
    source_id = f"proton:{_short_path(path)}"
    return _chunk_text(text, source_id, "proton")


def read_management_notes(path: Path) -> list[SourceChunk]:
    """Read a management note (person/meeting) from the vault."""
    text = path.read_text(encoding="utf-8", errors="replace")
    source_id = f"management:{_short_path(path)}"
    return _chunk_text(text, source_id, "management")


def read_phone_health_summary(watch_dir: Path) -> list[dict]:
    """Extract profile facts from phone_health_summary.json.

    Returns facts with source "phone:pixel_10" for daily totals
    (steps, active_minutes, sleep, resting HR).
    """
    summary_file = watch_dir / "phone_health_summary.json"
    if not summary_file.exists():
        return []
    try:
        data = json.loads(summary_file.read_text())
    except (json.JSONDecodeError, OSError):
        return []

    # Only use today's data
    from datetime import date as _date

    if data.get("date") != _date.today().isoformat():
        return []

    facts: list[dict] = []
    source = "phone:pixel_10"

    if data.get("resting_hr") is not None:
        facts.append(
            {
                "key": "health.resting_hr",
                "value": data["resting_hr"],
                "dimension": "energy_and_attention",
                "authority": "observation",
                "source": source,
            }
        )
    if data.get("steps") is not None:
        facts.append(
            {
                "key": "health.steps",
                "value": data["steps"],
                "dimension": "energy_and_attention",
                "authority": "observation",
                "source": source,
            }
        )
    if data.get("active_minutes") is not None:
        facts.append(
            {
                "key": "health.active_minutes",
                "value": data["active_minutes"],
                "dimension": "energy_and_attention",
                "authority": "observation",
                "source": source,
            }
        )
    if data.get("sleep_duration_min") is not None:
        facts.append(
            {
                "key": "health.sleep_duration",
                "value": data["sleep_duration_min"],
                "dimension": "energy_and_attention",
                "authority": "observation",
                "source": source,
            }
        )
    return facts


def read_watch_facts(watch_dir: Path | None = None) -> list[dict]:
    """Extract profile facts from watch state files.

    Reads heartrate.json, hrv.json, activity.json from the watch state directory
    and produces Observation-authority facts for the energy_and_attention dimension.

    Prefers phone daily aggregates (phone_health_summary.json) when available
    for daily totals (steps, active_minutes, sleep). Falls back to watch data.

    Returns empty list when no watch data is available (graceful degradation).
    """
    watch_dir = watch_dir or (HAPAX_HOME / "hapax-state" / "watch")
    facts: list[dict] = []

    # Check phone summary first for daily totals
    phone_facts = read_phone_health_summary(watch_dir)
    phone_keys = {f["key"] for f in phone_facts}
    facts.extend(phone_facts)

    # Heart rate — use watch for real-time, phone for resting
    hr_file = watch_dir / "heartrate.json"
    if hr_file.exists() and "health.resting_hr" not in phone_keys:
        try:
            data = json.loads(hr_file.read_text())
            current = data.get("current", {})
            if current.get("bpm") is not None:
                facts.append(
                    {
                        "key": "health.resting_hr",
                        "value": current["bpm"],
                        "dimension": "energy_and_attention",
                        "authority": "observation",
                        "source": "watch:pixel_watch_4",
                    }
                )
        except (json.JSONDecodeError, OSError):
            pass

    # HRV
    hrv_file = watch_dir / "hrv.json"
    if hrv_file.exists():
        try:
            data = json.loads(hrv_file.read_text())
            window = data.get("window_1h", {})
            if window.get("mean") is not None:
                facts.append(
                    {
                        "key": "health.hrv_baseline",
                        "value": window["mean"],
                        "dimension": "energy_and_attention",
                        "authority": "observation",
                        "source": "watch:pixel_watch_4",
                    }
                )
        except (json.JSONDecodeError, OSError):
            pass

    # Activity — only from watch if phone didn't provide
    activity_file = watch_dir / "activity.json"
    if activity_file.exists() and "health.active_minutes" not in phone_keys:
        try:
            data = json.loads(activity_file.read_text())
            active_min = data.get("active_minutes_today")
            if active_min is not None:
                facts.append(
                    {
                        "key": "health.active_minutes",
                        "value": active_min,
                        "dimension": "energy_and_attention",
                        "authority": "observation",
                        "source": "watch:pixel_watch_4",
                    }
                )
        except (json.JSONDecodeError, OSError):
            pass

    return facts


# ── Bulk reader ──────────────────────────────────────────────────────────────


def read_all_sources(
    sources: DiscoveredSources,
    *,
    source_filter: str | None = None,
    skip_source_ids: set[str] | None = None,
    exclude_source_types: set[str] | None = None,
) -> list[SourceChunk]:
    """Read all discovered sources and return chunks.

    Args:
        sources: Discovered sources to read.
        source_filter: If set, only read this source type (config, transcript, etc.)
        skip_source_ids: Source IDs already processed (for incremental updates).
        exclude_source_types: Source types to skip entirely (e.g. bridged sources).
    """
    skip = skip_source_ids or set()
    exclude = exclude_source_types or set()
    chunks: list[SourceChunk] = []

    def _want(source_type: str) -> bool:
        """Check if a source type should be read given filter and exclusion."""
        if source_filter is not None:
            return source_filter == source_type
        return source_type not in exclude

    def _read_capped(
        paths: list[Path],
        source_type: str,
        reader: Callable[[Path], list[SourceChunk]],
        sid_prefix: str,
    ) -> None:
        """Read files sorted by mtime (newest first), stop at chunk cap."""
        cap = SOURCE_TYPE_CHUNK_CAPS.get(source_type)
        # Sort by mtime descending (most recent first)
        sorted_paths = _sort_by_mtime(paths)
        type_chunks: list[SourceChunk] = []
        for idx, path in enumerate(sorted_paths):
            sid = f"{sid_prefix}:{_short_path(path)}"
            if sid in skip:
                continue
            try:
                file_chunks = reader(path)
            except (OSError, UnicodeDecodeError) as e:
                log.warning("Failed to read %s: %s", path, e)
                continue
            type_chunks.extend(file_chunks)
            if cap and len(type_chunks) >= cap:
                remaining = len(sorted_paths) - idx - 1
                if remaining > 0:
                    log.info(
                        "Chunk cap reached for %s: %d chunks (cap %d), skipping %d remaining files",
                        source_type,
                        len(type_chunks),
                        cap,
                        remaining,
                    )
                type_chunks = type_chunks[:cap]
                break
        chunks.extend(type_chunks)

    if _want("config"):
        _read_capped(sources.config_files, "config", read_config_file, "config")

    if _want("transcript"):
        _read_capped(sources.transcript_files, "transcript", read_transcript, "transcript")

    if _want("shell-history"):
        if sources.shell_history and "shell-history:~/.zsh_history" not in skip:
            chunks.extend(read_shell_history(sources.shell_history))

    if _want("git"):
        for repo in sources.git_repos:
            sid = f"git:{_short_path(repo)}"
            if sid not in skip:
                try:
                    chunks.extend(read_git_info(repo))
                except Exception as e:
                    log.warning("Failed to read git info from %s: %s", repo, e)

    if _want("memory"):
        _read_capped(sources.memory_files, "memory", read_memory_file, "memory")

    if _want("llm-export"):
        _read_capped(sources.llm_export_files, "llm-export", read_llm_export, "llm-export")

    if _want("takeout"):
        _read_capped(sources.takeout_files, "takeout", read_takeout, "takeout")

    if _want("proton"):
        _read_capped(sources.proton_files, "proton", read_proton, "proton")

    if _want("management"):
        _read_capped(sources.management_files, "management", read_management_notes, "management")

    if _want("drift") and sources.drift_report:
        sid = f"drift:{_short_path(sources.drift_report)}"
        if sid not in skip:
            chunks.extend(read_drift_report(sources.drift_report))

    if _want("conversation") and sources.pending_facts:
        sid = f"conversation:{_short_path(sources.pending_facts)}"
        if sid not in skip:
            chunks.extend(read_pending_facts(sources.pending_facts))

    if _want("decisions") and sources.decisions_log:
        sid = f"decisions:{_short_path(sources.decisions_log)}"
        if sid not in skip:
            chunks.extend(read_decisions_log(sources.decisions_log))

    if _want("langfuse") and sources.langfuse_available and "langfuse:telemetry" not in skip:
        chunks.extend(read_langfuse())

    return chunks


# ── Drift report reader ──────────────────────────────────────────────────


def read_drift_report(path: Path) -> list[SourceChunk]:
    """Read drift-report.json and produce a text chunk for profile extraction."""
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []

    items = data.get("drift_items", [])
    if not items:
        return []

    lines = [f"Drift report ({len(items)} items):"]
    for item in items:
        doc = item.get("document", "unknown")
        desc = item.get("description", "")
        lines.append(f"- {doc}: {desc}")

    source_id = f"drift:{_short_path(path)}"
    return [SourceChunk(text="\n".join(lines), source_id=source_id, source_type="drift")]


# ── Pending conversational facts reader ──────────────────────────────────


def read_pending_facts(path: Path) -> list[SourceChunk]:
    """Read pending-facts.jsonl and produce text chunks for profile extraction."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return []

    if not text:
        return []

    lines = []
    for raw_line in text.splitlines():
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        dim = entry.get("dimension", "unknown")
        key = entry.get("key", "")
        value = entry.get("value", "")
        evidence = entry.get("evidence", "")
        lines.append(f"- [{dim}] {key}: {value}")
        if evidence:
            lines.append(f"  evidence: {evidence}")

    if not lines:
        return []

    header = f"Pending conversational observations ({len(lines)} entries):"
    source_id = f"conversation:{_short_path(path)}"
    return [
        SourceChunk(
            text=header + "\n" + "\n".join(lines),
            source_id=source_id,
            source_type="conversation",
        )
    ]


# ── Decisions log reader ──────────────────────────────────────────────────


def read_decisions_log(path: Path) -> list[SourceChunk]:
    """Read decisions.jsonl and produce text chunks for behavioral profiling."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return []

    if not text:
        return []

    lines = []
    for raw_line in text.splitlines():
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        ts = entry.get("timestamp", "")[:19]  # Trim to readable length
        title = entry.get("nudge_title", "unknown")
        cat = entry.get("nudge_category", "")
        action = entry.get("action", "unknown")
        lines.append(f"- [{ts}] {action}: {title} ({cat})")

    if not lines:
        return []

    header = f"Operator decisions ({len(lines)} entries):"
    source_id = f"decisions:{_short_path(path)}"
    return [
        SourceChunk(
            text=header + "\n" + "\n".join(lines),
            source_id=source_id,
            source_type="decisions",
        )
    ]


# ── Langfuse telemetry reader ────────────────────────────────────────────

from shared.langfuse_client import (
    LANGFUSE_PK as _LANGFUSE_PK,
)
from shared.langfuse_client import (
    is_available as _check_langfuse_available,
)
from shared.langfuse_client import (
    langfuse_get as _langfuse_get,
)

LANGFUSE_LOOKBACK_DAYS = 30


def read_langfuse(lookback_days: int = LANGFUSE_LOOKBACK_DAYS) -> list[SourceChunk]:
    """Query Langfuse traces and produce behavioral summary chunks.

    Aggregates model usage, trace patterns, error rates, and cost data
    into text descriptions suitable for LLM-based profile extraction.
    """
    if not _LANGFUSE_PK:
        return []

    since = datetime.now(UTC) - timedelta(days=lookback_days)

    # Fetch all traces in window
    MAX_PAGES = 20
    all_traces: list[dict] = []
    page = 1
    while True:
        if page > MAX_PAGES:
            log.warning("Langfuse traces pagination limit reached (%d pages)", MAX_PAGES)
            break
        result = _langfuse_get(
            "/traces",
            {
                "fromTimestamp": since.isoformat(),
                "limit": 100,
                "page": page,
            },
        )
        traces = result.get("data", [])
        if not traces:
            break
        all_traces.extend(traces)
        total = result.get("meta", {}).get("totalItems", 0)
        if len(all_traces) >= total:
            break
        page += 1

    if not all_traces:
        return []

    # Fetch all generations in window
    all_obs: list[dict] = []
    page = 1
    while True:
        if page > MAX_PAGES:
            log.warning("Langfuse observations pagination limit reached (%d pages)", MAX_PAGES)
            break
        result = _langfuse_get(
            "/observations",
            {
                "fromStartTime": since.isoformat(),
                "type": "GENERATION",
                "limit": 100,
                "page": page,
            },
        )
        obs = result.get("data", [])
        if not obs:
            break
        all_obs.extend(obs)
        total = result.get("meta", {}).get("totalItems", 0)
        if len(all_obs) >= total:
            break
        page += 1

    # Aggregate behavioral data
    sections: list[str] = []
    source_id = "langfuse:telemetry"

    # ── Model preferences ──
    model_counts: Counter[str] = Counter()
    model_tokens: dict[str, dict[str, int]] = {}
    model_cost: Counter[str] = Counter()
    model_errors: Counter[str] = Counter()
    total_cost = 0.0

    for obs in all_obs:
        meta = obs.get("metadata", {}) or {}
        model = meta.get("model_group", obs.get("model", "unknown"))
        usage = obs.get("usage", {}) or {}
        cost = float(obs.get("calculatedTotalCost") or 0)
        level = obs.get("level", "DEFAULT")

        model_counts[model] += 1
        if model not in model_tokens:
            model_tokens[model] = {"input": 0, "output": 0}
        model_tokens[model]["input"] += usage.get("input", 0) or 0
        model_tokens[model]["output"] += usage.get("output", 0) or 0
        model_cost[model] += cost
        total_cost += cost
        if level == "ERROR":
            model_errors[model] += 1

    if model_counts:
        lines = [
            f"LLM Model Usage (last {lookback_days} days, {sum(model_counts.values())} total calls, ${total_cost:.4f} total cost):"
        ]
        for model, count in model_counts.most_common():
            tokens = model_tokens.get(model, {})
            cost = model_cost[model]
            errors = model_errors.get(model, 0)
            pct = 100 * count / sum(model_counts.values())
            err_str = f", {errors} errors" if errors else ""
            lines.append(
                f"  {model}: {count} calls ({pct:.0f}%), "
                f"{tokens.get('input', 0)} in / {tokens.get('output', 0)} out tokens, "
                f"${cost:.4f}{err_str}"
            )
        sections.append("\n".join(lines))

    # ── Trace name distribution (task types) ──
    trace_names: Counter[str] = Counter()
    for t in all_traces:
        name = t.get("name", "")
        if name:
            trace_names[name] += 1

    if trace_names:
        lines = [f"Trace Types (task distribution, {len(all_traces)} total traces):"]
        for name, count in trace_names.most_common(15):
            lines.append(f"  {name}: {count} traces")
        sections.append("\n".join(lines))

    # ── Usage cadence (hour-of-day distribution) ──
    hour_counts: Counter[int] = Counter()
    day_counts: Counter[str] = Counter()
    for t in all_traces:
        ts_str = t.get("timestamp", "")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                hour_counts[ts.hour] += 1
                day_counts[ts.strftime("%A")] += 1
            except ValueError:
                pass

    if hour_counts:
        peak_hours = [str(h) for h, _ in hour_counts.most_common(3)]
        quiet_hours = sorted(set(range(24)) - set(hour_counts.keys()))
        lines = ["Usage Cadence:"]
        lines.append(f"  Peak hours (UTC): {', '.join(peak_hours)}")
        if quiet_hours:
            ranges = _compress_ranges(quiet_hours)
            lines.append(f"  Quiet hours (UTC): {ranges}")
        if day_counts:
            active_days = [d for d, _ in day_counts.most_common(3)]
            lines.append(f"  Most active days: {', '.join(active_days)}")
        sections.append("\n".join(lines))

    # ── Error patterns ──
    if model_errors:
        total_errors = sum(model_errors.values())
        total_calls = sum(model_counts.values())
        lines = [
            f"Error Patterns ({total_errors}/{total_calls} calls failed, {100 * total_errors / total_calls:.1f}% error rate):"
        ]
        for model, err_count in model_errors.most_common():
            calls = model_counts[model]
            lines.append(f"  {model}: {err_count}/{calls} failed ({100 * err_count / calls:.0f}%)")
        sections.append("\n".join(lines))

    if not sections:
        return []

    text = "\n\n".join(sections)
    return _chunk_text(text, source_id, "langfuse")


def _compress_ranges(hours: list[int]) -> str:
    """Compress a sorted list of hours into ranges like '0-5, 23'."""
    if not hours:
        return ""
    ranges: list[str] = []
    start = hours[0]
    end = hours[0]
    for h in hours[1:]:
        if h == end + 1:
            end = h
        else:
            ranges.append(f"{start}-{end}" if start != end else str(start))
            start = end = h
    ranges.append(f"{start}-{end}" if start != end else str(start))
    return ", ".join(ranges)


def _langfuse_latest_timestamp() -> float | None:
    """Get the timestamp of the most recent Langfuse trace as a unix epoch."""
    result = _langfuse_get("/traces", {"limit": 1})
    traces = result.get("data", [])
    if not traces:
        return None
    ts_str = traces[0].get("timestamp", "")
    if not ts_str:
        return None
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return ts.timestamp()
    except ValueError:
        return None


# ── Helpers ──────────────────────────────────────────────────────────────────


def _short_path(path: Path) -> str:
    """Shorten a path for display by replacing home dir with ~."""
    try:
        return "~/" + str(path.relative_to(HOME))
    except ValueError:
        return str(path)


def _extract_text_content(content: str | list, role: str) -> str:
    """Extract plain text from message content, skipping tool_use/thinking blocks."""
    if isinstance(content, str):
        return f"[{role}]: {content}" if content.strip() else ""

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in KEEP_BLOCK_TYPES:
                text = block.get("text", "")
                if text.strip():
                    parts.append(text)
        if parts:
            return f"[{role}]: {' '.join(parts)}"

    return ""


def _sort_by_mtime(paths: list[Path]) -> list[Path]:
    """Sort paths by modification time, newest first. Missing files sort last."""

    def _mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    return sorted(paths, key=_mtime, reverse=True)


def _chunk_text(text: str, source_id: str, source_type: str) -> list[SourceChunk]:
    """Split text into chunks of approximately CHUNK_SIZE characters."""
    text = text.strip()
    if not text:
        return []

    if len(text) <= CHUNK_SIZE:
        return [SourceChunk(text=text, source_id=source_id, source_type=source_type)]

    chunks: list[SourceChunk] = []
    # Split on paragraph boundaries (double newlines), then reassemble into chunks
    paragraphs = text.split("\n\n")
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 2  # account for separator
        if current_len + para_len > CHUNK_SIZE and current:
            chunks.append(
                SourceChunk(
                    text="\n\n".join(current),
                    source_id=source_id,
                    source_type=source_type,
                )
            )
            current = []
            current_len = 0
        current.append(para)
        current_len += para_len

    if current:
        chunks.append(
            SourceChunk(
                text="\n\n".join(current),
                source_id=source_id,
                source_type=source_type,
            )
        )

    return chunks


# ── Change detection ─────────────────────────────────────────────────────────

from shared.config import PROFILES_DIR as STATE_DIR

STATE_FILE = STATE_DIR / ".state.json"


def _source_path(source_id: str, sources: DiscoveredSources) -> Path | None:
    """Resolve a source_id back to its filesystem path."""
    prefix, _, path_str = source_id.partition(":")
    if not path_str:
        return None

    # Expand ~ back to home
    expanded = Path(path_str.replace("~", str(HOME), 1))

    if prefix == "shell-history":
        return sources.shell_history
    if prefix == "git":
        # For git repos, use the .git dir mtime as proxy
        git_dir = expanded / ".git"
        return git_dir if git_dir.exists() else expanded

    return expanded if expanded.exists() else None


def get_source_mtimes(sources: DiscoveredSources) -> dict[str, float]:
    """Get mtime for every discovered source.

    Returns dict of source_id → mtime (unix timestamp).
    """
    mtimes: dict[str, float] = {}
    all_ids = list_source_ids(sources)

    for sid in all_ids:
        if sid == "langfuse:telemetry":
            # API-based source: use latest trace timestamp as proxy for mtime
            ts = _langfuse_latest_timestamp()
            if ts:
                mtimes[sid] = ts
            continue
        path = _source_path(sid, sources)
        if path and path.exists():
            try:
                mtimes[sid] = path.stat().st_mtime
            except OSError:
                pass

    return mtimes


def load_state() -> dict:
    """Load persisted state from .state.json."""
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(
    mtimes: dict[str, float],
    sources_processed: list[str],
) -> None:
    """Persist run state for future change detection."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = {
        "last_run": datetime.now(UTC).isoformat(),
        "source_mtimes": mtimes,
        "sources_processed": sources_processed,
    }
    STATE_FILE.write_text(json.dumps(state, indent=2))


def detect_changed_sources(sources: DiscoveredSources) -> tuple[set[str], set[str]]:
    """Compare current source mtimes to last run.

    Returns:
        (changed_ids, new_ids) — sources that were modified and sources
        that are entirely new since last run.
    """
    state = load_state()
    old_mtimes = state.get("source_mtimes", {})
    current_mtimes = get_source_mtimes(sources)

    changed: set[str] = set()
    new: set[str] = set()

    for sid, mtime in current_mtimes.items():
        if sid not in old_mtimes:
            new.add(sid)
        elif mtime > old_mtimes[sid]:
            changed.add(sid)

    return changed, new
