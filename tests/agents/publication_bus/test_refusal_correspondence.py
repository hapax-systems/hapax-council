"""Correspondence checks for REFUSED publication-bus surfaces."""

from __future__ import annotations

import importlib
from pathlib import Path

import yaml

from agents.publication_bus.publisher_kit.refused import REFUSED_PUBLISHER_CLASSES
from agents.publication_bus.surface_registry import (
    SURFACE_REGISTRY,
    AutomationStatus,
    refused_surfaces,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REFUSAL_REGISTRY = REPO_ROOT / "docs" / "refusal-briefs" / "_registry.yaml"


def _load_refusal_registry() -> dict[str, dict[str, str]]:
    data = yaml.safe_load(REFUSAL_REGISTRY.read_text(encoding="utf-8"))
    return data["refusals"]


def _resolve_class(dotted: str) -> type:
    module_name, class_name = dotted.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def test_refusal_registry_covers_every_refused_surface() -> None:
    registry = _load_refusal_registry()
    pure_refusals = {k for k, v in registry.items() if not v.get("receive_only_exception")}
    assert pure_refusals == set(refused_surfaces())


def test_every_refused_surface_link_points_to_existing_brief() -> None:
    registry = _load_refusal_registry()
    for surface in refused_surfaces():
        spec = SURFACE_REGISTRY[surface]
        assert spec.automation_status == AutomationStatus.REFUSED
        assert spec.refusal_link is not None
        assert registry[surface]["brief"] == spec.refusal_link

        brief_path = REPO_ROOT / spec.refusal_link
        assert brief_path.exists(), f"{surface} refusal_link dangles: {spec.refusal_link}"
        body = brief_path.read_text(encoding="utf-8")
        assert "Status:** REFUSED" in body
        assert f"Surface registry entry:** `{surface}`" in body


def test_every_refused_publisher_maps_to_refused_surface_and_registry_entry() -> None:
    registry = _load_refusal_registry()
    by_surface = {cls.surface_name: cls for cls in REFUSED_PUBLISHER_CLASSES}
    assert set(by_surface) == set(refused_surfaces())

    for surface, cls in by_surface.items():
        assert _resolve_class(registry[surface]["publisher_class"]) is cls
        assert SURFACE_REGISTRY[surface].automation_status == AutomationStatus.REFUSED


def test_registry_entries_have_task_and_lifecycle_probe() -> None:
    for surface, entry in _load_refusal_registry().items():
        assert entry["cc_task"], f"{surface} missing cc_task"
        assert entry["lifecycle_probe"], f"{surface} missing lifecycle_probe"
