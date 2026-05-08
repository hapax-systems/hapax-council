"""Private resource-capability schema/projection contracts.

This module is intentionally inert: it declares strict typed rows and fixture
loading only. It does not import provider SDKs, send mail, write calendars,
move money, or wire runtime services.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_CAPABILITY_FIXTURES = REPO_ROOT / "config" / "resource-capability-fixtures.json"
RESOURCE_CAPABILITY_SCHEMA_REF = "schemas/resource-capability.schema.json"

REQUIRED_MODELS = frozenset(
    {
        "ResourceOpportunity",
        "ResourceCapability",
        "MonetaryCapability",
        "ResourceReceipt",
        "ResourceExperiment",
        "CapabilityAccount",
        "AutonomyDebtEvent",
        "ObserverPostureSnapshot",
        "PredictionLedger",
        "MeasurementActionContract",
        "GrowthNoGoMatrix",
        "SemanticTransactionTrace",
        "TransactionPressureLedger",
        "PublicResourceClaimEnvelope",
        "AccountBoundaryRecord",
        "AccountFederationRegistry",
        "ExpectedCorrespondenceEnvelope",
        "ExpectedMailCandidate",
        "EmailAutonomyEvent",
        "CalendarWriteEnvelope",
        "CalendarObligation",
        "PaymentReceiptEvent",
        "BalanceSnapshot",
        "PayoutReconciliationRecord",
        "DisputeMonitorEvent",
        "RefundDraft",
        "TaxEvidencePacket",
        "ProviderNoticeEvent",
        "ResourceCreditReceipt",
    }
)

FORBIDDEN_PROVIDER_WRITE_SCOPES = frozenset(
    {
        "payment_refund",
        "payment_payout",
        "payment_transfer",
        "payment_top_up",
        "payment_debit_pull",
        "payment_creation",
        "bank_payment_creation",
        "bank_direct_debit_pull",
        "crypto_settlement",
        "trading_or_investment",
        "custody_or_lending",
        "gmail_send_outside_expected_correspondence",
        "tax_form_submission",
        "kyc_kyb_upload",
        "w9_w8_submission",
        "terms_acceptance",
        "grant_certification",
        "legal_signature",
        "public_endorsement_publication",
        "sponsorship_acceptance",
        "public_offer_publication",
        "public_claim_upgrade_without_envelope",
        "stale_surface_activation",
    }
)


class ResourceCapabilityError(ValueError):
    """Raised when resource-capability fixtures cannot be loaded safely."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResourceClass(StrEnum):
    CASH = "cash"
    RECEIVABLE = "receivable"
    CREDIT = "credit"
    COMPUTE = "compute"
    API_QUOTA = "api_quota"
    HARDWARE = "hardware"
    ACCESS = "access"
    BADGE = "badge"
    INSTITUTIONAL_SUPPORT = "institutional_support"
    OBLIGATION = "obligation"
    TRUST_COST = "trust_cost"


class DecisionState(StrEnum):
    CANDIDATE = "candidate"
    OBSERVE_ONLY = "observe_only"
    DRAFT_ONLY = "draft_only"
    BLOCKED = "blocked"
    BLOCKED_STALE_CONFLICT = "blocked_stale_conflict"


class AuthorityCeiling(StrEnum):
    NO_CLAIM = "no_claim"
    INTERNAL_ONLY = "internal_only"
    EVIDENCE_BOUND = "evidence_bound"
    PUBLIC_GATE_REQUIRED = "public_gate_required"


class PublicClaimCeiling(StrEnum):
    NONE = "none"
    PRIVATE_SUMMARY = "private_summary"
    EVIDENCE_BOUND = "evidence_bound"
    PUBLIC_GATE_REQUIRED = "public_gate_required"


class AvoidabilityClass(StrEnum):
    ELIMINABLE = "eliminable"
    REDUCIBLE = "reducible"
    BATCHABLE = "batchable"
    PREAUTHORIZABLE = "preauthorizable"
    DELEGABLE = "delegable"
    EXTERNAL_HARD_BOUNDARY = "external-hard-boundary"
    UNKNOWN = "unknown"


class InterventionClass(StrEnum):
    MONEY = "money"
    RESOURCE = "resource"
    CORRESPONDENCE = "correspondence"
    CALENDAR = "calendar"
    PUBLIC_CLAIM = "public_claim"
    LEGAL_TAX_KYC = "legal_tax_kyc"


class ActionClass(StrEnum):
    OBSERVE = "observe"
    DISPATCH = "dispatch"
    GATE = "gate"
    KILL = "kill"
    HOLD = "hold"
    ESCALATE = "escalate"


class ReplyTier(StrEnum):
    AUTO_ACK = "AUTO_ACK"
    AUTO_INFO = "AUTO_INFO"
    PRE_AUTH_REPLY = "PRE_AUTH_REPLY"
    DRAFT_ONLY = "DRAFT_ONLY"
    ESCALATE_NO_REPLY = "ESCALATE_NO_REPLY"
    REPORT_ONLY = "REPORT_ONLY"


class AuthenticationState(StrEnum):
    VERIFIED = "verified"
    ALIGNED = "aligned"
    WEAK = "weak"
    UNVERIFIED = "unverified"
    FAILED = "failed"


class HandlingDecision(StrEnum):
    AUTO_RESPONSE = "auto_response"
    DRAFT_FOR_REVIEW = "draft_for_review"
    OPERATOR_ESCALATION = "operator_escalation"
    HARD_REFUSAL = "hard_refusal"
    ARCHIVE_ONLY = "archive_only"
    NO_RESPONSE = "no_response"


class CalendarScope(StrEnum):
    PRIVATE_INTERNAL = "private_internal"
    OPERATOR_PRIMARY = "operator_primary"
    SHARED = "shared"
    EXTERNAL = "external"


class CalendarAuthorityLevel(StrEnum):
    AUTO_CREATE = "auto_create"
    DRAFT_FOR_REVIEW = "draft_for_review"
    ESCALATE = "escalate"


class NoGoDecision(StrEnum):
    BLOCKED = "blocked"
    REQUIRES_LATER_AUTHORITY = "requires_later_authority"
    ALLOWED_READ_RECEIVE_ONLY = "allowed_read_receive_only"


class SemanticTransactionKind(StrEnum):
    TRANSACTION_PRESSURE = "transaction_pressure"
    TRANSACTION = "transaction"
    COMMUNICATION = "communication"
    ACTION = "action"
    WAITING_STATE = "waiting_state"
    EVENT = "event"
    REFUSAL = "refusal"
    ESCALATION = "escalation"
    PROVIDER_STATE = "provider_state"
    CALENDAR_OBLIGATION = "calendar_obligation"


class ProviderWriteScope(StrEnum):
    PAYMENT_REFUND = "payment_refund"
    PAYMENT_PAYOUT = "payment_payout"
    PAYMENT_TRANSFER = "payment_transfer"
    PAYMENT_TOP_UP = "payment_top_up"
    PAYMENT_DEBIT_PULL = "payment_debit_pull"
    PAYMENT_CREATION = "payment_creation"
    BANK_PAYMENT_CREATION = "bank_payment_creation"
    BANK_DIRECT_DEBIT_PULL = "bank_direct_debit_pull"
    CRYPTO_SETTLEMENT = "crypto_settlement"
    TRADING_OR_INVESTMENT = "trading_or_investment"
    CUSTODY_OR_LENDING = "custody_or_lending"
    GMAIL_SEND_OUTSIDE_EXPECTED_CORRESPONDENCE = "gmail_send_outside_expected_correspondence"
    TAX_FORM_SUBMISSION = "tax_form_submission"
    KYC_KYB_UPLOAD = "kyc_kyb_upload"
    W9_W8_SUBMISSION = "w9_w8_submission"
    TERMS_ACCEPTANCE = "terms_acceptance"
    GRANT_CERTIFICATION = "grant_certification"
    LEGAL_SIGNATURE = "legal_signature"
    PUBLIC_ENDORSEMENT_PUBLICATION = "public_endorsement_publication"
    SPONSORSHIP_ACCEPTANCE = "sponsorship_acceptance"
    PUBLIC_OFFER_PUBLICATION = "public_offer_publication"
    PUBLIC_CLAIM_UPGRADE_WITHOUT_ENVELOPE = "public_claim_upgrade_without_envelope"
    STALE_SURFACE_ACTIVATION = "stale_surface_activation"


class ResourceValuation(StrictModel):
    nominal_value: float = Field(ge=0)
    nominal_unit: str
    cash_equivalent_value: float | None
    cash_equivalent_currency: str
    operational_capability_value: float = Field(ge=0)
    revenue_value: float = Field(ge=0)
    trust_cost: float = Field(default=0.0, ge=0)
    conversion_confidence: float = Field(ge=0, le=1)
    value_basis_refs: list[str] = Field(min_length=1)


class ResourceOpportunity(StrictModel):
    schema_version: Literal[1] = 1
    opportunity_id: str
    resource_class: ResourceClass
    source_ref: str
    valuation: ResourceValuation
    liquidity: str
    restrictions: list[str] = Field(default_factory=list)
    expiry: str | None = None
    transferability: str
    public_claim_ceiling: PublicClaimCeiling = PublicClaimCeiling.NONE
    authority_ceiling: AuthorityCeiling = AuthorityCeiling.INTERNAL_ONLY
    obligations: list[str] = Field(default_factory=list)
    hidden_operator_labor_risk: str
    privacy_ip_terms_risk: str
    lock_in_cost: str
    capabilities_unlocked: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(min_length=1)
    source_freshness_ttl_s: int = Field(ge=0)
    decision_state: DecisionState
    stale_conflict_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _stale_conflicts_fail_closed(self) -> Self:
        if self.stale_conflict_refs:
            if self.decision_state is not DecisionState.BLOCKED_STALE_CONFLICT:
                raise ValueError("stale conflicts must stay blocked_stale_conflict")
        if self.decision_state is DecisionState.BLOCKED_STALE_CONFLICT:
            if not self.stale_conflict_refs:
                raise ValueError("blocked_stale_conflict requires stale_conflict_refs")
        return self


class ResourceCapability(StrictModel):
    schema_version: Literal[1] = 1
    capability_id: str
    capability_name: str
    account_id: str
    opportunity_id: str | None = None
    resource_class: ResourceClass
    valuation: ResourceValuation
    authority_ceiling: AuthorityCeiling = AuthorityCeiling.INTERNAL_ONLY
    public_claim_ceiling: PublicClaimCeiling = PublicClaimCeiling.NONE
    capabilities_unlocked: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(min_length=1)
    source_freshness_ttl_s: int = Field(ge=0)
    decision_state: DecisionState = DecisionState.OBSERVE_ONLY
    autonomy_debt_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _public_claims_need_gate(self) -> Self:
        if self.public_claim_ceiling is PublicClaimCeiling.PUBLIC_GATE_REQUIRED:
            if self.authority_ceiling is not AuthorityCeiling.PUBLIC_GATE_REQUIRED:
                raise ValueError("public claim ceiling requires public gate authority ceiling")
        return self


class MonetaryCapability(ResourceCapability):
    monetary_capability_kind: Literal["resource_capability_subtype"] = "resource_capability_subtype"
    resource_class: ResourceClass

    @model_validator(mode="after")
    def _monetary_is_resource_subtype(self) -> Self:
        if self.resource_class not in {ResourceClass.CASH, ResourceClass.RECEIVABLE}:
            raise ValueError("MonetaryCapability must remain a ResourceCapability subtype")
        return self


class ResourceReceipt(StrictModel):
    schema_version: Literal[1] = 1
    receipt_id: str
    received_at: str
    resource_class: ResourceClass
    source_ref: str
    account_id: str
    valuation: ResourceValuation
    obligations: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(min_length=1)
    public_claim_envelope_ref: str | None = None
    observe_only: Literal[True] = True


class ResourceExperiment(StrictModel):
    schema_version: Literal[1] = 1
    experiment_id: str
    hypothesis: str
    gate_prerequisites: list[str] = Field(min_length=1)
    success_metric: str
    failure_metric: str
    stop_condition: str
    expiry: str
    rollback: str
    no_go_conditions: list[str] = Field(min_length=1)
    launch_authorized: Literal[False] = False


class ResourceAuthorityCase(StrictModel):
    case_id: str
    authority_case_kind: Literal["authority_case_profile"] = "authority_case_profile"
    outbound_financial_control_authorized: Literal[False] = False


class CapabilityAccount(StrictModel):
    schema_version: Literal[1] = 1
    account_id: str
    resource_classes: list[ResourceClass] = Field(min_length=1)
    nominal_value_total: float = Field(ge=0)
    cash_equivalent_value_total: float | None
    operational_capability_value_total: float = Field(ge=0)
    liquidity: str
    restrictions: list[str] = Field(default_factory=list)
    expiry: str | None = None
    conversion_confidence: float = Field(ge=0, le=1)
    downstream_capability_unlocked: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(min_length=1)


class AutonomyDebtEvent(StrictModel):
    schema_version: Literal[1] = 1
    event_id: str
    occurred_at: str
    triggering_opportunity_or_resource: str
    intervention_class: InterventionClass
    hard_boundary: bool
    avoidability: AvoidabilityClass
    operator_time_minutes: int = Field(ge=0)
    blocked_duration: str
    risk_if_automated: str
    why_required_now: str
    future_reduction_strategy: str
    recurrence_key: str
    created_followup_task: str | None = None
    evidence_refs: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _hard_boundaries_remain_debt(self) -> Self:
        if self.hard_boundary and self.avoidability is not AvoidabilityClass.EXTERNAL_HARD_BOUNDARY:
            raise ValueError("hard boundary autonomy debt must be external-hard-boundary")
        return self


class ObserverPostureSnapshot(StrictModel):
    schema_version: Literal[1] = 1
    snapshot_id: str
    observed_at: str
    autonomous_gross_resource_change: float
    autonomous_net_resource_change: float
    operator_touch_count: int = Field(ge=0)
    unavoidable_touch_count: int = Field(ge=0)
    autonomy_debt_event_refs: list[str] = Field(default_factory=list)
    recurrence_keys: list[str] = Field(default_factory=list)
    tax_evidence_completeness: str
    dispute_or_fraud_event_refs: list[str] = Field(default_factory=list)
    stale_opportunity_refs: list[str] = Field(default_factory=list)
    next_eligible_autonomous_actions: list[str] = Field(default_factory=list)


class PredictionLedger(StrictModel):
    schema_version: Literal[1] = 1
    prediction_id: str
    baseline: str
    horizon: str
    metric_definition: str
    expected_delta: str
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[str] = Field(min_length=1)
    update_cadence: str
    falsification_or_kill_criteria: str
    claim_authority: AuthorityCeiling = AuthorityCeiling.INTERNAL_ONLY


class MeasurementActionContract(StrictModel):
    schema_version: Literal[1] = 1
    metric_id: str
    source: str
    freshness_cadence: str
    ttl_s: int = Field(ge=0)
    consumer: str
    action_class: ActionClass
    stale_behavior: DecisionState
    no_go_threshold: str | None = None
    evidence_refs: list[str] = Field(min_length=1)
    authoritative: bool

    @model_validator(mode="after")
    def _action_metrics_need_semantics(self) -> Self:
        if self.action_class is not ActionClass.OBSERVE and self.no_go_threshold is None:
            raise ValueError("action-bearing metrics require no_go_threshold")
        if not self.authoritative and self.action_class is not ActionClass.OBSERVE:
            raise ValueError("non-authoritative metrics cannot drive actions")
        return self


class GrowthNoGoRule(StrictModel):
    scope: ProviderWriteScope
    decision: NoGoDecision = NoGoDecision.BLOCKED
    required_later_authority: str
    reason: str

    @model_validator(mode="after")
    def _forbidden_scopes_are_blocked(self) -> Self:
        if self.scope.value in FORBIDDEN_PROVIDER_WRITE_SCOPES:
            if self.decision is not NoGoDecision.BLOCKED:
                raise ValueError(f"{self.scope.value} must fail closed")
        return self


class GrowthNoGoMatrix(StrictModel):
    schema_version: Literal[1] = 1
    matrix_id: str
    forbidden_provider_write_scopes: list[ProviderWriteScope]
    rules: list[GrowthNoGoRule]
    unknown_scope_decision: Literal[NoGoDecision.BLOCKED] = NoGoDecision.BLOCKED
    stale_surface_conflict_decision: Literal[DecisionState.BLOCKED_STALE_CONFLICT] = (
        DecisionState.BLOCKED_STALE_CONFLICT
    )

    @model_validator(mode="after")
    def _covers_every_forbidden_scope(self) -> Self:
        declared = {scope.value for scope in self.forbidden_provider_write_scopes}
        if declared != FORBIDDEN_PROVIDER_WRITE_SCOPES:
            missing = FORBIDDEN_PROVIDER_WRITE_SCOPES - declared
            extra = declared - FORBIDDEN_PROVIDER_WRITE_SCOPES
            raise ValueError(
                "forbidden provider scopes mismatch; missing="
                f"{sorted(missing)}, extra={sorted(extra)}"
            )
        rules = {rule.scope.value: rule for rule in self.rules}
        missing_rules = FORBIDDEN_PROVIDER_WRITE_SCOPES - set(rules)
        if missing_rules:
            raise ValueError("GrowthNoGoMatrix missing rules: " + ", ".join(sorted(missing_rules)))
        return self

    def decision_for(self, scope: str) -> NoGoDecision:
        try:
            provider_scope = ProviderWriteScope(scope)
        except ValueError:
            return NoGoDecision.BLOCKED
        rule = {rule.scope: rule for rule in self.rules}.get(provider_scope)
        if rule is None:
            return NoGoDecision.BLOCKED
        return rule.decision


class SemanticTransactionTrace(StrictModel):
    schema_version: Literal[1] = 1
    trace_id: str
    observed_at: str
    trace_kind: SemanticTransactionKind
    source_ref: str
    semantic_state: str
    pressure_score: float = Field(ge=0, le=1)
    privacy_scope: Literal["private"] = "private"
    public_projection_allowed: Literal[False] = False
    observability_surface: Literal["machine_operator_only"] = "machine_operator_only"
    transaction_refs: list[str] = Field(default_factory=list)
    communication_refs: list[str] = Field(default_factory=list)
    action_refs: list[str] = Field(default_factory=list)
    waiting_state_refs: list[str] = Field(default_factory=list)
    event_refs: list[str] = Field(default_factory=list)
    refusal_refs: list[str] = Field(default_factory=list)
    escalation_refs: list[str] = Field(default_factory=list)
    provider_state_refs: list[str] = Field(default_factory=list)
    calendar_obligation_refs: list[str] = Field(default_factory=list)
    autonomy_debt_event_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(min_length=1)
    runtime_tracing_authorized: Literal[False] = False
    provider_api_execution_authorized: Literal[False] = False

    @model_validator(mode="after")
    def _trace_stays_private(self) -> Self:
        if self.trace_kind is SemanticTransactionKind.CALENDAR_OBLIGATION:
            if not self.calendar_obligation_refs:
                raise ValueError("calendar-obligation trace requires calendar_obligation_refs")
        if self.trace_kind is SemanticTransactionKind.ESCALATION:
            if not self.autonomy_debt_event_refs:
                raise ValueError("escalation trace requires autonomy_debt_event_refs")
        return self


class TransactionPressureLedger(StrictModel):
    schema_version: Literal[1] = 1
    ledger_id: str
    observed_at: str
    trace_refs: list[str] = Field(min_length=1)
    pressure_score: float = Field(ge=0, le=1)
    transaction_pressure_refs: list[str] = Field(default_factory=list)
    transaction_refs: list[str] = Field(default_factory=list)
    communication_refs: list[str] = Field(default_factory=list)
    action_refs: list[str] = Field(default_factory=list)
    waiting_state_refs: list[str] = Field(default_factory=list)
    event_refs: list[str] = Field(default_factory=list)
    refusal_refs: list[str] = Field(default_factory=list)
    escalation_refs: list[str] = Field(default_factory=list)
    provider_state_refs: list[str] = Field(default_factory=list)
    calendar_obligation_refs: list[str] = Field(default_factory=list)
    autonomy_debt_event_refs: list[str] = Field(default_factory=list)
    privacy_scope: Literal["private"] = "private"
    public_projection_allowed: Literal[False] = False
    observability_surface: Literal["machine_operator_only"] = "machine_operator_only"
    runtime_tracing_authorized: Literal[False] = False
    provider_poll_authorized: Literal[False] = False
    external_effect_authorized: Literal[False] = False

    @model_validator(mode="after")
    def _pressure_ledger_covers_semantic_surfaces(self) -> Self:
        surface_refs = (
            self.transaction_pressure_refs
            + self.transaction_refs
            + self.communication_refs
            + self.action_refs
            + self.waiting_state_refs
            + self.event_refs
            + self.refusal_refs
            + self.escalation_refs
            + self.provider_state_refs
            + self.calendar_obligation_refs
        )
        if not surface_refs:
            raise ValueError("transaction pressure ledger requires semantic surface refs")
        return self


class PublicResourceClaimEnvelope(StrictModel):
    schema_version: Literal[1] = 1
    envelope_id: str
    claim_text: str
    claim_class: str
    max_public_verb: str
    evidence_refs: list[str] = Field(default_factory=list)
    counterparty_terms_refs: list[str] = Field(default_factory=list)
    provenance: str
    freshness_ttl_s: int | None = Field(default=None, ge=0)
    rights_state: str
    privacy_state: str
    uncertainty: str
    correction_path: str
    blocked_phrases: list[str] = Field(default_factory=list)
    claim_allowed: bool = False

    @model_validator(mode="after")
    def _claims_fail_closed_without_evidence(self) -> Self:
        if self.claim_allowed:
            if (
                not self.evidence_refs
                or not self.counterparty_terms_refs
                or self.freshness_ttl_s is None
            ):
                raise ValueError("public resource claim requires evidence, terms, and TTL")
        return self


class AccountBoundaryRecord(StrictModel):
    schema_version: Literal[1] = 1
    account_id: str
    provider: str
    identity_class: str
    allowed_purposes: list[str] = Field(min_length=1)
    allowed_read_classes: list[str] = Field(default_factory=list)
    allowed_send_classes: list[str] = Field(default_factory=list)
    sender_identity_rule: str
    cross_account_reply_allowed: bool = False
    public_projection_allowed: bool = False
    encryption_degradation: str
    retention_policy: str
    private_data_to_public_claim_policy: str


class AccountFederationRegistry(StrictModel):
    schema_version: Literal[1] = 1
    registry_id: str
    provider: str
    account_id: str
    address_or_alias: str
    source_of_truth: str
    pass_or_secret_key: str
    read_scopes: list[str] = Field(default_factory=list)
    send_scopes: list[str] = Field(default_factory=list)
    allowed_labels: list[str] = Field(default_factory=list)
    allowed_templates: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(min_length=1)
    purpose_boundary: str
    no_fallback_to_default_token: Literal[True] = True
    proton_forwarding_policy: str
    gmail_forwarding_policy: str
    operator_boundary: str


class ExpectedCorrespondenceEnvelope(StrictModel):
    schema_version: Literal[1] = 1
    envelope_id: str
    allowed_accounts: list[str] = Field(min_length=1)
    allowed_aliases_or_labels: list[str] = Field(min_length=1)
    allowed_senders_or_domains: list[str] = Field(default_factory=list)
    expected_basis: list[str] = Field(min_length=1)
    message_classes: list[str] = Field(min_length=1)
    auth_confidence_minimum: float = Field(ge=0, le=1)
    allowed_templates: list[str] = Field(default_factory=list)
    allowed_slots: list[str] = Field(default_factory=list)
    forbidden_obligations: list[str] = Field(min_length=1)
    commercial_class: str
    disclosure_required: Literal[True] = True
    public_claim_ceiling: PublicClaimCeiling = PublicClaimCeiling.NONE
    rate_limit: str
    expiry: str
    kill_switch: Literal[True] = True
    escalation_rules: list[str] = Field(min_length=1)
    audit_requirements: list[str] = Field(min_length=1)
    reply_tier: ReplyTier


class ExpectedMailCandidate(StrictModel):
    schema_version: Literal[1] = 1
    message_id_hash: str
    source_account: str
    original_recipient: str
    label: str
    expected_class: str
    authentication_state: AuthenticationState
    pending_action_ref: str | None = None
    case_id: str | None = None
    evidence_refs: list[str] = Field(min_length=1)
    sender_identity_token: str | None = None

    @model_validator(mode="after")
    def _no_full_sender_address(self) -> Self:
        if self.sender_identity_token and "@" in self.sender_identity_token:
            raise ValueError("ExpectedMailCandidate cannot contain full sender address")
        return self


class EmailAutonomyEvent(StrictModel):
    schema_version: Literal[1] = 1
    event_id: str
    source_account: str
    message_ref: str
    thread_ref: str | None = None
    received_at: str
    expected_class_id: str
    confidence: float = Field(ge=0, le=1)
    authentication_state: AuthenticationState
    handling_decision: HandlingDecision
    template_id: str | None = None
    response_sent: bool = False
    operator_written_email: bool = False
    hard_boundary: bool = False
    unnerving_language_lint_failures: list[str] = Field(default_factory=list)
    claims_checked: bool = False
    suppression_checked: bool = False
    calendar_event_refs: list[str] = Field(default_factory=list)
    autonomy_debt_event_ref: str | None = None
    evidence_refs: list[str] = Field(min_length=1)


class CalendarWriteEnvelope(StrictModel):
    schema_version: Literal[1] = 1
    envelope_id: str
    calendar_scope: CalendarScope = CalendarScope.PRIVATE_INTERNAL
    attendee_policy: Literal["blocked_none"] = "blocked_none"
    notification_policy: Literal["blocked_none"] = "blocked_none"
    conference_data_policy: Literal["blocked_none"] = "blocked_none"
    description_policy: str
    idempotency_key: str
    source_confidence_minimum: float = Field(ge=0, le=1)
    timezone_required: Literal[True] = True
    private_payload_policy: str
    rollback_or_delete_policy: str
    availability_promise: Literal[False] = False


class CalendarObligation(StrictModel):
    schema_version: Literal[1] = 1
    obligation_id: str
    source_kind: str
    source_ref: str
    source_account_or_system: str
    date_time: str
    timezone: str
    confidence: float = Field(ge=0, le=1)
    obligation_class: str
    operator_needs_to_know: bool
    authority_level: CalendarAuthorityLevel
    calendar_id: str | None = None
    event_id: str | None = None
    reminder_policy: str
    notification_policy: str
    attendee_policy: str
    private_payload_policy: str
    created_or_updated_at: str | None = None
    evidence_refs: list[str] = Field(min_length=1)


class PaymentReceiptEvent(StrictModel):
    schema_version: Literal[1] = 1
    event_id: str
    provider: str
    received_at: str
    amount: float = Field(ge=0)
    currency: str
    receipt_ref: str
    evidence_refs: list[str] = Field(min_length=1)
    observability_only: Literal[True] = True
    outbound_movement_authorized: Literal[False] = False


class BalanceSnapshot(StrictModel):
    schema_version: Literal[1] = 1
    snapshot_id: str
    provider: str
    observed_at: str
    balance_amount: float = Field(ge=0)
    currency: str
    evidence_refs: list[str] = Field(min_length=1)
    observability_only: Literal[True] = True


class PayoutReconciliationRecord(StrictModel):
    schema_version: Literal[1] = 1
    record_id: str
    provider: str
    payout_ref: str
    observed_at: str
    reconciliation_state: str
    evidence_refs: list[str] = Field(min_length=1)
    observability_only: Literal[True] = True
    payout_authorized: Literal[False] = False


class DisputeMonitorEvent(StrictModel):
    schema_version: Literal[1] = 1
    event_id: str
    provider: str
    dispute_ref: str
    observed_at: str
    monitor_state: str
    evidence_refs: list[str] = Field(min_length=1)
    observability_only: Literal[True] = True
    dispute_submission_authorized: Literal[False] = False


class RefundDraft(StrictModel):
    schema_version: Literal[1] = 1
    draft_id: str
    provider: str
    payment_ref: str
    reason: str
    evidence_refs: list[str] = Field(min_length=1)
    draft_only: Literal[True] = True
    refund_authorized: Literal[False] = False


class TaxEvidencePacket(StrictModel):
    schema_version: Literal[1] = 1
    packet_id: str
    provider: str
    tax_context: str
    evidence_refs: list[str] = Field(min_length=1)
    packet_only: Literal[True] = True
    filing_or_submission_authorized: Literal[False] = False


class ProviderNoticeEvent(StrictModel):
    schema_version: Literal[1] = 1
    event_id: str
    provider: str
    notice_class: str
    received_at: str
    evidence_refs: list[str] = Field(min_length=1)
    observability_only: Literal[True] = True
    provider_action_authorized: Literal[False] = False


class ResourceCreditReceipt(StrictModel):
    schema_version: Literal[1] = 1
    receipt_id: str
    provider: str
    credit_class: str
    activated_at: str | None = None
    nominal_value: float = Field(ge=0)
    cash_equivalent_value: float | None
    operational_capability_value: float = Field(ge=0)
    evidence_refs: list[str] = Field(min_length=1)
    observability_only: Literal[True] = True


class ResourceCapabilityFailClosedPolicy(StrictModel):
    technical_rail_readiness_as_public_offer: Literal[False] = False
    high_value_upgrades_truth_or_claims: Literal[False] = False
    nominal_value_substitutes_cash_equivalent: Literal[False] = False
    revenue_value_substitutes_operational_capability_value: Literal[False] = False
    public_claim_without_envelope: Literal[False] = False
    stale_surface_conflict_activates_capability: Literal[False] = False
    semantic_transaction_trace_public_by_default: Literal[False] = False
    expected_mail_candidate_allows_body_or_thread: Literal[False] = False
    calendar_write_allows_attendees_or_notifications_by_default: Literal[False] = False
    provider_write_unknown_scope_allowed: Literal[False] = False


class ResourceCapabilityFixtureSet(StrictModel):
    schema_version: Literal[1] = 1
    fixture_set_id: str
    schema_ref: Literal["schemas/resource-capability.schema.json"]
    generated_from: list[str] = Field(min_length=1)
    declared_at: str
    producer: str
    required_models: list[str] = Field(min_length=1)
    forbidden_provider_write_scopes: list[ProviderWriteScope]
    fail_closed_policy: ResourceCapabilityFailClosedPolicy
    opportunities: list[ResourceOpportunity] = Field(min_length=1)
    capabilities: list[ResourceCapability] = Field(min_length=1)
    monetary_capabilities: list[MonetaryCapability] = Field(min_length=1)
    receipts: list[ResourceReceipt] = Field(min_length=1)
    experiments: list[ResourceExperiment] = Field(min_length=1)
    accounts: list[CapabilityAccount] = Field(min_length=1)
    autonomy_debt_events: list[AutonomyDebtEvent] = Field(min_length=1)
    observer_posture_snapshots: list[ObserverPostureSnapshot] = Field(min_length=1)
    prediction_ledger: list[PredictionLedger] = Field(min_length=1)
    measurement_action_contracts: list[MeasurementActionContract] = Field(min_length=1)
    growth_no_go_matrix: GrowthNoGoMatrix
    semantic_transaction_traces: list[SemanticTransactionTrace] = Field(min_length=1)
    transaction_pressure_ledgers: list[TransactionPressureLedger] = Field(min_length=1)
    resource_authority_cases: list[ResourceAuthorityCase] = Field(min_length=1)
    public_claim_envelopes: list[PublicResourceClaimEnvelope] = Field(min_length=1)
    account_boundaries: list[AccountBoundaryRecord] = Field(min_length=1)
    account_federation: list[AccountFederationRegistry] = Field(min_length=1)
    expected_correspondence_envelopes: list[ExpectedCorrespondenceEnvelope] = Field(min_length=1)
    expected_mail_candidates: list[ExpectedMailCandidate] = Field(min_length=1)
    email_autonomy_events: list[EmailAutonomyEvent] = Field(min_length=1)
    calendar_write_envelopes: list[CalendarWriteEnvelope] = Field(min_length=1)
    calendar_obligations: list[CalendarObligation] = Field(min_length=1)
    payment_receipt_events: list[PaymentReceiptEvent] = Field(min_length=1)
    balance_snapshots: list[BalanceSnapshot] = Field(min_length=1)
    payout_reconciliation_records: list[PayoutReconciliationRecord] = Field(min_length=1)
    dispute_monitor_events: list[DisputeMonitorEvent] = Field(min_length=1)
    refund_drafts: list[RefundDraft] = Field(min_length=1)
    tax_evidence_packets: list[TaxEvidencePacket] = Field(min_length=1)
    provider_notice_events: list[ProviderNoticeEvent] = Field(min_length=1)
    resource_credit_receipts: list[ResourceCreditReceipt] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_fixture_contract(self) -> Self:
        required = set(self.required_models)
        if required != REQUIRED_MODELS:
            missing = REQUIRED_MODELS - required
            extra = required - REQUIRED_MODELS
            raise ValueError(
                f"required_models mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
            )

        forbidden = {scope.value for scope in self.forbidden_provider_write_scopes}
        if forbidden != FORBIDDEN_PROVIDER_WRITE_SCOPES:
            raise ValueError("forbidden_provider_write_scopes does not match contract")

        if any(envelope.claim_allowed for envelope in self.public_claim_envelopes):
            raise ValueError("fixture set cannot default public claims to allowed")

        if not any(
            event.hard_boundary and event.avoidability is AvoidabilityClass.EXTERNAL_HARD_BOUNDARY
            for event in self.autonomy_debt_events
        ):
            raise ValueError("fixtures must include hard-boundary autonomy debt")

        if not any(
            opportunity.decision_state is DecisionState.BLOCKED_STALE_CONFLICT
            for opportunity in self.opportunities
        ):
            raise ValueError("fixtures must include blocked_stale_conflict opportunity")

        return self


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ResourceCapabilityError(f"{path} did not contain a JSON object")
    return payload


def load_resource_capability_fixtures(
    path: Path = RESOURCE_CAPABILITY_FIXTURES,
) -> ResourceCapabilityFixtureSet:
    """Load resource-capability fixtures, failing closed on malformed data."""

    try:
        return ResourceCapabilityFixtureSet.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ResourceCapabilityError(
            f"invalid resource capability fixtures at {path}: {exc}"
        ) from exc


_PYDANTIC_DYNAMIC_ENTRYPOINTS = (
    ResourceOpportunity._stale_conflicts_fail_closed,
    ResourceCapability._public_claims_need_gate,
    MonetaryCapability._monetary_is_resource_subtype,
    AutonomyDebtEvent._hard_boundaries_remain_debt,
    MeasurementActionContract._action_metrics_need_semantics,
    GrowthNoGoRule._forbidden_scopes_are_blocked,
    GrowthNoGoMatrix._covers_every_forbidden_scope,
    GrowthNoGoMatrix.decision_for,
    SemanticTransactionTrace._trace_stays_private,
    TransactionPressureLedger._pressure_ledger_covers_semantic_surfaces,
    PublicResourceClaimEnvelope._claims_fail_closed_without_evidence,
    ExpectedMailCandidate._no_full_sender_address,
)


__all__ = [
    "FORBIDDEN_PROVIDER_WRITE_SCOPES",
    "REQUIRED_MODELS",
    "RESOURCE_CAPABILITY_FIXTURES",
    "RESOURCE_CAPABILITY_SCHEMA_REF",
    "AccountBoundaryRecord",
    "AccountFederationRegistry",
    "AutonomyDebtEvent",
    "AvoidabilityClass",
    "BalanceSnapshot",
    "CalendarObligation",
    "CalendarWriteEnvelope",
    "CapabilityAccount",
    "DecisionState",
    "ExpectedMailCandidate",
    "GrowthNoGoMatrix",
    "MonetaryCapability",
    "NoGoDecision",
    "ProviderWriteScope",
    "PublicClaimCeiling",
    "PublicResourceClaimEnvelope",
    "ResourceCapability",
    "ResourceCapabilityError",
    "ResourceCapabilityFixtureSet",
    "ResourceClass",
    "ResourceOpportunity",
    "ResourceAuthorityCase",
    "ResourceValuation",
    "SemanticTransactionKind",
    "SemanticTransactionTrace",
    "TransactionPressureLedger",
    "load_resource_capability_fixtures",
]
