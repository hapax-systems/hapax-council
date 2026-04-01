"""Reading-dependency graph for the 14-node SCM."""

from __future__ import annotations

import networkx as nx

SCM_NODES = [
    "ir_perception",
    "contact_mic",
    "voice_daemon",
    "dmn",
    "imagination",
    "stimmung",
    "temporal_bonds",
    "apperception",
    "reactive_engine",
    "compositor",
    "reverie",
    "voice_pipeline",
    "content_resolver",
    "consent_engine",
]

SCM_EDGES = [
    ("dmn", "stimmung"),
    ("dmn", "voice_daemon"),
    ("dmn", "consent_engine"),
    ("dmn", "reverie"),
    ("dmn", "imagination"),
    ("imagination", "dmn"),
    ("imagination", "stimmung"),
    ("content_resolver", "imagination"),
    ("reverie", "imagination"),
    ("reverie", "stimmung"),
    ("reverie", "dmn"),
    ("reverie", "content_resolver"),
    ("reverie", "contact_mic"),
    ("voice_daemon", "stimmung"),
    ("voice_daemon", "dmn"),
    ("voice_daemon", "compositor"),
    ("apperception", "dmn"),
    ("compositor", "voice_daemon"),
    ("stimmung", "voice_daemon"),
    ("temporal_bonds", "voice_daemon"),
    ("ir_perception", "stimmung"),
    ("ir_perception", "apperception"),
    ("reactive_engine", "stimmung"),
    ("voice_pipeline", "voice_daemon"),
]


def build_scm_graph() -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_nodes_from(SCM_NODES)
    G.add_edges_from(SCM_EDGES)
    return G
