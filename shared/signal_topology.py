"""Signal topology — bridges equipment registry connections with live PipeWire graph.

Provides signal chain tracing across the static equipment graph (from
config/equipment/*.yaml connection fields) and the dynamic PipeWire
graph (from pw-dump). Answers: "trace the signal path from microphone
to broadcast output."

The static graph represents intended wiring (what SHOULD be connected).
The dynamic overlay represents actual wiring (what IS connected right now).
Discrepancies between the two are detectable.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

import networkx as nx

from shared import workspace_graph


def _get_pipewire_links() -> list[dict[str, Any]]:
    try:
        result = subprocess.run(
            ["pw-dump"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []
        objects = json.loads(result.stdout)
        return [o for o in objects if o.get("type") == "PipeWire:Interface:Link"]
    except (subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError):
        return []


def _get_pipewire_nodes() -> dict[int, dict[str, Any]]:
    try:
        result = subprocess.run(
            ["pw-dump"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return {}
        objects = json.loads(result.stdout)
        nodes = {}
        for o in objects:
            if o.get("type") == "PipeWire:Interface:Node":
                nodes[o.get("id", 0)] = o.get("info", {}).get("props", {})
        return nodes
    except (subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError):
        return {}


def static_signal_graph() -> nx.DiGraph:
    G = workspace_graph.load_graph()
    SG = nx.DiGraph()

    for u, v, key, data in G.edges(keys=True, data=True):
        if key in ("audio", "midi", "usb", "cv", "hdmi", "analog_clock"):
            SG.add_edge(
                u,
                v,
                protocol=key,
                **{k: v for k, v in data.items() if k != "key"},
            )

    return SG


def trace_path(source: str, destination: str) -> list[str] | None:
    SG = static_signal_graph()
    try:
        return nx.shortest_path(SG, source, destination)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None


def all_signal_paths_from(device_id: str) -> dict[str, list[str]]:
    SG = static_signal_graph()
    if device_id not in SG:
        return {}
    paths = {}
    for target in SG.nodes():
        if target == device_id:
            continue
        try:
            path = nx.shortest_path(SG, device_id, target)
            if len(path) > 1:
                paths[target] = path
        except nx.NetworkXNoPath:
            continue
    return paths


def signal_neighbors(device_id: str) -> dict[str, list[dict[str, Any]]]:
    SG = static_signal_graph()
    result: dict[str, list[dict[str, Any]]] = {"sends_to": [], "receives_from": []}

    for _, target, data in SG.out_edges(device_id, data=True):
        result["sends_to"].append({"target": target, **data})

    for source, _, data in SG.in_edges(device_id, data=True):
        result["receives_from"].append({"source": source, **data})

    return result


def live_pipewire_graph() -> nx.DiGraph:
    nodes = _get_pipewire_nodes()
    links = _get_pipewire_links()
    G = nx.DiGraph()

    for nid, props in nodes.items():
        name = props.get("node.name", f"node-{nid}")
        G.add_node(name, pw_id=nid, **props)

    for link in links:
        info = link.get("info", {})
        props = info.get("props", {})
        out_node = props.get("link.output.node")
        in_node = props.get("link.input.node")
        if out_node is not None and in_node is not None:
            out_name = nodes.get(out_node, {}).get("node.name", f"node-{out_node}")
            in_name = nodes.get(in_node, {}).get("node.name", f"node-{in_node}")
            G.add_edge(out_name, in_name, pw_link_id=link.get("id"))

    return G


def wiring_discrepancies() -> list[dict[str, Any]]:
    static = static_signal_graph()
    live = live_pipewire_graph()

    discrepancies = []

    for u, v, data in static.edges(data=True):
        protocol = data.get("protocol", "unknown")
        if protocol in ("audio", "usb"):
            u_pattern = _device_to_pw_pattern(u)
            v_pattern = _device_to_pw_pattern(v)
            if u_pattern and v_pattern:
                found = False
                for lu in live.nodes():
                    if u_pattern.lower() in lu.lower():
                        for lv in live.successors(lu):
                            if v_pattern.lower() in lv.lower():
                                found = True
                                break
                    if found:
                        break
                if not found:
                    discrepancies.append(
                        {
                            "type": "missing_live_link",
                            "static_source": u,
                            "static_target": v,
                            "protocol": protocol,
                        }
                    )

    return discrepancies


def _device_to_pw_pattern(device_id: str) -> str | None:
    device = workspace_graph.by_id(device_id)
    if not device:
        return None
    midi = device.get("specifications", {}).get("midi", {})
    pattern = midi.get("alsa_card_name_pattern")
    if pattern:
        return pattern
    identity = device.get("identity", {})
    return identity.get("model", "").split(" ")[0] if identity.get("model") else None
