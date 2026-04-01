"""Tests for imagination content resolver and DMN visual surface sensor.

Covers:
- Resolver core (text rendering, reference routing, staging swap)
- Qdrant and URL resolution (mocked)
- Imagination bus (publishing, cadence, escalation, reverberation)
- Imagination context formatter
- Intent alignment (Bachelard amendments, 9 dimensions, material quality)
"""

from __future__ import annotations

import json
import math
from unittest.mock import MagicMock, patch

import pytest

from agents.imagination import (
    CadenceController,
    ContentReference,
    ImaginationFragment,
    assemble_context,
    maybe_escalate,
    publish_fragment,
    reverberation_check,
)
from agents.imagination_context import (
    format_imagination_context,
)
from agents.imagination_resolver import (
    FAST_KINDS,
    MAX_SLOTS,
    SLOW_KINDS,
    cleanup_content_dir,
    resolve_references,
    resolve_references_staged,
    resolve_text,
    write_slot_manifest,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NINE_DIMENSIONS = {
    "intensity": 0.5,
    "tension": 0.3,
    "diffusion": 0.2,
    "degradation": 0.1,
    "depth": 0.4,
    "pitch_displacement": 0.0,
    "temporal_distortion": 0.15,
    "spectral_color": 0.6,
    "coherence": 0.8,
}


def _make_fragment(
    refs: list[ContentReference],
    fid: str = "test123",
    salience: float = 0.3,
    continuation: bool = False,
    material: str = "water",
    dimensions: dict[str, float] | None = None,
    narrative: str = "test thought",
) -> ImaginationFragment:
    return ImaginationFragment(
        id=fid,
        content_references=refs,
        dimensions=dimensions or {"intensity": 0.5},
        salience=salience,
        continuation=continuation,
        narrative=narrative,
        material=material,
    )


# ---------------------------------------------------------------------------
# Task 1: imagination resolver — text rendering
# ---------------------------------------------------------------------------


def test_resolve_text_creates_jpeg(tmp_path):
    ref = ContentReference(kind="text", source="Hello world", query=None, salience=0.5)
    result = resolve_text(ref, tmp_path, "frag1", 0)
    assert result is not None and result.exists()
    assert result.name == "frag1-0.jpg"
    assert result.stat().st_size > 100


def test_resolve_text_multiline(tmp_path):
    ref = ContentReference(
        kind="text", source="Line one\nLine two\nLine three", query=None, salience=0.5
    )
    result = resolve_text(ref, tmp_path, "frag2", 0)
    assert result is not None and result.exists()


def test_resolve_text_empty_source(tmp_path):
    """Empty text should still produce a valid JPEG (black canvas)."""
    ref = ContentReference(kind="text", source="", query=None, salience=0.5)
    result = resolve_text(ref, tmp_path, "empty", 0)
    assert result is not None and result.exists()


def test_resolve_text_unicode(tmp_path):
    """Unicode characters render without crashing."""
    ref = ContentReference(
        kind="text", source="日本語テスト — «résumé» ♫", query=None, salience=0.5
    )
    result = resolve_text(ref, tmp_path, "uni", 0)
    assert result is not None and result.exists()


def test_resolve_text_returns_none_on_save_failure(tmp_path, monkeypatch):
    """resolve_text returns None if PIL save raises."""
    import PIL.Image as _img

    def failing_save(self, *a, **kw):
        raise OSError("Disk full")

    monkeypatch.setattr(_img.Image, "save", failing_save)
    ref = ContentReference(kind="text", source="Hello", query=None, salience=0.5)
    result = resolve_text(ref, tmp_path, "fail1", 0)
    assert result is None


def test_font_fallback_loads_default(monkeypatch):
    """_load_font falls back to PIL default when no candidate font exists."""
    import agents.imagination_resolver as mod

    monkeypatch.setattr(mod, "_FONT_PATH", None)
    font = mod._load_font(24)
    assert font is not None


# ---------------------------------------------------------------------------
# Task 1b: reference routing and kind filtering
# ---------------------------------------------------------------------------


def test_resolve_references_skips_fast_kinds(tmp_path):
    refs = [
        ContentReference(kind="camera_frame", source="overhead", query=None, salience=0.8),
        ContentReference(kind="file", source="/some/path.jpg", query=None, salience=0.5),
        ContentReference(kind="text", source="hello", query=None, salience=0.3),
    ]
    frag = _make_fragment(refs)
    results = resolve_references(frag, tmp_path)
    assert len(results) == 1
    assert results[0].name == "test123-2.jpg"


def test_resolve_references_unknown_kind_falls_back_to_text(tmp_path):
    """Unknown content kinds should be rendered as text fallback."""
    refs = [ContentReference(kind="hologram", source="mystery data", query=None, salience=0.5)]
    frag = _make_fragment(refs)
    results = resolve_references(frag, tmp_path)
    assert len(results) == 1
    assert results[0].exists()


def test_resolve_references_audio_clip_falls_back_to_text(tmp_path):
    """audio_clip is listed in spec but has no resolver — should fallback to text."""
    refs = [ContentReference(kind="audio_clip", source="/tmp/clip.wav", query=None, salience=0.4)]
    frag = _make_fragment(refs)
    results = resolve_references(frag, tmp_path)
    # audio_clip is not in SLOW_KINDS or FAST_KINDS → unknown kind → text fallback
    assert len(results) == 1


def test_resolve_references_empty_content_references(tmp_path):
    """Fragment with no content references produces empty results."""
    frag = _make_fragment([], fid="empty")
    results = resolve_references(frag, tmp_path)
    assert results == []


def test_resolve_references_all_fast_kinds_produces_nothing(tmp_path):
    """All fast kinds → nothing resolved on Python side."""
    refs = [
        ContentReference(kind="camera_frame", source="hero", query=None, salience=0.9),
        ContentReference(kind="file", source="/img.jpg", query=None, salience=0.5),
    ]
    frag = _make_fragment(refs)
    results = resolve_references(frag, tmp_path)
    assert results == []


# ---------------------------------------------------------------------------
# Task 1c: staging + slot manifest
# ---------------------------------------------------------------------------


def test_write_slot_manifest(tmp_path):
    refs = [
        ContentReference(kind="text", source="Hello", query=None, salience=0.7),
        ContentReference(kind="text", source="World", query=None, salience=0.4),
    ]
    frag = _make_fragment(refs, fid="m1")
    manifest_path = tmp_path / "slots.json"
    paths = [tmp_path / "m1-0.jpg", tmp_path / "m1-1.jpg"]
    for p in paths:
        p.write_bytes(b"\xff\xd8dummy")
    write_slot_manifest(frag, paths, manifest_path)
    data = json.loads(manifest_path.read_text())
    assert data["fragment_id"] == "m1"
    assert len(data["slots"]) == 2
    assert data["slots"][0]["index"] == 0
    assert data["slots"][0]["salience"] == 0.7
    assert data["material"] == "water"
    assert data["continuation"] is False


def test_resolve_references_staged_atomic(tmp_path):
    staging = tmp_path / "staging"
    active = tmp_path / "active"
    refs = [ContentReference(kind="text", source="Test content", query=None, salience=0.5)]
    frag = _make_fragment(refs, fid="s1")
    resolve_references_staged(frag, staging_dir=staging, active_dir=active)
    assert active.exists()
    assert not staging.exists()
    assert (active / "s1-0.jpg").exists()
    manifest = json.loads((active / "slots.json").read_text())
    assert manifest["fragment_id"] == "s1"


def test_resolve_references_staged_replaces_previous(tmp_path):
    staging = tmp_path / "staging"
    active = tmp_path / "active"
    refs1 = [ContentReference(kind="text", source="First", query=None, salience=0.5)]
    frag1 = _make_fragment(refs1, fid="r1")
    resolve_references_staged(frag1, staging_dir=staging, active_dir=active)
    assert (active / "r1-0.jpg").exists()
    refs2 = [ContentReference(kind="text", source="Second", query=None, salience=0.6)]
    frag2 = _make_fragment(refs2, fid="r2")
    resolve_references_staged(frag2, staging_dir=staging, active_dir=active)
    assert (active / "r2-0.jpg").exists()
    assert not (active / "r1-0.jpg").exists()


def test_manifest_camera_frame_uses_source_path(tmp_path):
    refs = [ContentReference(kind="camera_frame", source="overhead", query=None, salience=0.8)]
    frag = _make_fragment(refs, fid="c1")
    manifest_path = tmp_path / "slots.json"
    write_slot_manifest(frag, [], manifest_path)
    data = json.loads(manifest_path.read_text())
    assert data["slots"][0]["path"] == "/dev/shm/hapax-compositor/overhead.jpg"
    assert data["slots"][0]["kind"] == "camera_frame"


def test_manifest_file_ref_uses_source_path(tmp_path):
    refs = [ContentReference(kind="file", source="/tmp/test.jpg", query=None, salience=0.6)]
    frag = _make_fragment(refs, fid="f1")
    manifest_path = tmp_path / "slots.json"
    write_slot_manifest(frag, [], manifest_path)
    data = json.loads(manifest_path.read_text())
    assert data["slots"][0]["path"] == "/tmp/test.jpg"


def test_manifest_max_four_slots(tmp_path):
    refs = [
        ContentReference(kind="text", source=f"Slot {i}", query=None, salience=0.5)
        for i in range(6)
    ]
    frag = _make_fragment(refs, fid="max")
    manifest_path = tmp_path / "slots.json"
    write_slot_manifest(frag, [tmp_path / f"max-{i}.jpg" for i in range(6)], manifest_path)
    data = json.loads(manifest_path.read_text())
    assert len(data["slots"]) == 4  # capped at MAX_SLOTS


def test_manifest_includes_material_and_continuation(tmp_path):
    """Manifest includes material and continuation for Rust shader interaction (B3)."""
    refs = [ContentReference(kind="text", source="Flame", query=None, salience=0.8)]
    frag = _make_fragment(refs, fid="mat1", material="fire", continuation=True)
    manifest_path = tmp_path / "slots.json"
    paths = [tmp_path / "mat1-0.jpg"]
    paths[0].write_bytes(b"\xff\xd8dummy")
    write_slot_manifest(frag, paths, manifest_path)
    data = json.loads(manifest_path.read_text())
    assert data["material"] == "fire"
    assert data["continuation"] is True


def test_cleanup_removes_old_files(tmp_path):
    (tmp_path / "old1-0.jpg").write_bytes(b"\xff\xd8fake")
    (tmp_path / "old1-1.jpg").write_bytes(b"\xff\xd8fake")
    assert len(list(tmp_path.glob("*.jpg"))) == 2
    cleanup_content_dir(tmp_path)
    assert len(list(tmp_path.glob("*.jpg"))) == 0


# ---------------------------------------------------------------------------
# Task 2: Qdrant resolver (mocked)
# ---------------------------------------------------------------------------


def test_resolve_qdrant_success(tmp_path):
    """_resolve_qdrant renders top Qdrant result as text JPEG."""
    mock_point = MagicMock()
    mock_point.payload = {"text": "Qdrant result text"}
    mock_results = MagicMock()
    mock_results.points = [mock_point]

    mock_client = MagicMock()
    mock_client.query_points.return_value = mock_results

    with (
        patch("agents._config.get_qdrant", return_value=mock_client),
        patch("agents._config.embed", return_value=[0.1] * 768),
    ):
        from agents.imagination_resolver import _resolve_qdrant

        ref = ContentReference(
            kind="qdrant_query", source="profile-facts", query="who", salience=0.5
        )
        result = _resolve_qdrant(ref, tmp_path, "q1", 0)

    assert result is not None and result.exists()
    mock_client.query_points.assert_called_once()


def test_resolve_qdrant_empty_results(tmp_path):
    """Empty Qdrant results return None without crashing."""
    mock_results = MagicMock()
    mock_results.points = []

    mock_client = MagicMock()
    mock_client.query_points.return_value = mock_results

    with (
        patch("agents._config.get_qdrant", return_value=mock_client),
        patch("agents._config.embed", return_value=[0.1] * 768),
    ):
        from agents.imagination_resolver import _resolve_qdrant

        ref = ContentReference(
            kind="qdrant_query", source="documents", query="nothing", salience=0.3
        )
        result = _resolve_qdrant(ref, tmp_path, "q2", 0)

    assert result is None


def test_resolve_qdrant_connection_error(tmp_path):
    """Connection error returns None with logging, not crash."""
    with (
        patch("agents._config.get_qdrant", side_effect=ConnectionError("refused")),
    ):
        from agents.imagination_resolver import _resolve_qdrant

        ref = ContentReference(
            kind="qdrant_query", source="profile-facts", query="test", salience=0.5
        )
        result = _resolve_qdrant(ref, tmp_path, "q3", 0)

    assert result is None


def test_resolve_qdrant_uses_query_over_source(tmp_path):
    """When query is set, embed(query) is called, not embed(source)."""
    mock_results = MagicMock()
    mock_results.points = []
    mock_client = MagicMock()
    mock_client.query_points.return_value = mock_results
    mock_embed = MagicMock(return_value=[0.1] * 768)

    with (
        patch("agents._config.get_qdrant", return_value=mock_client),
        patch("agents._config.embed", mock_embed),
    ):
        from agents.imagination_resolver import _resolve_qdrant

        ref = ContentReference(
            kind="qdrant_query", source="documents", query="specific question", salience=0.5
        )
        _resolve_qdrant(ref, tmp_path, "q4", 0)

    mock_embed.assert_called_once_with("specific question")


# ---------------------------------------------------------------------------
# Task 3: URL resolver (mocked)
# ---------------------------------------------------------------------------


def test_resolve_url_success(tmp_path):
    """Successful URL fetch produces a JPEG."""
    # Create a minimal valid JPEG in memory
    import io

    from PIL import Image

    img_bytes = io.BytesIO()
    Image.new("RGB", (100, 100), color=(255, 0, 0)).save(img_bytes, "JPEG")
    img_bytes.seek(0)

    mock_response = MagicMock()
    mock_response.content = img_bytes.getvalue()
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=mock_response):
        from agents.imagination_resolver import _resolve_url

        ref = ContentReference(
            kind="url", source="https://example.com/img.jpg", query=None, salience=0.5
        )
        result = _resolve_url(ref, tmp_path, "u1", 0)

    assert result is not None and result.exists()
    assert result.stat().st_size > 100


def test_resolve_url_timeout(tmp_path):
    """Timeout returns None, doesn't crash."""
    import httpx

    with patch("httpx.get", side_effect=httpx.TimeoutException("timed out")):
        from agents.imagination_resolver import _resolve_url

        ref = ContentReference(
            kind="url", source="https://slow.example.com/img.jpg", query=None, salience=0.5
        )
        result = _resolve_url(ref, tmp_path, "u2", 0)

    assert result is None


def test_resolve_url_404(tmp_path):
    """HTTP error returns None."""
    import httpx

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404", request=MagicMock(), response=MagicMock()
    )

    with patch("httpx.get", return_value=mock_response):
        from agents.imagination_resolver import _resolve_url

        ref = ContentReference(
            kind="url", source="https://example.com/missing.jpg", query=None, salience=0.5
        )
        result = _resolve_url(ref, tmp_path, "u3", 0)

    assert result is None


def test_resolve_url_corrupt_image(tmp_path):
    """Non-image content returns None."""
    mock_response = MagicMock()
    mock_response.content = b"this is not a jpeg"
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=mock_response):
        from agents.imagination_resolver import _resolve_url

        ref = ContentReference(
            kind="url", source="https://example.com/not-image.txt", query=None, salience=0.5
        )
        result = _resolve_url(ref, tmp_path, "u4", 0)

    assert result is None


# ---------------------------------------------------------------------------
# Task 4: Imagination bus — publishing
# ---------------------------------------------------------------------------


def test_publish_fragment_atomic_write(tmp_path):
    """publish_fragment writes current.json atomically and appends to stream."""
    current = tmp_path / "current.json"
    stream = tmp_path / "stream.jsonl"

    frag = _make_fragment([], fid="pub1", narrative="atomic test")
    publish_fragment(frag, current_path=current, stream_path=stream)

    assert current.exists()
    data = json.loads(current.read_text())
    assert data["id"] == "pub1"
    assert data["narrative"] == "atomic test"

    lines = stream.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["id"] == "pub1"


def test_publish_fragment_caps_stream(tmp_path):
    """Stream is capped at max_lines."""
    current = tmp_path / "current.json"
    stream = tmp_path / "stream.jsonl"

    for i in range(60):
        frag = _make_fragment([], fid=f"cap{i}", narrative=f"thought {i}")
        publish_fragment(frag, current_path=current, stream_path=stream, max_lines=50)

    lines = stream.read_text().strip().splitlines()
    assert len(lines) == 50
    # Most recent should be last
    assert json.loads(lines[-1])["id"] == "cap59"


# ---------------------------------------------------------------------------
# Task 5: Cadence controller
# ---------------------------------------------------------------------------


def test_cadence_base_interval():
    cc = CadenceController(base_s=12.0, accelerated_s=4.0)
    assert cc.current_interval() == 12.0


def test_cadence_accelerates_on_high_salience_continuation():
    cc = CadenceController(base_s=12.0, accelerated_s=4.0, salience_threshold=0.3)
    frag = _make_fragment([], salience=0.5, continuation=True)
    cc.update(frag)
    assert cc.current_interval() == 4.0


def test_cadence_decelerates_after_streak():
    cc = CadenceController(base_s=12.0, accelerated_s=4.0, decel_count=3)
    # Accelerate first
    cc.force_accelerated(True)
    assert cc.current_interval() == 4.0
    # Three non-continuation fragments decelerate
    for _ in range(3):
        frag = _make_fragment([], salience=0.5, continuation=False)
        cc.update(frag)
    assert cc.current_interval() == 12.0


def test_cadence_tpn_doubles_interval():
    """TPN active doubles the interval (D1: prioritize deliberative over generative)."""
    cc = CadenceController(base_s=12.0, accelerated_s=4.0)
    cc.set_tpn_active(True)
    assert cc.current_interval() == 24.0  # 12 * 2
    # Also doubles accelerated
    cc.force_accelerated(True)
    assert cc.current_interval() == 8.0  # 4 * 2


def test_cadence_force_accelerated():
    """External force_accelerated (from reverberation) overrides streak logic."""
    cc = CadenceController(base_s=12.0, accelerated_s=4.0)
    cc.force_accelerated(True)
    assert cc.current_interval() == 4.0
    cc.force_accelerated(False)
    assert cc.current_interval() == 12.0


# ---------------------------------------------------------------------------
# Task 6: Escalation (Bachelard B6 — soft sigmoid, not hard threshold)
# ---------------------------------------------------------------------------


def test_escalation_zero_salience_never_escalates():
    """Salience 0 should have near-zero escalation probability."""
    frag = _make_fragment([], salience=0.0)
    # Run many times — should never escalate
    escalated = sum(1 for _ in range(1000) if maybe_escalate(frag) is not None)
    assert escalated < 50  # sigmoid at 0.0 ≈ 0.012, expect ~12 in 1000 (wide margin for CI)


def test_escalation_high_salience_usually_escalates():
    """Salience 0.9 should escalate most of the time."""
    frag = _make_fragment([], salience=0.9)
    escalated = sum(1 for _ in range(1000) if maybe_escalate(frag) is not None)
    assert escalated > 900  # sigmoid at 0.9 ≈ 0.94


def test_escalation_continuation_boosts_probability():
    """Continuation flag applies 1.3x boost (B6)."""
    # At salience=0.55 (midpoint), probability ≈ 0.5
    midpoint = 0.55
    steepness = 8.0
    base_prob = 1.0 / (1.0 + math.exp(-steepness * (0.55 - midpoint)))
    boosted_prob = min(1.0, base_prob * 1.3)
    assert boosted_prob > base_prob

    # Empirical check
    frag_no_cont = _make_fragment([], salience=0.55, continuation=False)
    frag_cont = _make_fragment([], salience=0.55, continuation=True)
    no_cont_count = sum(1 for _ in range(2000) if maybe_escalate(frag_no_cont) is not None)
    cont_count = sum(1 for _ in range(2000) if maybe_escalate(frag_cont) is not None)
    assert cont_count > no_cont_count


def test_escalation_produces_valid_impingement():
    """Escalated impingement has correct source, type, and content keys."""
    frag = _make_fragment(
        [ContentReference(kind="text", source="hello", query=None, salience=0.5)],
        salience=1.0,  # guarantee escalation
        material="fire",
        continuation=True,
        narrative="burning insight",
    )
    imp = maybe_escalate(frag)
    assert imp is not None
    assert imp.source == "imagination"
    assert imp.type == "salience_integration"
    assert imp.strength == 1.0
    assert imp.content["narrative"] == "burning insight"
    assert imp.content["material"] == "fire"
    assert imp.content["continuation"] is True
    assert "dimensions" in imp.content
    assert "content_references" in imp.content


# ---------------------------------------------------------------------------
# Task 7: Reverberation (Bachelard B4)
# ---------------------------------------------------------------------------


def test_reverberation_identical_text_is_low():
    """Identical text = 0 reverberation (no surprise)."""
    assert reverberation_check("the room is quiet", "the room is quiet") == 0.0


def test_reverberation_disjoint_text_is_high():
    """Completely different words = high reverberation."""
    score = reverberation_check("gentle flowing water", "harsh burning flames")
    assert score > 0.8


def test_reverberation_partial_overlap():
    """Partial word overlap produces intermediate score."""
    score = reverberation_check(
        "the room is quiet and peaceful",
        "the room is loud and chaotic",
    )
    assert 0.2 < score < 0.8


def test_reverberation_empty_inputs_return_zero():
    """Empty or missing text returns 0 (no surprise detectable)."""
    assert reverberation_check("", "anything") == 0.0
    assert reverberation_check("anything", "") == 0.0
    assert reverberation_check("", "") == 0.0


def test_reverberation_is_case_insensitive():
    """Case differences don't affect reverberation."""
    assert reverberation_check("Hello World", "hello world") == 0.0


def test_reverberation_semantic_gap_documented():
    """KNOWN GAP (B4): Syntactically different paraphrases produce false surprise.

    The design spec calls for semantic similarity. The current Jaccard
    implementation is purely lexical. This test documents the gap:
    semantically similar text with different words registers as high
    reverberation, which overfires the acceleration loop.
    """
    # These are semantically similar but lexically different
    score = reverberation_check(
        "a peaceful serene environment",
        "a calm tranquil setting",
    )
    # Jaccard sees almost no overlap → high reverberation (false positive)
    assert score > 0.7, "Expected high score due to lexical gap (known limitation)"


# ---------------------------------------------------------------------------
# Task 8: Context assembly
# ---------------------------------------------------------------------------


def test_assemble_context_all_sections():
    """Context includes observations, system state, and recent fragments."""
    observations = ["saw something", "heard noise"]
    sensor_snapshot = {
        "stimmung": {"overall_stance": "cautious", "operator_stress": {"value": 0.3}},
        "perception": {"activity": "focused", "flow_score": 0.7},
        "watch": {"heart_rate": 72},
    }
    fragments = [_make_fragment([], narrative="recent thought")]
    ctx = assemble_context(observations, fragments, sensor_snapshot)
    assert "## Current Observations" in ctx
    assert "saw something" in ctx
    assert "## System State" in ctx
    assert "stance=cautious" in ctx
    assert "activity=focused" in ctx
    assert "HR=72" in ctx
    assert "## Recent Imagination" in ctx
    assert "recent thought" in ctx


def test_assemble_context_empty_inputs():
    """Empty inputs produce (none) markers, not crashes."""
    ctx = assemble_context([], [], {})
    assert "(none)" in ctx


def test_assemble_context_marks_continuation():
    """Continuing fragments are prefixed with (continuing)."""
    frag = _make_fragment([], continuation=True, narrative="ongoing train")
    ctx = assemble_context([], [frag], {})
    assert "(continuing)" in ctx


# ---------------------------------------------------------------------------
# Task 9: Imagination context formatter (voice injection)
# ---------------------------------------------------------------------------


def test_format_imagination_context_empty_stream(tmp_path):
    """Missing stream file produces quiet mind."""
    result = format_imagination_context(stream_path=tmp_path / "nonexistent.jsonl")
    assert "mind is quiet" in result


def test_format_imagination_context_salience_grading(tmp_path):
    """Fragments are graded by salience threshold (D4)."""
    stream = tmp_path / "stream.jsonl"
    low = json.dumps({"salience": 0.2, "narrative": "low thought", "continuation": False})
    high = json.dumps({"salience": 0.6, "narrative": "high thought", "continuation": False})
    stream.write_text(f"{low}\n{high}\n")

    result = format_imagination_context(stream_path=stream)
    assert "(background)" in result
    assert "(active thought)" in result
    assert "low thought" in result
    assert "high thought" in result


def test_format_imagination_context_malformed_json(tmp_path):
    """Malformed JSON lines are skipped gracefully."""
    stream = tmp_path / "stream.jsonl"
    good = json.dumps({"salience": 0.5, "narrative": "good line", "continuation": False})
    stream.write_text(f"{{broken json\n{good}\n")

    result = format_imagination_context(stream_path=stream)
    assert "good line" in result


def test_format_imagination_context_continuation_marker(tmp_path):
    """Continuing fragments get (continuing) marker."""
    stream = tmp_path / "stream.jsonl"
    frag = json.dumps({"salience": 0.5, "narrative": "ongoing", "continuation": True})
    stream.write_text(f"{frag}\n")

    result = format_imagination_context(stream_path=stream)
    assert "(continuing)" in result


# ---------------------------------------------------------------------------
# Task 10: Intent alignment — data model invariants
# ---------------------------------------------------------------------------


def test_fragment_material_values():
    """Material field accepts exactly 5 Bachelard elements (B3)."""
    for mat in ("water", "fire", "earth", "air", "void"):
        frag = _make_fragment([], material=mat)
        assert frag.material == mat


def test_fragment_material_default_is_water():
    """Default material is water — the contemplative element (B3)."""
    frag = ImaginationFragment(
        content_references=[],
        dimensions={},
        salience=0.3,
        continuation=False,
        narrative="test",
    )
    assert frag.material == "water"


def test_fragment_material_rejects_invalid():
    """Invalid material value is rejected by Pydantic Literal validation."""
    with pytest.raises(Exception):  # ValidationError
        ImaginationFragment(
            content_references=[],
            dimensions={},
            salience=0.3,
            continuation=False,
            narrative="test",
            material="plasma",  # type: ignore[arg-type]
        )


def test_fragment_salience_bounds():
    """Salience is bounded [0, 1]."""
    with pytest.raises(Exception):
        _make_fragment([], salience=-0.1)
    with pytest.raises(Exception):
        _make_fragment([], salience=1.1)


def test_fragment_is_frozen():
    """Fragments are immutable (Pydantic frozen=True)."""
    frag = _make_fragment([], narrative="original")
    with pytest.raises(Exception):
        frag.narrative = "modified"  # type: ignore[misc]


def test_content_reference_is_frozen():
    """Content references are immutable."""
    ref = ContentReference(kind="text", source="hello", query=None, salience=0.5)
    with pytest.raises(Exception):
        ref.source = "modified"  # type: ignore[misc]


def test_nine_dimensions_structure():
    """Intent: 9 named expressive dimensions per fragment (D7).

    The spec defines: intensity, tension, diffusion, degradation, depth,
    pitch_displacement, temporal_distortion, spectral_color, coherence.
    Currently dimensions is dict[str, float] — this test documents the
    expected schema even though the code doesn't enforce it yet.
    """
    frag = _make_fragment([], dimensions=NINE_DIMENSIONS)
    assert len(frag.dimensions) == 9
    for key in (
        "intensity",
        "tension",
        "diffusion",
        "degradation",
        "depth",
        "pitch_displacement",
        "temporal_distortion",
        "spectral_color",
        "coherence",
    ):
        assert key in frag.dimensions


def test_fragment_id_uniqueness():
    """Fragment IDs are unique (uuid4 hex[:12])."""
    frag_a = ImaginationFragment(
        content_references=[], dimensions={}, salience=0.3, continuation=False, narrative="a"
    )
    frag_b = ImaginationFragment(
        content_references=[], dimensions={}, salience=0.3, continuation=False, narrative="b"
    )
    assert frag_a.id != frag_b.id
    assert len(frag_a.id) == 12


# ---------------------------------------------------------------------------
# Task 11: Kind constants integrity
# ---------------------------------------------------------------------------


def test_slow_and_fast_kinds_are_disjoint():
    """SLOW_KINDS and FAST_KINDS must not overlap."""
    assert set() == SLOW_KINDS & FAST_KINDS


def test_max_slots_is_four():
    """Rust compositor expects exactly 4 texture slots."""
    assert MAX_SLOTS == 4


# ---------------------------------------------------------------------------
# Task 12: DMN visual surface sensor
# ---------------------------------------------------------------------------

from agents.dmn.sensor import read_visual_surface


def test_read_visual_surface_missing(tmp_path):
    result = read_visual_surface(
        frame_path=tmp_path / "nonexistent.jpg",
        imagination_path=tmp_path / "nonexistent.json",
    )
    assert result["source"] == "visual_surface"
    assert result["stale"] is True


def test_read_visual_surface_with_frame(tmp_path):
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"\xff\xd8\xff\xe0fake jpeg")
    current = tmp_path / "current.json"
    current.write_text(json.dumps({"id": "abc123", "timestamp": 0.0}))
    result = read_visual_surface(frame_path=frame, imagination_path=current)
    assert result["source"] == "visual_surface"
    assert result["frame_path"] == str(frame)
    assert result["imagination_fragment_id"] == "abc123"
    assert result["stale"] is False
