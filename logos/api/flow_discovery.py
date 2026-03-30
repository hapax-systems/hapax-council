"""Dynamic flow node discovery from agent manifests."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

MANIFESTS_DIR = Path(__file__).resolve().parent.parent.parent / "agents" / "manifests"
LAYER_ORDER = {"perception": 0, "cognition": 1, "output": 2}


def _expand_home(path: str) -> str:
    if path.startswith("~/"):
        from os.path import expanduser

        return expanduser(path)
    return path


def _read_json(path: str) -> dict | None:
    try:
        return json.loads(Path(_expand_home(path)).read_text())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _file_age(path: str) -> float:
    """Age in seconds since file was last modified."""
    try:
        return time.time() - Path(_expand_home(path)).stat().st_mtime
    except OSError:
        return 9999.0


def _status(age: float, stale_threshold: float = 10.0) -> str:
    if age < stale_threshold:
        return "active"
    if age < 30.0:
        return "stale"
    return "offline"


def read_state_metrics(path: str, metric_keys: list[str]) -> dict:
    """Read specific metric keys from a JSON state file."""
    if not path:
        return {}
    data = _read_json(path)
    if data is None:
        return {}
    result = {}
    for key in metric_keys:
        if key in data:
            val = data[key]
            if isinstance(val, dict) and "value" in val:
                val = val["value"]
            result[key] = val
    return result


def discover_pipeline_nodes(manifests_dir: Path | None = None) -> list[dict]:
    """Discover pipeline nodes from agent manifests.

    Only agents with ``pipeline_role`` are included.
    """
    if manifests_dir is None:
        manifests_dir = MANIFESTS_DIR

    nodes: list[dict] = []
    for path in sorted(manifests_dir.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text()) or {}
        except Exception:
            continue

        role = raw.get("pipeline_role")
        if not role:
            continue

        layer = raw.get("pipeline_layer", "output")
        state_cfg = raw.get("pipeline_state") or {}
        state_path = state_cfg.get("path", "")
        metric_keys = state_cfg.get("metrics", [])
        stale_threshold = state_cfg.get("stale_threshold", 10.0)

        age = _file_age(state_path) if state_path else 9999.0
        metrics = read_state_metrics(state_path, metric_keys)

        nodes.append(
            {
                "id": raw.get("id", path.stem),
                "label": raw.get("name", raw.get("id", path.stem)),
                "status": _status(age, stale_threshold),
                "age_s": round(age, 1),
                "metrics": metrics,
                "pipeline_role": role,
                "pipeline_layer": layer,
                "gates": raw.get("gates", []),
                "_state_path": state_path,
            }
        )

    return nodes


def build_declared_edges(nodes: list[dict]) -> list[dict]:
    """Build edges from layer adjacency rules and gate declarations."""
    edges: list[dict] = []
    node_map = {n["id"]: n for n in nodes}

    by_layer: dict[str, list[dict]] = {}
    for n in nodes:
        by_layer.setdefault(n["pipeline_layer"], []).append(n)

    layer_pairs = [("perception", "cognition"), ("cognition", "output")]
    for src_layer, dst_layer in layer_pairs:
        for src in by_layer.get(src_layer, []):
            for dst in by_layer.get(dst_layer, []):
                active = src["age_s"] < 30
                edges.append(
                    {
                        "source": src["id"],
                        "target": dst["id"],
                        "active": active,
                        "label": f"{src_layer}\u2192{dst_layer}",
                    }
                )

    for n in nodes:
        for gate_target in n.get("gates", []):
            if gate_target in node_map:
                edges.append(
                    {
                        "source": n["id"],
                        "target": gate_target,
                        "active": n["age_s"] < 30,
                        "label": "gate",
                    }
                )

    return edges


def composite_edges(
    declared: list[dict],
    observed: set[tuple[str, str]],
) -> list[dict]:
    """Merge declared and observed edges, classify each.

    ``edge_type``:
    - confirmed: declared edge whose source node has fresh state data (active=True),
      OR explicitly observed in SHM flow
    - emergent: observed in SHM but not declared (unexpected data flow)
    - dormant: declared but source node is stale/offline
    """
    result: list[dict] = []
    declared_pairs: set[tuple[str, str]] = set()

    for edge in declared:
        pair = (edge["source"], edge["target"])
        declared_pairs.add(pair)
        if pair in observed or edge.get("active", False):
            edge_type = "confirmed"
        else:
            edge_type = "dormant"
        result.append({**edge, "edge_type": edge_type})

    for src, tgt in observed:
        if (src, tgt) not in declared_pairs:
            result.append(
                {
                    "source": src,
                    "target": tgt,
                    "active": True,
                    "label": "observed",
                    "edge_type": "emergent",
                }
            )

    return result
