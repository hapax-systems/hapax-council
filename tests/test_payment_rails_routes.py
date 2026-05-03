"""Integration tests for the payment-rails FastAPI routes.

cc-task: github-sponsors-end-to-end-wiring.

Validates the full pipeline end-to-end:
  signed POST → receiver validates → normalized event → publisher
  dispatches → manifest file written → optional refusal log row
  on cancellation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agents.publication_bus.github_sponsors_publisher import (
    CANCELLATION_REFUSAL_AXIOM,
    CANCELLATION_REFUSAL_SURFACE,
)
from logos.api.app import app
from shared.github_sponsors_receive_only_rail import (
    GITHUB_SPONSORS_WEBHOOK_SECRET_ENV,
)

_VALID_SECRET = "github-sponsors-webhook-secret-aBcDeFgHiJkLmN"


def _sign(payload_bytes: bytes, secret: str = _VALID_SECRET) -> str:
    """GitHub-format signature header value: ``sha256=<hexdigest>``."""
    digest = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _sponsorship_payload(
    *,
    action: str = "created",
    sponsor_login: str = "alice-the-sponsor",
    monthly_dollars: int = 25,
    created_at: str = "2026-05-03T00:00:00Z",
) -> dict:
    """Realistic GitHub Sponsors webhook envelope.

    Captures the actual GitHub webhook shape for sponsorship events;
    the receiver pulls the four normalized fields plus computes a SHA
    of the raw bytes.
    """
    return {
        "action": action,
        "sponsorship": {
            "node_id": "MDxxxxxxNDU=",
            "created_at": created_at,
            "sponsor": {
                "login": sponsor_login,
                "id": 99999999,
                "type": "User",
            },
            "tier": {
                "node_id": "MDxxxxxxx",
                "name": "Generous Patron",
                "monthly_price_in_cents": monthly_dollars * 100,
                "monthly_price_in_dollars": monthly_dollars,
            },
        },
        "sender": {"login": sponsor_login, "id": 99999999},
    }


@pytest.fixture
def output_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override HAPAX_HOME so the publisher writes under the test tmp dir."""
    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    return tmp_path / "hapax-state" / "publications" / "github-sponsors"


@pytest.fixture
def secret_env(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set the rail's webhook secret env var so HMAC verification succeeds."""
    monkeypatch.setenv(GITHUB_SPONSORS_WEBHOOK_SECRET_ENV, _VALID_SECRET)
    return _VALID_SECRET


@pytest.fixture
def refusal_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override the refusal-brief log path so cancellation rows go to the test dir.

    The writer's DEFAULT_LOG_PATH is resolved at module-import time, which
    pre-dates the test fixture run.  Patch the module attribute directly
    so the publisher's lazy import (which calls ``append`` without an
    explicit log_path) picks up the test path.
    """
    log_path = tmp_path / "refusals" / "log.jsonl"
    monkeypatch.setenv("HAPAX_REFUSALS_LOG_PATH", str(log_path))
    import agents.refusal_brief.writer as writer_mod

    monkeypatch.setattr(writer_mod, "DEFAULT_LOG_PATH", log_path)
    return log_path.parent


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signed_created_event_returns_200_and_writes_manifest(
    output_dir: Path, secret_env: str
) -> None:
    payload = _sponsorship_payload(action="created", sponsor_login="alice")
    raw = json.dumps(payload).encode("utf-8")
    sig = _sign(raw)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/github-sponsors",
            content=raw,
            headers={
                "X-Hub-Signature-256": sig,
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "received"
    assert body["event_kind"] == "created"
    assert "raw_payload_sha256" in body

    files = list(output_dir.glob("event-created-*.md"))
    assert len(files) == 1, f"expected 1 manifest file, got {files}"
    contents = files[0].read_text()
    assert "GitHub Sponsors event — created" in contents
    assert "alice" in contents
    assert "2500" in contents  # amount_usd_cents (was "25.00" pre-cents-normalization)


@pytest.mark.asyncio
async def test_signed_tier_changed_event_writes_manifest(output_dir: Path, secret_env: str) -> None:
    payload = _sponsorship_payload(action="tier_changed", sponsor_login="bob")
    raw = json.dumps(payload).encode("utf-8")
    sig = _sign(raw)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/github-sponsors",
            content=raw,
            headers={"X-Hub-Signature-256": sig},
        )

    assert response.status_code == 200, response.text
    assert response.json()["event_kind"] == "tier_changed"
    assert list(output_dir.glob("event-tier_changed-*.md"))


@pytest.mark.asyncio
async def test_signed_pending_cancellation_event_writes_manifest(
    output_dir: Path, secret_env: str
) -> None:
    payload = _sponsorship_payload(action="pending_cancellation")
    raw = json.dumps(payload).encode("utf-8")
    sig = _sign(raw)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/github-sponsors",
            content=raw,
            headers={"X-Hub-Signature-256": sig},
        )

    assert response.status_code == 200, response.text
    assert response.json()["event_kind"] == "pending_cancellation"


# ---------------------------------------------------------------------------
# Cancellation auto-link to refusal log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelled_event_appends_to_refusal_log(
    output_dir: Path,
    secret_env: str,
    refusal_log_dir: Path,
) -> None:
    """End-to-end auto-link: cancelled event → publisher → refusal log row."""
    payload = _sponsorship_payload(action="cancelled", sponsor_login="charlie")
    raw = json.dumps(payload).encode("utf-8")
    sig = _sign(raw)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/github-sponsors",
            content=raw,
            headers={"X-Hub-Signature-256": sig},
        )

    assert response.status_code == 200, response.text
    assert response.json()["event_kind"] == "cancelled"

    # Manifest file written
    assert list(output_dir.glob("event-cancelled-*.md"))

    # Refusal log row appended with the expected axiom + surface
    log_file = refusal_log_dir / "log.jsonl"
    assert log_file.exists(), "refusal log was not written"
    rows = [json.loads(line) for line in log_file.read_text().splitlines() if line]
    cancellation_rows = [r for r in rows if r.get("surface") == CANCELLATION_REFUSAL_SURFACE]
    assert cancellation_rows, f"no cancellation refusal row found in {rows}"
    assert cancellation_rows[0]["axiom"] == CANCELLATION_REFUSAL_AXIOM
    assert "github-sponsors" in cancellation_rows[0]["reason"]


@pytest.mark.asyncio
async def test_non_cancellation_does_not_append_to_refusal_log(
    output_dir: Path,
    secret_env: str,
    refusal_log_dir: Path,
) -> None:
    """Created/tier_changed/pending_cancellation events do NOT auto-link."""
    payload = _sponsorship_payload(action="created")
    raw = json.dumps(payload).encode("utf-8")
    sig = _sign(raw)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/github-sponsors",
            content=raw,
            headers={"X-Hub-Signature-256": sig},
        )

    assert response.status_code == 200
    log_file = refusal_log_dir / "log.jsonl"
    if log_file.exists():
        rows = [json.loads(line) for line in log_file.read_text().splitlines() if line]
        cancellations = [r for r in rows if r.get("surface") == CANCELLATION_REFUSAL_SURFACE]
        assert not cancellations, "no cancellation should be logged for created event"


# ---------------------------------------------------------------------------
# Signature failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bad_signature_returns_400(output_dir: Path, secret_env: str) -> None:
    payload = _sponsorship_payload()
    raw = json.dumps(payload).encode("utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/github-sponsors",
            content=raw,
            headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
        )

    assert response.status_code == 400
    assert "signature" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_signature_provided_with_unset_secret_returns_400(
    output_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per receive-only invariant: signature with no secret fails closed."""
    monkeypatch.delenv(GITHUB_SPONSORS_WEBHOOK_SECRET_ENV, raising=False)
    payload = _sponsorship_payload()
    raw = json.dumps(payload).encode("utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/github-sponsors",
            content=raw,
            headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
        )

    assert response.status_code == 400
    assert "is not set" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Malformed payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_json_returns_400(secret_env: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/github-sponsors",
            content=b"not-valid-json{{{",
            headers={"X-Hub-Signature-256": "sha256=00"},
        )

    assert response.status_code == 400
    assert "malformed JSON" in response.json()["detail"]


@pytest.mark.asyncio
async def test_non_object_payload_returns_400(secret_env: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/github-sponsors",
            content=b'["array", "not-object"]',
            headers={"X-Hub-Signature-256": "sha256=00"},
        )

    assert response.status_code == 400
    assert "JSON object" in response.json()["detail"]


@pytest.mark.asyncio
async def test_unaccepted_action_returns_400(output_dir: Path, secret_env: str) -> None:
    payload = _sponsorship_payload(action="edited")  # GitHub emits but we reject
    raw = json.dumps(payload).encode("utf-8")
    sig = _sign(raw)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/github-sponsors",
            content=raw,
            headers={"X-Hub-Signature-256": sig},
        )

    assert response.status_code == 400
    assert "unaccepted" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_missing_sponsorship_returns_400(output_dir: Path, secret_env: str) -> None:
    payload = {"action": "created"}  # missing sponsorship envelope
    raw = json.dumps(payload).encode("utf-8")
    sig = _sign(raw)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/github-sponsors",
            content=raw,
            headers={"X-Hub-Signature-256": sig},
        )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Heartbeat / no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_body_returns_ping_ok() -> None:
    """Empty body + no signature is a heartbeat; sibling rails' pre-flight."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/github-sponsors",
            content=b"",
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ping_ok"


# ---------------------------------------------------------------------------
# Static checks
# ---------------------------------------------------------------------------


def test_route_module_carries_no_outbound_calls() -> None:
    import inspect

    import logos.api.routes.payment_rails as mod

    src = inspect.getsource(mod)
    forbidden = ("requests.", "httpx.AsyncClient", "urllib.request", "aiohttp")
    for token in forbidden:
        assert token not in src, f"unexpected I/O reference: {token!r}"


def test_publisher_module_carries_no_send_path() -> None:
    import inspect

    import agents.publication_bus.github_sponsors_publisher as mod

    src = inspect.getsource(mod).lower()
    forbidden_verbs = (
        "def send",
        "def initiate",
        "def payout",
        "def transfer",
        "def origination",
    )
    for token in forbidden_verbs:
        assert token not in src, f"unexpected send-path: {token!r}"


# ===========================================================================
# Liberapay rail integration tests (cc-task liberapay-end-to-end-wiring)
# ===========================================================================

from agents.publication_bus.liberapay_publisher import (
    CANCELLATION_REFUSAL_AXIOM as LIBERAPAY_REFUSAL_AXIOM,
)
from agents.publication_bus.liberapay_publisher import (
    CANCELLATION_REFUSAL_SURFACE as LIBERAPAY_REFUSAL_SURFACE,
)
from shared.liberapay_receive_only_rail import (
    LIBERAPAY_WEBHOOK_SECRET_ENV,
)


def _liberapay_payload(
    *,
    event: str = "payin_succeeded",
    donor: str = "alice-donor",
    amount: str = "5.00",
    occurred_at: str = "2026-05-03T00:00:00Z",
) -> dict:
    """Realistic Liberapay donation envelope as produced by an upstream bridge."""
    return {
        "event": event,
        "donor": {
            "username": donor,
            "id": 99999999,
        },
        "amount": {
            "amount": amount,
            "currency": "EUR",
        },
        "occurred_at": occurred_at,
        "source_ip": "127.0.0.1",
        "tip_message": "thanks for the work",  # PII-ish; rail must NOT extract
    }


@pytest.fixture
def liberapay_output_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    return tmp_path / "hapax-state" / "publications" / "liberapay"


@pytest.fixture
def liberapay_secret_env(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(LIBERAPAY_WEBHOOK_SECRET_ENV, "liberapay-secret-XYZ")
    return "liberapay-secret-XYZ"


@pytest.fixture
def liberapay_idempotency_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Reset the route's Liberapay idempotency singleton + point at tmp db."""
    import logos.api.routes.payment_rails as routes_mod

    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    routes_mod._liberapay_idempotency_store = None
    yield tmp_path / "liberapay" / "idempotency.db"
    routes_mod._liberapay_idempotency_store = None


@pytest.mark.asyncio
async def test_liberapay_signed_payin_succeeded_writes_manifest(
    liberapay_output_dir: Path,
    liberapay_secret_env: str,
    liberapay_idempotency_isolated: Path,
) -> None:
    payload = _liberapay_payload(event="payin_succeeded")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(liberapay_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/liberapay",
            content=raw,
            headers={
                "X-Liberapay-Signature": sig,
                "X-Liberapay-Delivery-Id": "lp-delivery-payin-test",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "received"
    assert body["event_kind"] == "payin_succeeded"
    files = list(liberapay_output_dir.glob("event-payin_succeeded-*.md"))
    assert len(files) == 1, f"expected 1 manifest, got {files}"
    contents = files[0].read_text()
    assert "alice-donor" in contents
    assert "Liberapay donation event" in contents


@pytest.mark.asyncio
async def test_liberapay_dotted_form_alias_accepted(
    liberapay_output_dir: Path,
    liberapay_secret_env: str,
    liberapay_idempotency_isolated: Path,
) -> None:
    """Bridges may forward Liberapay's dotted form (`payin.succeeded`)."""
    payload = _liberapay_payload(event="payin.succeeded")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(liberapay_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/liberapay",
            content=raw,
            headers={
                "X-Liberapay-Signature": sig,
                "X-Liberapay-Delivery-Id": "lp-delivery-dotted-test",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["event_kind"] == "payin_succeeded"


@pytest.mark.asyncio
async def test_liberapay_tip_cancelled_appends_to_refusal_log(
    liberapay_output_dir: Path,
    liberapay_secret_env: str,
    refusal_log_dir: Path,
    liberapay_idempotency_isolated: Path,
) -> None:
    payload = _liberapay_payload(event="tip_cancelled", donor="bob-donor")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(liberapay_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/liberapay",
            content=raw,
            headers={
                "X-Liberapay-Signature": sig,
                "X-Liberapay-Delivery-Id": "lp-delivery-cancel-test",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["event_kind"] == "tip_cancelled"

    log_file = refusal_log_dir / "log.jsonl"
    assert log_file.exists(), "refusal log was not written"
    rows = [json.loads(line) for line in log_file.read_text().splitlines() if line]
    cancellation_rows = [r for r in rows if r.get("surface") == LIBERAPAY_REFUSAL_SURFACE]
    assert cancellation_rows
    assert cancellation_rows[0]["axiom"] == LIBERAPAY_REFUSAL_AXIOM


@pytest.mark.asyncio
async def test_liberapay_bad_signature_returns_400(
    liberapay_output_dir: Path, liberapay_secret_env: str
) -> None:
    payload = _liberapay_payload()
    raw = json.dumps(payload).encode("utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/liberapay",
            content=raw,
            headers={"X-Liberapay-Signature": "0" * 64},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_liberapay_non_eur_currency_returns_400(
    liberapay_output_dir: Path, liberapay_secret_env: str
) -> None:
    """Liberapay rail rejects non-EUR; bridge must convert upstream."""
    payload = _liberapay_payload()
    payload["amount"]["currency"] = "USD"
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(liberapay_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/liberapay",
            content=raw,
            headers={"X-Liberapay-Signature": sig},
        )

    assert response.status_code == 400
    assert "non-EUR" in response.json()["detail"]


@pytest.mark.asyncio
async def test_liberapay_missing_donor_returns_400(
    liberapay_output_dir: Path, liberapay_secret_env: str
) -> None:
    payload = _liberapay_payload()
    del payload["donor"]
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(liberapay_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/liberapay",
            content=raw,
            headers={"X-Liberapay-Signature": sig},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_liberapay_empty_body_returns_ping_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/liberapay",
            content=b"",
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ping_ok"


def test_liberapay_publisher_module_carries_no_send_path() -> None:
    import inspect

    import agents.publication_bus.liberapay_publisher as mod

    src = inspect.getsource(mod).lower()
    forbidden_verbs = (
        "def send",
        "def initiate",
        "def payout",
        "def transfer",
        "def origination",
    )
    for token in forbidden_verbs:
        assert token not in src, f"unexpected send-path: {token!r}"


# ===========================================================================
# Liberapay — idempotency hard pin (cc-task jr-liberapay-rail-idempotency-pin)
# ===========================================================================


@pytest.mark.asyncio
async def test_liberapay_route_replays_same_delivery_id_returns_duplicate(
    liberapay_output_dir: Path,
    liberapay_secret_env: str,
    liberapay_idempotency_isolated: Path,
) -> None:
    """Two POSTs with same X-Liberapay-Delivery-Id → 2nd is duplicate."""
    payload = _liberapay_payload(event="payin_succeeded")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(liberapay_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    headers = {
        "X-Liberapay-Signature": sig,
        "X-Liberapay-Delivery-Id": "lp-replay-001",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/api/payment-rails/liberapay", content=raw, headers=headers)
        second = await client.post("/api/payment-rails/liberapay", content=raw, headers=headers)

    assert first.status_code == 200 and first.json()["status"] == "received"
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["status"] == "duplicate"
    assert body["delivery_id"] == "lp-replay-001"
    files = list(liberapay_output_dir.glob("event-payin_succeeded-*.md"))
    assert len(files) == 1


@pytest.mark.asyncio
async def test_liberapay_route_distinct_delivery_ids_both_processed(
    liberapay_output_dir: Path,
    liberapay_secret_env: str,
    liberapay_idempotency_isolated: Path,
) -> None:
    payload_a = _liberapay_payload(event="payin_succeeded")
    payload_b = _liberapay_payload(event="payin_succeeded", donor="bob-donor")
    raw_a = json.dumps(payload_a).encode("utf-8")
    raw_b = json.dumps(payload_b).encode("utf-8")
    sig_a = hmac.new(liberapay_secret_env.encode("utf-8"), raw_a, hashlib.sha256).hexdigest()
    sig_b = hmac.new(liberapay_secret_env.encode("utf-8"), raw_b, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_a = await client.post(
            "/api/payment-rails/liberapay",
            content=raw_a,
            headers={
                "X-Liberapay-Signature": sig_a,
                "X-Liberapay-Delivery-Id": "lp-delivery-a",
            },
        )
        r_b = await client.post(
            "/api/payment-rails/liberapay",
            content=raw_b,
            headers={
                "X-Liberapay-Signature": sig_b,
                "X-Liberapay-Delivery-Id": "lp-delivery-b",
            },
        )

    assert r_a.json()["status"] == "received"
    assert r_b.json()["status"] == "received"
    files = list(liberapay_output_dir.glob("event-payin_succeeded-*.md"))
    assert len(files) == 2


@pytest.mark.asyncio
async def test_liberapay_route_missing_delivery_id_returns_400(
    liberapay_output_dir: Path,
    liberapay_secret_env: str,
    liberapay_idempotency_isolated: Path,
) -> None:
    """No bridge delivery-id header → 400 (bridge fails-loud)."""
    payload = _liberapay_payload(event="payin_succeeded")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(liberapay_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/liberapay",
            content=raw,
            headers={"X-Liberapay-Signature": sig},  # NO delivery_id
        )

    assert response.status_code == 400
    assert "delivery_id" in response.json()["detail"]


@pytest.mark.asyncio
async def test_liberapay_route_accepts_cloudmailin_message_id_header(
    liberapay_output_dir: Path,
    liberapay_secret_env: str,
    liberapay_idempotency_isolated: Path,
) -> None:
    """Bridge fallback: X-Cloudmailin-Message-Id is a valid delivery_id."""
    payload = _liberapay_payload(event="payin_succeeded")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(liberapay_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/liberapay",
            content=raw,
            headers={
                "X-Liberapay-Signature": sig,
                "X-Cloudmailin-Message-Id": "cm-msg-001",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "received"


# ===========================================================================
# Open Collective rail integration tests (cc-task open-collective-end-to-end-wiring)
# ===========================================================================

from shared.open_collective_receive_only_rail import (
    OPEN_COLLECTIVE_WEBHOOK_SECRET_ENV,
)


def _open_collective_payload(
    *,
    activity: str = "order_processed",
    member: str = "alice-supporter",
    amount: int = 1500,
    currency: str = "USD",
    occurred_at: str = "2026-05-03T00:00:00Z",
) -> dict:
    """Realistic Open Collective webhook envelope."""
    return {
        "type": activity,
        "createdAt": occurred_at,
        "data": {
            "fromCollective": {"slug": member, "type": "USER"},
            "collective": {"slug": "hapax", "type": "COLLECTIVE"},
            "order": {
                "id": 99999,
                "totalAmount": amount,
                "currency": currency,
                "description": "thanks for the work",  # PII; rail should NOT extract
            },
        },
    }


@pytest.fixture
def open_collective_output_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    return tmp_path / "hapax-state" / "publications" / "open-collective"


@pytest.fixture
def open_collective_secret_env(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(OPEN_COLLECTIVE_WEBHOOK_SECRET_ENV, "oc-secret-XYZ")
    return "oc-secret-XYZ"


@pytest.fixture
def open_collective_idempotency_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Reset the route's Open Collective idempotency singleton + tmp db."""
    import logos.api.routes.payment_rails as routes_mod

    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    routes_mod._open_collective_idempotency_store = None
    yield tmp_path / "open-collective" / "idempotency.db"
    routes_mod._open_collective_idempotency_store = None


@pytest.mark.asyncio
async def test_open_collective_signed_order_processed_writes_manifest(
    open_collective_output_dir: Path,
    open_collective_secret_env: str,
    open_collective_idempotency_isolated: Path,
) -> None:
    payload = _open_collective_payload(activity="order_processed")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(open_collective_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/open-collective",
            content=raw,
            headers={
                "X-Open-Collective-Signature": sig,
                "X-Open-Collective-Activity-Id": "oc-act-order-test",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "received"
    assert body["event_kind"] == "order_processed"
    files = list(open_collective_output_dir.glob("event-order_processed-*.md"))
    assert len(files) == 1, f"expected 1 manifest, got {files}"
    contents = files[0].read_text()
    assert "alice-supporter" in contents


@pytest.mark.asyncio
async def test_open_collective_dotted_form_alias_accepted(
    open_collective_output_dir: Path,
    open_collective_secret_env: str,
    open_collective_idempotency_isolated: Path,
) -> None:
    """OC bridges may forward the dotted form `order.processed`."""
    payload = _open_collective_payload(activity="order.processed")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(open_collective_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/open-collective",
            content=raw,
            headers={
                "X-Open-Collective-Signature": sig,
                "X-Open-Collective-Activity-Id": "oc-act-dotted-test",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["event_kind"] == "order_processed"


@pytest.mark.asyncio
async def test_open_collective_member_created(
    open_collective_output_dir: Path,
    open_collective_secret_env: str,
    open_collective_idempotency_isolated: Path,
) -> None:
    payload = _open_collective_payload(activity="member_created", member="bob-member")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(open_collective_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/open-collective",
            content=raw,
            headers={
                "X-Open-Collective-Signature": sig,
                "X-Open-Collective-Activity-Id": "oc-act-member-test",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["event_kind"] == "member_created"


@pytest.mark.asyncio
async def test_open_collective_eur_currency(
    open_collective_output_dir: Path,
    open_collective_secret_env: str,
    open_collective_idempotency_isolated: Path,
) -> None:
    """Open Collective is multi-currency; EUR should pass."""
    payload = _open_collective_payload(currency="EUR", amount=2000)
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(open_collective_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/open-collective",
            content=raw,
            headers={
                "X-Open-Collective-Signature": sig,
                "X-Open-Collective-Activity-Id": "oc-act-eur-test",
            },
        )

    assert response.status_code == 200, response.text
    files = list(open_collective_output_dir.glob("event-order_processed-*.md"))
    assert any("EUR" in f.read_text() for f in files)


@pytest.mark.asyncio
async def test_open_collective_bad_signature_returns_400(
    open_collective_output_dir: Path, open_collective_secret_env: str
) -> None:
    payload = _open_collective_payload()
    raw = json.dumps(payload).encode("utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/open-collective",
            content=raw,
            headers={"X-Open-Collective-Signature": "0" * 64},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_open_collective_unaccepted_activity_returns_400(
    open_collective_output_dir: Path, open_collective_secret_env: str
) -> None:
    payload = _open_collective_payload(activity="collective.created")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(open_collective_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/open-collective",
            content=raw,
            headers={"X-Open-Collective-Signature": sig},
        )

    assert response.status_code == 400
    assert "unaccepted" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_open_collective_empty_body_returns_ping_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/open-collective",
            content=b"",
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ping_ok"


def test_open_collective_publisher_module_carries_no_send_path() -> None:
    import inspect

    import agents.publication_bus.open_collective_publisher as mod

    src = inspect.getsource(mod).lower()
    forbidden_verbs = (
        "def send",
        "def initiate",
        "def payout",
        "def transfer",
        "def origination",
    )
    for token in forbidden_verbs:
        assert token not in src, f"unexpected send-path: {token!r}"


# ===========================================================================
# Open Collective — idempotency hard pin (cc-task jr-open-collective-rail-idempotency-pin)
# ===========================================================================


@pytest.mark.asyncio
async def test_open_collective_route_replays_same_activity_id_returns_duplicate(
    open_collective_output_dir: Path,
    open_collective_secret_env: str,
    open_collective_idempotency_isolated: Path,
) -> None:
    payload = _open_collective_payload(activity="order_processed")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(open_collective_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    headers = {
        "X-Open-Collective-Signature": sig,
        "X-Open-Collective-Activity-Id": "oc-replay-001",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/api/payment-rails/open-collective", content=raw, headers=headers
        )
        second = await client.post(
            "/api/payment-rails/open-collective", content=raw, headers=headers
        )

    assert first.status_code == 200 and first.json()["status"] == "received"
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["status"] == "duplicate"
    assert body["delivery_id"] == "oc-replay-001"
    files = list(open_collective_output_dir.glob("event-order_processed-*.md"))
    assert len(files) == 1


@pytest.mark.asyncio
async def test_open_collective_route_distinct_activity_ids_both_processed(
    open_collective_output_dir: Path,
    open_collective_secret_env: str,
    open_collective_idempotency_isolated: Path,
) -> None:
    payload_a = _open_collective_payload(activity="order_processed")
    payload_b = _open_collective_payload(activity="order_processed", member="bob-supporter")
    raw_a = json.dumps(payload_a).encode("utf-8")
    raw_b = json.dumps(payload_b).encode("utf-8")
    sig_a = hmac.new(open_collective_secret_env.encode("utf-8"), raw_a, hashlib.sha256).hexdigest()
    sig_b = hmac.new(open_collective_secret_env.encode("utf-8"), raw_b, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_a = await client.post(
            "/api/payment-rails/open-collective",
            content=raw_a,
            headers={
                "X-Open-Collective-Signature": sig_a,
                "X-Open-Collective-Activity-Id": "oc-act-a",
            },
        )
        r_b = await client.post(
            "/api/payment-rails/open-collective",
            content=raw_b,
            headers={
                "X-Open-Collective-Signature": sig_b,
                "X-Open-Collective-Activity-Id": "oc-act-b",
            },
        )

    assert r_a.json()["status"] == "received"
    assert r_b.json()["status"] == "received"
    files = list(open_collective_output_dir.glob("event-order_processed-*.md"))
    assert len(files) == 2


@pytest.mark.asyncio
async def test_open_collective_route_missing_activity_id_returns_400(
    open_collective_output_dir: Path,
    open_collective_secret_env: str,
    open_collective_idempotency_isolated: Path,
) -> None:
    payload = _open_collective_payload(activity="order_processed")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(open_collective_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/open-collective",
            content=raw,
            headers={"X-Open-Collective-Signature": sig},  # NO activity_id
        )

    assert response.status_code == 400
    assert "delivery_id" in response.json()["detail"]


# ===========================================================================
# Stripe Payment Link rail integration tests (cc-task
# stripe-payment-link-end-to-end-wiring)
# ===========================================================================

import time as _time

from agents.publication_bus.stripe_payment_link_publisher import (
    CANCELLATION_REFUSAL_AXIOM as STRIPE_REFUSAL_AXIOM,
)
from agents.publication_bus.stripe_payment_link_publisher import (
    CANCELLATION_REFUSAL_SURFACE as STRIPE_REFUSAL_SURFACE,
)
from shared.stripe_payment_link_receive_only_rail import (
    STRIPE_PAYMENT_LINK_WEBHOOK_SECRET_ENV,
)


def _stripe_signature(payload_bytes: bytes, secret: str, ts: int) -> str:
    """Build a Stripe `Stripe-Signature` header value: t=<ts>,v1=<hex>."""
    signed = f"{ts}.".encode() + payload_bytes
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def _stripe_payload(
    *,
    event_type: str = "payment_intent.succeeded",
    customer_id: str = "cus_NwAVkkPDUrPaTC",
    amount: int = 5000,
    currency: str = "usd",
    occurred_at_unix: int | None = None,
) -> dict:
    """Realistic Stripe webhook envelope for a payment_intent.succeeded."""
    if occurred_at_unix is None:
        occurred_at_unix = int(_time.time())
    return {
        "id": "evt_3NqVe0LAuO3KjPaT0SgXLnX5",
        "type": event_type,
        "created": occurred_at_unix,
        "api_version": "2024-04-10",
        "data": {
            "object": {
                "id": "pi_3NqVe0LAuO3KjPaT0vKP6yYS",
                "object": "payment_intent",
                "amount": amount,
                "currency": currency,
                "customer": customer_id,
                "status": "succeeded",
                "receipt_email": "leak@example.com",  # PII; rail must NOT extract
                "billing_details": {
                    "name": "Alice Q. Customer",  # PII
                    "email": "leak2@example.com",
                },
            }
        },
    }


_STRIPE_VALID_SECRET = "whsec_stripe-test-XYZ-test-secret-1234567890"


@pytest.fixture
def stripe_output_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    return tmp_path / "hapax-state" / "publications" / "stripe-payment-link"


@pytest.fixture
def stripe_secret_env(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(STRIPE_PAYMENT_LINK_WEBHOOK_SECRET_ENV, _STRIPE_VALID_SECRET)
    return _STRIPE_VALID_SECRET


@pytest.mark.asyncio
async def test_stripe_signed_payment_intent_succeeded_writes_manifest(
    stripe_output_dir: Path, stripe_secret_env: str
) -> None:
    ts = int(_time.time())
    payload = _stripe_payload(occurred_at_unix=ts)
    raw = json.dumps(payload).encode("utf-8")
    sig = _stripe_signature(raw, stripe_secret_env, ts)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/stripe-payment-link",
            content=raw,
            headers={"Stripe-Signature": sig},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "received"
    assert body["event_kind"] == "payment_intent_succeeded"
    files = list(stripe_output_dir.glob("event-payment_intent_succeeded-*.md"))
    assert len(files) == 1, f"expected 1 manifest, got {files}"
    contents = files[0].read_text()
    assert "cus_NwAVkkPDUrPaTC" in contents
    assert "USD" in contents
    # PII must not leak
    assert "leak@example.com" not in contents
    assert "leak2@example.com" not in contents
    assert "Alice Q. Customer" not in contents


@pytest.mark.asyncio
async def test_stripe_subscription_deleted_appends_to_refusal_log(
    stripe_output_dir: Path,
    stripe_secret_env: str,
    refusal_log_dir: Path,
) -> None:
    ts = int(_time.time())
    payload = {
        "id": "evt_subscription_deleted",
        "type": "customer.subscription.deleted",
        "created": ts,
        "data": {
            "object": {
                "id": "sub_1234ABCD",
                "object": "subscription",
                "customer": "cus_NwAVkkPDUrPaTC",
                "currency": "usd",
                "items": {"data": [{"price": {"unit_amount": 1500, "currency": "usd"}}]},
            }
        },
    }
    raw = json.dumps(payload).encode("utf-8")
    sig = _stripe_signature(raw, stripe_secret_env, ts)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/stripe-payment-link",
            content=raw,
            headers={"Stripe-Signature": sig},
        )

    assert response.status_code == 200, response.text
    assert response.json()["event_kind"] == "customer_subscription_deleted"

    log_file = refusal_log_dir / "log.jsonl"
    assert log_file.exists()
    rows = [json.loads(line) for line in log_file.read_text().splitlines() if line]
    cancellations = [r for r in rows if r.get("surface") == STRIPE_REFUSAL_SURFACE]
    assert cancellations
    assert cancellations[0]["axiom"] == STRIPE_REFUSAL_AXIOM


@pytest.mark.asyncio
async def test_stripe_bad_signature_returns_400(
    stripe_output_dir: Path, stripe_secret_env: str
) -> None:
    ts = int(_time.time())
    payload = _stripe_payload(occurred_at_unix=ts)
    raw = json.dumps(payload).encode("utf-8")
    bad_sig = f"t={ts},v1={'0' * 64}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/stripe-payment-link",
            content=raw,
            headers={"Stripe-Signature": bad_sig},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_stripe_replay_protection_rejects_old_timestamp(
    stripe_output_dir: Path, stripe_secret_env: str
) -> None:
    """Stripe rail enforces replay-tolerance window."""
    old_ts = int(_time.time()) - 3600  # 1 hour ago, well past tolerance
    payload = _stripe_payload(occurred_at_unix=old_ts)
    raw = json.dumps(payload).encode("utf-8")
    sig = _stripe_signature(raw, stripe_secret_env, old_ts)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/stripe-payment-link",
            content=raw,
            headers={"Stripe-Signature": sig},
        )

    assert response.status_code == 400
    assert "replay" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_stripe_unaccepted_event_type_returns_400(
    stripe_output_dir: Path, stripe_secret_env: str
) -> None:
    ts = int(_time.time())
    payload = _stripe_payload(event_type="charge.refunded", occurred_at_unix=ts)
    raw = json.dumps(payload).encode("utf-8")
    sig = _stripe_signature(raw, stripe_secret_env, ts)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/stripe-payment-link",
            content=raw,
            headers={"Stripe-Signature": sig},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_stripe_empty_body_returns_ping_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/stripe-payment-link",
            content=b"",
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ping_ok"


def test_stripe_payment_link_publisher_module_carries_no_send_path() -> None:
    import inspect

    import agents.publication_bus.stripe_payment_link_publisher as mod

    src = inspect.getsource(mod).lower()
    forbidden_verbs = (
        "def send",
        "def initiate",
        "def payout",
        "def transfer",
        "def origination",
    )
    for token in forbidden_verbs:
        assert token not in src, f"unexpected send-path: {token!r}"


# ===========================================================================
# Stripe Payment Link — replay + idempotency hard pins (route-level integration)
# (cc-task: jr-stripe-payment-link-replay-idempotency-pin)
# ===========================================================================


@pytest.fixture
def stripe_idempotency_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Reset the route's idempotency singleton + point at a tmp sqlite db.

    HAPAX_HOME is set so :func:`_default_idempotency_db_path` lands in
    a per-test scratch directory; the module-level singleton is reset
    so the next call materializes a fresh sqlite db pointing into
    ``tmp_path``.
    """
    import logos.api.routes.payment_rails as routes_mod

    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    routes_mod._stripe_payment_link_idempotency_store = None
    yield tmp_path / "stripe-payment-link" / "idempotency.db"
    routes_mod._stripe_payment_link_idempotency_store = None


@pytest.mark.asyncio
async def test_stripe_route_replays_same_event_returns_duplicate_status(
    stripe_output_dir: Path,
    stripe_secret_env: str,
    stripe_idempotency_isolated: Path,
) -> None:
    """Two POSTs of identical signed payload — second returns status=duplicate."""
    ts = int(_time.time())
    payload = _stripe_payload(occurred_at_unix=ts)
    raw = json.dumps(payload).encode("utf-8")
    sig = _stripe_signature(raw, stripe_secret_env, ts)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/api/payment-rails/stripe-payment-link",
            content=raw,
            headers={"Stripe-Signature": sig},
        )
        second = await client.post(
            "/api/payment-rails/stripe-payment-link",
            content=raw,
            headers={"Stripe-Signature": sig},
        )

    assert first.status_code == 200 and first.json()["status"] == "received"
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["status"] == "duplicate"
    assert body["event_id"] == payload["id"]

    # Only ONE manifest file written despite two identical deliveries.
    files = list(stripe_output_dir.glob("event-payment_intent_succeeded-*.md"))
    assert len(files) == 1, f"expected 1 manifest, got {files}"


@pytest.mark.asyncio
async def test_stripe_route_distinct_event_ids_both_processed(
    stripe_output_dir: Path,
    stripe_secret_env: str,
    stripe_idempotency_isolated: Path,
) -> None:
    """Two distinct evt_... ids → both processed end-to-end."""
    ts = int(_time.time())
    payload_a = _stripe_payload(occurred_at_unix=ts)
    payload_b = _stripe_payload(occurred_at_unix=ts)
    payload_b["id"] = "evt_3NqVe0LAuO3KjPaT0SgXLnY9_distinct"
    payload_b["data"]["object"]["id"] = "pi_distinct"
    raw_a = json.dumps(payload_a).encode("utf-8")
    raw_b = json.dumps(payload_b).encode("utf-8")
    sig_a = _stripe_signature(raw_a, stripe_secret_env, ts)
    sig_b = _stripe_signature(raw_b, stripe_secret_env, ts)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_a = await client.post(
            "/api/payment-rails/stripe-payment-link",
            content=raw_a,
            headers={"Stripe-Signature": sig_a},
        )
        r_b = await client.post(
            "/api/payment-rails/stripe-payment-link",
            content=raw_b,
            headers={"Stripe-Signature": sig_b},
        )

    assert r_a.json()["status"] == "received"
    assert r_b.json()["status"] == "received"
    files = list(stripe_output_dir.glob("event-payment_intent_succeeded-*.md"))
    assert len(files) == 2


@pytest.mark.asyncio
async def test_stripe_route_thin_payload_rejected_400(
    stripe_secret_env: str,
    stripe_idempotency_isolated: Path,
) -> None:
    """Thin-payload event (data.object only id+object) returns 400."""
    ts = int(_time.time())
    thin_payload = {
        "id": "evt_thin_test",
        "type": "payment_intent.succeeded",
        "created": ts,
        "api_version": "2024-04-10",
        "data": {"object": {"id": "pi_thin", "object": "payment_intent"}},
    }
    raw = json.dumps(thin_payload).encode("utf-8")
    sig = _stripe_signature(raw, stripe_secret_env, ts)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/stripe-payment-link",
            content=raw,
            headers={"Stripe-Signature": sig},
        )

    assert response.status_code == 400
    assert "thin-payload event rejected" in response.json()["detail"]


@pytest.mark.asyncio
async def test_stripe_route_replay_attack_outside_tolerance_rejected_400(
    stripe_secret_env: str,
    stripe_idempotency_isolated: Path,
) -> None:
    """Signed payload with timestamp >300s old returns 400 — replay rejected."""
    now = int(_time.time())
    expired_ts = now - 600  # 10 minutes old; default tolerance 300s
    payload = _stripe_payload(occurred_at_unix=expired_ts)
    raw = json.dumps(payload).encode("utf-8")
    sig = _stripe_signature(raw, stripe_secret_env, expired_ts)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/stripe-payment-link",
            content=raw,
            headers={"Stripe-Signature": sig},
        )

    assert response.status_code == 400
    assert "replay rejected" in response.json()["detail"]


def test_validate_secret_or_raise_module_export() -> None:
    """The startup-validator helper is exported and callable."""
    from shared.stripe_payment_link_receive_only_rail import validate_secret_or_raise

    assert callable(validate_secret_or_raise)
    # Behavior tested in unit tests; this only pins module-export shape.


# ===========================================================================
# Ko-fi rail integration tests (cc-task ko-fi-end-to-end-wiring)
# ===========================================================================

from shared.ko_fi_receive_only_rail import (
    KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV,
)

_KO_FI_TOKEN = "kofi-test-verification-token-XYZ"


def _ko_fi_payload(
    *,
    kind: str = "Donation",
    sender: str = "alice-supporter",
    amount: str = "5.00",
    currency: str = "USD",
    occurred_at: str = "2026-05-03T00:00:00Z",
    token: str | None = _KO_FI_TOKEN,
    kofi_transaction_id: str = "ko-fi-tx-test-001",
) -> dict:
    """Realistic Ko-fi webhook envelope (Ko-fi sends straight JSON)."""
    payload = {
        "verification_token": token,
        "message_id": "fff-ddd-eee-aaa",
        "kofi_transaction_id": kofi_transaction_id,
        "timestamp": occurred_at,
        "type": kind,
        "from_name": sender,
        "amount": amount,
        "currency": currency,
        "is_public": True,
        "message": "thanks for the work",  # PII; rail must NOT extract
        "email": "leak@example.com",  # PII (Ko-fi sends if marketing-opt-in)
    }
    if token is None:
        del payload["verification_token"]
    return payload


@pytest.fixture
def ko_fi_output_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    return tmp_path / "hapax-state" / "publications" / "ko-fi"


@pytest.fixture
def ko_fi_token_env(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV, _KO_FI_TOKEN)
    return _KO_FI_TOKEN


@pytest.fixture
def ko_fi_idempotency_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Reset the route's Ko-fi idempotency singleton + point at tmp db."""
    import logos.api.routes.payment_rails as routes_mod

    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    routes_mod._ko_fi_idempotency_store = None
    yield tmp_path / "ko-fi" / "idempotency.db"
    routes_mod._ko_fi_idempotency_store = None


@pytest.mark.asyncio
async def test_ko_fi_donation_writes_manifest(
    ko_fi_output_dir: Path,
    ko_fi_token_env: str,
    ko_fi_idempotency_isolated: Path,
) -> None:
    payload = _ko_fi_payload(kind="Donation", kofi_transaction_id="tx-donation-test")
    raw = json.dumps(payload).encode("utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/payment-rails/ko-fi", content=raw)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "received"
    assert body["event_kind"] == "donation"
    files = list(ko_fi_output_dir.glob("event-donation-*.md"))
    assert len(files) == 1, f"expected 1 manifest, got {files}"
    contents = files[0].read_text()
    assert "alice-supporter" in contents
    # PII must not leak
    assert "thanks for the work" not in contents
    assert "leak@example.com" not in contents


@pytest.mark.asyncio
async def test_ko_fi_subscription_writes_manifest(
    ko_fi_output_dir: Path,
    ko_fi_token_env: str,
    ko_fi_idempotency_isolated: Path,
) -> None:
    payload = _ko_fi_payload(
        kind="Subscription", sender="bob-patron", kofi_transaction_id="tx-sub-test"
    )
    raw = json.dumps(payload).encode("utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/payment-rails/ko-fi", content=raw)

    assert response.status_code == 200, response.text
    assert response.json()["event_kind"] == "subscription"


@pytest.mark.asyncio
async def test_ko_fi_token_mismatch_returns_400(
    ko_fi_output_dir: Path, ko_fi_token_env: str
) -> None:
    payload = _ko_fi_payload(token="wrong-token")
    raw = json.dumps(payload).encode("utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/payment-rails/ko-fi", content=raw)

    assert response.status_code == 400
    assert "verification_token" in response.json()["detail"]


@pytest.mark.asyncio
async def test_ko_fi_missing_token_returns_400(
    ko_fi_output_dir: Path, ko_fi_token_env: str
) -> None:
    payload = _ko_fi_payload(token=None)
    raw = json.dumps(payload).encode("utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/payment-rails/ko-fi", content=raw)

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_ko_fi_unaccepted_event_kind_returns_400(
    ko_fi_output_dir: Path, ko_fi_token_env: str
) -> None:
    payload = _ko_fi_payload(kind="Unknown Type")
    raw = json.dumps(payload).encode("utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/payment-rails/ko-fi", content=raw)

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_ko_fi_empty_body_returns_ping_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/payment-rails/ko-fi", content=b"")

    assert response.status_code == 200
    assert response.json()["status"] == "ping_ok"


def test_ko_fi_publisher_module_carries_no_send_path() -> None:
    import inspect

    import agents.publication_bus.ko_fi_publisher as mod

    src = inspect.getsource(mod).lower()
    forbidden_verbs = (
        "def send",
        "def initiate",
        "def payout",
        "def transfer",
        "def origination",
    )
    for token in forbidden_verbs:
        assert token not in src, f"unexpected send-path: {token!r}"


# ===========================================================================
# Ko-fi — idempotency hard pin (cc-task jr-ko-fi-rail-idempotency-pin)
# ===========================================================================


@pytest.mark.asyncio
async def test_ko_fi_route_replays_same_transaction_id_returns_duplicate(
    ko_fi_output_dir: Path,
    ko_fi_token_env: str,
    ko_fi_idempotency_isolated: Path,
) -> None:
    """Two POSTs of identical Ko-fi payload + transaction id → 2nd is duplicate."""
    payload = _ko_fi_payload(kind="Donation", kofi_transaction_id="tx-replay-001")
    raw = json.dumps(payload).encode("utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/api/payment-rails/ko-fi", content=raw)
        second = await client.post("/api/payment-rails/ko-fi", content=raw)

    assert first.status_code == 200 and first.json()["status"] == "received"
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["status"] == "duplicate"
    assert body["kofi_transaction_id"] == "tx-replay-001"

    files = list(ko_fi_output_dir.glob("event-donation-*.md"))
    assert len(files) == 1, f"expected 1 manifest, got {files}"


@pytest.mark.asyncio
async def test_ko_fi_route_distinct_transaction_ids_both_processed(
    ko_fi_output_dir: Path,
    ko_fi_token_env: str,
    ko_fi_idempotency_isolated: Path,
) -> None:
    """Two payloads with distinct kofi_transaction_id → both write manifests."""
    payload_a = _ko_fi_payload(kind="Donation", kofi_transaction_id="tx-distinct-a")
    payload_b = _ko_fi_payload(
        kind="Donation", sender="bob-supporter", kofi_transaction_id="tx-distinct-b"
    )
    raw_a = json.dumps(payload_a).encode("utf-8")
    raw_b = json.dumps(payload_b).encode("utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_a = await client.post("/api/payment-rails/ko-fi", content=raw_a)
        r_b = await client.post("/api/payment-rails/ko-fi", content=raw_b)

    assert r_a.json()["status"] == "received"
    assert r_b.json()["status"] == "received"
    files = list(ko_fi_output_dir.glob("event-donation-*.md"))
    assert len(files) == 2


@pytest.mark.asyncio
async def test_ko_fi_route_missing_transaction_id_returns_400(
    ko_fi_output_dir: Path,
    ko_fi_token_env: str,
    ko_fi_idempotency_isolated: Path,
) -> None:
    """Idempotency store provided + payload missing kofi_transaction_id → 400."""
    payload = _ko_fi_payload(kind="Donation")
    del payload["kofi_transaction_id"]
    raw = json.dumps(payload).encode("utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/payment-rails/ko-fi", content=raw)

    assert response.status_code == 400
    assert "kofi_transaction_id" in response.json()["detail"]


# ===========================================================================
# Patreon rail integration tests (cc-task patreon-end-to-end-wiring)
# ===========================================================================

from agents.publication_bus.patreon_publisher import (
    CANCELLATION_REFUSAL_AXIOM as PATREON_REFUSAL_AXIOM,
)
from agents.publication_bus.patreon_publisher import (
    CANCELLATION_REFUSAL_SURFACE as PATREON_REFUSAL_SURFACE,
)
from shared.patreon_receive_only_rail import (
    PATREON_WEBHOOK_SECRET_ENV,
)

_PATREON_VALID_SECRET = "patreon-webhook-secret-XYZ"


def _patreon_md5_signature(payload_bytes: bytes, secret: str = _PATREON_VALID_SECRET) -> str:
    """Compute Patreon's HMAC MD5 hex digest (NOT SHA-256, per Patreon spec)."""
    import hashlib as _hashlib

    return hmac.new(secret.encode("utf-8"), payload_bytes, _hashlib.md5).hexdigest()


def _patreon_payload(
    *,
    patron_vanity: str = "alice-patron",
    amount_cents: int = 1500,
    currency: str = "USD",
    occurred_at: str = "2026-05-03T00:00:00Z",
) -> dict:
    """Realistic Patreon JSON:API webhook envelope."""
    return {
        "data": {
            "id": "1234567",
            "type": "member",
            "attributes": {
                "currently_entitled_amount_cents": amount_cents,
                "lifetime_support_cents": amount_cents,
                "patron_status": "active_patron",
                "last_charge_date": occurred_at,
                "pledge_relationship_start": occurred_at,
                "email": "leak@example.com",  # PII; rail must NOT extract
                "full_name": "Alice Q. Patron",  # PII
                "note": "thanks for the work",  # PII
            },
            "relationships": {
                "user": {"data": {"id": "9999", "type": "user"}},
                "campaign": {
                    "data": {"id": "555", "type": "campaign"},
                },
            },
        },
        "included": [
            {
                "id": "9999",
                "type": "user",
                "attributes": {
                    "vanity": patron_vanity,
                    "email": "leak2@example.com",  # PII
                },
            },
            {
                "id": "555",
                "type": "campaign",
                "attributes": {
                    "currency": currency,
                },
            },
        ],
    }


@pytest.fixture
def patreon_output_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    return tmp_path / "hapax-state" / "publications" / "patreon"


@pytest.fixture
def patreon_secret_env(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(PATREON_WEBHOOK_SECRET_ENV, _PATREON_VALID_SECRET)
    return _PATREON_VALID_SECRET


@pytest.fixture
def patreon_idempotency_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Reset the route's Patreon idempotency singleton + point at tmp db.

    HAPAX_HOME is set so :func:`default_idempotency_db_path` lands in
    a per-test scratch directory; the module-level singleton is reset
    so the next call materializes a fresh sqlite db.
    """
    import logos.api.routes.payment_rails as routes_mod

    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    routes_mod._patreon_idempotency_store = None
    yield tmp_path / "patreon" / "idempotency.db"
    routes_mod._patreon_idempotency_store = None


@pytest.mark.asyncio
async def test_patreon_signed_pledge_create_writes_manifest(
    patreon_output_dir: Path,
    patreon_secret_env: str,
    patreon_idempotency_isolated: Path,
) -> None:
    payload = _patreon_payload(patron_vanity="alice-patron")
    raw = json.dumps(payload).encode("utf-8")
    sig = _patreon_md5_signature(raw)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/patreon",
            content=raw,
            headers={
                "X-Patreon-Signature": sig,
                "X-Patreon-Event": "members:pledge:create",
                "X-Patreon-Webhook-Id": "wh_test_create_001",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "received"
    assert body["event_kind"] == "members_pledge_create"
    files = list(patreon_output_dir.glob("event-members_pledge_create-*.md"))
    assert len(files) == 1, f"expected 1 manifest, got {files}"
    contents = files[0].read_text()
    assert "alice-patron" in contents
    # PII must not leak
    assert "leak@example.com" not in contents
    assert "leak2@example.com" not in contents
    assert "Alice Q. Patron" not in contents
    assert "thanks for the work" not in contents


@pytest.mark.asyncio
async def test_patreon_pledge_delete_appends_to_refusal_log(
    patreon_output_dir: Path,
    patreon_secret_env: str,
    refusal_log_dir: Path,
    patreon_idempotency_isolated: Path,
) -> None:
    payload = _patreon_payload(patron_vanity="bob-patron")
    raw = json.dumps(payload).encode("utf-8")
    sig = _patreon_md5_signature(raw)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/patreon",
            content=raw,
            headers={
                "X-Patreon-Signature": sig,
                "X-Patreon-Event": "members:pledge:delete",
                "X-Patreon-Webhook-Id": "wh_test_delete_001",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["event_kind"] == "members_pledge_delete"

    log_file = refusal_log_dir / "log.jsonl"
    assert log_file.exists()
    rows = [json.loads(line) for line in log_file.read_text().splitlines() if line]
    cancellations = [r for r in rows if r.get("surface") == PATREON_REFUSAL_SURFACE]
    assert cancellations
    assert cancellations[0]["axiom"] == PATREON_REFUSAL_AXIOM


@pytest.mark.asyncio
async def test_patreon_bad_signature_returns_400(
    patreon_output_dir: Path, patreon_secret_env: str
) -> None:
    payload = _patreon_payload()
    raw = json.dumps(payload).encode("utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/patreon",
            content=raw,
            headers={
                "X-Patreon-Signature": "0" * 32,  # MD5 hex is 32 chars
                "X-Patreon-Event": "members:pledge:create",
            },
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_patreon_missing_event_header_returns_400(
    patreon_output_dir: Path, patreon_secret_env: str
) -> None:
    payload = _patreon_payload()
    raw = json.dumps(payload).encode("utf-8")
    sig = _patreon_md5_signature(raw)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/patreon",
            content=raw,
            headers={"X-Patreon-Signature": sig},  # no X-Patreon-Event
        )

    assert response.status_code == 400
    assert "X-Patreon-Event" in response.json()["detail"]


@pytest.mark.asyncio
async def test_patreon_unaccepted_event_kind_returns_400(
    patreon_output_dir: Path, patreon_secret_env: str
) -> None:
    payload = _patreon_payload()
    raw = json.dumps(payload).encode("utf-8")
    sig = _patreon_md5_signature(raw)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/patreon",
            content=raw,
            headers={
                "X-Patreon-Signature": sig,
                "X-Patreon-Event": "campaign:update",
            },
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_patreon_empty_body_returns_ping_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/payment-rails/patreon", content=b"")

    assert response.status_code == 200
    assert response.json()["status"] == "ping_ok"


def test_patreon_publisher_module_carries_no_send_path() -> None:
    import inspect

    import agents.publication_bus.patreon_publisher as mod

    src = inspect.getsource(mod).lower()
    forbidden_verbs = (
        "def send",
        "def initiate",
        "def payout",
        "def transfer",
        "def origination",
    )
    for token in forbidden_verbs:
        assert token not in src, f"unexpected send-path: {token!r}"


# ===========================================================================
# Patreon — idempotency hard pin (cc-task jr-patreon-rail-idempotency-pin)
# ===========================================================================


@pytest.mark.asyncio
async def test_patreon_route_replays_same_webhook_id_returns_duplicate_status(
    patreon_output_dir: Path,
    patreon_secret_env: str,
    patreon_idempotency_isolated: Path,
) -> None:
    """Two POSTs of identical signed payload + webhook_id → 2nd is duplicate."""
    payload = _patreon_payload(patron_vanity="alice-patron")
    raw = json.dumps(payload).encode("utf-8")
    sig = _patreon_md5_signature(raw)
    headers = {
        "X-Patreon-Signature": sig,
        "X-Patreon-Event": "members:pledge:create",
        "X-Patreon-Webhook-Id": "wh_replay_test_001",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/api/payment-rails/patreon", content=raw, headers=headers)
        second = await client.post("/api/payment-rails/patreon", content=raw, headers=headers)

    assert first.status_code == 200 and first.json()["status"] == "received"
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["status"] == "duplicate"
    assert body["webhook_id"] == "wh_replay_test_001"

    files = list(patreon_output_dir.glob("event-members_pledge_create-*.md"))
    assert len(files) == 1, f"expected 1 manifest, got {files}"


@pytest.mark.asyncio
async def test_patreon_route_distinct_webhook_ids_both_processed(
    patreon_output_dir: Path,
    patreon_secret_env: str,
    patreon_idempotency_isolated: Path,
) -> None:
    """Same payload but distinct X-Patreon-Webhook-Id → both write manifests."""
    payload_a = _patreon_payload(patron_vanity="alice-patron")
    payload_b = _patreon_payload(patron_vanity="bob-patron")
    raw_a = json.dumps(payload_a).encode("utf-8")
    raw_b = json.dumps(payload_b).encode("utf-8")
    sig_a = _patreon_md5_signature(raw_a)
    sig_b = _patreon_md5_signature(raw_b)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_a = await client.post(
            "/api/payment-rails/patreon",
            content=raw_a,
            headers={
                "X-Patreon-Signature": sig_a,
                "X-Patreon-Event": "members:pledge:create",
                "X-Patreon-Webhook-Id": "wh_distinct_a",
            },
        )
        r_b = await client.post(
            "/api/payment-rails/patreon",
            content=raw_b,
            headers={
                "X-Patreon-Signature": sig_b,
                "X-Patreon-Event": "members:pledge:create",
                "X-Patreon-Webhook-Id": "wh_distinct_b",
            },
        )

    assert r_a.json()["status"] == "received"
    assert r_b.json()["status"] == "received"
    files = list(patreon_output_dir.glob("event-members_pledge_create-*.md"))
    assert len(files) == 2


@pytest.mark.asyncio
async def test_patreon_route_missing_webhook_id_returns_400(
    patreon_output_dir: Path,
    patreon_secret_env: str,
    patreon_idempotency_isolated: Path,
) -> None:
    """Idempotency store provided but X-Patreon-Webhook-Id header missing → 400."""
    payload = _patreon_payload()
    raw = json.dumps(payload).encode("utf-8")
    sig = _patreon_md5_signature(raw)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/patreon",
            content=raw,
            headers={
                "X-Patreon-Signature": sig,
                "X-Patreon-Event": "members:pledge:create",
                # NO X-Patreon-Webhook-Id
            },
        )

    assert response.status_code == 400
    assert "webhook_id" in response.json()["detail"]


# ===========================================================================
# Buy Me a Coffee rail integration tests (cc-task buy-me-a-coffee-end-to-end-wiring)
# ===========================================================================

from agents.publication_bus.buy_me_a_coffee_publisher import (
    CANCELLATION_REFUSAL_AXIOM as BMAC_REFUSAL_AXIOM,
)
from agents.publication_bus.buy_me_a_coffee_publisher import (
    CANCELLATION_REFUSAL_SURFACE as BMAC_REFUSAL_SURFACE,
)
from shared.buy_me_a_coffee_receive_only_rail import (
    BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV,
)

_BMAC_VALID_SECRET = "bmac-webhook-secret-XYZ"


def _bmac_payload(
    *,
    kind: str = "donation",
    supporter: str = "alice-supporter",
    amount: str = "5.00",
    currency: str = "USD",
    occurred_at: str = "2026-05-03T00:00:00Z",
    event_id: str = "11111111-1111-1111-1111-111111111111",
) -> dict:
    return {
        "type": kind,
        "live_mode": True,
        "attempt": 1,
        "created": occurred_at,
        "event_id": event_id,
        "data": {
            "id": "donation-id-1",
            "supporter_name": supporter,
            "amount": amount,
            "currency": currency,
            "created_at": occurred_at,
            "support_note": "thanks for the work",  # PII; rail must NOT extract
            "supporter_email": "leak@example.com",  # PII
        },
    }


@pytest.fixture
def bmac_output_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    return tmp_path / "hapax-state" / "publications" / "buy-me-a-coffee"


@pytest.fixture
def bmac_secret_env(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV, _BMAC_VALID_SECRET)
    return _BMAC_VALID_SECRET


@pytest.fixture
def bmac_idempotency_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Reset the route's BMaC idempotency singleton + point at tmp db."""
    import logos.api.routes.payment_rails as routes_mod

    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    routes_mod._buy_me_a_coffee_idempotency_store = None
    yield tmp_path / "buy-me-a-coffee" / "idempotency.db"
    routes_mod._buy_me_a_coffee_idempotency_store = None


@pytest.mark.asyncio
async def test_bmac_signed_donation_writes_manifest(
    bmac_output_dir: Path,
    bmac_secret_env: str,
    bmac_idempotency_isolated: Path,
) -> None:
    payload = _bmac_payload(kind="donation", event_id="evt-bmac-donation-test")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(bmac_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/buy-me-a-coffee",
            content=raw,
            headers={"X-Signature-Sha256": sig},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "received"
    assert body["event_kind"] == "donation"
    files = list(bmac_output_dir.glob("event-donation-*.md"))
    assert len(files) == 1, f"expected 1 manifest, got {files}"
    contents = files[0].read_text()
    assert "alice-supporter" in contents
    # PII negative pin
    assert "thanks for the work" not in contents
    assert "leak@example.com" not in contents


@pytest.mark.asyncio
async def test_bmac_membership_started_dotted_form(
    bmac_output_dir: Path,
    bmac_secret_env: str,
    bmac_idempotency_isolated: Path,
) -> None:
    """BMaC membership.started uses dotted form (not underscored)."""
    payload = _bmac_payload(
        kind="membership.started",
        supporter="bob-member",
        event_id="evt-bmac-mship-started",
    )
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(bmac_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/buy-me-a-coffee",
            content=raw,
            headers={"X-Signature-Sha256": sig},
        )

    assert response.status_code == 200, response.text
    assert response.json()["event_kind"] == "membership.started"


@pytest.mark.asyncio
async def test_bmac_membership_cancelled_appends_to_refusal_log(
    bmac_output_dir: Path,
    bmac_secret_env: str,
    refusal_log_dir: Path,
    bmac_idempotency_isolated: Path,
) -> None:
    payload = _bmac_payload(
        kind="membership.cancelled",
        supporter="charlie-cancelled",
        event_id="evt-bmac-mship-cancelled",
    )
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(bmac_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/buy-me-a-coffee",
            content=raw,
            headers={"X-Signature-Sha256": sig},
        )

    assert response.status_code == 200, response.text
    assert response.json()["event_kind"] == "membership.cancelled"

    log_file = refusal_log_dir / "log.jsonl"
    assert log_file.exists()
    rows = [json.loads(line) for line in log_file.read_text().splitlines() if line]
    cancellations = [r for r in rows if r.get("surface") == BMAC_REFUSAL_SURFACE]
    assert cancellations
    assert cancellations[0]["axiom"] == BMAC_REFUSAL_AXIOM


@pytest.mark.asyncio
async def test_bmac_bad_signature_returns_400(bmac_output_dir: Path, bmac_secret_env: str) -> None:
    payload = _bmac_payload()
    raw = json.dumps(payload).encode("utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/buy-me-a-coffee",
            content=raw,
            headers={"X-Signature-Sha256": "0" * 64},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_bmac_sha256_prefix_form_accepted(
    bmac_output_dir: Path, bmac_secret_env: str
) -> None:
    """BMaC accepts both bare hex digest and ``sha256=<hex>`` prefixed."""
    payload = _bmac_payload()
    raw = json.dumps(payload).encode("utf-8")
    sig = "sha256=" + hmac.new(bmac_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/buy-me-a-coffee",
            content=raw,
            headers={"X-Signature-Sha256": sig},
        )

    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_bmac_unaccepted_kind_returns_400(
    bmac_output_dir: Path, bmac_secret_env: str
) -> None:
    payload = _bmac_payload(kind="contribution.refund")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(bmac_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/buy-me-a-coffee",
            content=raw,
            headers={"X-Signature-Sha256": sig},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_bmac_empty_body_returns_ping_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/payment-rails/buy-me-a-coffee", content=b"")

    assert response.status_code == 200
    assert response.json()["status"] == "ping_ok"


def test_bmac_publisher_module_carries_no_send_path() -> None:
    import inspect

    import agents.publication_bus.buy_me_a_coffee_publisher as mod

    src = inspect.getsource(mod).lower()
    forbidden_verbs = (
        "def send",
        "def initiate",
        "def payout",
        "def transfer",
        "def origination",
    )
    for token in forbidden_verbs:
        assert token not in src, f"unexpected send-path: {token!r}"


# ===========================================================================
# BMaC — idempotency hard pin (cc-task jr-buy-me-a-coffee-rail-idempotency-pin)
# ===========================================================================


@pytest.mark.asyncio
async def test_bmac_route_replays_same_event_id_returns_duplicate(
    bmac_output_dir: Path,
    bmac_secret_env: str,
    bmac_idempotency_isolated: Path,
) -> None:
    """Two POSTs of identical signed payload → second returns status=duplicate."""
    payload = _bmac_payload(kind="donation", event_id="evt-bmac-replay-001")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(bmac_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/api/payment-rails/buy-me-a-coffee",
            content=raw,
            headers={"X-Signature-Sha256": sig},
        )
        second = await client.post(
            "/api/payment-rails/buy-me-a-coffee",
            content=raw,
            headers={"X-Signature-Sha256": sig},
        )

    assert first.status_code == 200 and first.json()["status"] == "received"
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["status"] == "duplicate"
    assert body["event_id"] == "evt-bmac-replay-001"

    files = list(bmac_output_dir.glob("event-donation-*.md"))
    assert len(files) == 1, f"expected 1 manifest, got {files}"


@pytest.mark.asyncio
async def test_bmac_route_distinct_event_ids_both_processed(
    bmac_output_dir: Path,
    bmac_secret_env: str,
    bmac_idempotency_isolated: Path,
) -> None:
    """Distinct event_ids → both deliveries write manifests."""
    payload_a = _bmac_payload(kind="donation", event_id="evt-bmac-a")
    payload_b = _bmac_payload(kind="donation", supporter="bob", event_id="evt-bmac-b")
    raw_a = json.dumps(payload_a).encode("utf-8")
    raw_b = json.dumps(payload_b).encode("utf-8")
    sig_a = hmac.new(bmac_secret_env.encode("utf-8"), raw_a, hashlib.sha256).hexdigest()
    sig_b = hmac.new(bmac_secret_env.encode("utf-8"), raw_b, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_a = await client.post(
            "/api/payment-rails/buy-me-a-coffee",
            content=raw_a,
            headers={"X-Signature-Sha256": sig_a},
        )
        r_b = await client.post(
            "/api/payment-rails/buy-me-a-coffee",
            content=raw_b,
            headers={"X-Signature-Sha256": sig_b},
        )

    assert r_a.json()["status"] == "received"
    assert r_b.json()["status"] == "received"
    files = list(bmac_output_dir.glob("event-donation-*.md"))
    assert len(files) == 2


@pytest.mark.asyncio
async def test_bmac_route_missing_event_id_returns_400(
    bmac_output_dir: Path,
    bmac_secret_env: str,
    bmac_idempotency_isolated: Path,
) -> None:
    """Idempotency store provided + payload missing event_id → 400."""
    payload = _bmac_payload(kind="donation")
    del payload["event_id"]
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(bmac_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/buy-me-a-coffee",
            content=raw,
            headers={"X-Signature-Sha256": sig},
        )

    assert response.status_code == 400
    assert "event_id" in response.json()["detail"]


# ===========================================================================
# Mercury rail integration tests (cc-task mercury-end-to-end-wiring)
# ===========================================================================

from shared.mercury_receive_only_rail import (
    MERCURY_WEBHOOK_SECRET_ENV,
)

_MERCURY_VALID_SECRET = "mercury-webhook-secret-XYZ"


def _mercury_payload(
    *,
    event_type: str = "transaction.created",
    counterparty: str = "Acme Foundation",
    amount: str = "100.00",
    currency: str = "USD",
    kind: str = "ach_incoming",
    occurred_at: str = "2026-05-03T00:00:00Z",
    txn_id: str = "txn-mercury-incoming-1",
) -> dict:
    """Realistic Mercury delivery for an incoming ACH transfer.

    Includes banking PII (account_number, routing_number, memo) that
    the receiver MUST NOT extract.
    """
    return {
        "type": event_type,
        "data": {
            "id": txn_id,
            "amount": amount,
            "currency": currency,
            "kind": kind,
            "counterparty_name": counterparty,
            "counterparty_email": "treasury@example.com",  # PII
            "counterparty_routing_number": "021000089",  # PII
            "counterparty_account_number": "999111888777",  # PII
            "memo": "thank you Q2 retainer",  # PII
            "status": "settled",
            "created_at": occurred_at,
            "posted_at": occurred_at,
        },
    }


@pytest.fixture
def mercury_output_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    return tmp_path / "hapax-state" / "publications" / "mercury"


@pytest.fixture
def mercury_secret_env(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(MERCURY_WEBHOOK_SECRET_ENV, _MERCURY_VALID_SECRET)
    return _MERCURY_VALID_SECRET


@pytest.fixture
def mercury_idempotency_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Reset the route's Mercury idempotency singleton + tmp db."""
    import logos.api.routes.payment_rails as routes_mod

    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    routes_mod._mercury_idempotency_store = None
    yield tmp_path / "mercury" / "idempotency.db"
    routes_mod._mercury_idempotency_store = None


@pytest.mark.asyncio
async def test_mercury_signed_ach_incoming_writes_manifest(
    mercury_output_dir: Path, mercury_secret_env: str
) -> None:
    payload = _mercury_payload(kind="ach_incoming")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(mercury_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/mercury",
            content=raw,
            headers={"X-Mercury-Signature": sig},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "received"
    assert body["event_kind"] == "transaction.created"
    assert body["direction"] == "incoming"
    files = list(mercury_output_dir.glob("event-transaction_created-*.md"))
    assert len(files) == 1
    contents = files[0].read_text()
    assert "Acme Foundation" in contents
    # Banking PII must not leak
    assert "021000089" not in contents  # routing
    assert "999111888777" not in contents  # account
    assert "treasury@example.com" not in contents
    assert "Q2 retainer" not in contents


@pytest.mark.asyncio
async def test_mercury_legacy_x_hook_signature_header_accepted(
    mercury_output_dir: Path, mercury_secret_env: str
) -> None:
    """Older Mercury integrations may emit X-Hook-Signature instead of X-Mercury-Signature."""
    payload = _mercury_payload()
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(mercury_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/mercury",
            content=raw,
            headers={"X-Hook-Signature": sig},  # legacy header name
        )

    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_mercury_outgoing_kind_rejected(
    mercury_output_dir: Path, mercury_secret_env: str
) -> None:
    """Receiver direction filter rejects outgoing transaction kinds."""
    payload = _mercury_payload(kind="ach_outgoing")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(mercury_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/mercury",
            content=raw,
            headers={"X-Mercury-Signature": sig},
        )

    assert response.status_code == 400
    assert "refusing outgoing" in response.json()["detail"]


@pytest.mark.asyncio
async def test_mercury_wire_incoming_accepted(
    mercury_output_dir: Path, mercury_secret_env: str
) -> None:
    payload = _mercury_payload(kind="wire_incoming")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(mercury_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/mercury",
            content=raw,
            headers={"X-Mercury-Signature": sig},
        )

    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_mercury_bad_signature_returns_400(
    mercury_output_dir: Path, mercury_secret_env: str
) -> None:
    payload = _mercury_payload()
    raw = json.dumps(payload).encode("utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/mercury",
            content=raw,
            headers={"X-Mercury-Signature": "0" * 64},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_mercury_empty_body_returns_ping_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/payment-rails/mercury", content=b"")

    assert response.status_code == 200
    assert response.json()["status"] == "ping_ok"


def test_mercury_publisher_module_carries_no_send_path() -> None:
    import inspect

    import agents.publication_bus.mercury_publisher as mod

    src = inspect.getsource(mod).lower()
    forbidden_verbs = (
        "def send",
        "def initiate",
        "def payout",
        "def transfer",
        "def origination",
    )
    for token in forbidden_verbs:
        assert token not in src, f"unexpected send-path: {token!r}"


# ===========================================================================
# Mercury — idempotency hard pin (cc-task jr-mercury-rail-idempotency-pin)
# ===========================================================================


@pytest.mark.asyncio
async def test_mercury_route_replays_same_txn_id_returns_duplicate(
    mercury_output_dir: Path,
    mercury_secret_env: str,
    mercury_idempotency_isolated: Path,
) -> None:
    payload = _mercury_payload(txn_id="txn-mercury-replay-001")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(mercury_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    headers = {"X-Mercury-Signature": sig}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/api/payment-rails/mercury", content=raw, headers=headers)
        second = await client.post("/api/payment-rails/mercury", content=raw, headers=headers)

    assert first.status_code == 200 and first.json()["status"] == "received"
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["status"] == "duplicate"
    assert body["transaction_id"] == "txn-mercury-replay-001"
    files = list(mercury_output_dir.glob("event-transaction_created-*.md"))
    assert len(files) == 1


@pytest.mark.asyncio
async def test_mercury_route_distinct_txn_ids_both_processed(
    mercury_output_dir: Path,
    mercury_secret_env: str,
    mercury_idempotency_isolated: Path,
) -> None:
    payload_a = _mercury_payload(txn_id="txn-mercury-a")
    payload_b = _mercury_payload(txn_id="txn-mercury-b", counterparty="Foo Foundation")
    raw_a = json.dumps(payload_a).encode("utf-8")
    raw_b = json.dumps(payload_b).encode("utf-8")
    sig_a = hmac.new(mercury_secret_env.encode("utf-8"), raw_a, hashlib.sha256).hexdigest()
    sig_b = hmac.new(mercury_secret_env.encode("utf-8"), raw_b, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_a = await client.post(
            "/api/payment-rails/mercury",
            content=raw_a,
            headers={"X-Mercury-Signature": sig_a},
        )
        r_b = await client.post(
            "/api/payment-rails/mercury",
            content=raw_b,
            headers={"X-Mercury-Signature": sig_b},
        )

    assert r_a.json()["status"] == "received"
    assert r_b.json()["status"] == "received"
    files = list(mercury_output_dir.glob("event-transaction_created-*.md"))
    assert len(files) == 2


@pytest.mark.asyncio
async def test_mercury_route_missing_data_id_returns_400(
    mercury_output_dir: Path,
    mercury_secret_env: str,
    mercury_idempotency_isolated: Path,
) -> None:
    payload = _mercury_payload()
    del payload["data"]["id"]
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(mercury_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/mercury",
            content=raw,
            headers={"X-Mercury-Signature": sig},
        )

    assert response.status_code == 400
    assert "data.id" in response.json()["detail"]


# ===========================================================================
# Modern Treasury rail integration tests (cc-task modern-treasury-end-to-end-wiring)
# ===========================================================================

from shared.modern_treasury_receive_only_rail import (
    MODERN_TREASURY_WEBHOOK_SECRET_ENV,
)

_MT_VALID_SECRET = "modern-treasury-webhook-secret-XYZ"


def _modern_treasury_payload(
    *,
    event: str = "incoming_payment_detail.created",
    originating_party_name: str = "Foundation Trust",
    amount: object = 10000,
    currency: str = "USD",
    payment_type: str = "ach",
    created_at: str = "2026-05-03T00:00:00Z",
    payment_id: str = "ipd-uuid-1111",
) -> dict:
    return {
        "event": event,
        "data": {
            "id": payment_id,
            "object": "incoming_payment_detail",
            "amount": amount,
            "currency": currency,
            "type": payment_type,
            "status": "completed",
            "originating_party_name": originating_party_name,
            "originating_account_number": "999111888777",  # PII
            "originating_routing_number": "021000089",  # PII
            "description": "thank you Q2 retainer",  # PII
            "vendor_id": "mt-vendor-001",  # PII
            "created_at": created_at,
            "updated_at": created_at,
        },
    }


@pytest.fixture
def mt_output_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    return tmp_path / "hapax-state" / "publications" / "modern-treasury"


@pytest.fixture
def mt_secret_env(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(MODERN_TREASURY_WEBHOOK_SECRET_ENV, _MT_VALID_SECRET)
    return _MT_VALID_SECRET


@pytest.fixture
def mt_idempotency_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Reset the route's Modern Treasury idempotency singleton + tmp db."""
    import logos.api.routes.payment_rails as routes_mod

    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    routes_mod._modern_treasury_idempotency_store = None
    yield tmp_path / "modern-treasury" / "idempotency.db"
    routes_mod._modern_treasury_idempotency_store = None


@pytest.mark.asyncio
async def test_modern_treasury_signed_ach_created_writes_manifest(
    mt_output_dir: Path, mt_secret_env: str
) -> None:
    payload = _modern_treasury_payload()
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(mt_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/modern-treasury",
            content=raw,
            headers={"X-Signature": sig},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "received"
    assert body["event_kind"] == "incoming_payment_detail.created"
    assert body["payment_method"] == "ach"
    files = list(mt_output_dir.glob("event-incoming_payment_detail_created-*.md"))
    assert len(files) == 1
    contents = files[0].read_text()
    assert "Foundation Trust" in contents
    # Banking-PII negative pin
    assert "021000089" not in contents
    assert "999111888777" not in contents
    assert "Q2 retainer" not in contents
    assert "mt-vendor-001" not in contents


@pytest.mark.asyncio
async def test_modern_treasury_outgoing_event_rejected(
    mt_output_dir: Path, mt_secret_env: str
) -> None:
    """Event-name-level direction filter rejects payment_order.*."""
    payload = _modern_treasury_payload(event="payment_order.created")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(mt_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/modern-treasury",
            content=raw,
            headers={"X-Signature": sig},
        )

    assert response.status_code == 400
    assert "refusing outgoing" in response.json()["detail"]


@pytest.mark.asyncio
async def test_modern_treasury_wire_payment_method(
    mt_output_dir: Path,
    mt_secret_env: str,
    mt_idempotency_isolated: Path,
) -> None:
    payload = _modern_treasury_payload(payment_type="wire", payment_id="ipd-wire-test")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(mt_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/modern-treasury",
            content=raw,
            headers={"X-Signature": sig},
        )

    assert response.status_code == 200, response.text
    assert response.json()["payment_method"] == "wire"


@pytest.mark.asyncio
async def test_modern_treasury_completed_event(
    mt_output_dir: Path,
    mt_secret_env: str,
    mt_idempotency_isolated: Path,
) -> None:
    payload = _modern_treasury_payload(
        event="incoming_payment_detail.completed", payment_id="ipd-completed-test"
    )
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(mt_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/modern-treasury",
            content=raw,
            headers={"X-Signature": sig},
        )

    assert response.status_code == 200
    assert response.json()["event_kind"] == "incoming_payment_detail.completed"


@pytest.mark.asyncio
async def test_modern_treasury_bad_signature_returns_400(
    mt_output_dir: Path, mt_secret_env: str
) -> None:
    payload = _modern_treasury_payload()
    raw = json.dumps(payload).encode("utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/modern-treasury",
            content=raw,
            headers={"X-Signature": "0" * 64},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_modern_treasury_empty_body_returns_ping_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/payment-rails/modern-treasury", content=b"")

    assert response.status_code == 200
    assert response.json()["status"] == "ping_ok"


def test_modern_treasury_publisher_module_carries_no_send_path() -> None:
    import inspect

    import agents.publication_bus.modern_treasury_publisher as mod

    src = inspect.getsource(mod).lower()
    forbidden_verbs = (
        "def send",
        "def initiate",
        "def payout",
        "def transfer",
        "def origination",
    )
    for token in forbidden_verbs:
        assert token not in src, f"unexpected send-path: {token!r}"


# ===========================================================================
# Modern Treasury — idempotency hard pin (cc-task jr-modern-treasury-rail-idempotency-pin)
# ===========================================================================


@pytest.mark.asyncio
async def test_modern_treasury_route_replays_same_payment_id_returns_duplicate(
    mt_output_dir: Path,
    mt_secret_env: str,
    mt_idempotency_isolated: Path,
) -> None:
    payload = _modern_treasury_payload(payment_id="ipd-replay-001")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(mt_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    headers = {"X-Signature": sig}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/api/payment-rails/modern-treasury", content=raw, headers=headers
        )
        second = await client.post(
            "/api/payment-rails/modern-treasury", content=raw, headers=headers
        )

    assert first.status_code == 200 and first.json()["status"] == "received"
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["status"] == "duplicate"
    assert body["payment_id"] == "ipd-replay-001"
    files = list(mt_output_dir.glob("event-incoming_payment_detail_created-*.md"))
    assert len(files) == 1


@pytest.mark.asyncio
async def test_modern_treasury_route_distinct_payment_ids_both_processed(
    mt_output_dir: Path,
    mt_secret_env: str,
    mt_idempotency_isolated: Path,
) -> None:
    payload_a = _modern_treasury_payload(payment_id="ipd-a")
    payload_b = _modern_treasury_payload(payment_id="ipd-b")
    raw_a = json.dumps(payload_a).encode("utf-8")
    raw_b = json.dumps(payload_b).encode("utf-8")
    sig_a = hmac.new(mt_secret_env.encode("utf-8"), raw_a, hashlib.sha256).hexdigest()
    sig_b = hmac.new(mt_secret_env.encode("utf-8"), raw_b, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_a = await client.post(
            "/api/payment-rails/modern-treasury",
            content=raw_a,
            headers={"X-Signature": sig_a},
        )
        r_b = await client.post(
            "/api/payment-rails/modern-treasury",
            content=raw_b,
            headers={"X-Signature": sig_b},
        )

    assert r_a.json()["status"] == "received"
    assert r_b.json()["status"] == "received"
    files = list(mt_output_dir.glob("event-incoming_payment_detail_created-*.md"))
    assert len(files) == 2


@pytest.mark.asyncio
async def test_modern_treasury_route_missing_data_id_returns_400(
    mt_output_dir: Path,
    mt_secret_env: str,
    mt_idempotency_isolated: Path,
) -> None:
    payload = _modern_treasury_payload()
    del payload["data"]["id"]
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(mt_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/modern-treasury",
            content=raw,
            headers={"X-Signature": sig},
        )

    assert response.status_code == 400
    assert "data.id" in response.json()["detail"]


# ===========================================================================
# Treasury Prime rail integration tests (cc-task treasury-prime-end-to-end-wiring)
# ===========================================================================

from shared.treasury_prime_receive_only_rail import (
    TREASURY_PRIME_WEBHOOK_SECRET_ENV,
)

_TP_VALID_SECRET = "treasury-prime-webhook-secret-XYZ"


def _treasury_prime_payload(
    *,
    event: str = "incoming_ach.create",
    originating_party_name: str = "Acme Foundation",
    amount: object = 10000,
    currency: str = "USD",
    created_at: str = "2026-05-03T00:00:00Z",
) -> dict:
    return {
        "event": event,
        "data": {
            "id": "tp-incoming-ach-uuid",
            "amount": amount,
            "currency": currency,
            "originating_party_name": originating_party_name,
            "originating_account_number": "999111888777",  # PII
            "originating_routing_number": "021000089",  # PII
            "originating_address": "1 Main St",  # PII
            "trace_number": "TRACE-12345",  # PII
            "company_entry_description": "PAYROLL-Q2",  # PII
            "ledger_account_id": "la-uuid-1234",
            "created_at": created_at,
        },
    }


@pytest.fixture
def tp_output_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    return tmp_path / "hapax-state" / "publications" / "treasury-prime"


@pytest.fixture
def tp_secret_env(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(TREASURY_PRIME_WEBHOOK_SECRET_ENV, _TP_VALID_SECRET)
    return _TP_VALID_SECRET


@pytest.mark.asyncio
async def test_treasury_prime_signed_incoming_ach_writes_manifest(
    tp_output_dir: Path, tp_secret_env: str
) -> None:
    payload = _treasury_prime_payload()
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(tp_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/treasury-prime",
            content=raw,
            headers={"X-Signature": sig},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "received"
    assert body["event_kind"] == "incoming_ach.create"
    files = list(tp_output_dir.glob("event-incoming_ach_create-*.md"))
    assert len(files) == 1
    contents = files[0].read_text()
    assert "Acme Foundation" in contents
    # Banking-PII negative pin
    assert "021000089" not in contents
    assert "999111888777" not in contents
    assert "TRACE-12345" not in contents
    assert "PAYROLL-Q2" not in contents


@pytest.mark.asyncio
async def test_treasury_prime_phase_1_event_rejected(
    tp_output_dir: Path, tp_secret_env: str
) -> None:
    """Phase 0 rejects core-direct-account events (Phase 1 scope)."""
    payload = _treasury_prime_payload(event="transaction.create")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(tp_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/treasury-prime",
            content=raw,
            headers={"X-Signature": sig},
        )

    assert response.status_code == 400
    assert "out of Phase 0 scope" in response.json()["detail"]


@pytest.mark.asyncio
async def test_treasury_prime_outgoing_rejected(tp_output_dir: Path, tp_secret_env: str) -> None:
    payload = _treasury_prime_payload(event="ach_origination.create")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(tp_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/treasury-prime",
            content=raw,
            headers={"X-Signature": sig},
        )

    assert response.status_code == 400
    assert "refusing outgoing" in response.json()["detail"]


@pytest.mark.asyncio
async def test_treasury_prime_bad_signature_returns_400(
    tp_output_dir: Path, tp_secret_env: str
) -> None:
    payload = _treasury_prime_payload()
    raw = json.dumps(payload).encode("utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/treasury-prime",
            content=raw,
            headers={"X-Signature": "0" * 64},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_treasury_prime_empty_body_returns_ping_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/payment-rails/treasury-prime", content=b"")

    assert response.status_code == 200
    assert response.json()["status"] == "ping_ok"


def test_treasury_prime_publisher_module_carries_no_send_path() -> None:
    import inspect

    import agents.publication_bus.treasury_prime_publisher as mod

    src = inspect.getsource(mod).lower()
    forbidden_verbs = (
        "def send",
        "def initiate",
        "def payout",
        "def transfer",
        "def origination",
    )
    for token in forbidden_verbs:
        assert token not in src, f"unexpected send-path: {token!r}"
