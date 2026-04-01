def test_betti_0_connected():
    from shared.sheaf_graph import build_scm_graph
    from shared.topology_health import compute_betti_numbers

    b0, b1 = compute_betti_numbers(build_scm_graph())
    assert b0 == 1


def test_betti_1_has_cycles():
    from shared.sheaf_graph import build_scm_graph
    from shared.topology_health import compute_betti_numbers

    _, b1 = compute_betti_numbers(build_scm_graph())
    assert b1 >= 3


def test_topological_stability():
    from shared.sheaf_graph import build_scm_graph
    from shared.topology_health import compute_topological_stability

    result = compute_topological_stability(build_scm_graph())
    assert 0.0 < result["stability"] < 1.0
    assert result["worst_node"] != "none"
    assert result["betti"][0] == 1
