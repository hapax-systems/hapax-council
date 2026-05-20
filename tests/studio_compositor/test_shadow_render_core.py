"""Tests for agents.studio_compositor.shadow_render_core."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from agents.studio_compositor.shadow_render_core import (
    ShadowRenderCore,
    SourceClass,
    SourceContribution,
    SourceHealth,
    shadow_enabled,
)


def test_shadow_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_RENDER_CORE_SHADOW", raising=False)
    assert not shadow_enabled()


def test_shadow_enabled_when_set(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_RENDER_CORE_SHADOW", "1")
    assert shadow_enabled()


def test_core_produces_frames(tmp_path: Path) -> None:
    core = ShadowRenderCore(output_dir=tmp_path, target_fps=60)
    t = threading.Thread(target=core.run, daemon=True)
    t.start()
    time.sleep(0.15)
    core.stop()
    t.join(timeout=2)

    assert core.sequence > 0
    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.exists()
    data = json.loads(manifest_path.read_text())
    assert data["sequence"] == core.sequence
    assert "timestamp_ns" in data
    assert "render_cost_us" in data


def test_core_with_registered_source(tmp_path: Path) -> None:
    core = ShadowRenderCore(output_dir=tmp_path, target_fps=60)
    now_ns = time.monotonic_ns()
    core.register_source(
        SourceContribution(
            source_id="test-camera",
            source_class=SourceClass.CAMERA,
            health=SourceHealth.FRESH,
            width=1920,
            height=1080,
            last_update_ns=now_ns,
        )
    )

    t = threading.Thread(target=core.run, daemon=True)
    t.start()
    time.sleep(0.1)
    core.stop()
    t.join(timeout=2)

    data = json.loads((tmp_path / "manifest.json").read_text())
    assert data["source_count"] == 1
    assert data["sources"][0]["source_id"] == "test-camera"
    assert data["sources"][0]["health"] == "fresh"


def test_stale_source_degrades(tmp_path: Path) -> None:
    core = ShadowRenderCore(output_dir=tmp_path, target_fps=60)
    old_ns = time.monotonic_ns() - int(5e9)
    core.register_source(
        SourceContribution(
            source_id="stale-cam",
            source_class=SourceClass.CAMERA,
            health=SourceHealth.FRESH,
            width=640,
            height=480,
            last_update_ns=old_ns,
        )
    )

    t = threading.Thread(target=core.run, daemon=True)
    t.start()
    time.sleep(0.1)
    core.stop()
    t.join(timeout=2)

    data = json.loads((tmp_path / "manifest.json").read_text())
    assert data["degraded_count"] == 1
    assert "stale-cam" in data["degraded_sources"]
    assert data["sources"][0]["health"] == "stale"


def test_offline_source_with_no_update(tmp_path: Path) -> None:
    core = ShadowRenderCore(output_dir=tmp_path, target_fps=60)
    core.register_source(
        SourceContribution(
            source_id="never-updated",
            source_class=SourceClass.WARD,
            health=SourceHealth.OFFLINE,
            width=320,
            height=240,
            last_update_ns=0,
        )
    )

    t = threading.Thread(target=core.run, daemon=True)
    t.start()
    time.sleep(0.1)
    core.stop()
    t.join(timeout=2)

    data = json.loads((tmp_path / "manifest.json").read_text())
    assert data["sources"][0]["health"] == "offline"


def test_update_source_refreshes_timestamp(tmp_path: Path) -> None:
    core = ShadowRenderCore(output_dir=tmp_path, target_fps=60)
    core.register_source(
        SourceContribution(
            source_id="refreshable",
            source_class=SourceClass.CAMERA,
            health=SourceHealth.FRESH,
            width=1920,
            height=1080,
            last_update_ns=0,
        )
    )
    core.update_source("refreshable", timestamp_ns=time.monotonic_ns())

    t = threading.Thread(target=core.run, daemon=True)
    t.start()
    time.sleep(0.1)
    core.stop()
    t.join(timeout=2)

    data = json.loads((tmp_path / "manifest.json").read_text())
    assert data["sources"][0]["health"] == "fresh"


def test_empty_sources_produces_valid_manifest(tmp_path: Path) -> None:
    core = ShadowRenderCore(output_dir=tmp_path, target_fps=60)
    t = threading.Thread(target=core.run, daemon=True)
    t.start()
    time.sleep(0.1)
    core.stop()
    t.join(timeout=2)

    data = json.loads((tmp_path / "manifest.json").read_text())
    assert data["source_count"] == 0
    assert data["degraded_count"] == 0
