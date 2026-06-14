from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

HAPAX_COUNCIL_DIR = Path(__file__).resolve().parent.parent.parent
VAULT_DIR = Path.home() / "Documents" / "Personal"
MAX_READ_CHARS = 4000
# web_verify spawns a nested Perplexity agent with no internal bound; one slow
# call consumed most of a member's research budget and produced the TimeoutError
# cascade (verified diagnosis 2026-06-14). Bound it so a slow provider degrades
# to "no external evidence", never a starved member.
_WEB_VERIFY_TIMEOUT_S = float(os.environ.get("HAPAX_COUNCIL_WEB_VERIFY_TIMEOUT_S", "45"))


async def read_source(ctx: Any, path: str) -> str:
    """Read a source_ref file to verify it exists and check content."""
    log.info("council_tool call: read_source(%s)", path)
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = HAPAX_COUNCIL_DIR / p
    if not p.exists():
        return f"File not found: {p}"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_READ_CHARS:
            return text[:MAX_READ_CHARS] + f"\n... [{len(text) - MAX_READ_CHARS} more chars]"
        return text
    except Exception as e:
        return f"Error reading {p}: {e}"


async def grep_evidence(ctx: Any, pattern: str, scope: str) -> str:
    """Search codebase for evidence."""
    log.info("council_tool call: grep_evidence(%s, %s)", pattern, scope)
    search_dir = HAPAX_COUNCIL_DIR / scope
    if not search_dir.is_dir():
        search_dir = HAPAX_COUNCIL_DIR
    try:
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", "--include=*.md", pattern, str(search_dir)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        lines = result.stdout.strip().split("\n")[:20]
        if not lines or lines == [""]:
            return f"No matches for '{pattern}' in {scope}"
        return "\n".join(lines)
    except subprocess.TimeoutExpired:
        return f"Search timed out for '{pattern}' in {scope}"


async def git_provenance(ctx: Any, path: str) -> str:
    """Authorship, date, and commit context for a source file."""
    log.info("council_tool call: git_provenance(%s)", path)
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-5", "--", path],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(HAPAX_COUNCIL_DIR),
        )
        if not result.stdout.strip():
            return f"No git history for {path}"
        return result.stdout.strip()
    except Exception as e:
        return f"Git error for {path}: {e}"


async def web_verify(ctx: Any, query: str) -> str:
    """Web search via Perplexity Sonar for verifying external claims."""
    log.info("council_tool call: web_verify(%s)", query[:100])
    from pydantic_ai import Agent

    from shared.config import get_model

    agent = Agent(get_model("web-research"))
    try:
        result = await asyncio.wait_for(
            agent.run(f"Search and summarize evidence for or against: {query}"),
            timeout=_WEB_VERIFY_TIMEOUT_S,
        )
    except TimeoutError:
        log.warning("web_verify timed out after %.0fs: %s", _WEB_VERIFY_TIMEOUT_S, query[:80])
        return f"(web_verify timed out after {_WEB_VERIFY_TIMEOUT_S:.0f}s — no external evidence gathered)"
    return str(result.output)[:MAX_READ_CHARS]


async def qdrant_lookup(ctx: Any, query: str, collection: str = "affordances") -> str:
    """RAG search across ingested documents."""
    log.info("council_tool call: qdrant_lookup(%s, %s)", query[:100], collection)
    try:
        from shared.config import embed

        vector = embed(query)
        from qdrant_client import QdrantClient

        client = QdrantClient(host="localhost", port=6333)
        results = client.search(collection_name=collection, query_vector=vector, limit=3)
        if not results:
            return f"No results in {collection} for: {query}"
        return "\n---\n".join(
            f"score={r.score:.3f}: {r.payload.get('text', '')[:500]}" for r in results
        )
    except Exception as e:
        return f"Qdrant error: {e}"


async def vault_read(ctx: Any, note_path: str) -> str:
    """Read an Obsidian vault note."""
    log.info("council_tool call: vault_read(%s)", note_path)
    p = VAULT_DIR / note_path
    if not p.exists():
        return f"Vault note not found: {note_path}"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_READ_CHARS:
            return text[:MAX_READ_CHARS] + f"\n... [{len(text) - MAX_READ_CHARS} more chars]"
        return text
    except Exception as e:
        return f"Error reading vault note: {e}"


async def git_diff(ctx: Any, ref: str = "HEAD~1") -> str:
    """Show git diff against a reference (default: last commit)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", ref],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(HAPAX_COUNCIL_DIR),
        )
        stat = result.stdout.strip()
        detail = subprocess.run(
            ["git", "diff", ref, "--", "*.py"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(HAPAX_COUNCIL_DIR),
        )
        diff_text = detail.stdout.strip()
        if len(diff_text) > MAX_READ_CHARS:
            diff_text = (
                diff_text[:MAX_READ_CHARS] + f"\n... [{len(diff_text) - MAX_READ_CHARS} more chars]"
            )
        return f"## Diff stat vs {ref}\n{stat}\n\n## Python changes\n{diff_text}"
    except Exception as e:
        return f"Git diff error: {e}"


FULL_TOOLS = (
    read_source,
    grep_evidence,
    git_provenance,
    git_diff,
    web_verify,
    qdrant_lookup,
    vault_read,
)
RESTRICTED_TOOLS = (read_source, grep_evidence)
