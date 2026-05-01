"""Tests for ``agents.citable_nexus.citation_graph``."""

from __future__ import annotations

import json

from agents.citable_nexus.citation_graph import (
    CitationGraph,
    GraphEdge,
    GraphNode,
    compose_graph,
)
from agents.citable_nexus.datacite_snapshot import (
    DataCiteSnapshot,
    RelatedIdentifier,
    Work,
)


def _work(
    doi: str = "10.5281/zenodo.1",
    related: list[RelatedIdentifier] | None = None,
) -> Work:
    return Work(
        doi=doi,
        landing_page_url=f"https://doi.org/{doi}",
        citation_count=0,
        related_identifiers=related or [],
    )


def _snapshot(works: list[Work]) -> DataCiteSnapshot:
    return DataCiteSnapshot(
        snapshot_date="2026-05-01",
        orcid_url="https://orcid.org/test",
        works=works,
    )


# ── Graph composition ─────────────────────────────────────────────────


class TestComposeGraph:
    def test_empty_snapshot_yields_empty_graph(self):
        snap = DataCiteSnapshot(snapshot_date=None, orcid_url=None)
        graph = compose_graph(snap)
        assert graph.nodes == []
        assert graph.edges == []

    def test_snapshot_with_zero_works_yields_empty_graph(self):
        snap = _snapshot(works=[])
        graph = compose_graph(snap)
        assert graph.nodes == []
        assert graph.edges == []

    def test_single_work_no_relations_yields_one_node(self):
        snap = _snapshot([_work(doi="10.5281/zenodo.1")])
        graph = compose_graph(snap)
        assert len(graph.nodes) == 1
        assert graph.nodes[0].id == "10.5281/zenodo.1"
        assert graph.nodes[0].node_type == "work"
        assert graph.edges == []

    def test_work_with_one_relation_yields_two_nodes_one_edge(self):
        rel = RelatedIdentifier(
            related_identifier="https://osf.io/abc",
            relation_type="IsVersionOf",
        )
        snap = _snapshot([_work(doi="10.5281/zenodo.1", related=[rel])])
        graph = compose_graph(snap)
        assert len(graph.nodes) == 2
        assert len(graph.edges) == 1
        assert graph.edges[0].source == "10.5281/zenodo.1"
        assert graph.edges[0].target == "https://osf.io/abc"
        assert graph.edges[0].relation_type == "IsVersionOf"

    def test_node_types_are_work_and_related(self):
        rel = RelatedIdentifier(
            related_identifier="https://osf.io/abc",
            relation_type="IsVersionOf",
        )
        snap = _snapshot([_work(related=[rel])])
        graph = compose_graph(snap)
        types = {n.node_type for n in graph.nodes}
        assert types == {"work", "related"}

    def test_dedup_related_identifier_across_works(self):
        """Same related-identifier URL on two works → one node, two edges."""
        shared_rel = RelatedIdentifier(
            related_identifier="https://hapax.research",
            relation_type="IsRelatedTo",
        )
        snap = _snapshot(
            [
                _work(doi="10.5281/zenodo.1", related=[shared_rel]),
                _work(doi="10.5281/zenodo.2", related=[shared_rel]),
            ]
        )
        graph = compose_graph(snap)
        # 3 nodes: 2 works + 1 shared related-identifier
        assert len(graph.nodes) == 3
        # 2 edges: one from each work to the shared relation
        assert len(graph.edges) == 2
        assert {e.source for e in graph.edges} == {"10.5281/zenodo.1", "10.5281/zenodo.2"}

    def test_empty_related_identifier_target_is_skipped(self):
        rel = RelatedIdentifier(
            related_identifier="",
            relation_type="IsVersionOf",
        )
        snap = _snapshot([_work(related=[rel])])
        graph = compose_graph(snap)
        # The work node is kept; the empty-target relation is dropped.
        assert len(graph.nodes) == 1
        assert graph.edges == []

    def test_missing_relation_type_falls_back_to_is_related_to(self):
        rel = RelatedIdentifier(
            related_identifier="https://osf.io/abc",
            relation_type="",
        )
        snap = _snapshot([_work(related=[rel])])
        graph = compose_graph(snap)
        assert graph.edges[0].relation_type == "IsRelatedTo"


# ── Cytoscape elements rendering ─────────────────────────────────────


class TestToCytoscapeElements:
    def test_empty_graph_yields_empty_elements(self):
        graph = CitationGraph()
        assert graph.to_cytoscape_elements() == []

    def test_node_payload_shape(self):
        graph = CitationGraph(
            nodes=[GraphNode(id="n1", label="Node 1", node_type="work")],
            edges=[],
        )
        elements = graph.to_cytoscape_elements()
        assert len(elements) == 1
        assert elements[0] == {"data": {"id": "n1", "label": "Node 1", "type": "work"}}

    def test_edge_payload_shape(self):
        graph = CitationGraph(
            nodes=[
                GraphNode(id="a", label="A", node_type="work"),
                GraphNode(id="b", label="B", node_type="related"),
            ],
            edges=[
                GraphEdge(source="a", target="b", relation_type="IsVersionOf"),
            ],
        )
        elements = graph.to_cytoscape_elements()
        # 2 nodes + 1 edge.
        assert len(elements) == 3
        edge_element = elements[2]
        assert edge_element["data"]["source"] == "a"
        assert edge_element["data"]["target"] == "b"
        assert edge_element["data"]["label"] == "IsVersionOf"
        # Edge id is auto-generated and unique.
        assert edge_element["data"]["id"] == "edge-0"

    def test_multiple_edges_have_unique_ids(self):
        graph = CitationGraph(
            nodes=[],
            edges=[
                GraphEdge(source="a", target="b", relation_type="X"),
                GraphEdge(source="a", target="c", relation_type="Y"),
                GraphEdge(source="b", target="c", relation_type="Z"),
            ],
        )
        elements = graph.to_cytoscape_elements()
        edge_ids = {e["data"]["id"] for e in elements}
        assert edge_ids == {"edge-0", "edge-1", "edge-2"}


# ── Renderer integration ──────────────────────────────────────────────


class TestRendererIntegration:
    def test_render_citation_graph_with_snapshot(self):
        rel = RelatedIdentifier(
            related_identifier="https://osf.io/b89ga",
            relation_type="IsVersionOf",
        )
        snap = _snapshot([_work(doi="10.17605/osf.io/5c2kr", related=[rel])])

        from agents.citable_nexus.renderer import render_citation_graph_page

        page = render_citation_graph_page(snap)
        assert page.path == "/citation-graph"
        # Embedded JSON contains the graph elements.
        assert 'id="graph-data"' in page.body_html
        assert "10.17605/osf.io/5c2kr" in page.body_html
        assert "IsVersionOf" in page.body_html
        # Cytoscape script tag present.
        assert "cytoscape" in page.body_html.lower()

    def test_render_citation_graph_placeholder_when_absent(self):
        snap = DataCiteSnapshot(snapshot_date=None, orcid_url=None)

        from agents.citable_nexus.renderer import render_citation_graph_page

        page = render_citation_graph_page(snap)
        assert page.path == "/citation-graph"
        assert "snapshot-placeholder" in page.body_html
        assert "configure-orcid.sh" in page.body_html
        # No graph-data script when absent.
        assert 'id="graph-data"' not in page.body_html

    def test_embedded_json_is_valid_cytoscape_elements(self):
        rel = RelatedIdentifier(
            related_identifier="https://osf.io/b89ga",
            relation_type="IsVersionOf",
        )
        snap = _snapshot([_work(doi="10.17605/osf.io/5c2kr", related=[rel])])

        from agents.citable_nexus.renderer import render_citation_graph_page

        page = render_citation_graph_page(snap)
        # Pull the JSON out of the embedded script tag.
        marker_start = page.body_html.index('id="graph-data">') + len('id="graph-data">')
        marker_end = page.body_html.index("</script>", marker_start)
        json_text = page.body_html[marker_start:marker_end]
        elements = json.loads(json_text)
        # Cytoscape expects each element as a dict with "data".
        assert all("data" in e for e in elements)
        # 2 nodes + 1 edge for our fixture.
        assert len(elements) == 3
