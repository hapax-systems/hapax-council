def test_graph_has_14_nodes():
    from shared.sheaf_graph import build_scm_graph

    assert len(build_scm_graph().nodes) == 14


def test_graph_has_edges():
    from shared.sheaf_graph import build_scm_graph

    assert len(build_scm_graph().edges) >= 18


def test_cognitive_core_connected():
    from shared.sheaf_graph import build_scm_graph

    G = build_scm_graph()
    for node in ["dmn", "imagination", "stimmung", "reverie"]:
        assert G.degree(node) >= 3, f"{node} should be well-connected"
