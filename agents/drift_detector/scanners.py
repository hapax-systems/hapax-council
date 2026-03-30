"""Deterministic pre-LLM scanners for axiom violations, sufficiency, and memory."""

from __future__ import annotations

import logging

from opentelemetry import trace

from .config import HAPAX_HOME
from .docs import HAPAX_REPO_DIRS

# Re-export freshness checks for backward compatibility
from .freshness import check_doc_freshness as check_doc_freshness  # noqa: F401
from .freshness import check_screen_context_drift as check_screen_context_drift  # noqa: F401
from .models import DriftItem

log = logging.getLogger("drift_detector")
_tracer = trace.get_tracer(__name__)


def scan_axiom_violations() -> list[DriftItem]:
    """Deterministic pre-LLM scan: run T0 patterns against code repos.

    Returns DriftItems for any structural violations found.
    """
    with _tracer.start_as_current_span("drift.scan_axiom_violations"):
        from .axiom_patterns import load_t0_patterns, scan_directory

        patterns = load_t0_patterns()
        if not patterns:
            return []

        home = str(HAPAX_HOME)
        violations: list[DriftItem] = []

        for repo in HAPAX_REPO_DIRS:
            if not repo.exists():
                continue
            for match in scan_directory(repo, patterns):
                rel_path = match.file.replace(home, "~")
                violations.append(
                    DriftItem(
                        severity="high",
                        category="axiom-violation",
                        doc_file=rel_path,
                        doc_claim=f"T0 pattern match at line {match.line}",
                        reality=f"Code contains: {match.content}",
                        suggestion=f"Remove or refactor: {rel_path}:{match.line}",
                    )
                )

        span = trace.get_current_span()
        span.set_attribute("drift.violation_count", len(violations))
        return violations


def scan_sufficiency_gaps() -> list[DriftItem]:
    """Run sufficiency probes and convert failures to DriftItems."""
    with _tracer.start_as_current_span("drift.scan_sufficiency_gaps"):
        try:
            from .sufficiency_probes import run_probes
        except ImportError:
            return []

        results = run_probes()
        items: list[DriftItem] = []

        for r in results:
            if r.met:
                continue

            probe = next(
                (
                    p
                    for p in __import__("shared.sufficiency_probes", fromlist=["PROBES"]).PROBES
                    if p.id == r.probe_id
                ),
                None,
            )
            if probe:
                severity = {"T0": "high", "T1": "medium", "T2": "low"}.get(
                    _get_implication_tier(probe.implication_id), "low"
                )
            else:
                severity = "low"

            items.append(
                DriftItem(
                    severity=severity,
                    category="axiom-sufficiency-gap",
                    doc_file=f"probe:{r.probe_id}",
                    doc_claim=probe.question if probe else r.probe_id,
                    reality=r.evidence,
                    suggestion=f"Address sufficiency gap: {r.evidence}",
                )
            )

        return items


def _get_implication_tier(impl_id: str) -> str:
    """Look up the tier for an implication ID."""
    from .axiom_registry import load_implications

    if impl_id.startswith("ex-"):
        axiom_id = "executive_function"
    elif impl_id.startswith("mg-"):
        axiom_id = "management_governance"
    elif impl_id.startswith("cb-"):
        axiom_id = "corporate_boundary"
    else:
        axiom_id = "single_user"
    for impl in load_implications(axiom_id):
        if impl.id == impl_id:
            return impl.tier
    return "T2"


def check_project_memory() -> list[DriftItem]:
    """Check that all hapax repos have a ## Project Memory section in CLAUDE.md."""
    with _tracer.start_as_current_span("drift.check_project_memory"):
        items: list[DriftItem] = []
        home = str(HAPAX_HOME)

        for repo_dir in HAPAX_REPO_DIRS:
            if not repo_dir.is_dir():
                continue

            claude_md = repo_dir / "CLAUDE.md"
            short_path = str(repo_dir).replace(home, "~")

            if not claude_md.is_file():
                items.append(
                    DriftItem(
                        severity="medium",
                        category="missing_project_memory",
                        doc_file=f"{short_path}/CLAUDE.md",
                        doc_claim="File does not exist",
                        reality="All hapax repos must have a CLAUDE.md with ## Project Memory section",
                        suggestion=f"Create {short_path}/CLAUDE.md with a ## Project Memory section",
                    )
                )
                continue

            content = claude_md.read_text(errors="replace")
            if "## Project Memory" not in content:
                items.append(
                    DriftItem(
                        severity="medium",
                        category="missing_project_memory",
                        doc_file=f"{short_path}/CLAUDE.md",
                        doc_claim="No ## Project Memory section found",
                        reality="All hapax repos must have a ## Project Memory section for cross-session learning",
                        suggestion=f"Add a ## Project Memory section to {short_path}/CLAUDE.md with stable patterns and conventions",
                    )
                )

        return items
