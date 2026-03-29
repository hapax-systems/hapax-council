"""Tests for health_monitor — schemas, check functions, runner logic.

All I/O is mocked. No real subprocess calls, HTTP requests, or filesystem access.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.health_monitor import (
    CHECK_REGISTRY,
    CORE_CONTAINERS,
    PASS_ENTRIES,
    REQUIRED_QDRANT_COLLECTIONS,
    CheckResult,
    GroupResult,
    HealthReport,
    Status,
    build_group_result,
    format_human,
    quick_check,
    run_checks,
    worst_status,
)

# ── Schema tests ─────────────────────────────────────────────────────────────


class TestStatus:
    def test_values(self):
        assert Status.HEALTHY == "healthy"
        assert Status.DEGRADED == "degraded"
        assert Status.FAILED == "failed"

    def test_ordering_via_worst_status(self):
        assert worst_status(Status.HEALTHY, Status.HEALTHY) == Status.HEALTHY
        assert worst_status(Status.HEALTHY, Status.DEGRADED) == Status.DEGRADED
        assert worst_status(Status.HEALTHY, Status.FAILED) == Status.FAILED
        assert worst_status(Status.DEGRADED, Status.FAILED) == Status.FAILED
        assert worst_status(Status.FAILED, Status.DEGRADED, Status.HEALTHY) == Status.FAILED

    def test_worst_status_single(self):
        assert worst_status(Status.HEALTHY) == Status.HEALTHY
        assert worst_status(Status.DEGRADED) == Status.DEGRADED
        assert worst_status(Status.FAILED) == Status.FAILED

    def test_worst_status_empty(self):
        assert worst_status() == Status.HEALTHY


class TestCheckResult:
    def test_minimal(self):
        r = CheckResult(
            name="test.check",
            group="test",
            status=Status.HEALTHY,
            message="ok",
        )
        assert r.name == "test.check"
        assert r.detail is None
        assert r.remediation is None
        assert r.duration_ms == 0

    def test_full(self):
        r = CheckResult(
            name="test.check",
            group="test",
            status=Status.FAILED,
            message="broken",
            detail="stack trace",
            remediation="fix it",
            duration_ms=42,
        )
        assert r.status == Status.FAILED
        assert r.remediation == "fix it"
        assert r.duration_ms == 42

    def test_json_roundtrip(self):
        r = CheckResult(
            name="test.x",
            group="test",
            status=Status.DEGRADED,
            message="warn",
        )
        data = json.loads(r.model_dump_json())
        assert data["status"] == "degraded"
        r2 = CheckResult.model_validate(data)
        assert r2 == r


class TestGroupResult:
    def test_build_group_result_all_healthy(self):
        checks = [
            CheckResult(name="a", group="g", status=Status.HEALTHY, message="ok"),
            CheckResult(name="b", group="g", status=Status.HEALTHY, message="ok"),
        ]
        gr = build_group_result("g", checks)
        assert gr.status == Status.HEALTHY
        assert gr.healthy_count == 2
        assert gr.degraded_count == 0
        assert gr.failed_count == 0

    def test_build_group_result_mixed(self):
        checks = [
            CheckResult(name="a", group="g", status=Status.HEALTHY, message="ok"),
            CheckResult(name="b", group="g", status=Status.DEGRADED, message="warn"),
            CheckResult(name="c", group="g", status=Status.FAILED, message="bad"),
        ]
        gr = build_group_result("g", checks)
        assert gr.status == Status.FAILED
        assert gr.healthy_count == 1
        assert gr.degraded_count == 1
        assert gr.failed_count == 1

    def test_build_group_result_empty(self):
        gr = build_group_result("g", [])
        assert gr.status == Status.HEALTHY
        assert gr.healthy_count == 0


class TestHealthReport:
    def test_json_roundtrip(self):
        report = HealthReport(
            timestamp="2026-02-28T12:00:00Z",
            hostname="test",
            overall_status=Status.HEALTHY,
            groups=[],
            total_checks=0,
            summary="0/0 healthy",
        )
        data = json.loads(report.model_dump_json())
        r2 = HealthReport.model_validate(data)
        assert r2.overall_status == Status.HEALTHY


# ── Check function tests (mocked I/O) ───────────────────────────────────────


class TestDockerChecks:
    @pytest.mark.asyncio
    async def test_docker_daemon_healthy(self):
        from agents.health_monitor import check_docker_daemon

        with patch("agents.health_monitor.run_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = (0, "27.5.0", "")
            results = await check_docker_daemon()
        assert len(results) == 1
        assert results[0].status == Status.HEALTHY
        assert "27.5.0" in results[0].message

    @pytest.mark.asyncio
    async def test_docker_daemon_failed(self):
        from agents.health_monitor import check_docker_daemon

        with patch("agents.health_monitor.run_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = (1, "", "Cannot connect to Docker daemon")
            results = await check_docker_daemon()
        assert results[0].status == Status.FAILED
        assert results[0].remediation is not None

    @pytest.mark.asyncio
    async def test_compose_file_exists(self):
        from agents.health_monitor import check_compose_file

        with patch("agents.health_monitor.COMPOSE_FILE") as mock_path:
            mock_path.is_file.return_value = True
            mock_path.__str__ = lambda self: "/home/test/llm-stack/docker-compose.yml"
            results = await check_compose_file()
        assert results[0].status == Status.HEALTHY

    @pytest.mark.asyncio
    async def test_docker_containers_ndjson(self):
        from agents.health_monitor import check_docker_containers

        ndjson = "\n".join(
            [
                json.dumps(
                    {"Name": "qdrant", "Service": "qdrant", "State": "running", "Health": "healthy"}
                ),
                json.dumps(
                    {"Name": "ollama", "Service": "ollama", "State": "running", "Health": "healthy"}
                ),
                json.dumps({"Name": "n8n", "Service": "n8n", "State": "exited", "Health": ""}),
            ]
        )
        with patch("agents.health_monitor.run_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = (0, ndjson, "")
            results = await check_docker_containers()

        assert len(results) == 3
        qdrant_r = next(r for r in results if "qdrant" in r.name)
        assert qdrant_r.status == Status.HEALTHY

        n8n_r = next(r for r in results if "n8n" in r.name)
        # n8n is not core, so exited = degraded
        assert n8n_r.status == Status.DEGRADED
        assert n8n_r.remediation is not None

    @pytest.mark.asyncio
    async def test_core_container_down_is_failed(self):
        from agents.health_monitor import check_docker_containers

        ndjson = json.dumps(
            {
                "Name": "qdrant",
                "Service": "qdrant",
                "State": "exited",
                "Health": "",
            }
        )
        with patch("agents.health_monitor.run_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = (0, ndjson, "")
            results = await check_docker_containers()
        assert results[0].status == Status.FAILED


class TestGpuChecks:
    @pytest.mark.asyncio
    async def test_gpu_available(self):
        from agents.health_monitor import check_gpu_available

        with patch("agents.health_monitor._nvidia_smi", new_callable=AsyncMock) as mock:
            mock.return_value = (0, "570.86.16, NVIDIA GeForce RTX 3090", "")
            results = await check_gpu_available()
        assert results[0].status == Status.HEALTHY
        assert "RTX 3090" in results[0].message

    @pytest.mark.asyncio
    async def test_gpu_vram_healthy(self):
        from agents.health_monitor import check_gpu_vram

        with (
            patch("agents.health_monitor._nvidia_smi", new_callable=AsyncMock) as mock_smi,
            patch("agents.health_monitor.http_get", new_callable=AsyncMock) as mock_http,
        ):
            mock_smi.return_value = (0, "4000, 24576, 20576", "")
            mock_http.return_value = (200, '{"models": []}')
            results = await check_gpu_vram()
        assert results[0].status == Status.HEALTHY
        assert "4000MiB" in results[0].message

    @pytest.mark.asyncio
    async def test_gpu_vram_critical(self):
        from agents.health_monitor import check_gpu_vram

        with (
            patch("agents.health_monitor._nvidia_smi", new_callable=AsyncMock) as mock_smi,
            patch("agents.health_monitor.http_get", new_callable=AsyncMock) as mock_http,
        ):
            mock_smi.return_value = (0, "23500, 24576, 1076", "")
            mock_http.return_value = (200, '{"models": [{"name": "qwen3:30b"}]}')
            results = await check_gpu_vram()
        assert results[0].status == Status.FAILED
        assert results[0].detail is not None
        assert "qwen3:30b" in results[0].detail

    @pytest.mark.asyncio
    async def test_gpu_temp_healthy(self):
        from agents.health_monitor import check_gpu_temperature

        with patch("agents.health_monitor._nvidia_smi", new_callable=AsyncMock) as mock:
            mock.return_value = (0, "45", "")
            results = await check_gpu_temperature()
        assert results[0].status == Status.HEALTHY
        assert "45°C" in results[0].message

    @pytest.mark.asyncio
    async def test_gpu_temp_hot(self):
        from agents.health_monitor import check_gpu_temperature

        with patch("agents.health_monitor._nvidia_smi", new_callable=AsyncMock) as mock:
            mock.return_value = (0, "85", "")
            results = await check_gpu_temperature()
        assert results[0].status == Status.DEGRADED


class TestSystemdChecks:
    @pytest.mark.asyncio
    async def test_systemd_services_healthy(self):
        from agents.health_monitor import check_systemd_services

        with patch("agents.health_monitor.run_cmd", new_callable=AsyncMock) as mock:

            async def side_effect(cmd, **kwargs):
                unit = cmd[-1] if cmd else ""
                if "is-active" in cmd and "profile-update" in unit:
                    return (0, "active", "")
                if "is-active" in cmd and "digest" in unit:
                    return (0, "active", "")
                if "is-active" in cmd and "knowledge-maint" in unit:
                    return (0, "active", "")
                if "is-enabled" in cmd:
                    return (0, "enabled", "")
                if "list-timers" in cmd:
                    return (0, "NEXT  LEFT  LAST  PASSED  UNIT  ACTIVATES\nMon 2026...", "")
                if "is-active" in cmd and "midi-route" in unit:
                    return (3, "inactive", "")
                return (0, "", "")

            mock.side_effect = side_effect
            results = await check_systemd_services()

        profile = next(r for r in results if "profile-update" in r.name)
        assert profile.status == Status.HEALTHY

        midi = next(r for r in results if "midi-route" in r.name)
        assert midi.status == Status.HEALTHY  # optional


class TestQdrantChecks:
    @pytest.mark.asyncio
    async def test_qdrant_healthy(self):
        from agents.health_monitor import check_qdrant_health

        with patch("agents.health_monitor.http_get", new_callable=AsyncMock) as mock:
            mock.return_value = (200, "ok")
            results = await check_qdrant_health()
        assert results[0].status == Status.HEALTHY

    @pytest.mark.asyncio
    async def test_qdrant_collections_all_present(self):
        from agents.health_monitor import check_qdrant_collections

        collections_resp = json.dumps(
            {
                "result": {
                    "collections": [
                        {"name": "documents"},
                        {"name": "profile-facts"},
                        {"name": "axiom-precedents"},
                        {"name": "operator-corrections"},
                        {"name": "operator-episodes"},
                        {"name": "operator-patterns"},
                        {"name": "studio-moments"},
                    ]
                }
            }
        )

        def _coll_detail(name):
            dim = 768  # All collections use nomic 768-dim
            return json.dumps(
                {
                    "result": {
                        "points_count": 42,
                        "config": {"params": {"vectors": {"size": dim}}},
                    }
                }
            )

        with patch("agents.health_monitor.http_get", new_callable=AsyncMock) as mock:

            async def side_effect(url, **kwargs):
                if "/collections/" in url:
                    coll_name = url.rsplit("/", 1)[-1]
                    return (200, _coll_detail(coll_name))
                return (200, collections_resp)

            mock.side_effect = side_effect
            results = await check_qdrant_collections()
        assert all(r.status == Status.HEALTHY for r in results)
        assert len(results) == 7

    @pytest.mark.asyncio
    async def test_qdrant_collection_missing(self):
        from agents.health_monitor import check_qdrant_collections

        collections_resp = json.dumps({"result": {"collections": [{"name": "documents"}]}})
        with patch("agents.health_monitor.http_get", new_callable=AsyncMock) as mock:

            async def side_effect(url, **kwargs):
                if "/collections/" in url and "documents" in url:
                    return (
                        200,
                        json.dumps(
                            {
                                "result": {
                                    "points_count": 10,
                                    "config": {"params": {"vectors": {"size": 768}}},
                                }
                            }
                        ),
                    )
                return (200, collections_resp)

            mock.side_effect = side_effect
            results = await check_qdrant_collections()

        docs = next(r for r in results if "documents" in r.name)
        assert docs.status == Status.HEALTHY

        missing = next(r for r in results if "profile-facts" in r.name)
        assert missing.status == Status.FAILED
        assert missing.remediation is not None
        assert "curl" in missing.remediation


class TestProfileChecks:
    @pytest.mark.asyncio
    async def test_profile_files_all_present(self):
        from agents.health_monitor import check_profile_files

        with patch("agents.health_monitor.PROFILES_DIR") as mock_dir:

            def mock_path(name):
                p = MagicMock()
                p.is_file.return_value = True
                p.read_text.return_value = '{"key": "value"}'
                return p

            mock_dir.__truediv__ = lambda self, name: mock_path(name)
            results = await check_profile_files()
        assert all(r.status == Status.HEALTHY for r in results)

    @pytest.mark.asyncio
    async def test_profile_staleness_recent(self):
        from agents.health_monitor import check_profile_staleness

        now = datetime.now(UTC)
        state = json.dumps({"last_run": now.isoformat()})
        mock_path = MagicMock()
        mock_path.is_file.return_value = True
        mock_path.read_text.return_value = state

        with patch("agents.health_monitor.PROFILES_DIR") as mock_dir:
            mock_dir.__truediv__ = lambda self, name: mock_path
            results = await check_profile_staleness()
        assert results[0].status == Status.HEALTHY

    @pytest.mark.asyncio
    async def test_profile_staleness_old(self):
        from agents.health_monitor import check_profile_staleness

        old = datetime.now(UTC) - timedelta(hours=80)
        state = json.dumps({"last_run": old.isoformat()})
        mock_path = MagicMock()
        mock_path.is_file.return_value = True
        mock_path.read_text.return_value = state

        with patch("agents.health_monitor.PROFILES_DIR") as mock_dir:
            mock_dir.__truediv__ = lambda self, name: mock_path
            results = await check_profile_staleness()
        assert results[0].status == Status.FAILED


class TestEndpointChecks:
    @pytest.mark.asyncio
    async def test_all_endpoints_up(self):
        from agents.health_monitor import check_service_endpoints

        with patch("agents.health_monitor.http_get", new_callable=AsyncMock) as mock:
            mock.return_value = (200, "ok")
            results = await check_service_endpoints()
        assert all(r.status == Status.HEALTHY for r in results)
        assert len(results) == 4

    @pytest.mark.asyncio
    async def test_core_endpoint_down_is_failed(self):
        from agents.health_monitor import check_service_endpoints

        with patch("agents.health_monitor.http_get", new_callable=AsyncMock) as mock:

            async def side_effect(url, **kwargs):
                if "4000" in url:
                    return (0, "Connection refused")
                return (200, "ok")

            mock.side_effect = side_effect
            results = await check_service_endpoints()
        litellm_r = next(r for r in results if "litellm" in r.name)
        assert litellm_r.status == Status.FAILED

    @pytest.mark.asyncio
    async def test_optional_endpoint_down_is_degraded(self):
        from agents.health_monitor import check_service_endpoints

        with patch("agents.health_monitor.http_get", new_callable=AsyncMock) as mock:

            async def side_effect(url, **kwargs):
                if "3000" in url:
                    return (0, "Connection refused")
                return (200, "ok")

            mock.side_effect = side_effect
            results = await check_service_endpoints()
        langfuse_r = next(r for r in results if "langfuse" in r.name)
        assert langfuse_r.status == Status.DEGRADED


class TestCredentialChecks:
    @pytest.mark.asyncio
    async def test_pass_store_exists(self):
        from agents.health_monitor import check_pass_store

        with patch("agents.health_monitor.PASSWORD_STORE") as mock_path:
            mock_path.is_dir.return_value = True
            mock_path.__str__ = lambda self: "/home/test/.password-store"
            results = await check_pass_store()
        assert results[0].status == Status.HEALTHY

    @pytest.mark.asyncio
    async def test_pass_entries_mixed(self):
        from agents.health_monitor import check_pass_entries

        existing = {"api/anthropic", "api/google", "litellm/master-key"}

        with patch("agents.health_monitor.PASSWORD_STORE") as mock_store:

            def mock_div(self, entry):
                p = MagicMock()
                base = entry.replace(".gpg", "")
                p.is_file.return_value = base in existing
                return p

            mock_store.__truediv__ = mock_div
            results = await check_pass_entries()

        healthy = [r for r in results if r.status == Status.HEALTHY]
        failed = [r for r in results if r.status == Status.FAILED]
        assert len(healthy) == 3
        assert len(failed) == 2


class TestDiskChecks:
    @pytest.mark.asyncio
    async def test_disk_healthy(self):
        from agents.health_monitor import check_disk_usage

        with patch("agents.health_monitor.run_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = (0, "Use%\n 42%", "")
            results = await check_disk_usage()
        assert results[0].status == Status.HEALTHY
        assert "42%" in results[0].message

    @pytest.mark.asyncio
    async def test_disk_degraded(self):
        from agents.health_monitor import check_disk_usage

        with patch("agents.health_monitor.run_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = (0, "Use%\n 90%", "")
            results = await check_disk_usage()
        assert results[0].status == Status.DEGRADED


# ── Runner tests ─────────────────────────────────────────────────────────────


class TestRunner:
    @pytest.mark.asyncio
    async def test_run_checks_all_groups(self):
        """Verify run_checks returns a valid report with all groups."""
        # Mock all external calls
        with (
            patch("agents.health_monitor.run_cmd", new_callable=AsyncMock) as mock_cmd,
            patch("agents.health_monitor.http_get", new_callable=AsyncMock) as mock_http,
            patch("agents.health_monitor.COMPOSE_FILE") as mock_compose,
            patch("agents.health_monitor.PROFILES_DIR") as mock_profiles,
            patch("agents.health_monitor.PASSWORD_STORE") as mock_pass,
        ):
            mock_compose.is_file.return_value = True
            mock_compose.__str__ = lambda self: "/test/docker-compose.yml"
            mock_compose.parent = Path("/test")

            mock_pass.is_dir.return_value = True
            mock_pass.__str__ = lambda self: "/test/.password-store"
            mock_pass.__truediv__ = lambda self, x: MagicMock(is_file=MagicMock(return_value=True))

            # Profile files exist
            def mock_profile_path(name):
                p = MagicMock()
                p.is_file.return_value = True
                p.read_text.return_value = json.dumps({"last_run": datetime.now(UTC).isoformat()})
                return p

            mock_profiles.__truediv__ = lambda self, name: mock_profile_path(name)
            mock_profiles.parent = Path("/test")

            # Commands all succeed
            async def cmd_side_effect(cmd, **kwargs):
                if "docker" in cmd and "info" in cmd:
                    return (0, "27.5.0", "")
                if "docker" in cmd and "ps" in cmd:
                    return (
                        0,
                        json.dumps(
                            {"Name": "test", "Service": "test", "State": "running", "Health": ""}
                        ),
                        "",
                    )
                if "nvidia-smi" in cmd[0]:
                    query = cmd[1] if len(cmd) > 1 else ""
                    if "driver_version" in query:
                        return (0, "570.86, RTX 3090", "")
                    if "memory" in query:
                        return (0, "4000, 24576, 20576", "")
                    if "temperature" in query:
                        return (0, "45", "")
                if "systemctl" in cmd:
                    if "is-active" in cmd:
                        return (0, "active", "")
                    if "is-enabled" in cmd:
                        return (0, "enabled", "")
                    if "list-timers" in cmd:
                        return (0, "NEXT LEFT LAST PASSED UNIT\nline2", "")
                if "df" in cmd:
                    return (0, "Use%\n 42%", "")
                return (0, "", "")

            mock_cmd.side_effect = cmd_side_effect

            mock_http.return_value = (
                200,
                '{"result": {"collections": [{"name": "documents"}, {"name": "profile-facts"}, {"name": "operator-episodes"}]}}',
            )

            report = await run_checks()

        assert isinstance(report, HealthReport)
        assert report.total_checks > 0
        assert report.hostname  # should have a hostname
        assert report.timestamp  # should have a timestamp
        # All check groups should be represented
        group_names = {gr.group for gr in report.groups}
        assert "docker" in group_names
        assert "gpu" in group_names

    @pytest.mark.asyncio
    async def test_run_checks_specific_group(self):
        """Verify run_checks with specific group filter."""
        with patch("agents.health_monitor.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "Use%\n 42%", "")
            report = await run_checks(groups=["disk"])

        assert len(report.groups) == 1
        assert report.groups[0].group == "disk"


# ── quick_check tests ────────────────────────────────────────────────────────


class TestQuickCheck:
    @pytest.mark.asyncio
    async def test_quick_check_all_ok(self):
        with patch("agents.health_monitor.http_get", new_callable=AsyncMock) as mock:
            mock.return_value = (200, "ok")
            ok, results = await quick_check()
        assert ok is True
        assert len(results) == 2  # litellm + qdrant

    @pytest.mark.asyncio
    async def test_quick_check_one_down(self):
        with patch("agents.health_monitor.http_get", new_callable=AsyncMock) as mock:

            async def side_effect(url, **kwargs):
                if "4000" in url:
                    return (0, "Connection refused")
                return (200, "ok")

            mock.side_effect = side_effect
            ok, results = await quick_check()
        assert ok is False

    @pytest.mark.asyncio
    async def test_quick_check_custom_services(self):
        with patch("agents.health_monitor.http_get", new_callable=AsyncMock) as mock:
            mock.return_value = (200, "ok")
            ok, results = await quick_check(["ollama", "langfuse"])
        assert ok is True
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_quick_check_unknown_service(self):
        ok, results = await quick_check(["nonexistent"])
        assert ok is False
        assert results[0].status == Status.FAILED


# ── Formatter tests ──────────────────────────────────────────────────────────


class TestFormatter:
    def test_format_human_basic(self):
        report = HealthReport(
            timestamp="2026-02-28T12:00:00Z",
            hostname="test",
            overall_status=Status.HEALTHY,
            groups=[
                GroupResult(
                    group="test",
                    status=Status.HEALTHY,
                    checks=[
                        CheckResult(
                            name="test.a", group="test", status=Status.HEALTHY, message="ok"
                        ),
                    ],
                    healthy_count=1,
                ),
            ],
            total_checks=1,
            healthy_count=1,
            summary="1/1 healthy",
        )
        output = format_human(report, color=False)
        assert "HEALTHY" in output
        assert "test.a" in output
        assert "[OK]" in output

    def test_format_human_with_remediation(self):
        report = HealthReport(
            timestamp="2026-02-28T12:00:00Z",
            hostname="test",
            overall_status=Status.FAILED,
            groups=[
                GroupResult(
                    group="docker",
                    status=Status.FAILED,
                    checks=[
                        CheckResult(
                            name="docker.qdrant",
                            group="docker",
                            status=Status.FAILED,
                            message="not running",
                            remediation="docker compose up -d qdrant",
                        ),
                    ],
                    failed_count=1,
                ),
            ],
            total_checks=1,
            failed_count=1,
            summary="0/1 healthy, 1 failed",
        )
        output = format_human(report, color=False)
        assert "[FAIL]" in output
        assert "Fix:" in output
        assert "docker compose up -d qdrant" in output


# ── Registry tests ───────────────────────────────────────────────────────────


class TestModelChecks:
    @pytest.mark.asyncio
    async def test_ollama_models_all_present(self):
        from agents.health_monitor import check_ollama_models

        tags_resp = json.dumps(
            {
                "models": [
                    {"name": "nomic-embed-text-v2-moe:latest"},
                    {"name": "qwen3.5:27b"},
                    {"name": "qwen3:8b"},
                ]
            }
        )
        with patch("agents.health_monitor.http_get", new_callable=AsyncMock) as mock:
            mock.return_value = (200, tags_resp)
            results = await check_ollama_models()
        assert all(r.status == Status.HEALTHY for r in results)

    @pytest.mark.asyncio
    async def test_ollama_model_missing(self):
        from agents.health_monitor import check_ollama_models

        tags_resp = json.dumps({"models": [{"name": "qwen2.5:7b"}]})
        with patch("agents.health_monitor.http_get", new_callable=AsyncMock) as mock:
            mock.return_value = (200, tags_resp)
            results = await check_ollama_models()
        missing = [r for r in results if r.status == Status.DEGRADED]
        assert len(missing) >= 1
        assert any("ollama pull" in (r.remediation or "") for r in missing)


class TestAuthChecks:
    @pytest.mark.asyncio
    async def test_litellm_auth_no_key(self):
        from agents.health_monitor import check_litellm_auth

        with (
            patch.dict("os.environ", {"LITELLM_API_KEY": ""}, clear=False),
            patch("agents.health_monitor._pass_show", return_value=""),
        ):
            results = await check_litellm_auth()
        assert results[0].status == Status.DEGRADED

    @pytest.mark.asyncio
    async def test_langfuse_auth_no_keys(self):
        from agents.health_monitor import check_langfuse_auth

        with (
            patch.dict(
                "os.environ", {"LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": ""}, clear=False
            ),
            patch("agents.health_monitor._pass_show", return_value=""),
        ):
            results = await check_langfuse_auth()
        assert results[0].status == Status.DEGRADED


class TestRegistry:
    def test_all_groups_registered(self):
        expected = {
            "docker",
            "gpu",
            "systemd",
            "qdrant",
            "profiles",
            "endpoints",
            "credentials",
            "disk",
            "models",
            "auth",
            "connectivity",
            "latency",
            "secrets",
            "queues",
            "budget",
            "capacity",
            "axioms",
            "voice",
            "skills",
            "traces",
            "backup",
            "sync",
        }
        assert expected == set(CHECK_REGISTRY.keys())

    def test_constants(self):
        assert "qdrant" in CORE_CONTAINERS
        assert "ollama" in CORE_CONTAINERS
        assert "documents" in REQUIRED_QDRANT_COLLECTIONS
        assert "api/anthropic" in PASS_ENTRIES


# ── History rotation tests ──────────────────────────────────────────────────


class TestRotateHistory:
    def test_rotate_noop_when_missing(self, tmp_path, monkeypatch):
        import agents.health_monitor as hm

        monkeypatch.setattr(hm, "HISTORY_FILE", tmp_path / "missing.jsonl")
        hm.rotate_history()

    def test_rotate_noop_when_under_limit(self, tmp_path, monkeypatch):
        import agents.health_monitor as hm

        hist = tmp_path / "history.jsonl"
        hist.write_text("\n".join(f"line{i}" for i in range(100)) + "\n")
        monkeypatch.setattr(hm, "HISTORY_FILE", hist)
        hm.rotate_history()
        assert len(hist.read_text().strip().splitlines()) == 100

    def test_rotate_truncates_when_over_limit(self, tmp_path, monkeypatch):
        import agents.health_monitor as hm

        hist = tmp_path / "history.jsonl"
        lines = [f'{{"line": {i}}}' for i in range(12_000)]
        hist.write_text("\n".join(lines) + "\n")
        monkeypatch.setattr(hm, "HISTORY_FILE", hist)
        hm.rotate_history()
        result_lines = hist.read_text().strip().splitlines()
        assert len(result_lines) == hm.KEEP_HISTORY_LINES
        assert '{"line": 11999}' in result_lines[-1]

    def test_rotate_at_boundary(self, tmp_path, monkeypatch):
        import agents.health_monitor as hm

        hist = tmp_path / "history.jsonl"
        lines = [f"line{i}" for i in range(hm.MAX_HISTORY_LINES)]
        hist.write_text("\n".join(lines) + "\n")
        monkeypatch.setattr(hm, "HISTORY_FILE", hist)
        hm.rotate_history()
        assert len(hist.read_text().strip().splitlines()) == hm.MAX_HISTORY_LINES


# ── Latency checks ──────────────────────────────────────────────────────────


class TestLatencyChecks:
    @pytest.mark.asyncio
    async def test_healthy_latency(self):
        from agents.health_monitor import check_service_latency

        async def fast_latency(url, timeout=3.0):
            return 2.0  # 2ms — healthy

        with patch("agents.health_monitor._http_latency_ms", side_effect=fast_latency):
            results = await check_service_latency()
        assert all(r.status == Status.HEALTHY for r in results)
        assert len(results) == 3  # litellm, qdrant, ollama

    @pytest.mark.asyncio
    async def test_unreachable_service(self):
        from agents.health_monitor import check_service_latency

        async def fail_latency(url, timeout=3.0):
            return None  # unreachable

        with patch("agents.health_monitor._http_latency_ms", side_effect=fail_latency):
            results = await check_service_latency()
        assert all(r.status == Status.FAILED for r in results)

    @pytest.mark.asyncio
    async def test_postgres_healthy(self):
        from agents.health_monitor import check_postgres_latency

        async def fast_connect(host, port, timeout=3.0):
            return 5.0  # 5ms

        with patch("agents.health_monitor._tcp_connect_ms", side_effect=fast_connect):
            results = await check_postgres_latency()
        assert results[0].status == Status.HEALTHY

    @pytest.mark.asyncio
    async def test_postgres_unreachable(self):
        from agents.health_monitor import check_postgres_latency

        async def fail_connect(host, port, timeout=3.0):
            return None

        with patch("agents.health_monitor._tcp_connect_ms", side_effect=fail_connect):
            results = await check_postgres_latency()
        assert results[0].status == Status.FAILED


# ── Secret checks ────────────────────────────────────────────────────────────


class TestSecretChecks:
    @pytest.mark.asyncio
    async def test_all_secrets_set(self):
        from agents.health_monitor import REQUIRED_SECRETS, check_env_secrets

        env = {k: "a-real-secret-value-here" for k in REQUIRED_SECRETS}
        with patch.dict("os.environ", env, clear=False):
            results = await check_env_secrets()
        assert all(r.status == Status.HEALTHY for r in results)

    @pytest.mark.asyncio
    async def test_missing_secret(self):
        from agents.health_monitor import check_env_secrets

        with (
            patch.dict("os.environ", {"LITELLM_API_KEY": ""}, clear=False),
            patch("agents.health_monitor._pass_show", return_value=""),
        ):
            results = await check_env_secrets()
        litellm = [r for r in results if "litellm_api_key" in r.name]
        assert litellm[0].status == Status.FAILED

    @pytest.mark.asyncio
    async def test_short_secret(self):
        from agents.health_monitor import check_env_secrets

        with patch.dict("os.environ", {"LITELLM_API_KEY": "short"}, clear=False):
            results = await check_env_secrets()
        litellm = [r for r in results if "litellm_api_key" in r.name]
        assert litellm[0].status == Status.DEGRADED


# ── Queue checks ─────────────────────────────────────────────────────────────


class TestQueueChecks:
    @pytest.mark.asyncio
    async def test_no_retry_queue(self, tmp_path, monkeypatch):
        from agents.health_monitor import check_rag_retry_queue

        monkeypatch.setattr("agents.health_monitor.PROFILES_DIR", tmp_path)
        results = await check_rag_retry_queue()
        assert results[0].status == Status.HEALTHY

    @pytest.mark.asyncio
    async def test_large_retry_queue(self, tmp_path, monkeypatch):
        from agents.health_monitor import check_rag_retry_queue

        monkeypatch.setattr("agents.health_monitor.RAG_INGEST_STATE_DIR", tmp_path)
        queue = tmp_path / "retry-queue.jsonl"
        queue.write_text("\n".join(f'{{"file": "f{i}"}}' for i in range(60)))
        results = await check_rag_retry_queue()
        assert results[0].status == Status.DEGRADED

    @pytest.mark.asyncio
    async def test_n8n_responsive(self):
        from agents.health_monitor import check_n8n_executions

        async def ok_get(url, timeout=3.0):
            return (200, "ok")

        with patch("agents.health_monitor.http_get", side_effect=ok_get):
            results = await check_n8n_executions()
        assert results[0].status == Status.HEALTHY


# ── Budget checks ────────────────────────────────────────────────────────────


class TestBudgetChecks:
    @pytest.mark.asyncio
    async def test_under_budget(self):
        from agents.health_monitor import check_daily_spend

        async def spend_get(url, timeout=5.0):
            return (200, json.dumps([{"spend": 1.50}]))

        with patch("agents.health_monitor.http_get", side_effect=spend_get):
            results = await check_daily_spend()
        assert results[0].status == Status.HEALTHY
        assert "$1.50" in results[0].message

    @pytest.mark.asyncio
    async def test_over_budget(self):
        from agents.health_monitor import check_daily_spend

        async def spend_get(url, timeout=5.0):
            return (200, json.dumps([{"spend": 3.00}, {"spend": 4.00}]))

        with patch("agents.health_monitor.http_get", side_effect=spend_get):
            results = await check_daily_spend()
        assert results[0].status == Status.DEGRADED

    @pytest.mark.asyncio
    async def test_spend_endpoint_unavailable(self):
        from agents.health_monitor import check_daily_spend

        async def fail_get(url, timeout=5.0):
            return (404, "not found")

        with patch("agents.health_monitor.http_get", side_effect=fail_get):
            results = await check_daily_spend()
        assert results[0].status == Status.HEALTHY  # non-blocking
