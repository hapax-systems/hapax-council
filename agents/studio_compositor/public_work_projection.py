"""Bind an explicitly admitted public artifact to the existing Chronicle envelope.

Pure candidate projection: no store writes, admission issuance, runtime witness,
programme, device access or egress. The complete source policy and grounding result
travel together. The composed-frame registry's runtime requirements still apply
at release/egress; source eligibility is not a live-delivery claim.
"""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import math
from collections.abc import Mapping
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

from shared.aperture_registry import aperture_registry
from shared.chronicle import ChronicleEvent
from shared.governance.publication_allowlist import _grounding_denial_reason
from shared.research_vehicle_public_event import ResearchVehiclePublicEvent

APERTURE = "aperture:composed-livestream-frame"
SURFACE = "composed_livestream_frame"
WINDOW_SECONDS = 600.0
SOURCE = "public_work_projection"


@cache
def _validator(filename: str) -> Draft202012Validator:
    schema = Path(__file__).resolve().parents[2] / "schemas" / filename
    return Draft202012Validator(json.loads(schema.read_text()), format_checker=FormatChecker())


def _timestamp(value: str) -> float:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("explicit timezone required")
    return parsed.timestamp()


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and all(c.isprintable() for c in value)


def _public_url(value: Any) -> bool:
    if not _text(value):
        return False
    url = urlsplit(value)
    hostname = (url.hostname or "").rstrip(".").lower()
    if hostname.endswith((".local", ".localhost", ".internal")):
        return False
    try:
        if not ipaddress.ip_address(hostname).is_global:
            return False
    except ValueError:
        pass  # A DNS hostname; source/public-readback admission still belongs upstream.
    return bool(
        url.scheme == "https"
        and url.hostname
        and "." in url.hostname
        and not url.username
        and not url.password
        and not url.query
        and not url.fragment
        and not any(c.isspace() for c in value)
    )


def project_public_work(
    public_event: Mapping[str, Any], grounding_gate: Mapping[str, Any], *, observed_at: float
) -> ChronicleEvent | None:
    """Project only explicit frame-permitted artifact evidence; never grant that permit.

    Inputs are the existing RVPE and GroundingCommitmentGateResult contracts.
    The upstream grounding result must bind this exact source event and aperture
    in both its evidence and provenance. Unsupported requirements remain held.
    ``valid_time`` retains occurrence; ``ts`` and ``transaction_time`` record observation.
    """
    try:
        if isinstance(observed_at, bool) or not math.isfinite(observed_at):
            return None
        if not _validator("research-vehicle-public-event.schema.json").is_valid(public_event):
            return None
        if not _validator("grounding-commitment-gate.schema.json").is_valid(grounding_gate):
            return None
        event = ResearchVehiclePublicEvent.model_validate(public_event)
        gate = copy.deepcopy(dict(grounding_gate))
        policy = event.surface_policy
        # Naming a YouTube metadata surface is not composed-frame permission.
        if SURFACE not in policy.allowed_surfaces or SURFACE in policy.denied_surfaces:
            return None
        if (
            event.event_type != "publication.artifact"
            or event.privacy_class != "public_safe"
            or event.rights_class not in {"operator_original", "operator_controlled"}
            or not policy.claim_archive
            or policy.dry_run_reason is not None
            or policy.requires_human_review
            or policy.requires_audio_safe
            or policy.requires_egress_public_claim
            or policy.redaction_policy != "none"
        ):
            return None
        if (
            not event.provenance.token
            or not event.provenance.evidence_refs
            or not event.provenance.rights_basis
            or not event.source.evidence_ref
            or not _public_url(event.public_url)
        ):
            return None
        occurred = _timestamp(event.occurred_at)
        generated = _timestamp(event.provenance.generated_at)
        if not occurred <= generated <= observed_at:
            return None
        if aperture_registry().require(APERTURE).kind.value != SURFACE:
            return None
        if _grounding_denial_reason("publication.artifact", {"grounding_gate_result": gate}):
            return None
        claim = gate["claim"]
        digest = hashlib.sha256(
            json.dumps(
                event.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        refs = {
            f"ResearchVehiclePublicEvent:{event.event_id}",
            f"sha256:{digest}",
            APERTURE,
            event.source.evidence_ref,
        }
        if not (
            refs.issubset(claim["evidence_refs"])
            and refs.issubset(claim["provenance"]["source_refs"])
        ):
            return None
        result = gate["gate_result"]
        freshness = claim["freshness"]
        checked = _timestamp(freshness["checked_at"])
        evaluated = _timestamp(gate["evaluated_at"])
        ttl = freshness["ttl_s"]
        correction = claim["refusal_correction_path"]["correction_event_ref"]
        if (
            gate["public_private_mode"] != "public_live"
            or gate["infractions"]
            or result["blockers"]
            or result["unavailable_reasons"]
            or result["must_emit_refusal_artifact"]
            or result["must_emit_correction_artifact"]
            or claim["rights_state"] != event.rights_class
            or claim["privacy_state"] != event.privacy_class
            or claim["confidence"]["label"] not in {"low", "medium", "medium_high", "high"}
            or not _text(claim["claim_text"])
            or not _text(claim["uncertainty"])
            or not _public_url(correction)
            or freshness["status"] != "fresh"
            or isinstance(ttl, bool)
            or not isinstance(ttl, (int, float))
            or not math.isfinite(ttl)
            or not (0 <= observed_at - occurred <= min(ttl, WINDOW_SECONDS))
            or not (occurred <= checked <= evaluated <= observed_at)
            or not (0 <= observed_at - checked <= min(ttl, WINDOW_SECONDS))
        ):
            return None
        return ChronicleEvent(
            ts=observed_at,
            valid_time=occurred,
            transaction_time=observed_at,
            # No fabricated tracing witness: these remain diagnostic trace IDs.
            trace_id="0" * 32,
            span_id="0" * 16,
            parent_span_id=None,
            event_id=event.event_id,
            source=SOURCE,
            event_type=event.event_type,
            aperture_ref=APERTURE,
            public_scope="public",
            evidence_class="public_event",
            evidence_refs=tuple(sorted(refs)),
            payload={
                "salience": event.salience,
                "public_event": event.model_dump(mode="json"),
                "grounding_gate_result": gate,
            },
        )
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError, OSError):
        return None


def read_public_work(event: ChronicleEvent, *, now: float) -> ChronicleEvent | None:
    """Recheck the original policy at use; reject relabelled or mismatched envelopes."""
    try:
        projected = project_public_work(
            event.payload["public_event"], event.payload["grounding_gate_result"], observed_at=now
        )
        if projected is None:
            return None
        if (
            event.event_id != projected.event_id
            or event.source != SOURCE
            or event.event_type != projected.event_type
            or event.aperture_ref != APERTURE
            or event.public_scope != "public"
            or event.evidence_class != "public_event"
            or event.ts != event.transaction_time
            or event.valid_time != projected.valid_time
            or event.evidence_refs != projected.evidence_refs
            or event.payload != projected.payload
            or event.transaction_time is None
            or not (event.effective_valid_time <= event.ts <= now)
        ):
            return None
        return event
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
