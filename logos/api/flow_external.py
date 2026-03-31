"""logos/api/flow_external.py — Build synthetic external nodes from recent events."""

from __future__ import annotations

import time

from logos.event_bus import EventBus

_EXTERNAL_NODES = {
    "llm": {"label": "LLM Gateway", "pipeline_layer": "external"},
    "qdrant": {"label": "Vector DB", "pipeline_layer": "external"},
    "pi_fleet": {"label": "Pi Fleet", "pipeline_layer": "external"},
}

_KIND_TO_NODE = {
    "llm.call": "llm",
    "qdrant.op": "qdrant",
    "pi.detection": "pi_fleet",
}


def build_external_nodes(
    bus: EventBus,
    since: float | None = None,
) -> tuple[list[dict], list[dict]]:
    if since is None:
        since = time.time() - 60
    events = bus.recent(since=since)
    active_kinds: set[str] = set()
    edge_pairs: dict[tuple[str, str], str] = {}

    for ev in events:
        node_id = _KIND_TO_NODE.get(ev.kind)
        if node_id:
            active_kinds.add(ev.kind)
            edge_pairs[(ev.source, ev.target)] = ev.label

    nodes = []
    for kind, node_id in _KIND_TO_NODE.items():
        if kind in active_kinds:
            defn = _EXTERNAL_NODES[node_id]
            count = sum(1 for e in events if _KIND_TO_NODE.get(e.kind) == node_id)
            last_label = ""
            for e in reversed(events):
                if _KIND_TO_NODE.get(e.kind) == node_id:
                    last_label = e.label
                    break
            nodes.append(
                {
                    "id": node_id,
                    "label": defn["label"],
                    "status": "active",
                    "age_s": 0,
                    "pipeline_layer": defn["pipeline_layer"],
                    "metrics": {"recent_count": count, "last_label": last_label},
                }
            )

    edges = []
    for (source, target), label in edge_pairs.items():
        edges.append(
            {
                "source": source,
                "target": target,
                "active": True,
                "label": label,
                "edge_type": "emergent",
            }
        )

    return nodes, edges
