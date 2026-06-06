from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from logos.api.cache import cache
from logos.data.host_storage import (
    ActualHostWitness,
    HostStorageDevice,
    HostStorageFilesystem,
    HostStorageHost,
    HostStorageSnapshot,
    StorageDataRole,
    collect_host_storage,
)


@pytest.fixture
async def client():
    from logos.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _host() -> HostStorageHost:
    return HostStorageHost(
        host_id="hapax-appendix",
        evidence_host="hapax-appendix",
        evidence_machine_id="ffc36d1a0ca64320a3f1c9f1060292af",
        evidence_class="recent",
        observed_at="2026-06-06T08:50:33Z",
        recency_class="live",
        locality_class="cross_host_ssh",
        transport="ssh",
        anchor_verified=True,
        root_disk_serial="TPBF2510310070101576",
    )


def _storage() -> HostStorageSnapshot:
    fs = HostStorageFilesystem(
        target_host="hapax-appendix",
        device_serial="24511K802589",
        uuid="1e70ec1f-00db-4734-8885-3ecbdfa400e5",
        fstype="xfs",
        label="store",
        mountpoints=["/store"],
        partition_kernel_dev="/dev/nvme1n1p1",
        partuuid="cd852963-b7c8-4c1f-b001-7733832373cb",
    )
    witness = ActualHostWitness(
        source="logos_infra",
        evidence_host="hapax-appendix",
        evidence_machine_id="ffc36d1a0ca64320a3f1c9f1060292af",
        observed_at="2026-06-06T08:50:33Z",
        witness_age_s=2,
    )
    return HostStorageSnapshot(
        schema_version=1,
        generated_at="2026-06-06T08:50:40Z",
        hosts=[_host()],
        devices=[
            HostStorageDevice(
                target_host="hapax-appendix",
                serial="24511K802589",
                presence="present",
                model="WD_BLACK SN7100 1TB",
                kernel_dev="/dev/nvme1n1",
                size="931.5G",
                transport="nvme",
                by_id=["nvme-WD_BLACK_SN7100_1TB_24511K802589"],
                filesystems=[fs],
            )
        ],
        filesystems=[fs],
        data_roles=[
            StorageDataRole(
                store_id="minio-langfuse-live",
                surface="MinIO on 192.168.68.50",
                authority_class="runtime object store",
                retrieval_mode="object",
                current_placement="hapax-appendix:/store/llm-stack/runtime/minio.xfs",
                target_placement="appendix observability live store",
                data_authority_host="hapax-appendix",
                expected_host="hapax-appendix",
                container_running_host="hapax-appendix",
                actual_host_witness=witness,
                placement_state="aligned",
                quality_gate="SN7100 serial 24511K802589 verified",
            )
        ],
    )


class TestHostStorageRoutes:
    async def test_hosts_route_returns_host_qualified_cache(self, client, monkeypatch):
        monkeypatch.setattr("logos.api.routes.data.is_publicly_visible", lambda: False)
        cache.hosts = [_host()]
        resp = await client.get("/api/hosts")

        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["host_id"] == "hapax-appendix"
        assert data[0]["evidence_host"] == "hapax-appendix"
        assert data[0]["evidence_class"] == "recent"
        assert data[0]["observed_at"] == "2026-06-06T08:50:33Z"
        assert "x-cache-age" in resp.headers

    async def test_storage_route_public_mode_redacts_identity(self, client, monkeypatch):
        cache.host_storage = _storage()
        monkeypatch.setattr("logos.api.routes.data.is_publicly_visible", lambda: True)

        resp = await client.get("/api/infrastructure/storage")

        assert resp.status_code == 200
        body = json.dumps(resp.json())
        assert "24511K802589" not in body
        assert "nvme-WD_BLACK_SN7100" not in body
        assert "192.168.68.50" not in body
        assert "hapax-appendix" not in body
        assert "1e70ec1f-00db-4734-8885-3ecbdfa400e5" not in body


def _receipt(host: str, observed_at: str) -> dict:
    return {
        "schema_version": 1,
        "host_provenance": {
            "intent_host": host,
            "exec_host": "hapax-podium",
            "evidence_host": host,
            "transport": "ssh",
        },
        "evidence_witness": {
            "machine_id": "machine-" + host,
            "root_disk_serial": "root-" + host,
            "anchor_verified": True,
        },
        "hostname": host,
        "observed_at": observed_at,
        "recency_class": "live",
        "locality_class": "cross_host_ssh",
        "evidence_class": "recent",
        "collectors": {"lsblk": {"ran": True, "row_count": 1}},
        "devices": [
            {
                "presence": "present",
                "model": "WD_BLACK SN7100 1TB",
                "serial": "24511K802589",
                "kernel_dev": "/dev/nvme1n1",
                "size": "931.5G",
                "tran": "nvme",
                "by_id": ["nvme-WD_BLACK_SN7100_1TB_24511K802589"],
                "filesystems": [
                    {
                        "partition_kernel_dev": "/dev/nvme1n1p1",
                        "fstype": "xfs",
                        "label": "store",
                        "uuid": "1e70ec1f-00db-4734-8885-3ecbdfa400e5",
                        "partuuid": "cd852963-b7c8-4c1f-b001-7733832373cb",
                        "mountpoints": ["/store"],
                    }
                ],
            }
        ],
    }


def test_collect_host_storage_stale_witness_keeps_placement_unknown(tmp_path, monkeypatch):
    observed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    cache_dir = tmp_path / "receipts"
    cache_dir.mkdir()
    (cache_dir / "hapax-appendix.json").write_text(
        json.dumps(_receipt("hapax-appendix", observed_at))
    )
    registry = tmp_path / "data-role.md"
    registry.write_text(
        "\n".join(
            [
                "| store_id | surface | authority_class | retrieval_mode | current_placement | target_placement | backup_method | restore_method | retention_class | capacity_budget | quality_gate |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
                "| `minio-langfuse-live` | MinIO bucket `langfuse` | runtime object store | object | `hapax-appendix:/store/llm-stack/runtime/minio.xfs` | appendix observability live store | accepted | accepted | production | n/a | verified |",
            ]
        )
    )
    infra = tmp_path / "infra-snapshot.json"
    stale = (datetime.now(UTC) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    infra.write_text(
        json.dumps(
            {
                "evidence_host": "hapax-appendix",
                "machine_id": "machine-hapax-appendix",
                "observed_at": stale,
                "containers": [{"name": "minio", "service": "minio", "state": "running"}],
            }
        )
    )
    monkeypatch.setattr("logos.data.host_storage.CACHE_DIR", cache_dir)
    monkeypatch.setattr("logos.data.host_storage.DATA_ROLE_REGISTRY", registry)
    monkeypatch.setattr("logos.data.host_storage.INFRA_SNAPSHOT", infra)

    snapshot = collect_host_storage()

    assert snapshot.hosts[0].evidence_host == "hapax-appendix"
    assert snapshot.devices[0].target_host == "hapax-appendix"
    assert snapshot.data_roles[0].data_authority_host == "hapax-appendix"
    assert snapshot.data_roles[0].container_running_host == "hapax-appendix"
    assert snapshot.data_roles[0].placement_state == "unknown"


async def test_infrastructure_route_stamps_container_host_witness(client, tmp_path, monkeypatch):
    from logos.data.infrastructure import collect_docker

    monkeypatch.setattr("logos.api.routes.data.is_publicly_visible", lambda: False)
    snapshot = tmp_path / "infra-snapshot.json"
    observed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshot.write_text(
        json.dumps(
            {
                "evidence_host": "hapax-podium",
                "machine_id": "15c4e584aac74d048bcbe90fc35e6da3",
                "observed_at": observed_at,
                "containers": [{"name": "logos-api", "service": "logos", "state": "running"}],
            }
        )
    )
    monkeypatch.setattr("logos.data.infrastructure.INFRA_SNAPSHOT", snapshot)
    cache.containers = await collect_docker()

    resp = await client.get("/api/infrastructure")

    data = resp.json()
    assert data["containers"][0]["evidence_host"] == "hapax-podium"
    assert data["containers"][0]["actual_host_witness"]["source"] == "logos_infra"
