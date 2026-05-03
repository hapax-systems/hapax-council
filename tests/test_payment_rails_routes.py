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
    assert "25.00" in contents


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


@pytest.mark.asyncio
async def test_liberapay_signed_payin_succeeded_writes_manifest(
    liberapay_output_dir: Path, liberapay_secret_env: str
) -> None:
    payload = _liberapay_payload(event="payin_succeeded")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(liberapay_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/liberapay",
            content=raw,
            headers={"X-Liberapay-Signature": sig},
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
    liberapay_output_dir: Path, liberapay_secret_env: str
) -> None:
    """Bridges may forward Liberapay's dotted form (`payin.succeeded`)."""
    payload = _liberapay_payload(event="payin.succeeded")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(liberapay_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/liberapay",
            content=raw,
            headers={"X-Liberapay-Signature": sig},
        )

    assert response.status_code == 200, response.text
    assert response.json()["event_kind"] == "payin_succeeded"


@pytest.mark.asyncio
async def test_liberapay_tip_cancelled_appends_to_refusal_log(
    liberapay_output_dir: Path,
    liberapay_secret_env: str,
    refusal_log_dir: Path,
) -> None:
    payload = _liberapay_payload(event="tip_cancelled", donor="bob-donor")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(liberapay_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/liberapay",
            content=raw,
            headers={"X-Liberapay-Signature": sig},
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


@pytest.mark.asyncio
async def test_open_collective_signed_order_processed_writes_manifest(
    open_collective_output_dir: Path, open_collective_secret_env: str
) -> None:
    payload = _open_collective_payload(activity="order_processed")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(open_collective_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/open-collective",
            content=raw,
            headers={"X-Open-Collective-Signature": sig},
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
    open_collective_output_dir: Path, open_collective_secret_env: str
) -> None:
    """OC bridges may forward the dotted form `order.processed`."""
    payload = _open_collective_payload(activity="order.processed")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(open_collective_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/open-collective",
            content=raw,
            headers={"X-Open-Collective-Signature": sig},
        )

    assert response.status_code == 200, response.text
    assert response.json()["event_kind"] == "order_processed"


@pytest.mark.asyncio
async def test_open_collective_member_created(
    open_collective_output_dir: Path, open_collective_secret_env: str
) -> None:
    payload = _open_collective_payload(activity="member_created", member="bob-member")
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(open_collective_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/open-collective",
            content=raw,
            headers={"X-Open-Collective-Signature": sig},
        )

    assert response.status_code == 200, response.text
    assert response.json()["event_kind"] == "member_created"


@pytest.mark.asyncio
async def test_open_collective_eur_currency(
    open_collective_output_dir: Path, open_collective_secret_env: str
) -> None:
    """Open Collective is multi-currency; EUR should pass."""
    payload = _open_collective_payload(currency="EUR", amount=2000)
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(open_collective_secret_env.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/payment-rails/open-collective",
            content=raw,
            headers={"X-Open-Collective-Signature": sig},
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
) -> dict:
    """Realistic Ko-fi webhook envelope (Ko-fi sends straight JSON)."""
    payload = {
        "verification_token": token,
        "message_id": "fff-ddd-eee-aaa",
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


@pytest.mark.asyncio
async def test_ko_fi_donation_writes_manifest(ko_fi_output_dir: Path, ko_fi_token_env: str) -> None:
    payload = _ko_fi_payload(kind="Donation")
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
    ko_fi_output_dir: Path, ko_fi_token_env: str
) -> None:
    payload = _ko_fi_payload(kind="Subscription", sender="bob-patron")
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


@pytest.mark.asyncio
async def test_patreon_signed_pledge_create_writes_manifest(
    patreon_output_dir: Path, patreon_secret_env: str
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
) -> dict:
    return {
        "type": kind,
        "live_mode": True,
        "attempt": 1,
        "created": occurred_at,
        "event_id": "11111111-1111-1111-1111-111111111111",
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


@pytest.mark.asyncio
async def test_bmac_signed_donation_writes_manifest(
    bmac_output_dir: Path, bmac_secret_env: str
) -> None:
    payload = _bmac_payload(kind="donation")
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
    bmac_output_dir: Path, bmac_secret_env: str
) -> None:
    """BMaC membership.started uses dotted form (not underscored)."""
    payload = _bmac_payload(kind="membership.started", supporter="bob-member")
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
) -> None:
    payload = _bmac_payload(kind="membership.cancelled", supporter="charlie-cancelled")
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
