"""Tests for logos API."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    from logos.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestAppSkeleton:
    async def test_root_returns_info(self, client):
        resp = await client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "logos-api"
        assert "version" in data

    async def test_cors_headers_present(self, client):
        resp = await client.options(
            "/",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
        )
        assert resp.status_code == 200
        assert "access-control-allow-origin" in resp.headers


from dataclasses import dataclass, field

from logos.api.cache import cache


@dataclass
class MockHealth:
    overall_status: str = "healthy"
    total_checks: int = 49
    healthy: int = 49
    degraded: int = 0
    failed: int = 0
    duration_ms: float = 120
    failed_checks: list = field(default_factory=list)
    timestamp: str = "2026-03-02T10:00:00"


@dataclass
class MockVram:
    name: str = "RTX 3090"
    total_mb: int = 24576
    used_mb: int = 8000
    free_mb: int = 16576
    usage_pct: float = 32.6
    temperature_c: int = 55
    loaded_models: list = field(default_factory=lambda: ["qwen2.5-coder:32b"])


@dataclass
class MockContainer:
    name: str = "ollama"
    service: str = "ollama"
    state: str = "running"
    health: str = "healthy"
    image: str = "ollama:latest"
    ports: list = field(default_factory=lambda: ["11434"])


class TestHealthEndpoint:
    async def test_health_returns_data(self, client):
        cache.health = MockHealth()
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_status"] == "healthy"
        assert data["total_checks"] == 49

    async def test_health_returns_null_when_empty(self, client):
        cache.health = None
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() is None


class TestGpuEndpoint:
    async def test_gpu_returns_data(self, client):
        cache.gpu = MockVram()
        resp = await client.get("/api/gpu")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "RTX 3090"
        assert data["usage_pct"] == 32.6


class TestInfrastructureEndpoint:
    async def test_containers_returns_list(self, client):
        cache.containers = [MockContainer()]
        resp = await client.get("/api/infrastructure")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["containers"]) == 1
        assert data["containers"][0]["name"] == "ollama"


# ── Slow-cadence endpoints ──────────────────────────────────────────────────


@dataclass
class MockBriefing:
    headline: str = "Stack healthy"
    body: str = "All systems nominal."
    generated_at: str = "2026-03-01T07:00:00Z"
    hours: int = 24


@dataclass
class MockScout:
    generated_at: str = "2026-03-01T10:00:00Z"
    components_scanned: int = 3
    recommendations: list = field(default_factory=list)
    errors: list = field(default_factory=list)


@dataclass
class MockDrift:
    generated_at: str = "2026-03-01T03:00:00Z"
    drift_count: int = 5
    items: list = field(default_factory=list)


@dataclass
class MockCost:
    total_cost: float = 1.25
    period: str = "7d"
    by_model: dict = field(default_factory=dict)


@dataclass
class MockGoal:
    name: str = "Learn Rust"
    status: str = "active"
    description: str = "Systems programming"


@dataclass
class MockReadiness:
    level: str = "operational"
    score: float = 0.95
    gaps: list = field(default_factory=list)


@dataclass
class MockNudge:
    priority: int = 10
    source: str = "health"
    message: str = "3 checks degraded"


@dataclass
class MockAgent:
    name: str = "briefing"
    status: str = "healthy"
    last_run: str = "2026-03-01T07:00:00Z"


@dataclass
class MockAccommodation:
    time_anchor_enabled: bool = True
    soft_framing_enabled: bool = False
    energy_aware_enabled: bool = False


class TestBriefingEndpoint:
    async def test_briefing_returns_data(self, client):
        cache.briefing = MockBriefing()
        resp = await client.get("/api/briefing")
        assert resp.status_code == 200
        data = resp.json()
        assert data["headline"] == "Stack healthy"

    async def test_briefing_returns_null_when_empty(self, client):
        cache.briefing = None
        resp = await client.get("/api/briefing")
        assert resp.status_code == 200
        assert resp.json() is None

    async def test_briefing_has_cache_header(self, client):
        cache.briefing = MockBriefing()
        resp = await client.get("/api/briefing")
        assert "x-cache-age" in resp.headers


class TestScoutEndpoint:
    async def test_scout_returns_data(self, client):
        cache.scout = MockScout()
        resp = await client.get("/api/scout")
        assert resp.status_code == 200
        data = resp.json()
        assert data["components_scanned"] == 3

    async def test_scout_returns_null_when_empty(self, client):
        cache.scout = None
        resp = await client.get("/api/scout")
        assert resp.status_code == 200
        assert resp.json() is None


class TestDriftEndpoint:
    async def test_drift_returns_data(self, client):
        cache.drift = MockDrift()
        resp = await client.get("/api/drift")
        assert resp.status_code == 200
        data = resp.json()
        assert data["drift_count"] == 5


class TestCostEndpoint:
    async def test_cost_returns_data(self, client):
        cache.cost = MockCost()
        resp = await client.get("/api/cost")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_cost"] == 1.25


class TestGoalsEndpoint:
    async def test_goals_returns_data(self, client):
        cache.goals = [MockGoal()]
        resp = await client.get("/api/goals")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Learn Rust"

    async def test_goals_returns_null_when_empty(self, client):
        cache.goals = None
        resp = await client.get("/api/goals")
        assert resp.status_code == 200
        assert resp.json() is None


class TestReadinessEndpoint:
    async def test_readiness_returns_data(self, client):
        cache.readiness = MockReadiness()
        resp = await client.get("/api/readiness")
        assert resp.status_code == 200
        data = resp.json()
        assert data["level"] == "operational"


class TestNudgesEndpoint:
    async def test_nudges_returns_list(self, client):
        cache.nudges = [MockNudge()]
        resp = await client.get("/api/nudges")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["priority"] == 10

    async def test_nudges_empty_list(self, client):
        cache.nudges = []
        resp = await client.get("/api/nudges")
        assert resp.status_code == 200
        data = resp.json()
        assert data == []


class TestAgentsEndpoint:
    async def test_agents_returns_list(self, client):
        cache.agents = [MockAgent()]
        resp = await client.get("/api/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "briefing"


class TestAccommodationsEndpoint:
    async def test_accommodations_returns_data(self, client):
        cache.accommodations = MockAccommodation()
        resp = await client.get("/api/accommodations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["time_anchor_enabled"] is True

    async def test_accommodations_returns_null_when_empty(self, client):
        cache.accommodations = None
        resp = await client.get("/api/accommodations")
        assert resp.status_code == 200
        assert resp.json() is None


class TestCacheAgeHeaders:
    """All endpoints should include X-Cache-Age header."""

    async def test_fast_endpoint_has_cache_header(self, client):
        cache.health = MockHealth()
        resp = await client.get("/api/health")
        assert "x-cache-age" in resp.headers

    async def test_slow_endpoint_has_cache_header(self, client):
        cache.scout = MockScout()
        resp = await client.get("/api/scout")
        assert "x-cache-age" in resp.headers

    async def test_cache_age_is_numeric(self, client):
        cache.health = MockHealth()
        resp = await client.get("/api/health")
        age = resp.headers["x-cache-age"]
        assert age.lstrip("-").isdigit()


class TestPathSerialization:
    """Verify Path objects don't cause TypeError."""

    async def test_path_in_dataclass_serialized(self, client):
        from pathlib import Path as _Path

        @dataclass
        class DataWithPath:
            name: str = "test"
            file_path: _Path = _Path("/tmp/test.md")

        cache.briefing = DataWithPath()
        resp = await client.get("/api/briefing")
        assert resp.status_code == 200
        data = resp.json()
        assert data["file_path"] == "/tmp/test.md"
