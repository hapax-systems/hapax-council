"""System organ to visual representation mapping.

Loads the organ-visual map from config and provides typed accessors
for compositor wards, shader nodes, Logos panels, and Stimmung channels
associated with each system subsystem.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_MAP_PATH = Path(__file__).resolve().parents[1] / "config" / "system-organ-visual-map.yaml"


@lru_cache(maxsize=1)
def load_organ_visual_map(path: Path = _MAP_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def organ_ids() -> list[str]:
    data = load_organ_visual_map()
    return [o["id"] for o in data.get("organs", [])]


def organ_by_id(organ_id: str) -> dict[str, Any] | None:
    data = load_organ_visual_map()
    for o in data.get("organs", []):
        if o["id"] == organ_id:
            return o
    return None


def visual_techniques_for_organ(organ_id: str) -> list[dict[str, Any]]:
    organ = organ_by_id(organ_id)
    if organ is None:
        return []
    return organ.get("visual_representations", [])


def organs_using_technique(technique: str) -> list[str]:
    data = load_organ_visual_map()
    result: list[str] = []
    for o in data.get("organs", []):
        for vr in o.get("visual_representations", []):
            if vr.get("technique") == technique:
                result.append(o["id"])
                break
    return result


def ward_ids() -> list[str]:
    data = load_organ_visual_map()
    wards: list[str] = []
    for o in data.get("organs", []):
        for vr in o.get("visual_representations", []):
            if vr.get("technique") == "cairo_ward" and vr.get("ward_id"):
                wards.append(vr["ward_id"])
    return wards


def shader_node_ids() -> list[str]:
    data = load_organ_visual_map()
    nodes: list[str] = []
    for o in data.get("organs", []):
        for vr in o.get("visual_representations", []):
            if vr.get("technique") == "shader_node":
                nodes.extend(vr.get("node_ids", []))
    return nodes
