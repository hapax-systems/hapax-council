"""Workspace graph — parses equipment YAML into a queryable NetworkX MultiDiGraph.

Reads device records from either:
  1. Obsidian vault (~/Documents/Personal/30-areas/studio-inventory/*.md)
  2. Config YAML (config/equipment/*.yaml)

Builds a multi-relational property graph with typed edges:
  - spatial: location, visible_from, adjacent_to
  - signal: feeds, fed_by, connected_to (with protocol attribute)
  - electrical: powered_by
  - logical: part_of, replaces, replaced_by

Query functions mirror the cameras.py pattern: frozen registry loaded once,
derived lookups via functions.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import networkx as nx
import yaml

_VAULT_DIR = Path.home() / "Documents" / "Personal" / "30-areas" / "studio-inventory"
_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config" / "equipment"

_GRAPH: nx.MultiDiGraph | None = None


def _parse_frontmatter(path: Path) -> dict[str, Any] | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        return yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None


def _resolve_wikilink(link: str) -> str:
    return re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", link).strip()


def _load_from_vault(vault_dir: Path) -> nx.MultiDiGraph:
    G = nx.MultiDiGraph()
    for md in vault_dir.glob("*.md"):
        fm = _parse_frontmatter(md)
        if not fm or fm.get("type") != "device":
            continue
        device_id = fm.get("device_id", md.stem)
        node_attrs = {k: v for k, v in fm.items() if k not in ("connections", "type")}
        G.add_node(device_id, **node_attrs)
    return G


def _load_from_config(config_dir: Path) -> nx.MultiDiGraph:
    G = nx.MultiDiGraph()
    for yf in config_dir.glob("*.yaml"):
        data = yaml.safe_load(yf.read_text(encoding="utf-8"))
        if not data or "device_id" not in data:
            continue
        device_id = data["device_id"]
        G.add_node(device_id, **data)

        for conn in data.get("connections", []):
            target = conn.get("target", "")
            edge_type = conn.get("type", "unknown")
            direction = conn.get("direction", "send")
            attrs = {k: v for k, v in conn.items() if k not in ("target",)}
            if direction in ("send", "bidirectional"):
                G.add_edge(device_id, target, key=edge_type, **attrs)
            if direction in ("receive", "bidirectional"):
                G.add_edge(target, device_id, key=edge_type, **attrs)

        placement = data.get("placement", {})
        if placement.get("zone"):
            G.add_edge(device_id, placement["zone"], key="spatial", rel="in_zone")
        if placement.get("surface"):
            G.add_edge(device_id, placement["surface"], key="spatial", rel="on_surface")
    return G


def load_graph(*, force_reload: bool = False) -> nx.MultiDiGraph:
    global _GRAPH
    if _GRAPH is not None and not force_reload:
        return _GRAPH

    if _VAULT_DIR.is_dir() and any(_VAULT_DIR.glob("*.md")):
        G = _load_from_config(_CONFIG_DIR)
        vault_G = _load_from_vault(_VAULT_DIR)
        for node, attrs in vault_G.nodes(data=True):
            if node not in G:
                G.add_node(node, **attrs)
            else:
                G.nodes[node].update(attrs)
    else:
        G = _load_from_config(_CONFIG_DIR)

    _GRAPH = G
    return G


def by_id(device_id: str) -> dict[str, Any] | None:
    G = load_graph()
    if device_id in G:
        return dict(G.nodes[device_id])
    return None


def by_capability(capability: str) -> list[str]:
    G = load_graph()
    return [n for n, d in G.nodes(data=True) if capability in d.get("capabilities", [])]


def by_category(category: str) -> list[str]:
    G = load_graph()
    return [
        n
        for n, d in G.nodes(data=True)
        if d.get("identity", {}).get("category") == category or d.get("category") == category
    ]


def by_zone(zone: str) -> list[str]:
    G = load_graph()
    return [
        n
        for n, d in G.nodes(data=True)
        if d.get("placement", {}).get("zone") == zone or d.get("zone") == zone
    ]


def by_status(status: str) -> list[str]:
    G = load_graph()
    return [
        n
        for n, d in G.nodes(data=True)
        if d.get("acquisition", {}).get("status") == status or d.get("status") == status
    ]


def connected_to(device_id: str) -> list[dict[str, Any]]:
    G = load_graph()
    results = []
    for _, target, data in G.edges(device_id, data=True):
        if data.get("rel") not in ("in_zone", "on_surface"):
            results.append({"target": target, **data})
    for source, _, data in G.in_edges(device_id, data=True):
        if data.get("rel") not in ("in_zone", "on_surface"):
            results.append({"source": source, **data})
    return results


def signal_chain(source: str, target: str) -> list[str] | None:
    G = load_graph()
    SG = G.edge_subgraph(
        [
            (u, v, k)
            for u, v, k, _ in G.edges(keys=True, data=True)
            if k in ("audio", "midi", "usb", "cv")
        ]
    )
    try:
        return nx.shortest_path(SG, source, target)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None


def all_devices() -> list[dict[str, Any]]:
    G = load_graph()
    devices = []
    for n, d in G.nodes(data=True):
        if d.get("schema_version") or d.get("type") == "device":
            devices.append({"device_id": n, **d})
    return devices


def summary() -> dict[str, Any]:
    G = load_graph()
    devices = all_devices()
    return {
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
        "devices": len(devices),
        "categories": list(
            {d.get("identity", {}).get("category", d.get("category", "unknown")) for d in devices}
        ),
        "zones": list(
            {
                d.get("placement", {}).get("zone", d.get("zone"))
                for d in devices
                if d.get("placement", {}).get("zone") or d.get("zone")
            }
        ),
    }
