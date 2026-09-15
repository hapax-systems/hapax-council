"""API payload, refusal, startup, and durable retry witnesses using synthetic data."""

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import yaml
from fastapi import FastAPI

import logos._governance as mirror
from agents._governance import revocation_wiring
from logos.api.routes import consent as routes
from logos.api.routes import data
from shared.governance import consent
from shared.governance.revocation import RevocationPropagator
from tests.shared.synthetic_custody import CONTRACT, ENTRY, OLD_CONTRACT, OLD_PRINCIPAL, PRINCIPAL


@pytest.fixture
def local_api(synthetic_custody, monkeypatch, tmp_path):
    directory = tmp_path / "contracts"
    directory.mkdir()
    registry = consent.ConsentRegistry(_contracts_dir=directory)
    prop = RevocationPropagator(registry)
    monkeypatch.setattr(routes, "get_revocation_propagator", lambda: prop)
    monkeypatch.setattr(routes, "_PURGE_AUDIT_PATH", tmp_path / "archive" / "purge.log")
    monkeypatch.setattr(mirror, "load_contracts", lambda: registry)
    notifications = []
    monkeypatch.setattr(routes, "send_notification", lambda *a, **kw: notifications.append((a, kw)))
    app = FastAPI()
    app.include_router(routes.router)
    app.include_router(data.router)
    return app, prop, registry, notifications


@pytest.mark.parametrize("labeled", [True, False])
@pytest.mark.parametrize("historical_filename", [False, True])
async def test_trace_exports_canonical_metadata_and_filters_real_preview(
    labeled, historical_filename, local_api, synthetic_custody, monkeypatch, tmp_path
):
    app, prop, registry, notifications = local_api
    registry.create_contract(PRINCIPAL, frozenset({"audio"}), contract_id=CONTRACT)
    frontmatter = {"provenance": [OLD_CONTRACT]}
    if labeled:
        frontmatter["consent_label"] = {
            "policies": [{"owner": OLD_PRINCIPAL, "readers": ["operator", OLD_PRINCIPAL]}]
        }
    source = tmp_path / f"{OLD_PRINCIPAL if historical_filename else 'synthetic-source'}.md"
    body = f"Private notes about {OLD_PRINCIPAL}."
    source.write_text("---\n" + yaml.safe_dump(frontmatter) + "---\n" + body)
    monkeypatch.setattr(routes, "_TRACE_ALLOWED_BASES", (tmp_path,))
    count = Mock(return_value=SimpleNamespace(count=2))
    monkeypatch.setattr("logos.api.routes._config.get_qdrant", lambda: SimpleNamespace(count=count))
    original = consent._read_compatibility_document
    reads = []

    def read_once():
        reads.append(True)
        raw = original()
        synthetic_custody.delete(ENTRY)
        return raw

    snapshot = consent.load_identity_snapshot()
    monkeypatch.setattr(consent, "_read_compatibility_document", read_once)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test"
    ) as client:
        response = await client.get("/api/consent/trace", params={"source": str(source)})
    assert response.status_code == 200
    payload = response.json()
    assert payload["exists"]
    assert payload["provenance"] == [CONTRACT]
    assert payload["contracts"][0]["id"] == CONTRACT
    assert payload["body_preview"] == "[redacted]"
    assert body not in response.text
    assert not snapshot.contains_predecessor(response.text)
    if labeled:
        assert payload["consent_label"] == [
            {"owner": PRINCIPAL, "readers": ["operator", PRINCIPAL]}
        ]
    assert payload["revocation_impact"]["contracts"] == [CONTRACT]
    assert count.call_args.kwargs["count_filter"].must[0].match.value == CONTRACT
    assert len(reads) == 1


@pytest.mark.parametrize("restriction", ["label", "registered", "broadcast", "public"])
async def test_trace_preview_uses_existing_filter_seams(
    restriction, local_api, monkeypatch, tmp_path
):
    from agents._governance import consent_reader

    app, prop, registry, notifications = local_api
    fm = {}
    body = "Synthetic public note."
    expected = body
    if restriction == "label":
        fm["consent_label"] = {
            "policies": [{"owner": PRINCIPAL, "readers": ["operator", PRINCIPAL]}]
        }
        expected = "[redacted]"
    elif restriction == "registered":
        principal = "synthetic-opaque-only-principal"
        monkeypatch.setattr(consent_reader, "REGISTERED_PRINCIPALS", frozenset({principal}))
        body = f"Notes about {principal}."
        expected = "Notes about someone."
    elif restriction == "broadcast":
        registry.create_contract(PRINCIPAL, frozenset({"document"}), contract_id=CONTRACT)
        body = f"Notes about {PRINCIPAL}."
        expected = "[redacted]"
    source = tmp_path / "synthetic-preview.md"
    source.write_text("---\n" + yaml.safe_dump(fm) + "---\n" + body)
    monkeypatch.setattr(routes, "_TRACE_ALLOWED_BASES", (tmp_path,))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test"
    ) as client:
        response = await client.get("/api/consent/trace", params={"source": str(source)})
    assert response.status_code == 200
    assert response.json()["body_preview"] == expected


@pytest.mark.parametrize("surface", ["briefing", "nudges"])
@pytest.mark.parametrize("refusal", ["malformed", "unavailable", "loader"])
async def test_public_refusal_is_explicitly_incomplete(
    surface, refusal, local_api, synthetic_custody, monkeypatch, caplog
):
    app, prop, registry, notifications = local_api
    monkeypatch.setattr(data, "is_publicly_visible", lambda: True)
    items = [{"action": OLD_PRINCIPAL, "detail": OLD_PRINCIPAL}]
    monkeypatch.setattr(
        data.cache, surface, {"action_items": items} if surface == "briefing" else items
    )
    if refusal == "malformed":
        synthetic_custody.put(ENTRY, b"{")
    elif refusal == "unavailable":
        synthetic_custody.delete(ENTRY)
    else:
        monkeypatch.setattr(data, "_load_consent_registry", lambda: None)
    caplog.set_level(logging.WARNING)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test"
    ) as client:
        response = await client.get(f"/api/{surface}")
    assert response.status_code == 503
    payload = response.json()
    assert (payload["action_items"] if surface == "briefing" else payload) == []
    assert response.headers["X-Consent-Result"] == "incomplete"
    assert response.headers["X-Consent-Reason"] == "custody_unavailable"
    assert response.headers["X-Consent-Remedy"] == "restore_identity_custody_and_retry"
    assert "incomplete" in caplog.text and "custody" in caplog.text
    assert OLD_PRINCIPAL not in response.text + caplog.text


@pytest.mark.parametrize("failure", ["read", "malformed"])
async def test_startup_audit_cause_is_safe_and_does_not_cache(
    failure, synthetic_custody, monkeypatch, tmp_path, caplog
):
    audit = tmp_path / "purge.log"
    audit.write_text("{")
    monkeypatch.setattr(routes, "_PURGE_AUDIT_PATH", audit)
    monkeypatch.setattr(revocation_wiring, "_propagator", None)
    original = Path.open

    def denied(path, *args, **kwargs):
        if path == audit:
            raise PermissionError(f"synthetic refusal {OLD_PRINCIPAL}")
        return original(path, *args, **kwargs)

    if failure == "read":
        monkeypatch.setattr(Path, "open", denied)
    app = FastAPI()
    app.include_router(routes.router)
    async with app.router.lifespan_context(app):
        assert revocation_wiring._propagator is None
    cause = "PermissionError" if failure == "read" else "JSONDecodeError"
    assert f"cause_class={cause}" in caplog.text
    assert "inspect the durable purge audit" in caplog.text
    assert OLD_PRINCIPAL not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


async def test_multistage_retry_retires_exactly_completed_obligations(local_api, monkeypatch):
    app, prop, registry, notifications = local_api
    ids = ("synthetic-grant-one", "synthetic-grant-two")
    for cid in ids:
        registry.create_contract(PRINCIPAL, frozenset({"audio"}), contract_id=cid)
    original = Path.rename
    persistence_broken = True
    handler_broken = True

    def denied(path, target):
        if persistence_broken and path.name == f"{ids[1]}.yaml":
            raise PermissionError("synthetic refusal")
        return original(path, target)

    def handler(cid):
        if handler_broken:
            raise OSError("synthetic refusal")
        return 1

    monkeypatch.setattr(Path, "rename", denied)
    prop.register_handler("synthetic", handler)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test"
    ) as client:
        first = await client.post(f"/api/consent/revoke/{PRINCIPAL}")
        assert first.status_code == 503
        assert first.json()["retry_contract_ids"] == list(ids)
        # Another audit obligation for the same principal must survive this retry.
        with routes._PURGE_AUDIT_PATH.open("a") as audit:
            audit.write(
                json.dumps(
                    {
                        "event": "purge_pending",
                        "person_id": PRINCIPAL,
                        "contract_ids": ["synthetic-unrelated-grant"],
                    }
                )
                + "\n"
            )
        handler_broken = False
        middle = await client.post(f"/api/consent/retry/{PRINCIPAL}")
        assert middle.status_code == 503
        assert middle.json()["retry_contract_ids"] == [ids[1]]
        pending = await asyncio.to_thread(prop.pending_purges, routes._PURGE_AUDIT_PATH)
        assert pending == {PRINCIPAL: (ids[1], "synthetic-unrelated-grant")}
        persistence_broken = False
        last = await client.post(f"/api/consent/retry/{PRINCIPAL}")
        assert last.status_code == 200 and last.json()["purge_complete"]
        assert await asyncio.to_thread(prop.pending_purges, routes._PURGE_AUDIT_PATH) == {
            PRINCIPAL: ("synthetic-unrelated-grant",)
        }
    completed = [
        row["contract_ids"]
        for row in map(json.loads, routes._PURGE_AUDIT_PATH.read_text().splitlines())
        if row["event"] == "purge_complete"
    ]
    assert completed == [[ids[0]], [ids[1]]]


@pytest.mark.parametrize("stage", ["pending", "complete"])
async def test_audit_write_failure_preserves_response_notification_and_retry(
    stage, local_api, monkeypatch, caplog
):
    app, prop, registry, notifications = local_api
    registry.create_contract(PRINCIPAL, frozenset({"audio"}), contract_id=CONTRACT)
    broken = True
    calls = []

    def handler(cid):
        calls.append(cid)
        if broken:
            raise OSError("synthetic refusal")
        return 1

    prop.register_handler("synthetic", handler)
    original = Path.open
    audit_broken = stage == "pending"

    def denied(path, *args, **kwargs):
        if audit_broken and path == routes._PURGE_AUDIT_PATH:
            raise PermissionError(f"synthetic refusal {OLD_PRINCIPAL}")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test"
    ) as client:
        response = await client.post(f"/api/consent/revoke/{PRINCIPAL}")
        if stage == "complete":
            broken = False
            audit_broken = True
            response = await client.post(f"/api/consent/retry/{PRINCIPAL}")
        assert response.status_code == 503
        payload = response.json()
        assert payload["contract_revoked"]
        assert payload["purge_complete"] == (stage == "complete")
        assert payload["failures"] == (["purge_failed"] if stage == "pending" else [])
        assert payload["audit_failures"] == [f"purge_{stage}_audit_unwritten"]
        assert payload["durable_record"]["written"] is False
        assert "retain this response" in payload["retry_instruction"]
        assert "Audit write failed" in notifications[-1][0][1]
        assert PRINCIPAL in app.state.pending_consent_revocations
        broken = False
        audit_broken = False
        retried = await client.post(f"/api/consent/retry/{PRINCIPAL}")
        assert retried.status_code == 200
        assert retried.json()["purge_complete"]
        assert retried.json()["audit_failures"] == []
        assert PRINCIPAL not in app.state.pending_consent_revocations
        assert await asyncio.to_thread(prop.pending_purges, routes._PURGE_AUDIT_PATH) == {}
    assert calls == [CONTRACT, CONTRACT]
    assert OLD_PRINCIPAL not in caplog.text + json.dumps(notifications)
