from agents.publish_orchestrator.orchestrator import SurfaceResult


def test_surface_result_permalink():
    """Verify SurfaceResult holds and serializes permalink."""
    res = SurfaceResult(
        slug="test",
        surface="mastodon",
        result="ok",
        timestamp="2026",
        permalink="https://mastodon.social/@test",
    )

    d = res.to_dict()
    assert d["permalink"] == "https://mastodon.social/@test"
    assert res.permalink == "https://mastodon.social/@test"
