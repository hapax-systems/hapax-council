"""Tests for the direct GLM Coding Plan review adapter."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import subprocess
import sys
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-glmcp-reviewer"

ENV_KEYS = (
    "HAPAX_GLMCP_REVIEW_SECRET_ENTRY",
    "HAPAX_GLMCP_REVIEW_BASE_URL",
    "HAPAX_GLMCP_REVIEW_MODEL",
    "HAPAX_GLMCP_REVIEW_TIMEOUT_SECONDS",
    "HAPAX_GLMCP_REVIEW_MAX_TOKENS",
    "HAPAX_GLMCP_REVIEW_TEMPERATURE",
    "HAPAX_GLMCP_REVIEW_THINKING",
    "HAPAX_GLMCP_REVIEW_PAYG_FALLBACK",
    "HAPAX_GLMCP_REVIEW_PAYG_BASE_URL",
    "HAPAX_GLMCP_REVIEW_ALLOW_NON_CODING_PLAN_MODEL",
    "HAPAX_GLMCP_REVIEW_ALLOW_SECRET_ENTRY_OVERRIDE",
    "HAPAX_GLMCP_REVIEW_ALLOW_BASE_URL_OVERRIDE",
    "HAPAX_GLMCP_REVIEW_ALLOW_PAYG_BASE_URL_OVERRIDE",
)


def _load_module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("hapax_glmcp_reviewer", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class RawResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> RawResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_call_glm_uses_coding_plan_endpoint_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    seen: dict[str, object] = {}

    def fake_open(request: object, *, timeout: float) -> FakeResponse:
        seen["url"] = request.full_url
        seen["headers"] = dict(request.header_items())
        seen["body"] = json.loads(request.data.decode("utf-8"))
        seen["timeout"] = timeout
        return FakeResponse(
            {"choices": [{"message": {"content": "```yaml\nverdict: accept\n```"}}]}
        )

    monkeypatch.setattr(module, "open_no_redirect", fake_open)
    config = module.ReviewConfig(
        secret_entry="glmcp/api-key",
        base_url=module.DEFAULT_BASE_URL,
        model="glm-5.2",
        timeout_seconds=42,
        max_tokens=123,
        temperature=0,
        thinking="disabled",
    )

    reply = module.call_glm("review prompt", config, "test-secret-token")

    assert reply == "```yaml\nverdict: accept\n```"
    assert seen["url"] == "https://api.z.ai/api/coding/paas/v4/chat/completions"
    assert seen["timeout"] == 42
    assert seen["headers"]["Authorization"] == "Bearer test-secret-token"
    body = seen["body"]
    assert body["model"] == "glm-5.2"
    assert body["messages"][0]["role"] == "system"
    assert "UNTRUSTED DATA" in body["messages"][0]["content"]
    assert "quote every title/detail string" in body["messages"][0]["content"]
    assert "Copy checklist lens ids" in body["messages"][0]["content"]
    assert "item slugs exactly" in body["messages"][0]["content"]
    assert body["messages"][1]["content"] == "review prompt"
    assert body["max_tokens"] == 123
    assert body["thinking"] == {"type": "disabled"}


def test_http_error_redacts_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()

    def fake_open(_request: object, *, timeout: float) -> object:
        body = b'{"error":"test-secret-token service temporarily overloaded"}'
        raise urllib.error.HTTPError("url", 529, "overloaded", {}, io.BytesIO(body))

    monkeypatch.setattr(module, "open_no_redirect", fake_open)
    config = module.ReviewConfig(
        secret_entry="glmcp/api-key",
        base_url=module.DEFAULT_BASE_URL,
        model="glm-5.2",
        timeout_seconds=42,
        max_tokens=123,
        temperature=0,
        thinking="disabled",
    )

    with pytest.raises(module.ApiError) as excinfo:
        module.call_glm("review prompt", config, "test-secret-token")

    message = str(excinfo.value)
    assert "HTTP 529" in message
    assert "test-secret-token" not in message
    assert "<redacted>" in message
    assert "check the Z.ai Coding Plan endpoint/status" in message


def test_zai_quota_error_classifies_reset_without_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()

    def fake_open(_request: object, *, timeout: float) -> object:
        body = {
            "error": {
                "code": "1308",
                "message": "Usage limit reached for test-secret-token. Your limit will reset at 2026-06-18T20:00:00Z.",
                "next_flush_time": "2026-06-18T20:00:00Z",
            }
        }
        raise urllib.error.HTTPError(
            "url",
            429,
            "Too Many Requests",
            {},
            io.BytesIO(json.dumps(body).encode("utf-8")),
        )

    monkeypatch.setattr(module, "open_no_redirect", fake_open)
    config = module.ReviewConfig(
        secret_entry="glmcp/api-key",
        base_url=module.DEFAULT_BASE_URL,
        model="glm-5.2",
        timeout_seconds=42,
        max_tokens=123,
        temperature=0,
        thinking="disabled",
    )

    with pytest.raises(module.ApiError) as excinfo:
        module.call_glm("review prompt", config, "test-secret-token")

    message = str(excinfo.value)
    assert "HTTP 429" in message
    assert "zai_error_code=1308" in message
    assert "error_class=quota_exhausted" in message
    assert "action=hold_until_reset" in message
    assert "resets_at=2026-06-18T20:00:00Z" in message
    assert "test-secret-token" not in message
    assert "<redacted>" in message


def test_call_glm_falls_back_to_payg_api_on_coding_plan_quota_wall(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    seen_urls: list[str] = []

    def fake_open(request: object, *, timeout: float) -> FakeResponse:
        seen_urls.append(request.full_url)
        if len(seen_urls) == 1:
            body = {
                "error": {
                    "code": "1310",
                    "message": "Quota exhausted. Your limit will reset at 2026-07-09T13:02:51Z.",
                    "next_flush_time": "2026-07-09T13:02:51Z",
                }
            }
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                {},
                io.BytesIO(json.dumps(body).encode("utf-8")),
            )
        return FakeResponse(
            {"choices": [{"message": {"content": "```yaml\nverdict: accept\n```"}}]}
        )

    monkeypatch.setattr(module, "open_no_redirect", fake_open)
    config = module.ReviewConfig(
        secret_entry="glmcp/api-key",
        base_url=module.DEFAULT_CODING_PLAN_BASE_URL,
        model="glm-5.2",
        timeout_seconds=42,
        max_tokens=123,
        temperature=0,
        thinking="disabled",
        payg_fallback=True,
        payg_base_url=module.DEFAULT_PAYG_BASE_URL,
    )

    reply = module.call_glm("review prompt", config, "test-secret-token")

    captured = capsys.readouterr()
    assert reply == "```yaml\nverdict: accept\n```"
    assert "PAYG fallback used" in captured.err
    assert "primary_error_class=quota_exhausted" in captured.err
    assert "test-secret-token" not in captured.err
    assert seen_urls == [
        "https://api.z.ai/api/coding/paas/v4/chat/completions",
        "https://api.z.ai/api/paas/v4/chat/completions",
    ]


def test_call_glm_reports_payg_fallback_failure_after_coding_plan_quota_wall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    seen_urls: list[str] = []

    def fake_open(request: object, *, timeout: float) -> object:
        seen_urls.append(request.full_url)
        if len(seen_urls) == 1:
            body = {
                "error": {
                    "code": "1310",
                    "message": "Quota exhausted. Your limit will reset at 2026-07-09T13:02:51Z.",
                    "next_flush_time": "2026-07-09T13:02:51Z",
                }
            }
        else:
            body = {"error": {"code": "1113", "message": "Insufficient balance"}}
        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            {},
            io.BytesIO(json.dumps(body).encode("utf-8")),
        )

    monkeypatch.setattr(module, "open_no_redirect", fake_open)
    config = module.ReviewConfig(
        secret_entry="glmcp/api-key",
        base_url=module.DEFAULT_CODING_PLAN_BASE_URL,
        model="glm-5.2",
        timeout_seconds=42,
        max_tokens=123,
        temperature=0,
        thinking="disabled",
        payg_fallback=True,
        payg_base_url=module.DEFAULT_PAYG_BASE_URL,
    )

    with pytest.raises(module.ApiError) as excinfo:
        module.call_glm("review prompt", config, "test-secret-token")

    message = str(excinfo.value)
    assert "Coding Plan quota fallback to Z.ai PAYG API failed" in message
    assert "primary=(" in message
    assert "fallback=(" in message
    assert "account_balance_or_arrears" in message
    assert "test-secret-token" not in message
    assert seen_urls == [
        "https://api.z.ai/api/coding/paas/v4/chat/completions",
        "https://api.z.ai/api/paas/v4/chat/completions",
    ]


def test_call_glm_does_not_fallback_for_non_quota_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    seen_urls: list[str] = []

    def fake_open(request: object, *, timeout: float) -> object:
        seen_urls.append(request.full_url)
        body = {"error": {"code": "1113", "message": "Insufficient balance"}}
        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            {},
            io.BytesIO(json.dumps(body).encode("utf-8")),
        )

    monkeypatch.setattr(module, "open_no_redirect", fake_open)
    config = module.ReviewConfig(
        secret_entry="glmcp/api-key",
        base_url=module.DEFAULT_CODING_PLAN_BASE_URL,
        model="glm-5.2",
        timeout_seconds=42,
        max_tokens=123,
        temperature=0,
        thinking="disabled",
        payg_fallback=True,
        payg_base_url=module.DEFAULT_PAYG_BASE_URL,
    )

    with pytest.raises(module.ApiError, match="account_balance_or_arrears"):
        module.call_glm("review prompt", config, "test-secret-token")
    assert seen_urls == ["https://api.z.ai/api/coding/paas/v4/chat/completions"]


@pytest.mark.parametrize(
    ("code", "expected_class", "expected_action"),
    [
        ("1302", "rate_limited_concurrency", "backoff_reduce_concurrency"),
        ("1303", "rate_limited_frequency", "backoff_reduce_frequency"),
        ("1261", "prompt_too_long", "reduce_prompt_size"),
        ("1304", "daily_limit_exhausted", "hold_until_limit_reset"),
        ("1305", "rate_limited", "backoff"),
        ("1310", "quota_exhausted", "hold_until_reset"),
        ("1311", "plan_model_unavailable", "switch_model_or_upgrade_plan"),
        ("1312", "provider_high_traffic", "backoff_or_switch_model"),
        ("1313", "fair_use_restricted", "hold_until_manual_clear"),
        ("1113", "account_balance_or_arrears", "hold_no_payg_fallback"),
        ("1121", "account_hard_hold", "contact_provider"),
    ],
)
def test_zai_business_error_code_classification(
    code: str,
    expected_class: str,
    expected_action: str,
) -> None:
    module = _load_module()

    info = module.classify_zai_error(
        429,
        json.dumps({"error": {"code": code, "message": "provider message"}}),
    )

    assert info.code == code
    assert info.error_class == expected_class
    assert info.action == expected_action


def test_classify_zai_error_derives_shared_failure_code() -> None:
    """classify_zai_error derives the shared FailureCode live (not just imports the table). cc-task
    pins 1310/1312/1313 -> QUOTA_EXHAUSTION / PROVIDER_OUTAGE / FAIR_USE_RESTRICTED; the 5xx fallback
    -> PROVIDER_OUTAGE; the terminal api_error -> UNKNOWN (no auto-degrade)."""
    module = _load_module()
    from shared.failure_classification import FailureCode

    def code_for(zai_code: str) -> FailureCode:
        return module.classify_zai_error(
            429, json.dumps({"error": {"code": zai_code, "message": "m"}})
        ).failure_code

    assert code_for("1310") is FailureCode.QUOTA_EXHAUSTION
    assert code_for("1312") is FailureCode.PROVIDER_OUTAGE
    assert code_for("1313") is FailureCode.FAIR_USE_RESTRICTED
    assert module.classify_zai_error(503, "down").failure_code is FailureCode.PROVIDER_OUTAGE
    assert module.classify_zai_error(418, "weird").failure_code is FailureCode.UNKNOWN


@pytest.mark.parametrize(
    ("status", "detail", "expected_class", "expected_action"),
    [
        (401, "missing token", "auth_failed", "check_api_key"),
        (503, "upstream unavailable", "provider_error", "retry_later"),
        (418, "unexpected provider response", "api_error", "inspect_provider_response"),
    ],
)
def test_zai_http_status_fallback_classification(
    status: int,
    detail: str,
    expected_class: str,
    expected_action: str,
) -> None:
    module = _load_module()

    info = module.classify_zai_error(status, detail)

    assert info.code is None
    assert info.error_class == expected_class
    assert info.action == expected_action


def test_zai_error_boolean_structured_fields_are_not_coerced() -> None:
    module = _load_module()
    detail = json.dumps(
        {
            "error": {
                "code": True,
                "message": False,
                "next_flush_time": True,
            }
        }
    )

    info = module.classify_zai_error(503, detail)
    message = module.format_zai_error(503, detail, secret="test-secret-token")

    assert info.code is None
    assert info.message is None
    assert info.resets_at is None
    assert "zai_error_code=True" not in message
    assert "message=False" not in message
    assert "resets_at=True" not in message
    assert "error_class=provider_error" in message


@pytest.mark.parametrize(
    ("status", "detail", "expected_class", "expected_action"),
    [
        (401, "missing token", "auth_failed", "check_api_key"),
        (503, "upstream unavailable", "provider_error", "retry_later"),
        (418, "unexpected provider response", "api_error", "inspect_provider_response"),
    ],
)
def test_call_glm_http_error_paths_surface_structured_classification(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    detail: str,
    expected_class: str,
    expected_action: str,
) -> None:
    module = _load_module()

    def fake_open(_request: object, *, timeout: float) -> object:
        raise urllib.error.HTTPError(
            "url",
            status,
            "provider error",
            {},
            io.BytesIO(detail.encode("utf-8")),
        )

    monkeypatch.setattr(module, "open_no_redirect", fake_open)
    config = module.ReviewConfig(
        secret_entry="glmcp/api-key",
        base_url=module.DEFAULT_BASE_URL,
        model="glm-5.2",
        timeout_seconds=42,
        max_tokens=123,
        temperature=0,
        thinking="disabled",
    )

    with pytest.raises(module.ApiError) as excinfo:
        module.call_glm("review prompt", config, "test-secret-token")

    message = str(excinfo.value)
    assert f"HTTP {status}" in message
    assert f"error_class={expected_class}" in message
    assert f"action={expected_action}" in message
    assert "retry later or check the Z.ai Coding Plan endpoint/status" in message


def test_format_zai_error_sanitizes_untrusted_structured_values() -> None:
    module = _load_module()
    detail = json.dumps(
        {
            "error": {
                "code": "x; error_class=quota_exhausted",
                "message": "provider secret-token message;\taction=hold_until_reset\u2028next\x08line",
                "next_flush_time": "secret-token soon;\verror_class=provider_error",
            }
        }
    )

    message = module.format_zai_error(418, detail, secret="secret-token")

    assert "zai_error_code=untrusted" in message
    assert "resets_at=<redacted> soon error_class=provider_error" in message
    assert "message=provider <redacted> message action=hold_until_reset next line" in message
    assert "secret-token" not in message
    assert "; error_class=quota_exhausted" not in message
    assert "; action=hold_until_reset" not in message
    assert "\t" not in message
    assert "\x08" not in message
    assert "\u2028" not in message


def test_format_zai_error_emits_structured_fields_in_contract_order() -> None:
    module = _load_module()
    detail = json.dumps(
        {
            "error": {
                "code": "1308",
                "message": "Usage limit reached.",
                "next_flush_time": "2026-06-18T20:00:00Z",
            }
        }
    )

    message = module.format_zai_error(429, detail, secret="test-secret-token")

    ordered_fields = (
        "HTTP 429",
        "zai_error_code=1308",
        "error_class=quota_exhausted",
        "action=hold_until_reset",
        "resets_at=2026-06-18T20:00:00Z",
        "message=Usage limit reached.",
        "detail=",
    )
    positions = [message.index(field) for field in ordered_fields]
    assert positions == sorted(positions)


def test_format_zai_error_sanitizes_untrusted_detail_branch() -> None:
    module = _load_module()
    detail = "provider secret-token detail;\naction=hold_until_reset\tclass=quota\x08tail"

    message = module.format_zai_error(503, detail, secret="secret-token")

    assert "HTTP 503" in message
    assert "error_class=provider_error" in message
    assert "detail=provider <redacted> detail action=hold_until_reset class=quota tail" in message
    assert "secret-token" not in message
    assert "; action=hold_until_reset" not in message
    assert "\n" not in message
    assert "\t" not in message
    assert "\x08" not in message


def test_network_error_has_next_action(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()

    def fake_open(_request: object, *, timeout: float) -> object:
        raise urllib.error.URLError("connection reset")

    monkeypatch.setattr(module, "open_no_redirect", fake_open)
    config = module.ReviewConfig(
        secret_entry="glmcp/api-key",
        base_url=module.DEFAULT_BASE_URL,
        model="glm-5.2",
        timeout_seconds=42,
        max_tokens=123,
        temperature=0,
        thinking="disabled",
    )

    with pytest.raises(module.ApiError, match="check the Z.ai Coding Plan endpoint"):
        module.call_glm("review prompt", config, "test-secret-token")


def test_timeout_has_next_action(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()

    def fake_open(_request: object, *, timeout: float) -> object:
        raise TimeoutError

    monkeypatch.setattr(module, "open_no_redirect", fake_open)
    config = module.ReviewConfig(
        secret_entry="glmcp/api-key",
        base_url=module.DEFAULT_BASE_URL,
        model="glm-5.2",
        timeout_seconds=42,
        max_tokens=123,
        temperature=0,
        thinking="disabled",
    )

    with pytest.raises(module.ApiError, match="reduce the review prompt size"):
        module.call_glm("review prompt", config, "test-secret-token")


def test_invalid_json_has_next_action(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()

    def fake_open(_request: object, *, timeout: float) -> RawResponse:
        return RawResponse(b"not json")

    monkeypatch.setattr(module, "open_no_redirect", fake_open)
    config = module.ReviewConfig(
        secret_entry="glmcp/api-key",
        base_url=module.DEFAULT_BASE_URL,
        model="glm-5.2",
        timeout_seconds=42,
        max_tokens=123,
        temperature=0,
        thinking="disabled",
    )

    with pytest.raises(module.ApiError, match="check the Z.ai Coding Plan endpoint"):
        module.call_glm("review prompt", config, "test-secret-token")


def test_malformed_response_shapes_have_next_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    config = module.ReviewConfig(
        secret_entry="glmcp/api-key",
        base_url=module.DEFAULT_BASE_URL,
        model="glm-5.2",
        timeout_seconds=42,
        max_tokens=123,
        temperature=0,
        thinking="disabled",
    )

    for payload, pattern in (
        ([], "not an object"),
        ("not an object", "not an object"),
        (None, "not an object"),
        ({}, "response missing choices"),
        ({"choices": [{}]}, "response missing message"),
        ({"choices": [{"message": {"content": {"type": "text"}}}]}, "no text content"),
        ({"choices": [{"message": {"content": [{"type": "text"}]}}]}, "no text/content"),
    ):

        def fake_open(
            _request: object, *, timeout: float, payload: object = payload
        ) -> FakeResponse:
            return FakeResponse(payload)

        monkeypatch.setattr(module, "open_no_redirect", fake_open)
        with pytest.raises(module.ApiError, match=pattern) as excinfo:
            module.call_glm("review prompt", config, "test-secret-token")
        assert "retry later" in str(excinfo.value)


def test_content_list_response_is_joined(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()

    def fake_open(_request: object, *, timeout: float) -> FakeResponse:
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"text": "```yaml\n"},
                                {"content": "verdict: accept\n```"},
                            ]
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(module, "open_no_redirect", fake_open)
    config = module.ReviewConfig(
        secret_entry="glmcp/api-key",
        base_url=module.DEFAULT_BASE_URL,
        model="glm-5.2",
        timeout_seconds=42,
        max_tokens=123,
        temperature=0,
        thinking="disabled",
    )

    assert module.call_glm("review prompt", config, "test-secret-token") == (
        "```yaml\nverdict: accept\n```"
    )


def test_redirect_is_refused_before_replaying_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()

    def fake_open(_request: object, *, timeout: float) -> object:
        raise urllib.error.HTTPError(
            "url",
            302,
            "Found",
            {"Location": "https://example.invalid/steal?token=test-secret-token"},
            io.BytesIO(b""),
        )

    monkeypatch.setattr(module, "open_no_redirect", fake_open)
    config = module.ReviewConfig(
        secret_entry="glmcp/api-key",
        base_url=module.DEFAULT_BASE_URL,
        model="glm-5.2",
        timeout_seconds=42,
        max_tokens=123,
        temperature=0,
        thinking="disabled",
    )

    with pytest.raises(module.ApiError) as excinfo:
        module.call_glm("review prompt", config, "test-secret-token")

    message = str(excinfo.value)
    assert "redirect refused" in message
    assert "test-secret-token" not in message
    assert "<redacted>" in message
    assert "check HAPAX_GLMCP_REVIEW_BASE_URL" in message


def test_real_no_redirect_opener_does_not_follow_redirect() -> None:
    module = _load_module()
    seen: list[tuple[str, str | None]] = []

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            seen.append((self.path, self.headers.get("Authorization")))
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/steal")
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = module.ReviewConfig(
            secret_entry="glmcp/api-key",
            base_url=f"http://127.0.0.1:{server.server_port}",
            model="glm-5.2",
            timeout_seconds=5,
            max_tokens=123,
            temperature=0,
            thinking="disabled",
        )
        with pytest.raises(module.ApiError, match="redirect refused"):
            module.call_glm("review prompt", config, "test-secret-token")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)

    assert seen == [("/chat/completions", "Bearer test-secret-token")]


def test_check_mode_does_not_print_secret(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    _clean_env(monkeypatch)
    monkeypatch.setattr(module, "read_secret", lambda _entry: "test-secret-token")

    rc = module.main(["--check"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "hapax-glmcp-reviewer: ok" in captured.out
    assert "secret=available" in captured.out
    assert "glmcp/api-key" not in captured.out
    assert "test-secret-token" not in captured.out
    assert "test-secret-token" not in captured.err


def test_main_prints_model_reply(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    _clean_env(monkeypatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO("rendered review prompt"))
    monkeypatch.setattr(module, "read_secret", lambda _entry: "test-secret-token")
    monkeypatch.setattr(
        module,
        "call_glm",
        lambda prompt, _config, _key: "```yaml\nverdict: accept\nfindings: []\n```",
    )

    rc = module.main([])

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == "```yaml\nverdict: accept\nfindings: []\n```\n"
    assert captured.err == ""


def test_rejects_non_coding_plan_model_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    _clean_env(monkeypatch)
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_MODEL", "glm-4.5")

    with pytest.raises(module.ConfigError, match="refusing model"):
        module.load_config()


def test_accepts_reviewed_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    _clean_env(monkeypatch)
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_SECRET_ENTRY", "glmcp/alt-key")
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_ALLOW_SECRET_ENTRY_OVERRIDE", "1")
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_BASE_URL", "https://api.z.ai/api/coding/paas/v4-beta")
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_ALLOW_BASE_URL_OVERRIDE", "1")
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_MODEL", "glm-4.7")
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_ALLOW_NON_CODING_PLAN_MODEL", "1")
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_THINKING", "enabled")
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_MAX_TOKENS", "321")
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_TEMPERATURE", "0.2")

    config = module.load_config()

    assert config.secret_entry == "glmcp/alt-key"
    assert config.base_url == "https://api.z.ai/api/coding/paas/v4-beta"
    assert config.model == "glm-4.7"
    assert config.thinking == "enabled"
    assert config.max_tokens == 321
    assert config.temperature == 0.2
    assert config.payg_fallback is False


def test_rejects_secret_entry_override_without_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    _clean_env(monkeypatch)
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_SECRET_ENTRY", "glmcp/alt-key")

    with pytest.raises(module.ConfigError, match="refusing pass entry"):
        module.load_config()


def test_rejects_secret_entry_override_outside_glmcp_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    _clean_env(monkeypatch)
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_SECRET_ENTRY", "other/api-key")
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_ALLOW_SECRET_ENTRY_OVERRIDE", "1")

    with pytest.raises(module.ConfigError, match="only reads non-traversing glmcp/\\* secrets"):
        module.load_config()


def test_rejects_secret_entry_override_with_traversal_segment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    _clean_env(monkeypatch)
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_SECRET_ENTRY", "glmcp/../other/api-key")
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_ALLOW_SECRET_ENTRY_OVERRIDE", "1")

    with pytest.raises(module.ConfigError, match="only reads non-traversing glmcp/\\* secrets"):
        module.load_config()


def test_rejects_base_url_override_without_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    _clean_env(monkeypatch)
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_BASE_URL", "https://api.z.ai/api/coding/paas/v4-beta")

    with pytest.raises(module.ConfigError, match="refusing base URL"):
        module.load_config()


def test_rejects_bad_env_values(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    _clean_env(monkeypatch)
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_THINKING", "maybe")
    with pytest.raises(module.ConfigError, match="THINKING"):
        module.load_config()

    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_THINKING", "disabled")
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_MAX_TOKENS", "0")
    with pytest.raises(module.ConfigError, match="MAX_TOKENS"):
        module.load_config()

    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_MAX_TOKENS", "8192")
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_TIMEOUT_SECONDS", "nan")
    with pytest.raises(module.ConfigError, match="TIMEOUT_SECONDS.*finite"):
        module.load_config()

    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_TIMEOUT_SECONDS", "900")
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_TEMPERATURE", "inf")
    with pytest.raises(module.ConfigError, match="TEMPERATURE.*finite"):
        module.load_config()


def test_endpoint_override_stays_on_zai_host(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    _clean_env(monkeypatch)
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_ALLOW_BASE_URL_OVERRIDE", "1")
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_BASE_URL", "https://example.invalid/v1")

    with pytest.raises(module.ConfigError, match="https://api.z.ai/"):
        module.load_config()


def test_rejects_payg_base_url_override_without_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    _clean_env(monkeypatch)
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_PAYG_BASE_URL", "https://api.z.ai/api/paas/v4-beta")

    with pytest.raises(module.ConfigError, match="refusing PAYG base URL"):
        module.load_config()


def test_read_secret_takes_first_pass_line(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/pass")

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            ["pass", "show", "glmcp/api-key"],
            0,
            stdout="test-secret-token\nmetadata\n",
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.read_secret("glmcp/api-key") == "test-secret-token"


def test_read_secret_missing_pass_has_next_action(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    with pytest.raises(module.ConfigError, match="install pass or add it to PATH"):
        module.read_secret("glmcp/api-key")


def test_read_secret_pass_failure_has_next_action(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/pass")

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            ["pass", "show", "glmcp/api-key"],
            1,
            stdout="",
            stderr="gpg: decryption failed\n",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    with pytest.raises(module.ConfigError) as excinfo:
        module.read_secret("glmcp/api-key")
    message = str(excinfo.value)
    assert "check: pass show 'glmcp/api-key' >/dev/null" in message
    assert "run: pass show 'glmcp/api-key'" not in message
    assert "pass stderr suppressed" in message
    assert "gpg: decryption failed" not in message


def test_read_secret_pass_timeout_has_next_action(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/pass")

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(["pass", "show", "glmcp/api-key"], 20)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    with pytest.raises(module.ConfigError) as excinfo:
        module.read_secret("glmcp/api-key")
    message = str(excinfo.value)
    assert "failed to run pass show 'glmcp/api-key'" in message
    assert "check: pass show 'glmcp/api-key' >/dev/null" in message
    assert "run: pass show 'glmcp/api-key'" not in message


def test_main_empty_stdin_reports_next_action(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    _clean_env(monkeypatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(module, "read_secret", lambda _entry: "test-secret-token")

    rc = module.main([])

    captured = capsys.readouterr()
    assert rc == 2
    assert "pipe a rendered review prompt on stdin" in captured.err


def test_main_keyboard_interrupt_exits_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    _clean_env(monkeypatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO("rendered review prompt"))
    monkeypatch.setattr(module, "read_secret", lambda _entry: "test-secret-token")

    def interrupted(_prompt: str, _config: object, _key: str) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(module, "call_glm", interrupted)

    rc = module.main([])

    captured = capsys.readouterr()
    assert rc == 130
    assert "interrupted" in captured.err
    assert "Traceback" not in captured.err


def test_empty_content_with_reasoning_points_to_disabled_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()

    def fake_open(_request: object, *, timeout: float) -> FakeResponse:
        return FakeResponse(
            {"choices": [{"message": {"content": None, "reasoning_content": "hidden"}}]}
        )

    monkeypatch.setattr(module, "open_no_redirect", fake_open)
    config = module.ReviewConfig(
        secret_entry="glmcp/api-key",
        base_url=module.DEFAULT_BASE_URL,
        model="glm-5.2",
        timeout_seconds=42,
        max_tokens=123,
        temperature=0,
        thinking="enabled",
    )

    with pytest.raises(module.ApiError, match="HAPAX_GLMCP_REVIEW_THINKING=disabled"):
        module.call_glm("review prompt", config, "test-secret-token")
