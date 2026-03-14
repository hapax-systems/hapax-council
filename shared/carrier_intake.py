"""Carrier fact intake — parse and validate carrier facts from frontmatter.

Bridges the reactive engine (filesystem events) to the carrier registry
(in-memory cross-domain fact carrying). When a file with `carrier: true`
arrives, this module:

1. Parses the carrier fact from frontmatter (source_domain, value)
2. Extracts consent label and provenance via labeled_read (DD-12)
3. Validates consent via GovernorWrapper if a policy is provided
4. Offers the fact to the CarrierRegistry for the target principal
5. Returns a structured result for logging and audit

Implements DD-26: carrier-flagged filesystem events.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.carrier import CarrierFact, CarrierRegistry, DisplacementResult
from shared.consent_label import ConsentLabel
from shared.frontmatter import extract_consent_label, extract_provenance, parse_frontmatter
from shared.labeled import Labeled

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CarrierIntakeResult:
    """Outcome of processing a carrier-flagged file."""

    accepted: bool
    path: str
    principal_id: str
    source_domain: str
    displacement: DisplacementResult | None = None
    rejection_reason: str = ""


def parse_carrier_fact(
    path: Path,
    *,
    now: float | None = None,
) -> CarrierFact | None:
    """Parse a carrier fact from a frontmatter file.

    Expected frontmatter:
        carrier: true
        source_domain: "health_monitor"
        carrier_value: "resting HR elevated 3 days"
        consent_label: ...    (optional, DD-11 format)
        provenance: [...]     (optional, DD-20 format)

    Returns None if the file is not a valid carrier fact.
    """
    fm, body = parse_frontmatter(path)
    if not fm.get("carrier"):
        return None

    source_domain = fm.get("source_domain", "")
    if not source_domain:
        _log.warning("Carrier file %s missing source_domain", path)
        return None

    # The carried value: explicit carrier_value field, or the file body
    value: Any = fm.get("carrier_value", body.strip() or None)
    if value is None:
        _log.warning("Carrier file %s has no carrier_value or body", path)
        return None

    label = extract_consent_label(fm) or ConsentLabel.bottom()
    provenance = extract_provenance(fm)
    timestamp = now if now is not None else time.time()

    return CarrierFact(
        labeled=Labeled(value=value, label=label, provenance=provenance),
        source_domain=source_domain,
        observation_count=1,
        first_seen=timestamp,
        last_seen=timestamp,
    )


def intake_carrier_fact(
    path: Path,
    principal_id: str,
    registry: CarrierRegistry,
    *,
    required_label: ConsentLabel | None = None,
    now: float | None = None,
) -> CarrierIntakeResult:
    """Parse, validate, and register a carrier fact from a file.

    Args:
        path: Path to the carrier-flagged markdown file.
        principal_id: The principal receiving this carrier fact.
        registry: CarrierRegistry to offer the fact to.
        required_label: If provided, reject facts whose consent label
            cannot flow to this label (IFC enforcement at boundary).
        now: Timestamp override for testing.

    Returns:
        CarrierIntakeResult with acceptance/rejection details.
    """
    fact = parse_carrier_fact(path, now=now)
    if fact is None:
        return CarrierIntakeResult(
            accepted=False,
            path=str(path),
            principal_id=principal_id,
            source_domain="",
            rejection_reason="invalid carrier file",
        )

    # IFC boundary check: consent label must flow to required label
    if required_label is not None:
        if not fact.consent_label.can_flow_to(required_label):
            _log.info(
                "Carrier fact from %s rejected: consent label cannot flow to required label",
                path,
            )
            return CarrierIntakeResult(
                accepted=False,
                path=str(path),
                principal_id=principal_id,
                source_domain=fact.source_domain,
                rejection_reason="consent label flow violation",
            )

    # Offer to registry (handles capacity, displacement, dedup)
    try:
        result = registry.offer(principal_id, fact)
    except ValueError as e:
        return CarrierIntakeResult(
            accepted=False,
            path=str(path),
            principal_id=principal_id,
            source_domain=fact.source_domain,
            rejection_reason=str(e),
        )

    if result.inserted:
        _log.info(
            "Carrier fact accepted: domain=%s principal=%s reason=%s",
            fact.source_domain,
            principal_id,
            result.reason,
        )
        if result.displaced is not None:
            _log.info(
                "Displaced carrier fact: domain=%s obs_count=%d",
                result.displaced.source_domain,
                result.displaced.observation_count,
            )
    else:
        _log.debug(
            "Carrier fact rejected: domain=%s reason=%s",
            fact.source_domain,
            result.reason,
        )

    return CarrierIntakeResult(
        accepted=result.inserted,
        path=str(path),
        principal_id=principal_id,
        source_domain=fact.source_domain,
        displacement=result,
    )
