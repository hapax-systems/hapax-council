"""Append-only journal for research artifacts.

Closes the witness gap that makes the `research_instrument_mesh` braid
rail compute to zero (local 2026-05-04 audit, leverage-rank-9 finding).
The braid runner reads ``~/hapax-state/research/registry.jsonl`` (per
``scripts/braided_value_snapshot_runner.py``'s ``research_registry``
WitnessSpec, family ``research_instrument_mesh``); when the file is
missing or stale (>7 days), the rail short-circuits to braid_score=0.

This module owns the write path. It is INDEPENDENT of LRR Phase 1's
``shared.research_registry_schema`` (which models per-condition YAML
files at ``~/hapax-state/research-registry/<condition_id>/``). The two
schemas live side-by-side because they describe different artefacts at
different cadences:

- LRR per-condition YAML — research-condition lifecycle (open, close,
  freeze, sibling chain), ~1-2 entries per week, manually curated.
- This module — every research artefact's existence (specs, plans,
  research drops, audits, voice-grounding state, Bayesian validation
  outcomes), idempotent registration, daemon-emitted at 6h cadence.

JSONL append semantics: each line is a self-contained JSON object;
appends are POSIX-atomic for line writes <PIPE_BUF (4096 bytes on
Linux), so concurrent producers do not interleave bytes. Caller is
responsible for dedup — ``find_entry()`` provides existence check by
``entry_id`` so the scanner can skip already-registered artefacts.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Default registry path — matches the WitnessSpec in
# ``scripts/braided_value_snapshot_runner.py:default_witness_specs()``.
DEFAULT_REGISTRY_PATH: Path = Path.home() / "hapax-state" / "research" / "registry.jsonl"

# Bytewise read chunk size for sha256 hashing of large markdown files.
HASH_CHUNK_BYTES: int = 65536

# Allowed kinds for the registry. Each kind maps to a canonical scan
# root in the producer CLI; see ``scripts/research-registry-emit.py``.
EntryKind = Literal[
    "spec",
    "plan",
    "research-drop",
    "audit",
    "voice-grounding",
    "bayesian-validation",
]

# entry_id regex: ``<kind>-<sha256-prefix-12>``. The kind prefix gives
# operators a quick visual sort; the sha256 prefix is the unique key
# (collision-free for any realistic registry size).
_ENTRY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]+-[0-9a-f]{12}$")


class ResearchRegistryEntry(BaseModel):
    """One journaled research artefact.

    Schema is deliberately small and stable: artefact identity
    (``entry_id``, ``sha256``), provenance (``source_path``,
    ``byte_size``), and timestamps. Avoids embedding the artefact body
    or volatile metadata so the registry stays append-only and
    diff-friendly.

    Strict pydantic validation (``extra="forbid"``) so a producer
    misspelling a field fails at write time rather than silently
    corrupting the journal.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: str = Field(..., pattern=_ENTRY_ID_RE.pattern, min_length=1)
    kind: EntryKind
    title: str = Field(..., min_length=1)
    source_path: str = Field(..., min_length=1)
    registered_at: datetime
    byte_size: int = Field(..., ge=0)
    sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    tags: list[str] = Field(default_factory=list)


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def compute_sha256(path: Path) -> str:
    """Hash a file's bytes with SHA-256, streaming in 64KB chunks.

    Used for both ``sha256`` (the canonical artefact identity) and
    ``entry_id`` (which embeds the first 12 hex chars of sha256).
    """

    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(HASH_CHUNK_BYTES)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def derive_entry_id(kind: EntryKind, sha256: str) -> str:
    """Compose the deterministic ``entry_id`` for an artefact.

    Format: ``<kind>-<sha256[:12]>``. Same artefact bytes => same id, so
    re-registering after content edits writes a fresh entry rather than
    silently overwriting. (Append-only contract per the audit's stance:
    artefact churn is itself research signal.)
    """

    return f"{kind}-{sha256[:12]}"


def derive_title(source_path: Path) -> str:
    """Read the first H1 (``# Title``) line of a markdown source file.

    Falls back to the file stem if no H1 found in the first 50 lines.
    Keeps the journal human-grep-friendly without parsing full
    markdown.
    """

    try:
        with source_path.open("r", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= 50:
                    break
                stripped = line.strip()
                if stripped.startswith("# "):
                    return stripped.removeprefix("# ").strip()
    except OSError:
        pass
    return source_path.stem


def build_entry(
    source_path: Path,
    *,
    kind: EntryKind,
    repo_root: Path | None = None,
    tags: list[str] | None = None,
    now: datetime | None = None,
) -> ResearchRegistryEntry:
    """Build an entry for ``source_path`` with default-derived fields.

    ``repo_root`` lets the producer record a repo-relative path so the
    journal stays portable across worktrees. When None, falls back to
    the absolute path string.
    """

    sha = compute_sha256(source_path)
    entry_id = derive_entry_id(kind, sha)
    if repo_root is not None:
        try:
            relative = source_path.resolve().relative_to(repo_root.resolve())
            source_str = str(relative)
        except ValueError:
            source_str = str(source_path.resolve())
    else:
        source_str = str(source_path.resolve())
    return ResearchRegistryEntry(
        entry_id=entry_id,
        kind=kind,
        title=derive_title(source_path),
        source_path=source_str,
        registered_at=now if now is not None else utc_now(),
        byte_size=source_path.stat().st_size,
        sha256=sha,
        tags=list(tags or []),
    )


def append_entry(entry: ResearchRegistryEntry, registry_path: Path) -> None:
    """Append one entry as a single JSONL line.

    Atomicity: jsonl writes <PIPE_BUF (4096 bytes on Linux) under
    ``O_APPEND`` are POSIX-atomic — concurrent producers cannot
    interleave bytes within a single write. Each entry serializes well
    under that bound (typical ~400 bytes with default fields). For
    larger custom payloads, callers should switch to a flock pattern;
    not needed for the producer's current scope.
    """

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    line = entry.model_dump_json() + "\n"
    with registry_path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def read_entries(registry_path: Path) -> Iterator[ResearchRegistryEntry]:
    """Stream entries from the JSONL journal, skipping malformed lines.

    Resilient by design — a single corrupted line cannot block the
    rest of the journal from being read. Validates each line through
    the pydantic schema so consumers get fully-typed objects.
    """

    if not registry_path.exists():
        return
    with registry_path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            try:
                yield ResearchRegistryEntry.model_validate(payload)
            except (ValueError, TypeError):
                continue


def known_entry_ids(registry_path: Path) -> set[str]:
    """Load all known ``entry_id`` values for fast scanner-side dedup.

    Bulk variant of ``find_entry`` — O(N) read, O(1) membership lookup.
    Preferable when the scanner is about to consider many candidates.
    """

    return {entry.entry_id for entry in read_entries(registry_path)}
