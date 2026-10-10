"""Observed GLM transport and durable spend operations shared with the legacy reviewer.

No route selection, credential discovery, retry, or fallback happens here. Callers
must supply current admission; publication's adapter checks it at this boundary.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from shared.failure_classification import ZAI_ERROR_CLASS_BY_CODE, FailureCode, failure_code_for_zai
from shared.platform_capability_registry import ExecutionDescriptor
from shared.quota_spend_ledger import (
    GLMCP_MODEL_IDS,
    CapacityPool,
    PaidRouteRequest,
    QuotaSpendLedgerError,
    SpendReason,
    SpendReceipt,
    evaluate_paid_route_eligibility,
    frozen_spend_receipt_payload,
    glmcp_payg_reservation_usd,
    glmcp_payg_usage_ceiling_usd,
    glmcp_payg_usage_cost_usd,
    load_quota_spend_ledger,
    load_quota_spend_ledger_resolved,
)

REASONING_BUDGET_EXHAUSTED = "reasoning_budget_exhausted"
_RESET_RE = re.compile(
    r"(?:reset|resets|will reset)\s+(?:at|on|in)?\s*([^.;,\n]+(?:T[^.;,\n]+)?)",
    re.IGNORECASE,
)
_ZAI_CODE_RE = re.compile(r"\A\d{3,8}\Z")
_STRUCTURED_VALUE_SEPARATOR_RE = re.compile(r"[;\s\x00-\x1f\x7f-\x9f\u2028\u2029]+")


class ApiError(RuntimeError):
    """Provider/API failure."""


class ProviderReplyUnusable(ApiError):
    """The provider answered (on PAYG, it billed) but the reply is unusable or unidentified.

    Carries the provider observation so PAYG spend is reconciled from the reported usage
    instead of staying pending with no evidence of what was charged.
    """

    def __init__(self, message: str, *, observation: ProviderObservation) -> None:
        self.observation = observation
        super().__init__(message)


class ReasoningBudgetExhausted(ProviderReplyUnusable):
    """The model spent the whole completion budget reasoning and produced no content.

    Billed and unusable like its parent, but named, so the dispatcher treats the seat as
    unavailable instead of as a reviewer that answered badly.
    """


class ReplyTruncated(ProviderReplyUnusable):
    """The provider stopped the reply at max_tokens: a partial review, never a complete one.

    Billed and unusable like its parent, named so a truncation is not read as invalid output,
    and retryable: the same seat may finish on a second run.
    """


class ZaiHttpError(ApiError):
    """Structured Z.ai HTTP failure that may be eligible for a governed fallback."""

    def __init__(
        self,
        *,
        status: int,
        detail: str,
        secret: str,
        base_url: str,
        provider_label: str,
    ) -> None:
        self.status = status
        self.detail = detail
        self.info = classify_zai_error(status, detail)
        self.base_url = base_url
        self.provider_label = provider_label
        super().__init__(format_zai_error(status, detail, secret=secret))


@dataclass(frozen=True)
class ZaiErrorInfo:
    code: str | None
    error_class: str
    action: str
    resets_at: str | None
    message: str | None
    # the shared structured taxonomy code, derived from error_class (telemetry; format_zai_error
    # does not read it, so the formatted ApiError string is unchanged).
    failure_code: FailureCode = FailureCode.UNKNOWN


@dataclass(frozen=True)
class ProviderObservation:
    """What the provider reported executing: served model, finish reason, token usage."""

    served_model: str | None = None
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    cached_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None

    def has_usage(self) -> bool:
        return self.prompt_tokens is not None and self.completion_tokens is not None


def _refuse_redirect(*_args: object, **_kwargs: object) -> None:
    """Never replay Authorization to a redirected origin."""
    return None


def chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def redact(text: str, secret: str) -> str:
    return text.replace(secret, "<redacted>") if secret else text


def open_no_redirect(request: urllib.request.Request, *, timeout: float) -> Any:
    handler = urllib.request.HTTPRedirectHandler()
    handler.redirect_request = _refuse_redirect
    opener = urllib.request.build_opener(handler)
    return opener.open(request, timeout=timeout)


def safe_structured_value(value: str, *, max_chars: int) -> str:
    return _STRUCTURED_VALUE_SEPARATOR_RE.sub(" ", value).strip()[:max_chars]


def _coerce_error_payload(detail: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _first_string(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
    return None


def _extract_reset_hint(error_obj: dict[str, Any], message: str | None) -> str | None:
    for key in ("next_flush_time", "nextFlushTime", "resets_at", "reset_at", "resetAt"):
        value = error_obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
    if message:
        match = _RESET_RE.search(message)
        if match:
            return match.group(1).strip()
    return None


def classify_zai_error(status: int, detail: str) -> ZaiErrorInfo:
    """Classify a Z.ai API failure into quota/admission language.

    The official API returns an HTTP status plus an inner business error code.
    Keep this local and string-based so tests can exercise it without live calls.
    """

    payload = _coerce_error_payload(detail)
    error_obj: dict[str, Any] = {}
    if payload is not None:
        raw_error = payload.get("error")
        if isinstance(raw_error, dict):
            error_obj = raw_error
        else:
            error_obj = payload

    message = _first_string(
        error_obj.get("message"),
        payload.get("message") if payload is not None else None,
    )
    code = _first_string(
        error_obj.get("code"),
        payload.get("code") if payload is not None else None,
    )
    resets_at = _extract_reset_hint(error_obj, message)

    if code in ZAI_ERROR_CLASS_BY_CODE:
        error_class, action = ZAI_ERROR_CLASS_BY_CODE[code]
    elif status == 401:
        error_class, action = "auth_failed", "check_api_key"
    elif status == 429:
        lower = (message or detail).lower()
        if "insufficient balance" in lower or "arrears" in lower:
            error_class, action = "account_balance_or_arrears", "hold_no_payg_fallback"
        elif "account anomaly" in lower or "locked" in lower or "violation" in lower:
            error_class, action = "account_hard_hold", "contact_provider"
        elif "quota" in lower or "usage limit" in lower or "limit exhausted" in lower:
            error_class, action = "quota_exhausted", "hold_until_reset"
        elif "traffic" in lower or "overload" in lower or "temporarily" in lower:
            error_class, action = "provider_high_traffic", "backoff_or_switch_model"
        else:
            error_class, action = "rate_limited", "backoff"
    elif 500 <= status < 600:
        error_class, action = "provider_error", "retry_later"
    else:
        error_class, action = "api_error", "inspect_provider_response"

    return ZaiErrorInfo(
        code=code,
        error_class=error_class,
        action=action,
        resets_at=resets_at,
        message=message,
        failure_code=failure_code_for_zai(error_class),
    )


def format_zai_error(status: int, detail: str, *, secret: str) -> str:
    info = classify_zai_error(status, detail)
    redacted_detail = redact(detail, secret).strip()
    parts = [f"HTTP {status}"]
    if info.code:
        code = info.code if _ZAI_CODE_RE.fullmatch(info.code) else "untrusted"
        parts.append(f"zai_error_code={code}")
    parts.append(f"error_class={info.error_class}")
    parts.append(f"action={info.action}")
    if info.resets_at:
        resets_at = safe_structured_value(redact(info.resets_at, secret), max_chars=120)
        if resets_at:
            parts.append(f"resets_at={resets_at}")
    message_value = ""
    if info.message:
        message_value = safe_structured_value(redact(info.message, secret), max_chars=240)
        if message_value:
            parts.append(f"message={message_value}")
    if redacted_detail:
        detail_value = safe_structured_value(redacted_detail, max_chars=1000)
        if detail_value and detail_value != message_value:
            parts.append(f"detail={detail_value}")
    return "; ".join(parts)


def _usage_count(container: object, key: str) -> int | None:
    if not isinstance(container, dict):
        return None
    value = container.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _provider_observation(payload: dict[str, Any]) -> ProviderObservation:
    usage = payload.get("usage")
    choices = payload.get("choices")
    first = choices[0] if isinstance(choices, list) and choices else None
    finish = first.get("finish_reason") if isinstance(first, dict) else None
    served = payload.get("model")
    return ProviderObservation(
        served_model=safe_structured_value(served, max_chars=80)
        if isinstance(served, str)
        else None,
        finish_reason=safe_structured_value(finish, max_chars=40)
        if isinstance(finish, str)
        else None,
        prompt_tokens=_usage_count(usage, "prompt_tokens"),
        cached_tokens=_usage_count(
            usage.get("prompt_tokens_details") if isinstance(usage, dict) else None,
            "cached_tokens",
        ),
        completion_tokens=_usage_count(usage, "completion_tokens"),
        reasoning_tokens=_usage_count(
            usage.get("completion_tokens_details") if isinstance(usage, dict) else None,
            "reasoning_tokens",
        ),
    )


def _append_spend_receipt_to_live_ledger(*, ledger_path: Path, receipt: SpendReceipt) -> None:
    try:
        ledger = load_quota_spend_ledger(ledger_path)
        payload = ledger.model_dump(mode="json")
        existing_ids = {item["spend_id"] for item in payload["spend_receipts"]}
        if receipt.spend_id not in existing_ids:
            payload["spend_receipts"] = [
                *payload["spend_receipts"],
                receipt.model_dump(mode="json"),
            ]
        _write_json_atomic(ledger_path, payload)
    except (OSError, QuotaSpendLedgerError, ValueError) as exc:
        raise ApiError(
            "PAYG fallback refused by paid-spend gate: could not reserve spend in live "
            f"quota/spend ledger ({type(exc).__name__}); rerun "
            "scripts/hapax-quota-telemetry-writer --json and retry"
        ) from exc


def _replace_spend_receipt_in_live_ledger(*, ledger_path: Path, receipt: SpendReceipt) -> None:
    try:
        ledger = load_quota_spend_ledger(ledger_path)
        payload = ledger.model_dump(mode="json")
        replaced = False
        next_receipts: list[dict[str, object]] = []
        for existing in payload["spend_receipts"]:
            if existing["spend_id"] == receipt.spend_id:
                next_receipts.append(receipt.model_dump(mode="json"))
                replaced = True
            else:
                next_receipts.append(existing)
        if not replaced:
            next_receipts.append(receipt.model_dump(mode="json"))
        payload["spend_receipts"] = next_receipts
        _write_json_atomic(ledger_path, payload)
    except (OSError, QuotaSpendLedgerError, ValueError) as exc:
        raise ApiError(
            "PAYG fallback could not reconcile spend receipt in live quota/spend "
            f"ledger ({type(exc).__name__}); run scripts/hapax-quota-telemetry-writer "
            "--json before retrying"
        ) from exc


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, indent=1, sort_keys=True) + "\n"
    try:
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    except OSError as exc:
        raise ApiError(
            "PAYG fallback refused by paid-spend gate: could not create live ledger "
            f"reservation temp file; ledger={path}"
        ) from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise ApiError(
            "PAYG fallback refused by paid-spend gate: could not commit live ledger "
            f"reservation; ledger={path}"
        ) from exc
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def call_once_observed(
    payload: Mapping[str, object],
    api_key: str,
    *,
    base_url: str,
    provider_label: str,
    timeout_seconds: float,
    opener: Callable[..., Any] | None = None,
) -> tuple[str, ProviderObservation]:
    """One synchronous request; retain identity and usage from that very response."""
    body = json.dumps(payload).encode("utf-8")
    max_tokens = int(payload["max_tokens"])
    thinking = payload["thinking"]["type"]
    request = urllib.request.Request(
        chat_url(base_url),
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with (opener or open_no_redirect)(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            location = ""
            if exc.headers is not None:
                location = str(exc.headers.get("Location", ""))
            raise ApiError(
                f"HTTP {exc.code}: redirect refused before replaying Authorization; "
                f"location={redact(location, api_key)[:300] or 'unknown'}; "
                "check HAPAX_GLMCP_REVIEW_BASE_URL and rerun with a reviewed "
                "https://api.z.ai/ endpoint"
            ) from exc
        detail = exc.read().decode("utf-8", errors="replace")
        raise ZaiHttpError(
            status=exc.code,
            detail=detail or str(exc.reason),
            secret=api_key,
            base_url=base_url,
            provider_label=provider_label,
        ) from exc
    except urllib.error.URLError as exc:
        raise ApiError(
            f"network error: {exc.reason}; retry later or check the Z.ai {provider_label} endpoint"
        ) from exc
    except TimeoutError as exc:
        raise ApiError(
            f"request timed out after {timeout_seconds:g}s; retry later or reduce "
            "the review prompt size"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ApiError(
            f"invalid JSON response: {exc}; retry later or check the Z.ai Coding Plan endpoint"
        ) from exc

    if not isinstance(payload, dict):
        raise ApiError(
            "response JSON was not an object; retry later or capture the provider payload for review"
        )

    observation = _provider_observation(payload)
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderReplyUnusable(
            "response missing choices; retry later or capture the provider payload for review",
            observation=observation,
        )
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise ProviderReplyUnusable(
            "response missing message; retry later or capture the provider payload for review",
            observation=observation,
        )
    content: Any = message.get("content")
    if isinstance(content, str):
        reply = content
    elif isinstance(content, list):
        parts: list[str] = []
        unexpected_parts = False
        for part in content:
            if not isinstance(part, dict):
                unexpected_parts = True
                continue
            text_part = part.get("text") if part.get("text") is not None else part.get("content")
            if text_part is None:
                unexpected_parts = True
            else:
                parts.append(str(text_part))
        reply = "".join(parts)
        if unexpected_parts and not reply.strip():
            raise ProviderReplyUnusable(
                "response content parts had no text/content; retry later or capture the "
                "provider payload for review",
                observation=observation,
            )
    elif content is None:
        reply = ""
    else:
        raise ProviderReplyUnusable(
            "response message has no text content; retry later or capture the provider "
            "payload for review",
            observation=observation,
        )
    if reply.strip() and observation.finish_reason == "length":
        raise ReplyTruncated(
            "the provider cut the reply at max_tokens "
            f"(finish_reason=length completion_tokens={observation.completion_tokens} "
            f"reasoning_tokens={observation.reasoning_tokens} max_tokens={max_tokens}); "
            "the partial review was not used; retry the seat, or raise "
            "HAPAX_GLMCP_REVIEW_MAX_TOKENS if it recurs",
            observation=observation,
        )
    if not reply.strip():
        reasoning = message.get("reasoning_content")
        if thinking == "enabled" and isinstance(reasoning, str) and reasoning.strip():
            if observation.finish_reason == "length" or (
                observation.completion_tokens is not None
                and observation.completion_tokens >= max_tokens
            ):
                raise ReasoningBudgetExhausted(
                    f"{REASONING_BUDGET_EXHAUSTED}: reasoning consumed the completion budget "
                    f"and left no content (completion_tokens={observation.completion_tokens} "
                    f"reasoning_tokens={observation.reasoning_tokens} "
                    f"max_tokens={max_tokens} finish_reason={observation.finish_reason}); "
                    "the seat cannot vote on this budget; raise PAYG_THINKING_MIN_MAX_TOKENS "
                    "in hapax-glmcp-reviewer or hold the GLM family",
                    observation=observation,
                )
            raise ProviderReplyUnusable(
                "response content was empty but reasoning_content was present; rerun with "
                "HAPAX_GLMCP_REVIEW_THINKING=disabled for review-quorum output",
                observation=observation,
            )
        raise ProviderReplyUnusable(
            "response message was empty; retry later or rerun with "
            "HAPAX_GLMCP_REVIEW_THINKING=disabled",  # pragma: allowlist secret - public setting
            observation=observation,
        )
    return reply, observation


@contextmanager
def quota_spend_lock(ledger_path: Path) -> Iterator[None]:
    lock_path = ledger_path.with_name(f"{ledger_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def execute_paid_completion(
    *,
    request: PaidRouteRequest,
    descriptor: ExecutionDescriptor,
    authority_case: str,
    budget_id: str,
    task_hash: str,
    ledger_path: Path,
    messages: Sequence[Mapping[str, str]],
    temperature: float,
    max_tokens: int,
    thinking: str,
    timeout_seconds: float,
    base_url: str,
    api_key: str,
    spend_reason: SpendReason,
    quality_preservation_reason: str,
    require_admission: Callable[[], None],
) -> tuple[str, ProviderObservation, SpendReceipt]:
    """Reserve, execute once, then durably reconcile before exposing any content.

    The admitted caller owns route/executor qualification. This is the existing
    GLM PAYG transport only; it never interprets a review-seat quota failure.
    A failed/uncertain call freezes its reservation; this function never retries.
    """
    descriptor = ExecutionDescriptor.model_validate(descriptor.model_dump())
    request = PaidRouteRequest.model_validate(request.model_dump())
    models = {str(identity): model for model, identity in GLMCP_MODEL_IDS.items()}
    model = models.get(str(descriptor.model_id))
    if (
        model is None
        or descriptor.effort != "none"
        or descriptor.context_mode != "standard"
        or descriptor.fast_mode != "off"
        or descriptor.quantization != "none"
        or request.provider != "z_ai"
        or request.capacity_pool != CapacityPool.API_PAID_SPEND
        or base_url != "https://api.z.ai/api/paas/v4"
        or thinking not in {"enabled", "disabled"}
        or max_tokens < 1
        or timeout_seconds <= 0
    ):
        raise ApiError("unsupported concrete completion descriptor or transport")
    # Snapshot the entire request; callers cannot mutate messages between pricing and send.
    message_snapshot = json.loads(json.dumps(messages))
    if not message_snapshot or any(
        not isinstance(item, dict)
        or set(item) != {"role", "content"}
        or item["role"] not in {"system", "user", "assistant"}
        or not isinstance(item["content"], str)
        for item in message_snapshot
    ):
        raise ApiError("unsupported completion messages")
    payload = {
        "model": model,
        "messages": message_snapshot,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking": {"type": thinking},
        "stream": False,
    }
    estimated = glmcp_payg_reservation_usd(
        model=model,
        prompt_utf8_bytes=len(json.dumps(message_snapshot).encode("utf-8")),
        max_tokens=max_tokens,
    )
    if request.estimated_cost_usd < estimated:
        raise ApiError("declared completion estimate does not cover the full request")
    # The caller supplied this ceiling; retaining it cannot enlarge the approved budget.
    with quota_spend_lock(ledger_path):
        require_admission()
        resolved = load_quota_spend_ledger_resolved(live_path=ledger_path)
        decision = evaluate_paid_route_eligibility(resolved.ledger, request)
        if (
            resolved.source != "live"
            or resolved.path != ledger_path
            or not decision.eligible
            or decision.state != "eligible_active_budget"
            or decision.budget_id != budget_id
            or decision.cap_remaining_usd is None
        ):
            raise ApiError(
                "completion spend admission refused: " + "; ".join(decision.blocking_reasons)
            )
        budget = resolved.ledger.budget_by_id(budget_id)
        if budget.authority_case != authority_case:
            raise ApiError("completion budget authority mismatch")
        now = datetime.now(UTC)
        receipt = SpendReceipt.model_validate(
            {
                "spend_id": f"spend-{now:%Y%m%dT%H%M%SZ}-glm-completion-{uuid.uuid4().hex}",
                "task_id": request.task_id,
                "task_hash": task_hash,
                "authority_case": authority_case,
                "route_id": request.route_id,
                "capacity_pool": request.capacity_pool,
                "budget_id": budget_id,
                "provider": request.provider,
                "model_or_engine": model,
                "model_id": descriptor.model_id,
                "effort": descriptor.effort,
                "quantization": descriptor.quantization,
                "auth_surface": "api_key",
                "quality_floor": request.quality_floor,
                "quality_preservation_reason": quality_preservation_reason,
                "spend_reason": spend_reason,
                "estimated_cost_usd": request.estimated_cost_usd,
                "cap_remaining_usd": decision.cap_remaining_usd,
                "created_at": now,
                "reconcile_by": now + timedelta(hours=24),
                "artifact_refs": (
                    "request:sha256:"
                    + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                ),
            }
        )
        _append_spend_receipt_to_live_ledger(ledger_path=ledger_path, receipt=receipt)
        _require_owned_reservation(ledger_path, receipt)
    observation = None
    try:
        reply, observation = call_once_observed(
            payload,
            api_key,
            base_url=base_url,
            provider_label="admitted completion",
            timeout_seconds=timeout_seconds,
        )
        if observation.served_model != model:
            raise ApiError("completion served model missing or mismatched")
        if not observation.has_usage() or observation.finish_reason != "stop":
            raise ApiError("completion outcome or usage ambiguous")
        if (
            observation.completion_tokens > max_tokens
            or (observation.reasoning_tokens or 0) > observation.completion_tokens
        ):
            raise ApiError("completion usage exceeds the admitted token bound")
        actual = glmcp_payg_usage_cost_usd(
            model=model,
            prompt_tokens=observation.prompt_tokens,
            cached_tokens=observation.cached_tokens or 0,
            completion_tokens=observation.completion_tokens,
        )
        if actual > receipt.estimated_cost_usd:
            raise ApiError("completion usage exceeds its reservation")
        with quota_spend_lock(ledger_path):
            _require_owned_reservation(ledger_path, receipt)
            completed = SpendReceipt.model_validate(
                {
                    **receipt.model_dump(),
                    "actual_cost_usd": actual,
                    "cap_remaining_usd": receipt.cap_remaining_usd
                    + receipt.estimated_cost_usd
                    - actual,
                    "reconciliation_state": "reconciled",
                    "reconciled_at": datetime.now(UTC),
                    "reconciliation_reason": "same-call provider-reported identity and usage at list price; not an invoice",
                }
            )
            _replace_spend_receipt_in_live_ledger(ledger_path=ledger_path, receipt=completed)
            _require_owned_reservation(ledger_path, completed)
        return reply, observation, completed
    except BaseException as exc:
        # Even interruption/unknown transport failure may follow a billable request.
        if isinstance(exc, ProviderReplyUnusable):
            observation = exc.observation
        with quota_spend_lock(ledger_path):
            _require_owned_reservation(ledger_path, receipt)
            count = Decimal("0")
            if observation is not None and observation.has_usage():
                count = glmcp_payg_usage_ceiling_usd(
                    prompt_tokens=observation.prompt_tokens,
                    completion_tokens=observation.completion_tokens,
                )
            frozen = SpendReceipt.model_validate(
                frozen_spend_receipt_payload(
                    receipt.model_dump(mode="json"),
                    count_usd=count,
                    frozen_at=datetime.now(UTC).isoformat(),
                    reason=f"completion outcome held ({type(exc).__name__}); independent reconciliation required",
                )
            )
            _replace_spend_receipt_in_live_ledger(ledger_path=ledger_path, receipt=frozen)
        raise


def _require_owned_reservation(ledger_path: Path, expected: SpendReceipt) -> None:
    matches = [
        r
        for r in load_quota_spend_ledger(ledger_path).spend_receipts
        if r.spend_id == expected.spend_id
    ]
    if matches != [expected]:
        raise ApiError("completion reservation absent, changed or foreign; content held")
