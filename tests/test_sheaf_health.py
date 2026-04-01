def test_consistent_system():
    from shared.sheaf_health import compute_consistency_radius

    assert compute_consistency_radius([0.0, 0.0, 0.0]) == 0.0


def test_inconsistent_system():
    from shared.sheaf_health import compute_consistency_radius

    assert compute_consistency_radius([0.8, 0.5, 0.9]) > 0.5


def test_full_sheaf_health():
    from shared.sheaf_health import compute_sheaf_health

    traces = {
        "stimmung": {
            "overall_stance": "nominal",
            "health": {"value": 0.1, "trend": "stable", "freshness_s": 5.0},
        },
        "dmn": {"stance": "nominal"},
        "imagination": {"salience": 0.3},
        "perception": {},
    }
    result = compute_sheaf_health(traces)
    assert "consistency_radius" in result
    assert "h1_dimension" in result
    assert isinstance(result["consistency_radius"], float)
