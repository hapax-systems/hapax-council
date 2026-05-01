"""Monetization readiness ledger.

Aggregates evidence from upstream feeders (audio-health, egress-state,
provenance kill-switch, public-event contract, etc.) and computes per
target-family readiness using the canonical
``conversion-target-readiness-threshold-matrix``. Output exposes
reasons + evidence refs (not just green/red) so a public-growth surface
that consumes the ledger has the same evidence chain the operator
would.

This module is intentionally narrow: it does NOT perform engagement,
revenue, or trend-driven upgrades. ``ConversionTargetReadinessMatrix``
already enforces the anti-overclaim policy; the ledger surfaces the
matrix's decisions plus their evidence so downstream surfaces never
need to construct their own ad-hoc readiness logic.

The ledger is the single read-side gate. Public-growth surfaces query
this module before allowing any monetization, support-prompt,
artifact-release, or YouTube/VOD packaging action.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from shared.conversion_target_readiness import (
    PUBLIC_READINESS_STATES,
    REQUIRED_GATE_DIMENSIONS,
    ConversionReadinessDecision,
    ConversionTargetReadinessMatrix,
    GateDimension,
    ReadinessState,
    TargetFamilyId,
    decide_readiness_state,
    load_conversion_target_readiness_matrix,
)

# State ladder used when the caller doesn't pin a specific requested
# state per family. We try each non-terminal state from most-public to
# least and return the highest one that the matrix allows.
_PROBE_STATES: tuple[ReadinessState, ...] = (
    "public-monetizable",
    "public-live",
    "public-archive",
    "dry-run",
    "private-evidence",
)


class LedgerModel(BaseModel):
    """Frozen-by-default pydantic base, mirrors the matrix module's idiom."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class GateDimensionEvidence(LedgerModel):
    """Evidence for one gate dimension at snapshot time.

    ``satisfied`` is the boolean the matrix consumes;
    ``evidence_refs`` are operator-visible artifact paths or URLs that
    back the satisfaction claim, and ``operator_visible_reason`` is a
    short human-readable line for the dashboard. ``severity`` is
    optional and lets feeders distinguish a known-fail (block downstream
    public/money states) from a known-degraded (allow private-evidence
    but not public-live).
    """

    dimension: GateDimension
    satisfied: bool
    evidence_refs: tuple[str, ...] = Field(default=(), min_length=0)
    operator_visible_reason: str = Field(min_length=1)
    severity: str | None = None


class MonetizationReadinessSnapshot(LedgerModel):
    """Aggregate evidence snapshot at a point in time.

    Construct one of these from feeder outputs (``BroadcastAudioHealth``,
    ``LivestreamEgressState``, the public-event contract resolver, etc.);
    the ledger reads only this snapshot. There is no implicit feeder
    coupling, so the ledger is testable without the full runtime.
    """

    captured_at: datetime
    evidence: Mapping[GateDimension, GateDimensionEvidence]
    snapshot_source: str = Field(min_length=1)

    @classmethod
    def empty(cls, *, captured_at: datetime | None = None, source: str = "empty") -> Self:
        """A snapshot where no gate dimensions are satisfied.

        Useful as a fail-closed default before any feeder reports in.
        """

        when = captured_at or datetime.now(tz=UTC)
        evidence = {
            dim: GateDimensionEvidence(
                dimension=dim,
                satisfied=False,
                evidence_refs=(),
                operator_visible_reason="no evidence reported",
            )
            for dim in REQUIRED_GATE_DIMENSIONS
        }
        return cls(captured_at=when, evidence=evidence, snapshot_source=source)

    def satisfied_dimensions(self) -> frozenset[GateDimension]:
        """Return the subset of dimensions whose evidence is satisfied."""

        return frozenset(dim for dim, ev in self.evidence.items() if ev.satisfied)

    def reasons_for(
        self,
        dimensions: Iterable[GateDimension],
    ) -> tuple[str, ...]:
        """Operator-visible reasons for the named dimensions."""

        return tuple(
            self.evidence[dim].operator_visible_reason for dim in dimensions if dim in self.evidence
        )

    def evidence_refs_for(
        self,
        dimensions: Iterable[GateDimension],
    ) -> tuple[str, ...]:
        """Flat tuple of all evidence refs across the named dimensions."""

        seen: list[str] = []
        for dim in dimensions:
            ev = self.evidence.get(dim)
            if ev is None:
                continue
            for ref in ev.evidence_refs:
                if ref not in seen:
                    seen.append(ref)
        return tuple(seen)


class TargetFamilyLedgerEntry(LedgerModel):
    """Per-target-family ledger row with full evidence + reasoning."""

    target_family_id: TargetFamilyId
    decision: ConversionReadinessDecision
    relevant_dimensions: tuple[GateDimension, ...]
    satisfied_dimensions: tuple[GateDimension, ...]
    evidence_refs: tuple[str, ...]
    operator_visible_reasons: tuple[str, ...]

    @property
    def is_public(self) -> bool:
        return self.decision.effective_state in PUBLIC_READINESS_STATES

    @property
    def is_monetizable(self) -> bool:
        return self.decision.effective_state == "public-monetizable"


class MonetizationReadinessLedger(LedgerModel):
    """Ledger output — per-family decisions plus the source snapshot."""

    snapshot_captured_at: datetime
    snapshot_source: str
    entries: tuple[TargetFamilyLedgerEntry, ...]

    def for_target_family(
        self,
        target_family_id: TargetFamilyId,
    ) -> TargetFamilyLedgerEntry:
        """Look up the ledger row for one target family, or raise."""

        for entry in self.entries:
            if entry.target_family_id == target_family_id:
                return entry
        msg = f"no ledger entry for target family {target_family_id!r}"
        raise KeyError(msg)

    def public_target_families(self) -> tuple[TargetFamilyId, ...]:
        """Target families currently in any public readiness state."""

        return tuple(entry.target_family_id for entry in self.entries if entry.is_public)

    def monetizable_target_families(self) -> tuple[TargetFamilyId, ...]:
        """Target families currently allowed to monetize."""

        return tuple(entry.target_family_id for entry in self.entries if entry.is_monetizable)

    def blocked_target_families(self) -> tuple[TargetFamilyId, ...]:
        """Target families that are currently blocked from any public state."""

        return tuple(entry.target_family_id for entry in self.entries if not entry.decision.allowed)


def evaluate_monetization_readiness(
    matrix: ConversionTargetReadinessMatrix,
    snapshot: MonetizationReadinessSnapshot,
    requested_states: Mapping[TargetFamilyId, ReadinessState] | None = None,
) -> MonetizationReadinessLedger:
    """Evaluate the snapshot against every target family in the matrix.

    When ``requested_states`` doesn't pin a target family, the ledger
    probes the public-monetizable → public-live → public-archive →
    dry-run → private-evidence ladder and returns the highest state
    that the matrix allows for that family. Anything still failing
    falls back to ``blocked`` (this matches the matrix's own
    ``default_state`` for every family).
    """

    requested = dict(requested_states or {})
    satisfied = snapshot.satisfied_dimensions()
    by_family = matrix.by_family_id()
    entries: list[TargetFamilyLedgerEntry] = []
    for family_id, target in by_family.items():
        decision = _decide_for_family(
            matrix=matrix,
            family_id=family_id,
            requested=requested.get(family_id),
            satisfied=satisfied,
            allowed_states=target.allowed_states,
        )
        relevant = tuple(sorted(target.required_dimensions_for_state(decision.effective_state)))
        relevant_satisfied = tuple(dim for dim in relevant if dim in satisfied)
        evidence_refs = snapshot.evidence_refs_for(relevant)
        reasons = snapshot.reasons_for(decision.missing_gate_dimensions or relevant_satisfied)
        if not reasons and decision.operator_visible_reason:
            reasons = (decision.operator_visible_reason,)
        entries.append(
            TargetFamilyLedgerEntry(
                target_family_id=family_id,
                decision=decision,
                relevant_dimensions=relevant,
                satisfied_dimensions=relevant_satisfied,
                evidence_refs=evidence_refs,
                operator_visible_reasons=reasons,
            )
        )
    return MonetizationReadinessLedger(
        snapshot_captured_at=snapshot.captured_at,
        snapshot_source=snapshot.snapshot_source,
        entries=tuple(entries),
    )


def _decide_for_family(
    *,
    matrix: ConversionTargetReadinessMatrix,
    family_id: TargetFamilyId,
    requested: ReadinessState | None,
    satisfied: frozenset[GateDimension],
    allowed_states: tuple[ReadinessState, ...],
) -> ConversionReadinessDecision:
    """Resolve one family's effective state.

    If ``requested`` is pinned, defer to the matrix verbatim. Otherwise
    walk the probe ladder and return the highest-state decision that
    the matrix allows.
    """

    if requested is not None:
        return decide_readiness_state(matrix, family_id, requested, satisfied)

    last_decision: ConversionReadinessDecision | None = None
    for candidate in _PROBE_STATES:
        if candidate not in allowed_states:
            continue
        decision = decide_readiness_state(matrix, family_id, candidate, satisfied)
        if decision.allowed:
            return decision
        last_decision = decision

    if last_decision is not None:
        return last_decision
    return ConversionReadinessDecision(
        target_family_id=family_id,
        requested_state="blocked",
        effective_state="blocked",
        allowed=False,
        missing_gate_dimensions=(),
        operator_visible_reason="no allowed states for this family",
    )


def evaluate_default_monetization_readiness(
    snapshot: MonetizationReadinessSnapshot,
) -> MonetizationReadinessLedger:
    """Convenience: evaluate against the canonical on-disk matrix."""

    matrix = load_conversion_target_readiness_matrix()
    return evaluate_monetization_readiness(matrix, snapshot)
