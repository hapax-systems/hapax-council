"""Exercise the operator's actual ASGI response and retained purge retry."""

import asyncio
import json
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
    monkeypatch.setattr(routes, "_pending_revocations", {})
    app = FastAPI()
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
        assert (await client.post(f"/api/consent/retry/{PRINCIPAL}")).status_code == 404
    assert "purge_handler_failed: purge_failed" in caplog.text
    assert OLD_PRINCIPAL not in caplog.text
    assert OLD_PRINCIPAL not in json.dumps(result)
    assert all(record.exc_info is None for record in caplog.records)


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
