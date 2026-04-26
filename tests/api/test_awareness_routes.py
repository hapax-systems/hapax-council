"""Tests for the awareness REST endpoints.

In-process FastAPI app via ``fastapi.testclient.TestClient``. State
and refusal-log paths are monkeypatched per test so we never touch
``/dev/shm`` from CI.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.operator_awareness.state import AwarenessState, write_state_atomic
from logos.api.routes.awareness import router as awareness_router


@pytest.fixture
def app() -> FastAPI:
    new_app = FastAPI()
    new_app.include_router(awareness_router)
    return new_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _write_fresh_state(tmp_path: Path) -> Path:
    state = AwarenessState(timestamp=datetime.now(UTC), ttl_seconds=300)
    path = tmp_path / "state.json"
    write_state_atomic(state, path)
    return path


def _patch_state_path(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr("logos.api.routes.awareness.DEFAULT_STATE_PATH", path)


def _patch_refusals_path(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr("logos.api.routes.awareness.DEFAULT_REFUSALS_PATH", path)


# ── /api/awareness ──────────────────────────────────────────────────


class TestAwarenessEndpoint:
    def test_returns_state_when_fresh(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        path = _write_fresh_state(tmp_path)
        _patch_state_path(monkeypatch, path)

        resp = client.get("/api/awareness")
        assert resp.status_code == 200
        body = resp.json()
        assert body["schema_version"] == 1
        assert "stream" in body
        assert "X-Awareness-State-Stale" not in resp.headers

    def test_503_when_file_absent(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        _patch_state_path(monkeypatch, tmp_path / "absent.json")
        resp = client.get("/api/awareness")
        assert resp.status_code == 503
        assert resp.headers["X-Awareness-State-Stale"] == "true"
        assert resp.json()["stale"] is True

    def test_503_when_state_stale(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        path = tmp_path / "state.json"
        state = AwarenessState(timestamp=datetime.now(UTC), ttl_seconds=1)
        write_state_atomic(state, path)
        old = time.time() - 30
        os.utime(path, (old, old))
        _patch_state_path(monkeypatch, path)

        resp = client.get("/api/awareness")
        assert resp.status_code == 503
        assert resp.headers["X-Awareness-State-Stale"] == "true"
        body = resp.json()
        assert body["schema_version"] == 1

    def test_503_when_state_unparseable(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        path = tmp_path / "state.json"
        path.write_text("not json {")
        _patch_state_path(monkeypatch, path)

        resp = client.get("/api/awareness")
        assert resp.status_code == 503
        assert resp.headers["X-Awareness-State-Stale"] == "true"

    def test_public_filter_applied(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        path = _write_fresh_state(tmp_path)
        _patch_state_path(monkeypatch, path)

        resp = client.get("/api/awareness?public=true")
        assert resp.status_code == 200
        body = resp.json()
        assert "stream" in body
        assert "refusals_recent" in body


# ── /api/awareness/watch-summary ────────────────────────────────────


class TestWatchSummaryEndpoint:
    def test_payload_compact_under_256_bytes(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        path = _write_fresh_state(tmp_path)
        _patch_state_path(monkeypatch, path)

        resp = client.get("/api/awareness/watch-summary")
        assert resp.status_code == 200
        body = resp.json()
        assert len(json.dumps(body, separators=(",", ":"))) <= 256
        assert {"stance", "live", "stale", "timestamp"} <= set(body.keys())

    def test_returns_503_with_dim_payload_when_absent(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        _patch_state_path(monkeypatch, tmp_path / "absent.json")
        resp = client.get("/api/awareness/watch-summary")
        assert resp.status_code == 503
        body = resp.json()
        assert body["stale"] is True
        assert body["live"] is False

    def test_returns_503_when_stale(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        path = tmp_path / "state.json"
        state = AwarenessState(timestamp=datetime.now(UTC), ttl_seconds=1)
        write_state_atomic(state, path)
        old = time.time() - 30
        os.utime(path, (old, old))
        _patch_state_path(monkeypatch, path)

        resp = client.get("/api/awareness/watch-summary")
        assert resp.status_code == 503
        assert resp.json()["stale"] is True


# ── /api/refusals ───────────────────────────────────────────────────


class TestRefusalsEndpoint:
    def test_empty_when_log_absent(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        _patch_refusals_path(monkeypatch, tmp_path / "absent.jsonl")
        resp = client.get("/api/refusals")
        assert resp.status_code == 200
        assert resp.json() == {"refusals": [], "total_in_window": 0}

    def test_returns_raw_entries(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        path = tmp_path / "log.jsonl"
        now = datetime.now(UTC)
        events = [
            {
                "timestamp": (now - timedelta(minutes=i)).isoformat(),
                "axiom": f"axiom-{i}",
                "surface": f"surface-{i}",
                "reason": f"reason-{i}",
            }
            for i in range(5)
        ]
        path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
        _patch_refusals_path(monkeypatch, path)

        resp = client.get("/api/refusals")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["refusals"]) == 5
        assert body["total_in_window"] == 5
        for i, ev in enumerate(body["refusals"]):
            assert ev["axiom"] == f"axiom-{i}"

    def test_limit_caps_returned_count(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        path = tmp_path / "log.jsonl"
        now = datetime.now(UTC)
        events = [
            {"timestamp": now.isoformat(), "axiom": "x", "surface": "y", "reason": f"r{i}"}
            for i in range(20)
        ]
        path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
        _patch_refusals_path(monkeypatch, path)

        resp = client.get("/api/refusals?limit=5")
        body = resp.json()
        assert len(body["refusals"]) == 5
        assert body["total_in_window"] == 20

    def test_since_filter_drops_older_entries(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        path = tmp_path / "log.jsonl"
        now = datetime.now(UTC)
        events = [
            {
                "timestamp": (now - timedelta(hours=h)).isoformat(),
                "axiom": "x",
                "surface": "y",
                "reason": f"hour-{h}",
            }
            for h in range(5)
        ]
        path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
        _patch_refusals_path(monkeypatch, path)

        cutoff = (now - timedelta(hours=2, minutes=30)).isoformat()
        # Pass via params dict so TestClient URL-encodes the ``+`` in
        # the ISO-8601 ``+00:00`` offset (otherwise FastAPI sees a
        # space and rejects the parse).
        resp = client.get("/api/refusals", params={"since": cutoff})
        body = resp.json()
        assert body["total_in_window"] == 3

    def test_skips_malformed_lines(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        path = tmp_path / "log.jsonl"
        now = datetime.now(UTC)
        path.write_text(
            "not json\n"
            + json.dumps(
                {"timestamp": now.isoformat(), "axiom": "x", "surface": "y", "reason": "kept"}
            )
            + "\n"
        )
        _patch_refusals_path(monkeypatch, path)

        resp = client.get("/api/refusals")
        body = resp.json()
        assert body["total_in_window"] == 1
        assert body["refusals"][0]["reason"] == "kept"


# ── Read-only contract ──────────────────────────────────────────────


class TestReadOnlyContract:
    """Constitutional invariant: awareness/refusals are read-only.
    POST/PUT/DELETE/PATCH must NOT be registered for any of the
    three endpoints. Aggregation/mutation paths are explicit REFUSED
    cc-tasks; CI must catch a regression that adds them."""

    def test_no_mutation_routes_under_awareness(self, app: FastAPI):
        mutation_methods = {"POST", "PUT", "DELETE", "PATCH"}
        for route in app.routes:
            path = getattr(route, "path", "")
            if not path.startswith(("/api/awareness", "/api/refusals")):
                continue
            methods = set(getattr(route, "methods", set()) or set())
            assert not (methods & mutation_methods), (
                f"mutation method on read-only route {path}: {methods & mutation_methods}"
            )
