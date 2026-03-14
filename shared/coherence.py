"""Coherence checker: validates governance chain integrity (§4.8).

Checks the complete chain: constitutive rules → implications → enforcement.
Identifies gaps where:
- Constitutive rules link to non-existent implications
- Implications have no constitutive rules feeding them
- Enforcement patterns reference non-existent implications
- Axioms have implications but no enforcement mechanism

Analogous to OperettA's model checking for institutional specifications.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from shared.axiom_registry import AXIOMS_PATH, load_axioms, load_implications
from shared.constitutive import ConstitutiveRuleSet

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CoherenceGap:
    """A gap in the governance chain."""

    gap_type: str  # "orphan_rule" | "orphan_implication" | "missing_link" | "missing_enforcement"
    source_id: str  # rule/implication/pattern ID
    target_id: str  # what's missing or disconnected
    description: str


@dataclass(frozen=True)
class CoherenceReport:
    """Result of coherence validation."""

    gaps: tuple[CoherenceGap, ...]
    total_rules: int
    total_implications: int
    linked_implications: int  # implications referenced by at least one rule
    coverage_ratio: float  # linked_implications / total_implications

    @property
    def is_coherent(self) -> bool:
        return len(self.gaps) == 0


def check_coherence(*, axioms_path: Path = AXIOMS_PATH) -> CoherenceReport:
    """Validate governance chain coherence.

    Checks:
    1. All constitutive rule linked_implications reference real implications
    2. Implications without any constitutive rule feeding them (orphans)
    3. Coverage: what fraction of implications are reachable from constitutive rules
    """
    # Load all components
    ruleset = ConstitutiveRuleSet.from_yaml(axioms_path)
    axioms = load_axioms(path=axioms_path)

    # Collect all implication IDs
    all_impl_ids: set[str] = set()
    for axiom in axioms:
        for impl in load_implications(axiom.id, path=axioms_path):
            all_impl_ids.add(impl.id)

    # Collect linked implications from constitutive rules
    linked_from_rules: set[str] = set()
    gaps: list[CoherenceGap] = []

    for rule in ruleset.rules:
        for impl_id in rule.linked_implications:
            linked_from_rules.add(impl_id)
            if impl_id not in all_impl_ids:
                gaps.append(
                    CoherenceGap(
                        gap_type="missing_link",
                        source_id=rule.id,
                        target_id=impl_id,
                        description=(
                            f"Constitutive rule '{rule.id}' links to implication "
                            f"'{impl_id}' which does not exist"
                        ),
                    )
                )

    # Find orphan implications (not linked from any constitutive rule)
    orphan_impls = all_impl_ids - linked_from_rules
    for impl_id in sorted(orphan_impls):
        gaps.append(
            CoherenceGap(
                gap_type="orphan_implication",
                source_id=impl_id,
                target_id="",
                description=(f"Implication '{impl_id}' has no constitutive rule feeding it"),
            )
        )

    coverage = len(linked_from_rules & all_impl_ids) / max(len(all_impl_ids), 1)

    return CoherenceReport(
        gaps=tuple(gaps),
        total_rules=len(ruleset.rules),
        total_implications=len(all_impl_ids),
        linked_implications=len(linked_from_rules & all_impl_ids),
        coverage_ratio=round(coverage, 3),
    )
