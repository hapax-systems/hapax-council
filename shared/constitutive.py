"""Constitutive rules: explicit 'X counts as Y in context C' mappings (§4.3).

Constitutive rules assign institutional status to brute facts. A markdown file
on disk is a brute fact; its classification as 'profile-fact' or 'consented-data'
is institutional. Making these mappings explicit enables:
- Auditable governance chains (constitutive rule → regulative implication → enforcement)
- Defeasible logic: general rules can be overridden by defeating conditions
- Coherence checking: ensure all classifications link to regulative rules

Follows Governatori & Rotolo's defeasible logic formalization: each rule has
optional defeating conditions that override the base classification.
"""

from __future__ import annotations

import fnmatch
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

AXIOMS_PATH: Path = Path(
    os.environ.get(
        "AXIOMS_PATH",
        str(Path(__file__).resolve().parent.parent / "axioms"),
    )
)


@dataclass(frozen=True)
class DefeatCondition:
    """A condition that defeats (overrides) a constitutive rule.

    When a defeating condition matches, the base rule's classification is
    overridden — either replaced by a different institutional type or negated.
    """

    field: str  # frontmatter field to check
    value: str | None = None  # expected value (None = field must exist)
    override_type: str = ""  # replacement institutional type ("" = negation)
    description: str = ""

    def matches(self, frontmatter: dict[str, Any]) -> bool:
        """Check if this defeating condition is satisfied."""
        if self.field not in frontmatter:
            return False
        if self.value is None:
            return True  # field existence suffices
        return str(frontmatter[self.field]) == self.value


@dataclass(frozen=True)
class ConstitutiveRule:
    """A single 'X counts as Y in context C' mapping.

    match_type determines how the brute_pattern is evaluated:
    - 'path': fnmatch against file path
    - 'frontmatter': check frontmatter[field] == value
    - 'frontmatter_exists': check frontmatter field exists
    """

    id: str
    brute_pattern: str  # pattern for the brute fact
    institutional_type: str  # what it counts as
    context: str  # in what governance context
    match_type: str  # "path" | "frontmatter" | "frontmatter_exists"
    match_field: str = ""  # frontmatter field (for frontmatter match types)
    match_value: str = ""  # expected value (for frontmatter match type)
    defeating_conditions: tuple[DefeatCondition, ...] = ()
    linked_implications: tuple[str, ...] = ()  # implication IDs this rule feeds
    description: str = ""


@dataclass(frozen=True)
class InstitutionalFact:
    """Result of constitutive classification."""

    institutional_type: str
    context: str
    rule_id: str
    defeated: bool = False
    defeat_override: str = ""  # replacement type if defeated with override


class ConstitutiveRuleSet:
    """Evaluates constitutive rules against brute facts (files + frontmatter).

    Rules are evaluated in order. All matching rules produce InstitutionalFacts.
    Defeating conditions are checked for each match — if a defeat condition
    matches, the fact is marked as defeated (with optional type override).
    """

    __slots__ = ("_rules",)

    def __init__(self, rules: Sequence[ConstitutiveRule]) -> None:
        self._rules = tuple(rules)

    @property
    def rules(self) -> tuple[ConstitutiveRule, ...]:
        return self._rules

    def classify(
        self, path: str, frontmatter: dict[str, Any] | None = None
    ) -> list[InstitutionalFact]:
        """Classify a file into institutional facts.

        Args:
            path: File path (relative or absolute).
            frontmatter: Parsed YAML frontmatter from the file.

        Returns:
            List of InstitutionalFacts from all matching rules.
        """
        fm = frontmatter or {}
        results: list[InstitutionalFact] = []

        for rule in self._rules:
            if not self._matches(rule, path, fm):
                continue

            # Check defeating conditions
            defeated = False
            override = ""
            for dc in rule.defeating_conditions:
                if dc.matches(fm):
                    defeated = True
                    override = dc.override_type
                    break

            results.append(
                InstitutionalFact(
                    institutional_type=override
                    if (defeated and override)
                    else rule.institutional_type,
                    context=rule.context,
                    rule_id=rule.id,
                    defeated=defeated,
                    defeat_override=override,
                )
            )

        return results

    def rules_for_type(self, institutional_type: str) -> tuple[ConstitutiveRule, ...]:
        """Find all rules that produce a given institutional type."""
        return tuple(r for r in self._rules if r.institutional_type == institutional_type)

    def linked_implications(self, rule_id: str) -> tuple[str, ...]:
        """Get implication IDs linked to a specific rule."""
        for r in self._rules:
            if r.id == rule_id:
                return r.linked_implications
        return ()

    @staticmethod
    def _matches(rule: ConstitutiveRule, path: str, frontmatter: dict[str, Any]) -> bool:
        """Check if a rule matches the given brute fact."""
        if rule.match_type == "path":
            return fnmatch.fnmatch(path, rule.brute_pattern)
        if rule.match_type == "frontmatter":
            return str(frontmatter.get(rule.match_field, "")) == rule.match_value
        if rule.match_type == "frontmatter_exists":
            return rule.match_field in frontmatter
        return False

    @staticmethod
    def from_yaml(path: Path | None = None) -> ConstitutiveRuleSet:
        """Load constitutive rules from YAML file."""
        yaml_path = (path or AXIOMS_PATH) / "constitutive-rules.yaml"
        if not yaml_path.exists():
            log.warning("Constitutive rules not found: %s", yaml_path)
            return ConstitutiveRuleSet([])

        try:
            data = yaml.safe_load(yaml_path.read_text())
        except Exception as e:
            log.error("Failed to parse constitutive rules: %s", e)
            return ConstitutiveRuleSet([])

        rules: list[ConstitutiveRule] = []
        for entry in data.get("rules", []):
            defeats = []
            for dc in entry.get("defeating_conditions", []):
                defeats.append(
                    DefeatCondition(
                        field=dc["field"],
                        value=dc.get("value"),
                        override_type=dc.get("override_type", ""),
                        description=dc.get("description", ""),
                    )
                )

            rules.append(
                ConstitutiveRule(
                    id=entry["id"],
                    brute_pattern=entry.get("brute_pattern", ""),
                    institutional_type=entry["institutional_type"],
                    context=entry.get("context", ""),
                    match_type=entry.get("match_type", "path"),
                    match_field=entry.get("match_field", ""),
                    match_value=entry.get("match_value", ""),
                    defeating_conditions=tuple(defeats),
                    linked_implications=tuple(entry.get("linked_implications", [])),
                    description=entry.get("description", ""),
                )
            )

        return ConstitutiveRuleSet(rules)
