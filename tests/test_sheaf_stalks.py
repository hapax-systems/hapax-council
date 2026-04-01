def test_linearize_stimmung():
    from shared.sheaf_stalks import linearize_stimmung

    state = {
        "overall_stance": "nominal",
        "health": {"value": 0.1, "trend": "stable", "freshness_s": 5.0},
    }
    vec = linearize_stimmung(state)
    assert isinstance(vec, list)
    assert all(isinstance(v, float) for v in vec)
    assert len(vec) == 31  # 10 dims × 3 fields + 1 stance


def test_linearize_empty():
    from shared.sheaf_stalks import linearize_stimmung

    assert all(v == 0.0 for v in linearize_stimmung({}))
