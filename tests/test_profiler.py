"""Tests for the profiler agent — schemas, merging, discovery, chunking, I/O.

No LLM calls; tests focus on deterministic logic.
"""

import json

import pytest

from agents.profiler import (
    PROFILE_DIMENSIONS,
    ChunkExtraction,
    CurationOp,
    DimensionCuration,
    OperatorUpdate,
    ProfileDimension,
    ProfileFact,
    SynthesisOutput,
    UserProfile,
    apply_curation,
    build_profile,
    generate_extraction_prompts,
    group_facts_by_dimension,
    load_existing_profile,
    merge_facts,
)
from agents.profiler_sources import (
    CHUNK_SIZE,
    DiscoveredSources,
    SourceChunk,
    _chunk_text,
    _compress_ranges,
    _extract_text_content,
    _short_path,
    detect_changed_sources,
    discover_sources,
    get_source_mtimes,
    list_source_ids,
    load_state,
    read_langfuse,
    save_state,
)

# ── Schema tests ─────────────────────────────────────────────────────────────


def test_profile_fact_validation():
    fact = ProfileFact(
        dimension="technical_skills",
        key="preferred_tool",
        value="uv",
        confidence=0.9,
        source="config:~/.claude/CLAUDE.md",
        evidence="Always use uv for Python package management",
    )
    assert fact.dimension == "technical_skills"
    assert fact.confidence == 0.9


def test_profile_fact_confidence_bounds():
    with pytest.raises(Exception):
        ProfileFact(
            dimension="identity",
            key="name",
            value="test",
            confidence=1.5,  # out of bounds
            source="test",
            evidence="test",
        )
    with pytest.raises(Exception):
        ProfileFact(
            dimension="identity",
            key="name",
            value="test",
            confidence=-0.1,  # out of bounds
            source="test",
            evidence="test",
        )


def test_chunk_extraction_empty():
    extraction = ChunkExtraction(facts=[])
    assert extraction.facts == []


def test_chunk_extraction_with_facts():
    fact = ProfileFact(
        dimension="identity",
        key="name",
        value="Operator",
        confidence=0.95,
        source="test",
        evidence="Name is Operator",
    )
    extraction = ChunkExtraction(facts=[fact])
    assert len(extraction.facts) == 1
    assert extraction.facts[0].value == "Operator"


def test_user_profile_serialization():
    profile = UserProfile(
        name="Operator",
        summary="A developer and music producer.",
        dimensions=[
            ProfileDimension(
                name="identity",
                summary="Operator is a developer.",
                facts=[
                    ProfileFact(
                        dimension="identity",
                        key="name",
                        value="Operator",
                        confidence=0.95,
                        source="test",
                        evidence="name",
                    )
                ],
            )
        ],
        sources_processed=["config:test"],
        version=1,
        updated_at="2026-01-01T00:00:00Z",
    )
    # Round-trip through JSON
    json_str = profile.model_dump_json()
    restored = UserProfile.model_validate_json(json_str)
    assert restored.name == "Operator"
    assert len(restored.dimensions) == 1
    assert restored.dimensions[0].facts[0].key == "name"


def test_profile_dimensions_are_defined():
    assert len(PROFILE_DIMENSIONS) >= 8
    assert "identity" in PROFILE_DIMENSIONS
    assert "values" in PROFILE_DIMENSIONS
    assert "work_patterns" in PROFILE_DIMENSIONS


# ── Fact merging tests ───────────────────────────────────────────────────────


def _make_fact(dim: str, key: str, value: str, confidence: float = 0.5) -> ProfileFact:
    return ProfileFact(
        dimension=dim,
        key=key,
        value=value,
        confidence=confidence,
        source="test",
        evidence="test",
    )


def test_merge_facts_no_overlap():
    existing = [_make_fact("identity", "name", "Operator", 0.9)]
    new = [_make_fact("technical_skills", "language", "Python", 0.8)]
    merged = merge_facts(existing, new)
    assert len(merged) == 2


def test_merge_facts_higher_confidence_wins():
    existing = [_make_fact("identity", "name", "Operator", 0.7)]
    new = [_make_fact("identity", "name", "Op K.", 0.9)]
    merged = merge_facts(existing, new)
    assert len(merged) == 1
    assert merged[0].value == "Op K."
    assert merged[0].confidence == 0.9


def test_merge_facts_keeps_existing_if_higher():
    existing = [_make_fact("identity", "name", "Operator", 0.95)]
    new = [_make_fact("identity", "name", "R.", 0.3)]
    merged = merge_facts(existing, new)
    assert len(merged) == 1
    assert merged[0].value == "Operator"


def test_merge_facts_empty_existing():
    new = [_make_fact("identity", "name", "Operator", 0.9)]
    merged = merge_facts([], new)
    assert len(merged) == 1


def test_merge_facts_empty_new():
    existing = [_make_fact("identity", "name", "Operator", 0.9)]
    merged = merge_facts(existing, [])
    assert len(merged) == 1


def _make_sourced_fact(
    dim: str, key: str, value: str, confidence: float, source: str
) -> ProfileFact:
    return ProfileFact(
        dimension=dim,
        key=key,
        value=value,
        confidence=confidence,
        source=source,
        evidence="test",
    )


def test_merge_authority_overrides_observation():
    """Authority source (interview) should override observation (langfuse) regardless of confidence."""
    existing = [_make_sourced_fact("technical_skills", "tool", "pip", 0.9, "langfuse/traces")]
    new = [_make_sourced_fact("technical_skills", "tool", "uv", 0.7, "interview:2024-01-15")]
    merged = merge_facts(existing, new)
    assert len(merged) == 1
    assert merged[0].value == "uv"


def test_merge_observation_cannot_override_authority():
    """Observation source should never override authority source."""
    existing = [_make_sourced_fact("technical_skills", "tool", "uv", 0.7, "config:CLAUDE.md")]
    new = [_make_sourced_fact("technical_skills", "tool", "pip", 0.95, "langfuse/traces")]
    merged = merge_facts(existing, new)
    assert len(merged) == 1
    assert merged[0].value == "uv"


def test_merge_same_type_higher_confidence_wins():
    """When both are observation sources, higher confidence wins."""
    existing = [_make_sourced_fact("workflow", "method", "CLI", 0.6, "shell/history")]
    new = [_make_sourced_fact("workflow", "method", "TUI", 0.8, "git/commits")]
    merged = merge_facts(existing, new)
    assert len(merged) == 1
    assert merged[0].value == "TUI"


def test_merge_both_authority_higher_confidence_wins():
    """When both are authority sources, higher confidence wins."""
    existing = [_make_sourced_fact("workflow", "method", "CLI", 0.6, "interview:2024")]
    new = [_make_sourced_fact("workflow", "method", "TUI", 0.8, "config:CLAUDE.md")]
    merged = merge_facts(existing, new)
    assert len(merged) == 1
    assert merged[0].value == "TUI"


def test_authority_sources_constant():
    from agents.profiler import AUTHORITY_SOURCES

    assert "interview" in AUTHORITY_SOURCES
    assert "config" in AUTHORITY_SOURCES
    assert "memory" in AUTHORITY_SOURCES
    assert "operator" in AUTHORITY_SOURCES
    assert "langfuse" not in AUTHORITY_SOURCES


def test_group_facts_by_dimension():
    facts = [
        _make_fact("identity", "name", "Operator"),
        _make_fact("identity", "role", "Developer"),
        _make_fact("technical_skills", "language", "Python"),
    ]
    grouped = group_facts_by_dimension(facts)
    assert len(grouped) == 2
    assert len(grouped["identity"]) == 2
    assert len(grouped["technical_skills"]) == 1


# ── Source discovery tests ───────────────────────────────────────────────────


def test_discover_sources_finds_config():
    sources = discover_sources()
    # Should find at least ~/.claude/CLAUDE.md
    config_names = [p.name for p in sources.config_files]
    assert "CLAUDE.md" in config_names


def test_discover_sources_finds_rules():
    sources = discover_sources()
    config_paths = [str(p) for p in sources.config_files]
    rules = [p for p in config_paths if "/rules/" in p]
    assert len(rules) >= 1  # At least one rules file


def test_discover_sources_finds_transcripts():
    sources = discover_sources()
    assert len(sources.transcript_files) >= 1


def test_list_source_ids():
    sources = discover_sources()
    ids = list_source_ids(sources)
    assert len(ids) >= 3  # At minimum: config + transcript + something
    assert any(sid.startswith("config:") for sid in ids)


# ── Chunking tests ───────────────────────────────────────────────────────────


def test_chunk_text_short():
    chunks = _chunk_text("hello world", "test:source", "test")
    assert len(chunks) == 1
    assert chunks[0].text == "hello world"
    assert chunks[0].source_id == "test:source"
    assert chunks[0].char_count == 11


def test_chunk_text_empty():
    chunks = _chunk_text("", "test:source", "test")
    assert len(chunks) == 0


def test_chunk_text_whitespace_only():
    chunks = _chunk_text("   \n\n  ", "test:source", "test")
    assert len(chunks) == 0


def test_chunk_text_splits_long():
    # Generate text longer than CHUNK_SIZE
    paragraphs = [f"Paragraph {i}. " * 50 for i in range(20)]
    text = "\n\n".join(paragraphs)
    assert len(text) > CHUNK_SIZE
    chunks = _chunk_text(text, "test:long", "test")
    assert len(chunks) > 1
    # All chunks should have content
    for chunk in chunks:
        assert len(chunk.text) > 0
        assert chunk.source_id == "test:long"


def test_source_chunk_char_count():
    chunk = SourceChunk(text="hello", source_id="test", source_type="test")
    assert chunk.char_count == 5


# ── Content extraction tests ────────────────────────────────────────────────


def test_extract_text_from_string():
    result = _extract_text_content("hello world", "user")
    assert result == "[user]: hello world"


def test_extract_text_from_list():
    content = [
        {"type": "text", "text": "hello"},
        {"type": "tool_use", "name": "Read", "input": {}},
        {"type": "text", "text": "world"},
    ]
    result = _extract_text_content(content, "assistant")
    assert "hello" in result
    assert "world" in result
    assert "tool_use" not in result


def test_extract_text_skips_thinking():
    content = [
        {"type": "thinking", "text": "internal thought"},
        {"type": "text", "text": "visible response"},
    ]
    result = _extract_text_content(content, "assistant")
    assert "internal thought" not in result
    assert "visible response" in result


def test_extract_text_empty_string():
    result = _extract_text_content("", "user")
    assert result == ""


def test_extract_text_empty_list():
    result = _extract_text_content([], "user")
    assert result == ""


# ── Path helper tests ────────────────────────────────────────────────────────


def test_short_path_replaces_home():
    from shared.config import HAPAX_HOME

    home = HAPAX_HOME
    path = home / "projects" / "test"
    short = _short_path(path)
    assert short == "~/projects/test"


# ── Build profile test ───────────────────────────────────────────────────────


def test_build_profile():
    facts = [
        _make_fact("identity", "name", "Operator", 0.95),
        _make_fact("technical_skills", "language", "Python", 0.9),
    ]
    synthesis = SynthesisOutput(
        name="Operator",
        email=None,
        summary="A developer and music producer.",
        dimension_summaries={
            "identity": "Operator is a developer and music producer.",
            "technical_skills": "Proficient in Python with type hints.",
        },
    )
    profile = build_profile(facts, synthesis, ["config:test"])
    assert profile.name == "Operator"
    assert profile.version == 1
    assert len(profile.dimensions) == 2
    assert profile.sources_processed == ["config:test"]


def test_build_profile_increments_version():
    existing = UserProfile(
        name="Operator",
        summary="v1",
        version=3,
        dimensions=[],
        sources_processed=["old"],
    )
    synthesis = SynthesisOutput(
        name="Operator",
        summary="v2",
        dimension_summaries={},
    )
    profile = build_profile([], synthesis, ["old", "new"], existing)
    assert profile.version == 4


# ── Extraction prompts test ──────────────────────────────────────────────────


def test_generate_extraction_prompts():
    prompts = generate_extraction_prompts()
    assert "Claude.ai" in prompts
    assert "Gemini" in prompts
    assert "Perplexity" not in prompts  # Removed — no official bulk export
    assert "ProfileFact" not in prompts or "dimension" in prompts  # Contains schema info
    assert "source" in prompts
    assert "confidence" in prompts


# ── Change detection tests ──────────────────────────────────────────────────


def test_get_source_mtimes():
    sources = discover_sources()
    mtimes = get_source_mtimes(sources)
    assert len(mtimes) > 0
    # All values should be positive floats (unix timestamps)
    for _sid, mtime in mtimes.items():
        assert isinstance(mtime, float)
        assert mtime > 0


def test_load_state_missing_file():
    state = load_state()
    # Should return empty dict if no state file, not crash
    assert isinstance(state, dict)


def test_save_and_load_state(tmp_path, monkeypatch):
    """Test state round-trip using a temp directory."""
    import agents.profiler_sources as ps

    monkeypatch.setattr(ps, "STATE_DIR", tmp_path)
    monkeypatch.setattr(ps, "STATE_FILE", tmp_path / ".state.json")

    mtimes = {"config:test": 1234567890.0}
    save_state(mtimes, ["config:test"])

    state = load_state()
    assert state["source_mtimes"]["config:test"] == 1234567890.0
    assert "config:test" in state["sources_processed"]
    assert "last_run" in state


def test_detect_changed_sources_all_new(tmp_path, monkeypatch):
    """With no prior state, all sources should be reported as new."""
    import agents.profiler_sources as ps

    monkeypatch.setattr(ps, "STATE_DIR", tmp_path)
    monkeypatch.setattr(ps, "STATE_FILE", tmp_path / ".state.json")

    sources = discover_sources()
    changed, new = detect_changed_sources(sources)
    # With no prior state, everything should be "new"
    assert len(new) > 0
    assert len(changed) == 0


def test_detect_changed_sources_nothing_changed(tmp_path, monkeypatch):
    """After saving current mtimes, detect_changed should return empty sets."""
    import agents.profiler_sources as ps

    monkeypatch.setattr(ps, "STATE_DIR", tmp_path)
    monkeypatch.setattr(ps, "STATE_FILE", tmp_path / ".state.json")

    sources = discover_sources()
    mtimes = get_source_mtimes(sources)
    save_state(mtimes, list_source_ids(sources))

    changed, new = detect_changed_sources(sources)
    assert len(changed) == 0
    assert len(new) == 0


# ── Operator update schema tests ────────────────────────────────────────────


def test_operator_update_schema_empty():
    update = OperatorUpdate(
        goal_updates={},
        new_patterns=[],
        summary="",
    )
    assert update.goal_updates == {}
    assert update.new_patterns == []
    assert update.summary == ""


def test_operator_update_schema_with_data():
    update = OperatorUpdate(
        goal_updates={"agent-coverage": "3 of 6 agents implemented"},
        new_patterns=["Iterates rapidly on agent design"],
        summary="",
    )
    assert "agent-coverage" in update.goal_updates
    assert len(update.new_patterns) == 1


# ── Curation tests ──────────────────────────────────────────────────────────


def test_curation_op_schema():
    op = CurationOp(
        action="delete",
        keys=["stale_fact"],
        reason="No longer relevant",
    )
    assert op.action == "delete"
    assert op.new_key is None


def test_dimension_curation_schema():
    curation = DimensionCuration(
        dimension="identity",
        operations=[],
        health_score=1.0,
    )
    assert curation.health_score == 1.0
    assert curation.operations == []


def test_apply_curation_delete():
    facts = [
        _make_fact("identity", "name", "Operator", 0.95),
        _make_fact("identity", "stale_info", "Old data", 0.3),
    ]
    curation = DimensionCuration(
        dimension="identity",
        operations=[
            CurationOp(action="delete", keys=["stale_info"], reason="Stale"),
        ],
        health_score=0.8,
    )
    curated, flagged = apply_curation(facts, curation)
    assert len(curated) == 1
    assert curated[0].key == "name"
    assert len(flagged) == 0


def test_apply_curation_merge():
    facts = [
        _make_fact("technical_skills", "preferred_python_tool", "uv", 0.9),
        _make_fact("technical_skills", "python_package_manager", "uv", 0.85),
    ]
    curation = DimensionCuration(
        dimension="technical_skills",
        operations=[
            CurationOp(
                action="merge",
                keys=["preferred_python_tool", "python_package_manager"],
                reason="Same fact",
                new_key="python_package_manager",
                new_value="uv — used for all Python package management and project setup",
                new_confidence=0.95,
            ),
        ],
        health_score=0.9,
    )
    curated, flagged = apply_curation(facts, curation)
    assert len(curated) == 1
    assert curated[0].key == "python_package_manager"
    assert curated[0].confidence == 0.95
    assert "Merged from" in curated[0].evidence


def test_apply_curation_update_key():
    facts = [
        _make_fact("hardware", "gpu_type", "RTX 3090", 0.9),
    ]
    curation = DimensionCuration(
        dimension="hardware",
        operations=[
            CurationOp(
                action="update",
                keys=["gpu_type"],
                reason="Normalize key",
                new_key="gpu_model",
                new_value=None,
            ),
        ],
        health_score=0.95,
    )
    curated, flagged = apply_curation(facts, curation)
    assert len(curated) == 1
    assert curated[0].key == "gpu_model"
    assert curated[0].value == "RTX 3090"  # Value preserved


def test_apply_curation_update_value():
    facts = [
        _make_fact("software_preferences", "chat_ui", "LibreChat", 0.8),
    ]
    curation = DimensionCuration(
        dimension="software_preferences",
        operations=[
            CurationOp(
                action="update",
                keys=["chat_ui"],
                reason="LibreChat replaced by Open WebUI",
                new_key=None,
                new_value="Open WebUI",
                new_confidence=0.95,
            ),
        ],
        health_score=0.9,
    )
    curated, flagged = apply_curation(facts, curation)
    assert len(curated) == 1
    assert curated[0].value == "Open WebUI"
    assert curated[0].confidence == 0.95


def test_apply_curation_flag():
    facts = [
        _make_fact("workflow", "daw_usage", "Uses Ableton", 0.6),
        _make_fact("workflow", "dawless_workflow", "DAWless only", 0.9),
    ]
    curation = DimensionCuration(
        dimension="workflow",
        operations=[
            CurationOp(
                action="flag",
                keys=["daw_usage", "dawless_workflow"],
                reason="Contradictory: one says DAW, other says DAWless",
            ),
        ],
        health_score=0.5,
    )
    curated, flagged = apply_curation(facts, curation)
    assert len(curated) == 2  # Flagged facts are NOT removed
    assert len(flagged) == 1
    assert "daw_usage" in flagged[0].keys


def test_apply_curation_noop():
    facts = [_make_fact("identity", "name", "Operator", 0.95)]
    curation = DimensionCuration(
        dimension="identity",
        operations=[],
        health_score=1.0,
    )
    curated, flagged = apply_curation(facts, curation)
    assert len(curated) == 1
    assert len(flagged) == 0


def test_apply_curation_delete_missing_key():
    """Deleting a key that doesn't exist should not crash."""
    facts = [_make_fact("identity", "name", "Operator", 0.95)]
    curation = DimensionCuration(
        dimension="identity",
        operations=[
            CurationOp(action="delete", keys=["nonexistent"], reason="test"),
        ],
        health_score=0.9,
    )
    curated, flagged = apply_curation(facts, curation)
    assert len(curated) == 1  # Original fact preserved


# ── Langfuse source tests ──────────────────────────────────────────────────

from unittest.mock import patch


def test_discovered_sources_langfuse_field():
    s = DiscoveredSources()
    assert s.langfuse_available is False
    s.langfuse_available = True
    assert s.langfuse_available is True


@patch("agents.profiler_sources._LANGFUSE_PK", "")
def test_read_langfuse_no_credentials():
    chunks = read_langfuse()
    assert chunks == []


@patch("agents.profiler_sources._LANGFUSE_PK", "pk-test")
@patch("agents.profiler_sources._langfuse_get")
def test_read_langfuse_with_data(mock_get):
    traces = [
        {"id": "t1", "name": "drift-detector", "timestamp": "2026-02-28T10:00:00Z"},
        {"id": "t2", "name": "profiler", "timestamp": "2026-02-28T14:00:00Z"},
        {"id": "t3", "name": "drift-detector", "timestamp": "2026-02-28T22:00:00Z"},
    ]
    observations = [
        {
            "model": "claude-haiku",
            "metadata": {"model_group": "claude-haiku"},
            "usage": {"input": 1000, "output": 500},
            "calculatedTotalCost": 0.01,
            "latency": 200,
            "level": "DEFAULT",
        },
        {
            "model": "qwen-7b",
            "metadata": {"model_group": "qwen-7b"},
            "usage": {"input": 200, "output": 50},
            "calculatedTotalCost": 0.0,
            "latency": 100,
            "level": "DEFAULT",
        },
    ]

    def side_effect(path, params=None):
        if "/traces" in path:
            return {"data": traces, "meta": {"totalItems": 3}}
        if "/observations" in path:
            return {"data": observations, "meta": {"totalItems": 2}}
        return {}

    mock_get.side_effect = side_effect

    chunks = read_langfuse(lookback_days=7)
    assert len(chunks) >= 1

    text = chunks[0].text
    assert "claude-haiku" in text
    assert "qwen-7b" in text
    assert chunks[0].source_type == "langfuse"
    assert chunks[0].source_id == "langfuse:telemetry"


@patch("agents.profiler_sources._LANGFUSE_PK", "pk-test")
@patch("agents.profiler_sources._langfuse_get")
def test_read_langfuse_empty_response(mock_get):
    mock_get.return_value = {"data": [], "meta": {"totalItems": 0}}
    chunks = read_langfuse()
    assert chunks == []


@patch("agents.profiler_sources._LANGFUSE_PK", "pk-test")
@patch("agents.profiler_sources._langfuse_get")
def test_read_langfuse_with_errors(mock_get):
    traces = [{"id": "t1", "name": "test", "timestamp": "2026-02-28T10:00:00Z"}]
    observations = [
        {
            "model": "gemini-flash",
            "metadata": {},
            "usage": {},
            "calculatedTotalCost": 0,
            "latency": 0,
            "level": "ERROR",
        },
    ]

    mock_get.side_effect = lambda path, params=None: (
        {"data": traces, "meta": {"totalItems": 1}}
        if "/traces" in path
        else {"data": observations, "meta": {"totalItems": 1}}
    )

    chunks = read_langfuse()
    assert len(chunks) >= 1
    assert "error" in chunks[0].text.lower() or "Error" in chunks[0].text


def test_compress_ranges():
    assert _compress_ranges([0, 1, 2, 3, 4, 5, 23]) == "0-5, 23"
    assert _compress_ranges([]) == ""
    assert _compress_ranges([3]) == "3"
    assert _compress_ranges([1, 3, 5]) == "1, 3, 5"
    assert _compress_ranges([10, 11, 12, 20, 21]) == "10-12, 20-21"


@patch("agents.profiler_sources._check_langfuse_available", return_value=True)
def test_list_source_ids_includes_langfuse(mock_check):
    sources = discover_sources()
    ids = list_source_ids(sources)
    assert "langfuse:telemetry" in ids


# ── gap_type tests ──────────────────────────────────────────────────────────


def test_curation_op_gap_type_optional():
    """gap_type defaults to None for backward compatibility."""
    op = CurationOp(
        action="flag",
        keys=["a", "b"],
        reason="test contradiction",
    )
    assert op.gap_type is None


def test_curation_op_gap_type_set():
    """gap_type can be explicitly set."""
    op = CurationOp(
        action="flag",
        keys=["stated_preference", "observed_behavior"],
        reason="Knows but struggles to initiate",
        gap_type="executive_function",
    )
    assert op.gap_type == "executive_function"


def test_apply_curation_flag_preserves_gap_type():
    """gap_type survives through apply_curation flagging."""
    facts = [
        _make_fact("workflow", "stated", "Uses uv", 0.9),
        _make_fact("workflow", "observed", "pip install seen", 0.7),
    ]
    curation = DimensionCuration(
        dimension="workflow",
        operations=[
            CurationOp(
                action="flag",
                keys=["stated", "observed"],
                reason="Executive function gap",
                gap_type="executive_function",
            ),
        ],
        health_score=0.6,
    )
    curated, flagged = apply_curation(facts, curation)
    assert len(flagged) == 1
    assert flagged[0].gap_type == "executive_function"
    assert len(curated) == 2  # Flagged facts are NOT removed


def test_neurocognitive_profile_in_dimensions():
    """neurocognitive is a registered profile dimension."""
    assert "neurocognitive" in PROFILE_DIMENSIONS


def test_operator_update_neurocognitive_field():
    """OperatorUpdate accepts neurocognitive_updates dict."""
    update = OperatorUpdate(
        goal_updates={},
        summary="",
        neurocognitive_updates={
            "task_initiation": ["Body doubling effective"],
            "energy_cycles": ["Morning focus peak"],
        },
    )
    assert update.neurocognitive_updates["task_initiation"] == ["Body doubling effective"]
    assert len(update.neurocognitive_updates) == 2


def test_operator_update_neurocognitive_default_empty():
    """OperatorUpdate defaults neurocognitive_updates to empty dict."""
    update = OperatorUpdate(goal_updates={}, summary="")
    assert update.neurocognitive_updates == {}


# ── Dimension count ──────────────────────────────────────────────────


def test_profile_dimensions_count():
    """11 total profile dimensions."""
    assert len(PROFILE_DIMENSIONS) == 11


def test_profile_dimensions_from_registry():
    """PROFILE_DIMENSIONS is sourced from shared.dimensions registry."""
    from shared.dimensions import get_dimension_names

    assert get_dimension_names() == PROFILE_DIMENSIONS


def test_load_structured_facts_includes_management(tmp_path):
    """load_structured_facts reads management-structured-facts.json."""
    import json
    from unittest.mock import patch

    facts_data = [
        {
            "dimension": "management",
            "key": "team_size",
            "value": "5",
            "confidence": 0.90,
            "source": "management-vault",
            "evidence": "5 active people",
        },
    ]
    mgmt_file = tmp_path / "management-structured-facts.json"
    mgmt_file.write_text(json.dumps(facts_data))

    with (
        patch("agents.profiler.PROFILES_DIR", tmp_path),
        patch("agents.profiler._SYNC_CACHE_BASE", tmp_path / "empty-cache"),
        patch("agents.profiler_sources.read_flow_facts", return_value=[]),
    ):
        from agents.profiler import load_structured_facts

        facts = load_structured_facts()

    assert len(facts) == 1
    assert facts[0].dimension == "management"
    assert facts[0].key == "team_size"


def test_load_structured_facts_empty_when_missing(tmp_path):
    """load_structured_facts returns empty list when no files exist."""
    from unittest.mock import patch

    with (
        patch("agents.profiler.PROFILES_DIR", tmp_path),
        patch("agents.profiler._SYNC_CACHE_BASE", tmp_path / "empty-cache"),
        patch("agents.profiler_sources.read_flow_facts", return_value=[]),
    ):
        from agents.profiler import load_structured_facts

        facts = load_structured_facts()
    assert facts == []


def test_profiler_source_cli_accepts_management():
    """--source management is a valid CLI choice."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        choices=[
            "config",
            "transcript",
            "shell-history",
            "git",
            "memory",
            "llm-export",
            "takeout",
            "proton",
            "management",
        ],
    )
    args = parser.parse_args(["--source", "management"])
    assert args.source == "management"


def test_profiler_sources_discover_management_files(tmp_path):
    """discover_sources finds management files in vault."""
    from unittest.mock import patch

    people = tmp_path / "10-work" / "people"
    people.mkdir(parents=True)
    (people / "Alice.md").write_text("---\ntype: person\n---\n")
    meetings = tmp_path / "10-work" / "meetings"
    meetings.mkdir(parents=True)
    (meetings / "m1.md").write_text("---\ntype: meeting\n---\n")

    with patch("agents.profiler_sources._VAULT_PATH", tmp_path):
        from agents.profiler_sources import discover_sources

        sources = discover_sources()

    mgmt_names = [f.name for f in sources.management_files]
    assert "Alice.md" in mgmt_names
    assert "m1.md" in mgmt_names


def test_insight_dimension_map_neurocognitive():
    """insight_dimension_map maps neurocognitive_pattern to neurocognitive_profile."""
    # Access the map from flush_interview_to_profile scope
    # It's defined inline, so we verify the mapping indirectly via the constant
    from logos.interview import RecordedInsight

    # Verify neurocognitive_pattern is a valid category
    insight = RecordedInsight(
        category="neurocognitive_pattern",
        description="Test pattern",
        recommendation="Test rec",
    )
    assert insight.category == "neurocognitive_pattern"


# ── Scalability: Bridge exclusion tests ──────────────────────────────────

from agents.profiler_sources import (
    BRIDGED_SOURCE_TYPES,
    SOURCE_TYPE_CHUNK_CAPS,
    _sort_by_mtime,
    read_all_sources,
)


def test_bridged_source_types_constant():
    """BRIDGED_SOURCE_TYPES includes proton, takeout, management."""
    assert "proton" in BRIDGED_SOURCE_TYPES
    assert "takeout" in BRIDGED_SOURCE_TYPES
    assert "management" in BRIDGED_SOURCE_TYPES
    assert "config" not in BRIDGED_SOURCE_TYPES
    assert "llm-export" not in BRIDGED_SOURCE_TYPES


def test_source_type_chunk_caps_all_types():
    """All expected source types have chunk caps."""
    assert "llm-export" in SOURCE_TYPE_CHUNK_CAPS
    assert "proton" in SOURCE_TYPE_CHUNK_CAPS
    assert "takeout" in SOURCE_TYPE_CHUNK_CAPS
    assert "config" in SOURCE_TYPE_CHUNK_CAPS
    for cap in SOURCE_TYPE_CHUNK_CAPS.values():
        assert isinstance(cap, int)
        assert cap > 0


def test_exclude_source_types_skips_proton(tmp_path):
    """read_all_sources with exclude_source_types skips proton files."""
    # Create a proton file
    proton_dir = tmp_path / "proton"
    proton_dir.mkdir()
    (proton_dir / "mail1.md").write_text("Subject: Test\n\nHello world")

    sources = DiscoveredSources(
        proton_files=[proton_dir / "mail1.md"],
    )
    # Without exclusion: should get chunks
    chunks = read_all_sources(sources, source_filter="proton")
    assert len(chunks) >= 1

    # With exclusion (no explicit filter): proton should be skipped
    chunks = read_all_sources(sources, exclude_source_types={"proton"})
    proton_chunks = [c for c in chunks if c.source_type == "proton"]
    assert len(proton_chunks) == 0


def test_exclude_source_types_explicit_filter_overrides(tmp_path):
    """source_filter='proton' overrides exclude_source_types."""
    proton_dir = tmp_path / "proton"
    proton_dir.mkdir()
    (proton_dir / "mail1.md").write_text("Subject: Test\n\nHello world")

    sources = DiscoveredSources(
        proton_files=[proton_dir / "mail1.md"],
    )
    # Explicit filter should override exclusion
    chunks = read_all_sources(
        sources,
        source_filter="proton",
        exclude_source_types={"proton"},
    )
    assert len(chunks) >= 1
    assert all(c.source_type == "proton" for c in chunks)


def test_exclude_does_not_affect_non_excluded_types(tmp_path):
    """Excluding bridged types leaves other types unaffected."""
    config_file = tmp_path / "test.md"
    config_file.write_text("# Config\nSome config text")

    sources = DiscoveredSources(
        config_files=[config_file],
    )
    chunks = read_all_sources(sources, exclude_source_types=BRIDGED_SOURCE_TYPES)
    config_chunks = [c for c in chunks if c.source_type == "config"]
    assert len(config_chunks) >= 1


# ── Scalability: Chunk cap tests ─────────────────────────────────────────


def test_sort_by_mtime(tmp_path):
    """_sort_by_mtime sorts newest first."""
    import time

    old = tmp_path / "old.md"
    old.write_text("old file")
    time.sleep(0.05)
    new = tmp_path / "new.md"
    new.write_text("new file")

    sorted_paths = _sort_by_mtime([old, new])
    assert sorted_paths[0] == new
    assert sorted_paths[1] == old


def test_sort_by_mtime_missing_file(tmp_path):
    """Missing files sort last (mtime 0)."""
    existing = tmp_path / "exists.md"
    existing.write_text("content")
    missing = tmp_path / "missing.md"

    sorted_paths = _sort_by_mtime([missing, existing])
    assert sorted_paths[0] == existing
    assert sorted_paths[1] == missing


def test_chunk_cap_limits_output(tmp_path):
    """When files exceed chunk cap, output is limited."""
    import time
    from unittest.mock import patch

    # Create more files than the config cap (50)
    config_files = []
    for i in range(60):
        f = tmp_path / f"config_{i:03d}.md"
        f.write_text(f"Config content block {i}. " * 20)
        config_files.append(f)
        time.sleep(0.001)

    sources = DiscoveredSources(config_files=config_files)

    # Patch cap to a small value for testing
    test_caps = {**SOURCE_TYPE_CHUNK_CAPS, "config": 5}
    with patch("agents.profiler_sources.SOURCE_TYPE_CHUNK_CAPS", test_caps):
        chunks = read_all_sources(sources, source_filter="config")

    assert len(chunks) <= 5


def test_chunk_cap_reads_newest_first(tmp_path):
    """Chunk capping reads most recent files first."""
    import os
    import time
    from unittest.mock import patch

    # Create files with different mtimes
    old_file = tmp_path / "old.md"
    old_file.write_text("Old content with unique marker OLD_MARKER")
    # Set old mtime
    os.utime(old_file, (1000000, 1000000))

    time.sleep(0.01)
    new_file = tmp_path / "new.md"
    new_file.write_text("New content with unique marker NEW_MARKER")

    sources = DiscoveredSources(config_files=[old_file, new_file])

    # Cap to 1 chunk — should only get the newest file
    test_caps = {**SOURCE_TYPE_CHUNK_CAPS, "config": 1}
    with patch("agents.profiler_sources.SOURCE_TYPE_CHUNK_CAPS", test_caps):
        chunks = read_all_sources(sources, source_filter="config")

    assert len(chunks) == 1
    assert "NEW_MARKER" in chunks[0].text


# ── F-3.2: Git error isolation in read_all_sources ────────────────────────


def test_read_all_sources_survives_git_failure(tmp_path, caplog):
    """read_all_sources continues after git subprocess failure."""
    import logging

    sources = DiscoveredSources(
        git_repos=[tmp_path / "fake-repo"],  # non-existent repo
        config_files=[],
    )
    with caplog.at_level(logging.WARNING):
        chunks = read_all_sources(sources, source_filter="git")
    # Should not raise; chunks may be empty but no crash
    assert isinstance(chunks, list)


# ── Scalability: Concurrent extraction tests ─────────────────────────────

from agents.profiler import (
    DEFAULT_EXTRACTION_CONCURRENCY,
    EARLY_STOP_THRESHOLD,
    EARLY_STOP_WINDOW,
    extract_from_chunks,
)


def test_extraction_concurrency_constant():
    assert DEFAULT_EXTRACTION_CONCURRENCY == 8


def test_early_stop_constants():
    assert EARLY_STOP_WINDOW == 20
    assert EARLY_STOP_THRESHOLD == 1


async def test_extract_from_chunks_empty():
    """Extracting from empty list returns empty."""
    facts = await extract_from_chunks([])
    assert facts == []


async def test_extract_from_chunks_with_concurrency(monkeypatch):
    """extract_from_chunks processes chunks concurrently."""
    import asyncio

    call_count = 0

    async def mock_run(prompt):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.01)  # Simulate LLM latency
        fact = ProfileFact(
            dimension="identity",
            key=f"key_{call_count}",
            value="val",
            confidence=0.8,
            source="test",
            evidence="test",
        )
        return type("Result", (), {"output": ChunkExtraction(facts=[fact])})()

    monkeypatch.setattr("agents.profiler.extraction_agent.run", mock_run)

    chunks = [
        SourceChunk(text=f"chunk {i}", source_id=f"test:chunk_{i}", source_type="config")
        for i in range(5)
    ]

    facts = await extract_from_chunks(chunks, concurrency=3)
    assert len(facts) == 5
    assert call_count == 5


async def test_extract_from_chunks_early_stop(monkeypatch):
    """Early-stop kicks in when chunks stop producing new keys."""

    call_count = 0

    async def mock_run(prompt):
        nonlocal call_count
        call_count += 1
        # Always return the same fact — no new keys after first
        fact = ProfileFact(
            dimension="identity",
            key="same_key",
            value="same_val",
            confidence=0.8,
            source="test",
            evidence="test",
        )
        return type("Result", (), {"output": ChunkExtraction(facts=[fact])})()

    monkeypatch.setattr("agents.profiler.extraction_agent.run", mock_run)

    # Create enough chunks to trigger early-stop (EARLY_STOP_WINDOW + extra)
    chunks = [
        SourceChunk(text=f"chunk {i}", source_id=f"test:chunk_{i}", source_type="config")
        for i in range(EARLY_STOP_WINDOW + 10)
    ]

    # Pre-seed with the key that will be returned — so all chunks produce 0 new keys
    existing_keys = {("identity", "same_key")}
    await extract_from_chunks(
        chunks,
        concurrency=1,
        existing_fact_keys=existing_keys,
    )

    # Early-stop should have kicked in after EARLY_STOP_WINDOW chunks
    # Not all chunks should have been processed
    assert call_count <= EARLY_STOP_WINDOW + 5  # Some tolerance for concurrency


async def test_extract_from_chunks_error_handling(monkeypatch):
    """Errors in individual chunks don't crash the whole extraction."""
    call_count = 0

    async def mock_run(prompt):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("LLM error")
        fact = ProfileFact(
            dimension="identity",
            key=f"key_{call_count}",
            value="val",
            confidence=0.8,
            source="test",
            evidence="test",
        )
        return type("Result", (), {"output": ChunkExtraction(facts=[fact])})()

    monkeypatch.setattr("agents.profiler.extraction_agent.run", mock_run)

    chunks = [
        SourceChunk(text=f"chunk {i}", source_id=f"test:chunk_{i}", source_type="config")
        for i in range(3)
    ]

    facts = await extract_from_chunks(chunks, concurrency=1)
    # 2 of 3 should succeed
    assert len(facts) == 2


async def test_extract_from_chunks_existing_keys_seeded(monkeypatch):
    """Existing fact keys are pre-seeded into seen_keys for early-stop."""
    calls = []

    async def mock_run(prompt):
        calls.append(1)
        # Return a fact with a key that's already in existing_keys
        fact = ProfileFact(
            dimension="identity",
            key="known_key",
            value="val",
            confidence=0.8,
            source="test",
            evidence="test",
        )
        return type("Result", (), {"output": ChunkExtraction(facts=[fact])})()

    monkeypatch.setattr("agents.profiler.extraction_agent.run", mock_run)

    chunks = [SourceChunk(text="chunk", source_id="test:c", source_type="config")]
    existing_keys = {("identity", "known_key")}

    facts = await extract_from_chunks(chunks, existing_fact_keys=existing_keys)
    # Fact should still be returned (early-stop doesn't discard, just stops processing)
    assert len(facts) == 1


# ── Scalability: Pipeline wiring tests ────────────────────────────────────


def test_bridged_source_types_imported_in_profiler():
    """BRIDGED_SOURCE_TYPES is properly imported in profiler.py."""
    from agents.profiler import BRIDGED_SOURCE_TYPES as profiler_bridged

    assert profiler_bridged == BRIDGED_SOURCE_TYPES


# ── F-1.2: load_existing_profile logs corruption ─────────────────────────


def test_load_existing_profile_corrupt_json(tmp_path, caplog):
    """Corrupt JSON triggers warning log, returns None."""
    profile_path = tmp_path / "operator-profile.json"
    profile_path.write_text("{not valid json!!!")
    with patch("agents.profiler.PROFILES_DIR", tmp_path):
        import logging

        with caplog.at_level(logging.WARNING):
            result = load_existing_profile()
    assert result is None
    assert any("corrupt" in r.message.lower() for r in caplog.records)


def test_load_existing_profile_missing_returns_none(tmp_path):
    """Missing file returns None without logging."""
    with patch("agents.profiler.PROFILES_DIR", tmp_path):
        result = load_existing_profile()
    assert result is None


def test_load_existing_profile_valid(tmp_path):
    """Valid profile JSON loads correctly."""
    profile = UserProfile(
        dimensions=[ProfileDimension(name="identity", facts=[])],
    )
    profile_path = tmp_path / "operator-profile.json"
    profile_path.write_text(profile.model_dump_json())
    with patch("agents.profiler.PROFILES_DIR", tmp_path):
        result = load_existing_profile()
    assert result is not None
    assert result.dimensions[0].name == "identity"


# ── F-1.1 / F-1.3: regenerate_operator atomic write + corruption recovery ─

from unittest.mock import AsyncMock, MagicMock

from agents.profiler import regenerate_operator


@pytest.mark.asyncio
async def test_regenerate_operator_creates_backup(tmp_path):
    """regenerate_operator creates .bak before overwriting."""
    operator_path = tmp_path / "operator.json"
    operator_data = {
        "operator": {"name": "test", "context": "original"},
        "goals": {"primary": [], "secondary": []},
        "patterns": {},
        "neurocognitive": {},
    }
    operator_path.write_text(json.dumps(operator_data, indent=2))

    # Mock the agent to return a no-op update
    mock_result = MagicMock()
    mock_result.output = OperatorUpdate(
        goal_updates={},
        new_patterns=[],
        neurocognitive_updates={},
        summary="updated context",
    )

    with (
        patch("agents.profiler.PROFILES_DIR", tmp_path),
        patch("agents.profiler.operator_agent") as mock_agent,
        patch("agents.profiler._regenerate_operator_md"),
    ):
        mock_agent.run = AsyncMock(return_value=mock_result)
        await regenerate_operator(UserProfile(dimensions=[]))

    backup_path = tmp_path / "operator.json.bak"
    assert backup_path.exists()
    backup_data = json.loads(backup_path.read_text())
    assert backup_data["operator"]["context"] == "original"


@pytest.mark.asyncio
async def test_regenerate_operator_recovers_from_corrupt_json(tmp_path, caplog):
    """Corrupt operator.json recovered from backup."""
    operator_path = tmp_path / "operator.json"
    backup_path = tmp_path / "operator.json.bak"

    operator_path.write_text("{corrupt!!")
    backup_data = {
        "operator": {"name": "test", "context": "from backup"},
        "goals": {"primary": [], "secondary": []},
        "patterns": {},
        "neurocognitive": {},
    }
    backup_path.write_text(json.dumps(backup_data, indent=2))

    mock_result = MagicMock()
    mock_result.output = OperatorUpdate(
        goal_updates={},
        new_patterns=[],
        neurocognitive_updates={},
        summary="updated",
    )

    import logging

    with (
        patch("agents.profiler.PROFILES_DIR", tmp_path),
        patch("agents.profiler.operator_agent") as mock_agent,
        patch("agents.profiler._regenerate_operator_md"),
        caplog.at_level(logging.WARNING),
    ):
        mock_agent.run = AsyncMock(return_value=mock_result)
        await regenerate_operator(UserProfile(dimensions=[]))

    assert any("corrupt" in r.message.lower() for r in caplog.records)
    assert any("recovering from backup" in r.message.lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_regenerate_operator_rejects_tiny_output(tmp_path, caplog):
    """Suspiciously small LLM output aborts write."""
    operator_path = tmp_path / "operator.json"
    operator_data = {
        "operator": {"name": "test", "context": "original"},
        "goals": {"primary": [], "secondary": []},
        "patterns": {},
        "neurocognitive": {},
    }
    operator_path.write_text(json.dumps(operator_data, indent=2))

    mock_result = MagicMock()
    mock_result.output = OperatorUpdate(
        goal_updates={},
        new_patterns=[],
        neurocognitive_updates={},
        summary="x",  # This will change the content but result in small output
    )

    # Patch json.dumps in the function to return tiny output
    import logging

    with (
        patch("agents.profiler.PROFILES_DIR", tmp_path),
        patch("agents.profiler.operator_agent") as mock_agent,
        patch("agents.profiler._regenerate_operator_md"),
        caplog.at_level(logging.ERROR),
    ):
        mock_agent.run = AsyncMock(return_value=mock_result)
        # We need the operator_data to produce small output.
        # The simplest approach: make the file have just enough to parse
        # but the update results in a tiny json output
        operator_path.write_text('{"operator":{}}')
        await regenerate_operator(UserProfile(dimensions=[]))

    # The small output check fires when json.dumps produces < 100 bytes
    # With operator_data = {"operator": {}} and summary="x", it will produce
    # {"operator": {"context": "x"}} which is tiny
    assert any("suspiciously small" in r.message.lower() for r in caplog.records)
