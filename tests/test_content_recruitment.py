"""Tests for content recruitment — content appears only via affordance matching."""

from agents.reverie._affordances import ALL_CONTENT_AFFORDANCES


def test_content_affordances_use_gibson_verbs():
    """Content affordance descriptions use perception/expression verbs, not implementation."""
    for name, desc, _ops in ALL_CONTENT_AFFORDANCES:
        assert "qdrant" not in desc.lower(), f"{name}: mentions implementation (qdrant)"
        assert "jpeg" not in desc.lower(), f"{name}: mentions implementation (jpeg)"
        assert "shm" not in desc.lower(), f"{name}: mentions implementation (shm)"


def test_content_affordances_have_latency_class():
    """Each content affordance specifies fast or slow latency."""
    from agents.reverie._affordances import build_reverie_pipeline_affordances

    records = build_reverie_pipeline_affordances()
    content_records = [r for r in records if r.name.startswith("content.")]
    assert len(content_records) >= 5
    for r in content_records:
        assert r.operational.latency_class in ("fast", "slow"), (
            f"{r.name}: latency_class must be 'fast' or 'slow', got '{r.operational.latency_class}'"
        )


from agents.reverie._content_capabilities import ContentCapabilityRouter


def test_router_maps_affordance_to_camera():
    """Affordance names map to camera names."""
    router = ContentCapabilityRouter()
    assert router.camera_for_affordance("content.overhead_perspective") == "c920-overhead"
    assert router.camera_for_affordance("content.desk_perspective") == "c920-desk"
    assert router.camera_for_affordance("content.operator_perspective") == "brio-operator"
    assert router.camera_for_affordance("content.unknown") is None


def test_router_returns_false_for_missing_camera(tmp_path):
    """Camera activation returns False when compositor frame doesn't exist."""
    router = ContentCapabilityRouter(
        sources_dir=tmp_path / "sources",
        compositor_dir=tmp_path / "compositor",
    )
    (tmp_path / "sources").mkdir()
    (tmp_path / "compositor").mkdir()
    result = router.activate_camera("content.overhead_perspective", level=0.7)
    assert result is False
