"""PerceptualField grounding key registry and witness map.

Classifies every claimable :mod:`shared.perceptual_field` key with its
producing subsystem, WCS surface, evidence class, temporal band, witness
policy, freshness budget, authority ceiling, public scope, failure
policy, prompt-rendering rules, and allowed consumers.

The registry is the gate that converts raw ``PerceptualField`` JSON
blocks into evidence-bearing facts before they enter a model prompt,
impingement, autonomous narration, director output, public claim, or
action selection. Raw untyped values cannot satisfy a consumer's claim
floor; they must come through registry-driven rendering.

Spec: ``hapax-research/specs/2026-05-01-perceptual-field-grounding-key-witness-map-contract.md``
Parent ontology: ``hapax-research/specs/2026-04-30-canonical-temporal-grounding-ontology.md``
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Type literals — all enums the spec calls out as required vocabulary.
# Keep these tight to the spec; do not add ad-hoc values.
# ---------------------------------------------------------------------------

type EvidenceClass = Literal[
    "sensor",
    "public-event",
    "route",
    "archive",
    "classifier",
    "derived-state",
    "operator-command",
    "diagnostic",
]

type TemporalBand = Literal[
    "impression",
    "retention",
    "protention",
    "surprise",
    "nonclaimable-diagnostic",
]

type SpanRefPolicy = Literal["required", "optional", "forbidden", "diagnostic-only"]

type WitnessKind = Literal[
    "runtime-witness",
    "append-only-event",
    "state-file",
    "sensor-frame",
    "classifier-output",
    "broadcast-frame",
    "archive-span",
    "synthetic-fixture",
]

type AuthorityCeiling = Literal[
    "none",
    "diagnostic",
    "private-only",
    "witnessed-presence",
    "grounded-private",
    "public-visible",
    "public-live",
    "action-authorizing",
]

type PublicScope = Literal[
    "never-public",
    "public-only-with-egress",
    "public-archive-only",
    "public-live-only-with-witness",
    "internal-only",
]

type FailureMode = Literal[
    "missing",
    "stale",
    "malformed",
    "spanless",
    "contradictory",
    "synthetic-only",
    "inferred-only",
    "parser-fallback",
    "private-route-requested-public",
    "protention-as-fact",
]

type FailurePolicy = Literal[
    "fail-closed",
    "render-as-diagnostic",
    "drop-from-prompt",
    "redact-with-caveat",
    "downgrade-authority",
]

type PromptRenderingMode = Literal[
    "render-with-age-and-window",
    "render-with-caveat-only",
    "render-bounded-summary",
    "render-as-diagnostic-block",
    "do-not-render",
]

type Consumer = Literal[
    "director",
    "autonomous-narration",
    "private-voice",
    "public-broadcast",
    "content-programme",
    "affordance-recruitment",
    "dashboard",
    "diagnostics",
]

# Public scopes that require a live/archive egress witness chain.
PUBLIC_SCOPES_REQUIRING_WITNESS: frozenset[PublicScope] = frozenset(
    {
        "public-only-with-egress",
        "public-archive-only",
        "public-live-only-with-witness",
    }
)

# Authority ceilings that may render in public/broadcast prompts.
PUBLIC_AUTHORITY_CEILINGS: frozenset[AuthorityCeiling] = frozenset(
    {"public-visible", "public-live", "action-authorizing"}
)


# ---------------------------------------------------------------------------
# Core models
# ---------------------------------------------------------------------------


class RegistryModel(BaseModel):
    """Frozen-by-default base; mirrors the matrix module's idiom."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RegistryRow(RegistryModel):
    """One claimable PerceptualField key with its full witness contract."""

    key_path: str = Field(min_length=1)
    producer_ref: str = Field(min_length=1)
    wcs_surface_id: str = Field(min_length=1)
    evidence_class: EvidenceClass
    temporal_band: TemporalBand
    evidence_envelope_ref: str = Field(min_length=1)
    span_ref_policy: SpanRefPolicy
    ttl_ms: int = Field(ge=0)
    witness_kind: WitnessKind
    authority_ceiling: AuthorityCeiling
    public_scope: PublicScope
    failure_policy: Mapping[FailureMode, FailurePolicy]
    prompt_rendering: PromptRenderingMode
    allowed_consumers: tuple[Consumer, ...] = Field(min_length=1)

    def is_diagnostic_only(self) -> bool:
        return (
            self.authority_ceiling in {"none", "diagnostic"}
            or self.public_scope == "internal-only"
            or self.temporal_band == "nonclaimable-diagnostic"
            or self.prompt_rendering == "render-as-diagnostic-block"
        )

    def allows_consumer(self, consumer: Consumer) -> bool:
        return consumer in self.allowed_consumers

    def public_safe(self) -> bool:
        """May this row appear in a public-broadcast prompt?"""

        if self.is_diagnostic_only():
            return False
        if self.authority_ceiling not in PUBLIC_AUTHORITY_CEILINGS:
            return False
        return self.public_scope in PUBLIC_SCOPES_REQUIRING_WITNESS


class FieldEvidence(RegistryModel):
    """Caller-supplied evidence for a registry row at evaluation time.

    The registry doesn't read sensors itself; consumers pass in what
    they observed (value, age, span ref, witness ref, sources). The
    registry decides whether that evidence satisfies the row's claim
    floor for the requested consumer.
    """

    key_path: str = Field(min_length=1)
    value_present: bool
    captured_at_ms: float | None = None
    span_ref: str | None = None
    witness_ref: str | None = None
    is_inferred: bool = False
    is_synthetic: bool = False
    is_parser_fallback: bool = False
    contradictory_sources: tuple[str, ...] = ()
    is_protention: bool = False


class GroundingDecision(RegistryModel):
    """Result of evaluating evidence for a registry row + consumer pair."""

    key_path: str
    consumer: Consumer
    admitted: bool
    effective_authority: AuthorityCeiling
    rendering: PromptRenderingMode
    triggered_failures: tuple[FailureMode, ...]
    operator_visible_reason: str

    @classmethod
    def hard_blocked(
        cls,
        *,
        key_path: str,
        consumer: Consumer,
        failures: Iterable[FailureMode],
        reason: str,
    ) -> Self:
        return cls(
            key_path=key_path,
            consumer=consumer,
            admitted=False,
            effective_authority="none",
            rendering="do-not-render",
            triggered_failures=tuple(failures),
            operator_visible_reason=reason,
        )


# ---------------------------------------------------------------------------
# Registry container + first-tranche fixture rows
# ---------------------------------------------------------------------------


class PerceptualFieldGroundingRegistry(RegistryModel):
    """Registry of claimable PerceptualField keys with witness contracts."""

    rows: tuple[RegistryRow, ...]
    diagnostic_only_prefixes: tuple[str, ...] = (
        "inferred.",
        "parser_fallback.",
        "silence_hold.",
        "synthetic.",
        "decorative.",
        "classifier_fallback.",
        "protention.",
        "stale_retention.",
    )

    def by_key_path(self) -> dict[str, RegistryRow]:
        return {row.key_path: row for row in self.rows}

    def row_for(self, key_path: str) -> RegistryRow | None:
        for row in self.rows:
            if row.key_path == key_path:
                return row
        return None

    def is_diagnostic_only_path(self, key_path: str) -> bool:
        return any(key_path.startswith(prefix) for prefix in self.diagnostic_only_prefixes)

    def evaluate(
        self,
        evidence: FieldEvidence,
        consumer: Consumer,
        *,
        now_ms: float | None = None,
    ) -> GroundingDecision:
        """Decide whether this evidence may render for the consumer."""

        if self.is_diagnostic_only_path(evidence.key_path):
            return GroundingDecision.hard_blocked(
                key_path=evidence.key_path,
                consumer=consumer,
                failures=("inferred-only",),
                reason=(
                    "diagnostic-only path; cannot authorize factual / current / "
                    "live / public claims"
                ),
            )

        row = self.row_for(evidence.key_path)
        if row is None:
            return GroundingDecision.hard_blocked(
                key_path=evidence.key_path,
                consumer=consumer,
                failures=("missing",),
                reason="no registry row for this key path; raw value cannot enter a prompt",
            )

        if not row.allows_consumer(consumer):
            return GroundingDecision.hard_blocked(
                key_path=evidence.key_path,
                consumer=consumer,
                failures=("private-route-requested-public",),
                reason=(f"consumer '{consumer}' is not in the row's allowed_consumers list"),
            )

        failures: list[FailureMode] = []

        if not evidence.value_present:
            failures.append("missing")
        if evidence.is_synthetic:
            failures.append("synthetic-only")
        if evidence.is_inferred:
            failures.append("inferred-only")
        if evidence.is_parser_fallback:
            failures.append("parser-fallback")
        if evidence.contradictory_sources:
            failures.append("contradictory")
        if evidence.is_protention:
            failures.append("protention-as-fact")
        if row.span_ref_policy == "required" and evidence.span_ref is None:
            failures.append("spanless")

        if evidence.value_present and evidence.captured_at_ms is not None and row.ttl_ms > 0:
            current_ms = now_ms if now_ms is not None else time.time() * 1000
            age_ms = current_ms - evidence.captured_at_ms
            if age_ms > row.ttl_ms:
                failures.append("stale")

        if consumer in {"public-broadcast"} and not row.public_safe():
            failures.append("private-route-requested-public")

        if failures:
            policy = self._resolve_policy(row, failures)
            admitted = policy not in {"fail-closed", "drop-from-prompt"}
            rendering = self._policy_to_rendering(policy, row.prompt_rendering)
            authority = self._policy_to_authority(policy, row.authority_ceiling)
            return GroundingDecision(
                key_path=evidence.key_path,
                consumer=consumer,
                admitted=admitted,
                effective_authority=authority,
                rendering=rendering,
                triggered_failures=tuple(failures),
                operator_visible_reason=(
                    f"failure(s) {sorted(failures)} resolved via policy '{policy}'"
                ),
            )

        return GroundingDecision(
            key_path=evidence.key_path,
            consumer=consumer,
            admitted=True,
            effective_authority=row.authority_ceiling,
            rendering=row.prompt_rendering,
            triggered_failures=(),
            operator_visible_reason="evidence satisfies the row's claim floor",
        )

    @staticmethod
    def _resolve_policy(
        row: RegistryRow,
        failures: Iterable[FailureMode],
    ) -> FailurePolicy:
        """Pick the strictest policy among the triggered failures."""

        order: list[FailurePolicy] = [
            "fail-closed",
            "drop-from-prompt",
            "redact-with-caveat",
            "downgrade-authority",
            "render-as-diagnostic",
        ]
        triggered_policies = {
            row.failure_policy[failure] for failure in failures if failure in row.failure_policy
        }
        for candidate in order:
            if candidate in triggered_policies:
                return candidate
        return "fail-closed"

    @staticmethod
    def _policy_to_rendering(
        policy: FailurePolicy,
        baseline: PromptRenderingMode,
    ) -> PromptRenderingMode:
        if policy == "fail-closed" or policy == "drop-from-prompt":
            return "do-not-render"
        if policy == "render-as-diagnostic":
            return "render-as-diagnostic-block"
        if policy == "redact-with-caveat":
            return "render-with-caveat-only"
        if policy == "downgrade-authority":
            return baseline
        return baseline

    @staticmethod
    def _policy_to_authority(
        policy: FailurePolicy,
        baseline: AuthorityCeiling,
    ) -> AuthorityCeiling:
        if policy in {"fail-closed", "drop-from-prompt"}:
            return "none"
        if policy == "render-as-diagnostic":
            return "diagnostic"
        if policy == "downgrade-authority":
            if baseline in {"public-live", "action-authorizing"}:
                return "public-visible"
            if baseline in {"public-visible"}:
                return "grounded-private"
            if baseline in {"grounded-private"}:
                return "witnessed-presence"
            if baseline in {"witnessed-presence"}:
                return "private-only"
            return "diagnostic"
        return baseline


def _common_failure_policy(
    *,
    high_risk: bool,
) -> Mapping[FailureMode, FailurePolicy]:
    """Default failure policy used by most first-tranche rows.

    High-risk fields (anything that can authorize public/live/action
    claims) fail closed on every failure mode. Lower-risk fields render
    diagnostically when stale or inferred, but still fail closed on
    contradictory or synthetic-only evidence.
    """

    if high_risk:
        return {
            "missing": "fail-closed",
            "stale": "fail-closed",
            "malformed": "fail-closed",
            "spanless": "fail-closed",
            "contradictory": "fail-closed",
            "synthetic-only": "fail-closed",
            "inferred-only": "fail-closed",
            "parser-fallback": "fail-closed",
            "private-route-requested-public": "drop-from-prompt",
            "protention-as-fact": "fail-closed",
        }
    return {
        "missing": "drop-from-prompt",
        "stale": "render-with-caveat-only" if False else "render-as-diagnostic",
        "malformed": "drop-from-prompt",
        "spanless": "render-as-diagnostic",
        "contradictory": "fail-closed",
        "synthetic-only": "fail-closed",
        "inferred-only": "render-as-diagnostic",
        "parser-fallback": "render-as-diagnostic",
        "private-route-requested-public": "drop-from-prompt",
        "protention-as-fact": "fail-closed",
    }


# First-tranche representative rows. Cover at least one row per first-
# tranche category from the spec; downstream PRs extend coverage to
# full first-tranche breadth.
_FIRST_TRANCHE_ROWS: tuple[RegistryRow, ...] = (
    # Music + track surface (high-risk: rights/monetization downstream)
    RegistryRow(
        key_path="current_track",
        producer_ref="hapax-content-resolver / album-state.json",
        wcs_surface_id="audio-current-track",
        evidence_class="derived-state",
        temporal_band="impression",
        evidence_envelope_ref="album_state.AlbumStateEnvelope",
        span_ref_policy="required",
        ttl_ms=15_000,
        witness_kind="state-file",
        authority_ceiling="public-live",
        public_scope="public-live-only-with-witness",
        failure_policy=_common_failure_policy(high_risk=True),
        prompt_rendering="render-with-age-and-window",
        allowed_consumers=(
            "director",
            "autonomous-narration",
            "public-broadcast",
            "content-programme",
            "dashboard",
        ),
    ),
    # Stream live state (high-risk: gates public surfaces)
    RegistryRow(
        key_path="stream_live",
        producer_ref="agents/studio_compositor (stream-live SHM)",
        wcs_surface_id="livestream-egress-state",
        evidence_class="route",
        temporal_band="impression",
        evidence_envelope_ref="livestream_egress_state.LivestreamEgressState",
        span_ref_policy="required",
        ttl_ms=5_000,
        witness_kind="state-file",
        authority_ceiling="action-authorizing",
        public_scope="public-live-only-with-witness",
        failure_policy=_common_failure_policy(high_risk=True),
        prompt_rendering="render-with-age-and-window",
        allowed_consumers=("director", "autonomous-narration", "public-broadcast", "dashboard"),
    ),
    # Chat counts (lower-risk; can render diagnostically when stale)
    RegistryRow(
        key_path="chat.recent_count",
        producer_ref="agents/studio_compositor (chat-recent.json)",
        wcs_surface_id="chat-window",
        evidence_class="public-event",
        temporal_band="retention",
        evidence_envelope_ref="chat_state.ChatRecentEnvelope",
        span_ref_policy="optional",
        ttl_ms=60_000,
        witness_kind="state-file",
        authority_ceiling="public-visible",
        public_scope="public-archive-only",
        failure_policy=_common_failure_policy(high_risk=False),
        prompt_rendering="render-with-age-and-window",
        allowed_consumers=(
            "director",
            "autonomous-narration",
            "content-programme",
            "dashboard",
        ),
    ),
    # Operator presence (private; classifier-derived)
    RegistryRow(
        key_path="presence.operator_present",
        producer_ref="agents/hapax_daimonion presence_engine",
        wcs_surface_id="operator-presence",
        evidence_class="classifier",
        temporal_band="impression",
        evidence_envelope_ref="presence_engine.PresenceEnvelope",
        span_ref_policy="required",
        ttl_ms=10_000,
        witness_kind="classifier-output",
        authority_ceiling="grounded-private",
        public_scope="never-public",
        failure_policy=_common_failure_policy(high_risk=True),
        prompt_rendering="render-with-age-and-window",
        allowed_consumers=("director", "private-voice", "affordance-recruitment", "dashboard"),
    ),
    # Per-camera classification (sensor-derived; private surface)
    RegistryRow(
        key_path="camera.classifications",
        producer_ref="agents/studio_compositor classification pipeline",
        wcs_surface_id="camera-classification",
        evidence_class="classifier",
        temporal_band="impression",
        evidence_envelope_ref="classification.CameraClassificationEnvelope",
        span_ref_policy="required",
        ttl_ms=8_000,
        witness_kind="classifier-output",
        authority_ceiling="grounded-private",
        public_scope="never-public",
        failure_policy=_common_failure_policy(high_risk=False),
        prompt_rendering="render-bounded-summary",
        allowed_consumers=("director", "affordance-recruitment", "dashboard"),
    ),
    # HOMAGE state (private; consent-safe gate downstream)
    RegistryRow(
        key_path="homage.active_artefact",
        producer_ref="agents/studio_compositor HOMAGE choreographer",
        wcs_surface_id="homage-state",
        evidence_class="derived-state",
        temporal_band="impression",
        evidence_envelope_ref="homage_state.HomageEnvelope",
        span_ref_policy="required",
        ttl_ms=30_000,
        witness_kind="state-file",
        authority_ceiling="grounded-private",
        public_scope="public-live-only-with-witness",
        failure_policy=_common_failure_policy(high_risk=True),
        prompt_rendering="render-with-age-and-window",
        allowed_consumers=("director", "autonomous-narration", "content-programme", "dashboard"),
    ),
    # Recent reactions (low-risk recruitment signal)
    RegistryRow(
        key_path="reactions.recent",
        producer_ref="agents/studio_compositor chat-reactor",
        wcs_surface_id="chat-reactions",
        evidence_class="public-event",
        temporal_band="retention",
        evidence_envelope_ref="chat_state.ReactionsEnvelope",
        span_ref_policy="optional",
        ttl_ms=120_000,
        witness_kind="append-only-event",
        authority_ceiling="witnessed-presence",
        public_scope="public-archive-only",
        failure_policy=_common_failure_policy(high_risk=False),
        prompt_rendering="render-bounded-summary",
        allowed_consumers=("director", "affordance-recruitment", "content-programme", "dashboard"),
    ),
)


def default_registry() -> PerceptualFieldGroundingRegistry:
    """Canonical first-tranche registry."""

    return PerceptualFieldGroundingRegistry(rows=_FIRST_TRANCHE_ROWS)
