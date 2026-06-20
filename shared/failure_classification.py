"""Shared failure-classification vocabulary — the measurement-spine root of the CapabilityAdapter.

A single ``FailureCode`` taxonomy + a lossless ``FailureReceipt`` shared across the review plane
(``scripts/review_team.py``) and the worker/provider plane (``scripts/hapax-glmcp-reviewer``), so a
reviewer wall and a worker quota wall speak the same language.

IMPORTANT — ``FailureCode`` is intentionally FINER than the four dispatch verdicts
(quota-wall / reviewer-route-unavailable / provider-outage / invalid-output). The receipt records the
fine code; the dispatch verdict layer COLLAPSES many codes into one verdict exactly as it does today
(e.g. rate_limited*, account_*, fair_use_restricted, plan_model_unavailable all stay in the review_team
QUOTA allowlist → quota-wall verdict). This module only supplies the vocabulary + data tables; it carries
NO channel-trust regex/parse logic and NO verdict decision. NEVER move an error_class between the
``STRUCTURED_*`` allowlists or the dispatch verdicts will drift.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class FailureCode(StrEnum):
    """The structured failure taxonomy (finer than the dispatch verdicts). Default to UNKNOWN on an
    ambiguous signal — never auto-degrade. CLAIM_CONFLICT is reserved (no producer in this slice)."""

    QUOTA_EXHAUSTION = "quota_exhaustion"
    PROVIDER_OUTAGE = "provider_outage"
    AUTH_FAILURE = "auth_failure"
    CLAIM_CONFLICT = "claim_conflict"
    ROUTE_UNAVAILABLE = "route_unavailable"
    FAIR_USE_RESTRICTED = "fair_use_restricted"
    INVALID_OUTPUT = "invalid_output"
    TRANSIENT = "transient"
    UNKNOWN = "unknown"


# The four dispatch verdict literals, kept identical to today's strings so the collapse lives in one
# place and nothing downstream changes. (cc-pr-review-dispatch.py owns the strict else-if priority.)
VERDICT_QUOTA_WALL = "quota-wall"
VERDICT_REVIEWER_ROUTE_UNAVAILABLE = "reviewer-route-unavailable"
VERDICT_PROVIDER_OUTAGE = "provider-outage"
VERDICT_INVALID_OUTPUT = "invalid-output"


class FailureReceipt(BaseModel):
    """A lossless structured record of a classified failure. Frozen + extra-forbid (the project's
    StrictModel convention is inline ConfigDict — there is no shared StrictModel base). Nothing the
    classifiers surface is dropped: raw_signal + platform + route_id + the zai diagnostic fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: FailureCode = FailureCode.UNKNOWN
    raw_signal: str = ""
    platform: str | None = None
    route_id: str | None = None
    zai_code: str | None = None
    error_class: str | None = None
    action: str | None = None
    resets_at: str | None = None
    message: str | None = None
    http_status: int | None = None


# The Z.ai inner-business-code table — byte-identical to scripts/hapax-glmcp-reviewer's former
# _ZAI_ERROR_CLASS_BY_CODE (21 entries). Single source of truth; glmcp imports it from here.
ZAI_ERROR_CLASS_BY_CODE: dict[str, tuple[str, str]] = {
    "1000": ("auth_failed", "check_api_key"),
    "1001": ("auth_failed", "check_api_key"),
    "1002": ("auth_failed", "check_api_key"),
    "1003": ("auth_failed", "refresh_api_key"),
    "1004": ("auth_failed", "check_api_key"),
    "1110": ("account_hard_hold", "contact_provider"),
    "1112": ("account_hard_hold", "contact_provider"),
    "1113": ("account_balance_or_arrears", "hold_no_payg_fallback"),
    "1121": ("account_hard_hold", "contact_provider"),
    "1211": ("model_not_found", "check_model_configuration"),
    "1261": ("prompt_too_long", "reduce_prompt_size"),
    "1302": ("rate_limited_concurrency", "backoff_reduce_concurrency"),
    "1303": ("rate_limited_frequency", "backoff_reduce_frequency"),
    "1304": ("daily_limit_exhausted", "hold_until_limit_reset"),
    "1305": ("rate_limited", "backoff"),
    "1308": ("quota_exhausted", "hold_until_reset"),
    "1309": ("subscription_expired", "hold_until_subscription_restored"),
    "1310": ("quota_exhausted", "hold_until_reset"),
    "1311": ("plan_model_unavailable", "switch_model_or_upgrade_plan"),
    "1312": ("provider_high_traffic", "backoff_or_switch_model"),
    "1313": ("fair_use_restricted", "hold_until_manual_clear"),
}

# error_class strings that classify_zai_error's FALLBACK ladder (HTTP-status branches) produces but
# that never appear in the code table above — needed so the sync guard is not falsely tripped.
FALLBACK_LADDER_ERROR_CLASSES: frozenset[str] = frozenset({"provider_error", "api_error"})

# Every error_class string the codebase can produce → its FailureCode. api_error is the no-auto-degrade
# default (UNKNOWN). The account-hold / subscription / prompt_too_long mappings are RECEIPT-CODE choices
# (verdict-neutral — they stay in the review_team QUOTA allowlist so the verdict is unaffected).
ZAI_ERROR_CLASS_TO_FAILURE_CODE: dict[str, FailureCode] = {
    "auth_failed": FailureCode.AUTH_FAILURE,
    "account_hard_hold": FailureCode.FAIR_USE_RESTRICTED,
    "account_balance_or_arrears": FailureCode.FAIR_USE_RESTRICTED,
    "model_not_found": FailureCode.ROUTE_UNAVAILABLE,
    "prompt_too_long": FailureCode.INVALID_OUTPUT,
    "rate_limited_concurrency": FailureCode.TRANSIENT,
    "rate_limited_frequency": FailureCode.TRANSIENT,
    "daily_limit_exhausted": FailureCode.QUOTA_EXHAUSTION,
    "rate_limited": FailureCode.TRANSIENT,
    "quota_exhausted": FailureCode.QUOTA_EXHAUSTION,
    "subscription_expired": FailureCode.FAIR_USE_RESTRICTED,
    "plan_model_unavailable": FailureCode.ROUTE_UNAVAILABLE,
    "provider_high_traffic": FailureCode.PROVIDER_OUTAGE,  # cc-task PINS this to PROVIDER_OUTAGE
    "fair_use_restricted": FailureCode.FAIR_USE_RESTRICTED,
    "provider_error": FailureCode.PROVIDER_OUTAGE,
    "api_error": FailureCode.UNKNOWN,
}


def failure_code_for_zai(error_class: str) -> FailureCode:
    """Map a Z.ai error_class string to its FailureCode; UNKNOWN for anything unmapped (no degrade)."""
    return ZAI_ERROR_CLASS_TO_FAILURE_CODE.get(error_class, FailureCode.UNKNOWN)


# The structured-envelope allowlists — byte-identical to scripts/review_team.py's former in-file
# literals. review_team aliases these so the structured-zai-envelope classification stays unchanged.
# DO NOT move a class between QUOTA and PROVIDER_OUTAGE here — that would change is_quota_wall /
# is_provider_outage verdicts.
STRUCTURED_QUOTA_ERROR_CLASSES: frozenset[str] = frozenset(
    {
        "account_balance_or_arrears",
        "account_hard_hold",
        "daily_limit_exhausted",
        "fair_use_restricted",
        "plan_model_unavailable",
        "quota_exhausted",
        "rate_limited",
        "rate_limited_concurrency",
        "rate_limited_frequency",
        "subscription_expired",
    }
)
STRUCTURED_QUOTA_ACTIONS: frozenset[str] = frozenset(
    {
        "backoff",
        "backoff_reduce_concurrency",
        "backoff_reduce_frequency",
        "contact_provider",
        "hold_no_payg_fallback",
        "hold_until_limit_reset",
        "hold_until_manual_clear",
        "hold_until_reset",
        "hold_until_subscription_restored",
        "switch_model_or_upgrade_plan",
    }
)
STRUCTURED_PROVIDER_OUTAGE_ERROR_CLASSES: frozenset[str] = frozenset(
    {
        "provider_error",
        "provider_high_traffic",
    }
)
STRUCTURED_PROVIDER_OUTAGE_ACTIONS: frozenset[str] = frozenset(
    {
        "backoff_or_switch_model",
        "retry_later",
    }
)
