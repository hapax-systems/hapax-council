"""Citation-graph composition for the /citation-graph page.

Builds a Cytoscape.js-shaped node + edge graph from a
:class:`agents.citable_nexus.datacite_snapshot.DataCiteSnapshot`.
Nodes: each work DOI + each ``relatedIdentifier`` URL (deduped
across works). Edges: typed by the snapshot's ``relationType`` field
(``IsVersionOf``, ``IsRequiredBy``, ``IsObsoletedBy``, etc.).

The graph is rendered into the ``/citation-graph`` page via embedded
``<script type="application/json">`` so it's degradeable when JS is
disabled (the JSON is human-readable + machine-extractable). When JS
is enabled, Cytoscape.js loads the JSON and lays out the graph.

Compositionally pure: takes a snapshot, returns a graph; no
filesystem I/O. Tests inject fixture snapshots directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agents.citable_nexus.datacite_snapshot import DataCiteSnapshot


@dataclass(frozen=True)
class GraphNode:
    """One node in the citation graph."""

    id: str
    """Stable identifier — the DOI string for work nodes, the
    relatedIdentifier URL for related-identifier nodes."""
    label: str
    """Human-readable label for the node."""
    node_type: str
    """``work`` for operator-authored DOIs; ``related`` for related-
    identifier targets."""


@dataclass(frozen=True)
class GraphEdge:
    """One edge in the citation graph."""

    source: str
    """Source node id (a work DOI)."""
    target: str
    """Target node id (a related-identifier URL)."""
    relation_type: str
    """DataCite relation type, e.g. ``IsVersionOf``, ``IsRequiredBy``."""


@dataclass(frozen=True)
class CitationGraph:
    """The composed graph payload — Cytoscape.js elements shape."""

    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    def to_cytoscape_elements(self) -> list[dict]:
        """Render to Cytoscape.js ``elements`` array.

        Each node becomes ``{"data": {"id", "label", "type"}}``;
        each edge becomes ``{"data": {"id", "source", "target",
        "label"}}`` (Cytoscape's id is required and unique).
        """
        elements: list[dict] = []
        for node in self.nodes:
            elements.append(
                {
                    "data": {
                        "id": node.id,
                        "label": node.label,
                        "type": node.node_type,
                    }
                }
            )
        for i, edge in enumerate(self.edges):
            elements.append(
                {
                    "data": {
                        "id": f"edge-{i}",
                        "source": edge.source,
                        "target": edge.target,
                        "label": edge.relation_type,
                    }
                }
            )
        return elements


def compose_graph(snapshot: DataCiteSnapshot) -> CitationGraph:
    """Build a :class:`CitationGraph` from a DataCite snapshot.

    Empty snapshot → empty graph. Related-identifier targets that
    appear under multiple works are deduped (same id, single node);
    the inbound edges from each work are kept.
    """
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    seen_node_ids: set[str] = set()

    for work in snapshot.works:
        if work.doi not in seen_node_ids:
            nodes.append(
                GraphNode(
                    id=work.doi,
                    label=work.doi,
                    node_type="work",
                )
            )
            seen_node_ids.add(work.doi)

        for rel in work.related_identifiers:
            target = rel.related_identifier
            if not target:
                continue
            if target not in seen_node_ids:
                nodes.append(
                    GraphNode(
                        id=target,
                        label=target,
                        node_type="related",
                    )
                )
                seen_node_ids.add(target)
            edges.append(
                GraphEdge(
                    source=work.doi,
                    target=target,
                    relation_type=rel.relation_type or "IsRelatedTo",
                )
            )

    return CitationGraph(nodes=nodes, edges=edges)


__all__ = [
    "CitationGraph",
    "GraphEdge",
    "GraphNode",
    "compose_graph",
]
