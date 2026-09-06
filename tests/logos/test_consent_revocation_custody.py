"""Exercise the operator's actual ASGI response and retained purge retry."""

import asyncio
import json
import logging
import threading

import httpx
import pytest
from fastapi import FastAPI

from logos.api.routes import consent as routes
from shared.governance import consent
from shared.governance.revocation import RevocationPropagator
from tests.shared.synthetic_custody import CONTRACT, OLD_PRINCIPAL, PRINCIPAL


@pytest.fixture
def api(synthetic_custody, monkeypatch, tmp_path):
    registry = consent.ConsentRegistry(_contracts_dir=tmp_path / "contracts")
    registry.create_contract(PRINCIPAL, frozenset({"audio"}), contract_id=CONTRACT)
    prop = RevocationPropagator(registry)
    monkeypatch.setattr(routes, "get_revocation_propagator", lambda: prop)
    monkeypatch.setattr(routes, "_PURGE_AUDIT_PATH", tmp_path / "stream-archive" / "purge.log")
    notifications = []
    monkeypatch.setattr(routes, "send_notification", lambda *a, **kw: notifications.append((a, kw)))
    app = FastAPI()
    app.state.notifications = notifications
    app.include_router(routes.router)
    return app, prop, registry


async def test_revocation_route_keeps_failure_and_retries(api, caplog):
    app, prop, registry = api
    calls = []
    broken = True

    def completed(contract_id):
        calls.append("completed")
        return 2

    def flaky(contract_id):
        calls.append("flaky")
        if broken:
            raise OSError(f"synthetic private path {OLD_PRINCIPAL}")
        return 3

    prop.register_handler("completed", completed)
    prop.register_handler("flaky", flaky)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test"
    ) as client:
        response = await client.post(f"/api/consent/revoke/{OLD_PRINCIPAL}")
        assert response.status_code == 503
        failed = response.json()
        assert failed["contract_revoked"] is True
        assert failed["purge_complete"] is False
        assert failed["failures"] == ["purge_failed"]
        assert failed["retry_contract_ids"] == [CONTRACT]
        assert failed["prior_purge_results"] == []
        assert failed["total_purged"] == 2
        assert failed["purge_results"][1]["failures"] == ["purge_failed"]
        assert failed["purge_results"][1]["purge_complete"] is False
        assert failed["durable_record"] == {
            "event": "purge_pending",
            "audit": str(routes._PURGE_AUDIT_PATH),
        }
        assert "current process only" in failed["retry_instruction"]
        assert f"POST /api/consent/retry/{PRINCIPAL}" in failed["retry_instruction"]
        rows = [json.loads(line) for line in routes._PURGE_AUDIT_PATH.read_text().splitlines()]
        assert rows[-1]["event"] == "purge_pending"
        assert rows[-1]["person_id"] == PRINCIPAL
        assert rows[-1]["contract_ids"] == [CONTRACT]
        assert await asyncio.to_thread(prop.pending_purges, routes._PURGE_AUDIT_PATH) == {
            PRINCIPAL: (CONTRACT,)
        }
        message = app.state.notifications[-1][0][1]
        assert PRINCIPAL in message and CONTRACT in message
        assert f"POST /api/consent/retry/{PRINCIPAL}" in message
        assert "purge_pending" in message
        assert not await asyncio.to_thread(registry.contract_check, PRINCIPAL, "audio")
        repeated = await client.post(f"/api/consent/revoke/{PRINCIPAL}")
        assert repeated.status_code == 503
        assert repeated.json()["failures"] == ["purge_failed"]
        broken = False
        retried = await client.post(f"/api/consent/retry/{PRINCIPAL}")
        assert retried.status_code == 200
        result = retried.json()
        assert result["purge_complete"] is True
        assert result["failures"] == []
        assert result["retry_contract_ids"] == []
        assert result["prior_purge_results"] == failed["purge_results"]
        assert result["total_purged"] == 5
        assert calls == ["completed", "flaky", "flaky"]
        assert await asyncio.to_thread(prop.pending_purges, routes._PURGE_AUDIT_PATH) == {}
        assert (
            json.loads(routes._PURGE_AUDIT_PATH.read_text().splitlines()[-1])["event"]
            == "purge_complete"
        )
        assert (await client.post(f"/api/consent/retry/{PRINCIPAL}")).status_code == 404
    assert "purge_handler_failed: purge_failed" in caplog.text
    assert OLD_PRINCIPAL not in caplog.text
    assert OLD_PRINCIPAL not in json.dumps(result)
    assert all(record.exc_info is None for record in caplog.records)
    snapshot = consent.load_identity_snapshot()
    assert not snapshot.contains_predecessor(routes._PURGE_AUDIT_PATH.read_text())
    assert not snapshot.contains_predecessor(repr(app.state.notifications))


async def test_fresh_app_warns_and_points_retry_to_durable_residue(api, monkeypatch, caplog):
    app, prop, registry = api
    calls = []

    def broken(contract_id):
        calls.append(contract_id)
        raise OSError("synthetic failure")

    prop.register_handler("broken", broken)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test"
    ) as client:
        assert (await client.post(f"/api/consent/revoke/{OLD_PRINCIPAL}")).status_code == 503

    # Reload both registry and propagator; the new app has no retained report.
    restored_registry = consent.ConsentRegistry(_contracts_dir=registry._contracts_dir)
    restored_registry.load()
    restored_prop = RevocationPropagator(restored_registry)
    restored_prop.register_handler("broken", broken)
    monkeypatch.setattr(routes, "get_revocation_propagator", lambda: restored_prop)
    fresh_app = FastAPI()
    fresh_app.include_router(routes.router)
    caplog.clear()
    caplog.set_level(logging.WARNING)
    async with fresh_app.router.lifespan_context(fresh_app):
        warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
        assert warnings
        assert "purge_pending" in caplog.text
        assert PRINCIPAL in caplog.text
        assert f"POST /api/consent/retry/{PRINCIPAL}" in caplog.text
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=fresh_app), base_url="http://synthetic.test"
        ) as client:
            response = await client.post(f"/api/consent/retry/{PRINCIPAL}")
            assert response.status_code == 404
            assert response.json()["durable_record"] == {
                "event": "purge_pending",
                "audit": str(routes._PURGE_AUDIT_PATH),
            }
            assert "No report retained in this process" in response.json()["retry_instruction"]
    assert calls == [CONTRACT]  # Startup and unavailable retry never execute a purge.
    assert await asyncio.to_thread(restored_prop.pending_purges, routes._PURGE_AUDIT_PATH) == {
        PRINCIPAL: (CONTRACT,)
    }
    assert not consent.load_identity_snapshot().contains_predecessor(caplog.text)


async def test_completed_retry_leaves_no_startup_residue(api, monkeypatch, caplog):
    app, prop, registry = api
    broken = True

    def handler(contract_id):
        if broken:
            raise OSError("synthetic failure")
        return 1

    prop.register_handler("synthetic", handler)
    # An ordinary archive audit entry shares this existing file and is preserved.
    routes._PURGE_AUDIT_PATH.parent.mkdir(parents=True)
    ordinary = '{"ts": "synthetic", "condition_id": "synthetic", "mode": "dry-run"}\n'
    routes._PURGE_AUDIT_PATH.write_text(ordinary)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test"
    ) as client:
        assert (await client.post(f"/api/consent/revoke/{PRINCIPAL}")).status_code == 503
        broken = False
        assert (await client.post(f"/api/consent/retry/{PRINCIPAL}")).status_code == 200
    fresh_prop = RevocationPropagator(
        consent.ConsentRegistry(_contracts_dir=registry._contracts_dir)
    )
    monkeypatch.setattr(routes, "get_revocation_propagator", lambda: fresh_prop)
    fresh_app = FastAPI()
    fresh_app.include_router(routes.router)
    caplog.clear()
    async with fresh_app.router.lifespan_context(fresh_app):
        assert "purge_pending" not in caplog.text
    assert routes._PURGE_AUDIT_PATH.read_text().startswith(ordinary)
    assert await asyncio.to_thread(fresh_prop.pending_purges, routes._PURGE_AUDIT_PATH) == {}


@pytest.mark.parametrize("endpoint", ["create", "revoke", "contracts", "trace"])
async def test_consent_routes_use_one_worker_snapshot(endpoint, api, monkeypatch):
    import logos._governance as mirror

    app, prop, registry = api
    monkeypatch.setattr(mirror, "load_contracts", lambda: registry)
    monkeypatch.setattr("logos.api.deps.stream_redaction.is_publicly_visible", lambda: False)
    main_thread = threading.get_ident()
    original = consent._read_compatibility_document
    reads = []

    def checked_read():
        reads.append(threading.get_ident())
        assert reads[-1] != main_thread
        return original()

    monkeypatch.setattr(consent, "_read_compatibility_document", checked_read)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test"
    ) as client:
        if endpoint == "create":
            response = await client.post(
                "/api/consent/create", json={"person_id": OLD_PRINCIPAL, "scope": ["audio"]}
            )
        elif endpoint == "revoke":
            response = await client.post(f"/api/consent/revoke/{PRINCIPAL}")
        elif endpoint == "trace":
            response = await client.get(
                "/api/consent/trace", params={"source": "synthetic-nonexistent"}
            )
        else:
            response = await client.get("/api/consent/contracts")
        assert response.status_code == 200
        assert len(reads) == 1
