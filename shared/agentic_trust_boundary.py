"""Shared non-supply boundary for the agentic-trust evaluator surface.

This module deliberately has no registry or dispatch imports so request schemas,
inventory projections, receipt models, and launch adapters can apply the same
identity law without creating import cycles.
"""

from __future__ import annotations

import re

AGENTIC_TRUST_EVIDENCE_SURFACE_ID = "local_compute.agentic_trust_evaluator_surface"
AGENTIC_TRUST_EVIDENCE_RECEIPT_CLASS = "AgenticTrustEvidenceReceiptV1"
_UNTYPED_POLICY_EVIDENCE_NAMESPACES = frozenset({"digest", "hash", "run", "sha256"})


def normalize_supply_admission_identity(value: str) -> str:
    """Canonicalize an admitted-supply identity and one transport prefix."""

    if type(value) is not str:
        raise TypeError("supply admission identity must be exact text")
    normalized = value.strip().lower().replace("/", ".")
    for prefix in ("surface.", "route."):
        if normalized.startswith(prefix):
            return normalized.removeprefix(prefix)
    return normalized


def is_agentic_trust_evidence_surface_identity(value: str | None) -> bool:
    """Return whether *value* is the exact reserved evaluator observation identity.

    Children of the evaluator namespace are intentionally distinct surfaces and
    must pass through the ordinary intake/admission path.
    """

    if type(value) is not str:
        return False
    return normalize_supply_admission_identity(value) == AGENTIC_TRUST_EVIDENCE_SURFACE_ID


def is_agentic_trust_supply_evidence_reference(value: str | None) -> bool:
    """Return whether a supply-side value cites evaluator observation evidence."""

    if type(value) is not str:
        return False
    normalized = value.strip().lower().replace("/", ".")
    surface_marker = re.search(
        r"(?:^|[^a-z0-9_.-])(?:surface\.|route\.)?"
        r"local_compute\.agentic_trust_evaluator_surface(?:$|[^a-z0-9_.-])",
        normalized,
    )
    receipt_marker = re.search(
        r"(?:^|[^a-z0-9_-])(?:agentictrustevidencereceiptv1|"
        r"agentic-trust-evidence-receipt-v1)(?:$|[^a-z0-9_-])",
        normalized,
    )
    return surface_marker is not None or receipt_marker is not None


def is_syntactically_typed_policy_evidence_reference(value: str | None) -> bool:
    """Return whether a policy-bearing evidence reference retains namespace syntax.

    A bare digest or run identifier carries no machine-visible provenance type and
    must not gain freshness, confidence, equivalence, or authority effects merely
    by being copied into another receipt. A namespace is an asserted type boundary,
    not authentication: consumers that require authenticity must still resolve and
    verify the referenced artifact. This predicate cannot detect a digest that a
    caller deliberately relabels under another syntactically valid namespace.
    """

    if type(value) is not str:
        return False
    normalized = value.strip()
    namespace, separator, subject = normalized.partition(":")
    return bool(
        namespace
        and separator
        and subject
        and namespace.lower() not in _UNTYPED_POLICY_EVIDENCE_NAMESPACES
        and not any(character.isspace() for character in namespace)
        and not is_agentic_trust_supply_evidence_reference(normalized)
    )


def agentic_trust_supply_evidence_paths(value: object, path: str = "") -> tuple[str, ...]:
    """Locate observation-only values in supply-side reference-bearing fields."""

    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            reference_field = (
                key == "explicit_equivalence_records"
                or key.endswith("_ref")
                or key.endswith("_refs")
            )
            if reference_field:
                values = child if isinstance(child, (list, tuple)) else (child,)
                if any(is_agentic_trust_supply_evidence_reference(item) for item in values):
                    found.append(child_path)
            else:
                found.extend(agentic_trust_supply_evidence_paths(child, child_path))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            found.extend(agentic_trust_supply_evidence_paths(child, f"{path}[{index}]"))
    return tuple(found)
