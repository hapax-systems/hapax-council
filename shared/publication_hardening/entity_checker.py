"""Attribution entity checker — flags product-company misattributions in text.

Loads a known-entities YAML registry (config/publication-hardening/known-entities.yaml)
and scans text for patterns like "Anthropic's Codex" or "Codex by Anthropic" that
contradict the registry. Codex belongs to OpenAI, not Anthropic.

Public API:
  - EntityRegistry:      loaded product→company lookup
  - AttributionFinding:  one misattribution finding
  - load_registry(path)  → EntityRegistry
  - check_attributions(text, registry) → list[AttributionFinding]
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

__all__ = [
    "AttributionFinding",
    "EntityRegistry",
    "check_attributions",
    "load_registry",
]

DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "config"
    / "publication-hardening"
    / "known-entities.yaml"
)


@dataclass(frozen=True)
class AttributionFinding:
    """One misattribution detected in text."""

    line: int
    col: int
    product: str
    claimed_company: str
    actual_company: str
    matched_text: str
    severity: str = "error"

    def __str__(self) -> str:
        return (
            f"line {self.line}, col {self.col}: "
            f"{self.product!r} attributed to {self.claimed_company!r} "
            f"but belongs to {self.actual_company!r} "
            f"(matched: {self.matched_text!r})"
        )


class EntityRegistry:
    """Bidirectional lookup: product name → canonical company name."""

    def __init__(
        self,
        product_to_company: dict[str, str],
        company_names: set[str],
    ) -> None:
        self._product_to_company = product_to_company
        self._company_names = company_names

    @property
    def product_to_company(self) -> dict[str, str]:
        return dict(self._product_to_company)

    @property
    def company_names(self) -> set[str]:
        return set(self._company_names)

    def lookup(self, product_name: str) -> str | None:
        return self._product_to_company.get(product_name.lower())

    def is_company(self, name: str) -> bool:
        return name.lower() in {c.lower() for c in self._company_names}


def load_registry(path: Path | str | None = None) -> EntityRegistry:
    """Load the known-entities YAML into an EntityRegistry."""
    p = Path(path) if path else DEFAULT_REGISTRY_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    companies = data.get("companies", {})

    product_to_company: dict[str, str] = {}
    company_names: set[str] = set()

    for company_name, company_data in companies.items():
        company_names.add(company_name)
        for product in company_data.get("products", []):
            canonical = product["name"].lower()
            product_to_company[canonical] = company_name
            for alias in product.get("aliases", []):
                product_to_company[alias.lower()] = company_name

    return EntityRegistry(product_to_company, company_names)


def _build_product_alternation(registry: EntityRegistry) -> str:
    """Build a regex alternation of all known product names, longest first."""
    names = sorted(registry.product_to_company.keys(), key=len, reverse=True)
    return "|".join(re.escape(n) for n in names)


def _build_company_alternation(registry: EntityRegistry) -> str:
    """Build a regex alternation of all known company names, longest first."""
    names = sorted(registry.company_names, key=len, reverse=True)
    return "|".join(re.escape(n) for n in names)


def check_attributions(
    text: str,
    registry: EntityRegistry | None = None,
    *,
    registry_path: Path | str | None = None,
) -> list[AttributionFinding]:
    """Scan text for product-company misattributions.

    Returns a list of AttributionFinding for each mismatch found.
    """
    if registry is None:
        registry = load_registry(registry_path)

    findings: list[AttributionFinding] = []
    seen_spans: set[tuple[int, int]] = set()

    line_offsets: list[int] = []
    offset = 0
    for line in text.split("\n"):
        line_offsets.append(offset)
        offset += len(line) + 1

    def _pos_for_offset(char_offset: int) -> tuple[int, int]:
        line_num = 1
        for i, _lo in enumerate(line_offsets):
            if i + 1 < len(line_offsets) and line_offsets[i + 1] > char_offset:
                line_num = i + 1
                break
            if i + 1 == len(line_offsets):
                line_num = i + 1
        col = char_offset - line_offsets[line_num - 1]
        return line_num, col

    def _overlaps(start: int, end: int) -> bool:
        return any(start < e and end > s for s, e in seen_spans)

    def _add_finding(
        span: tuple[int, int],
        product: str,
        claimed: str,
        actual: str,
        matched: str,
    ) -> None:
        if _overlaps(*span):
            return
        line, col = _pos_for_offset(span[0])
        seen_spans.add(span)
        findings.append(
            AttributionFinding(
                line=line,
                col=col,
                product=product,
                claimed_company=claimed,
                actual_company=actual,
                matched_text=matched,
            )
        )

    product_alt = _build_product_alternation(registry)
    company_alt = _build_company_alternation(registry)

    # Pattern 1: Company's Product (possessive)
    pat_possessive = re.compile(rf"\b({company_alt})'s\s+({product_alt})\b", re.IGNORECASE)
    for m in pat_possessive.finditer(text):
        company_claimed = m.group(1)
        product_matched = m.group(2)
        actual = registry.lookup(product_matched)
        if actual and actual.lower() != company_claimed.lower():
            _add_finding(m.span(), product_matched, company_claimed, actual, m.group(0))

    # Pattern 2: Company Product (adjacent, no possessive)
    pat_adjacent = re.compile(rf"\b({company_alt})\s+({product_alt})\b", re.IGNORECASE)
    for m in pat_adjacent.finditer(text):
        company_claimed = m.group(1)
        product_matched = m.group(2)
        actual = registry.lookup(product_matched)
        if actual and actual.lower() != company_claimed.lower():
            _add_finding(m.span(), product_matched, company_claimed, actual, m.group(0))

    # Pattern 3: Product by/from Company
    pat_by_from = re.compile(rf"\b({product_alt})\s+(?:by|from)\s+({company_alt})\b", re.IGNORECASE)
    for m in pat_by_from.finditer(text):
        product_matched = m.group(1)
        company_claimed = m.group(2)
        actual = registry.lookup(product_matched)
        if actual and actual.lower() != company_claimed.lower():
            _add_finding(m.span(), product_matched, company_claimed, actual, m.group(0))

    findings.sort(key=lambda f: (f.line, f.col))
    return findings
