from __future__ import annotations

import asyncio
import contextvars
import logging
import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .capability_admission import admit_tool, tool_result_prefix

log = logging.getLogger(__name__)

HAPAX_COUNCIL_DIR = Path(__file__).resolve().parent.parent.parent
VAULT_DIR = Path.home() / "Documents" / "Personal"
MAX_READ_CHARS = 4000
# web_verify spawns a nested Perplexity agent with no internal bound; one slow
# call consumed most of a member's research budget and produced the TimeoutError
# cascade (verified diagnosis 2026-06-14). Bound it so a slow provider degrades
# to "no external evidence", never a starved member.
_WEB_VERIFY_TIMEOUT_S = float(os.environ.get("HAPAX_COUNCIL_WEB_VERIFY_TIMEOUT_S", "45"))

# ── PER-RUN TOOL MEMOIZATION ──────────────────────────────────────────────────
# cc-task cctv-prompt-caching-quality-neutral-20260607 R4. Across one
# ``deliberate()`` run the same source file is read and the same pattern grepped
# many times (every member, every phase). The deterministic read-only tools
# (read_source / grep_evidence) short-circuit identical sub-calls within a single
# deliberation via a ContextVar-scoped cache. The cache is entered by
# ``tool_memoization_scope()`` (engine.deliberate wraps its body); the ContextVar
# is COPIED into the asyncio.gather member tasks, so all members of one
# deliberation share one cache while distinct deliberations stay isolated. When
# no scope is active (default None) the tools run uncached — unchanged behaviour
# for any caller outside ``deliberate()``.
_tool_cache: contextvars.ContextVar[dict[tuple[str, ...], str] | None] = contextvars.ContextVar(
    "cctv_tool_cache", default=None
)


@contextmanager
def tool_memoization_scope() -> Iterator[None]:
    """Activate a per-run memoization cache for the duration of the block.

    REENTRANT: when a cache is already active (an OUTER scope — e.g. one segment's whole
    multi-pass prep, opened at the ``prep_segment`` call site), reuse it so research done
    in an early pass is not re-paid in a later pass; only the OUTERMOST scope creates and
    tears down the cache. A fresh outermost scope still isolates distinct segments. Without
    this, each inner ``deliberate()`` opened its own scope and re-ran identical
    web_verify/grep/read research every recompose pass — a dominant prep-budget sink.
    """
    if _tool_cache.get() is not None:
        # Reuse the active (outer) cache — do NOT reset it, so it survives this block.
        yield
        return
    token = _tool_cache.set({})
    try:
        yield
    finally:
        _tool_cache.reset(token)


def _memo_get(key: tuple[str, ...]) -> str | None:
    cache = _tool_cache.get()
    return None if cache is None else cache.get(key)


def _memo_put(key: tuple[str, ...], value: str) -> str:
    cache = _tool_cache.get()
    if cache is not None:
        cache[key] = value
    return value


async def read_source(ctx: Any, path: str) -> str:
    """Read a source_ref file to verify it exists and check content."""
    key = ("read_source", path)
    cached = _memo_get(key)
    if cached is not None:
        return cached
    log.info("council_tool call: read_source(%s)", path)
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = HAPAX_COUNCIL_DIR / p
    if not p.exists():
        return _memo_put(key, f"File not found: {p}")
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + f"\n... [{len(text) - MAX_READ_CHARS} more chars]"
        return _memo_put(key, text)
    except Exception as e:
        return _memo_put(key, f"Error reading {p}: {e}")


async def grep_evidence(ctx: Any, pattern: str, scope: str) -> str:
    """Search codebase for evidence."""
    key = ("grep_evidence", pattern, scope)
    cached = _memo_get(key)
    if cached is not None:
        return cached
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
            return _memo_put(key, f"No matches for '{pattern}' in {scope}")
        return _memo_put(key, "\n".join(lines))
    except subprocess.TimeoutExpired:
        # Transient — do NOT memoize so a later identical call can retry.
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
    """Web search via Perplexity Sonar for verifying external claims.

    Memoized within the active scope (the dominant research cost): an identical query is
    fetched once per segment, and a query that TIMES OUT is memoized too — re-asking it
    would re-pay the full 45s for the same dead result. The per-segment scope is
    short-lived, so a transient slow query is at most re-checked on the next segment.
    """
    key = ("web_verify", query)
    cached = _memo_get(key)
    if cached is not None:
        return cached
    log.info("council_tool call: web_verify(%s)", query[:100])
    admission = admit_tool("web_verify")
    prefix = tool_result_prefix(admission)
    if not admission.admitted:
        log.warning("web_verify refused by capability admission: %s", admission.short_reason())
        return _memo_put(
            key,
            prefix + "refused before external research provider invocation",
        )
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
        return _memo_put(
            key,
            prefix
            + f"(web_verify timed out after {_WEB_VERIFY_TIMEOUT_S:.0f}s — no external evidence gathered)",
        )
    return _memo_put(key, prefix + str(result.output)[:MAX_READ_CHARS])


async def qdrant_lookup(ctx: Any, query: str, collection: str = "affordances") -> str:
    """RAG search across ingested documents."""
    key = ("qdrant_lookup", query, collection)
    cached = _memo_get(key)
    if cached is not None:
        return cached
    log.info("council_tool call: qdrant_lookup(%s, %s)", query[:100], collection)
    admission = admit_tool("qdrant_lookup")
    prefix = tool_result_prefix(admission)
    if not admission.admitted:
        log.warning("qdrant_lookup refused by capability admission: %s", admission.short_reason())
        return _memo_put(key, prefix + "refused before local embedding/resource invocation")
    try:
        from shared.config import embed

        vector = embed(query)
        from qdrant_client import QdrantClient

        client = QdrantClient(host="localhost", port=6333)
        results = client.search(collection_name=collection, query_vector=vector, limit=3)
        if not results:
            return _memo_put(key, prefix + f"No results in {collection} for: {query}")
        return _memo_put(
            key,
            "\n---\n".join(
                prefix + f"score={r.score:.3f}: {r.payload.get('text', '')[:500]}" for r in results
            ),
        )
    except Exception as e:
        return _memo_put(key, prefix + f"Qdrant error: {e}")


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
