"""Tests for Stage 7: Profile Visibility.

Covers: apply_corrections, /profile command parsing, read_profile tool,
and correction authority (operator:correction gets confidence 1.0).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.profiler import (
    ProfileFact,
    ProfileDimension,
    UserProfile,
    apply_corrections,
    load_existing_profile,
    merge_facts,
    PROFILE_DIMENSIONS,
    AUTHORITY_SOURCES,
)
from shared.config import PROFILES_DIR


# ── Fixtures ──────────────────────────────────────────────────────────────

def _make_profile(facts: list[ProfileFact], version: int = 1) -> UserProfile:
    """Build a minimal UserProfile for testing."""
    from agents.profiler import group_facts_by_dimension

    grouped = group_facts_by_dimension(facts)
    dimensions = []
    for dim_name, dim_facts in grouped.items():
        dimensions.append(ProfileDimension(
            name=dim_name,
            summary=f"Summary for {dim_name}",
            facts=dim_facts,
        ))
    return UserProfile(
        name="Test",
        summary="Test profile",
        dimensions=dimensions,
        sources_processed=["test"],
        version=version,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


@pytest.fixture
def profile_dir(tmp_path):
    """Set up a temp profiles directory with a basic profile."""
    facts = [
        ProfileFact(
            dimension="work_patterns",
            key="preferred_editor",
            value="neovim",
            confidence=0.9,
            source="interview:cockpit",
            evidence="operator said neovim",
        ),
        ProfileFact(
            dimension="work_patterns",
            key="preferred_tool",
            value="uv",
            confidence=0.8,
            source="config:CLAUDE.md",
            evidence="always use uv",
        ),
        ProfileFact(
            dimension="identity",
            key="primary_language",
            value="python",
            confidence=0.9,
            source="config:CLAUDE.md",
            evidence="Python toolchain",
        ),
    ]
    profile = _make_profile(facts)
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "ryan.json").write_text(profile.model_dump_json(indent=2))
    return profiles_dir


# ── apply_corrections tests ───────────────────────────────────────────────

def test_apply_correction_updates_value(profile_dir):
    """Correcting a fact replaces its value."""
    with patch("agents.profiler.PROFILES_DIR", profile_dir):
        result = apply_corrections([{
            "dimension": "work_patterns",
            "key": "preferred_editor",
            "value": "vscode",
        }])
    assert "corrected" in result
    # Verify the profile was updated
    with patch("agents.profiler.PROFILES_DIR", profile_dir):
        profile = load_existing_profile()
    editor_facts = [
        f for d in profile.dimensions for f in d.facts
        if f.key == "preferred_editor"
    ]
    assert len(editor_facts) == 1
    assert editor_facts[0].value == "vscode"
    assert editor_facts[0].confidence == 1.0
    assert editor_facts[0].source == "operator:correction"


def test_apply_correction_deletes_fact(profile_dir):
    """Deleting a fact removes it from the profile."""
    with patch("agents.profiler.PROFILES_DIR", profile_dir):
        result = apply_corrections([{
            "dimension": "work_patterns",
            "key": "preferred_editor",
            "value": None,
        }])
    assert "deleted" in result
    with patch("agents.profiler.PROFILES_DIR", profile_dir):
        profile = load_existing_profile()
    editor_facts = [
        f for d in profile.dimensions for f in d.facts
        if f.key == "preferred_editor"
    ]
    assert len(editor_facts) == 0


def test_apply_correction_increments_version(profile_dir):
    """Corrections bump the profile version."""
    with patch("agents.profiler.PROFILES_DIR", profile_dir):
        before = load_existing_profile()
        apply_corrections([{"dimension": "work_patterns", "key": "preferred_editor", "value": "emacs"}])
        after = load_existing_profile()
    assert after.version == before.version + 1


def test_apply_correction_preserves_other_facts(profile_dir):
    """Correcting one fact doesn't affect other facts."""
    with patch("agents.profiler.PROFILES_DIR", profile_dir):
        apply_corrections([{"dimension": "work_patterns", "key": "preferred_editor", "value": "emacs"}])
        profile = load_existing_profile()
    tool_facts = [
        f for d in profile.dimensions for f in d.facts
        if f.key == "preferred_tool"
    ]
    assert len(tool_facts) == 1
    assert tool_facts[0].value == "uv"


def test_apply_correction_no_profile(tmp_path):
    """Returns error message when no profile exists."""
    empty_dir = tmp_path / "profiles"
    empty_dir.mkdir()
    with patch("agents.profiler.PROFILES_DIR", empty_dir):
        result = apply_corrections([{"dimension": "work_patterns", "key": "x", "value": "y"}])
    assert "No profile found" in result


def test_apply_multiple_corrections(profile_dir):
    """Multiple corrections in one call."""
    with patch("agents.profiler.PROFILES_DIR", profile_dir):
        result = apply_corrections([
            {"dimension": "work_patterns", "key": "preferred_editor", "value": "emacs"},
            {"dimension": "identity", "key": "primary_language", "value": None},
        ])
    assert "corrected" in result
    assert "deleted" in result
    with patch("agents.profiler.PROFILES_DIR", profile_dir):
        profile = load_existing_profile()
    all_facts = [f for d in profile.dimensions for f in d.facts]
    keys = {f.key for f in all_facts}
    assert "preferred_editor" in keys
    assert "primary_language" not in keys


# ── Correction authority tests ────────────────────────────────────────────

def test_operator_correction_is_authority():
    """'operator' prefix is in AUTHORITY_SOURCES — corrections override everything."""
    assert "operator" in AUTHORITY_SOURCES


def test_correction_overrides_interview():
    """operator:correction (conf 1.0) overrides interview (conf 0.9)."""
    existing = [ProfileFact(
        dimension="work_patterns",
        key="preferred_editor",
        value="neovim",
        confidence=0.9,
        source="interview:cockpit",
        evidence="said so",
    )]
    correction = [ProfileFact(
        dimension="work_patterns",
        key="preferred_editor",
        value="vscode",
        confidence=1.0,
        source="operator:correction",
        evidence="operator correction",
    )]
    merged = merge_facts(existing, correction)
    result = {f.key: f.value for f in merged}
    assert result["preferred_editor"] == "vscode"


def test_correction_overrides_config():
    """operator:correction overrides config-sourced facts."""
    existing = [ProfileFact(
        dimension="work_patterns",
        key="preferred_tool",
        value="uv",
        confidence=0.8,
        source="config:CLAUDE.md",
        evidence="from config",
    )]
    correction = [ProfileFact(
        dimension="work_patterns",
        key="preferred_tool",
        value="poetry",
        confidence=1.0,
        source="operator:correction",
        evidence="operator correction",
    )]
    merged = merge_facts(existing, correction)
    result = {f.key: f.value for f in merged}
    assert result["preferred_tool"] == "poetry"
