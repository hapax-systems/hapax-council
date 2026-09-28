"""Live public and revocation composition with exclusively synthetic custody."""

import asyncio
import json
import logging
import threading
from contextvars import ContextVar
from pathlib import Path

import httpx
import pytest
import yaml
from agentgov.carrier import CarrierFact, CarrierRegistry
from agentgov.consent_label import ConsentLabel
from agentgov.labeled import Labeled

import logos._governance as mirror
from agents._governance import revocation_wiring
from logos.api.routes import consent as routes
from logos.api.routes import data
from shared.governance import consent
from tests.shared.synthetic_custody import (
    CONTRACT,
    ENTRY,
    OLD_PRINCIPAL,
    PRINCIPAL,
    document,
)


@pytest.fixture
def public_data(synthetic_custody, monkeypatch, tmp_path):
    directory = tmp_path / "contracts"
    directory.mkdir()
    monkeypatch.setattr(mirror, "_CONTRACTS_DIR", directory)
    monkeypatch.setattr(data, "is_publicly_visible", lambda: True)
    return directory


@pytest.mark.parametrize("surface", ["briefing", "nudges"])
@pytest.mark.parametrize("stored_party", [OLD_PRINCIPAL, PRINCIPAL])
async def test_public_surfaces_recognize_both_custody_spellings(
    surface, stored_party, public_data, synthetic_custody, monkeypatch, caplog
):
    (public_data / "contract.yaml").write_text(
        yaml.safe_dump({"id": CONTRACT, "parties": ["operator", stored_party], "scope": ["audio"]})
    )
    granted = "synthetic-broadcast-subject"
    (public_data / "granted.yaml").write_text(
        yaml.safe_dump(
            {"id": "synthetic-granted", "parties": ["operator", granted], "scope": ["broadcast"]}
        )
    )
    snapshot = consent.load_identity_snapshot()
    doc = document()
    doc["principals"]["syn"] = PRINCIPAL
    doc["inventory"].append("syn")
    synthetic_custody.put(ENTRY, json.dumps(doc).encode())
    fields = (
        ("action", "reason", "command")
        if surface == "briefing"
        else ("detail", "title", "suggested_action")
    )
    denied = [
        {field: f"Notes about {spelling}."}
        for spelling in (OLD_PRINCIPAL, PRINCIPAL)
        for field in fields
    ]
    kept = [{fields[0]: f"Notes about {granted}."}, {fields[0]: "A synapse is mentioned."}]
    payload = {"action_items": denied + kept} if surface == "briefing" else denied + kept
    monkeypatch.setattr(data.cache, surface, payload)
    caplog.set_level(logging.INFO)
    response = await getattr(data, f"get_{surface}")()
    result = json.loads(response.body)
    assert (result["action_items"] if surface == "briefing" else result) == kept
    assert not snapshot.contains_predecessor(response.body.decode())
    assert not snapshot.contains_predecessor(caplog.text)


@pytest.mark.parametrize("surface", ["briefing", "nudges"])
async def test_public_consent_operation_keeps_loop_responsive(surface, public_data, monkeypatch):
    items = [{"action": f"Notes about {PRINCIPAL}.", "detail": f"Notes about {PRINCIPAL}."}] * 3
    monkeypatch.setattr(
        data.cache, surface, {"action_items": items} if surface == "briefing" else items
    )
    read_started = threading.Event()
    loop_progressed = threading.Event()
    context = ContextVar("synthetic_public_context", default=None)
    token = context.set("synthetic-operation")
    loop_thread = threading.get_ident()
    reads = []
    original = consent._read_compatibility_document

    def delayed_read():
        read_started.set()
        progressed = loop_progressed.wait(0.5)
        reads.append((threading.get_ident(), context.get(), progressed))
        return original()

    monkeypatch.setattr(consent, "_read_compatibility_document", delayed_read)

    async def concurrent_work():
        while not read_started.is_set():
            await asyncio.sleep(0.001)
        loop_progressed.set()

    try:
        response, _ = await asyncio.gather(getattr(data, f"get_{surface}")(), concurrent_work())
    finally:
        context.reset(token)
    assert len(reads) == 1
    assert reads[0][0] != loop_thread
    assert reads[0][1:] == ("synthetic-operation", True)
    result = json.loads(response.body)
    assert (result["action_items"] if surface == "briefing" else result) == []


@pytest.mark.parametrize("surface", ["briefing", "nudges"])
async def test_public_filter_pins_snapshot_for_load_recognition_and_checks(
    surface, public_data, synthetic_custody, monkeypatch
):
    (public_data / "contract.yaml").write_text(
        yaml.safe_dump({"id": CONTRACT, "parties": ["operator", PRINCIPAL], "scope": ["broadcast"]})
    )
    item = {"action": OLD_PRINCIPAL, "detail": OLD_PRINCIPAL}
    monkeypatch.setattr(
        data.cache, surface, {"action_items": [item]} if surface == "briefing" else [item]
    )
    calls = []
    original = consent._read_compatibility_document

    def replace_after_read():
        calls.append(threading.get_ident())
        raw = original()
        synthetic_custody.delete(ENTRY)
        return raw

    monkeypatch.setattr(consent, "_read_compatibility_document", replace_after_read)
    response = await getattr(data, f"get_{surface}")()
    result = json.loads(response.body)
    assert (result["action_items"] if surface == "briefing" else result) == [item]
    assert len(calls) == 1


@pytest.fixture
def composed_api(synthetic_custody, monkeypatch, tmp_path):
    from fastapi import FastAPI

    from logos.engine import reactive_rules

    directory = tmp_path / "contracts"
    directory.mkdir()
    monkeypatch.setattr(consent, "_CONTRACTS_DIR", directory)
    monkeypatch.setattr(mirror, "_CONTRACTS_DIR", directory)
    monkeypatch.setattr(revocation_wiring, "_propagator", None)
    monkeypatch.setattr(routes, "_PURGE_AUDIT_PATH", tmp_path / "archive" / "purge.log")
    monkeypatch.setattr(routes, "send_notification", lambda *args, **kwargs: None)
    carrier = CarrierRegistry()
    carrier.register("synthetic-agent", capacity=5)
    monkeypatch.setattr(reactive_rules, "get_carrier_registry", lambda: carrier)
    app = FastAPI()
    app.include_router(routes.router)
    return app, directory, carrier


@pytest.mark.parametrize("purge_fails", [False, True])
async def test_startup_then_route_grant_revoke_refreshes_under_lock(
    composed_api, purge_fails, monkeypatch
):
    app, directory, carrier = composed_api
    async with app.router.lifespan_context(app):
        assert revocation_wiring._propagator is None
        prop = await asyncio.to_thread(revocation_wiring.get_revocation_propagator)
        assert not prop._consent_registry.active_contracts
        original = type(prop._consent_registry).load
        refresh_locks = []

        def checked_refresh(registry, *args, **kwargs):
            refresh_locks.append(routes._revocation_lock.locked())
            return original(registry, *args, **kwargs)

        monkeypatch.setattr(type(prop._consent_registry), "load", checked_refresh)
        broken = purge_fails

        def flaky(contract_id):
            if broken:
                raise OSError("synthetic refusal")
            return 1

        if purge_fails:
            prop.register_handler("synthetic-flaky", flaky)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test"
        ) as client:
            created = await client.post(
                "/api/consent/create", json={"person_id": PRINCIPAL, "scope": ["audio"]}
            )
            assert created.status_code == 200
            cid = created.json()["contract_id"]
            carrier.offer(
                "synthetic-agent",
                CarrierFact(
                    Labeled("synthetic-data", ConsentLabel.bottom(), frozenset({cid})),
                    "synthetic-domain",
                ),
            )
            response = await client.post(f"/api/consent/revoke/{PRINCIPAL}")
            assert response.status_code == (503 if purge_fails else 200)
            assert response.json()["contract_revoked"]
            assert response.json()["total_purged"] == 1
            assert not carrier.facts("synthetic-agent")
            assert not (directory / f"{cid}.yaml").exists()
            assert refresh_locks == [True]
            if purge_fails:
                broken = False
                retried = await client.post(f"/api/consent/retry/{PRINCIPAL}")
                assert retried.status_code == 200
                assert retried.json()["purge_complete"]
                assert refresh_locks == [True, True]


@pytest.mark.parametrize("failed_index", [0, 1])
async def test_partial_persistence_retains_completed_purges_and_pending_obligations(
    composed_api, failed_index, monkeypatch, caplog
):
    app, directory, carrier = composed_api
    ids = ("synthetic-contract-1", "synthetic-contract-2")
    registry = consent.ConsentRegistry(_contracts_dir=directory)
    for cid in ids:
        registry.create_contract(PRINCIPAL, frozenset({"audio"}), contract_id=cid)
        carrier.offer(
            "synthetic-agent",
            CarrierFact(Labeled(cid, ConsentLabel.bottom(), frozenset({cid})), "synthetic-domain"),
        )
    original = Path.rename
    broken = True

    def denied_second(path, target):
        if broken and path.name == f"{ids[failed_index]}.yaml":
            raise PermissionError(f"synthetic private path: {OLD_PRINCIPAL}")
        return original(path, target)

    monkeypatch.setattr(Path, "rename", denied_second)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test"
        ) as client:
            failed = await client.post(f"/api/consent/revoke/{PRINCIPAL}")
            assert failed.status_code == 503
            report = failed.json()
            assert report["contract_revoked"] == bool(failed_index)
            assert report["contract_id"] == ",".join(ids[:failed_index])
            assert report["total_purged"] == failed_index
            assert report["retry_contract_ids"] == list(ids[failed_index:])
            assert report["retry_revocation_ids"] == list(ids[failed_index:])
            prop = revocation_wiring._propagator
            assert (
                tuple(c.id for c in prop._consent_registry.active_contracts) == ids[failed_index:]
            )
            assert len(carrier.facts("synthetic-agent")) == len(ids) - failed_index
            assert sorted(p.stem for p in directory.glob("*.yaml")) == list(ids[failed_index:])
            pending = await asyncio.to_thread(prop.pending_purges, routes._PURGE_AUDIT_PATH)
            assert pending == {PRINCIPAL: ids[failed_index:]}
            repeated = await client.post(f"/api/consent/revoke/{PRINCIPAL}")
            assert repeated.status_code == 503
            assert repeated.json()["retry_contract_ids"] == list(ids[failed_index:])
            assert repeated.json()["total_purged"] == failed_index
            broken = False
            retried = await client.post(f"/api/consent/retry/{PRINCIPAL}")
            assert retried.status_code == 200
            assert retried.json()["purge_complete"]
            assert retried.json()["total_purged"] == len(ids)
            assert not carrier.facts("synthetic-agent")
            assert not list(directory.glob("*.yaml"))
            assert await asyncio.to_thread(prop.pending_purges, routes._PURGE_AUDIT_PATH) == {}
    snapshot = consent.load_identity_snapshot()
    assert not snapshot.contains_predecessor(caplog.text)
    assert not snapshot.contains_predecessor(routes._PURGE_AUDIT_PATH.read_text())
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize("intermediate", ["repeated_revoke", "file_already_moved"])
async def test_pending_persistence_becomes_a_purge_obligation(
    composed_api, intermediate, monkeypatch
):
    app, directory, carrier = composed_api
    registry = consent.ConsentRegistry(_contracts_dir=directory)
    registry.create_contract(PRINCIPAL, frozenset({"audio"}), contract_id=CONTRACT)
    carrier.offer(
        "synthetic-agent",
        CarrierFact(
            Labeled("synthetic-data", ConsentLabel.bottom(), frozenset({CONTRACT})),
            "synthetic-domain",
        ),
    )
    original = Path.rename
    persistence_broken = True
    handler_broken = True
    calls = []

    def denied_move(path, target):
        if persistence_broken and path.name == f"{CONTRACT}.yaml":
            raise PermissionError("synthetic refusal")
        return original(path, target)

    def flaky(contract_id):
        calls.append(contract_id)
        if handler_broken:
            raise OSError("synthetic refusal")
        return 1

    monkeypatch.setattr(Path, "rename", denied_move)
    async with app.router.lifespan_context(app):
        assert revocation_wiring._propagator is None
        prop = await asyncio.to_thread(revocation_wiring.get_revocation_propagator)
        prop.register_handler("synthetic-flaky", flaky)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test"
        ) as client:
            assert (await client.post(f"/api/consent/revoke/{PRINCIPAL}")).status_code == 503
            assert not calls
            persistence_broken = False
            if intermediate == "repeated_revoke":
                repeated = await client.post(f"/api/consent/revoke/{PRINCIPAL}")
                assert repeated.status_code == 503
                assert repeated.json()["retry_revocation_ids"] == []
                assert repeated.json()["retry_contract_ids"] == [CONTRACT]
                assert calls == [CONTRACT]
            else:
                (directory / f"{CONTRACT}.yaml").rename(directory / "revoked" / "synthetic.yaml")
            handler_broken = False
            retried = await client.post(f"/api/consent/retry/{PRINCIPAL}")
            assert retried.status_code == 200
            assert retried.json()["purge_complete"]
            assert retried.json()["total_purged"] == 2
            assert calls == [CONTRACT] * (2 if intermediate == "repeated_revoke" else 1)
            assert not carrier.facts("synthetic-agent")
            assert await asyncio.to_thread(prop.pending_purges, routes._PURGE_AUDIT_PATH) == {}
