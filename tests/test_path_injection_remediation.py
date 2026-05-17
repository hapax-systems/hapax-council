"""Regression tests for CodeQL py/path-injection remediation helpers."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError


def test_consent_trace_reads_only_allowlisted_absolute_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from logos.api.routes import consent as consent_routes

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    inside = allowed / "note.md"
    inside.write_text("---\nconsent_label:\n  policies: []\n---\nVisible body", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("---\n---\nHidden body", encoding="utf-8")

    monkeypatch.setattr(consent_routes, "_TRACE_ALLOWED_BASES", (allowed,))

    inside_result = asyncio.run(consent_routes.trace_consent(str(inside)))
    outside_result = asyncio.run(consent_routes.trace_consent(str(outside)))

    assert inside_result["exists"] is True
    assert inside_result["body_preview"] == "Visible body"
    assert outside_result["exists"] is False
    assert outside_result["body_preview"] == ""


def test_engine_audit_rejects_traversal_date() -> None:
    from logos.api.routes.engine import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/api/engine/audit?date=2026-05-17%2F..%2F..%2Fescape")

    assert response.status_code == 400


def test_pi_state_paths_reject_absolute_and_traversal_components(tmp_path: Path) -> None:
    from logos.api.routes.pi import _bounded_child_path

    with pytest.raises(ValueError):
        _bounded_child_path(tmp_path, "../escape.json")
    with pytest.raises(ValueError):
        _bounded_child_path(tmp_path, "/tmp/escape.json")


def test_pi_atomic_write_replaces_symlink_without_overwriting_target(tmp_path: Path) -> None:
    from logos.api.routes.pi import _write_json_atomic

    outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
    outside.write_text("outside", encoding="utf-8")
    link = tmp_path / "state.json"
    link.symlink_to(outside)

    _write_json_atomic(link, json.dumps({"ok": True}))

    assert outside.read_text(encoding="utf-8") == "outside"
    assert not link.is_symlink()
    assert json.loads(link.read_text(encoding="utf-8")) == {"ok": True}


def test_studio_feed_resolver_rejects_traversal_absolute_and_symlink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from logos.api.routes import studio

    compositor_dir = tmp_path / "compositor"
    compositor_dir.mkdir()
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"not really a jpeg")
    (compositor_dir / "desk.jpg").symlink_to(outside)
    monkeypatch.setattr(studio, "_COMPOSITOR_DIR", compositor_dir)

    assert studio._safe_compositor_path("../outside") is None
    assert studio._safe_compositor_path("/tmp/outside") is None
    assert studio._safe_compositor_path("desk") is None


def test_studio_preset_paths_reject_absolute_and_traversal_names(tmp_path: Path) -> None:
    from logos.api.routes.studio_effects import _preset_path

    with pytest.raises(ValueError):
        _preset_path(tmp_path, "../escape")
    with pytest.raises(ValueError):
        _preset_path(tmp_path, "/tmp/escape")


def test_studio_create_preset_maps_rejected_sanitized_name_to_400() -> None:
    from fastapi import HTTPException

    from logos.api.routes.studio_effects import create_preset

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_preset({"name": "_"}))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid preset name"


def test_watch_health_summary_date_is_bounded_filename_component() -> None:
    from agents.watch_receiver import HealthSummaryPayload

    with pytest.raises(ValidationError):
        HealthSummaryPayload(device_id="pixel10", date="../2026-03-12")
    with pytest.raises(ValidationError):
        HealthSummaryPayload(device_id="pixel10", date="2026-3-12")


def test_watch_atomic_write_replaces_symlink_without_overwriting_target(tmp_path: Path) -> None:
    from agents.watch_receiver import _atomic_write_text

    outside = tmp_path.parent / f"{tmp_path.name}-watch-outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = tmp_path / "health-2026-03-12.md"
    link.symlink_to(outside)

    _atomic_write_text(link, "safe")

    assert outside.read_text(encoding="utf-8") == "outside"
    assert not link.is_symlink()
    assert link.read_text(encoding="utf-8") == "safe"


def test_consent_contract_id_is_bounded_to_contracts_directory(tmp_path: Path) -> None:
    from logos._governance import ConsentRegistry

    registry = ConsentRegistry()
    contract = registry.create_contract(
        "alice/../../escape",
        frozenset({"presence"}),
        contracts_dir=tmp_path,
    )

    assert contract.id.startswith("contract-alice-escape-")
    assert (tmp_path / f"{contract.id}.yaml").is_file()
    with pytest.raises(ValueError):
        registry.create_contract(
            "alice", frozenset(), contract_id="../escape", contracts_dir=tmp_path
        )
