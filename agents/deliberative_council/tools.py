from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

HAPAX_COUNCIL_DIR = Path(__file__).resolve().parent.parent.parent
VAULT_DIR = Path.home() / "Documents" / "Personal"
MAX_READ_CHARS = 4000


async def read_source(ctx: Any, path: str) -> str:
    """Read a source_ref file to verify it exists and check content."""
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
    from pydantic_ai import Agent

    from shared.config import get_model

    agent = Agent(get_model("web-research"))
    result = await agent.run(f"Search and summarize evidence for or against: {query}")
    return str(result.output)[:MAX_READ_CHARS]


async def qdrant_lookup(ctx: Any, query: str, collection: str = "affordances") -> str:
    """RAG search across ingested documents."""
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
