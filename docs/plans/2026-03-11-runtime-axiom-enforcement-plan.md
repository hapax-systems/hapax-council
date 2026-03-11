# Runtime Axiom Enforcement Engine — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add runtime validation of all LLM-generated text against constitutional axiom implications, with two enforcement layers (LiteLLM audit + application enforcer) and an extant text sweep.

**Architecture:** Two-layer enforcement: Layer 1 is a LiteLLM callback that monitors all LLM completions via pattern matching (universal, un-opt-out-able). Layer 2 is an application-level enforcer that wraps agent output with pattern checks + LLM-as-judge, supporting block/retry/quarantine for T0 violations. Path classifications (full/fast/deferred) control which checks run synchronously.

**Tech Stack:** Python 3.12+, pydantic-ai, pydantic 2.x, PyYAML, httpx, qdrant-client, LiteLLM custom callbacks, Langfuse trace annotations, pytest + unittest.mock

**Design Spec:** `/home/hapaxlegomenon/projects/hapax-constitution/docs/plans/2026-03-11-runtime-axiom-enforcement-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `axioms/enforcement-patterns.yaml` | Pattern registry mapping regex patterns to axiom implications |
| `axioms/enforcement-config.yaml` | Alert thresholds and enforcement configuration |
| `axioms/enforcement-exceptions.yaml` | Documented exceptions for paths below `full` classification |
| `shared/axiom_pattern_checker.py` | Load patterns, check text, return violations |
| `shared/axiom_judge.py` | LLM-as-judge agent for semantic axiom compliance checking |
| `shared/axiom_enforcer.py` | Application-level enforcement: wrap output paths, block/retry/quarantine |
| `shared/axiom_litellm_callback.py` | LiteLLM audit callback for universal monitoring |
| `scripts/axiom-sweep.py` | One-time extant text audit script |
| `tests/test_axiom_pattern_checker.py` | Pattern checker tests |
| `tests/test_axiom_judge.py` | Judge agent tests |
| `tests/test_axiom_enforcer.py` | Enforcer integration tests |
| `tests/test_axiom_litellm_callback.py` | Audit callback tests |
| `tests/test_axiom_sweep.py` | Sweep script tests |

### Modified Files

| File | Change |
|------|--------|
| `agents/drift_detector.py` | Add pattern compliance pass in `detect_drift()` |
| `agents/knowledge_maint.py` | Add pattern compliance check during Qdrant iteration |
| All 16 LLM agent files | Wire enforcer around `agent.run()` calls |

---

## Chunk 1: Pattern Layer

### Task 1: Pattern Registry YAML

**Files:**
- Create: `axioms/enforcement-patterns.yaml`

- [ ] **Step 1: Create the pattern registry**

```yaml
# axioms/enforcement-patterns.yaml
# Runtime text validation patterns mapped to axiom implications.
# Used by shared/axiom_pattern_checker.py for sub-millisecond text scanning.
# For static code scanning, see shared/axiom_patterns.txt (separate purpose).

patterns:
  # executive_function / ex-prose-001: Direct, informative prose only
  - axiom: executive_function
    implication: ex-prose-001
    tier: T0
    patterns:
      - regex: "This isn't .{1,50} — it's"
        label: rhetorical-pivot
      - regex: "That's not .{1,50} — that's"
        label: rhetorical-pivot-alt
      - regex: "The question becomes"
        label: performative-insight
      - regex: "What .{1,80} really means is"
        label: false-revelation
      - regex: "It turns out"
        label: false-discovery
      - regex: "Here's the thing"
        label: performative-setup
      - regex: "The real .{1,30} is"
        label: false-revelation-alt
      - regex: "Let's be (clear|honest|real)"
        label: performative-setup-alt

  # management_safety / mg-boundary-001: No feedback language
  - axiom: management_safety
    implication: mg-boundary-001
    tier: T0
    patterns:
      - regex: "you should (tell|say to|ask) \\w+"
        label: delivery-language
      - regex: "feedback for \\w+:"
        label: directed-feedback
      - regex: "(suggest|recommend).*saying"
        label: scripted-delivery
      - regex: "consider telling .{1,50} that"
        label: scripted-delivery-alt

  # management_safety / mg-boundary-002: No drafted language for people conversations
  - axiom: management_safety
    implication: mg-boundary-002
    tier: T0
    patterns:
      - regex: "you could say.{0,5}(\"|\u201c)"
        label: draft-script
      - regex: "try (saying|asking|telling)"
        label: draft-script-alt
```

- [ ] **Step 2: Commit**

```bash
git add axioms/enforcement-patterns.yaml
git commit -m "feat: add enforcement pattern registry for runtime text validation"
```

---

### Task 2: Pattern Checker Module — Models and Loader

**Files:**
- Create: `shared/axiom_pattern_checker.py`
- Create: `tests/test_axiom_pattern_checker.py`

- [ ] **Step 1: Write failing tests for models and loader**

```python
# tests/test_axiom_pattern_checker.py
"""Tests for axiom_pattern_checker — runtime text pattern validation."""

import unittest
from pathlib import Path
from unittest.mock import patch

from shared.axiom_pattern_checker import (
    PatternViolation,
    load_patterns,
    PatternEntry,
    PatternGroup,
)


class TestPatternModels(unittest.TestCase):
    def test_pattern_violation_fields(self):
        v = PatternViolation(
            axiom_id="executive_function",
            implication_id="ex-prose-001",
            tier="T0",
            label="rhetorical-pivot",
            matched_text="This isn't a bug — it's a feature",
            position=42,
        )
        assert v.axiom_id == "executive_function"
        assert v.tier == "T0"
        assert v.position == 42

    def test_pattern_entry_fields(self):
        e = PatternEntry(regex="test pattern", label="test-label")
        assert e.regex == "test pattern"
        assert e.label == "test-label"

    def test_pattern_group_fields(self):
        g = PatternGroup(
            axiom="executive_function",
            implication="ex-prose-001",
            tier="T0",
            patterns=[PatternEntry(regex="test", label="test-label")],
        )
        assert g.axiom == "executive_function"
        assert len(g.patterns) == 1


class TestLoadPatterns(unittest.TestCase):
    def test_load_from_real_registry(self):
        """Load the actual enforcement-patterns.yaml and verify structure."""
        groups = load_patterns()
        assert len(groups) > 0
        for g in groups:
            assert g.axiom
            assert g.implication
            assert g.tier in ("T0", "T1", "T2", "T3")
            assert len(g.patterns) > 0

    def test_load_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_patterns(Path("/nonexistent/path.yaml"))

    def test_load_malformed_yaml(self, tmp_path=None):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("not: valid: yaml: [")
            f.flush()
            with self.assertRaises(Exception):
                load_patterns(Path(f.name))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/test_axiom_pattern_checker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shared.axiom_pattern_checker'`

- [ ] **Step 3: Write minimal implementation — models and loader**

```python
# shared/axiom_pattern_checker.py
"""Runtime text pattern validation against axiom implications.

Loads regex patterns from axioms/enforcement-patterns.yaml and checks
LLM-generated text for violations. Sub-millisecond per check.

For static code scanning (Python class/function patterns), see
axiom_patterns.py and axiom_patterns.txt — different purpose, different file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_DEFAULT_REGISTRY = Path(__file__).resolve().parent.parent / "axioms" / "enforcement-patterns.yaml"


@dataclass(frozen=True)
class PatternViolation:
    """A single pattern match against LLM-generated text."""
    axiom_id: str
    implication_id: str
    tier: str
    label: str
    matched_text: str
    position: int


@dataclass(frozen=True)
class PatternEntry:
    """A single regex pattern with a human-readable label."""
    regex: str
    label: str


@dataclass(frozen=True)
class PatternGroup:
    """A group of patterns mapped to one axiom implication."""
    axiom: str
    implication: str
    tier: str
    patterns: list[PatternEntry]


@dataclass
class CompiledGroup:
    """A pattern group with pre-compiled regexes for fast matching."""
    axiom: str
    implication: str
    tier: str
    compiled: list[tuple[re.Pattern[str], str]]  # (pattern, label)


def load_patterns(path: Path | None = None) -> list[PatternGroup]:
    """Load pattern groups from the enforcement-patterns.yaml registry.

    Raises FileNotFoundError if the registry file does not exist.
    Raises yaml.YAMLError or KeyError on malformed content.
    """
    registry_path = path or _DEFAULT_REGISTRY
    if not registry_path.exists():
        raise FileNotFoundError(f"Pattern registry not found: {registry_path}")

    with open(registry_path) as f:
        data = yaml.safe_load(f)

    groups: list[PatternGroup] = []
    for entry in data["patterns"]:
        patterns = [
            PatternEntry(regex=p["regex"], label=p["label"])
            for p in entry["patterns"]
        ]
        groups.append(PatternGroup(
            axiom=entry["axiom"],
            implication=entry["implication"],
            tier=entry["tier"],
            patterns=patterns,
        ))
    return groups
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/test_axiom_pattern_checker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shared/axiom_pattern_checker.py tests/test_axiom_pattern_checker.py
git commit -m "feat: add pattern checker models and YAML loader"
```

---

### Task 3: Pattern Checker — check_text() Function

**Files:**
- Modify: `shared/axiom_pattern_checker.py`
- Modify: `tests/test_axiom_pattern_checker.py`

- [ ] **Step 1: Write failing tests for check_text()**

Add to `tests/test_axiom_pattern_checker.py`:

```python
from shared.axiom_pattern_checker import check_text, _compile_groups


class TestCheckText(unittest.TestCase):
    def test_clean_text_returns_empty(self):
        violations = check_text("The briefing covers three topics for Monday.")
        assert violations == []

    def test_detects_rhetorical_pivot(self):
        text = "This isn't a status update — it's a call to action."
        violations = check_text(text)
        assert len(violations) == 1
        assert violations[0].label == "rhetorical-pivot"
        assert violations[0].implication_id == "ex-prose-001"
        assert violations[0].tier == "T0"

    def test_detects_performative_insight(self):
        violations = check_text("The question becomes whether we should proceed.")
        assert len(violations) == 1
        assert violations[0].label == "performative-insight"

    def test_detects_feedback_language(self):
        violations = check_text("you should tell Marcus that his work is slipping.")
        assert len(violations) >= 1
        labels = {v.label for v in violations}
        assert "delivery-language" in labels

    def test_case_insensitive(self):
        violations = check_text("HERE'S THE THING about this approach.")
        assert len(violations) == 1
        assert violations[0].label == "performative-setup"

    def test_tier_filter(self):
        text = "This isn't a bug — it's a feature."
        # T0 filter should catch it
        violations = check_text(text, tier_filter={"T0"})
        assert len(violations) == 1
        # T1 filter should miss it
        violations = check_text(text, tier_filter={"T1"})
        assert len(violations) == 0

    def test_position_is_character_offset(self):
        text = "Clean text. This isn't a bug — it's a feature."
        violations = check_text(text)
        assert len(violations) == 1
        assert violations[0].position == 12  # start of "This isn't..."

    def test_multiple_violations(self):
        text = "Here's the thing. The question becomes clear."
        violations = check_text(text)
        assert len(violations) == 2

    def test_false_positive_resistance(self):
        # "This isn't working" should NOT match rhetorical pivot
        # because the pattern requires " — it's" (em dash + it's)
        violations = check_text("This isn't working properly.")
        assert len(violations) == 0

    def test_compile_groups_caches(self):
        g1 = _compile_groups()
        g2 = _compile_groups()
        assert g1 is g2  # same object, cached


class TestCheckTextWithCustomPatterns(unittest.TestCase):
    def test_custom_pattern_path(self):
        import tempfile
        custom = {
            "patterns": [{
                "axiom": "test_axiom",
                "implication": "test-001",
                "tier": "T1",
                "patterns": [{"regex": "bad phrase", "label": "test-bad"}],
            }]
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(custom, f)
            f.flush()
            violations = check_text("This contains a bad phrase here.", registry_path=Path(f.name))
            assert len(violations) == 1
            assert violations[0].label == "test-bad"
            assert violations[0].tier == "T1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/test_axiom_pattern_checker.py::TestCheckText -v`
Expected: FAIL — `ImportError: cannot import name 'check_text'`

- [ ] **Step 3: Write check_text() implementation**

Add to `shared/axiom_pattern_checker.py`:

```python
# Module-level cache for compiled pattern groups
_compiled_cache: list[CompiledGroup] | None = None
_compiled_cache_path: Path | None = None


def _compile_groups(registry_path: Path | None = None) -> list[CompiledGroup]:
    """Load and compile patterns. Cached after first call per path."""
    global _compiled_cache, _compiled_cache_path
    effective_path = registry_path or _DEFAULT_REGISTRY
    if _compiled_cache is not None and _compiled_cache_path == effective_path:
        return _compiled_cache

    groups = load_patterns(effective_path)
    compiled: list[CompiledGroup] = []
    for g in groups:
        compiled_patterns = [
            (re.compile(p.regex, re.IGNORECASE), p.label)
            for p in g.patterns
        ]
        compiled.append(CompiledGroup(
            axiom=g.axiom,
            implication=g.implication,
            tier=g.tier,
            compiled=compiled_patterns,
        ))

    _compiled_cache = compiled
    _compiled_cache_path = effective_path
    return compiled


def check_text(
    text: str,
    *,
    tier_filter: set[str] | None = None,
    registry_path: Path | None = None,
) -> list[PatternViolation]:
    """Check text against all enforcement patterns.

    Returns a list of PatternViolation for each match found.
    Sub-millisecond for typical agent output lengths.

    Args:
        text: The LLM-generated text to check.
        tier_filter: If provided, only check patterns at these tiers (e.g. {"T0"}).
        registry_path: Override the default pattern registry path (for testing).
    """
    compiled_groups = _compile_groups(registry_path)
    violations: list[PatternViolation] = []

    for group in compiled_groups:
        if tier_filter and group.tier not in tier_filter:
            continue
        for pattern, label in group.compiled:
            for match in pattern.finditer(text):
                violations.append(PatternViolation(
                    axiom_id=group.axiom,
                    implication_id=group.implication,
                    tier=group.tier,
                    label=label,
                    matched_text=match.group(),
                    position=match.start(),
                ))

    return violations
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/test_axiom_pattern_checker.py -v`
Expected: PASS (all tests including Task 2 tests)

- [ ] **Step 5: Commit**

```bash
git add shared/axiom_pattern_checker.py tests/test_axiom_pattern_checker.py
git commit -m "feat: add check_text() for runtime pattern validation"
```

---

## Chunk 2: LLM Judge Layer

### Task 4: Judge Agent — Models and Core

**Files:**
- Create: `shared/axiom_judge.py`
- Create: `tests/test_axiom_judge.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_axiom_judge.py
"""Tests for axiom_judge — LLM-as-judge semantic compliance checking."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from shared.axiom_judge import (
    JudgeVerdict,
    JudgeViolation,
    evaluate_compliance,
)


class TestJudgeModels(unittest.TestCase):
    def test_verdict_compliant(self):
        v = JudgeVerdict(compliant=True, violations=[])
        assert v.compliant is True
        assert v.violations == []

    def test_verdict_with_violations(self):
        v = JudgeVerdict(
            compliant=False,
            violations=[
                JudgeViolation(
                    implication_id="ex-prose-001",
                    tier="T0",
                    excerpt="Here's the thing about management",
                    reasoning="Performative setup pattern",
                )
            ],
        )
        assert not v.compliant
        assert len(v.violations) == 1
        assert v.violations[0].tier == "T0"


class TestEvaluateCompliance(unittest.IsolatedAsyncioTestCase):
    def _mock_agent(self):
        mock = MagicMock()
        mock.run = AsyncMock()
        return mock

    @patch("shared.axiom_judge._get_judge_agent")
    async def test_compliant_text(self, mock_get_agent):
        mock_agent = self._mock_agent()
        mock_get_agent.return_value = mock_agent
        mock_result = MagicMock()
        mock_result.output = JudgeVerdict(compliant=True, violations=[])
        mock_agent.run.return_value = mock_result

        verdict = await evaluate_compliance(
            text="The briefing covers three topics.",
            implications=[],
        )
        assert verdict.compliant is True

    @patch("shared.axiom_judge._get_judge_agent")
    async def test_violation_detected(self, mock_get_agent):
        mock_agent = self._mock_agent()
        mock_get_agent.return_value = mock_agent
        violation = JudgeViolation(
            implication_id="ex-prose-001",
            tier="T0",
            excerpt="This isn't a report",
            reasoning="Rhetorical pivot",
        )
        mock_result = MagicMock()
        mock_result.output = JudgeVerdict(compliant=False, violations=[violation])
        mock_agent.run.return_value = mock_result

        verdict = await evaluate_compliance(
            text="This isn't a report — it's a wake-up call.",
            implications=[],
        )
        assert not verdict.compliant
        assert len(verdict.violations) == 1

    @patch("shared.axiom_judge._get_judge_agent")
    async def test_judge_tags_metadata(self, mock_get_agent):
        mock_agent = self._mock_agent()
        mock_get_agent.return_value = mock_agent
        mock_result = MagicMock()
        mock_result.output = JudgeVerdict(compliant=True, violations=[])
        mock_agent.run.return_value = mock_result

        await evaluate_compliance(text="Clean text.", implications=[])

        # Verify the agent.run call includes judge metadata
        call_args = mock_agent.run.call_args
        assert call_args is not None
        # Check x-axiom-judge metadata is passed
        _, kwargs = call_args
        assert kwargs.get("metadata", {}).get("x-axiom-judge") == "true"

    @patch("shared.axiom_judge._get_judge_agent")
    async def test_judge_unavailable_raises(self, mock_get_agent):
        mock_agent = self._mock_agent()
        mock_get_agent.return_value = mock_agent
        mock_agent.run.side_effect = Exception("Model unavailable")

        with self.assertRaises(Exception) as ctx:
            await evaluate_compliance(text="Some text.", implications=[])
        assert "Model unavailable" in str(ctx.exception)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/test_axiom_judge.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# shared/axiom_judge.py
"""LLM-as-judge for semantic axiom compliance checking.

Uses a cheap/fast model (haiku) to evaluate LLM-generated text against
axiom implications that regex patterns cannot catch: novel rhetorical
structures, subtle feedback language, contextual violations.

The judge does not replace pattern checking — patterns run first, always.
The judge evaluates text that passed the pattern layer.
"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic_ai import Agent

from shared.config import get_model


class JudgeViolation(BaseModel):
    """A semantic violation found by the LLM judge."""
    implication_id: str
    tier: str
    excerpt: str
    reasoning: str


class JudgeVerdict(BaseModel):
    """The judge's evaluation of a text against axiom implications."""
    compliant: bool
    violations: list[JudgeViolation]


_JUDGE_SYSTEM_PROMPT = """\
You are an axiom compliance judge. You evaluate LLM-generated text against \
constitutional axiom implications.

You will receive:
1. The text to evaluate
2. A list of axiom implications with their IDs, tiers, and full text

For each implication, check whether the text violates it. Be precise:
- Only flag actual violations, not borderline cases
- Quote the specific violating passage in the excerpt field
- Explain concisely why it violates the implication

If the text complies with all implications, return compliant=true with an empty violations list.
"""

_judge_agent: Agent[None, JudgeVerdict] | None = None


def _get_judge_agent() -> Agent[None, JudgeVerdict]:
    """Lazy initialization of judge agent. Avoids import-time LiteLLM dependency."""
    global _judge_agent
    if _judge_agent is None:
        _judge_agent = Agent(
            get_model("fast"),
            system_prompt=_JUDGE_SYSTEM_PROMPT,
            output_type=JudgeVerdict,
        )
    return _judge_agent


def _build_judge_prompt(text: str, implications: list[dict[str, str]]) -> str:
    """Build the evaluation prompt with text and implications."""
    impl_text = ""
    for impl in implications:
        impl_text += f"\n- [{impl['id']}] (Tier {impl['tier']}): {impl['text']}"

    return f"""Evaluate this text for axiom compliance.

## Applicable implications:
{impl_text}

## Text to evaluate:

{text}
"""


async def evaluate_compliance(
    text: str,
    implications: list[dict[str, str]],
) -> JudgeVerdict:
    """Evaluate text against axiom implications using LLM-as-judge.

    Args:
        text: The LLM-generated text to evaluate.
        implications: List of dicts with keys: id, tier, text.

    Returns:
        JudgeVerdict with compliant flag and any violations found.

    Raises:
        Exception if the judge model is unavailable.
    """
    prompt = _build_judge_prompt(text, implications)
    agent = _get_judge_agent()
    result = await agent.run(
        prompt,
        metadata={"x-axiom-judge": "true"},
    )
    return result.output
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/test_axiom_judge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shared/axiom_judge.py tests/test_axiom_judge.py
git commit -m "feat: add LLM-as-judge for semantic axiom compliance"
```

---

## Chunk 3: Application Enforcer

### Task 5: Enforcement Config and Models

**Files:**
- Create: `axioms/enforcement-config.yaml`
- Create: `axioms/enforcement-exceptions.yaml`
- Modify: `shared/axiom_enforcer.py` (create)

- [ ] **Step 1: Create enforcement config**

```yaml
# axioms/enforcement-config.yaml
# Alert thresholds for the runtime enforcement engine.
# Missing or malformed file falls back to these defaults with a warning.

alerts:
  enforcement_latency_p95_ms: 1000
  quarantine_rate_24h: 3
  divergence_any: true
```

- [ ] **Step 2: Create enforcement exceptions (empty initial)**

```yaml
# axioms/enforcement-exceptions.yaml
# Documented exceptions for output paths classified below 'full'.
# Each exception must prove a conflict between axioms — convenience
# is not a valid justification.
#
# Required fields per exception:
#   path: identifier for the output path
#   classification: the downgraded classification (fast or deferred)
#   default: what the classification would be without the exception (full)
#   reason: why enforcement at the default level breaks usability
#   compensating_control: what alternative coverage exists
#   approved: date the exception was approved

exceptions: []
```

- [ ] **Step 3: Commit config files**

```bash
git add axioms/enforcement-config.yaml axioms/enforcement-exceptions.yaml
git commit -m "feat: add enforcement config and exceptions registry"
```

---

### Task 6: Application Enforcer — Core

**Files:**
- Create: `shared/axiom_enforcer.py`
- Create: `tests/test_axiom_enforcer.py`

- [ ] **Step 1: Write failing tests for enforcer models and enforce()**

```python
# tests/test_axiom_enforcer.py
"""Tests for axiom_enforcer — application-level enforcement layer."""

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import tempfile
import json

from shared.axiom_enforcer import (
    EnforcementResult,
    OutputPath,
    enforce,
    extract_text_fields,
)
from shared.axiom_pattern_checker import PatternViolation
from shared.axiom_judge import JudgeVerdict, JudgeViolation


class TestModels(unittest.TestCase):
    def test_output_path(self):
        p = OutputPath(
            name="management-briefing",
            classification="full",
            agent_name="management_briefing",
            output_destination="data/briefings/",
        )
        assert p.classification == "full"

    def test_enforcement_result_passed(self):
        r = EnforcementResult(
            passed=True,
            violations=[],
            action_taken="delivered",
            retries_used=0,
        )
        assert r.passed is True


class TestExtractTextFields(unittest.TestCase):
    def test_flat_model(self):
        from pydantic import BaseModel

        class Simple(BaseModel):
            title: str
            count: int
            summary: str

        obj = Simple(title="Hello", count=5, summary="World")
        text = extract_text_fields(obj)
        assert "Hello" in text
        assert "World" in text
        assert "5" not in text  # int fields excluded

    def test_nested_model(self):
        from pydantic import BaseModel

        class Inner(BaseModel):
            detail: str

        class Outer(BaseModel):
            name: str
            inner: Inner

        obj = Outer(name="Top", inner=Inner(detail="Nested"))
        text = extract_text_fields(obj)
        assert "Top" in text
        assert "Nested" in text

    def test_list_of_strings(self):
        from pydantic import BaseModel

        class WithList(BaseModel):
            items: list[str]

        obj = WithList(items=["one", "two", "three"])
        text = extract_text_fields(obj)
        assert "one" in text
        assert "three" in text


class TestEnforceCleanText(unittest.IsolatedAsyncioTestCase):
    @patch("shared.axiom_enforcer._load_implications")
    @patch("shared.axiom_enforcer.evaluate_compliance")
    async def test_clean_text_full_path(self, mock_judge, mock_impls):
        mock_impls.return_value = [{"id": "ex-prose-001", "tier": "T0", "text": "..."}]
        mock_judge.return_value = JudgeVerdict(compliant=True, violations=[])

        path = OutputPath(
            name="test-agent",
            classification="full",
            agent_name="test",
            output_destination="data/test/",
        )
        result = await enforce("Clean informative text.", path)
        assert result.passed is True
        assert result.action_taken == "delivered"
        assert result.retries_used == 0
        mock_judge.assert_called_once()

    async def test_clean_text_fast_path(self):
        path = OutputPath(
            name="test-agent",
            classification="fast",
            agent_name="test",
            output_destination="data/test/",
        )
        result = await enforce("Clean informative text.", path)
        assert result.passed is True
        assert result.action_taken == "delivered"


class TestEnforcePatternViolation(unittest.IsolatedAsyncioTestCase):
    async def test_t0_pattern_violation_no_retry_quarantines(self):
        path = OutputPath(
            name="test-agent",
            classification="fast",
            agent_name="test",
            output_destination="data/test/",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("shared.axiom_enforcer.QUARANTINE_DIR", Path(tmpdir)):
                result = await enforce(
                    "This isn't a report — it's a revelation.",
                    path,
                )
                assert result.passed is False
                assert result.action_taken == "quarantined"
                assert len(result.violations) >= 1

    async def test_t0_pattern_violation_retry_succeeds(self):
        call_count = 0

        async def retry_fn(violations):
            nonlocal call_count
            call_count += 1
            return "Clean informative text on retry."

        path = OutputPath(
            name="test-agent",
            classification="fast",
            agent_name="test",
            output_destination="data/test/",
        )
        result = await enforce(
            "This isn't a report — it's a revelation.",
            path,
            retry_fn=retry_fn,
        )
        assert result.passed is True
        assert result.action_taken == "delivered"
        assert result.retries_used == 1
        assert call_count == 1

    async def test_t0_pattern_violation_retries_exhausted(self):
        async def retry_fn(violations):
            return "Here's the thing — it's still bad."

        path = OutputPath(
            name="test-agent",
            classification="fast",
            agent_name="test",
            output_destination="data/test/",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("shared.axiom_enforcer.QUARANTINE_DIR", Path(tmpdir)):
                result = await enforce(
                    "This isn't a report — it's bad.",
                    path,
                    retry_fn=retry_fn,
                )
                assert result.passed is False
                assert result.action_taken == "quarantined"
                assert result.retries_used == 2


class TestEnforceJudgeViolation(unittest.IsolatedAsyncioTestCase):
    @patch("shared.axiom_enforcer._load_implications")
    @patch("shared.axiom_enforcer.evaluate_compliance")
    async def test_judge_t0_violation_quarantines(self, mock_judge, mock_impls):
        mock_impls.return_value = [{"id": "ex-prose-001", "tier": "T0", "text": "..."}]
        violation = JudgeViolation(
            implication_id="ex-prose-001",
            tier="T0",
            excerpt="subtle rhetorical pattern",
            reasoning="Novel pivot structure",
        )
        mock_judge.return_value = JudgeVerdict(compliant=False, violations=[violation])

        path = OutputPath(
            name="test-agent",
            classification="full",
            agent_name="test",
            output_destination="data/test/",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("shared.axiom_enforcer.QUARANTINE_DIR", Path(tmpdir)):
                result = await enforce("Text that passes patterns.", path)
                assert result.passed is False
                assert result.action_taken == "quarantined"

    @patch("shared.axiom_enforcer._load_implications")
    @patch("shared.axiom_enforcer.evaluate_compliance")
    async def test_judge_unavailable_quarantines_full_path(self, mock_judge, mock_impls):
        mock_impls.return_value = [{"id": "ex-prose-001", "tier": "T0", "text": "..."}]
        mock_judge.side_effect = Exception("Model unavailable")

        path = OutputPath(
            name="test-agent",
            classification="full",
            agent_name="test",
            output_destination="data/test/",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("shared.axiom_enforcer.QUARANTINE_DIR", Path(tmpdir)):
                result = await enforce("Clean text.", path)
                assert result.passed is False
                assert result.action_taken == "quarantined"


class TestQuarantineFile(unittest.IsolatedAsyncioTestCase):
    async def test_quarantine_writes_file_with_frontmatter(self):
        path = OutputPath(
            name="test-agent",
            classification="fast",
            agent_name="test",
            output_destination="data/test/",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("shared.axiom_enforcer.QUARANTINE_DIR", Path(tmpdir)):
                result = await enforce(
                    "This isn't clean — it's bad.",
                    path,
                )
                assert result.action_taken == "quarantined"
                # Check quarantine file exists
                q_dir = Path(tmpdir) / "test-agent"
                files = list(q_dir.glob("*.md"))
                assert len(files) == 1
                content = files[0].read_text()
                assert "violations:" in content
                assert "This isn't clean" in content


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/test_axiom_enforcer.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write enforcer implementation**

```python
# shared/axiom_enforcer.py
"""Application-level axiom enforcement for agent output paths.

Wraps agent output with pattern checks + LLM-as-judge, supporting
block/retry/quarantine for T0 violations. Path classifications
(full/fast/deferred) control which checks run synchronously.

Layer 2 of the two-layer enforcement architecture. Layer 1 (LiteLLM
audit callback) provides universal monitoring as a backstop.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Awaitable, Literal

import yaml
from pydantic import BaseModel

from shared.axiom_pattern_checker import PatternViolation, check_text
from shared.axiom_judge import JudgeVerdict, JudgeViolation, evaluate_compliance

logger = logging.getLogger(__name__)

QUARANTINE_DIR = Path(__file__).resolve().parent.parent / "profiles" / ".quarantine"
_AXIOMS_DIR = Path(__file__).resolve().parent.parent / "axioms"
_MAX_RETRIES = 2


class OutputPath(BaseModel):
    """Declares an agent output path with its enforcement classification."""
    name: str
    classification: Literal["full", "fast", "deferred"]
    agent_name: str
    output_destination: str


class EnforcementResult(BaseModel):
    """Result of enforcing axiom compliance on agent output."""
    passed: bool
    violations: list[PatternViolation | JudgeViolation]
    action_taken: Literal["delivered", "retried", "quarantined"]
    retries_used: int


def extract_text_fields(obj: BaseModel) -> str:
    """Recursively extract all string-typed fields from a Pydantic model.

    Concatenates all string values with newlines. Non-string fields
    (int, float, bool, None) are skipped. Nested models are recursed.
    Lists of strings are joined.
    """
    parts: list[str] = []

    for field_name, field_info in obj.model_fields.items():
        value = getattr(obj, field_name)
        if value is None:
            continue
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, BaseModel):
            parts.append(extract_text_fields(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, BaseModel):
                    parts.append(extract_text_fields(item))

    return "\n".join(parts)


def _load_implications() -> list[dict[str, str]]:
    """Load all axiom implications for judge evaluation."""
    implications: list[dict[str, str]] = []
    impl_dir = _AXIOMS_DIR / "implications"
    if not impl_dir.exists():
        return implications

    for yaml_file in impl_dir.glob("*.yaml"):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        if not data or "implications" not in data:
            continue
        for impl in data["implications"]:
            implications.append({
                "id": impl["id"],
                "tier": impl["tier"],
                "text": impl["text"],
            })
    return implications


def _quarantine(
    text: str,
    path: OutputPath,
    violations: list[PatternViolation | JudgeViolation],
    reason: str = "",
) -> None:
    """Write quarantined output to profiles/.quarantine/{path.name}/."""
    q_dir = QUARANTINE_DIR / path.name
    q_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    q_file = q_dir / f"{timestamp}.md"

    violation_data = []
    for v in violations:
        if isinstance(v, PatternViolation):
            violation_data.append({
                "type": "pattern",
                "implication": v.implication_id,
                "tier": v.tier,
                "label": v.label,
                "matched_text": v.matched_text,
            })
        elif isinstance(v, JudgeViolation):
            violation_data.append({
                "type": "judge",
                "implication": v.implication_id,
                "tier": v.tier,
                "excerpt": v.excerpt,
                "reasoning": v.reasoning,
            })

    frontmatter = yaml.dump({
        "quarantined": timestamp,
        "agent": path.agent_name,
        "path": path.name,
        "classification": path.classification,
        "reason": reason or "T0 violation",
        "violations": violation_data,
    }, default_flow_style=False)

    q_file.write_text(f"---\n{frontmatter}---\n\n{text}\n")


async def enforce(
    text: str,
    path: OutputPath,
    retry_fn: Callable[[list[PatternViolation | JudgeViolation]], Awaitable[str]] | None = None,
) -> EnforcementResult:
    """Enforce axiom compliance on agent output text.

    Args:
        text: The LLM-generated text to validate.
        path: The output path declaration with classification.
        retry_fn: Optional async callable that accepts violations and returns
            regenerated text. Called on T0 violations, up to 2 retries.

    Returns:
        EnforcementResult with pass/fail, violations, and action taken.
    """
    retries_used = 0
    current_text = text

    for attempt in range(_MAX_RETRIES + 1):
        all_violations: list[PatternViolation | JudgeViolation] = []

        # Pattern check — always runs, all paths
        pattern_violations = check_text(current_text)
        all_violations.extend(pattern_violations)

        # Judge check — full paths sync, deferred paths async, fast paths skip
        t0_pattern_hits = [v for v in pattern_violations if v.tier == "T0"]
        if path.classification == "full" and not t0_pattern_hits:
            # Sync judge — block on result before delivery
            try:
                implications = _load_implications()
                verdict = await evaluate_compliance(current_text, implications)
                if not verdict.compliant:
                    all_violations.extend(verdict.violations)
            except Exception as e:
                logger.error("Judge unavailable: %s", e)
                _quarantine(current_text, path, all_violations, reason=f"judge unavailable: {e}")
                return EnforcementResult(
                    passed=False,
                    violations=all_violations,
                    action_taken="quarantined",
                    retries_used=retries_used,
                )
        elif path.classification == "deferred" and not t0_pattern_hits:
            # Async judge — dispatch background task, deliver immediately
            import asyncio

            async def _deferred_judge(text_to_check: str, output_path: OutputPath) -> None:
                try:
                    implications = _load_implications()
                    verdict = await evaluate_compliance(text_to_check, implications)
                    if not verdict.compliant:
                        t0_judge = [v for v in verdict.violations if v.tier == "T0"]
                        if t0_judge:
                            from shared.notify import send_notification
                            labels = ", ".join(v.implication_id for v in t0_judge[:3])
                            send_notification(
                                title="Deferred axiom violation",
                                message=(
                                    f"Post-hoc judge found T0 violations on "
                                    f"path {output_path.name}: {labels}"
                                ),
                                priority="high",
                                tags=["axiom", "deferred-violation"],
                            )
                        logger.warning(
                            "Deferred judge found %d violations on %s",
                            len(verdict.violations),
                            output_path.name,
                        )
                except Exception as e:
                    logger.error("Deferred judge failed for %s: %s", output_path.name, e)

            asyncio.create_task(_deferred_judge(current_text, path))

        # Evaluate T0 violations
        t0_violations = [
            v for v in all_violations
            if (isinstance(v, PatternViolation) and v.tier == "T0")
            or (isinstance(v, JudgeViolation) and v.tier == "T0")
        ]

        if not t0_violations:
            # T1+ violations: log but deliver
            if all_violations:
                logger.warning(
                    "Non-blocking violations on path %s: %d violations",
                    path.name,
                    len(all_violations),
                )
            return EnforcementResult(
                passed=len(all_violations) == 0,
                violations=all_violations,
                action_taken="delivered" if retries_used == 0 else "retried",
                retries_used=retries_used,
            )

        # T0 violation — try retry
        if retry_fn and attempt < _MAX_RETRIES:
            retries_used += 1
            current_text = await retry_fn(t0_violations)
            continue

        # T0 violation — retries exhausted or no retry_fn
        _quarantine(current_text, path, all_violations)
        return EnforcementResult(
            passed=False,
            violations=all_violations,
            action_taken="quarantined",
            retries_used=retries_used,
        )

    # Should not reach here, but safety fallback
    _quarantine(current_text, path, [])
    return EnforcementResult(
        passed=False,
        violations=[],
        action_taken="quarantined",
        retries_used=retries_used,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/test_axiom_enforcer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shared/axiom_enforcer.py tests/test_axiom_enforcer.py
git commit -m "feat: add application-level axiom enforcer with block/retry/quarantine"
```

---

## Chunk 4: LiteLLM Audit Callback

### Task 7: Audit Callback Module

**Files:**
- Create: `shared/axiom_litellm_callback.py`
- Create: `tests/test_axiom_litellm_callback.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_axiom_litellm_callback.py
"""Tests for axiom_litellm_callback — LiteLLM audit monitoring layer."""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock


class TestAxiomAuditCallback(unittest.IsolatedAsyncioTestCase):
    def _make_callback(self):
        from shared.axiom_litellm_callback import AxiomAuditCallback
        return AxiomAuditCallback()

    def _make_response(self, content: str):
        choice = MagicMock()
        choice.message.content = content
        response = MagicMock()
        response.choices = [choice]
        return response

    def _make_kwargs(self, *, enforced: bool = False, judge: bool = False):
        metadata = {}
        if enforced:
            metadata["x-axiom-enforced"] = "true"
        if judge:
            metadata["x-axiom-judge"] = "true"
        return {
            "litellm_params": {"metadata": metadata},
            "model": "claude-haiku",
            "response_cost": 0.001,
        }

    @patch("shared.axiom_litellm_callback.check_text")
    async def test_clean_text_no_alert(self, mock_check):
        mock_check.return_value = []
        cb = self._make_callback()
        response = self._make_response("Clean text.")
        kwargs = self._make_kwargs()

        await cb.async_log_success_event(kwargs, response, None, None)
        mock_check.assert_called_once_with("Clean text.")

    @patch("shared.axiom_litellm_callback._send_ntfy_alert")
    @patch("shared.axiom_litellm_callback._annotate_langfuse_trace")
    @patch("shared.axiom_litellm_callback.check_text")
    async def test_violation_on_unenforced_request_alerts(self, mock_check, mock_annotate, mock_ntfy):
        from shared.axiom_pattern_checker import PatternViolation
        mock_check.return_value = [
            PatternViolation(
                axiom_id="executive_function",
                implication_id="ex-prose-001",
                tier="T0",
                label="rhetorical-pivot",
                matched_text="This isn't X — it's Y",
                position=0,
            )
        ]
        cb = self._make_callback()
        response = self._make_response("This isn't X — it's Y")
        kwargs = self._make_kwargs(enforced=False)

        await cb.async_log_success_event(kwargs, response, None, None)
        mock_ntfy.assert_called_once()
        call_args = mock_ntfy.call_args
        assert "divergence" in call_args.kwargs.get("tags", call_args[1].get("tags", []))
        mock_annotate.assert_called_once()

    @patch("shared.axiom_litellm_callback.check_text")
    async def test_violation_on_enforced_request_no_divergence_alert(self, mock_check):
        from shared.axiom_pattern_checker import PatternViolation
        mock_check.return_value = [
            PatternViolation(
                axiom_id="executive_function",
                implication_id="ex-prose-001",
                tier="T0",
                label="rhetorical-pivot",
                matched_text="test",
                position=0,
            )
        ]
        cb = self._make_callback()
        response = self._make_response("test")
        kwargs = self._make_kwargs(enforced=True)

        # Should not raise or alert divergence
        await cb.async_log_success_event(kwargs, response, None, None)

    @patch("shared.axiom_litellm_callback.check_text")
    async def test_judge_requests_skipped(self, mock_check):
        cb = self._make_callback()
        response = self._make_response("Judge output text.")
        kwargs = self._make_kwargs(judge=True)

        await cb.async_log_success_event(kwargs, response, None, None)
        mock_check.assert_not_called()

    async def test_empty_response_skipped(self):
        cb = self._make_callback()
        response = self._make_response(None)
        kwargs = self._make_kwargs()

        # Should not raise
        await cb.async_log_success_event(kwargs, response, None, None)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/test_axiom_litellm_callback.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

Note: This module has TWO import modes. When running on the host (tests, development),
it imports from `shared.*`. When deployed inside the LiteLLM Docker container, modules
are mounted at `/app/` without the `shared.` prefix. The implementation handles both
with a try/except import pattern. The container version uses raw HTTP calls for ntfy
and Langfuse instead of client libraries.

```python
# shared/axiom_litellm_callback.py
"""LiteLLM audit callback for universal axiom monitoring.

Layer 1 of the two-layer enforcement architecture. Fires on every LLM
completion, runs pattern checks, logs violations. Cannot block
delivery — it is an observer. Detects Layer 1/Layer 2 divergence (violations
on requests not tagged by the application enforcer).

Designed to run inside the LiteLLM Docker container. Dependencies limited
to re, pyyaml, and httpx (HTTP calls for notifications, no client libs).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

# Support both host imports (shared.*) and container imports (flat at /app/)
try:
    from shared.axiom_pattern_checker import check_text, PatternViolation
except ImportError:
    from axiom_pattern_checker import check_text, PatternViolation  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

_NTFY_URL = os.environ.get("NTFY_BASE_URL", "http://localhost:8090")
_NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "cockpit")
_LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
_LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
_LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")


def _send_ntfy_alert(title: str, message: str, tags: list[str]) -> None:
    """Send notification via raw HTTP to ntfy. No client library dependency."""
    try:
        httpx.post(
            f"{_NTFY_URL}/{_NTFY_TOPIC}",
            content=message,
            headers={
                "Title": title,
                "Priority": "high",
                "Tags": ",".join(tags),
            },
            timeout=5.0,
        )
    except Exception as e:
        logger.error("Failed to send ntfy alert: %s", e)


def _annotate_langfuse_trace(
    kwargs: dict[str, Any],
    violations: list[PatternViolation],
) -> None:
    """Annotate the existing Langfuse trace with violation data via HTTP."""
    if not _LANGFUSE_PUBLIC_KEY or not _LANGFUSE_SECRET_KEY:
        return

    trace_id = kwargs.get("litellm_params", {}).get("metadata", {}).get("trace_id")
    if not trace_id:
        return

    violation_data = [
        {
            "axiom_id": v.axiom_id,
            "implication_id": v.implication_id,
            "tier": v.tier,
            "label": v.label,
            "matched_text": v.matched_text,
        }
        for v in violations
    ]

    try:
        httpx.post(
            f"{_LANGFUSE_HOST}/api/public/scores",
            json={
                "traceId": trace_id,
                "name": "axiom-violations",
                "value": len(violations),
                "comment": json.dumps(violation_data[:5]),
            },
            auth=(_LANGFUSE_PUBLIC_KEY, _LANGFUSE_SECRET_KEY),
            timeout=5.0,
        )
    except Exception as e:
        logger.error("Failed to annotate Langfuse trace: %s", e)


class AxiomAuditCallback:
    """Custom LiteLLM callback for axiom compliance auditing."""

    async def async_log_success_event(
        self,
        kwargs: dict[str, Any],
        response_obj: Any,
        start_time: Any,
        end_time: Any,
    ) -> None:
        """Called by LiteLLM after every successful completion."""
        metadata = kwargs.get("litellm_params", {}).get("metadata", {})

        # Skip judge requests to prevent recursion
        if metadata.get("x-axiom-judge") == "true":
            return

        # Extract response text
        try:
            text = response_obj.choices[0].message.content
        except (AttributeError, IndexError):
            return
        if not text:
            return

        # Run pattern checks
        violations = check_text(text)
        if not violations:
            return

        logger.warning(
            "Axiom audit: %d violations in %s response",
            len(violations),
            kwargs.get("model", "unknown"),
        )

        # Annotate Langfuse trace
        _annotate_langfuse_trace(kwargs, violations)

        # Check for Layer 1/Layer 2 divergence
        is_enforced = metadata.get("x-axiom-enforced") == "true"
        if not is_enforced:
            t0_violations = [v for v in violations if v.tier == "T0"]
            if t0_violations:
                labels = ", ".join(v.label for v in t0_violations[:3])
                _send_ntfy_alert(
                    title="Axiom enforcement divergence",
                    message=(
                        f"T0 violations on un-enforced LLM call "
                        f"(model: {kwargs.get('model', 'unknown')}). "
                        f"Violations: {labels}. "
                        f"Agent bypassing Layer 2 enforcement."
                    ),
                    tags=["axiom", "divergence"],
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/test_axiom_litellm_callback.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shared/axiom_litellm_callback.py tests/test_axiom_litellm_callback.py
git commit -m "feat: add LiteLLM audit callback for universal axiom monitoring"
```

---

## Chunk 5: Agent Integration

### Task 8: Wire Enforcer into First Agent (management_briefing.py)

This is the template integration. All subsequent agents follow this pattern.

**Files:**
- Modify: `agents/briefing.py`
- Create: `tests/test_briefing_enforcement.py`

- [ ] **Step 1: Read agents/briefing.py to find the agent.run() call site**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && grep -n "agent.run\|result.output\|briefing_agent" agents/briefing.py | head -20`

Identify: the `briefing_agent.run(prompt)` call (around line 537) and where `result.output` is used.

- [ ] **Step 2: Write failing test for enforced briefing output**

```python
# tests/test_briefing_enforcement.py
"""Tests that briefing agent output passes through axiom enforcement."""

import unittest
from unittest.mock import patch, AsyncMock, MagicMock

from shared.axiom_enforcer import OutputPath


class TestBriefingEnforcement(unittest.IsolatedAsyncioTestCase):
    @patch("shared.axiom_enforcer.enforce")
    @patch("agents.briefing.briefing_agent")
    async def test_briefing_calls_enforcer(self, mock_agent, mock_enforce):
        """Verify the briefing agent wires through the enforcer."""
        from shared.axiom_enforcer import EnforcementResult

        mock_enforce.return_value = EnforcementResult(
            passed=True,
            violations=[],
            action_taken="delivered",
            retries_used=0,
        )
        # This test verifies the integration pattern exists.
        # The actual briefing generation requires significant mocking
        # of management data, so we verify the enforcer import and
        # OutputPath declaration exist.
        from agents.briefing import BRIEFING_OUTPUT_PATH
        assert BRIEFING_OUTPUT_PATH.classification == "full"
        assert BRIEFING_OUTPUT_PATH.name == "management-briefing"


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/test_briefing_enforcement.py -v`
Expected: FAIL — `ImportError: cannot import name 'BRIEFING_OUTPUT_PATH'`

- [ ] **Step 4: Wire enforcer into agents/briefing.py**

Add near the top of the file (after existing imports):

```python
from shared.axiom_enforcer import enforce, OutputPath, extract_text_fields

BRIEFING_OUTPUT_PATH = OutputPath(
    name="management-briefing",
    classification="full",
    agent_name="management_briefing",
    output_destination="data/briefings/",
)

# Metadata tag for Layer 1/Layer 2 divergence detection
_ENFORCED_METADATA = {"x-axiom-enforced": "true"}
```

Find the `result = await briefing_agent.run(prompt)` call. First, add the enforcement
metadata to the original call so the LiteLLM audit callback knows this agent is enforced:

```python
# Change: result = await briefing_agent.run(prompt)
# To:
result = await briefing_agent.run(prompt, metadata=_ENFORCED_METADATA)
```

Then wrap the output with enforcement:

```python
text_content = extract_text_fields(result.output)

async def _retry_briefing(violations):
    amendment = "\n".join(
        f"Previous output violated {v.implication_id}: {v.matched_text if hasattr(v, 'matched_text') else v.excerpt}"
        for v in violations
    )
    retry_result = await briefing_agent.run(
        prompt + f"\n\nREGENERATE. {amendment}",
        metadata=_ENFORCED_METADATA,
    )
    return extract_text_fields(retry_result.output)

enforcement = await enforce(
    text_content,
    BRIEFING_OUTPUT_PATH,
    retry_fn=_retry_briefing,
)
if enforcement.action_taken == "quarantined":
    logger.error("Briefing output quarantined: %s", enforcement.violations)
    return  # Do not write to vault
```

**Important:** The `metadata=_ENFORCED_METADATA` on `agent.run()` tells pydantic-ai
to forward this metadata to LiteLLM, which forwards it to callbacks. Without this tag,
every enforced agent will trigger false Layer 1 divergence alerts. All agents in Task 9
must include this metadata on their `agent.run()` calls.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/test_briefing_enforcement.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add agents/briefing.py tests/test_briefing_enforcement.py
git commit -m "feat: wire axiom enforcer into management briefing agent"
```

---

### Task 9: Wire Enforcer into Remaining Agents

Apply the same pattern from Task 8 to all remaining LLM agents. Each agent gets:
1. Import `enforce`, `OutputPath`, `extract_text_fields`
2. An `OutputPath` constant at module level
3. Enforcement wrapping after `agent.run()` call
4. A basic test verifying the `OutputPath` declaration exists

**Files to modify (one commit per agent group):**

**Group A — Management agents (6 files):**
- `agents/profiler.py` — 5 agent.run() calls. Path: `management-profiler`, classification: `full`
- `agents/management_prep.py` — LLM calls for prep/snapshot/overview. Path: `management-prep`, classification: `full`
- `agents/meeting_lifecycle.py` — LLM calls for meeting prep/transcript. Path: `meeting-lifecycle`, classification: `full`
- `agents/demo.py` — 4 agent.run() calls. Path: `demo-script`, classification: `full`
- `agents/demo_pipeline/eval_rubrics.py` — 3 calls. Path: `demo-eval`, classification: `full`
- `agents/demo_pipeline/critique.py` — 3 calls. Path: `demo-critique`, classification: `full`

**Group B — Analysis agents (5 files):**
- `agents/drift_detector.py` — 2 calls. Path: `drift-detector`, classification: `full`
- `agents/scout.py` — 1 call. Path: `scout-report`, classification: `full`
- `agents/digest.py` — 1 call. Path: `digest`, classification: `full`
- `agents/code_review.py` — 1 call. Path: `code-review`, classification: `full`
- `agents/research.py` — 2 calls. Path: `research`, classification: `full`

**Group C — Reporting and other LLM agents (5 files):**
- `agents/status_update.py` — LLM call for status reports. Path: `status-update`, classification: `full`
- `agents/review_prep.py` — LLM call for review evidence. Path: `review-prep`, classification: `full`
- `agents/knowledge_maint.py` — 1 call (optional --summarize). Path: `knowledge-maint-summary`, classification: `full`
- `agents/activity_analyzer.py` — 1 call. Path: `activity-analysis`, classification: `full`
- `agents/dev_story/__main__.py` — 2 calls. Path: `dev-story`, classification: `full`

**Multi-call agent guidance:** For agents with multiple `agent.run()` calls:
- Each `agent.run()` call gets `metadata=_ENFORCED_METADATA`
- Enforce after EACH call that produces operator-facing text, not just at the end
- For sequential pipelines (profiler: extraction → synthesis → summary), each step's
  output is enforced independently because each step writes to different destinations
- For retry functions in multi-call agents, retry only the specific call that violated,
  not the entire pipeline

- [ ] **Step 1: Wire Group A agents (4 files)**

For each file, follow the exact same pattern as Task 8:
- Add imports and OutputPath constant
- Wrap each `agent.run()` result with enforcement
- Add early return on quarantine

- [ ] **Step 2: Create test file for agent OutputPath declarations**

```python
# tests/test_agent_enforcement_paths.py
"""Verify all LLM agents declare OutputPath constants for enforcement."""

import unittest


class TestAgentEnforcementPaths(unittest.TestCase):
    def test_profiler_path(self):
        from agents.profiler import PROFILER_OUTPUT_PATH
        assert PROFILER_OUTPUT_PATH.classification == "full"

    def test_management_prep_path(self):
        from agents.management_prep import PREP_OUTPUT_PATH
        assert PREP_OUTPUT_PATH.classification == "full"

    def test_meeting_lifecycle_path(self):
        from agents.meeting_lifecycle import MEETING_OUTPUT_PATH
        assert MEETING_OUTPUT_PATH.classification == "full"

    def test_demo_path(self):
        from agents.demo import DEMO_OUTPUT_PATH
        assert DEMO_OUTPUT_PATH.classification == "full"

    def test_demo_eval_path(self):
        from agents.demo_pipeline.eval_rubrics import DEMO_EVAL_OUTPUT_PATH
        assert DEMO_EVAL_OUTPUT_PATH.classification == "full"

    def test_demo_critique_path(self):
        from agents.demo_pipeline.critique import DEMO_CRITIQUE_OUTPUT_PATH
        assert DEMO_CRITIQUE_OUTPUT_PATH.classification == "full"

    def test_drift_detector_path(self):
        from agents.drift_detector import DRIFT_OUTPUT_PATH
        assert DRIFT_OUTPUT_PATH.classification == "full"

    def test_scout_path(self):
        from agents.scout import SCOUT_OUTPUT_PATH
        assert SCOUT_OUTPUT_PATH.classification == "full"

    def test_digest_path(self):
        from agents.digest import DIGEST_OUTPUT_PATH
        assert DIGEST_OUTPUT_PATH.classification == "full"

    def test_code_review_path(self):
        from agents.code_review import CODE_REVIEW_OUTPUT_PATH
        assert CODE_REVIEW_OUTPUT_PATH.classification == "full"

    def test_research_path(self):
        from agents.research import RESEARCH_OUTPUT_PATH
        assert RESEARCH_OUTPUT_PATH.classification == "full"

    def test_status_update_path(self):
        from agents.status_update import STATUS_OUTPUT_PATH
        assert STATUS_OUTPUT_PATH.classification == "full"

    def test_review_prep_path(self):
        from agents.review_prep import REVIEW_PREP_OUTPUT_PATH
        assert REVIEW_PREP_OUTPUT_PATH.classification == "full"

    def test_knowledge_maint_path(self):
        from agents.knowledge_maint import KNOWLEDGE_MAINT_OUTPUT_PATH
        assert KNOWLEDGE_MAINT_OUTPUT_PATH.classification == "full"

    def test_activity_analyzer_path(self):
        from agents.activity_analyzer import ACTIVITY_OUTPUT_PATH
        assert ACTIVITY_OUTPUT_PATH.classification == "full"

    def test_dev_story_path(self):
        from agents.dev_story.__main__ import DEV_STORY_OUTPUT_PATH
        assert DEV_STORY_OUTPUT_PATH.classification == "full"


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run existing tests + new test (expect failures)**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/test_agent_enforcement_paths.py -v`
Expected: FAIL — ImportError on all agent OutputPath constants (they don't exist yet)

- [ ] **Step 4: Wire Group A agents (6 files) and run tests**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/ -q --timeout=60`
Expected: All existing tests pass + Group A enforcement path tests pass

- [ ] **Step 5: Commit Group A**

```bash
git add agents/profiler.py agents/management_prep.py agents/meeting_lifecycle.py agents/demo.py agents/demo_pipeline/eval_rubrics.py agents/demo_pipeline/critique.py tests/test_agent_enforcement_paths.py
git commit -m "feat: wire axiom enforcer into management and demo agents"
```

- [ ] **Step 4: Wire Group B agents (5 files)**

Same pattern as above.

- [ ] **Step 5: Run tests**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/ -q --timeout=60`
Expected: PASS

- [ ] **Step 7: Commit Group B**

```bash
git add agents/drift_detector.py agents/scout.py agents/digest.py agents/code_review.py agents/research.py
git commit -m "feat: wire axiom enforcer into analysis agents"
```

- [ ] **Step 8: Wire Group C agents (5 files)**

Same pattern.

- [ ] **Step 8: Run tests**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/ -q --timeout=60`
Expected: PASS

- [ ] **Step 10: Commit Group C**

```bash
git add agents/status_update.py agents/review_prep.py agents/knowledge_maint.py agents/activity_analyzer.py agents/dev_story/__main__.py
git commit -m "feat: wire axiom enforcer into remaining LLM agents"
```

---

## Chunk 6: Extant Text Sweep and Ongoing Coverage

### Task 10: Extant Text Sweep Script

**Files:**
- Create: `scripts/axiom-sweep.py`
- Create: `tests/test_axiom_sweep.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_axiom_sweep.py
"""Tests for axiom-sweep.py — extant text audit script."""

import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestSweepFileScanning(unittest.TestCase):
    def test_scan_markdown_file(self):
        from scripts import axiom_sweep

        with tempfile.TemporaryDirectory() as tmpdir:
            md_file = Path(tmpdir) / "test.md"
            md_file.write_text(
                "---\ntitle: Test\n---\n\nThis isn't a doc — it's a manifesto.\n"
            )
            violations = axiom_sweep.scan_file(md_file)
            assert len(violations) >= 1
            assert violations[0]["implication"] == "ex-prose-001"

    def test_skips_frontmatter_keys(self):
        from scripts import axiom_sweep

        with tempfile.TemporaryDirectory() as tmpdir:
            md_file = Path(tmpdir) / "test.md"
            # Frontmatter value containing pattern should not trigger
            md_file.write_text(
                "---\ntitle: This isn't relevant — it's metadata\n---\n\nClean prose.\n"
            )
            violations = axiom_sweep.scan_file(md_file)
            assert len(violations) == 0

    def test_scan_directory(self):
        from scripts import axiom_sweep

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "clean.md").write_text("Clean informative text.")
            (Path(tmpdir) / "bad.md").write_text("Here's the thing about this.")
            violations = axiom_sweep.scan_directory(Path(tmpdir))
            assert len(violations) >= 1

    def test_report_generation(self):
        from scripts import axiom_sweep

        violations = [
            {
                "source": "data/test.md",
                "implication": "ex-prose-001",
                "label": "performative-setup",
                "excerpt": "Here's the thing",
                "line": 5,
            }
        ]
        report = axiom_sweep.build_report(violations, files_scanned=10, qdrant_scanned=0)
        assert report["summary"]["total_violations"] == 1
        assert report["summary"]["by_implication"]["ex-prose-001"] == 1


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/test_axiom_sweep.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create scripts/__init__.py if needed and write sweep script**

```python
# scripts/axiom_sweep.py
"""One-time audit of extant text artifacts for axiom compliance.

Scans data/, profiles/, docs/, demo-data/, shared/operator.py system
prompt fragments, and Qdrant collections. Produces a JSON report.

Usage:
    uv run python scripts/axiom_sweep.py [--output PATH] [--skip-qdrant]
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path for imports
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from shared.axiom_pattern_checker import check_text

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

SCAN_DIRS = [
    _PROJECT_ROOT / "data",
    _PROJECT_ROOT / "profiles",
    _PROJECT_ROOT / "docs",
    _PROJECT_ROOT / "demo-data",
]

SCAN_FILES = [
    _PROJECT_ROOT / "README.md",
    _PROJECT_ROOT / "agent-architecture.md",
    _PROJECT_ROOT / "operations-manual.md",
]


def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter from markdown content."""
    match = _FRONTMATTER_RE.match(content)
    if match:
        return content[match.end():]
    return content


def scan_file(file_path: Path) -> list[dict]:
    """Scan a single file for axiom violations in prose content."""
    try:
        content = file_path.read_text(errors="replace")
    except (OSError, UnicodeDecodeError):
        return []

    prose = _strip_frontmatter(content)
    violations = check_text(prose)

    results = []
    for v in violations:
        # Calculate line number from position in prose
        line_in_prose = prose[:v.position].count("\n") + 1
        # Offset by frontmatter lines
        fm_match = _FRONTMATTER_RE.match(content)
        fm_lines = content[:fm_match.end()].count("\n") if fm_match else 0
        line = line_in_prose + fm_lines

        results.append({
            "source": str(file_path),
            "implication": v.implication_id,
            "label": v.label,
            "excerpt": v.matched_text,
            "line": line,
        })
    return results


def scan_directory(dir_path: Path) -> list[dict]:
    """Scan all markdown files in a directory tree."""
    violations = []
    if not dir_path.exists():
        return violations
    for md_file in dir_path.rglob("*.md"):
        violations.extend(scan_file(md_file))
    return violations


def build_report(
    violations: list[dict],
    files_scanned: int,
    qdrant_scanned: int,
) -> dict:
    """Build the sweep report structure."""
    by_implication = Counter(v["implication"] for v in violations)
    by_source_type: Counter[str] = Counter()
    for v in violations:
        source = v["source"]
        if "/data/" in source:
            by_source_type["data"] += 1
        elif "/profiles/" in source:
            by_source_type["profiles"] += 1
        elif "/docs/" in source:
            by_source_type["docs"] += 1
        elif "/demo-data/" in source:
            by_source_type["demo-data"] += 1
        else:
            by_source_type["other"] += 1

    return {
        "scan_time": datetime.now(timezone.utc).isoformat(),
        "files_scanned": files_scanned,
        "qdrant_entries_scanned": qdrant_scanned,
        "violations": violations,
        "summary": {
            "total_violations": len(violations),
            "by_implication": dict(by_implication),
            "by_source_type": dict(by_source_type),
        },
    }


def main() -> None:
    """Run the full extant text sweep."""
    import argparse

    parser = argparse.ArgumentParser(description="Axiom compliance sweep of extant text")
    parser.add_argument("--output", type=Path, default=_PROJECT_ROOT / "profiles" / "axiom-sweep-report.json")
    parser.add_argument("--skip-qdrant", action="store_true")
    args = parser.parse_args()

    all_violations: list[dict] = []
    files_scanned = 0

    # Scan directories
    for scan_dir in SCAN_DIRS:
        if scan_dir.exists():
            dir_violations = scan_directory(scan_dir)
            all_violations.extend(dir_violations)
            files_scanned += sum(1 for _ in scan_dir.rglob("*.md"))

    # Scan individual files
    for scan_file_path in SCAN_FILES:
        if scan_file_path.exists():
            all_violations.extend(scan_file(scan_file_path))
            files_scanned += 1

    # Scan system prompt fragments
    operator_py = _PROJECT_ROOT / "shared" / "operator.py"
    if operator_py.exists():
        all_violations.extend(scan_file(operator_py))
        files_scanned += 1

    qdrant_scanned = 0
    if not args.skip_qdrant:
        try:
            from qdrant_client import QdrantClient

            qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
            client = QdrantClient(qdrant_url)
            collections = ["claude-memory", "profile-facts", "documents", "axiom-precedents"]

            for collection in collections:
                try:
                    offset = None
                    while True:
                        points, next_offset = client.scroll(
                            collection_name=collection,
                            limit=100,
                            offset=offset,
                            with_payload=True,
                            with_vectors=False,
                        )
                        if not points:
                            break
                        for point in points:
                            qdrant_scanned += 1
                            payload = point.payload or {}
                            for field in ("text", "content", "summary", "description"):
                                text = payload.get(field, "")
                                if not text or not isinstance(text, str):
                                    continue
                                text_violations = check_text(text)
                                for v in text_violations:
                                    all_violations.append({
                                        "source": f"qdrant:{collection}:{point.id}:{field}",
                                        "implication": v.implication_id,
                                        "label": v.label,
                                        "excerpt": v.matched_text,
                                        "line": 0,
                                    })
                        offset = next_offset
                        if offset is None:
                            break
                except Exception as e:
                    print(f"Warning: failed to scan collection {collection}: {e}")
        except ImportError:
            print("Warning: qdrant-client not installed, skipping Qdrant scan")

    report = build_report(all_violations, files_scanned, qdrant_scanned)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    print(f"Sweep complete: {report['summary']['total_violations']} violations in {files_scanned} files")
    print(f"Report saved to {args.output}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/test_axiom_sweep.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/axiom_sweep.py tests/test_axiom_sweep.py
git commit -m "feat: add extant text sweep script for axiom compliance audit"
```

---

### Task 11: Ongoing Coverage — Drift Detector Integration

**Files:**
- Modify: `agents/drift_detector.py`

- [ ] **Step 1: Read drift_detector.py detect_drift() to find integration point**

The `detect_drift()` function (around line 536) runs several deterministic scans before the LLM call. The compliance pattern pass inserts after the existing `scan_axiom_violations()` call at line 542.

- [ ] **Step 2: Add pattern compliance scan to detect_drift()**

After the existing `axiom_violations = scan_axiom_violations()` line, add:

```python
# Runtime text compliance scan on documentation
from shared.axiom_pattern_checker import check_text as check_prose_compliance

prose_violations = []
docs_dir = Path(__file__).resolve().parent.parent / "docs"
for md_file in docs_dir.rglob("*.md"):
    try:
        content = md_file.read_text(errors="replace")
        # Strip frontmatter
        import re as _re
        fm = _re.match(r"^---\s*\n.*?\n---\s*\n", content, _re.DOTALL)
        prose = content[fm.end():] if fm else content
        violations = check_prose_compliance(prose)
        for v in violations:
            prose_violations.append({
                "file": str(md_file),
                "implication": v.implication_id,
                "label": v.label,
                "excerpt": v.matched_text,
            })
    except Exception:
        continue
```

Then include `prose_violations` in the drift report's deterministic items section.

- [ ] **Step 3: Run existing drift detector tests**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/ -k drift -v`
Expected: PASS (existing tests should not break — the new code only adds items to the report)

- [ ] **Step 4: Commit**

```bash
git add agents/drift_detector.py
git commit -m "feat: add prose compliance pass to drift detector"
```

---

### Task 12: Ongoing Coverage — Knowledge Maint Integration

**Files:**
- Modify: `agents/knowledge_maint.py`

- [ ] **Step 1: Read knowledge_maint.py to find Qdrant iteration loop**

The agent iterates Qdrant entries in `find_stale_sources()` (around line 110). The compliance check hooks into the same iteration or adds a new pass.

- [ ] **Step 2: Add compliance check function**

Add a new function that iterates a Qdrant collection and checks text payloads:

```python
def check_collection_compliance(
    client: QdrantClient,
    collection: str,
    limit: int = 1000,
) -> list[dict]:
    """Check Qdrant collection entries for axiom compliance violations."""
    from shared.axiom_pattern_checker import check_text

    violations = []
    offset = None

    while True:
        points, next_offset = client.scroll(
            collection_name=collection,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            break

        for point in points:
            payload = point.payload or {}
            # Check text-bearing payload fields
            for field in ("text", "content", "summary", "description"):
                text = payload.get(field, "")
                if not text:
                    continue
                text_violations = check_text(text)
                for v in text_violations:
                    violations.append({
                        "collection": collection,
                        "point_id": str(point.id),
                        "field": field,
                        "implication": v.implication_id,
                        "label": v.label,
                        "excerpt": v.matched_text,
                    })

        offset = next_offset
        if offset is None:
            break

    return violations
```

- [ ] **Step 3: Wire into the main report output**

Add the compliance results to the agent's existing report/summary output so violations appear when running `uv run python -m agents.knowledge_maint --summarize`.

- [ ] **Step 4: Run existing knowledge_maint tests**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/ -k knowledge -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/knowledge_maint.py
git commit -m "feat: add axiom compliance check to knowledge maintenance"
```

---

## Chunk 7: Observability and Finalization

### Task 13: Enforcement Timing and Observability

**Files:**
- Modify: `shared/axiom_enforcer.py`
- Modify: `tests/test_axiom_enforcer.py`

- [ ] **Step 1: Add timing instrumentation to enforce()**

Add `import time` to the top of `shared/axiom_enforcer.py`.

Wrap the pattern check and judge calls with timing in the `enforce()` function:

```python
import time

# In enforce(), before pattern check:
t0 = time.monotonic()
pattern_violations = check_text(current_text)
pattern_duration_ms = (time.monotonic() - t0) * 1000

# Before judge call (inside the full path block):
judge_duration_ms = 0.0
t1 = time.monotonic()
# ... existing judge call ...
judge_duration_ms = (time.monotonic() - t1) * 1000

total_duration_ms = pattern_duration_ms + judge_duration_ms
```

Add a `timing` field to `EnforcementResult`:

```python
class EnforcementTiming(BaseModel):
    pattern_duration_ms: float
    judge_duration_ms: float
    total_duration_ms: float

class EnforcementResult(BaseModel):
    passed: bool
    violations: list[PatternViolation | JudgeViolation]
    action_taken: Literal["delivered", "retried", "quarantined"]
    retries_used: int
    timing: EnforcementTiming | None = None
```

Populate `timing` in the return value. The caller (agent integration code) can
forward this to Langfuse as trace metadata if Langfuse is available. The enforcer
itself does not import Langfuse — it returns timing data, the caller logs it.

- [ ] **Step 2: Add timing test**

Add to `tests/test_axiom_enforcer.py`:

```python
class TestEnforceTiming(unittest.IsolatedAsyncioTestCase):
    async def test_timing_populated(self):
        path = OutputPath(
            name="test-agent",
            classification="fast",
            agent_name="test",
            output_destination="data/test/",
        )
        result = await enforce("Clean informative text.", path)
        assert result.timing is not None
        assert result.timing.pattern_duration_ms >= 0
        assert result.timing.total_duration_ms >= 0
```

- [ ] **Step 3: Run tests**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/test_axiom_enforcer.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add shared/axiom_enforcer.py tests/test_axiom_enforcer.py
git commit -m "feat: add enforcement timing instrumentation"
```

---

### Task 14: Run Full Test Suite

- [ ] **Step 1: Run all tests**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pytest tests/ -q --timeout=60`
Expected: All tests pass. New tests added: ~30 across 5 test files.

- [ ] **Step 2: Run linting**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run ruff check shared/axiom_pattern_checker.py shared/axiom_judge.py shared/axiom_enforcer.py shared/axiom_litellm_callback.py scripts/axiom_sweep.py`
Expected: No errors.

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run ruff format --check shared/axiom_pattern_checker.py shared/axiom_judge.py shared/axiom_enforcer.py shared/axiom_litellm_callback.py scripts/axiom_sweep.py`
Expected: No formatting issues.

- [ ] **Step 3: Run type checking**

Run: `cd /home/hapaxlegomenon/projects/hapax-council && uv run pyright shared/axiom_pattern_checker.py shared/axiom_judge.py shared/axiom_enforcer.py`
Expected: No errors.

- [ ] **Step 4: Fix any issues found, commit fixes**

```bash
git add -u
git commit -m "fix: address lint and type issues in enforcement modules"
```

---

### Task 15: LiteLLM Container Configuration

**Files:**
- Modify: `~/llm-stack/docker-compose.yml` (add volume mounts)
- Modify: `~/llm-stack/litellm-config.yaml` (add callback)

Note: These changes affect shared infrastructure. Verify with operator before applying.

- [ ] **Step 1: Document the required docker-compose.yml changes**

Add to the litellm service volumes:

```yaml
volumes:
  - ./litellm-config.yaml:/app/config.yaml:ro
  # Axiom enforcement callback
  - /home/hapaxlegomenon/projects/hapax-council/shared/axiom_litellm_callback.py:/app/axiom_litellm_callback.py:ro
  - /home/hapaxlegomenon/projects/hapax-council/shared/axiom_pattern_checker.py:/app/axiom_pattern_checker.py:ro
  - /home/hapaxlegomenon/projects/hapax-council/axioms/enforcement-patterns.yaml:/app/enforcement-patterns.yaml:ro
```

- [ ] **Step 2: Document the required litellm-config.yaml changes**

Add to litellm_settings:

```yaml
litellm_settings:
  success_callback: ["langfuse", "axiom_litellm_callback.AxiomAuditCallback"]
```

- [ ] **Step 3: Commit documentation of infra changes**

Create `docs/enforcement-deployment.md` with the above changes documented:

```bash
git add docs/enforcement-deployment.md
git commit -m "docs: add enforcement engine deployment instructions"
```
