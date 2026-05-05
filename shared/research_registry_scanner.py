"""Scan canonical research-artefact dirs and emit registry entries.

Companion to ``shared.research_registry_writer``. Walks a configured
set of source roots, computes ``ResearchRegistryEntry`` instances for
each candidate file, and skips entries already present in the journal
(dedup by ``entry_id``, which is content-hash derived). Emit cadence
is owned by the scanner caller — the producer CLI runs every 6 hours
under ``hapax-research-registry-producer.timer``.

Source-root taxonomy maps each kind to a canonical workspace path:

| kind               | root pattern                              | rationale |
|--------------------|-------------------------------------------|-----------|
| spec               | ``docs/superpowers/specs/*.md``           | Designed-but-not-yet-implemented synthesis docs (LRR rotation policy). |
| plan               | ``docs/superpowers/plans/*.md``           | Phased implementation plans. |
| research-drop      | ``docs/research/*.md``                    | Research artefacts (drops, surveys, framework reviews). |
| audit              | ``docs/audits/*.md``                      | Cross-codebase audits and rot reports. |
| voice-grounding    | ``agents/hapax_daimonion/proofs/*.md``    | Voice-grounding research-state continuity files. |
| bayesian-validation| ``docs/research/bayesian-validation/*.md``| Bayesian model validation outcomes. |

Roots are operator-tunable: ``ScanRoot.from_default_layout()`` returns
the canonical mapping; callers can pass custom roots for tests or
narrowed scans.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from shared.research_registry_writer import (
    DEFAULT_REGISTRY_PATH,
    EntryKind,
    ResearchRegistryEntry,
    append_entry,
    build_entry,
    known_entry_ids,
)


@dataclass(frozen=True)
class ScanRoot:
    """One scannable source root.

    Each root pairs a path with a ``kind`` (registry classification)
    and a glob (which files inside the root count). Glob is shallow by
    default — flat dirs like ``docs/research/`` shouldn't recurse into
    nested structure unless configured.
    """

    path: Path
    kind: EntryKind
    glob: str = "*.md"
    tags: tuple[str, ...] = ()

    def discover(self) -> Iterable[Path]:
        """Yield candidate files matching this root's glob.

        Returns empty when the root path doesn't exist (workspace may
        not have one of the canonical dirs yet — silent no-op rather
        than scanner crash).
        """

        if not self.path.exists():
            return
        yield from sorted(self.path.glob(self.glob))


@dataclass(frozen=True)
class ScanResult:
    """Per-scan summary returned by ``scan_and_register``.

    Fields:
    - ``scanned`` — number of files inspected across all roots.
    - ``new_entries`` — number of entries actually appended (after dedup).
    - ``skipped_existing`` — number of files matching an entry already
      in the journal (dedup hits).
    - ``errors`` — per-path error messages (e.g. read failures).
    - ``new_entry_ids`` — the entry_ids appended this pass; lets
      callers verify what landed.
    """

    scanned: int = 0
    new_entries: int = 0
    skipped_existing: int = 0
    errors: list[str] = field(default_factory=list)
    new_entry_ids: list[str] = field(default_factory=list)


def default_scan_roots(repo_root: Path) -> tuple[ScanRoot, ...]:
    """Canonical scan-root layout — tied to the council repo structure.

    Mapping is conservative: only roots that exist as established
    publishing surfaces today. The producer can grow this list as new
    research-artefact families come online.
    """

    return (
        ScanRoot(repo_root / "docs" / "superpowers" / "specs", "spec"),
        ScanRoot(repo_root / "docs" / "superpowers" / "plans", "plan"),
        ScanRoot(repo_root / "docs" / "research", "research-drop"),
        ScanRoot(repo_root / "docs" / "audits", "audit"),
        ScanRoot(
            repo_root / "agents" / "hapax_daimonion" / "proofs",
            "voice-grounding",
        ),
        ScanRoot(
            repo_root / "docs" / "research" / "bayesian-validation",
            "bayesian-validation",
        ),
    )


def scan_and_register(
    roots: Iterable[ScanRoot],
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    repo_root: Path | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
) -> ScanResult:
    """Walk ``roots``, compute entries, append novel ones to the journal.

    Dedup is content-hash-based via ``entry_id``: same bytes => same
    id => skip. A file edit changes its sha256 => new entry_id => the
    journal grows by one row, which is the desired append-only
    semantics (artefact churn is research signal, not noise).

    ``dry_run`` computes entries but does not write — used by the
    producer CLI's dry-run mode and by tests that want to inspect
    candidate entries without mutating the journal.
    """

    known = known_entry_ids(registry_path) if registry_path.exists() else set()
    result_scanned = 0
    result_new = 0
    result_skipped = 0
    errors: list[str] = []
    new_ids: list[str] = []

    for root in roots:
        for candidate in root.discover():
            result_scanned += 1
            try:
                entry: ResearchRegistryEntry = build_entry(
                    candidate,
                    kind=root.kind,
                    repo_root=repo_root,
                    tags=list(root.tags),
                    now=now,
                )
            except OSError as exc:
                errors.append(f"{candidate}: {exc.__class__.__name__}: {exc}")
                continue
            if entry.entry_id in known:
                result_skipped += 1
                continue
            if not dry_run:
                append_entry(entry, registry_path)
            known.add(entry.entry_id)
            result_new += 1
            new_ids.append(entry.entry_id)

    return ScanResult(
        scanned=result_scanned,
        new_entries=result_new,
        skipped_existing=result_skipped,
        errors=errors,
        new_entry_ids=new_ids,
    )
