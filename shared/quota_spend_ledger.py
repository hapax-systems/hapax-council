"""Inert quota and spend ledger models for capacity routing.

This module validates local ledger fixtures and computes fail-closed paid/API
route eligibility. It does not call providers, read credentials, alter billing,
dispatch work, or mutate runtime state.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_serializer,
    model_validator,
)

from shared.agentic_trust_boundary import is_agentic_trust_supply_evidence_reference

REPO_ROOT = Path(__file__).resolve().parents[1]
QUOTA_SPEND_LEDGER_FIXTURES = REPO_ROOT / "config" / "quota-spend-ledger-fixtures.json"

QUOTA_SPEND_LEDGER_LIVE_ENV = "HAPAX_QUOTA_SPEND_LEDGER_LIVE"
DEFAULT_QUOTA_SPEND_LEDGER_LIVE = (
    Path.home() / ".cache" / "hapax" / "orchestration" / "quota-spend-ledger-live.json"
)

PAID_CAPACITY_POOLS = frozenset({"api_paid_spend", "bootstrap_budget", "incident_override"})
CLAUDE_RECEIPT_BOUNDED_SUBSCRIPTION_ROUTES = frozenset(
    {"claude.headless.full", "claude.review.opus"}
)
RECEIPT_BOUNDED_SUBSCRIPTION_ROUTES = frozenset(
    {
        "agy.review.direct",
        "glmcp.review.direct",
        "kimi.interactive.lane",
        *CLAUDE_RECEIPT_BOUNDED_SUBSCRIPTION_ROUTES,
    }
)
RECEIPT_BOUNDED_SUBSCRIPTION_PROVIDERS = {
    "agy.review.direct": "google-antigravity-cli-agy",
    "glmcp.review.direct": "z_ai-glm-coding-plan",
    "claude.headless.full": "anthropic-claude-subscription",
    "claude.review.opus": "anthropic-claude-subscription",
    "kimi.interactive.lane": "moonshot-kimi-code-managed",
}
GLMCP_QUOTA_TELEMETRY_WRITER_REF = "scripts/hapax-quota-telemetry-writer"
AGY_ADMISSION_SUPPORTED_TOOL = "hapax-agy-reviewer"
AGY_ADMISSION_MODEL = "gemini-3.1-pro-high"
AGY_ADMISSION_MODELS = frozenset({AGY_ADMISSION_MODEL, "gemini-3.1-pro-preview"})
AGY_ADMISSION_RECEIPT_LABEL_RE = re.compile(
    r"\Arelay-receipt:"
    r"(?:[a-z0-9_.+-]*agy-quota-admission[a-z0-9_.+-]*\.yaml|"
    r"unsafe-receipt-name-sha256:[0-9a-f]{16})"
    r":witness:"
)
AGY_ADMISSION_EVIDENCE_REF_RE = re.compile(r"\A[a-z0-9][a-z0-9_.+-]{2,239}\Z")
AGY_ADMISSION_SECRETISH_RE = re.compile(
    r"(?:api[_-]?key|bearer|secret|token|sk-[a-z0-9_-]+|[a-z0-9]{32,})",
    re.IGNORECASE,
)
AGY_ADMISSION_WITNESS_REF_RE = re.compile(r":witness:([^:]+):supported_tool:")
KIMI_ADMISSION_SUPPORTED_TOOL = "hapax-kimi-quota-admission"
KIMI_ADMISSION_MODEL = "kimi-code/k3"
KIMI_ADMISSION_MODELS = frozenset({KIMI_ADMISSION_MODEL})
KIMI_ADMISSION_RECEIPT_LABEL_RE = re.compile(
    r"\Arelay-receipt:"
    r"(?:[a-z0-9_.+-]*kimi-quota-admission[a-z0-9_.+-]*\.yaml|"
    r"unsafe-receipt-name-sha256:[0-9a-f]{16})"
    r":witness:"
)
KIMI_ADMISSION_EVIDENCE_REF_RE = re.compile(r"\A[a-z0-9][a-z0-9_.+-]{2,239}\Z")
KIMI_ADMISSION_SECRETISH_RE = re.compile(
    r"(?:api[_-]?key|bearer|secret|token|sk-[a-z0-9_-]+|[a-z0-9]{32,})",
    re.IGNORECASE,
)
KIMI_ADMISSION_WITNESS_REF_RE = re.compile(r":witness:([^:]+):supported_tool:")
# Claude subscription-quota admission (scripts/hapax-claude-subscription-quota-admission →
# hapax-quota-telemetry-writer). The composite ledger evidence ref MUST end in the account-live
# suffix so the availability guarantor's _account_live_quota_observed_ref attests; lane/session
# presence never produces this ref (the writer refuses lane/tmux witnesses).
CLAUDE_ADMISSION_OBSERVATIONS = frozenset(
    {
        "subscription_quota_headroom_observed",
        "operator_confirmed_subscription_headroom",
    }
)
CLAUDE_ADMISSION_ACCOUNT_LIVE_QUOTA_SUFFIX = ":account-live-quota:observed"
CLAUDE_ADMISSION_OBSERVATION_PATTERN = "|".join(
    re.escape(observation) for observation in sorted(CLAUDE_ADMISSION_OBSERVATIONS)
)
CLAUDE_ADMISSION_WITNESS_PATTERN = (
    r"claude-(?:subscription-headroom-observed|operator-confirmed-subscription-headroom)-"
    r"\d{8}t\d{4}(?:\d{2})?z"
)
CLAUDE_ADMISSION_WITNESS_ALLOWLIST_RE = re.compile(rf"\A{CLAUDE_ADMISSION_WITNESS_PATTERN}\Z")
CLAUDE_ADMISSION_RECEIPT_LABEL_RE = re.compile(
    r"\Arelay-receipt:"
    r"(?P<label>[a-z0-9_.+-]*claude-subscription-quota-admission[a-z0-9_.+-]*\.yaml)"
    r":witness:"
)
CLAUDE_ADMISSION_COMPOSITE_REF_RE = re.compile(
    r"\Arelay-receipt:"
    r"(?P<label>[a-z0-9_.+-]*claude-subscription-quota-admission[a-z0-9_.+-]*\.yaml):"
    rf"witness:(?P<witness>{CLAUDE_ADMISSION_WITNESS_PATTERN}):"
    rf"observation:(?P<observation>{CLAUDE_ADMISSION_OBSERVATION_PATTERN}):"
    r"observed_at:(?P<observed_at>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z):"
    r"fresh_until:(?P<fresh_until>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)"
    rf"{re.escape(CLAUDE_ADMISSION_ACCOUNT_LIVE_QUOTA_SUFFIX)}\Z"
)
CLAUDE_ADMISSION_EVIDENCE_REF_RE = re.compile(r"\A[a-z0-9][a-z0-9_.+-]{2,239}\Z")
CLAUDE_ADMISSION_SECRETISH_RE = re.compile(
    r"(?:api[_-]?key|bearer|secret|token|sk-[a-z0-9_-]+|[a-z0-9]{32,})",
    re.IGNORECASE,
)
CLAUDE_ADMISSION_BILLINGISH_RE = re.compile(
    r"(?:"
    r"(?:^|[-_.+:])(?:billing|customer|account|invoice|payment)[a-z0-9]*(?:$|[-_.+:])|"
    r"(?:^|[-_.+:])subscription[-_.+:]?id[a-z0-9]*(?:$|[-_.+:])|"
    r"(?:^|[-_.+:])(?:cus|sub|acct|in|ch)[0-9][a-z0-9]*(?:$|[-_.+:])|"
    r"(?:^|[-_.+:])(?:cus|sub|acct|in|ch)[-_.+:][a-z0-9]+(?:$|[-_.+:])"
    r")",
    re.IGNORECASE,
)
CLAUDE_ADMISSION_LANE_PRESENCE_RE = re.compile(
    r"(?:"
    r"hapax-claude-[a-z0-9-]+|session-present|lane-present|lane-exists|"
    r"(?:^|[-_.+])"
    r"(?:(?:tmux|sessions?|lanes?|dev)[0-9]*|"
    r"(?:alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|"
    r"lambda|mu|nu|xi|omicron|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega)[0-9]*|"
    r"cx-[a-z0-9-]+|vbe-[0-9]+)"
    r"(?:$|[-_.+])"
    r")",
    re.IGNORECASE,
)
CLAUDE_ADMISSION_IGNORED_REASON_RE = re.compile(r"\A[a-z0-9][a-z0-9-]{0,119}\Z")
CLAUDE_ADMISSION_IGNORED_UNSAFE_DETAIL_RE = re.compile(
    r"(?:"
    r"(?:^|-)(?:cus|sub|acct|in|ch)-[a-z0-9]+(?:$|-)|"
    r"(?:^|-)subscription-?id-?[a-z0-9]*[0-9][a-z0-9]*(?:$|-)|"
    r"(?:^|-)(?:customer|account|invoice|payment|billing)[a-z0-9-]*[0-9][a-z0-9-]*(?:$|-)|"
    r"(?:^|-)(?:session-present|lane-present|lane-exists)(?:$|-)|"
    r"(?:^|-)(?:tmux|sessions?|lanes?|dev)[0-9]+(?:$|-)|"
    r"(?:^|-)(?:alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|"
    r"lambda|mu|nu|xi|omicron|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega)[0-9]*(?:$|-)|"
    r"(?:^|-)(?:cx-[a-z0-9-]+|vbe-[0-9]+|hapax-claude-[a-z0-9-]+)(?:$|-)"
    r")",
    re.IGNORECASE,
)
CLAUDE_ADMISSION_WITNESS_REF_RE = re.compile(r":witness:([^:]+):observation:")
GLMCP_ADMISSION_CODING_PLAN_ENDPOINT = "https://api.z.ai/api/coding/paas/v4"
GLMCP_ADMISSION_PAYG_ENDPOINT = "https://api.z.ai/api/paas/v4"
GLMCP_PAYG_BUDGET_ROUTE_ID = "glmcp.review.direct"
GLMCP_PAYG_BUDGET_PROVIDER = "z_ai"
GLMCP_PAYG_BUDGET_PROFILE = "glmcp-review-direct"
GLMCP_PAYG_BUDGET_TASK_CLASS = "independent-review"
GLMCP_PAYG_BUDGET_QUALITY_FLOOR = "frontier_review_required"
# Nominal amount for "can this budget still admit a GLMCP PAYG call" checks (seat admission,
# review-team constitution). A real call reserves glmcp_payg_reservation_usd(...) instead.
GLMCP_PAYG_ESTIMATED_COST_USD = "0.05"
GLMCP_ADMISSION_TOOL_ENDPOINTS = {
    "hapax-glmcp-reviewer": frozenset(
        {
            GLMCP_ADMISSION_CODING_PLAN_ENDPOINT,
            GLMCP_ADMISSION_PAYG_ENDPOINT,
        }
    ),
}
GLMCP_ADMISSION_SUPPORTED_TOOLS = frozenset(GLMCP_ADMISSION_TOOL_ENDPOINTS)
GLMCP_ADMISSION_ENDPOINTS = frozenset(
    endpoint for endpoints in GLMCP_ADMISSION_TOOL_ENDPOINTS.values() for endpoint in endpoints
)
# Mirrors scripts/hapax-quota-telemetry-writer and the direct
# scripts/hapax-glmcp-reviewer route metadata. glm-5.3 is the reviewer's default since #4692;
# glm-5.2 stays admitted because the seat refresh and older receipts still name it. Each
# request id maps to exactly one structured ModelId — a receipt never borrows another's.
GLMCP_ADMISSION_MODELS = frozenset({"glm-5.3", "glm-5.2"})
GLMCP_MODEL_IDS = {"glm-5.3": "z_ai-glm-5.3", "glm-5.2": "z_ai-glm-5.2"}
# Z.ai PAYG list prices, USD per 1M tokens, from https://docs.z.ai/guides/overview/pricing
# (retrieved 2026-09-24): GLM-5.3 and GLM-5.2 each $1.4 input, $0.26 cached input, $4.4 output.
# The page prices only input, cached input and output tokens, no separate reasoning rate.
# Reasoning is counted inside completion_tokens: the 2026-09-24T19:20:12Z PAYG probe of glm-5.3
# reported completion_tokens 57 with completion_tokens_details.reasoning_tokens 51 (vault
# 30-areas/hapax/frame/coordinator-succession-20260924/glm-payg/probe-20260924T192011Z.json),
# so pricing completion_tokens at the output rate covers reasoning.
GLMCP_PAYG_PRICE_BASIS_REF = "docs.z.ai-guides-overview-pricing-20260924"
GLMCP_PAYG_PRICES_USD_PER_MTOK = {
    model: {
        "input": Decimal("1.40"),
        "cached_input": Decimal("0.26"),
        "output": Decimal("4.40"),
    }
    for model in ("glm-5.3", "glm-5.2")
}
# Chat-template tokens the provider adds around the messages; generous so the bound holds.
GLMCP_PAYG_TEMPLATE_TOKEN_ALLOWANCE = 256
GLMCP_PAYG_COST_QUANTUM = Decimal("0.000001")
GLMCP_ADMISSION_RECEIPT_LABEL_RE = re.compile(
    r"\Arelay-receipt:"
    r"(?:[a-z0-9_.+-]*glmcp-quota-admission[a-z0-9_.+-]*\.yaml|"
    r"unsafe-receipt-name-sha256:[0-9a-f]{16})"
    r":witness:"
)
GLMCP_ADMISSION_EVIDENCE_REF_RE = re.compile(r"\A[a-z0-9][a-z0-9_.+-]{2,239}\Z")
GLMCP_ADMISSION_SECRETISH_RE = re.compile(
    r"(?:api[_-]?key|bearer|secret|token|sk-[a-z0-9_-]+|[a-z0-9]{32,})",
    re.IGNORECASE,
)
GLMCP_ADMISSION_WITNESS_REF_RE = re.compile(r":witness:([^:]+):supported_tool:")
GLMCP_ADMISSION_SUPPORTED_TOOL_REF_RE = re.compile(r":supported_tool:([a-z0-9_.+-]+):")
GLMCP_PAYG_PRIMARY_ERROR_CLASSES = frozenset({"daily_limit_exhausted", "quota_exhausted"})
GLMCP_PAYG_PRIMARY_ERROR_CLASS_REF_RE = re.compile(r":primary_error_class:([^:]+):")
GLMCP_PAYG_QUOTA_WALL_REF_RE = re.compile(r":quota_wall_evidence_ref:([^:]+):")


class QuotaSpendLedgerError(ValueError):
    """Raised when quota/spend ledger data cannot be trusted."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CapacityPool(StrEnum):
    SUBSCRIPTION_QUOTA = "subscription_quota"
    LOCAL_COMPUTE = "local_compute"
    API_PAID_SPEND = "api_paid_spend"
    BOOTSTRAP_BUDGET = "bootstrap_budget"
    STEADY_STATE_TARGET = "steady_state_target"
    INCIDENT_OVERRIDE = "incident_override"


class AuthSurface(StrEnum):
    SUBSCRIPTION = "subscription"
    API_KEY = "api_key"
    VERTEX = "vertex"
    LOCAL = "local"
    UNKNOWN = "unknown"


class Quantization(StrEnum):
    # byte-identical to shared.platform_capability_registry.Quantization, mirrored here so the
    # low-dependency ledger never imports the registry (a value-set drift-pin guards the parity).
    NONE = "none"
    EXL3_4_0BPW = "exl3_4_0bpw"
    EXL3_5_0BPW = "exl3_5_0bpw"
    NOT_APPLICABLE = "not_applicable"


class Effort(StrEnum):
    # mirrored from shared.platform_capability_registry.Effort (dependency-direction: the inert
    # ledger never imports the registry); a value-set drift-pin guards the parity.
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class ModelId(StrEnum):
    # mirrored from shared.platform_capability_registry.ModelId — the structured dated identity that
    # replaces the coarse free-text model_or_engine for spend metering; drift-pinned to the registry.
    CLAUDE_OPUS_4_8 = "claude-opus-4-8"
    CLAUDE_OPUS_4_6 = "claude-opus-4-6"
    CLAUDE_SONNET_4_6 = "claude-sonnet-4-6"
    CLAUDE_SONNET_5 = "claude-sonnet-5"
    CLAUDE_HAIKU_4_5 = "claude-haiku-4-5"
    CLAUDE_FABLE_5 = "claude-fable-5"
    GPT_5_5 = "gpt-5.5"
    GPT_6_ASTRA = "gpt-6-astra"
    GPT_5_3_CODEX_SPARK = "gpt-5.3-codex-spark"
    GPT_OSS_120B = "gpt-oss-120b"
    COMMAND_R_08_2024 = "command-r-08-2024"
    QWEN3_5_9B = "qwen3.5-9b"
    MISTRAL_MEDIUM_3_5 = "mistral-medium-3.5"
    GEMINI_3_1_PRO_PREVIEW = "gemini-3.1-pro-preview"
    GEMINI_3_5_FLASH = "gemini-3.5-flash"
    Z_AI_GLM_5 = "z_ai-glm-5"
    Z_AI_GLM_5_2 = "z_ai-glm-5.2"
    Z_AI_GLM_5_3 = "z_ai-glm-5.3"
    KIMI_K3 = "kimi-code/k3"
    UNKNOWN = "unknown"


class BudgetApproval(StrEnum):
    OPERATOR = "operator"
    LATER_AUTHORITY_PACKET = "later_authority_packet"


class BudgetLifecycleState(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"
    REVOKED = "revoked"


class SpendReason(StrEnum):
    QUOTA_EXHAUSTION = "quota_exhaustion"
    BURST_CAPACITY = "burst_capacity"
    BOOTSTRAP_EQUILIBRIUM = "bootstrap_equilibrium"
    RETRY_AFTER = "retry_after"
    QUALITY_ESCALATION = "quality_escalation"


class SpendReconciliationState(StrEnum):
    PENDING = "pending"
    RECONCILED = "reconciled"
    FROZEN_REFUSED = "frozen_refused"
    # Resolved without a per-call figure: a provider balance observed after the spend settled
    # already reflects it (settle_spend_covered_by_provider_balance). No actual is claimed.
    SETTLED_BY_PROVIDER_BALANCE = "settled_by_provider_balance"


class SupportArtifactAuthority(StrEnum):
    NONE = "none"
    SUPPORT_NON_AUTHORITATIVE = "support_non_authoritative"
    ACCEPTED_AUTHORITATIVE = "accepted_authoritative"


class SupportArtifactDisposition(StrEnum):
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    RETIRED = "retired"


class DependencyState(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"
    REPLACED = "replaced"


class SubscriptionQuotaState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"
    EXHAUSTED = "exhausted"


class PaidApiBudgetState(StrEnum):
    NONE = "none"
    ACTIVE = "active"
    EXPIRED = "expired"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"


class BootstrapDependencyState(StrEnum):
    NONE = "none"
    ACTIVE = "active"
    EXPIRED = "expired"
    REPLACEMENT_OVERDUE = "replacement_overdue"


class LocalResourceState(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    STALE = "stale"
    UNKNOWN = "unknown"


class RouteAvailability(StrEnum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class SpendGateDecisionState(StrEnum):
    ELIGIBLE_ACTIVE_BUDGET = "eligible_active_budget"
    REFUSED_NO_MATCHING_BUDGET = "refused_no_matching_budget"
    REFUSED_EXPIRED_BUDGET = "refused_expired_budget"
    REFUSED_EXHAUSTED_BUDGET = "refused_exhausted_budget"
    REFUSED_STALE_BUDGET_LEDGER = "refused_stale_budget_ledger"
    REFUSED_UNRECONCILED_SPEND = "refused_unreconciled_spend"
    REFUSED_BUDGET_GATE = "refused_budget_gate"


class SteadyStateReplacement(StrictModel):
    target_route_id: str | None = None
    blocker_to_remove: str | None = None
    exit_criterion: str | None = None

    def complete(self) -> bool:
        return all((self.target_route_id, self.blocker_to_remove, self.exit_criterion))


PROVIDER_BALANCE_FIELDS = (
    "provider_balance_usd",
    "provider_balance_observed_at",
    "provider_balance_covers_spend_before",
    "provider_balance_evidence_ref",
)


class TransitionBudget(StrictModel):
    """Time-boxed paid/API authority. Dates and caps are gates, not hints."""

    budget_schema: Literal[1] = 1
    budget_id: str = Field(pattern=r"^tb-\d{8}-[a-z0-9-]+$")
    authority_case: str = Field(min_length=1)
    approved_by: BudgetApproval
    created_at: datetime
    expires_at: datetime
    capacity_pool: CapacityPool
    providers_allowed: tuple[str, ...] = Field(min_length=1)
    profiles_allowed: tuple[str, ...] = Field(min_length=1)
    task_classes_allowed: tuple[str, ...] = Field(min_length=1)
    quality_floors_allowed: tuple[str, ...] = Field(min_length=1)
    total_cap_usd: Decimal = Field(ge=Decimal("0"))
    per_task_cap_usd: Decimal = Field(ge=Decimal("0"))
    daily_cap_usd: Decimal = Field(ge=Decimal("0"))
    auto_top_up_allowed: Literal[False] = False
    subscription_path_checked_at: datetime | None = None
    reason_subscription_path_not_used: str | None = None
    steady_state_replacement: SteadyStateReplacement = Field(default_factory=SteadyStateReplacement)
    ledger_owner: str | None = None
    dashboard_visibility: Literal["required"] = "required"
    lifecycle_state: BudgetLifecycleState = BudgetLifecycleState.ACTIVE
    # A provider-reported balance the cap was set from. Spend that settled before
    # ``provider_balance_covers_spend_before`` is already out of that balance, so unresolved
    # receipts from before it on *other* budgets cannot overspend it and do not block this one.
    provider_balance_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    provider_balance_observed_at: datetime | None = None
    provider_balance_covers_spend_before: datetime | None = None
    provider_balance_evidence_ref: str | None = None

    @model_validator(mode="after")
    def _budget_contract(self) -> Self:
        _require_aware(self.created_at, "created_at")
        _require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.created_at:
            raise ValueError(f"{self.budget_id} expires_at must be after created_at")
        balance = self.provider_balance_usd
        observed = self.provider_balance_observed_at
        covers = self.provider_balance_covers_spend_before
        evidence = self.provider_balance_evidence_ref
        if any(field is not None for field in (balance, observed, covers, evidence)):
            if (
                balance is None
                or observed is None
                or covers is None
                or not (evidence or "").strip()
            ):
                raise ValueError(f"{self.budget_id} provider balance evidence must be complete")
            _require_aware(observed, "provider_balance_observed_at")
            _require_aware(covers, "provider_balance_covers_spend_before")
            if covers > observed:
                raise ValueError(
                    f"{self.budget_id} a balance cannot cover spend after it was observed"
                )
            if self.total_cap_usd > balance:
                raise ValueError(f"{self.budget_id} total cap exceeds the observed balance")
        if self.capacity_pool.value not in PAID_CAPACITY_POOLS:
            raise ValueError(f"{self.budget_id} must use a paid/API capacity pool")
        if self.lifecycle_state is BudgetLifecycleState.ACTIVE:
            if self.total_cap_usd <= 0 or self.per_task_cap_usd <= 0 or self.daily_cap_usd <= 0:
                raise ValueError(f"{self.budget_id} active budgets require positive caps")
            if self.subscription_path_checked_at is None:
                raise ValueError(
                    f"{self.budget_id} active budgets require subscription path review"
                )
            _require_aware(self.subscription_path_checked_at, "subscription_path_checked_at")
            if not self.reason_subscription_path_not_used:
                raise ValueError(
                    f"{self.budget_id} active budgets require subscription-path rationale"
                )
        if self.capacity_pool is CapacityPool.BOOTSTRAP_BUDGET:
            if not self.steady_state_replacement.complete():
                raise ValueError(f"{self.budget_id} bootstrap budgets require replacement plan")
        if any(
            is_agentic_trust_supply_evidence_reference(value)
            for value in (
                *self.providers_allowed,
                *self.profiles_allowed,
                *self.task_classes_allowed,
                *self.quality_floors_allowed,
            )
        ):
            raise ValueError(
                "agentic-trust observation evidence cannot define transition-budget eligibility"
            )
        _reject_private_or_identity_refs(
            _refs(
                self.budget_id,
                self.authority_case,
                *self.providers_allowed,
                *self.profiles_allowed,
                *self.task_classes_allowed,
                *self.quality_floors_allowed,
                self.ledger_owner,
                self.provider_balance_evidence_ref,
            ),
            "transition budget",
        )
        return self

    @model_serializer(mode="wrap")
    def _serialize_without_absent_provider_balance(self, handler: Any) -> dict[str, Any]:
        # Budgets without provider balance evidence dump exactly as before the fields existed,
        # so governance records carry over byte-identical through the telemetry writer.
        payload = handler(self)
        for key in PROVIDER_BALANCE_FIELDS:
            if payload.get(key) is None:
                payload.pop(key, None)
        return payload

    def provider_balance_covers(self, receipt: SpendReceipt) -> bool:
        """Whether this budget's observed provider balance already reflects ``receipt``.

        Only the same provider's spend; never the budget's own spend; never spend after the
        settlement cut-off.
        """

        return (
            self.provider_balance_covers_spend_before is not None
            and receipt.provider in self.providers_allowed
            and receipt.budget_id != self.budget_id
            and receipt.created_at < self.provider_balance_covers_spend_before
        )

    def matches_request(self, request: PaidRouteRequest) -> bool:
        return (
            request.provider in self.providers_allowed
            and request.profile in self.profiles_allowed
            and request.task_class in self.task_classes_allowed
            and request.quality_floor in self.quality_floors_allowed
        )

    def is_unexpired_at(self, now: datetime) -> bool:
        return self.created_at <= now < self.expires_at


class SpendReceipt(StrictModel):
    """Estimated or reconciled spend event under a transition budget."""

    spend_receipt_schema: Literal[1] = 1
    spend_id: str = Field(pattern=r"^spend-\d{8}T\d{6}Z-[a-z0-9_.:-]+$")
    task_id: str = Field(min_length=1)
    task_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    authority_case: str = Field(min_length=1)
    route_id: str = Field(min_length=1)
    capacity_pool: CapacityPool
    budget_id: str | None = None
    provider: str = Field(min_length=1)
    model_or_engine: str | None = None
    # structured execution-axis metering, shared with the route's execution_descriptor:
    #   model_id  — the structured dated identity (model_or_engine stays as the legacy free text)
    #   effort    — reasoning effort the spend was incurred at (changes token cost)
    #   quantization — local-inference EXL3 bpw (separable per receipt)
    model_id: ModelId | None = None
    effort: Effort = Effort.NONE
    quantization: Quantization = Quantization.NOT_APPLICABLE
    auth_surface: AuthSurface
    quality_floor: str = Field(min_length=1)
    quality_preservation_reason: str = Field(min_length=1)
    spend_reason: SpendReason
    estimated_cost_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    actual_cost_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    cap_remaining_usd: Decimal | None = Field(default=None)
    created_at: datetime
    reconcile_by: datetime | None = None
    reconciliation_state: SpendReconciliationState = SpendReconciliationState.PENDING
    reconciled_at: datetime | None = None
    reconciliation_reason: str | None = None
    artifact_refs: tuple[str, ...] = Field(default=())
    support_artifact_authority: SupportArtifactAuthority = SupportArtifactAuthority.NONE

    @model_validator(mode="after")
    def _receipt_contract(self) -> Self:
        _require_aware(self.created_at, "created_at")
        if self.reconcile_by is not None:
            _require_aware(self.reconcile_by, "reconcile_by")
            if self.reconcile_by <= self.created_at:
                raise ValueError(f"{self.spend_id} reconcile_by must be after created_at")
        if self.capacity_pool.value in PAID_CAPACITY_POOLS:
            if not self.budget_id:
                raise ValueError(f"{self.spend_id} paid/API spend requires budget_id")
            if self.estimated_cost_usd is None and self.actual_cost_usd is None:
                raise ValueError(f"{self.spend_id} spend requires estimated or actual cost")
        if self.actual_cost_usd is None and self.estimated_cost_usd is not None:
            if self.reconcile_by is None:
                raise ValueError(f"{self.spend_id} estimated spend requires reconcile_by")
        if self.actual_cost_usd is not None and self.cap_remaining_usd is None:
            raise ValueError(f"{self.spend_id} reconciled spend requires cap_remaining_usd")
        if self.reconciled_at is not None:
            _require_aware(self.reconciled_at, "reconciled_at")
        if self.reconciliation_state is SpendReconciliationState.PENDING:
            if self.actual_cost_usd is not None:
                raise ValueError(f"{self.spend_id} actual spend requires reconciled state")
            if self.reconciled_at is not None or self.reconciliation_reason:
                raise ValueError(f"{self.spend_id} pending spend cannot carry reconciliation")
        elif self.reconciliation_state is SpendReconciliationState.RECONCILED:
            if self.actual_cost_usd is None:
                raise ValueError(f"{self.spend_id} reconciled spend requires actual cost")
            if self.reconciled_at is None or not self.reconciliation_reason:
                raise ValueError(f"{self.spend_id} reconciled spend requires review evidence")
        elif self.reconciliation_state is SpendReconciliationState.FROZEN_REFUSED:
            if self.actual_cost_usd is not None:
                raise ValueError(f"{self.spend_id} frozen/refused spend cannot claim actual cost")
            if self.reconciled_at is None or not self.reconciliation_reason:
                raise ValueError(f"{self.spend_id} frozen/refused spend requires review evidence")
        elif self.reconciliation_state is SpendReconciliationState.SETTLED_BY_PROVIDER_BALANCE:
            if self.actual_cost_usd is not None:
                raise ValueError(f"{self.spend_id} balance-settled spend cannot claim actual cost")
            if self.reconciled_at is None or not self.reconciliation_reason:
                raise ValueError(f"{self.spend_id} balance-settled spend requires its evidence")
        _reject_private_or_identity_refs(
            _refs(
                self.spend_id,
                self.task_id,
                self.task_hash,
                self.authority_case,
                self.route_id,
                self.budget_id,
                self.provider,
                self.model_or_engine,
                self.model_id.value if self.model_id is not None else None,
                self.effort.value,
                self.quantization.value,
                self.quality_floor,
                self.quality_preservation_reason,
                self.reconciliation_reason,
                *self.artifact_refs,
            ),
            "spend receipt",
        )
        return self

    @model_serializer(mode="wrap")
    def _serialize_without_empty_task_hash(self, handler: Any) -> dict[str, Any]:
        payload = handler(self)
        if payload.get("task_hash") is None:
            payload.pop("task_hash", None)
        return payload

    def cost_against_cap(self) -> Decimal:
        if self.actual_cost_usd is not None:
            return self.actual_cost_usd
        if self.estimated_cost_usd is not None:
            return self.estimated_cost_usd
        return Decimal("0")

    def is_unreconciled_overdue(self, now: datetime) -> bool:
        return (
            self.reconciliation_state is SpendReconciliationState.PENDING
            and self.actual_cost_usd is None
            and self.estimated_cost_usd is not None
            and self.reconcile_by is not None
            and self.reconcile_by <= now
        )

    def is_frozen_refused(self) -> bool:
        return self.reconciliation_state is SpendReconciliationState.FROZEN_REFUSED


class ProviderDependencyRecord(StrictModel):
    dependency_schema: Literal[1] = 1
    dependency_id: str = Field(pattern=r"^dep-[a-z0-9_.:-]+$")
    route_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    capacity_pool: CapacityPool
    dependency_state: DependencyState = DependencyState.ACTIVE
    recurring: bool
    critical_path: bool
    transition_budget_id: str | None = None
    first_seen_at: datetime
    review_by: datetime
    last_reviewed_at: datetime | None = None
    replacement_route_id: str | None = None
    bootstrap_dependency: bool
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    operator_visible_reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _dependency_contract(self) -> Self:
        _require_aware(self.first_seen_at, "first_seen_at")
        _require_aware(self.review_by, "review_by")
        if self.review_by <= self.first_seen_at:
            raise ValueError(f"{self.dependency_id} review_by must be after first_seen_at")
        if self.last_reviewed_at is not None:
            _require_aware(self.last_reviewed_at, "last_reviewed_at")
        if self.dependency_state is DependencyState.REPLACED and not self.replacement_route_id:
            raise ValueError(f"{self.dependency_id} replaced dependencies need replacement route")
        if self.dependency_state is not DependencyState.ACTIVE and self.last_reviewed_at is None:
            raise ValueError(f"{self.dependency_id} closed dependencies need review timestamp")
        if self.bootstrap_dependency:
            if self.capacity_pool is not CapacityPool.BOOTSTRAP_BUDGET:
                raise ValueError(f"{self.dependency_id} bootstrap dependencies need bootstrap pool")
            if not self.transition_budget_id:
                raise ValueError(f"{self.dependency_id} bootstrap dependencies need budget ref")
        _reject_private_or_identity_refs(
            _refs(
                self.dependency_id,
                self.route_id,
                self.provider,
                self.transition_budget_id,
                self.replacement_route_id,
                *self.evidence_refs,
                self.operator_visible_reason,
            ),
            "provider dependency",
        )
        return self


class ArtifactProvenanceRecord(StrictModel):
    provenance_schema: Literal[1] = 1
    provenance_id: str = Field(pattern=r"^prov-[a-z0-9_.:-]+$")
    artifact_refs: tuple[str, ...] = Field(min_length=1)
    produced_by_route_id: str = Field(min_length=1)
    produced_under_budget_id: str | None = None
    source_spend_receipt_ids: tuple[str, ...] = Field(default=())
    support_artifact_authority: SupportArtifactAuthority
    artifact_disposition: SupportArtifactDisposition = SupportArtifactDisposition.PENDING_REVIEW
    accepted_by_route_id: str | None = None
    accepted_at: datetime | None = None
    disposition_reviewed_at: datetime | None = None
    disposition_reason: str | None = None
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    operator_visible_reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _provenance_contract(self) -> Self:
        if self.accepted_at is not None:
            _require_aware(self.accepted_at, "accepted_at")
        if self.disposition_reviewed_at is not None:
            _require_aware(self.disposition_reviewed_at, "disposition_reviewed_at")
        if self.support_artifact_authority is SupportArtifactAuthority.ACCEPTED_AUTHORITATIVE:
            if not self.accepted_by_route_id or self.accepted_at is None:
                raise ValueError(f"{self.provenance_id} accepted artifacts require acceptor")
            if self.artifact_disposition is not SupportArtifactDisposition.ACCEPTED:
                raise ValueError(
                    f"{self.provenance_id} accepted artifacts need accepted disposition"
                )
        else:
            if self.accepted_by_route_id or self.accepted_at is not None:
                raise ValueError(
                    f"{self.provenance_id} non-authoritative artifacts cannot carry acceptance"
                )
            if self.artifact_disposition is SupportArtifactDisposition.ACCEPTED:
                raise ValueError(
                    f"{self.provenance_id} accepted disposition requires authoritative acceptance"
                )
        if self.artifact_disposition in {
            SupportArtifactDisposition.REJECTED,
            SupportArtifactDisposition.RETIRED,
        }:
            if self.disposition_reviewed_at is None or not self.disposition_reason:
                raise ValueError(f"{self.provenance_id} closed artifacts require disposition")
        if (
            self.produced_under_budget_id
            and self.support_artifact_authority is SupportArtifactAuthority.NONE
        ):
            raise ValueError(
                f"{self.provenance_id} budget-produced artifacts require authority marker"
            )
        _reject_private_or_identity_refs(
            _refs(
                self.provenance_id,
                *self.artifact_refs,
                self.produced_by_route_id,
                self.produced_under_budget_id,
                *self.source_spend_receipt_ids,
                self.accepted_by_route_id,
                self.disposition_reason,
                *self.evidence_refs,
                self.operator_visible_reason,
            ),
            "artifact provenance",
        )
        return self

    def waiting_for_review(self) -> bool:
        return (
            self.produced_under_budget_id is not None
            and self.support_artifact_authority
            is SupportArtifactAuthority.SUPPORT_NON_AUTHORITATIVE
            and self.artifact_disposition is SupportArtifactDisposition.PENDING_REVIEW
        )


class RenewalRecord(StrictModel):
    renewal_schema: Literal[1] = 1
    renewal_id: str = Field(pattern=r"^renew-[a-z0-9_.:-]+$")
    provider: str = Field(min_length=1)
    auth_surface: AuthSurface
    capacity_pool: CapacityPool
    recurring_cost_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    subscription_renewal_at: datetime | None = None
    top_up_enabled: Literal[False] = False
    hard_expiry_review_at: datetime
    cancellation_or_exit_ref: str | None = None
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    operator_visible_reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _renewal_contract(self) -> Self:
        if self.subscription_renewal_at is not None:
            _require_aware(self.subscription_renewal_at, "subscription_renewal_at")
        _require_aware(self.hard_expiry_review_at, "hard_expiry_review_at")
        if self.capacity_pool.value in PAID_CAPACITY_POOLS and self.recurring_cost_usd is None:
            raise ValueError(f"{self.renewal_id} paid/API renewals require cost marker")
        _reject_private_or_identity_refs(
            _refs(
                self.renewal_id,
                self.provider,
                self.cancellation_or_exit_ref,
                *self.evidence_refs,
                self.operator_visible_reason,
            ),
            "renewal",
        )
        return self


class QuotaMeasurement(StrictModel):
    """A measurement is evidence, never an admission or a spend authorization."""

    capacity_id: str = Field(min_length=1)
    quantity: float | None = Field(default=None, allow_inf_nan=False)
    unit: str | None = None
    window: str | None = None
    resets_at: datetime | None = None
    label: Literal["observed", "derived", "wall-signal", "operator-reported", "unobserved"] = (
        "unobserved"
    )
    source: str = "none"
    observed_at: datetime | None = None
    measurement_fresh_until: datetime | None = None
    reason_code: str | None = None
    details: dict[str, int | float | str | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _measurement_contract(self) -> Self:
        for key in ("resets_at", "observed_at", "measurement_fresh_until"):
            value = getattr(self, key)
            if value is not None:
                _require_aware(value, key)
        if self.label in {"observed", "derived"} and self.quantity is None:
            raise ValueError("observed/derived measurements require a quantity")
        if self.label in {"wall-signal", "unobserved"} and self.quantity is not None:
            raise ValueError("walls and missing evidence cannot become a fraction")
        if self.label != "unobserved" and self.observed_at is None:
            raise ValueError("evidence requires its source time")
        if self.label == "unobserved" and not self.reason_code:
            raise ValueError("unobserved measurements require a reason_code")
        return self

    def measurement_is_fresh(self, now: datetime) -> bool:
        return (
            self.observed_at is not None
            and self.measurement_fresh_until is not None
            and self.observed_at <= now < self.measurement_fresh_until
        )


class QuotaSnapshot(QuotaMeasurement):
    quota_snapshot_schema: Literal[1, 2] = 1
    capacity_id: str = "legacy.unmeasured"
    reason_code: str | None = "legacy_binary_snapshot"
    family: str = "unknown"
    stage: Literal[
        "unusable", "usable-undeclared", "declared-unmeasured", "declared-measured", "routable"
    ] = "declared-unmeasured"
    next_act: str = "Collect a local quantity with source and observation time"
    owner: Literal["operator", "source", "runtime"] = "source"
    measurements: tuple[QuotaMeasurement, ...] = ()
    # Measurement-only rows must never participate in legacy admission decisions.
    admission_compatible: bool = True
    snapshot_id: str = Field(pattern=r"^quota-[a-z0-9_.:-]+$")
    captured_at: datetime
    fresh_until: datetime | None = None
    route_id: str | None = Field(default=None, min_length=1)
    provider: str = Field(min_length=1)
    capacity_pool: CapacityPool
    subscription_quota_state: SubscriptionQuotaState
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    operator_visible_reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _quota_snapshot_contract(self) -> Self:
        _require_aware(self.captured_at, "captured_at")
        if self.route_id is None and self.admission_compatible:
            raise ValueError("an undeclared capacity cannot carry route admission")
        if self.fresh_until is not None:
            _require_aware(self.fresh_until, "fresh_until")
            if self.fresh_until <= self.captured_at:
                raise ValueError(f"{self.snapshot_id} fresh_until must be after captured_at")
        _reject_private_or_identity_refs(
            [
                self.snapshot_id,
                self.route_id or "undeclared",
                self.provider,
                *self.evidence_refs,
                self.operator_visible_reason,
            ],
            "quota snapshot",
        )
        return self


class PaidRouteRequest(StrictModel):
    route_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    profile: str = Field(min_length=1)
    task_class: str = Field(min_length=1)
    quality_floor: str = Field(min_length=1)
    estimated_cost_usd: Decimal = Field(gt=Decimal("0"))
    capacity_pool: CapacityPool = CapacityPool.API_PAID_SPEND

    @model_validator(mode="after")
    def _paid_route_request_contract(self) -> Self:
        if self.capacity_pool.value not in PAID_CAPACITY_POOLS:
            raise ValueError("paid route eligibility can only evaluate paid/API capacity pools")
        if any(
            is_agentic_trust_supply_evidence_reference(value)
            for value in (
                self.route_id,
                self.provider,
                self.profile,
                self.task_class,
                self.quality_floor,
            )
        ):
            raise ValueError(
                "agentic-trust observation evidence cannot define paid-route eligibility"
            )
        _reject_private_or_identity_refs(
            [
                self.route_id,
                self.task_id,
                self.provider,
                self.profile,
                self.task_class,
                self.quality_floor,
            ],
            "paid route request",
        )
        return self


class PaidRouteEligibility(StrictModel):
    eligible: bool
    state: str
    budget_id: str | None = None
    cap_remaining_usd: Decimal | None = None
    blocking_reasons: tuple[str, ...] = Field(default=())
    evidence_refs: tuple[str, ...] = Field(default=())


class SpendGateDecisionRecord(StrictModel):
    """Recorded paid/API gate decision, including rejected decisions."""

    decision_schema: Literal[1] = 1
    decision_id: str = Field(pattern=r"^sgd-[a-z0-9_.:-]+$")
    created_at: datetime
    route_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    profile: str = Field(min_length=1)
    task_class: str = Field(min_length=1)
    quality_floor: str = Field(min_length=1)
    capacity_pool: CapacityPool
    requested_cost_usd: Decimal = Field(ge=Decimal("0"))
    decision_state: SpendGateDecisionState
    eligible: bool
    budget_id: str | None = None
    blocking_reasons: tuple[str, ...] = Field(default=())
    evidence_refs: tuple[str, ...] = Field(default=())

    @model_validator(mode="after")
    def _decision_contract(self) -> Self:
        _require_aware(self.created_at, "created_at")
        if self.capacity_pool.value not in PAID_CAPACITY_POOLS:
            raise ValueError(f"{self.decision_id} spend gates require paid/API pool")
        if self.eligible:
            if self.decision_state is not SpendGateDecisionState.ELIGIBLE_ACTIVE_BUDGET:
                raise ValueError(f"{self.decision_id} eligible decisions need eligible state")
            if not self.budget_id:
                raise ValueError(f"{self.decision_id} eligible decisions require budget_id")
            if self.blocking_reasons:
                raise ValueError(f"{self.decision_id} eligible decisions cannot have blockers")
        else:
            if self.decision_state is SpendGateDecisionState.ELIGIBLE_ACTIVE_BUDGET:
                raise ValueError(f"{self.decision_id} refused decisions cannot use eligible state")
            if not self.blocking_reasons:
                raise ValueError(f"{self.decision_id} refused decisions require blockers")
        _reject_private_or_identity_refs(
            _refs(
                self.decision_id,
                self.route_id,
                self.provider,
                self.profile,
                self.task_class,
                self.quality_floor,
                self.budget_id,
                *self.blocking_reasons,
                *self.evidence_refs,
            ),
            "spend gate decision",
        )
        return self


class QuotaSpendDashboard(StrictModel):
    quality_preserving_routes_available: RouteAvailability
    blocked_quality_floor_reason: str | None = None
    subscription_quota_state: SubscriptionQuotaState
    paid_api_budget_state: PaidApiBudgetState
    bootstrap_dependency_state: BootstrapDependencyState
    local_resource_state: LocalResourceState
    current_capacity_pool: CapacityPool | None = None
    next_budget_review_at: datetime | None = None
    provider_dependency_count: int = Field(ge=0)
    support_artifacts_waiting_for_review: int = Field(ge=0)
    budget_ledger_stale: bool
    paid_api_route_eligible: bool
    paid_api_blocking_reasons: tuple[str, ...] = Field(default=())
    non_green_states: tuple[str, ...] = Field(default=())
    transition_budget_refs: tuple[str, ...] = Field(default=())
    unreconciled_spend_refs: tuple[str, ...] = Field(default=())
    frozen_spend_refs: tuple[str, ...] = Field(default=())
    provider_dependency_refs: tuple[str, ...] = Field(default=())
    closed_provider_dependency_refs: tuple[str, ...] = Field(default=())
    support_artifact_refs: tuple[str, ...] = Field(default=())
    closed_support_artifact_refs: tuple[str, ...] = Field(default=())
    renewal_review_refs: tuple[str, ...] = Field(default=())


class QuotaSpendLedger(StrictModel):
    """Complete local ledger fixture. Loading this grants no spend authority."""

    schema_version: Literal[1, 2] = 1
    ledger_id: str = Field(min_length=1)
    captured_at: datetime
    authority_source: Literal["isap:quota-spend-ledger-20260509"]
    generated_from: tuple[str, ...] = Field(min_length=1)
    privacy_scope: Literal["private"] = "private"
    consumer_permission_after: Literal["private_capacity_routing_tests_only"]
    paid_api_budget_freshness_ttl_s: int = Field(default=60, ge=0)
    quality_preserving_routes_available: RouteAvailability = RouteAvailability.UNKNOWN
    blocked_quality_floor_reason: str | None = None
    local_resource_state: LocalResourceState = LocalResourceState.UNKNOWN
    quota_snapshots: tuple[QuotaSnapshot, ...] = Field(default=())
    transition_budgets: tuple[TransitionBudget, ...] = Field(default=())
    spend_receipts: tuple[SpendReceipt, ...] = Field(default=())
    spend_gate_decisions: tuple[SpendGateDecisionRecord, ...] = Field(default=())
    provider_dependencies: tuple[ProviderDependencyRecord, ...] = Field(default=())
    artifact_provenance: tuple[ArtifactProvenanceRecord, ...] = Field(default=())
    renewal_records: tuple[RenewalRecord, ...] = Field(default=())
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    freeze: dict[str, Any] = Field(default_factory=dict)
    operator_reports: tuple[QuotaMeasurement, ...] = ()

    def schema_v1_payload(self) -> dict[str, Any]:
        """Explicit downgrade for strict pre-v2 readers; no second ledger is written."""
        payload = self.model_dump(mode="json")
        payload["schema_version"] = 1
        payload.pop("freeze")
        payload.pop("operator_reports")
        fields = {
            "snapshot_id",
            "captured_at",
            "fresh_until",
            "route_id",
            "provider",
            "capacity_pool",
            "subscription_quota_state",
            "evidence_refs",
            "operator_visible_reason",
        }
        payload["quota_snapshots"] = [
            {"quota_snapshot_schema": 1, **{key: row[key] for key in fields}}
            for row in payload["quota_snapshots"]
            if row["admission_compatible"] and row["route_id"] is not None
        ]
        return payload

    @model_validator(mode="after")
    def _ledger_contract(self) -> Self:
        _require_aware(self.captured_at, "captured_at")
        _reject_private_or_identity_refs(
            [self.ledger_id, *self.generated_from, *self.evidence_refs],
            "quota spend ledger",
        )
        _require_unique("budget_id", [budget.budget_id for budget in self.transition_budgets])
        _require_unique("spend_id", [receipt.spend_id for receipt in self.spend_receipts])
        _require_unique(
            "decision_id", [decision.decision_id for decision in self.spend_gate_decisions]
        )
        _require_unique(
            "dependency_id", [dependency.dependency_id for dependency in self.provider_dependencies]
        )
        _require_unique(
            "provenance_id", [record.provenance_id for record in self.artifact_provenance]
        )
        _require_unique("renewal_id", [record.renewal_id for record in self.renewal_records])
        _require_unique(
            "quota snapshot_id", [snapshot.snapshot_id for snapshot in self.quota_snapshots]
        )

        budget_ids = {budget.budget_id for budget in self.transition_budgets}
        spend_ids = {receipt.spend_id for receipt in self.spend_receipts}
        for receipt in self.spend_receipts:
            if receipt.budget_id and receipt.budget_id not in budget_ids:
                raise ValueError(f"{receipt.spend_id} references unknown budget")
        for decision in self.spend_gate_decisions:
            if decision.budget_id and decision.budget_id not in budget_ids:
                raise ValueError(f"{decision.decision_id} references unknown budget")
        for dependency in self.provider_dependencies:
            if (
                dependency.transition_budget_id
                and dependency.transition_budget_id not in budget_ids
            ):
                raise ValueError(f"{dependency.dependency_id} references unknown budget")
        for provenance in self.artifact_provenance:
            if (
                provenance.produced_under_budget_id
                and provenance.produced_under_budget_id not in budget_ids
            ):
                raise ValueError(f"{provenance.provenance_id} references unknown budget")
            missing_spends = set(provenance.source_spend_receipt_ids) - spend_ids
            if missing_spends:
                raise ValueError(
                    f"{provenance.provenance_id} references unknown spend receipts: "
                    f"{sorted(missing_spends)}"
                )
        return self

    def budget_by_id(self, budget_id: str) -> TransitionBudget:
        for budget in self.transition_budgets:
            if budget.budget_id == budget_id:
                return budget
        raise QuotaSpendLedgerError(f"missing transition budget {budget_id}")

    def active_paid_budgets(self, now: datetime | None = None) -> tuple[TransitionBudget, ...]:
        when = _coerce_now(now)
        return tuple(
            budget
            for budget in self.transition_budgets
            if budget.lifecycle_state is BudgetLifecycleState.ACTIVE
            and budget.capacity_pool.value in PAID_CAPACITY_POOLS
            and budget.is_unexpired_at(when)
            and self._budget_remaining_usd(budget) > 0
        )

    def _budget_receipts(self, budget: TransitionBudget) -> tuple[SpendReceipt, ...]:
        return tuple(
            receipt for receipt in self.spend_receipts if receipt.budget_id == budget.budget_id
        )

    def _budget_spent_usd(self, budget: TransitionBudget) -> Decimal:
        return sum(
            (receipt.cost_against_cap() for receipt in self._budget_receipts(budget)),
            start=Decimal("0"),
        )

    def _budget_spent_today_usd(self, budget: TransitionBudget, now: datetime) -> Decimal:
        today = now.date()
        return sum(
            (
                receipt.cost_against_cap()
                for receipt in self._budget_receipts(budget)
                if receipt.created_at.astimezone(UTC).date() == today
            ),
            start=Decimal("0"),
        )

    def _budget_spent_for_task_usd(self, budget: TransitionBudget, task_id: str) -> Decimal:
        return sum(
            (
                receipt.cost_against_cap()
                for receipt in self._budget_receipts(budget)
                if receipt.task_id == task_id
            ),
            start=Decimal("0"),
        )

    def _budget_remaining_usd(self, budget: TransitionBudget) -> Decimal:
        remaining = budget.total_cap_usd - self._budget_spent_usd(budget)
        return max(Decimal("0"), remaining)

    def budget_has_overdue_reconciliation(self, budget: TransitionBudget, now: datetime) -> bool:
        return any(
            receipt.is_unreconciled_overdue(now) for receipt in self._budget_receipts(budget)
        )

    def budget_has_frozen_refused_spend(self, budget: TransitionBudget) -> bool:
        return any(receipt.is_frozen_refused() for receipt in self._budget_receipts(budget))

    def ledger_stale(self, now: datetime | None = None) -> bool:
        when = _coerce_now(now)
        age_s = (when - self.captured_at).total_seconds()
        return age_s > self.paid_api_budget_freshness_ttl_s


def evaluate_paid_route_eligibility(
    ledger: QuotaSpendLedger,
    request: PaidRouteRequest,
    *,
    now: datetime | None = None,
) -> PaidRouteEligibility:
    """Return paid/API route eligibility; every uncertainty is a refusal."""

    when = _coerce_now(now)
    blocking: list[str] = []
    evidence_refs: list[str] = []
    matching = tuple(
        budget for budget in ledger.transition_budgets if budget.matches_request(request)
    )

    if ledger.ledger_stale(when):
        blocking.append("budget ledger stale")

    if not matching:
        blocking.append("no matching TransitionBudget")
        return PaidRouteEligibility(
            eligible=False,
            state="refused_no_matching_budget",
            blocking_reasons=tuple(blocking),
        )

    unexpired = tuple(
        budget
        for budget in matching
        if budget.lifecycle_state is BudgetLifecycleState.ACTIVE and budget.is_unexpired_at(when)
    )
    # Every unresolved receipt on a matching budget blocks. Resolution is an act recorded on
    # the receipt (a reviewed governance record, or settle_spend_covered_by_provider_balance),
    # never a judgement made here at decision time.
    overdue = tuple(
        budget for budget in matching if ledger.budget_has_overdue_reconciliation(budget, when)
    )
    if overdue:
        blocking.append(
            "unreconciled spend receipts overdue for " + ", ".join(b.budget_id for b in overdue)
        )
    frozen = tuple(budget for budget in matching if ledger.budget_has_frozen_refused_spend(budget))
    if frozen:
        blocking.append(
            "frozen/refused spend receipts for " + ", ".join(b.budget_id for b in frozen)
        )

    if not unexpired:
        blocking.append("matching TransitionBudget expired or inactive")
        return PaidRouteEligibility(
            eligible=False,
            state="refused_expired_budget",
            blocking_reasons=tuple(blocking),
            evidence_refs=tuple(b.budget_id for b in matching),
        )

    cap_eligible: list[tuple[TransitionBudget, Decimal]] = []
    for budget in unexpired:
        remaining = ledger._budget_remaining_usd(budget)
        daily_remaining = budget.daily_cap_usd - ledger._budget_spent_today_usd(budget, when)
        task_remaining = budget.per_task_cap_usd - ledger._budget_spent_for_task_usd(
            budget,
            request.task_id,
        )
        limiting_remaining = min(remaining, daily_remaining, task_remaining)
        if request.estimated_cost_usd > task_remaining:
            continue
        if request.estimated_cost_usd > remaining:
            continue
        if request.estimated_cost_usd > daily_remaining:
            continue
        cap_eligible.append((budget, limiting_remaining - request.estimated_cost_usd))

    if not cap_eligible:
        blocking.append("matching TransitionBudget cap exhausted")
        return PaidRouteEligibility(
            eligible=False,
            state="refused_exhausted_budget",
            blocking_reasons=tuple(blocking),
            evidence_refs=tuple(b.budget_id for b in unexpired),
        )

    if blocking:
        return PaidRouteEligibility(
            eligible=False,
            state="refused_budget_gate",
            blocking_reasons=tuple(blocking),
            evidence_refs=tuple(b.budget_id for b, _ in cap_eligible),
        )

    budget, cap_remaining = cap_eligible[0]
    evidence_refs.append(budget.budget_id)
    return PaidRouteEligibility(
        eligible=True,
        state="eligible_active_budget",
        budget_id=budget.budget_id,
        cap_remaining_usd=cap_remaining,
        evidence_refs=tuple(evidence_refs),
    )


def settle_spend_covered_by_provider_balance(ledger: QuotaSpendLedger) -> QuotaSpendLedger:
    """Resolve unresolved spend that a later provider balance observation already reflects.

    The act the telemetry writer performs every tick (no operator): a pending or frozen
    receipt that some budget's provider balance covers (same provider, another budget, created
    before the settlement cut-off; TransitionBudget.provider_balance_covers) becomes
    SETTLED_BY_PROVIDER_BALANCE. Whatever it cost is already out of the observed balance that
    budget's cap was set from. No actual is claimed, the estimate stays held, and the reason
    names the evidence. Spend no balance covers stays unresolved and keeps blocking.
    """

    payload = ledger.model_dump(mode="json")
    settled_any = False
    for index, receipt in enumerate(ledger.spend_receipts):
        if receipt.reconciliation_state not in {
            SpendReconciliationState.PENDING,
            SpendReconciliationState.FROZEN_REFUSED,
        }:
            continue
        covering = next(
            (b for b in ledger.transition_budgets if b.provider_balance_covers(receipt)), None
        )
        if covering is None:
            continue
        settled = dict(payload["spend_receipts"][index])
        settled.pop("actual_cost_usd", None)
        if settled.get("estimated_cost_usd") is None:
            settled["estimated_cost_usd"] = str(receipt.cost_against_cap())
        settled["reconciliation_state"] = SpendReconciliationState.SETTLED_BY_PROVIDER_BALANCE.value
        settled["reconciled_at"] = _payload_datetime(covering.provider_balance_observed_at)
        settled["reconciliation_reason"] = (
            f"settled against provider balance USD {covering.provider_balance_usd} observed "
            f"{_payload_datetime(covering.provider_balance_observed_at)} (budget "
            f"{covering.budget_id}, evidence {covering.provider_balance_evidence_ref}), which "
            f"covers spend before {_payload_datetime(covering.provider_balance_covers_spend_before)}"
            f"; per-call cost unknown, estimate held; was {receipt.reconciliation_state.value}: "
            f"{receipt.reconciliation_reason or 'pending'}"
        )
        payload["spend_receipts"][index] = settled
        settled_any = True
    return QuotaSpendLedger.model_validate(payload) if settled_any else ledger


def _payload_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_dashboard(
    ledger: QuotaSpendLedger,
    *,
    now: datetime | None = None,
) -> QuotaSpendDashboard:
    """Build private dashboard JSON fields from the inert ledger state."""

    when = _coerce_now(now)
    ledger_stale = ledger.ledger_stale(when)
    paid_state = _paid_api_budget_state(ledger, when)
    bootstrap_state = _bootstrap_dependency_state(ledger, when)
    subscription_state = _subscription_quota_state(ledger, now=when)
    support_waiting = tuple(
        record for record in ledger.artifact_provenance if record.waiting_for_review()
    )
    overdue_receipts = tuple(
        receipt for receipt in ledger.spend_receipts if receipt.is_unreconciled_overdue(when)
    )
    frozen_receipts = tuple(
        receipt for receipt in ledger.spend_receipts if receipt.is_frozen_refused()
    )
    active_dependency_refs = tuple(
        dependency.dependency_id
        for dependency in ledger.provider_dependencies
        if dependency.dependency_state is DependencyState.ACTIVE
    )
    closed_dependency_refs = tuple(
        dependency.dependency_id
        for dependency in ledger.provider_dependencies
        if dependency.dependency_state is not DependencyState.ACTIVE
    )
    closed_support_artifact_refs = tuple(
        ref
        for record in ledger.artifact_provenance
        if record.artifact_disposition
        in {SupportArtifactDisposition.REJECTED, SupportArtifactDisposition.RETIRED}
        for ref in record.artifact_refs
    )
    non_green = _non_green_states(
        ledger_stale=ledger_stale,
        paid_state=paid_state,
        bootstrap_state=bootstrap_state,
        subscription_state=subscription_state,
        local_resource_state=ledger.local_resource_state,
        overdue_receipts=overdue_receipts,
    )
    paid_api_route_eligible = paid_state is PaidApiBudgetState.ACTIVE and not ledger_stale
    return QuotaSpendDashboard(
        quality_preserving_routes_available=ledger.quality_preserving_routes_available,
        blocked_quality_floor_reason=ledger.blocked_quality_floor_reason,
        subscription_quota_state=subscription_state,
        paid_api_budget_state=paid_state,
        bootstrap_dependency_state=bootstrap_state,
        local_resource_state=ledger.local_resource_state,
        current_capacity_pool=(
            ledger.active_paid_budgets(when)[0].capacity_pool
            if ledger.active_paid_budgets(when) and not ledger_stale
            else None
        ),
        next_budget_review_at=_next_budget_review_at(ledger),
        provider_dependency_count=len(active_dependency_refs),
        support_artifacts_waiting_for_review=len(support_waiting),
        budget_ledger_stale=ledger_stale,
        paid_api_route_eligible=paid_api_route_eligible,
        paid_api_blocking_reasons=_paid_api_blocking_reasons(
            non_green,
            paid_api_route_eligible=paid_api_route_eligible,
        ),
        non_green_states=tuple(non_green),
        transition_budget_refs=tuple(budget.budget_id for budget in ledger.transition_budgets),
        unreconciled_spend_refs=tuple(receipt.spend_id for receipt in overdue_receipts),
        frozen_spend_refs=tuple(receipt.spend_id for receipt in frozen_receipts),
        provider_dependency_refs=active_dependency_refs,
        closed_provider_dependency_refs=closed_dependency_refs,
        support_artifact_refs=tuple(
            ref for record in support_waiting for ref in record.artifact_refs
        ),
        closed_support_artifact_refs=closed_support_artifact_refs,
        renewal_review_refs=tuple(record.renewal_id for record in ledger.renewal_records),
    )


def load_quota_spend_ledger(path: Path = QUOTA_SPEND_LEDGER_FIXTURES) -> QuotaSpendLedger:
    """Load quota/spend fixtures, failing closed on malformed data."""

    try:
        return QuotaSpendLedger.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise QuotaSpendLedgerError(f"invalid quota/spend ledger at {path}: {exc}") from exc


class ResolvedQuotaSpendLedger(StrictModel):
    """Quota/spend ledger plus the provenance of where it was read from."""

    ledger: QuotaSpendLedger
    path: Path
    source: Literal["live", "fixtures"]
    live_error: str | None = None


def load_quota_spend_ledger_resolved(
    *,
    live_path: Path | None = None,
    fixtures_path: Path = QUOTA_SPEND_LEDGER_FIXTURES,
) -> ResolvedQuotaSpendLedger:
    """Load the live telemetry ledger when present, else the checked-in fixtures.

    The live ledger is written on a timer by ``scripts/hapax-quota-telemetry-writer``.
    A missing live file is the normal fixture-fallback path; a present-but-invalid
    live file also falls back but carries the validation error so consumers can
    surface the degraded read instead of silently trusting stale fixtures. The
    fixture fallback stays honest on its own: its old ``captured_at`` keeps
    ``ledger_stale()`` / ``budget_ledger_stale`` flagged.

    This module stays inert (no env reads); callers honoring the
    ``HAPAX_QUOTA_SPEND_LEDGER_LIVE`` override resolve it themselves and pass
    ``live_path`` explicitly.
    """

    candidate = live_path if live_path is not None else DEFAULT_QUOTA_SPEND_LEDGER_LIVE
    live_error: str | None = None
    if candidate.exists():
        try:
            return ResolvedQuotaSpendLedger(
                ledger=load_quota_spend_ledger(candidate),
                path=candidate,
                source="live",
            )
        except QuotaSpendLedgerError as exc:
            live_error = str(exc)
    return ResolvedQuotaSpendLedger(
        ledger=load_quota_spend_ledger(fixtures_path),
        path=fixtures_path,
        source="fixtures",
        live_error=live_error,
    )


def _paid_api_budget_state(ledger: QuotaSpendLedger, now: datetime) -> PaidApiBudgetState:
    if not ledger.transition_budgets:
        return PaidApiBudgetState.NONE
    if ledger.active_paid_budgets(now):
        if any(
            ledger.budget_has_overdue_reconciliation(budget, now)
            for budget in ledger.active_paid_budgets(now)
        ):
            return PaidApiBudgetState.UNKNOWN
        return PaidApiBudgetState.ACTIVE
    active_lifecycle = tuple(
        budget
        for budget in ledger.transition_budgets
        if budget.lifecycle_state is BudgetLifecycleState.ACTIVE
    )
    if active_lifecycle and all(budget.expires_at <= now for budget in active_lifecycle):
        return PaidApiBudgetState.EXPIRED
    if active_lifecycle and all(
        ledger._budget_remaining_usd(budget) <= 0 for budget in active_lifecycle
    ):
        return PaidApiBudgetState.EXHAUSTED
    return PaidApiBudgetState.UNKNOWN


def _bootstrap_dependency_state(
    ledger: QuotaSpendLedger, now: datetime
) -> BootstrapDependencyState:
    dependencies = tuple(
        dependency
        for dependency in ledger.provider_dependencies
        if dependency.dependency_state is DependencyState.ACTIVE and dependency.bootstrap_dependency
    )
    if not dependencies:
        return BootstrapDependencyState.NONE
    for dependency in dependencies:
        if dependency.transition_budget_id:
            budget = ledger.budget_by_id(dependency.transition_budget_id)
            if budget.expires_at <= now:
                return BootstrapDependencyState.EXPIRED
    if any(
        dependency.review_by <= now or not dependency.replacement_route_id
        for dependency in dependencies
    ):
        return BootstrapDependencyState.REPLACEMENT_OVERDUE
    return BootstrapDependencyState.ACTIVE


def _subscription_quota_state(
    ledger: QuotaSpendLedger,
    *,
    now: datetime,
) -> SubscriptionQuotaState:
    snapshots = tuple(
        snapshot
        for snapshot in ledger.quota_snapshots
        if snapshot.admission_compatible
        and snapshot.capacity_pool is CapacityPool.SUBSCRIPTION_QUOTA
    )
    if not snapshots:
        return SubscriptionQuotaState.UNKNOWN
    if any(
        _effective_subscription_quota_state(ledger, snapshot, now=now)
        is SubscriptionQuotaState.FRESH
        for snapshot in snapshots
    ):
        return SubscriptionQuotaState.FRESH
    if any(
        _effective_subscription_quota_state(ledger, snapshot, now=now)
        is SubscriptionQuotaState.EXHAUSTED
        for snapshot in snapshots
    ):
        return SubscriptionQuotaState.EXHAUSTED
    if any(
        _effective_subscription_quota_state(ledger, snapshot, now=now)
        is SubscriptionQuotaState.STALE
        for snapshot in snapshots
    ):
        return SubscriptionQuotaState.STALE
    return SubscriptionQuotaState.UNKNOWN


def subscription_quota_state_for_route(
    ledger: QuotaSpendLedger,
    route_id: str,
    *,
    now: datetime | None = None,
) -> tuple[SubscriptionQuotaState, tuple[str, ...]]:
    """Return route-specific subscription quota state and evidence refs.

    Aggregate subscription freshness answers "does any subscription lane have
    capacity?" Route dispatch needs a stricter question for receipt-bound routes
    such as GLMCP: "is this exact route's quota fresh?"
    """

    checked_at = _coerce_now(now)
    normalized_route_id = _normalize_route_id(route_id)
    snapshots = tuple(
        snapshot
        for snapshot in ledger.quota_snapshots
        if snapshot.admission_compatible
        and snapshot.capacity_pool is CapacityPool.SUBSCRIPTION_QUOTA
        and _normalize_route_id(snapshot.route_id) == normalized_route_id
    )
    if not snapshots:
        return (
            SubscriptionQuotaState.UNKNOWN,
            (f"quota-snapshot:{normalized_route_id}:missing",),
        )
    evidence_refs = tuple(
        _redact_quota_evidence_ref(normalized_route_id, ref)
        for snapshot in snapshots
        for ref in snapshot.evidence_refs
    ) or (f"quota-snapshot:{normalized_route_id}:no-evidence",)
    expired_refs = tuple(
        f"quota-snapshot:{snapshot.snapshot_id}:fresh_until_expired:{snapshot.fresh_until.isoformat().replace('+00:00', 'Z')}"
        for snapshot in snapshots
        if _subscription_quota_fresh_until_expired(snapshot, now=checked_at)
    )
    missing_fresh_until_refs = tuple(
        f"quota-snapshot:{snapshot.snapshot_id}:fresh_until_missing"
        for snapshot in snapshots
        if _subscription_quota_missing_required_fresh_until(snapshot)
    )
    untrusted_fresh_refs = tuple(
        "quota-snapshot:"
        f"{snapshot.snapshot_id}:"
        f"{_subscription_quota_untrusted_admission_evidence_reason(snapshot)}"
        for snapshot in snapshots
        if _subscription_quota_missing_required_admission_evidence(ledger, snapshot)
    )
    missing_payg_spend_gate_refs = tuple(
        f"quota-snapshot:{snapshot.snapshot_id}:payg_spend_gate_missing_or_ineligible"
        for snapshot in snapshots
        if _subscription_quota_missing_required_payg_spend_gate(ledger, snapshot, now=checked_at)
    )
    return _strict_subscription_quota_state(ledger, snapshots, now=checked_at), (
        *evidence_refs,
        *expired_refs,
        *missing_fresh_until_refs,
        *untrusted_fresh_refs,
        *missing_payg_spend_gate_refs,
    )


def _strict_subscription_quota_state(
    ledger: QuotaSpendLedger,
    snapshots: tuple[QuotaSnapshot, ...],
    *,
    now: datetime,
) -> SubscriptionQuotaState:
    if any(
        _effective_subscription_quota_state(ledger, snapshot, now=now)
        is SubscriptionQuotaState.EXHAUSTED
        for snapshot in snapshots
    ):
        return SubscriptionQuotaState.EXHAUSTED
    if any(
        _effective_subscription_quota_state(ledger, snapshot, now=now)
        is SubscriptionQuotaState.STALE
        for snapshot in snapshots
    ):
        return SubscriptionQuotaState.STALE
    if any(
        _effective_subscription_quota_state(ledger, snapshot, now=now)
        is SubscriptionQuotaState.UNKNOWN
        for snapshot in snapshots
    ):
        return SubscriptionQuotaState.UNKNOWN
    if any(
        _effective_subscription_quota_state(ledger, snapshot, now=now)
        is SubscriptionQuotaState.FRESH
        for snapshot in snapshots
    ):
        return SubscriptionQuotaState.FRESH
    return SubscriptionQuotaState.UNKNOWN


def _effective_subscription_quota_state(
    ledger: QuotaSpendLedger,
    snapshot: QuotaSnapshot,
    *,
    now: datetime,
) -> SubscriptionQuotaState:
    if _subscription_quota_missing_required_admission_evidence(ledger, snapshot):
        return SubscriptionQuotaState.UNKNOWN
    if _subscription_quota_missing_required_payg_spend_gate(ledger, snapshot, now=now):
        return SubscriptionQuotaState.UNKNOWN
    if _subscription_quota_missing_required_fresh_until(snapshot):
        return SubscriptionQuotaState.UNKNOWN
    if _subscription_quota_fresh_until_expired(snapshot, now=now):
        return SubscriptionQuotaState.STALE
    return snapshot.subscription_quota_state


def _subscription_quota_missing_required_fresh_until(snapshot: QuotaSnapshot) -> bool:
    return (
        snapshot.subscription_quota_state is SubscriptionQuotaState.FRESH
        and _normalize_route_id(snapshot.route_id) in RECEIPT_BOUNDED_SUBSCRIPTION_ROUTES
        and snapshot.fresh_until is None
    )


def _subscription_quota_missing_required_admission_evidence(
    ledger: QuotaSpendLedger,
    snapshot: QuotaSnapshot,
) -> bool:
    if snapshot.subscription_quota_state is not SubscriptionQuotaState.FRESH:
        return False
    normalized_route_id = _normalize_route_id(snapshot.route_id)
    if normalized_route_id not in RECEIPT_BOUNDED_SUBSCRIPTION_ROUTES:
        return False
    expected_provider = RECEIPT_BOUNDED_SUBSCRIPTION_PROVIDERS.get(normalized_route_id)
    if expected_provider is None:
        return True
    if GLMCP_QUOTA_TELEMETRY_WRITER_REF not in ledger.generated_from:
        return True
    if snapshot.provider != expected_provider:
        return True
    if normalized_route_id == "glmcp.review.direct":
        return not any(_is_glmcp_admission_evidence_ref(ref) for ref in snapshot.evidence_refs)
    if normalized_route_id == "agy.review.direct":
        return not any(_is_agy_admission_evidence_ref(ref) for ref in snapshot.evidence_refs)
    if normalized_route_id in CLAUDE_RECEIPT_BOUNDED_SUBSCRIPTION_ROUTES:
        return not any(_is_claude_admission_evidence_ref(ref) for ref in snapshot.evidence_refs)
    if normalized_route_id == "kimi.interactive.lane":
        return not any(_is_kimi_admission_evidence_ref(ref) for ref in snapshot.evidence_refs)
    return True


def _subscription_quota_untrusted_admission_evidence_reason(snapshot: QuotaSnapshot) -> str:
    normalized_route_id = _normalize_route_id(snapshot.route_id)
    if normalized_route_id == "glmcp.review.direct":
        return "untrusted_glmcp_admission_evidence"
    if normalized_route_id == "agy.review.direct":
        return "untrusted_agy_admission_evidence"
    if normalized_route_id in CLAUDE_RECEIPT_BOUNDED_SUBSCRIPTION_ROUTES:
        return "untrusted_claude_admission_evidence"
    if normalized_route_id == "kimi.interactive.lane":
        return "untrusted_kimi_admission_evidence"
    return "untrusted_route_admission_evidence"


def _subscription_quota_missing_required_payg_spend_gate(
    ledger: QuotaSpendLedger,
    snapshot: QuotaSnapshot,
    *,
    now: datetime,
) -> bool:
    if snapshot.subscription_quota_state is not SubscriptionQuotaState.FRESH:
        return False
    if _normalize_route_id(snapshot.route_id) != GLMCP_PAYG_BUDGET_ROUTE_ID:
        return False
    if not any(_is_glmcp_payg_admission_evidence_ref(ref) for ref in snapshot.evidence_refs):
        return False
    for receipt in _matching_glmcp_payg_spend_receipts(ledger, snapshot):
        decision = evaluate_paid_route_eligibility(
            ledger,
            _glmcp_payg_budget_request(receipt.task_id),
            now=now,
        )
        required_refs = {
            f"spend-gate:{GLMCP_PAYG_BUDGET_ROUTE_ID}:eligible_active_budget",
            f"spend-gate-budget:{decision.budget_id}",
        }
        if (
            decision.eligible
            and decision.budget_id == receipt.budget_id
            and required_refs.issubset(set(snapshot.evidence_refs))
        ):
            return False
    return True


def _is_glmcp_admission_evidence_ref(ref: str) -> bool:
    return (
        GLMCP_ADMISSION_RECEIPT_LABEL_RE.match(ref) is not None
        and _has_safe_glmcp_admission_witness(ref)
        and _has_glmcp_admission_tool_endpoint_pair(ref)
        and _has_glmcp_payg_witness_fields_for_endpoint(ref)
        and any(f":model:{model}:" in ref for model in GLMCP_ADMISSION_MODELS)
        and ":observed_at:" in ref
        and ":fresh_until:" in ref
    )


def _is_agy_admission_evidence_ref(ref: str) -> bool:
    return (
        AGY_ADMISSION_RECEIPT_LABEL_RE.match(ref) is not None
        and _has_safe_agy_admission_witness(ref)
        and f":supported_tool:{AGY_ADMISSION_SUPPORTED_TOOL}:" in ref
        and any(f":model:{model}:" in ref for model in AGY_ADMISSION_MODELS)
        and ":observed_at:" in ref
        and ":fresh_until:" in ref
    )


def _is_kimi_admission_evidence_ref(ref: str) -> bool:
    return (
        KIMI_ADMISSION_RECEIPT_LABEL_RE.match(ref) is not None
        and _has_safe_kimi_admission_witness(ref)
        and f":supported_tool:{KIMI_ADMISSION_SUPPORTED_TOOL}:" in ref
        and any(f":model:{model}:" in ref for model in KIMI_ADMISSION_MODELS)
        and ":observed_at:" in ref
        and ":fresh_until:" in ref
    )


def _is_claude_admission_evidence_ref(ref: str) -> bool:
    if CLAUDE_ADMISSION_COMPOSITE_REF_RE.fullmatch(ref) is None:
        return False
    return _has_safe_claude_admission_receipt_label(ref) and _has_safe_claude_admission_witness(ref)


def _has_safe_claude_admission_receipt_label(ref: str) -> bool:
    label_match = CLAUDE_ADMISSION_RECEIPT_LABEL_RE.match(ref)
    if label_match is None:
        return False
    label = label_match.group("label")
    label_stem = label.removesuffix(".yaml")
    return (
        CLAUDE_ADMISSION_SECRETISH_RE.search(label_stem) is None
        and CLAUDE_ADMISSION_BILLINGISH_RE.search(label_stem) is None
        and CLAUDE_ADMISSION_LANE_PRESENCE_RE.search(label_stem) is None
    )


def _claude_evidence_receipt_label(ref: str) -> str | None:
    if not ref.startswith("relay-receipt:"):
        return None
    rest = ref.removeprefix("relay-receipt:")
    if rest.startswith("unsafe-receipt-name-sha256:"):
        prefix, _, suffix = rest.partition(":")
        digest, sep, remainder = suffix.partition(":")
        if not sep:
            return None
        label = f"{prefix}:{digest}"
    else:
        label, sep, remainder = rest.partition(":")
        if not sep:
            return None
    if remainder.startswith("witness:") or remainder.startswith("ignored:"):
        return label
    return None


def _is_safe_claude_ignored_evidence_ref(ref: str) -> bool:
    if ":ignored:" not in ref:
        return False
    label = _claude_evidence_receipt_label(ref)
    if label is None:
        return False
    ignored_reason = ref.split(":ignored:", maxsplit=1)[1]
    if not _is_safe_claude_ignored_reason(ignored_reason):
        return False
    if re.fullmatch(r"unsafe-receipt-name-sha256:[0-9a-f]{16}", label) is not None:
        return True
    label_stem = label.removesuffix(".yaml")
    return (
        CLAUDE_ADMISSION_RECEIPT_LABEL_RE.match(f"relay-receipt:{label}:witness:") is not None
        and CLAUDE_ADMISSION_SECRETISH_RE.search(label_stem) is None
        and CLAUDE_ADMISSION_BILLINGISH_RE.search(label_stem) is None
        and CLAUDE_ADMISSION_LANE_PRESENCE_RE.search(label_stem) is None
    )


def _is_safe_claude_ignored_reason(reason: str) -> bool:
    return (
        CLAUDE_ADMISSION_IGNORED_REASON_RE.fullmatch(reason) is not None
        and CLAUDE_ADMISSION_SECRETISH_RE.search(reason) is None
        and CLAUDE_ADMISSION_IGNORED_UNSAFE_DETAIL_RE.search(reason) is None
    )


def _is_untrusted_claude_admission_ref_for_evidence(ref: str) -> bool:
    if _is_claude_admission_evidence_ref(ref) or _is_safe_claude_ignored_evidence_ref(ref):
        return False
    if (
        CLAUDE_ADMISSION_BILLINGISH_RE.search(ref) is not None
        or CLAUDE_ADMISSION_LANE_PRESENCE_RE.search(ref) is not None
    ):
        return True
    if not ref.startswith("relay-receipt:"):
        return False
    return (
        "claude-subscription-quota-admission" in ref
        or "unsafe-receipt-name-sha256:" in ref
        or bool(CLAUDE_ADMISSION_WITNESS_REF_RE.search(ref))
    )


def _is_glmcp_payg_admission_evidence_ref(ref: str) -> bool:
    return (
        _is_glmcp_admission_evidence_ref(ref)
        and f":endpoint:{GLMCP_ADMISSION_PAYG_ENDPOINT}:" in ref
    )


def _glmcp_payg_spend_receipt_witness_refs(receipt: SpendReceipt) -> set[str]:
    if (
        _normalize_route_id(receipt.route_id) != GLMCP_PAYG_BUDGET_ROUTE_ID
        or receipt.capacity_pool is not CapacityPool.API_PAID_SPEND
        or receipt.provider != GLMCP_PAYG_BUDGET_PROVIDER
        or receipt.spend_reason is not SpendReason.QUOTA_EXHAUSTION
    ):
        return set()
    refs = {receipt.spend_id}
    match = re.fullmatch(r"spend-([0-9]{8}T[0-9]{6}Z)-glmcp-payg-review-(.+)", receipt.spend_id)
    if match is not None:
        stamp, suffix = match.groups()
        refs.add(f"glmcp-payg-spend-{stamp.lower()}-{suffix}.yaml")
    return refs


def _matching_glmcp_payg_spend_receipts(
    ledger: QuotaSpendLedger,
    snapshot: QuotaSnapshot,
) -> tuple[SpendReceipt, ...]:
    witnesses = {
        match.group(1)
        for ref in snapshot.evidence_refs
        if _is_glmcp_payg_admission_evidence_ref(ref)
        for match in [GLMCP_ADMISSION_WITNESS_REF_RE.search(ref)]
        if match is not None
    }
    if not witnesses:
        return ()
    return tuple(
        receipt
        for receipt in ledger.spend_receipts
        if witnesses & _glmcp_payg_spend_receipt_witness_refs(receipt)
    )


def _glmcp_payg_budget_allows_review_spend(
    budget: TransitionBudget,
    receipt: SpendReceipt,
) -> bool:
    if budget.budget_id != receipt.budget_id:
        return False
    if budget.capacity_pool is not CapacityPool.API_PAID_SPEND:
        return False
    if receipt.provider not in budget.providers_allowed:
        return False
    if GLMCP_PAYG_BUDGET_PROFILE not in budget.profiles_allowed:
        return False
    if GLMCP_PAYG_BUDGET_TASK_CLASS not in budget.task_classes_allowed:
        return False
    if GLMCP_PAYG_BUDGET_QUALITY_FLOOR not in budget.quality_floors_allowed:
        return False
    return budget.created_at <= receipt.created_at < budget.expires_at


def successful_task_scoped_glmcp_payg_review_spend_receipts(
    ledger: QuotaSpendLedger,
    task_id: str,
) -> tuple[SpendReceipt, ...]:
    """Reconciled GLMCP PAYG review spends already consumed for one task."""

    normalized_task_id = task_id.strip()
    if not normalized_task_id:
        return ()
    ledger_budgets = getattr(ledger, "transition_budgets", ())
    ledger_receipts = getattr(ledger, "spend_receipts", ())
    budgets = {budget.budget_id: budget for budget in ledger_budgets}
    receipts: list[SpendReceipt] = []
    for receipt in ledger_receipts:
        budget = budgets.get(str(receipt.budget_id or ""))
        if budget is None:
            continue
        if receipt.task_id != normalized_task_id:
            continue
        if not _glmcp_payg_spend_receipt_witness_refs(receipt):
            continue
        if receipt.auth_surface is not AuthSurface.API_KEY:
            continue
        if receipt.quality_floor != GLMCP_PAYG_BUDGET_QUALITY_FLOOR:
            continue
        if receipt.reconciliation_state is not SpendReconciliationState.RECONCILED:
            continue
        if receipt.actual_cost_usd is None or receipt.actual_cost_usd <= Decimal("0"):
            continue
        if receipt.reconciled_at is None or not receipt.reconciliation_reason:
            continue
        model_id = receipt.model_id.value if receipt.model_id is not None else None
        if (
            receipt.model_or_engine not in GLMCP_ADMISSION_MODELS
            and model_id not in GLMCP_MODEL_IDS.values()
        ):
            continue
        if not _glmcp_payg_budget_allows_review_spend(budget, receipt):
            continue
        receipts.append(receipt)
    return tuple(receipts)


def has_successful_task_scoped_glmcp_payg_review_spend(
    ledger: QuotaSpendLedger,
    task_id: str,
) -> bool:
    return bool(successful_task_scoped_glmcp_payg_review_spend_receipts(ledger, task_id))


def _glmcp_payg_prices(model: str) -> dict[str, Decimal]:
    prices = GLMCP_PAYG_PRICES_USD_PER_MTOK.get(model)
    if prices is None:
        raise QuotaSpendLedgerError(
            f"no Z.ai PAYG list price for model {model!r}; admitted: "
            f"{sorted(GLMCP_PAYG_PRICES_USD_PER_MTOK)}"
        )
    return prices


def glmcp_payg_reservation_usd(
    *,
    model: str,
    prompt_utf8_bytes: int,
    max_tokens: int,
    attempts: int = 1,
) -> Decimal:
    """Upper bound on one PAYG call at list price, charged against caps before the call.

    A byte-level tokenizer emits at most one token per prompt byte, so UTF-8 bytes plus a
    template allowance bound the input tokens; every input token is priced uncached and every
    allowed output token (reasoning included) as output. ``attempts`` counts provider calls
    whose input may bill, such as a rejected first attempt before a contract retry.
    """

    if prompt_utf8_bytes < 0 or max_tokens < 1 or attempts < 1:
        raise QuotaSpendLedgerError(
            "PAYG reservation needs bytes >= 0, max_tokens >= 1, attempts >= 1"
        )
    prices = _glmcp_payg_prices(model)
    input_tokens = (prompt_utf8_bytes + GLMCP_PAYG_TEMPLATE_TOKEN_ALLOWANCE) * attempts
    cost = (input_tokens * prices["input"] + max_tokens * prices["output"]) / Decimal(1_000_000)
    return cost.quantize(GLMCP_PAYG_COST_QUANTUM, rounding=ROUND_CEILING)


def glmcp_payg_usage_cost_usd(
    *,
    model: str,
    prompt_tokens: int,
    cached_tokens: int,
    completion_tokens: int,
) -> Decimal:
    """List-price cost of provider-reported usage. An estimate from usage, not an invoice."""

    if min(prompt_tokens, cached_tokens, completion_tokens) < 0 or cached_tokens > prompt_tokens:
        raise QuotaSpendLedgerError("PAYG usage must be non-negative with cached <= prompt tokens")
    prices = _glmcp_payg_prices(model)
    cost = (
        (prompt_tokens - cached_tokens) * prices["input"]
        + cached_tokens * prices["cached_input"]
        + completion_tokens * prices["output"]
    ) / Decimal(1_000_000)
    return cost.quantize(GLMCP_PAYG_COST_QUANTUM, rounding=ROUND_CEILING)


def glmcp_payg_usage_ceiling_usd(*, prompt_tokens: int, completion_tokens: int) -> Decimal:
    """Usage priced at the dearest known input and output rates, all input uncached.

    For a served model with no recorded list price: it bounds what any known model would
    charge for the reported usage; it cannot bound an unknown dearer model, which is why
    callers freeze such spend rather than reconcile it.
    """

    if min(prompt_tokens, completion_tokens) < 0:
        raise QuotaSpendLedgerError("PAYG usage must be non-negative")
    dearest_input = max(p["input"] for p in GLMCP_PAYG_PRICES_USD_PER_MTOK.values())
    dearest_output = max(p["output"] for p in GLMCP_PAYG_PRICES_USD_PER_MTOK.values())
    cost = (prompt_tokens * dearest_input + completion_tokens * dearest_output) / Decimal(1_000_000)
    return cost.quantize(GLMCP_PAYG_COST_QUANTUM, rounding=ROUND_CEILING)


def frozen_spend_receipt_payload(
    payload: dict[str, Any],
    *,
    count_usd: Decimal,
    frozen_at: str,
    reason: str,
) -> dict[str, Any]:
    """Freeze a spend receipt that may have billed but cannot be trusted as reconciled.

    No actual is claimed. The higher of ``count_usd`` and whatever the receipt already
    counted is held against the caps as its estimate, and the frozen state refuses further
    paid spend on every matching budget until a reviewed governance record supersedes it.
    """

    counted = [count_usd]
    for key in ("estimated_cost_usd", "actual_cost_usd"):
        value = payload.get(key)
        if value is not None and str(value).strip():
            counted.append(Decimal(str(value)))
    frozen = dict(payload)
    frozen.pop("actual_cost_usd", None)
    frozen["estimated_cost_usd"] = str(max(counted))
    frozen["reconciliation_state"] = SpendReconciliationState.FROZEN_REFUSED.value
    frozen["reconciled_at"] = frozen_at
    frozen["reconciliation_reason"] = reason
    return frozen


def _glmcp_payg_budget_request(task_id: str) -> PaidRouteRequest:
    return PaidRouteRequest.model_validate(
        {
            "route_id": GLMCP_PAYG_BUDGET_ROUTE_ID,
            "task_id": task_id,
            "provider": GLMCP_PAYG_BUDGET_PROVIDER,
            "profile": GLMCP_PAYG_BUDGET_PROFILE,
            "task_class": GLMCP_PAYG_BUDGET_TASK_CLASS,
            "quality_floor": GLMCP_PAYG_BUDGET_QUALITY_FLOOR,
            "estimated_cost_usd": GLMCP_PAYG_ESTIMATED_COST_USD,
            "capacity_pool": CapacityPool.API_PAID_SPEND,
        }
    )


def _has_glmcp_admission_tool_endpoint_pair(ref: str) -> bool:
    tool_matches = GLMCP_ADMISSION_SUPPORTED_TOOL_REF_RE.findall(ref)
    endpoint_matches = [
        endpoint for endpoint in GLMCP_ADMISSION_ENDPOINTS if f":endpoint:{endpoint}:" in ref
    ]
    if len(tool_matches) != 1 or len(endpoint_matches) != 1:
        return False
    tool = tool_matches[0]
    endpoint = endpoint_matches[0]
    return endpoint in GLMCP_ADMISSION_TOOL_ENDPOINTS.get(tool, frozenset())


def _has_glmcp_payg_witness_fields_for_endpoint(ref: str) -> bool:
    endpoint_matches = [
        endpoint for endpoint in GLMCP_ADMISSION_ENDPOINTS if f":endpoint:{endpoint}:" in ref
    ]
    primary_error_matches = GLMCP_PAYG_PRIMARY_ERROR_CLASS_REF_RE.findall(ref)
    wall_ref_matches = GLMCP_PAYG_QUOTA_WALL_REF_RE.findall(ref)
    if len(endpoint_matches) != 1:
        return False
    if endpoint_matches[0] != GLMCP_ADMISSION_PAYG_ENDPOINT:
        return not primary_error_matches and not wall_ref_matches
    if len(primary_error_matches) != 1 or len(wall_ref_matches) != 1:
        return False
    wall_ref = wall_ref_matches[0]
    return (
        primary_error_matches[0] in GLMCP_PAYG_PRIMARY_ERROR_CLASSES
        and GLMCP_ADMISSION_EVIDENCE_REF_RE.fullmatch(wall_ref) is not None
        and GLMCP_ADMISSION_SECRETISH_RE.search(wall_ref) is None
    )


def _has_safe_glmcp_admission_witness(ref: str) -> bool:
    witness_matches = GLMCP_ADMISSION_WITNESS_REF_RE.findall(ref)
    if len(witness_matches) != 1:
        return False
    witness = witness_matches[0]
    return (
        GLMCP_ADMISSION_EVIDENCE_REF_RE.fullmatch(witness) is not None
        and GLMCP_ADMISSION_SECRETISH_RE.search(witness) is None
    )


def _has_safe_agy_admission_witness(ref: str) -> bool:
    witness_matches = AGY_ADMISSION_WITNESS_REF_RE.findall(ref)
    if len(witness_matches) != 1:
        return False
    witness = witness_matches[0]
    return (
        AGY_ADMISSION_EVIDENCE_REF_RE.fullmatch(witness) is not None
        and AGY_ADMISSION_SECRETISH_RE.search(witness) is None
    )


def _has_safe_kimi_admission_witness(ref: str) -> bool:
    witness_matches = KIMI_ADMISSION_WITNESS_REF_RE.findall(ref)
    if len(witness_matches) != 1:
        return False
    witness = witness_matches[0]
    label = ref.removeprefix("relay-receipt:").split(":witness:", maxsplit=1)[0]
    label_stem = label.removesuffix(".yaml")
    return (
        KIMI_ADMISSION_EVIDENCE_REF_RE.fullmatch(witness) is not None
        and KIMI_ADMISSION_SECRETISH_RE.search(witness) is None
        and (
            label.startswith("unsafe-receipt-name-sha256:")
            or KIMI_ADMISSION_SECRETISH_RE.search(label_stem) is None
        )
    )


def _has_safe_claude_admission_witness(ref: str) -> bool:
    witness_matches = CLAUDE_ADMISSION_WITNESS_REF_RE.findall(ref)
    if len(witness_matches) != 1:
        return False
    witness = witness_matches[0]
    return (
        CLAUDE_ADMISSION_EVIDENCE_REF_RE.fullmatch(witness) is not None
        and CLAUDE_ADMISSION_WITNESS_ALLOWLIST_RE.fullmatch(witness) is not None
        and CLAUDE_ADMISSION_SECRETISH_RE.search(witness) is None
        and CLAUDE_ADMISSION_BILLINGISH_RE.search(witness) is None
        and CLAUDE_ADMISSION_LANE_PRESENCE_RE.search(witness) is None
    )


def _redact_secretish_quota_evidence_ref(ref: str) -> str:
    if GLMCP_ADMISSION_SECRETISH_RE.search(ref) is None:
        return ref
    digest = hashlib.sha256(ref.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"quota-evidence-ref:redacted-secretish-sha256:{digest}"


def _redact_quota_evidence_ref(route_id: str, ref: str) -> str:
    redacted = _redact_secretish_quota_evidence_ref(ref)
    if redacted != ref:
        return redacted
    if (
        route_id in CLAUDE_RECEIPT_BOUNDED_SUBSCRIPTION_ROUTES
        and _is_untrusted_claude_admission_ref_for_evidence(ref)
    ):
        digest = hashlib.sha256(ref.encode("utf-8", errors="replace")).hexdigest()[:16]
        return f"quota-evidence-ref:redacted-untrusted-claude-admission-sha256:{digest}"
    return ref


def _subscription_quota_fresh_until_expired(
    snapshot: QuotaSnapshot,
    *,
    now: datetime,
) -> bool:
    return (
        snapshot.subscription_quota_state is SubscriptionQuotaState.FRESH
        and snapshot.fresh_until is not None
        and now >= snapshot.fresh_until
    )


def _paid_api_blocking_reasons(
    non_green_states: list[str],
    *,
    paid_api_route_eligible: bool,
) -> tuple[str, ...]:
    if paid_api_route_eligible:
        return ()
    return tuple(
        state for state in non_green_states if not state.startswith("subscription_quota_state:")
    )


def _next_budget_review_at(ledger: QuotaSpendLedger) -> datetime | None:
    candidates: list[datetime] = []
    candidates.extend(
        budget.expires_at
        for budget in ledger.transition_budgets
        if budget.lifecycle_state is BudgetLifecycleState.ACTIVE
    )
    candidates.extend(
        dependency.review_by
        for dependency in ledger.provider_dependencies
        if dependency.dependency_state is DependencyState.ACTIVE
    )
    candidates.extend(record.hard_expiry_review_at for record in ledger.renewal_records)
    return min(candidates) if candidates else None


def _non_green_states(
    *,
    ledger_stale: bool,
    paid_state: PaidApiBudgetState,
    bootstrap_state: BootstrapDependencyState,
    subscription_state: SubscriptionQuotaState,
    local_resource_state: LocalResourceState,
    overdue_receipts: tuple[SpendReceipt, ...],
) -> list[str]:
    states: list[str] = []
    if ledger_stale:
        states.append("budget_ledger_stale")
    if paid_state is not PaidApiBudgetState.ACTIVE:
        states.append(f"paid_api_budget_state:{paid_state.value}")
    if bootstrap_state not in {
        BootstrapDependencyState.NONE,
        BootstrapDependencyState.ACTIVE,
    }:
        states.append(f"bootstrap_dependency_state:{bootstrap_state.value}")
    if subscription_state is not SubscriptionQuotaState.FRESH:
        states.append(f"subscription_quota_state:{subscription_state.value}")
    if local_resource_state not in {LocalResourceState.GREEN, LocalResourceState.YELLOW}:
        states.append(f"local_resource_state:{local_resource_state.value}")
    if overdue_receipts:
        states.append("spend_reconciliation_overdue")
    return states


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise QuotaSpendLedgerError(f"{path} did not contain a JSON object")
    return payload


def _coerce_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(tz=UTC)
    _require_aware(now, "now")
    return now.astimezone(UTC)


def _normalize_route_id(route_id: str) -> str:
    return route_id.strip().replace("/", ".")


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _require_unique(label: str, values: list[str]) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} values must be unique")


def _reject_private_or_identity_refs(refs: list[str], label: str) -> None:
    if any(ref.startswith(("/", "~")) for ref in refs):
        raise ValueError(f"{label} refs must stay repo-relative or symbolic")
    if any("@" in ref for ref in refs):
        raise ValueError(f"{label} refs must not contain raw email addresses")


def _refs(*values: str | None) -> list[str]:
    return [value for value in values if value is not None]


_PYDANTIC_DYNAMIC_ENTRYPOINTS = (
    QuotaMeasurement._measurement_contract,
    TransitionBudget._budget_contract,
    SpendReceipt._receipt_contract,
    ProviderDependencyRecord._dependency_contract,
    ArtifactProvenanceRecord._provenance_contract,
    RenewalRecord._renewal_contract,
    QuotaSnapshot._quota_snapshot_contract,
    PaidRouteRequest._paid_route_request_contract,
    SpendGateDecisionRecord._decision_contract,
    QuotaSpendLedger._ledger_contract,
)


__all__ = [
    "DEFAULT_QUOTA_SPEND_LEDGER_LIVE",
    "PAID_CAPACITY_POOLS",
    "QUOTA_SPEND_LEDGER_FIXTURES",
    "QUOTA_SPEND_LEDGER_LIVE_ENV",
    "ArtifactProvenanceRecord",
    "AuthSurface",
    "BootstrapDependencyState",
    "BudgetApproval",
    "BudgetLifecycleState",
    "CapacityPool",
    "DependencyState",
    "Effort",
    "LocalResourceState",
    "ModelId",
    "PaidApiBudgetState",
    "PaidRouteEligibility",
    "PaidRouteRequest",
    "ProviderDependencyRecord",
    "QuotaSnapshot",
    "QuotaSpendDashboard",
    "Quantization",
    "QuotaSpendLedger",
    "QuotaSpendLedgerError",
    "RenewalRecord",
    "ResolvedQuotaSpendLedger",
    "RouteAvailability",
    "SpendReason",
    "SpendGateDecisionRecord",
    "SpendGateDecisionState",
    "SpendReceipt",
    "SteadyStateReplacement",
    "SubscriptionQuotaState",
    "SupportArtifactAuthority",
    "TransitionBudget",
    "build_dashboard",
    "evaluate_paid_route_eligibility",
    "load_quota_spend_ledger",
    "load_quota_spend_ledger_resolved",
    "subscription_quota_state_for_route",
]
