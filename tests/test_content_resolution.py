"""Test that content affordances produce visual output via the sources protocol."""

import json

from agents.reverie._content_capabilities import ContentCapabilityRouter


def test_narrative_text_produces_source(tmp_path, monkeypatch):
    """Narrative text should render to RGBA and write to sources protocol."""
    from agents.reverie import content_injector

    global_sources = tmp_path / "global-sources"
    router_sources = tmp_path / "router-sources"
    monkeypatch.setattr(content_injector, "SOURCES_DIR", global_sources)
    with content_injector._SOURCE_DIRS_LOCK:
        content_injector._CREATED_SOURCE_DIRS.clear()

    router = ContentCapabilityRouter(sources_dir=router_sources)
    result = router.activate_content(
        "content.narrative_text",
        "the weight of unfinished work accumulates like sediment",
        level=0.6,
    )
    assert result is True
    source_dir = router_sources / "content-narrative_text"
    assert (source_dir / "frame.rgba").exists()
    assert not (global_sources / "content-narrative_text").exists()
    manifest = json.loads((source_dir / "manifest.json").read_text())
    assert 0.5 <= manifest["opacity"] <= 0.7
    assert "recruited" in manifest["tags"]
    assert manifest["ttl_ms"] > 0


def test_narrative_text_publishes_when_text_render_fails(tmp_path, monkeypatch):
    """Content recruitment should still publish a source if Pillow rendering fails."""
    from agents import imagination_source_protocol
    from agents.reverie import content_injector

    global_sources = tmp_path / "global-sources"
    router_sources = tmp_path / "router-sources"

    def _raise_render_error(*_args, **_kwargs):
        raise RuntimeError("font cache unavailable")

    monkeypatch.setattr(content_injector, "SOURCES_DIR", global_sources)
    monkeypatch.setattr(imagination_source_protocol, "_render_text_to_rgba", _raise_render_error)
    with content_injector._SOURCE_DIRS_LOCK:
        content_injector._CREATED_SOURCE_DIRS.clear()

    router = ContentCapabilityRouter(sources_dir=router_sources)
    result = router.activate_content(
        "content.narrative_text",
        "the weight of unfinished work accumulates like sediment",
        level=0.6,
    )

    source_dir = router_sources / "content-narrative_text"
    assert result is True
    assert (source_dir / "frame.rgba").stat().st_size == 640 * 360 * 4
    assert not (global_sources / "content-narrative_text").exists()
    manifest = json.loads((source_dir / "manifest.json").read_text())
    assert 0.5 <= manifest["opacity"] <= 0.7
    assert "recruited" in manifest["tags"]
    assert manifest["ttl_ms"] > 0


def test_narrative_text_recovers_stale_router_source_cache(tmp_path, monkeypatch):
    """A stale hot-path directory cache entry must not make router-local writes fail."""
    from agents.reverie import content_injector

    global_sources = tmp_path / "global-sources"
    router_sources = tmp_path / "router-sources"
    source_dir = router_sources / "content-narrative_text"
    monkeypatch.setattr(content_injector, "SOURCES_DIR", global_sources)
    with content_injector._SOURCE_DIRS_LOCK:
        content_injector._CREATED_SOURCE_DIRS.clear()
        content_injector._CREATED_SOURCE_DIRS.add(source_dir)

    router = ContentCapabilityRouter(sources_dir=router_sources)
    result = router.activate_content(
        "content.narrative_text",
        "the weight of unfinished work accumulates like sediment",
        level=0.6,
    )

    assert result is True
    assert (source_dir / "frame.rgba").exists()
    assert not (global_sources / "content-narrative_text").exists()
    manifest = json.loads((source_dir / "manifest.json").read_text())
    assert 0.5 <= manifest["opacity"] <= 0.7
    assert "recruited" in manifest["tags"]
    assert manifest["ttl_ms"] > 0


def test_unknown_content_returns_false(tmp_path):
    router = ContentCapabilityRouter(sources_dir=tmp_path)
    result = router.activate_content("content.unknown_type", "test", level=0.5)
    assert result is False


def test_resolver_dispatch_table_has_all_content_types():
    from agents.reverie._content_resolvers import CONTENT_RESOLVERS

    # Keys must match names in shared/affordance_registry.py
    expected = {
        "content.narrative_text",
        "content.waveform_viz",
        "knowledge.episodic_recall",
        "knowledge.document_search",
        "knowledge.vault_search",
        "knowledge.profile_facts",
    }
    assert expected.issubset(set(CONTENT_RESOLVERS.keys()))
