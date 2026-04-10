# Prompt Compression Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compress typical voice turn from ~2,200 tokens to ~900-1,100 tokens via 7 independent optimizations on non-frozen code paths.

**Architecture:** Each task modifies a single module or small cluster of modules. No task depends on another except where noted. All work is in R&D mode on non-frozen paths. Tests follow existing patterns: `unittest.mock`, self-contained per file, `asyncio_mode = "auto"`.

**Tech Stack:** Python 3.12+, Pydantic, TOON format (`toon` package), LLMLingua-2 (optional), Qdrant client.

**Spec:** `docs/superpowers/specs/2026-04-10-prompt-compression-research-plan-design.md`

---

## File Map

| Task | Creates | Modifies | Tests |
|---|---|---|---|
| 1 | — | `agents/hapax_daimonion/persona.py`, `agents/hapax_daimonion/pipeline_start.py` | `tests/test_hapax_daimonion_persona.py` |
| 2 | — | `agents/hapax_daimonion/context_enrichment.py` | `tests/hapax_daimonion/test_context_enrichment.py` |
| 3 | — | `agents/hapax_daimonion/conversational_policy.py` | `tests/hapax_daimonion/test_conversational_policy.py` |
| 4 | — | `shared/operator.py`, `logos/_operator.py`, `shared/knowledge_search.py`, `agents/_knowledge_search.py` | `tests/test_context_compression.py` |
| 5 | — | `shared/knowledge_search.py`, `shared/profile_store.py` | `tests/shared/test_knowledge_search.py` (new) |
| 6 | — | `shared/context_compression.py` | `tests/test_context_compression.py` |
| 7 | — | `shared/context.py` | `tests/shared/test_context_assembler.py` (new) |

---

### Task 1: System Prompt Tool Directory Stripping

**Files:**
- Modify: `agents/hapax_daimonion/persona.py`
- Modify: `agents/hapax_daimonion/pipeline_start.py:74`
- Test: `tests/test_hapax_daimonion_persona.py`

- [ ] **Step 1: Write failing test for minimal prompt**

Add to `tests/test_hapax_daimonion_persona.py`:

```python
def test_system_prompt_minimal_has_no_tool_directory() -> None:
    prompt = system_prompt(tool_recruitment_active=True)
    assert "Hapax" in prompt
    assert "Your tools:" not in prompt
    assert "get_calendar_today" not in prompt
    assert len(prompt) < 600  # ~150 tokens ≈ ~600 chars


def test_system_prompt_minimal_preserves_identity() -> None:
    prompt = system_prompt(tool_recruitment_active=True)
    assert "warm but concise" in prompt
    assert "Never invent" in prompt


def test_system_prompt_full_when_no_recruitment() -> None:
    prompt = system_prompt(tool_recruitment_active=False)
    assert "Your tools:" in prompt
    assert "get_calendar_today" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_hapax_daimonion_persona.py -v -k "minimal or full_when"`
Expected: FAIL — `system_prompt()` does not accept `tool_recruitment_active` parameter

- [ ] **Step 3: Add `_SYSTEM_PROMPT_MINIMAL` and update `system_prompt()` in persona.py**

In `agents/hapax_daimonion/persona.py`, add after line 58 (after `_SYSTEM_PROMPT`):

```python
_SYSTEM_PROMPT_MINIMAL = (
    "You are Hapax, a voice assistant for {name}. "
    "You are warm but concise — friendly without being chatty. "
    "Keep responses spoken-natural and brief — one to three sentences. "
    "You know {name} well — use first name, skip formalities. "
    "Vary your phrasing naturally — never start two responses the same way. "
    "IMPORTANT: Only state facts you actually know or can look up via tools. "
    "Never invent meetings, events, notifications, or other specifics. "
    "If {name} says just your name without a clear request, "
    "acknowledge warmly and ask what they need. One sentence. "
    "If you have tools available, say a brief natural bridge before calling them — "
    "'Let me check', 'One moment', or similar. "
    "If you don't have tools for something, say so honestly."
)
```

Update `system_prompt()` signature and body:

```python
def system_prompt(
    guest_mode: bool = False,
    policy_block: str = "",
    experiment_mode: bool = False,
    tool_recruitment_active: bool = False,
) -> str:
    """Return the system prompt for the current session mode."""
    if guest_mode:
        return _GUEST_PROMPT + policy_block
    if experiment_mode:
        base = _EXPERIMENT_PROMPT
    elif tool_recruitment_active:
        base = _SYSTEM_PROMPT_MINIMAL
    else:
        base = _SYSTEM_PROMPT
    return base.format(name=operator_name()) + policy_block
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_hapax_daimonion_persona.py -v`
Expected: All PASS including new tests

- [ ] **Step 5: Wire flag in pipeline_start.py**

In `agents/hapax_daimonion/pipeline_start.py`, update lines 74-78:

```python
    tool_recruitment_gate = getattr(daemon, "_tool_recruitment_gate", None)

    prompt = system_prompt(
        guest_mode=daemon.session.is_guest_mode,
        policy_block=policy_block,
        experiment_mode=_experiment_mode,
        tool_recruitment_active=tool_recruitment_gate is not None,
    )
```

- [ ] **Step 6: Run full daimonion test suite**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_hapax_daimonion_persona.py tests/hapax_daimonion/test_conversational_policy.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
cd ~/projects/hapax-council
git add agents/hapax_daimonion/persona.py agents/hapax_daimonion/pipeline_start.py tests/test_hapax_daimonion_persona.py
git commit -m "feat: strip tool directory from system prompt when recruitment gate active

~1,000 tokens saved per voice turn. Recruited tool schemas in
kwargs['tools'] already carry complete descriptions — the natural
language directory in the system prompt is redundant.

Adds _SYSTEM_PROMPT_MINIMAL (identity + voice rules, no tool list).
Wired via tool_recruitment_active flag from pipeline_start.py."
```

---

### Task 2: DMN Buffer Compression

**Files:**
- Modify: `agents/hapax_daimonion/context_enrichment.py:103-127`
- Test: `tests/hapax_daimonion/test_context_enrichment.py`

- [ ] **Step 1: Write failing tests for compressed DMN output**

Add to `tests/hapax_daimonion/test_context_enrichment.py`:

```python
import os
import tempfile
import time

from agents.hapax_daimonion.context_enrichment import render_dmn


class TestRenderDmn:
    def _write_buffer(self, tmp: str, content: str) -> None:
        Path(tmp).write_text(content, encoding="utf-8")

    def test_stable_buffer_compressed(self, tmp_path):
        buf = tmp_path / "buffer.txt"
        lines = [
            f'<dmn_observation tick="{i}" age="{(18-i)*8}s">stable</dmn_observation>'
            for i in range(18)
        ]
        lines.append('<dmn_evaluation tick="17" age="5s"> Trajectory: stable. Concerns: none </dmn_evaluation>')
        buf.write_text("\n".join(lines))
        with patch("agents.hapax_daimonion.context_enrichment._DMN_BUFFER_PATH", buf):
            result = render_dmn()
            assert "stable" in result
            assert result.count("<dmn_observation") == 0  # No raw XML
            assert "18" in result  # Tick count preserved
            assert len(result) < 120  # Compressed, not 1200+ chars

    def test_changing_trajectory_shows_transitions(self, tmp_path):
        buf = tmp_path / "buffer.txt"
        lines = [
            '<dmn_observation tick="1" age="40s">stable</dmn_observation>',
            '<dmn_observation tick="2" age="32s">stable</dmn_observation>',
            '<dmn_observation tick="3" age="24s">elevated</dmn_observation>',
            '<dmn_observation tick="4" age="16s">elevated</dmn_observation>',
            '<dmn_observation tick="5" age="8s">cautious</dmn_observation>',
            '<dmn_evaluation tick="5" age="3s"> Trajectory: declining. Concerns: resource_pressure </dmn_evaluation>',
        ]
        buf.write_text("\n".join(lines))
        with patch("agents.hapax_daimonion.context_enrichment._DMN_BUFFER_PATH", buf):
            result = render_dmn()
            assert "stable" in result
            assert "elevated" in result
            assert "cautious" in result
            assert "resource_pressure" in result

    def test_empty_buffer_returns_empty(self, tmp_path):
        buf = tmp_path / "buffer.txt"
        buf.write_text("")
        with patch("agents.hapax_daimonion.context_enrichment._DMN_BUFFER_PATH", buf):
            assert render_dmn() == ""

    def test_stale_buffer_returns_empty(self, tmp_path):
        buf = tmp_path / "buffer.txt"
        buf.write_text('<dmn_observation tick="1" age="5s">stable</dmn_observation>')
        # Make file 120 seconds old
        old_time = time.time() - 120
        os.utime(buf, (old_time, old_time))
        with patch("agents.hapax_daimonion.context_enrichment._DMN_BUFFER_PATH", buf):
            assert render_dmn() == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/hapax-council && uv run pytest tests/hapax_daimonion/test_context_enrichment.py::TestRenderDmn -v`
Expected: FAIL — `_DMN_BUFFER_PATH` not patchable / raw XML still in output

- [ ] **Step 3: Implement compressed DMN rendering**

Replace `render_dmn()` in `agents/hapax_daimonion/context_enrichment.py`:

```python
import re
from pathlib import Path

_DMN_BUFFER_PATH = Path("/dev/shm/hapax-dmn/buffer.txt")
_DMN_STALE_S = 60.0

_OBS_RE = re.compile(r"<dmn_observation[^>]*>([^<]*)</dmn_observation>")
_EVAL_RE = re.compile(r"<dmn_evaluation[^>]*>\s*(.*?)\s*</dmn_evaluation>")


def render_dmn() -> str:
    """DMN buffer — compressed continuous background awareness.

    Parses raw XML observations, run-length encodes consecutive identical
    states, and emits a compact summary. ~10-15 tokens instead of ~300.
    """
    try:
        import os

        path = _DMN_BUFFER_PATH
        if not path.exists():
            return ""
        age_s = time.time() - os.path.getmtime(path)
        if age_s > _DMN_STALE_S:
            return ""
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return ""

        # Parse observations into run-length encoded segments
        observations = _OBS_RE.findall(text)
        evaluations = _EVAL_RE.findall(text)

        if not observations:
            return ""

        # Run-length encode
        runs: list[tuple[str, int]] = []
        for obs in observations:
            obs = obs.strip()
            if runs and runs[-1][0] == obs:
                runs[-1] = (obs, runs[-1][1] + 1)
            else:
                runs.append((obs, 1))

        # Format compressed summary
        if len(runs) == 1:
            state, count = runs[0]
            summary = f"DMN: {state} ({count} ticks)"
        else:
            parts = [f"{state} ({count})" for state, count in runs]
            summary = "DMN: " + " \u2192 ".join(parts)

        # Append evaluation if present
        if evaluations:
            eval_text = evaluations[-1].strip()
            summary += f". {eval_text}"

        return f"## Background Awareness (DMN)\n{summary}"
    except Exception:
        log.debug("render_dmn failed (non-fatal)", exc_info=True)
        return ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/projects/hapax-council && uv run pytest tests/hapax_daimonion/test_context_enrichment.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd ~/projects/hapax-council
git add agents/hapax_daimonion/context_enrichment.py tests/hapax_daimonion/test_context_enrichment.py
git commit -m "feat: compress DMN buffer from raw XML to run-length summary

18 identical 'stable' observations were consuming ~300 tokens.
Now rendered as 'DMN: stable (18 ticks)' at ~10-15 tokens.
Trajectory changes show transitions: 'stable (12) → elevated (3)'.
96% token reduction when DMN is stable (the common case)."
```

---

### Task 3: Policy Block Compression

**Files:**
- Modify: `agents/hapax_daimonion/conversational_policy.py:106-183`
- Test: `tests/hapax_daimonion/test_conversational_policy.py`

- [ ] **Step 1: Write failing test for compressed policy directives**

Add to `tests/hapax_daimonion/test_conversational_policy.py`:

```python
from agents.hapax_daimonion.conversational_policy import _modulate_for_environment


class TestCompressedModulation:
    def test_coding_mode_is_terse(self):
        env = MagicMock()
        env.activity_mode = "coding"
        env.face_count = 1
        env.consent_phase = "no_guest"
        env.phone_call_active = False
        env.phone_call_incoming = False
        env.phone_battery_pct = 100
        env.phone_media_playing = False
        rules = _modulate_for_environment(env)
        assert len(rules) == 1
        assert len(rules[0]) < 60  # Compressed, not verbose

    def test_meeting_mode_is_terse(self):
        env = MagicMock()
        env.activity_mode = "meeting"
        env.face_count = 1
        env.consent_phase = "no_guest"
        env.phone_call_active = False
        env.phone_call_incoming = False
        env.phone_battery_pct = 100
        env.phone_media_playing = False
        rules = _modulate_for_environment(env)
        assert len(rules) == 1
        assert len(rules[0]) < 80
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/hapax-council && uv run pytest tests/hapax_daimonion/test_conversational_policy.py::TestCompressedModulation -v`
Expected: FAIL — current directives are >60 chars

- [ ] **Step 3: Compress activity modulation directives**

Replace `_ACTIVITY_MODULATIONS` in `agents/hapax_daimonion/conversational_policy.py`:

```python
_ACTIVITY_MODULATIONS: dict[str, str] = {
    "coding": "Mode: coding. Maximum brevity. Technical register. No pleasantries.",
    "production": "Mode: production. Minimal interruption. Short confirmations only.",
    "meeting": "Mode: meeting. SILENT unless wake-word addressed. Hold everything.",
    "idle": "Mode: idle. Conversational. Exploratory pacing. Digressions welcome.",
}
```

- [ ] **Step 4: Compress phone/time-of-day/session directives**

Replace the verbose directives in `_modulate_for_environment()` body:

```python
    # Guest present
    if getattr(env, "guest_count", 0) > 0 or env.face_count > 1:
        rules.append("Guest present. Accessible language. No personal/work data.")

    # Session duration
    if session_start is not None:
        import time

        elapsed = time.monotonic() - session_start
        if elapsed > _LONG_SESSION_S:
            rules.append("Long session. Extra concise.")

    # Phone state
    if getattr(env, "phone_call_active", False):
        rules.append("Phone call active. Silent unless addressed.")
    if getattr(env, "phone_call_incoming", False):
        rules.append("Incoming call. Be brief.")
    phone_battery = getattr(env, "phone_battery_pct", 100)
    if phone_battery <= 15:
        rules.append(f"Phone battery {phone_battery}%.")
    if getattr(env, "phone_media_playing", False):
        title = getattr(env, "phone_media_app", "")
        rules.append(f"Phone playing media{f' ({title})' if title else ''}. Keep short.")

    # Time-of-day
    hour = datetime.now().hour
    if hour >= _LATE_EVENING_START or hour < _EARLY_MORNING_END:
        rules.append("Late hours. Lighter tone, shorter responses.")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ~/projects/hapax-council && uv run pytest tests/hapax_daimonion/test_conversational_policy.py -v`
Expected: All PASS (including existing tests — they test `get_policy()` structure, not directive wording)

- [ ] **Step 6: Commit**

```bash
cd ~/projects/hapax-council
git add agents/hapax_daimonion/conversational_policy.py tests/hapax_daimonion/test_conversational_policy.py
git commit -m "feat: compress policy directives from verbose to terse signals

Activity mode directives reduced from ~30 tokens to ~8 tokens each.
Phone/time/session directives similarly compressed.
SFT-only models (Hermes 3) respond more reliably to terse directives.
Total savings: 100-250 tokens per voice turn."
```

---

### Task 4: TOON Format Expansion

**Files:**
- Modify: `shared/knowledge_search.py:96-100`
- Modify: `agents/_knowledge_search.py:96-100`
- Modify: `shared/operator.py`
- Modify: `logos/_operator.py`
- Test: `tests/test_context_compression.py`

- [ ] **Step 1: Write test for TOON encoding of search results**

Add to `tests/test_context_compression.py`:

```python
class TestToToonSearchResults:
    def test_search_results_encode(self):
        data = {
            "query": "meeting notes",
            "results": [
                {"source": "obsidian", "text": "Team standup notes from Monday", "score": 0.85},
                {"source": "gmail", "text": "RE: Project kickoff", "score": 0.72},
            ],
        }
        result = to_toon(data)
        assert "obsidian" in result
        assert "0.85" in result or "85" in result
        # TOON is more compact than JSON
        import json
        json_len = len(json.dumps(data))
        assert len(result) < json_len
```

- [ ] **Step 2: Run test to verify it passes** (TOON already works for dicts)

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_context_compression.py::TestToToonSearchResults -v`
Expected: PASS — `to_toon()` already handles dicts. This confirms TOON works for the target format.

- [ ] **Step 3: Verify TOON is already used in knowledge_search.py**

`shared/knowledge_search.py:100` already calls `to_toon(result_data)`. Same for `agents/_knowledge_search.py:100`. These are already done.

Check which operator context paths still use markdown. Read `shared/operator.py` and `logos/_operator.py` for any structured data formatted as markdown instead of TOON.

- [ ] **Step 4: Convert remaining structured data to TOON in operator modules**

In both `shared/operator.py` and `logos/_operator.py`, find any health snapshot, nudge, or profile data rendered as markdown. Replace with `to_toon()` calls where the data source is structured (dict/Pydantic model). Preserve narrative text as-is.

Specific targets:
- Profile digest rendering (if formatted as markdown list)
- Health summary injection (if formatted as inline text)
- Goal rendering (if formatted as markdown list)

For each, replace:
```python
# Before
lines.append(f"- [{g.category}] {g.name}")
# After
from shared.context_compression import to_toon
lines.append(to_toon({"goals": [{"category": g.category, "name": g.name} for g in active]}))
```

- [ ] **Step 5: Run tests**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_context_compression.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
cd ~/projects/hapax-council
git add shared/operator.py logos/_operator.py shared/knowledge_search.py agents/_knowledge_search.py tests/test_context_compression.py
git commit -m "feat: expand TOON encoding to operator context and search results

TOON provides 40-60% token savings over markdown for structured data.
Applied to profile digest, health summary, and goal rendering in
operator context modules. Knowledge search already uses TOON."
```

---

### Task 5: Qdrant Retrieval Compression

**Files:**
- Modify: `shared/knowledge_search.py`
- Modify: `shared/profile_store.py`
- Create test: `tests/shared/test_retrieval_compression.py`

- [ ] **Step 1: Write failing tests for adaptive result limits**

Create `tests/shared/test_retrieval_compression.py`:

```python
"""Tests for Qdrant retrieval compression — adaptive limits."""

from __future__ import annotations

from shared.knowledge_search import _adaptive_limit


class TestAdaptiveLimit:
    def test_voice_pipeline_reduces_limit(self):
        assert _adaptive_limit(default=10, pipeline="voice") == 3

    def test_local_tier_reduces_limit(self):
        assert _adaptive_limit(default=10, tier="LOCAL") == 3

    def test_capable_tier_keeps_default(self):
        assert _adaptive_limit(default=10, tier="CAPABLE") == 10

    def test_no_context_keeps_default(self):
        assert _adaptive_limit(default=10) == 10

    def test_profile_voice_limit(self):
        assert _adaptive_limit(default=5, pipeline="voice") == 2

    def test_profile_default_limit(self):
        assert _adaptive_limit(default=5) == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council && uv run pytest tests/shared/test_retrieval_compression.py -v`
Expected: FAIL — `_adaptive_limit` does not exist

- [ ] **Step 3: Implement `_adaptive_limit` in knowledge_search.py**

Add to `shared/knowledge_search.py`:

```python
# Adaptive result limits for token-constrained pipelines
_VOICE_LIMIT_RATIO = 0.3  # 30% of default for voice/LOCAL
_MIN_LIMIT = 2


def _adaptive_limit(
    default: int,
    pipeline: str | None = None,
    tier: str | None = None,
) -> int:
    """Reduce Qdrant result limits for token-constrained contexts."""
    if pipeline == "voice" or tier in ("LOCAL", "local"):
        return max(_MIN_LIMIT, int(default * _VOICE_LIMIT_RATIO))
    return default
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council && uv run pytest tests/shared/test_retrieval_compression.py -v`
Expected: All PASS

- [ ] **Step 5: Wire adaptive limits into search functions**

Update `search_documents()` in `shared/knowledge_search.py` to accept optional `pipeline` and `tier` parameters and use `_adaptive_limit()` on the `limit` parameter before the Qdrant query.

Update `search()` in `shared/profile_store.py` similarly.

- [ ] **Step 6: Run full test suite for search**

Run: `cd ~/projects/hapax-council && uv run pytest tests/shared/ tests/test_context_compression.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
cd ~/projects/hapax-council
git add shared/knowledge_search.py shared/profile_store.py tests/shared/test_retrieval_compression.py
git commit -m "feat: adaptive Qdrant result limits for voice and LOCAL tiers

Voice pipeline and LOCAL tier get 30% of default result limits
(documents: 10→3, profiles: 5→2). Saves 200-400 tokens on
retrieval-heavy voice turns without affecting cloud agent queries."
```

---

### Task 6: LLMLingua-2 Hardening

**Files:**
- Modify: `shared/context_compression.py`
- Delete: `agents/_context_compression.py` (replace with re-export)
- Delete: `logos/_context_compression.py` (replace with re-export)
- Test: `tests/test_context_compression.py`

- [ ] **Step 1: Write test for compressor health check**

Add to `tests/test_context_compression.py`:

```python
class TestCompressorHealth:
    @patch("shared.context_compression._compressor", None)
    @patch("shared.context_compression._compressor_load_attempted", True)
    def test_health_reports_unavailable(self):
        from shared.context_compression import compressor_available
        assert compressor_available() is False

    @patch("shared.context_compression._compressor", MagicMock())
    @patch("shared.context_compression._compressor_load_attempted", True)
    def test_health_reports_available(self):
        from shared.context_compression import compressor_available
        assert compressor_available() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_context_compression.py::TestCompressorHealth -v`
Expected: FAIL — `compressor_available` not defined

- [ ] **Step 3: Add `compressor_available()` and domain-aware force tokens**

Add to `shared/context_compression.py`:

```python
# Domain-aware force tokens for compression
FORCE_TOKENS_VOICE = ["\n", "[", "]", "ACCEPT", "CLARIFY", "REJECT", "IGNORE", "REPAIR", "GROUNDED"]
FORCE_TOKENS_RETRIEVAL = ["\n", "[", "]", "source:", "score:"]
FORCE_TOKENS_DEFAULT = ["\n", "[", "]"]


def compressor_available() -> bool:
    """Check if LLMLingua-2 compressor is loaded. For health monitor."""
    return _compressor is not None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_context_compression.py -v`
Expected: All PASS

- [ ] **Step 5: Deduplicate compression module copies**

Replace `agents/_context_compression.py` contents with:

```python
"""agents/_context_compression.py — Re-export shim for shared.context_compression."""
from shared.context_compression import (  # noqa: F401
    FORCE_TOKENS_DEFAULT,
    FORCE_TOKENS_RETRIEVAL,
    FORCE_TOKENS_VOICE,
    compress_history,
    compressor_available,
    to_toon,
)
```

Replace `logos/_context_compression.py` contents with identical re-export shim (substitute `logos/` in the docstring).

- [ ] **Step 6: Verify all imports still resolve**

Run: `cd ~/projects/hapax-council && uv run python -c "from agents._context_compression import to_toon, compressor_available; print('agents OK')" && uv run python -c "from logos._context_compression import to_toon, compressor_available; print('logos OK')" && uv run python -c "from shared.context_compression import to_toon, compressor_available; print('shared OK')"`
Expected: All three print OK

- [ ] **Step 7: Run full test suite**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_context_compression.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
cd ~/projects/hapax-council
git add shared/context_compression.py agents/_context_compression.py logos/_context_compression.py tests/test_context_compression.py
git commit -m "feat: harden LLMLingua-2 — health check, domain force tokens, dedup

Adds compressor_available() for health monitor integration.
Adds domain-aware force_tokens lists (voice preserves grounding
markers, retrieval preserves citations).
Deduplicates 3 copies into shared/ canonical + re-export shims."
```

---

### Task 7: Cross-Agent Context Deduplication

**Files:**
- Modify: `shared/context.py`
- Create test: `tests/shared/test_context_assembler.py`

- [ ] **Step 1: Write failing test for cached context assembly**

Create `tests/shared/test_context_assembler.py`:

```python
"""Tests for ContextAssembler cached fragment assembly."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from shared.context import ContextAssembler


class TestCachedAssembly:
    def test_goals_cached_within_ttl(self):
        call_count = 0

        def goals_fn():
            nonlocal call_count
            call_count += 1
            return [{"name": "Ship v2", "category": "primary"}]

        assembler = ContextAssembler(goals_fn=goals_fn)
        snap1 = assembler.snapshot()
        snap2 = assembler.snapshot()
        assert snap1.active_goals == snap2.active_goals
        assert call_count == 1  # Second call served from cache

    def test_goals_refreshed_after_ttl(self):
        call_count = 0

        def goals_fn():
            nonlocal call_count
            call_count += 1
            return [{"name": f"Goal {call_count}"}]

        assembler = ContextAssembler(goals_fn=goals_fn, goals_ttl=0.0)
        snap1 = assembler.snapshot()
        snap2 = assembler.snapshot()
        assert call_count == 2

    def test_health_cached_within_ttl(self):
        call_count = 0

        def health_fn():
            nonlocal call_count
            call_count += 1
            return {"status": "healthy"}

        assembler = ContextAssembler(health_fn=health_fn)
        assembler.snapshot()
        assembler.snapshot()
        assert call_count == 1

    def test_flush_clears_cache(self):
        call_count = 0

        def goals_fn():
            nonlocal call_count
            call_count += 1
            return []

        assembler = ContextAssembler(goals_fn=goals_fn)
        assembler.snapshot()
        assembler.flush()
        assembler.snapshot()
        assert call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council && uv run pytest tests/shared/test_context_assembler.py -v`
Expected: FAIL — `ContextAssembler` does not accept `goals_ttl`, `snapshot()` not cached, `flush()` missing

- [ ] **Step 3: Add TTL-based caching to ContextAssembler**

Modify `shared/context.py` — update `ContextAssembler.__init__` to accept TTL parameters and add per-source caching:

```python
class ContextAssembler:
    """Gathers context from canonical sources with snapshot isolation and caching."""

    def __init__(
        self,
        stimmung_path: Path = _DEFAULT_STIMMUNG,
        dmn_buffer_path: Path = _DEFAULT_DMN_BUFFER,
        imagination_path: Path = _DEFAULT_IMAGINATION,
        goals_fn=None,
        health_fn=None,
        nudges_fn=None,
        perception_fn=None,
        goals_ttl: float = 60.0,
        health_ttl: float = 30.0,
        nudges_ttl: float = 30.0,
        profile_ttl: float = 300.0,
    ) -> None:
        self._stimmung_path = stimmung_path
        self._dmn_buffer_path = dmn_buffer_path
        self._imagination_path = imagination_path
        self._goals_fn = goals_fn or (lambda: [])
        self._health_fn = health_fn or (lambda: {})
        self._nudges_fn = nudges_fn or (lambda: [])
        self._perception_fn = perception_fn or (lambda: {})

        # Per-source cache: (result, timestamp)
        self._cache: dict[str, tuple[object, float]] = {}
        self._ttls = {
            "goals": goals_ttl,
            "health": health_ttl,
            "nudges": nudges_ttl,
        }

    def _cached_call(self, key: str, fn) -> object:
        """Return cached result if within TTL, otherwise call fn and cache."""
        now = time.time()
        ttl = self._ttls.get(key, 30.0)
        if key in self._cache:
            result, ts = self._cache[key]
            if (now - ts) < ttl:
                return result
        result = fn()
        self._cache[key] = (result, now)
        return result

    def flush(self) -> None:
        """Clear all cached fragments. Forces fresh data on next snapshot()."""
        self._cache.clear()
```

Update `snapshot()` to use `_cached_call()` for goals, health, and nudges:

```python
    def snapshot(self) -> EnrichmentContext:
        """Assemble a context snapshot from all sources."""
        return EnrichmentContext(
            timestamp=time.time(),
            stimmung_stance=self._read_stimmung_stance(),
            stimmung_raw=self._read_stimmung_raw(),
            active_goals=self._cached_call("goals", self._goals_fn),
            health_summary=self._cached_call("health", self._health_fn),
            pending_nudges=self._cached_call("nudges", self._nudges_fn),
            dmn_observations=self._read_dmn(),
            imagination_fragments=self._read_imagination(),
            perception_snapshot=self._perception_fn(),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council && uv run pytest tests/shared/test_context_assembler.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `cd ~/projects/hapax-council && uv run pytest tests/ -q --timeout=30`
Expected: No regressions

- [ ] **Step 6: Commit**

```bash
cd ~/projects/hapax-council
git add shared/context.py tests/shared/test_context_assembler.py
git commit -m "feat: TTL-based caching for ContextAssembler fragments

Goals (60s), health (30s), nudges (30s) are now cached per-source
with configurable TTLs. Agents calling within the same window
share cached results instead of re-querying independently.
flush() available for explicit cache invalidation."
```

---

## Verification Gate G-PC1

After all 7 tasks complete:

- [ ] **Run full test suite**

```bash
cd ~/projects/hapax-council && uv run pytest tests/ -q --timeout=60
```

- [ ] **Measure token budget**

```bash
cd ~/projects/hapax-council && uv run python -c "
from agents.hapax_daimonion.persona import system_prompt
full = system_prompt()
minimal = system_prompt(tool_recruitment_active=True)
print(f'Full prompt: {len(full)} chars (~{len(full)//4} tokens)')
print(f'Minimal prompt: {len(minimal)} chars (~{len(minimal)//4} tokens)')
print(f'Savings: {len(full) - len(minimal)} chars (~{(len(full) - len(minimal))//4} tokens)')
"
```

Expected: Minimal prompt < 600 chars (~150 tokens). Savings > 2,000 chars (~500 tokens) from system prompt alone.

- [ ] **Lint and format**

```bash
cd ~/projects/hapax-council && uv run ruff check . && uv run ruff format .
```
