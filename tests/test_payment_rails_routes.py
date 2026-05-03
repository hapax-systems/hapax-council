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
