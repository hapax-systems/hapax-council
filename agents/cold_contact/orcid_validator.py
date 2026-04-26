"""ORCID public-API validator — Phase 1.

Per cc-task ``cold-contact-candidate-registry``. Validates each
:class:`agents.cold_contact.candidate_registry.CandidateEntry` against
the public ORCID API (no authentication required for read).

Endpoint: ``https://pub.orcid.org/v3.0/{orcid-id}/record``

Validation surface:
- 404 → entry's ORCID iD is invalid or revoked
- 200 + name match → OK
- 200 + name mismatch → operator-fixable mismatch flag
- network/transport failure → recordable, retryable

Mismatches are emitted as observable events; the validator NEVER
auto-fixes the YAML (per cc-task spec: "operator must update YAML").
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from prometheus_client import Counter

from agents.cold_contact.candidate_registry import CandidateEntry

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

ORCID_PUBLIC_API_BASE: str = "https://pub.orcid.org/v3.0"
"""Public ORCID API endpoint root. No auth required for read."""

ORCID_REQUEST_TIMEOUT_S: float = 30.0


class OrcidValidationOutcome(Enum):
    """Outcome categories for one validation pass.

    ``OK`` — name matches as configured in the registry.
    ``NAME_MISMATCH`` — ORCID record exists but the configured name
        differs from the canonical name returned by ORCID; operator
        update required.
    ``NOT_FOUND`` — 404 from ORCID; the iD is invalid or revoked.
    ``TRANSPORT_ERROR`` — network or HTTP-level failure; safe to retry
        on next validation pass.
    ``UNKNOWN`` — unexpected response payload; defensive bucket so
        downstream observers see something rather than nothing.
    """

    OK = "ok"
    NAME_MISMATCH = "name_mismatch"
    NOT_FOUND = "not_found"
    TRANSPORT_ERROR = "transport_error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ValidationResult:
    """One candidate's validation outcome.

    ``fetched_name`` is the canonical name returned by ORCID (when
    available); used by downstream observability to surface mismatches
    in the operator dashboard.
    """

    candidate_orcid: str
    outcome: OrcidValidationOutcome
    expected_name: str = ""
    fetched_name: str = ""
    error: str = ""


orcid_validation_failures_total = Counter(
    "hapax_cold_contact_orcid_validation_failures_total",
    "ORCID validation failures per candidate name + outcome.",
    ["candidate_name", "outcome"],
)


def validate_candidate(entry: CandidateEntry) -> ValidationResult:
    """Validate one ``CandidateEntry`` against the ORCID public API.

    Returns a :class:`ValidationResult` reflecting the outcome. Never
    raises — transport failures map to ``TRANSPORT_ERROR`` so the
    validator can be invoked in a daemon loop without try/except
    wrapping.
    """
    if requests is None:
        return ValidationResult(
            candidate_orcid=entry.orcid,
            outcome=OrcidValidationOutcome.TRANSPORT_ERROR,
            expected_name=entry.name,
            error="requests library not available",
        )

    url = f"{ORCID_PUBLIC_API_BASE}/{entry.orcid}/record"
    try:
        response = requests.get(
            url,
            headers={"Accept": "application/json"},
            timeout=ORCID_REQUEST_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        log.warning("orcid validation transport failure for %s: %s", entry.orcid, exc)
        orcid_validation_failures_total.labels(
            candidate_name=entry.name, outcome=OrcidValidationOutcome.TRANSPORT_ERROR.value
        ).inc()
        return ValidationResult(
            candidate_orcid=entry.orcid,
            outcome=OrcidValidationOutcome.TRANSPORT_ERROR,
            expected_name=entry.name,
            error=f"transport failure: {exc}",
        )

    if response.status_code == 404:
        orcid_validation_failures_total.labels(
            candidate_name=entry.name, outcome=OrcidValidationOutcome.NOT_FOUND.value
        ).inc()
        return ValidationResult(
            candidate_orcid=entry.orcid,
            outcome=OrcidValidationOutcome.NOT_FOUND,
            expected_name=entry.name,
        )

    if response.status_code != 200:
        return ValidationResult(
            candidate_orcid=entry.orcid,
            outcome=OrcidValidationOutcome.UNKNOWN,
            expected_name=entry.name,
            error=f"HTTP {response.status_code}",
        )

    try:
        data = response.json()
    except ValueError:
        return ValidationResult(
            candidate_orcid=entry.orcid,
            outcome=OrcidValidationOutcome.UNKNOWN,
            expected_name=entry.name,
            error="ORCID returned non-JSON body",
        )

    fetched_name = _extract_name(data)
    if not fetched_name:
        return ValidationResult(
            candidate_orcid=entry.orcid,
            outcome=OrcidValidationOutcome.UNKNOWN,
            expected_name=entry.name,
            error="ORCID record lacks person.name",
        )

    if _names_match(entry.name, fetched_name):
        return ValidationResult(
            candidate_orcid=entry.orcid,
            outcome=OrcidValidationOutcome.OK,
            expected_name=entry.name,
            fetched_name=fetched_name,
        )

    orcid_validation_failures_total.labels(
        candidate_name=entry.name,
        outcome=OrcidValidationOutcome.NAME_MISMATCH.value,
    ).inc()
    return ValidationResult(
        candidate_orcid=entry.orcid,
        outcome=OrcidValidationOutcome.NAME_MISMATCH,
        expected_name=entry.name,
        fetched_name=fetched_name,
    )


def _extract_name(data: dict) -> str:
    person = data.get("person") if isinstance(data, dict) else None
    if not isinstance(person, dict):
        return ""
    name = person.get("name")
    if not isinstance(name, dict):
        return ""
    given = (name.get("given-names") or {}).get("value", "")
    family = (name.get("family-name") or {}).get("value", "")
    return f"{given} {family}".strip()


def _names_match(expected: str, fetched: str) -> bool:
    """Compare names case-insensitively, ignoring whitespace differences."""
    return expected.strip().lower() == fetched.strip().lower()


__all__ = [
    "ORCID_PUBLIC_API_BASE",
    "ORCID_REQUEST_TIMEOUT_S",
    "OrcidValidationOutcome",
    "ValidationResult",
    "orcid_validation_failures_total",
    "validate_candidate",
]
