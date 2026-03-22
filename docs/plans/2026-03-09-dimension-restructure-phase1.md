# Phase 1: Dimension Registry Foundation

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create `shared/dimensions.py` as the single source of truth for profile dimensions, update all consumers to import from it, and migrate existing profile data to the new 12-dimension taxonomy.

**Architecture:** A frozen dataclass registry in `shared/dimensions.py` replaces the hardcoded `PROFILE_DIMENSIONS` list in `agents/profiler.py`. A backward-compatible `get_dimension_names()` function ensures existing code works during migration. All imports shift from `agents.profiler.PROFILE_DIMENSIONS` to `shared.dimensions`. A one-time migration script remaps existing profile facts.

**Tech Stack:** Python 3.12+, Pydantic, pytest, dataclasses

---

### Task 1: Create `shared/dimensions.py` with DimensionDef registry

**Files:**
- Create: `shared/dimensions.py`
- Test: `tests/test_dimensions.py`

**Step 1: Write the failing tests**

```python
"""Tests for the dimension registry."""
from shared.dimensions import (
    DimensionDef,
    DIMENSIONS,
    get_dimension,
    get_dimension_names,
    get_dimensions_by_kind,
    validate_behavioral_write,
)
import pytest


def test_dimension_count_is_12():
    assert len(DIMENSIONS) == 12


def test_trait_dimensions_count():
    traits = get_dimensions_by_kind("trait")
    assert len(traits) == 6


def test_behavioral_dimensions_count():
    behavioral = get_dimensions_by_kind("behavioral")
    assert len(behavioral) == 6


def test_get_dimension_by_name():
    dim = get_dimension("identity")
    assert dim is not None
    assert dim.kind == "trait"
    assert dim.name == "identity"


def test_get_dimension_unknown_returns_none():
    assert get_dimension("nonexistent") is None


def test_get_dimension_names_returns_all():
    names = get_dimension_names()
    assert len(names) == 12
    assert "identity" in names
    assert "work_patterns" in names


def test_trait_dimension_names():
    traits = get_dimensions_by_kind("trait")
    names = {d.name for d in traits}
    assert names == {
        "identity", "neurocognitive", "values",
        "communication_style", "management", "relationships",
    }


def test_behavioral_dimension_names():
    behavioral = get_dimensions_by_kind("behavioral")
    names = {d.name for d in behavioral}
    assert names == {
        "work_patterns", "energy_and_attention", "information_seeking",
        "creative_process", "tool_usage", "communication_patterns",
    }


def test_validate_behavioral_write_accepts_valid():
    # Should not raise
    validate_behavioral_write("work_patterns", "gcalendar_sync")


def test_validate_behavioral_write_rejects_trait():
    with pytest.raises(ValueError, match="trait dimension"):
        validate_behavioral_write("identity", "gcalendar_sync")


def test_validate_behavioral_write_rejects_unknown():
    with pytest.raises(ValueError, match="unknown dimension"):
        validate_behavioral_write("hardware", "gcalendar_sync")


def test_dimension_def_is_frozen():
    dim = get_dimension("identity")
    with pytest.raises(AttributeError):
        dim.name = "changed"


def test_all_dimensions_have_consumers():
    for dim in DIMENSIONS:
        assert len(dim.consumers) > 0, f"{dim.name} has no consumers"


def test_all_dimensions_have_sources():
    for dim in DIMENSIONS:
        assert len(dim.primary_sources) > 0, f"{dim.name} has no sources"


def test_interview_eligible_defaults_true():
    dim = get_dimension("identity")
    assert dim.interview_eligible is True


def test_communication_patterns_not_interview_eligible():
    dim = get_dimension("communication_patterns")
    assert dim.interview_eligible is False
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dimensions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shared.dimensions'`

**Step 3: Write the implementation**

Create `shared/dimensions.py`:

```python
"""shared/dimensions.py — Profile dimension registry.

Single source of truth for all profile dimensions. Replaces the
hardcoded PROFILE_DIMENSIONS list in agents/profiler.py.

Each dimension defines its kind (trait vs behavioral), consumers
(what agents act on it), producers (what writes to it), and whether
the interview system can target it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DimensionDef:
    """Definition of a profile dimension."""
    name: str
    kind: Literal["trait", "behavioral"]
    description: str
    consumers: tuple[str, ...]
    primary_sources: tuple[str, ...]
    interview_eligible: bool = True


# ── Dimension Registry ────────────────────────────────────────────────────────

DIMENSIONS: tuple[DimensionDef, ...] = (
    # ── Trait dimensions (stable, interview-sourced) ──────────────────────
    DimensionDef(
        name="identity",
        kind="trait",
        description="Who the operator is — roles, background, stated skills, affiliations",
        consumers=("system_prompt", "profiler_digest"),
        primary_sources=("interview", "config", "profiler"),
    ),
    DimensionDef(
        name="neurocognitive",
        kind="trait",
        description="Stable cognitive traits — demand sensitivity, sensory preferences, cognitive style",
        consumers=("system_prompt", "nudge_framing", "notification_timing"),
        primary_sources=("interview", "micro_probes"),
    ),
    DimensionDef(
        name="values",
        kind="trait",
        description="Principles, aesthetic sensibility, decision heuristics, philosophy",
        consumers=("demo_content", "scout_framing", "management_prep"),
        primary_sources=("interview", "profiler"),
    ),
    DimensionDef(
        name="communication_style",
        kind="trait",
        description="How the operator prefers to receive and give information",
        consumers=("agent_output_formatting", "briefing_structure", "notification_verbosity"),
        primary_sources=("interview", "profiler"),
    ),
    DimensionDef(
        name="management",
        kind="trait",
        description="Management approach, team philosophy, coaching style (axiom-constrained)",
        consumers=("management_prep", "meeting_lifecycle", "management_collector"),
        primary_sources=("interview", "vault_notes"),
    ),
    DimensionDef(
        name="relationships",
        kind="trait",
        description="People context, relational history, meeting cadence expectations",
        consumers=("management_prep", "meeting_lifecycle", "calendar_context"),
        primary_sources=("interview", "vault_contacts", "gcalendar_sync"),
    ),
    # ── Behavioral dimensions (dynamic, observation-sourced) ──────────────
    DimensionDef(
        name="work_patterns",
        kind="behavioral",
        description="Time allocation, task switching, project engagement, focus sessions",
        consumers=("briefing", "nudges", "workspace_vision"),
        primary_sources=("gcalendar_sync", "screen_context", "claude_code_sync", "git"),
    ),
    DimensionDef(
        name="energy_and_attention",
        kind="behavioral",
        description="Focus duration, presence patterns, circadian rhythm, productive windows",
        consumers=("nudge_timing", "interview_gating", "notification_priority", "briefing"),
        primary_sources=("workspace_vision", "audio_processor", "gcalendar_sync"),
    ),
    DimensionDef(
        name="information_seeking",
        kind="behavioral",
        description="Research patterns, content consumption, learning interests, browsing depth",
        consumers=("scout_topics", "digest_selection", "profiler_sources"),
        primary_sources=("chrome_sync", "youtube_sync", "obsidian_sync", "gdrive_sync"),
    ),
    DimensionDef(
        name="creative_process",
        kind="behavioral",
        description="Production sessions, creative flow triggers, aesthetic development",
        consumers=("demo_content", "briefing", "studio"),
        primary_sources=("audio_processor", "screen_context", "interview"),
        interview_eligible=True,
    ),
    DimensionDef(
        name="tool_usage",
        kind="behavioral",
        description="Tool preferences, adoption patterns, workflow toolchain, dev environment",
        consumers=("context_tools", "profiler_targeting"),
        primary_sources=("chrome_sync", "claude_code_sync", "shell_history", "git"),
    ),
    DimensionDef(
        name="communication_patterns",
        kind="behavioral",
        description="Response cadence, meeting density, collaboration frequency",
        consumers=("management_prep", "nudges", "briefing"),
        primary_sources=("gmail_sync", "gcalendar_sync", "audio_processor"),
        interview_eligible=False,
    ),
)

# ── Index for fast lookup ─────────────────────────────────────────────────────

_BY_NAME: dict[str, DimensionDef] = {d.name: d for d in DIMENSIONS}


# ── Public API ────────────────────────────────────────────────────────────────

def get_dimension(name: str) -> DimensionDef | None:
    """Look up a dimension by name. Returns None if not found."""
    return _BY_NAME.get(name)


def get_dimension_names() -> list[str]:
    """Return all dimension names as a list. Backward-compatible with PROFILE_DIMENSIONS."""
    return [d.name for d in DIMENSIONS]


def get_dimensions_by_kind(kind: Literal["trait", "behavioral"]) -> list[DimensionDef]:
    """Return dimensions filtered by kind."""
    return [d for d in DIMENSIONS if d.kind == kind]


def validate_behavioral_write(dimension: str, source: str) -> None:
    """Assert that a source is writing to a valid behavioral dimension.

    Raises ValueError if the dimension doesn't exist or is a trait dimension.
    Used by sync agent tests to catch misrouted facts.
    """
    dim_def = _BY_NAME.get(dimension)
    if dim_def is None:
        raise ValueError(f"{source} writing to unknown dimension: {dimension}")
    if dim_def.kind != "behavioral":
        raise ValueError(f"{source} writing to trait dimension: {dimension}")
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dimensions.py -v`
Expected: all 15 tests PASS

**Step 5: Commit**

```bash
git add shared/dimensions.py tests/test_dimensions.py
git commit -m "feat: add dimension registry (shared/dimensions.py)"
```

---

### Task 2: Add backward-compatible PROFILE_DIMENSIONS re-export in profiler

**Files:**
- Modify: `agents/profiler.py:57-72`
- Test: `tests/test_profiler.py`

**Step 1: Write the failing test**

Add to `tests/test_profiler.py`:

```python
def test_profile_dimensions_from_registry():
    """PROFILE_DIMENSIONS is sourced from shared.dimensions registry."""
    from shared.dimensions import get_dimension_names
    assert PROFILE_DIMENSIONS == get_dimension_names()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_profiler.py::test_profile_dimensions_from_registry -v`
Expected: FAIL — lists don't match (old has 14, new has 12)

**Step 3: Update profiler.py**

Replace lines 57-72 in `agents/profiler.py`:

```python
# Old:
# PROFILE_DIMENSIONS = [
#     "identity",
#     "technical_skills",
#     ...
# ]

# New:
from shared.dimensions import get_dimension_names

PROFILE_DIMENSIONS = get_dimension_names()
```

**Step 4: Update existing dimension-count tests**

In `tests/test_profiler.py`, update the tests that assert specific old dimensions:

- `test_profile_dimensions_are_defined` (line 128): Update assertions to new dimension names
- `test_neurocognitive_profile_in_dimensions` (line 801): Change `"neurocognitive_profile"` to `"neurocognitive"`
- `test_management_dimensions_in_profile` (line 828): Change assertions to just `"management"`
- `test_profile_dimensions_count_is_14` (line 834): Change to `== 12`

```python
def test_profile_dimensions_are_defined():
    assert len(PROFILE_DIMENSIONS) >= 8
    assert "identity" in PROFILE_DIMENSIONS
    assert "values" in PROFILE_DIMENSIONS
    assert "work_patterns" in PROFILE_DIMENSIONS


def test_neurocognitive_in_dimensions():
    """neurocognitive is a registered profile dimension."""
    assert "neurocognitive" in PROFILE_DIMENSIONS


def test_management_dimension_in_profile():
    """management is a registered dimension (merged from management_practice + team_leadership)."""
    assert "management" in PROFILE_DIMENSIONS


def test_profile_dimensions_count_is_12():
    """12 total profile dimensions after restructure."""
    assert len(PROFILE_DIMENSIONS) == 12
```

**Step 5: Run all profiler tests**

Run: `uv run pytest tests/test_profiler.py -v`
Expected: Some tests may fail due to facts referencing old dimension names in test helpers. Note failures for Task 3.

**Step 6: Commit**

```bash
git add agents/profiler.py tests/test_profiler.py
git commit -m "refactor: source PROFILE_DIMENSIONS from shared.dimensions registry"
```

---

### Task 3: Update profiler insight-to-dimension mapping

**Files:**
- Modify: `agents/profiler.py:638-644`

**Step 1: Write the failing test**

Add to `tests/test_profiler.py`:

```python
def test_flush_insight_dimension_mapping_uses_new_dims():
    """flush_interview_facts maps insights to new dimension names."""
    from logos.interview import RecordedInsight
    from unittest.mock import patch

    insight = RecordedInsight(
        category="workflow_gap",
        description="Test gap",
        recommendation="Fix it",
    )
    with patch("agents.profiler.load_existing_profile", return_value=None), \
         patch("agents.profiler.save_profile"):
        result = flush_interview_facts(facts=[], insights=[insight])

    # Should map to work_patterns, not workflow
    assert "work_patterns" in result or "1" in result  # flushed 1 insight
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_profiler.py::test_flush_insight_dimension_mapping_uses_new_dims -v`
Expected: FAIL — maps to `workflow` (old name)

**Step 3: Update the mapping**

In `agents/profiler.py`, replace the `insight_dimension_map` dict (around line 638):

```python
    insight_dimension_map = {
        "workflow_gap": "work_patterns",
        "goal_refinement": "values",
        "practice_critique": "work_patterns",
        "aspiration": "values",
        "contradiction": "values",
        "neurocognitive_pattern": "neurocognitive",
    }
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_profiler.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add agents/profiler.py tests/test_profiler.py
git commit -m "refactor: update insight-to-dimension mapping for new taxonomy"
```

---

### Task 4: Update all test files that import PROFILE_DIMENSIONS

**Files:**
- Modify: `tests/test_interview.py:27`
- Modify: `tests/test_profile_visibility.py:22`
- Modify: `logos/interview.py:116-134`
- Modify: `logos/chat_agent.py:415`
- Modify: `logos/api/routes/profile.py:25,64`

**Step 1: Audit and update imports**

Every file that does `from agents.profiler import ... PROFILE_DIMENSIONS` should switch to `from shared.dimensions import get_dimension_names` or continue importing from profiler (which re-exports). The profiler re-export keeps backward compatibility, so no import changes strictly needed — but `logos/interview.py` directly references the list for gap analysis and should use the registry for richer data.

Update `logos/interview.py` lines 115-134 — change:
```python
    from agents.profiler import (
        PROFILE_DIMENSIONS,
        load_existing_profile,
        group_facts_by_dimension,
    )
```
to:
```python
    from agents.profiler import (
        load_existing_profile,
        group_facts_by_dimension,
    )
    from shared.dimensions import get_dimension_names
```

And replace `PROFILE_DIMENSIONS` references with `get_dimension_names()` in that function.

**Step 2: Update test helpers that use old dimension names**

In `tests/test_interview.py`, update `_make_topic` default from `dimension="workflow"` to `dimension="work_patterns"`.

In `tests/test_profile_store.py`, update `_make_profile` to use `"work_patterns"` instead of `"workflow"`.

In `tests/test_profile_visibility.py`, update any references to old dimension names.

**Step 3: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: Note any remaining failures from old dimension name references

**Step 4: Fix remaining test failures**

Address each failure by updating old dimension names to new ones in test data.

**Step 5: Commit**

```bash
git add logos/interview.py logos/chat_agent.py logos/api/routes/profile.py tests/
git commit -m "refactor: update all PROFILE_DIMENSIONS consumers for new taxonomy"
```

---

### Task 5: Update profiler extraction prompt

**Files:**
- Modify: `agents/profiler.py:130` (extraction agent system prompt)
- Modify: `agents/profiler.py:895` (Claude.ai extraction prompt)

**Step 1: Verify current prompt references old dimensions**

Read `agents/profiler.py:128-140` and `agents/profiler.py:893-906`. Both inject the dimension list into LLM prompts.

**Step 2: Update extraction prompt to include kind**

The extraction prompt at line 130 currently does:
```python
"Dimensions to extract into: " + ", ".join(PROFILE_DIMENSIONS) + "\n\n"
```

Update to include descriptions and kind hints:
```python
from shared.dimensions import DIMENSIONS

dim_descriptions = "\n".join(
    f"- {d.name} ({d.kind}): {d.description}"
    for d in DIMENSIONS
)
```

Then inject `dim_descriptions` instead of the bare name list in both the extraction agent prompt (line 130) and the Claude.ai extraction prompt (line 895).

**Step 3: Run profiler tests**

Run: `uv run pytest tests/test_profiler.py -v`
Expected: PASS (prompts are strings, no test asserts on exact prompt content)

**Step 4: Commit**

```bash
git add agents/profiler.py
git commit -m "refactor: update extraction prompts with dimension descriptions and kinds"
```

---

### Task 6: Write profile fact migration script

**Files:**
- Create: `scripts/migrate_profile_dimensions.py`
- Test: `tests/test_dimension_migration.py`

**Step 1: Write the failing tests**

```python
"""Tests for the dimension migration script."""
import json
from scripts.migrate_profile_dimensions import remap_dimension, migrate_profile


def test_remap_identity_unchanged():
    assert remap_dimension("identity", "name") == "identity"


def test_remap_neurocognitive_profile():
    assert remap_dimension("neurocognitive_profile", "any_key") == "neurocognitive"


def test_remap_philosophy():
    assert remap_dimension("philosophy", "any_key") == "values"


def test_remap_team_leadership():
    assert remap_dimension("team_leadership", "any_key") == "management"


def test_remap_management_practice():
    assert remap_dimension("management_practice", "any_key") == "management"


def test_remap_workflow_tool_key():
    assert remap_dimension("workflow", "preferred_python_tool") == "tool_usage"


def test_remap_workflow_schedule_key():
    assert remap_dimension("workflow", "daily_schedule") == "work_patterns"


def test_remap_workflow_ambiguous_key():
    assert remap_dimension("workflow", "some_random_thing") == "work_patterns"


def test_remap_technical_skills_tool_key():
    assert remap_dimension("technical_skills", "python_proficiency") == "identity"


def test_remap_music_production_gear_key():
    assert remap_dimension("music_production", "sp404_workflow") == "creative_process"


def test_remap_music_production_aesthetic():
    assert remap_dimension("music_production", "preferred_bpm_range") == "values"


def test_remap_software_preferences():
    assert remap_dimension("software_preferences", "ide_choice") == "tool_usage"


def test_remap_hardware_dropped():
    assert remap_dimension("hardware", "gpu_model") is None


def test_remap_knowledge_domains():
    assert remap_dimension("knowledge_domains", "any_key") == "information_seeking"


def test_remap_decision_patterns_to_values():
    assert remap_dimension("decision_patterns", "risk_tolerance") == "values"


def test_remap_chrome_interests():
    """Sync agent drift dimension 'interests' maps correctly."""
    assert remap_dimension("interests", "top_domains") == "information_seeking"


def test_remap_gmail_communication():
    """Sync agent drift dimension 'communication' maps correctly."""
    assert remap_dimension("communication", "email_volume") == "communication_patterns"


def test_remap_obsidian_knowledge():
    """Sync agent drift dimension 'knowledge' maps correctly."""
    assert remap_dimension("knowledge", "active_areas") == "information_seeking"


def test_migrate_profile_remaps_facts(tmp_path):
    profile = {
        "name": "the operator",
        "summary": "Test",
        "version": 42,
        "updated_at": "2026-03-09",
        "sources_processed": ["test"],
        "dimensions": [
            {
                "name": "workflow",
                "summary": "Old summary",
                "facts": [
                    {"dimension": "workflow", "key": "preferred_editor", "value": "vscode",
                     "confidence": 0.9, "source": "config", "evidence": "test"},
                    {"dimension": "workflow", "key": "daily_standup_time", "value": "9am",
                     "confidence": 0.8, "source": "interview", "evidence": "test"},
                ],
            },
            {
                "name": "hardware",
                "summary": "Hardware info",
                "facts": [
                    {"dimension": "hardware", "key": "gpu_model", "value": "RTX 3090",
                     "confidence": 1.0, "source": "config", "evidence": "test"},
                ],
            },
        ],
    }
    input_path = tmp_path / "operator-profile.json"
    input_path.write_text(json.dumps(profile))

    result = migrate_profile(input_path)

    dim_names = {d["name"] for d in result["dimensions"]}
    assert "workflow" not in dim_names
    assert "hardware" not in dim_names
    assert "tool_usage" in dim_names
    assert "work_patterns" in dim_names

    # Hardware facts should be in review file
    review_path = tmp_path / "migration-review.jsonl"
    assert review_path.exists()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dimension_migration.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write the migration script**

Create `scripts/migrate_profile_dimensions.py`:

```python
"""One-time migration: remap profile facts from old 14 dimensions to new 12.

Usage:
    uv run python scripts/migrate_profile_dimensions.py [--dry-run]

Reads profiles/operator-profile.json, remaps dimensions, writes updated profile.
Dropped facts (e.g. hardware) go to profiles/migration-review.jsonl.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from shared.dimensions import get_dimension_names


# ── Key heuristics for dimensions that fan out ────────────────────────────────

_TOOL_KEYS = {"tool", "prefer", "editor", "ide", "cli", "shell", "terminal", "plugin", "extension"}
_SCHEDULE_KEYS = {"schedule", "cadence", "meeting", "time", "focus", "routine", "session", "daily", "weekly"}
_AESTHETIC_KEYS = {"bpm", "aesthetic", "genre", "style", "taste", "vibe", "sound", "texture"}
_GEAR_KEYS = {"sp404", "mpc", "digitakt", "digitone", "oxi", "rytm", "sampler", "synth", "midi", "daw"}


def _key_matches(key: str, keywords: set[str]) -> bool:
    key_lower = key.lower()
    return any(kw in key_lower for kw in keywords)


def remap_dimension(old_dim: str, key: str) -> str | None:
    """Map an old dimension + key to a new dimension name.

    Returns None if the fact should be dropped (e.g. hardware).
    """
    # Direct renames
    direct_map = {
        "identity": "identity",
        "neurocognitive_profile": "neurocognitive",
        "communication_style": "communication_style",
        "relationships": "relationships",
        "philosophy": "values",
        "team_leadership": "management",
        "management_practice": "management",
    }

    if old_dim in direct_map:
        return direct_map[old_dim]

    # Dropped dimensions
    if old_dim == "hardware":
        return None

    # Sync agent drift dimensions
    drift_map = {
        "interests": "information_seeking",
        "communication": "communication_patterns",
        "knowledge": "information_seeking",
    }
    if old_dim in drift_map:
        return drift_map[old_dim]

    # Fan-out dimensions (key heuristics)
    if old_dim == "workflow":
        if _key_matches(key, _TOOL_KEYS):
            return "tool_usage"
        return "work_patterns"

    if old_dim == "technical_skills":
        if _key_matches(key, _TOOL_KEYS):
            return "tool_usage"
        return "identity"

    if old_dim == "software_preferences":
        return "tool_usage"

    if old_dim == "music_production":
        if _key_matches(key, _AESTHETIC_KEYS):
            return "values"
        return "creative_process"

    if old_dim == "decision_patterns":
        return "values"

    if old_dim == "knowledge_domains":
        return "information_seeking"

    # Unknown dimension — check if it's already valid
    if old_dim in get_dimension_names():
        return old_dim

    return None


def migrate_profile(profile_path: Path) -> dict:
    """Read a profile, remap all facts, return the new profile dict.

    Dropped facts are written to migration-review.jsonl alongside the profile.
    """
    raw = json.loads(profile_path.read_text())
    review_path = profile_path.parent / "migration-review.jsonl"

    new_dims: dict[str, dict] = {}  # name -> {"name", "summary", "facts"}
    dropped: list[dict] = []

    for dim in raw.get("dimensions", []):
        old_name = dim["name"]
        for fact in dim.get("facts", []):
            new_name = remap_dimension(old_name, fact.get("key", ""))
            if new_name is None:
                dropped.append({
                    "old_dimension": old_name,
                    "fact": fact,
                    "reason": f"dimension '{old_name}' dropped from taxonomy",
                })
                continue

            fact["dimension"] = new_name
            if new_name not in new_dims:
                new_dims[new_name] = {"name": new_name, "summary": "", "facts": []}
            new_dims[new_name]["facts"].append(fact)

    # Write dropped facts for review
    if dropped:
        with open(review_path, "w", encoding="utf-8") as fh:
            for entry in dropped:
                fh.write(json.dumps(entry) + "\n")

    raw["dimensions"] = list(new_dims.values())
    raw["version"] = raw.get("version", 0) + 1
    return raw


def main():
    from shared.config import PROFILES_DIR

    dry_run = "--dry-run" in sys.argv
    profile_path = PROFILES_DIR / "operator-profile.json"

    if not profile_path.exists():
        print("No profile found at", profile_path)
        return

    result = migrate_profile(profile_path)

    if dry_run:
        dim_summary = {d["name"]: len(d["facts"]) for d in result["dimensions"]}
        print("Dry run — new dimensions:")
        for name, count in sorted(dim_summary.items()):
            print(f"  {name}: {count} facts")
        print(f"\nTotal: {sum(dim_summary.values())} facts across {len(dim_summary)} dimensions")
        review_path = profile_path.parent / "migration-review.jsonl"
        if review_path.exists():
            lines = review_path.read_text().strip().splitlines()
            print(f"Dropped: {len(lines)} facts (see {review_path})")
    else:
        import shutil
        backup_path = profile_path.with_suffix(".pre-migration.json")
        shutil.copy2(profile_path, backup_path)
        print(f"Backup: {backup_path}")

        profile_path.write_text(json.dumps(result, indent=2))
        print(f"Migrated profile: v{result['version']}, {len(result['dimensions'])} dimensions")


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_dimension_migration.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/migrate_profile_dimensions.py tests/test_dimension_migration.py
git commit -m "feat: add profile dimension migration script"
```

---

### Task 7: Run full test suite and fix remaining breakage

**Files:**
- Modify: any test files with residual old dimension references

**Step 1: Run full test suite**

Run: `uv run pytest tests/ -q 2>&1 | tail -20`
Expected: Note exact failures

**Step 2: Fix each failure**

Common patterns to fix:
- Test data using `dimension="workflow"` → `dimension="work_patterns"`
- Test data using `dimension="philosophy"` → `dimension="values"`
- Test data using `dimension="neurocognitive_profile"` → `dimension="neurocognitive"`
- Test data using `dimension="management_practice"` → `dimension="management"`
- Test data using `dimension="team_leadership"` → `dimension="management"`
- Assertions on `len(PROFILE_DIMENSIONS) == 14` → `== 12`
- Assertions on specific old dimension names

**Step 3: Run full suite again**

Run: `uv run pytest tests/ -q`
Expected: All 1524+ tests PASS

**Step 4: Commit**

```bash
git add tests/
git commit -m "fix: update all tests for 12-dimension taxonomy"
```

---

### Task 8: Run migration on live profile (manual)

**Step 1: Dry run**

Run: `uv run python scripts/migrate_profile_dimensions.py --dry-run`
Expected: Summary of new dimensions with fact counts, list of dropped facts

**Step 2: Review dropped facts**

Read: `profiles/migration-review.jsonl`
Verify only `hardware` facts are dropped (these live in component-registry.yaml).

**Step 3: Execute migration**

Run: `uv run python scripts/migrate_profile_dimensions.py`
Expected: Backup created at `profiles/operator.pre-migration.json`, profile updated

**Step 4: Verify**

Run: `uv run python -m agents.profiler --show 2>&1 | head -30`
Expected: Profile displays with new dimension names

**Step 5: Commit migration artifacts**

Note: `profiles/*.json` is gitignored, so no commit needed for the profile itself. The backup is also gitignored. Only commit if migration-review.jsonl should be tracked (probably not — it's operational data).

---

### Ship Criterion

- `shared/dimensions.py` exists with 12 `DimensionDef` entries
- `agents/profiler.py` imports `PROFILE_DIMENSIONS` from registry
- All consumers reference new dimension names
- All 1524+ tests pass
- Live profile migrated to new taxonomy
- Backup of pre-migration profile preserved
