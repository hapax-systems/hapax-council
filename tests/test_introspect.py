"""Tests for introspect — schemas, collectors, formatter.

All I/O is mocked. No real subprocess calls, HTTP requests, or filesystem access.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agents.introspect import (
    ContainerInfo,
    DiskInfo,
    GpuInfo,
    InfrastructureManifest,
    LiteLLMRoute,
    OllamaModel,
    QdrantCollection,
    SystemdUnit,
    collect_disk,
    collect_docker,
    collect_gpu,
    collect_listening_ports,
    collect_litellm_routes,
    collect_ollama,
    collect_pass_entries,
    collect_profile_files,
    collect_qdrant,
    collect_systemd,
    format_summary,
)

# ── Schema tests ─────────────────────────────────────────────────────────────


class TestContainerInfo:
    def test_required_fields(self):
        c = ContainerInfo(
            name="ollama",
            service="ollama",
            image="ollama/ollama",
            state="running",
            health="healthy",
        )
        assert c.name == "ollama"
        assert c.ports == []

    def test_with_ports(self):
        c = ContainerInfo(
            name="qdrant",
            service="qdrant",
            image="qdrant/qdrant",
            state="running",
            health="healthy",
            ports=["127.0.0.1:6333->6333/tcp"],
        )
        assert len(c.ports) == 1


class TestSystemdUnit:
    def test_required_fields(self):
        u = SystemdUnit(
            name="rag-ingest.service", type="service", active="active", enabled="enabled"
        )
        assert u.description == ""

    def test_with_description(self):
        u = SystemdUnit(
            name="daily-briefing.timer",
            type="timer",
            active="active",
            enabled="enabled",
            description="Daily system briefing",
        )
        assert u.description == "Daily system briefing"


class TestQdrantCollection:
    def test_defaults(self):
        c = QdrantCollection(name="documents")
        assert c.points_count == 0
        assert c.vectors_size == 768
        assert c.distance == "Cosine"

    def test_with_data(self):
        c = QdrantCollection(
            name="profile-facts", points_count=1500, vectors_size=768, distance="Cosine"
        )
        assert c.points_count == 1500


class TestOllamaModel:
    def test_defaults(self):
        m = OllamaModel(name="qwen2.5-coder:32b")
        assert m.size_bytes == 0
        assert m.modified_at == ""

    def test_with_data(self):
        m = OllamaModel(
            name="nomic-embed-text", size_bytes=274_000_000, modified_at="2026-01-15T10:00:00Z"
        )
        assert m.size_bytes == 274_000_000


class TestGpuInfo:
    def test_defaults(self):
        g = GpuInfo()
        assert g.name == ""
        assert g.vram_total_mb == 0
        assert g.loaded_models == []

    def test_with_data(self):
        g = GpuInfo(
            name="NVIDIA GeForce RTX 3090",
            driver="565.57.01",
            vram_total_mb=24576,
            vram_used_mb=4200,
            vram_free_mb=20376,
            temperature_c=42,
            loaded_models=["qwen2.5-coder:32b"],
        )
        assert g.vram_free_mb == 20376
        assert len(g.loaded_models) == 1


class TestLiteLLMRoute:
    def test_minimal(self):
        r = LiteLLMRoute(model_name="claude-opus")
        assert r.litellm_params_model == ""

    def test_with_params(self):
        r = LiteLLMRoute(model_name="claude-opus", litellm_params_model="anthropic/claude-opus-4")
        assert "anthropic" in r.litellm_params_model


class TestDiskInfo:
    def test_defaults(self):
        d = DiskInfo(mount="/home")
        assert d.use_percent == 0
        assert d.size == ""

    def test_with_data(self):
        d = DiskInfo(mount="/home", size="500G", used="200G", available="300G", use_percent=40)
        assert d.use_percent == 40


class TestInfrastructureManifest:
    def test_minimal(self):
        m = InfrastructureManifest(timestamp="2026-02-28T12:00:00Z", hostname="testhost")
        assert m.containers == []
        assert m.gpu is None
        assert m.pass_entries == []

    def test_json_round_trip(self):
        m = InfrastructureManifest(
            timestamp="2026-02-28T12:00:00Z",
            hostname="testhost",
            os_info="Linux 6.18.7",
            docker_version="27.5.0",
            containers=[
                ContainerInfo(
                    name="ollama",
                    service="ollama",
                    image="ollama/ollama",
                    state="running",
                    health="healthy",
                ),
            ],
            qdrant_collections=[
                QdrantCollection(name="documents", points_count=100),
            ],
            gpu=GpuInfo(name="RTX 3090", vram_total_mb=24576),
        )
        json_str = m.model_dump_json()
        restored = InfrastructureManifest.model_validate_json(json_str)
        assert restored.hostname == "testhost"
        assert len(restored.containers) == 1
        assert restored.gpu is not None
        assert restored.gpu.name == "RTX 3090"


# ── Collector tests ──────────────────────────────────────────────────────────


class TestCollectDocker:
    @pytest.mark.asyncio
    async def test_success(self):
        ndjson = (
            '{"Name":"ollama","Service":"ollama","Image":"ollama/ollama","State":"running","Health":"healthy","Publishers":[{"URL":"127.0.0.1","TargetPort":11434,"PublishedPort":11434,"Protocol":"tcp"}]}\n'
            '{"Name":"qdrant","Service":"qdrant","Image":"qdrant/qdrant","State":"running","Health":"healthy","Publishers":[]}\n'
        )

        async def mock_run_cmd(cmd):
            if "info" in cmd:
                return (0, "27.5.0", "")
            if "ps" in cmd:
                return (0, ndjson, "")
            return (1, "", "")

        with patch("agents.introspect.run_cmd", side_effect=mock_run_cmd):
            version, containers = await collect_docker()

        assert version == "27.5.0"
        assert len(containers) == 2
        assert containers[0].name == "ollama"
        assert len(containers[0].ports) == 1
        assert "11434" in containers[0].ports[0]

    @pytest.mark.asyncio
    async def test_docker_down(self):
        async def mock_run_cmd(cmd):
            return (1, "", "Cannot connect to Docker daemon")

        with patch("agents.introspect.run_cmd", side_effect=mock_run_cmd):
            version, containers = await collect_docker()

        assert version == ""
        assert containers == []

    @pytest.mark.asyncio
    async def test_malformed_json_lines_skipped(self):
        ndjson = '{"Name":"ok","Service":"ok","Image":"i","State":"running","Health":"","Publishers":[]}\nnot-json\n'

        async def mock_run_cmd(cmd):
            if "info" in cmd:
                return (0, "27.5.0", "")
            return (0, ndjson, "")

        with patch("agents.introspect.run_cmd", side_effect=mock_run_cmd):
            version, containers = await collect_docker()

        assert len(containers) == 1


class TestCollectSystemd:
    @pytest.mark.asyncio
    async def test_success(self):
        service_output = "rag-ingest.service loaded active running RAG ingestion\n"
        timer_output = "daily-briefing.timer loaded active waiting Daily briefing\n"

        call_count = {"n": 0}

        async def mock_run_cmd(cmd):
            call_count["n"] += 1
            cmd_str = " ".join(cmd)
            if "list-units" in cmd_str and "service" in cmd_str:
                return (0, service_output, "")
            if "list-units" in cmd_str and "timer" in cmd_str:
                return (0, timer_output, "")
            if "is-enabled" in cmd_str:
                return (0, "enabled", "")
            if "show" in cmd_str:
                return (0, "Some description", "")
            return (1, "", "")

        with patch("agents.introspect.run_cmd", side_effect=mock_run_cmd):
            services, timers = await collect_systemd()

        assert len(services) == 1
        assert services[0].name == "rag-ingest.service"
        assert services[0].active == "active"
        assert services[0].enabled == "enabled"
        assert len(timers) == 1
        assert timers[0].name == "daily-briefing.timer"

    @pytest.mark.asyncio
    async def test_systemctl_failure(self):
        async def mock_run_cmd(cmd):
            return (1, "", "")

        with patch("agents.introspect.run_cmd", side_effect=mock_run_cmd):
            services, timers = await collect_systemd()

        assert services == []
        assert timers == []


class TestCollectQdrant:
    @pytest.mark.asyncio
    async def test_success(self):
        collections_resp = json.dumps(
            {"result": {"collections": [{"name": "documents"}, {"name": "profile-facts"}]}}
        )
        doc_detail = json.dumps(
            {
                "result": {
                    "points_count": 150,
                    "config": {"params": {"vectors": {"size": 768, "distance": "Cosine"}}},
                }
            }
        )
        samples_detail = json.dumps(
            {
                "result": {
                    "points_count": 42,
                    "config": {"params": {"vectors": {"size": 768, "distance": "Cosine"}}},
                }
            }
        )

        async def mock_http_get(url, **kwargs):
            if url.endswith("/collections"):
                return (200, collections_resp)
            if "documents" in url:
                return (200, doc_detail)
            if "profile-facts" in url:
                return (200, samples_detail)
            return (404, "")

        with patch("agents.introspect.http_get", side_effect=mock_http_get):
            collections = await collect_qdrant()

        assert len(collections) == 2
        assert collections[0].name == "documents"
        assert collections[0].points_count == 150
        assert collections[1].name == "profile-facts"
        assert collections[1].points_count == 42

    @pytest.mark.asyncio
    async def test_qdrant_down(self):
        async def mock_http_get(url, **kwargs):
            return (0, "")

        with patch("agents.introspect.http_get", side_effect=mock_http_get):
            collections = await collect_qdrant()

        assert collections == []

    @pytest.mark.asyncio
    async def test_detail_failure_skips_collection(self):
        """When detail fetch returns non-200, that collection is skipped."""
        collections_resp = json.dumps({"result": {"collections": [{"name": "documents"}]}})

        async def mock_http_get(url, **kwargs):
            if url.endswith("/collections"):
                return (200, collections_resp)
            return (500, "error")

        with patch("agents.introspect.http_get", side_effect=mock_http_get):
            collections = await collect_qdrant()

        assert len(collections) == 0

    @pytest.mark.asyncio
    async def test_detail_malformed_json_returns_defaults(self):
        """When detail returns 200 but malformed JSON body, collection gets defaults."""
        collections_resp = json.dumps({"result": {"collections": [{"name": "documents"}]}})

        async def mock_http_get(url, **kwargs):
            if url.endswith("/collections"):
                return (200, collections_resp)
            return (200, "not-json")

        with patch("agents.introspect.http_get", side_effect=mock_http_get):
            collections = await collect_qdrant()

        assert len(collections) == 1
        assert collections[0].name == "documents"
        assert collections[0].points_count == 0


class TestCollectOllama:
    @pytest.mark.asyncio
    async def test_success(self):
        resp = json.dumps(
            {
                "models": [
                    {
                        "name": "qwen2.5-coder:32b",
                        "size": 20_000_000_000,
                        "modified_at": "2026-01-01T00:00:00Z",
                    },
                    {
                        "name": "nomic-embed-text",
                        "size": 274_000_000,
                        "modified_at": "2026-01-01T00:00:00Z",
                    },
                ]
            }
        )

        async def mock_http_get(url, **kwargs):
            return (200, resp)

        with patch("agents.introspect.http_get", side_effect=mock_http_get):
            models = await collect_ollama()

        assert len(models) == 2
        assert models[0].name == "qwen2.5-coder:32b"

    @pytest.mark.asyncio
    async def test_ollama_down(self):
        async def mock_http_get(url, **kwargs):
            return (0, "")

        with patch("agents.introspect.http_get", side_effect=mock_http_get):
            models = await collect_ollama()

        assert models == []


class TestCollectGpu:
    @pytest.mark.asyncio
    async def test_success(self):
        nvidia_output = "NVIDIA GeForce RTX 3090, 565.57.01, 24576, 4200, 20376, 42"
        ollama_ps = json.dumps({"models": [{"name": "qwen2.5-coder:32b"}]})

        async def mock_run_cmd(cmd):
            return (0, nvidia_output, "")

        async def mock_http_get(url, **kwargs):
            return (200, ollama_ps)

        with (
            patch("agents.introspect.run_cmd", side_effect=mock_run_cmd),
            patch("agents.introspect.http_get", side_effect=mock_http_get),
        ):
            gpu = await collect_gpu()

        assert gpu is not None
        assert gpu.name == "NVIDIA GeForce RTX 3090"
        assert gpu.vram_total_mb == 24576
        assert gpu.temperature_c == 42
        assert gpu.loaded_models == ["qwen2.5-coder:32b"]

    @pytest.mark.asyncio
    async def test_no_gpu(self):
        async def mock_run_cmd(cmd):
            return (1, "", "nvidia-smi not found")

        with patch("agents.introspect.run_cmd", side_effect=mock_run_cmd):
            gpu = await collect_gpu()

        assert gpu is None

    @pytest.mark.asyncio
    async def test_malformed_output(self):
        async def mock_run_cmd(cmd):
            return (0, "garbage output", "")

        with patch("agents.introspect.run_cmd", side_effect=mock_run_cmd):
            gpu = await collect_gpu()

        assert gpu is None

    @pytest.mark.asyncio
    async def test_ollama_ps_failure_still_returns_gpu(self):
        nvidia_output = "RTX 3090, 565.57.01, 24576, 4200, 20376, 42"

        async def mock_run_cmd(cmd):
            return (0, nvidia_output, "")

        async def mock_http_get(url, **kwargs):
            return (0, "")

        with (
            patch("agents.introspect.run_cmd", side_effect=mock_run_cmd),
            patch("agents.introspect.http_get", side_effect=mock_http_get),
        ):
            gpu = await collect_gpu()

        assert gpu is not None
        assert gpu.loaded_models == []


class TestCollectDisk:
    @pytest.mark.asyncio
    async def test_success(self):
        df_output = "Mounted on      Size  Used Avail Use%\n/home           500G  200G  300G  40%\n"

        async def mock_run_cmd(cmd):
            return (0, df_output, "")

        with patch("agents.introspect.run_cmd", side_effect=mock_run_cmd):
            disks = await collect_disk()

        assert len(disks) == 1
        assert disks[0].mount == "/home"
        assert disks[0].use_percent == 40

    @pytest.mark.asyncio
    async def test_failure(self):
        async def mock_run_cmd(cmd):
            return (1, "", "")

        with patch("agents.introspect.run_cmd", side_effect=mock_run_cmd):
            disks = await collect_disk()

        assert disks == []


class TestCollectPassEntries:
    def test_with_entries(self, tmp_path):
        store = tmp_path / ".password-store"
        store.mkdir()
        (store / "api").mkdir()
        (store / "api" / "anthropic.gpg").touch()
        (store / "api" / "google.gpg").touch()
        (store / "litellm").mkdir()
        (store / "litellm" / "master-key.gpg").touch()

        with patch("agents.introspect.PASSWORD_STORE", store):
            entries = collect_pass_entries()

        assert "api/anthropic" in entries
        assert "api/google" in entries
        assert "litellm/master-key" in entries

    def test_empty_store(self, tmp_path):
        store = tmp_path / ".password-store"
        store.mkdir()

        with patch("agents.introspect.PASSWORD_STORE", store):
            entries = collect_pass_entries()

        assert entries == []

    def test_no_store_dir(self, tmp_path):
        store = tmp_path / "nonexistent"

        with patch("agents.introspect.PASSWORD_STORE", store):
            entries = collect_pass_entries()

        assert entries == []


class TestCollectProfileFiles:
    def test_with_files(self, tmp_path):
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        (profiles / "operator.json").touch()
        (profiles / "operator-profile.json").touch()
        (profiles / ".state.json").touch()

        with patch("agents.introspect.PROFILES_DIR", profiles):
            files = collect_profile_files()

        assert ".state.json" in files
        assert "operator.json" in files
        assert "operator-profile.json" in files

    def test_no_dir(self, tmp_path):
        with patch("agents.introspect.PROFILES_DIR", tmp_path / "nonexistent"):
            files = collect_profile_files()

        assert files == []


class TestCollectListeningPorts:
    @pytest.mark.asyncio
    async def test_success(self):
        ss_output = (
            "State   Recv-Q  Send-Q  Local Address:Port  Peer Address:Port\n"
            "LISTEN  0       128     127.0.0.1:4000      0.0.0.0:*\n"
            "LISTEN  0       128     127.0.0.1:6333      0.0.0.0:*\n"
            "LISTEN  0       128     0.0.0.0:22          0.0.0.0:*\n"
        )

        async def mock_run_cmd(cmd):
            return (0, ss_output, "")

        with patch("agents.introspect.run_cmd", side_effect=mock_run_cmd):
            ports = await collect_listening_ports()

        # Only 127.0.0.1 ports
        assert len(ports) == 2
        assert any("4000" in p for p in ports)
        assert any("6333" in p for p in ports)

    @pytest.mark.asyncio
    async def test_failure(self):
        async def mock_run_cmd(cmd):
            return (1, "", "")

        with patch("agents.introspect.run_cmd", side_effect=mock_run_cmd):
            ports = await collect_listening_ports()

        assert ports == []


class TestCollectLiteLLMRoutes:
    @pytest.mark.asyncio
    async def test_no_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            routes = await collect_litellm_routes()

        assert routes == []

    @pytest.mark.asyncio
    async def test_success(self):
        resp_data = {
            "data": [
                {"id": "claude-opus"},
                {"id": "claude-sonnet"},
                {"id": "gemini-pro"},
            ]
        }

        def mock_urlopen(req, timeout=None):
            body = json.dumps(resp_data).encode()
            mock_resp = MagicMock()
            mock_resp.read.return_value = body
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with (
            patch.dict("os.environ", {"LITELLM_API_KEY": "sk-test"}),
            patch("urllib.request.urlopen", side_effect=mock_urlopen),
        ):
            routes = await collect_litellm_routes()

        assert len(routes) == 3
        assert routes[0].model_name == "claude-opus"


# ── format_summary tests ────────────────────────────────────────────────────


class TestFormatSummary:
    def _make_manifest(self, **kwargs) -> InfrastructureManifest:
        defaults = {
            "timestamp": "2026-02-28T12:00:00Z",
            "hostname": "testhost",
            "os_info": "Linux 6.18.7",
            "docker_version": "27.5.0",
        }
        defaults.update(kwargs)
        return InfrastructureManifest(**defaults)

    def test_minimal(self):
        m = self._make_manifest()
        output = format_summary(m)
        assert "testhost" in output
        assert "Linux 6.18.7" in output
        assert "Docker: 27.5.0" in output
        assert "Docker Containers (0)" in output

    def test_with_gpu(self):
        m = self._make_manifest(
            gpu=GpuInfo(
                name="RTX 3090",
                driver="565.57.01",
                vram_total_mb=24576,
                vram_used_mb=4200,
                temperature_c=42,
                loaded_models=["qwen:32b"],
            ),
        )
        output = format_summary(m)
        assert "RTX 3090" in output
        assert "4200/24576" in output
        assert "42°C" in output
        assert "qwen:32b" in output

    def test_with_containers(self):
        m = self._make_manifest(
            containers=[
                ContainerInfo(
                    name="ollama",
                    service="ollama",
                    image="ollama/ollama",
                    state="running",
                    health="healthy",
                ),
                ContainerInfo(
                    name="qdrant",
                    service="qdrant",
                    image="qdrant/qdrant",
                    state="running",
                    health="healthy",
                    ports=["127.0.0.1:6333->6333/tcp"],
                ),
            ],
        )
        output = format_summary(m)
        assert "Docker Containers (2)" in output
        assert "ollama" in output
        assert "(healthy)" in output
        assert "6333" in output

    def test_with_qdrant_collections(self):
        m = self._make_manifest(
            qdrant_collections=[
                QdrantCollection(name="documents", points_count=150),
                QdrantCollection(name="profile-facts", points_count=42),
            ],
        )
        output = format_summary(m)
        assert "Qdrant Collections (2)" in output
        assert "documents" in output
        assert "150" in output

    def test_with_ollama_models(self):
        m = self._make_manifest(
            ollama_models=[
                OllamaModel(name="qwen2.5-coder:32b", size_bytes=20_000_000_000),
            ],
        )
        output = format_summary(m)
        assert "Ollama Models (1)" in output
        assert "qwen2.5-coder:32b" in output

    def test_with_disk(self):
        m = self._make_manifest(
            disk=[
                DiskInfo(mount="/home", size="500G", used="200G", available="300G", use_percent=40)
            ],
        )
        output = format_summary(m)
        assert "200G/500G" in output
        assert "40%" in output

    def test_with_pass_entries(self):
        m = self._make_manifest(pass_entries=["api/anthropic", "api/google"])
        output = format_summary(m)
        assert "Pass Entries (2)" in output
        assert "api/anthropic" in output

    def test_with_systemd(self):
        m = self._make_manifest(
            systemd_units=[
                SystemdUnit(
                    name="rag-ingest.service", type="service", active="active", enabled="enabled"
                ),
            ],
            systemd_timers=[
                SystemdUnit(
                    name="daily-briefing.timer", type="timer", active="active", enabled="enabled"
                ),
            ],
        )
        output = format_summary(m)
        assert "Systemd Services (1)" in output
        assert "rag-ingest.service" in output
        assert "Systemd Timers (1)" in output
        assert "daily-briefing.timer" in output

    def test_no_gpu(self):
        m = self._make_manifest(gpu=None)
        output = format_summary(m)
        assert "GPU:" not in output
