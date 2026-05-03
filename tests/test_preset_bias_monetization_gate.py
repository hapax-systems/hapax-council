"""Tests for cc-task preset-bias-similarity-recruit-trace.

Pins the gate behavior that broke the director's preset.bias recruitment
loop on 2026-05-02. Director impingements with intent_family="preset.bias"
embed the narrative, retrieve fx.family.* candidates from Qdrant, and
must pass the MonetizationRiskGate.

The trace investigation found that the catalog source (compositional_affordances.py)
correctly declares fx.family.* with monetization_risk='none' + public_capable=True,
but the live Qdrant `affordances` collection had stale payloads predating those
fields — every fx.family.* candidate returned with monetization_risk=None,
which the gate's _public_or_monetizable() coerced to 'unknown' and blocked
because medium='visual' is in _PUBLIC_MEDIA. 176 of 188 preset.bias attempts
in the most recent 10000-trace window dropped at monetization_filter_empty.

Fix: re-seed via scripts/seed-compositional-affordances.py (operational, idempotent).
This test pins the gate's allow-vs-block contract for the post-seed payload
shape so a future regression that drops the monetization_risk field from
the seeder is caught at CI time, not when 5000 dispatch-trace records have
piled up in production with intent_family entries dropping silently.
"""

from __future__ import annotations

from shared.affordance import SelectionCandidate
from shared.compositional_affordances import COMPOSITIONAL_CAPABILITIES
from shared.governance.monetization_safety import GATE


def _payload_from_record(record) -> dict:
    """Build a Qdrant-shaped payload dict from a CapabilityRecord.

    Mirrors the shape that AffordancePipeline.index_capability writes —
    every field the gate consults must be present so the in-memory
    candidate matches what live retrieval returns from a freshly-seeded
    Qdrant collection.
    """
    op = record.operational
    return {
        "capability_name": record.name,
        "description": record.description,
        "daemon": record.daemon,
        "requires_gpu": op.requires_gpu,
        "latency_class": op.latency_class,
        "consent_required": op.consent_required,
        "priority_floor": op.priority_floor,
        "medium": op.medium,
        "public_capable": op.public_capable,
        "monetization_risk": op.monetization_risk,
        "risk_reason": op.risk_reason,
        "content_risk": op.content_risk,
        "content_risk_reason": op.content_risk_reason,
    }


def _fx_family_records():
    return [r for r in COMPOSITIONAL_CAPABILITIES if r.name.startswith("fx.family.")]


class TestFxFamilyCatalogContract:
    """The catalog source itself must keep the governance fields populated.

    If a future commit drops monetization_risk or public_capable on any
    fx.family.* registration, the seeder writes a stale-shape payload to
    Qdrant and the gate fails closed silently. Pin the source contract
    so that regression is caught before the seed step runs.
    """

    def test_fx_family_records_exist(self) -> None:
        records = _fx_family_records()
        assert len(records) >= 4, (
            f"expected ≥4 fx.family.* registrations in COMPOSITIONAL_CAPABILITIES, "
            f"got {len(records)}; the preset.bias dispatcher targets this namespace"
        )

    def test_fx_family_records_declare_monetization_risk(self) -> None:
        for record in _fx_family_records():
            assert record.operational.monetization_risk in (
                "none",
                "low",
            ), (
                f"{record.name} has monetization_risk="
                f"{record.operational.monetization_risk!r}; the catalog must declare "
                f"a non-medium/non-high risk so the MonetizationRiskGate passes the "
                f"candidate through to the scoring stage"
            )

    def test_fx_family_records_declare_public_capable(self) -> None:
        for record in _fx_family_records():
            assert record.operational.public_capable is True, (
                f"{record.name}.public_capable={record.operational.public_capable!r}; "
                f"compositor presets are operator-authored visual modulations and "
                f"are public-capable by intent — declaring otherwise breaks the "
                f"intent_family routing that the director loop depends on"
            )


class TestFxFamilyMonetizationGatePassesAll:
    """Gate behavior pin — every fx.family.* candidate built from the live
    catalog must be allowed by the monetization gate, with the live payload
    shape that AffordancePipeline.index_capability writes to Qdrant.

    This is the contract the seeder must preserve. Any future change that
    drops or renames a payload field consulted by _public_or_monetizable()
    breaks this test deterministically.
    """

    def test_every_fx_family_capability_passes_the_gate(self) -> None:
        for record in _fx_family_records():
            payload = _payload_from_record(record)
            candidate = SelectionCandidate(
                capability_name=record.name,
                similarity=0.5,
                payload=payload,
            )
            assessment = GATE.assess(candidate)
            assert assessment.allowed, (
                f"{record.name} blocked by MonetizationRiskGate: "
                f"risk={assessment.risk!r}, reason={assessment.reason!r}. "
                f"The director loop emits compositional_impingements with "
                f"intent_family='preset.bias' that route here; if any candidate "
                f"is blocked the entire intent family drops at "
                f"monetization_filter_empty and the operator's compositor never "
                f"reacts to narrative cues."
            )


class TestStaleQdrantPayloadStillFailsClosed:
    """Negative pin — the gate's fail-closed-on-missing-fields behavior must
    remain in force. The fix is to keep the SEEDER current with the catalog,
    not to relax the gate. If anyone ever loosens _public_or_monetizable(),
    stale Qdrant payloads silently start passing high-risk content.
    """

    def test_missing_monetization_risk_with_visual_medium_is_blocked(self) -> None:
        """The exact pre-reseed shape observed on 2026-05-02 must still fail closed."""
        stale_payload = {
            "capability_name": "fx.family.audio-reactive",
            "description": "stale-payload sentinel",
            "daemon": "studio_compositor",
            "requires_gpu": True,
            "latency_class": "fast",
            "consent_required": False,
            "priority_floor": 0,
            "medium": "visual",
            # NOTE: deliberately omitting monetization_risk, public_capable,
            # content_risk to mirror the stale-Qdrant shape that triggered
            # the dispatch-trace dropout.
        }
        candidate = SelectionCandidate(
            capability_name="fx.family.audio-reactive",
            similarity=0.5,
            payload=stale_payload,
        )
        assessment = GATE.assess(candidate)
        assert not assessment.allowed, (
            "stale-Qdrant-shape candidate (missing monetization_risk + public_capable, "
            "medium='visual') must remain blocked by the gate's fail-closed branch; "
            "the fix is to keep the seeder current, not to relax the gate"
        )
