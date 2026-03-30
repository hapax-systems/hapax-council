"""Sufficiency probe framework — types, registry, and runner.

Probe implementations are in probes_*.py modules.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

log = logging.getLogger(__name__)


@dataclass
class SufficiencyProbe:
    id: str
    axiom_id: str
    implication_id: str
    level: str  # "component" | "subsystem" | "system"
    question: str
    check: Callable[[], tuple[bool, str]]  # (met, evidence)


@dataclass
class ProbeResult:
    probe_id: str
    met: bool
    evidence: str
    timestamp: str


# ── Scope coverage probe (depends only on base types) ───────────────────────


def _check_scope_coverage() -> tuple[bool, str]:
    """Check that sufficiency implications with enumerated scope have coverage entries."""
    from .axiom_registry import load_axioms, load_implications

    axioms = load_axioms()
    problems: list[str] = []
    checked = 0

    for axiom in axioms:
        for impl in load_implications(axiom.id):
            if impl.mode != "sufficiency":
                continue
            if impl.tier not in ("T0", "T1"):
                continue

            checked += 1

            if impl.scope is None:
                problems.append(f"{impl.id}: T0/T1 sufficiency implication has no scope")
                continue

            if impl.scope.type == "enumerated":
                if not impl.scope.items:
                    problems.append(f"{impl.id}: enumerated scope has no items")

    if checked == 0:
        return True, "no T0/T1 sufficiency implications to check"

    if not problems:
        return True, f"all {checked} T0/T1 sufficiency implications have valid scope"
    return False, f"{len(problems)} issue(s): {'; '.join(problems[:5])}"


# ── Probe registry (aggregated from all probe modules) ──────────────────────

PROBES: list[SufficiencyProbe] = [
    SufficiencyProbe(
        id="probe-scope-coverage-001",
        axiom_id="management_governance",
        implication_id="mg-cadence-001",
        level="system",
        question="Do T0/T1 sufficiency implications have valid enumerable scope?",
        check=_check_scope_coverage,
    ),
]


def _load_all_probes() -> None:
    """Import and register all probe modules."""
    from .probes_alerting import ALERTING_PROBES
    from .probes_boundary import BOUNDARY_PROBES
    from .probes_coverage import COVERAGE_PROBES
    from .probes_deliberation import DELIBERATION_PROBES
    from .probes_executive import EXECUTIVE_PROBES
    from .probes_runtime import RUNTIME_PROBES
    from .probes_single_user import SINGLE_USER_PROBES
    from .probes_skill import SKILL_PROBES

    PROBES.extend(EXECUTIVE_PROBES)
    PROBES.extend(ALERTING_PROBES)
    PROBES.extend(SINGLE_USER_PROBES)
    PROBES.extend(BOUNDARY_PROBES)
    PROBES.extend(DELIBERATION_PROBES)
    PROBES.extend(SKILL_PROBES)
    PROBES.extend(RUNTIME_PROBES)
    PROBES.extend(COVERAGE_PROBES)


_load_all_probes()


def run_probes(*, axiom_id: str = "", level: str = "") -> list[ProbeResult]:
    """Run all sufficiency probes and return results."""
    probes = PROBES
    if axiom_id:
        probes = [p for p in probes if p.axiom_id == axiom_id]
    if level:
        probes = [p for p in probes if p.level == level]

    results: list[ProbeResult] = []
    now = datetime.now(UTC).isoformat()

    for probe in probes:
        try:
            met, evidence = probe.check()
        except Exception as e:
            met = False
            evidence = f"probe error: {e}"
            log.warning("Probe %s failed: %s", probe.id, e)

        results.append(
            ProbeResult(
                probe_id=probe.id,
                met=met,
                evidence=evidence,
                timestamp=now,
            )
        )

    return results
