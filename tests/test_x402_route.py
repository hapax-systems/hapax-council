"""Tests for logos/api/routes/x402.py — Path A refusal-as-data handler."""

from __future__ import annotations

import ast
import inspect

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.payment_processors.x402.models import (
    PaymentRequired,
    decode_payment_required,
)
from logos.api.routes import x402 as x402_module
from logos.api.routes.x402 import (
    PAYMENT_REQUIRED_HEADER,
    payment_required_response,
    router,
)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


# ── Demo route (integration: first-touch 402) ────────────────────────


class TestDemoRoute:
    def test_returns_402(self):
        client = TestClient(_make_app())
        resp = client.get("/api/x402/demo")
        assert resp.status_code == 402

    def test_response_carries_payment_required_header(self):
        client = TestClient(_make_app())
        resp = client.get("/api/x402/demo")
        assert PAYMENT_REQUIRED_HEADER in resp.headers

    def test_header_decodes_to_valid_payment_required(self):
        client = TestClient(_make_app())
        resp = client.get("/api/x402/demo")
        encoded = resp.headers[PAYMENT_REQUIRED_HEADER]
        decoded = decode_payment_required(encoded)
        assert isinstance(decoded, PaymentRequired)
        assert decoded.x402Version == 2

    def test_path_a_accepts_is_empty(self):
        """Acceptance criterion of Path A: refusal-as-data via empty accepts."""
        client = TestClient(_make_app())
        resp = client.get("/api/x402/demo")
        decoded = decode_payment_required(resp.headers[PAYMENT_REQUIRED_HEADER])
        assert decoded.accepts == [], "Path A always refuses with accepts=[]"

    def test_resource_ref_is_self_reference(self):
        client = TestClient(_make_app())
        resp = client.get("/api/x402/demo")
        decoded = decode_payment_required(resp.headers[PAYMENT_REQUIRED_HEADER])
        assert decoded.resource.url == "/api/x402/demo"
        assert "demo" in decoded.resource.description.lower()
        assert decoded.resource.mimeType == "application/json"

    def test_body_is_empty_under_path_a(self):
        """Path A puts the requirement in the header, not the body."""
        client = TestClient(_make_app())
        resp = client.get("/api/x402/demo")
        assert resp.content == b""


# ── payment_required_response helper ─────────────────────────────────


class TestPaymentRequiredResponseHelper:
    def test_emits_402(self):
        resp = payment_required_response("/api/some-route")
        assert resp.status_code == 402

    def test_header_present(self):
        resp = payment_required_response("/api/some-route")
        assert PAYMENT_REQUIRED_HEADER in resp.headers

    def test_path_a_default_empty_accepts(self):
        """Default behaviour is Path A — accepts must be empty."""
        resp = payment_required_response("/api/some-route")
        decoded = decode_payment_required(resp.headers[PAYMENT_REQUIRED_HEADER])
        assert decoded.accepts == []

    def test_resource_ref_propagates(self):
        resp = payment_required_response(
            "/api/specific-resource",
            description="Test resource",
            mime_type="text/plain",
        )
        decoded = decode_payment_required(resp.headers[PAYMENT_REQUIRED_HEADER])
        assert decoded.resource.url == "/api/specific-resource"
        assert decoded.resource.description == "Test resource"
        assert decoded.resource.mimeType == "text/plain"

    def test_default_description_is_empty_string(self):
        resp = payment_required_response("/api/x")
        decoded = decode_payment_required(resp.headers[PAYMENT_REQUIRED_HEADER])
        assert decoded.resource.description == ""

    def test_default_mime_type_is_octet_stream(self):
        resp = payment_required_response("/api/x")
        decoded = decode_payment_required(resp.headers[PAYMENT_REQUIRED_HEADER])
        assert decoded.resource.mimeType == "application/octet-stream"

    def test_custom_error_message(self):
        resp = payment_required_response(
            "/api/x",
            error="custom error message",
        )
        decoded = decode_payment_required(resp.headers[PAYMENT_REQUIRED_HEADER])
        assert decoded.error == "custom error message"

    def test_default_error_message(self):
        resp = payment_required_response("/api/x")
        decoded = decode_payment_required(resp.headers[PAYMENT_REQUIRED_HEADER])
        assert decoded.error == "payment required"


# ── Read-only contract pin (mirrors test_read_only_contract.py) ──────


class TestReadOnlyContract:
    """Enforce the receive-only invariant on the route module.

    `tests/payment_processors/test_read_only_contract.py` scans the
    `agents/payment_processors/` source tree for forbidden outbound
    verbs and fails any def/class that names one. The route module
    lives in `logos/api/routes/`, outside that scanner's scope, so
    this pin extends the same invariant to the handler side.

    Path A is structurally incapable of initiating outbound payment
    (no facilitator wired, no signing keys present), but the type
    system can't prove that. This test makes the invariant lexical:
    no def/class in the route module may be named after a forbidden
    outbound verb.
    """

    FORBIDDEN_VERBS: tuple[str, ...] = (
        "send",
        "initiate",
        "payout",
        "transfer",
        "withdraw",
        "pay",
        "remit",
    )

    def test_no_forbidden_verb_definitions(self):
        src = inspect.getsource(x402_module)
        tree = ast.parse(src)

        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                lower = node.name.lower()
                for verb in self.FORBIDDEN_VERBS:
                    if lower == verb or lower.startswith(f"{verb}_"):
                        offenders.append(node.name)
                        break

        assert not offenders, (
            f"x402 route module has forbidden outbound verbs in defs: {offenders}; "
            "Path A is refusal-as-data — handler must never define names "
            "implying outbound value flow. Mirror of "
            "tests/payment_processors/test_read_only_contract.py."
        )

    def test_no_facilitator_call_imports(self):
        """Path A forbids facilitator /verify or /settle calls.

        Sanity-check that the route module does not import an http
        client (httpx, requests, aiohttp) — under Path A there is no
        outbound HTTP. If a future change adds one, this test should
        fail and force an explicit decision (extend the import
        allowlist for Path B reversal, or refactor the call away).
        """
        src = inspect.getsource(x402_module)
        tree = ast.parse(src)

        forbidden_imports = {"httpx", "requests", "aiohttp", "urllib3"}
        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root in forbidden_imports:
                        offenders.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".", 1)[0]
                if root in forbidden_imports:
                    offenders.append(node.module or "")

        assert not offenders, (
            f"x402 route module imports outbound HTTP client(s): {offenders}; "
            "Path A is refusal-as-data — no facilitator call path may exist. "
            "If this fires after a Path B reversal, update the test exemption "
            "list to match the choice recorded in "
            "docs/governance/x402-facilitator-choice.md."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
