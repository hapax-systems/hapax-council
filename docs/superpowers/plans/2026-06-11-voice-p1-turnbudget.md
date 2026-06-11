# TurnBudget: One Timing Module, Constants Unified — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One timing SSOT (`agents/hapax_daimonion/turn_budget.py`) threaded STT→route→LLM→synth→playback; the ≥8-file constant scatter and its direct contradictions die; every daimonion LLM call is bounded; the spontaneous path can no longer wedge the speech lock; per-turn TIMING receipt lines land in the log and the voice-output witness.

**Task:** voice-p1-turnbudget-20260610 · CASE-VOICE-FOUNDATION-20260610 · spec §5e of `tts-voice-foundation-audit-2026-06-10-v2-execution.md`. Mutation scope: `agents/hapax_daimonion/` (+ tests, plan doc).

**Architecture:** `turn_budget.py` is a leaf module (imports nothing from daimonion) holding every voice-loop timing constant with a derivation comment, plus a `TurnBudget` dataclass (deadline + per-leg ms accounting + receipt rendering). Consumers import constants from it (keeping their existing local names as aliases where tests/back-compat need them). The witness gains `record_turn_timing`/`last_turn_timing`. The runner's exploration-surfacing path is restructured: LLM composition happens OUTSIDE the speech lock; the lock is held only for synth+playback+holdover.

**Tech Stack:** Python 3.12, pytest, pydantic (witness model), litellm (mocked in tests). Run tests with `uv run pytest`.

**Inventory ground truth (from origin/main):**

| Concept | Today | Contradiction |
|---|---|---|
| Echo TTL | `_ECHO_TTL_S = 30.0` (conversation_pipeline.py:1971, `_is_echo`) AND `_ECHO_TTL_S = 8.0` (same file :2013, `_strip_echo_prefix`) | same name, same file, two values |
| Pre-roll | `PRE_ROLL_FRAMES = 50` (=1500ms) in conversation_buffer.py:30; module docstring says "captures 300ms" | doc vs code, 5× off |
| Post-TTS cooldown | conversation_buffer docstring: "Post-TTS cooldown removed"; code: `POST_TTS_COOLDOWN_S = 2.0` + dynamic scaling live; runner duplicates `_echo_cooldown_s = 2.0`; two hardcoded `asyncio.sleep(3.0)` holdovers in runner | doc vs code + duplicated literal |
| Silence timeout | `_SILENCE_TIMEOUT_S = 30.0` (conversation_helpers.py:163) + `silence_timeout_s: int = 30` (config.py) + runner `_INTERVIEW_SILENCE_DEFAULT_S = 15.0` (post-question suppression, misleadingly named vs `_PROGRAMME_SILENCE_TIMEOUT["interview"] = 180.0`) | duplicated defaults, colliding names |
| LLM bounds | spontaneous 60s (named const), conversational stream `kwargs["timeout"] = 15` (bare literal) + `wait_for(..., timeout=90.0)` (bare literal), `daily_segment_prep._PREP_LLM_TIMEOUT_S = 1200`, **angle_resolver.py:323 litellm.completion with NO timeout** (litellm default 600s) | one unbounded call; literals scattered |
| Speech lock | runner:1450 holds `_speech_lock` across `generate_spontaneous_speech` INCLUDING the LLM call (≤60s hold) | spontaneous path wedges lock |
| TIMING lines | per-leg scatter: `TIMING stt=` (:851), `TIMING route=` (:1012), `TIMING llm_ttft=` (:1495), `TIMING tts_synth=` (:2313); no end-of-turn receipt, nothing in witness | no per-turn receipt |

---

### Task 1: `turn_budget.py` — constants + TurnBudget object (TDD)

**Files:**
- Create: `agents/hapax_daimonion/turn_budget.py`
- Test: `tests/hapax_daimonion/test_turn_budget.py`

- [ ] **Step 1: Write failing tests** for constants, derivations, `TurnBudget` behavior, `dynamic_cooldown_s`:

```python
"""TurnBudget SSOT — voice-p1-turnbudget-20260610 (CASE-VOICE-FOUNDATION-20260610)."""

import time

from agents.hapax_daimonion import turn_budget as tb


class TestConstants:
    def test_echo_ttls_are_distinct_named_concepts(self):
        assert tb.ECHO_DETECT_TTL_S == 30.0
        assert tb.ECHO_STRIP_TTL_S == 8.0

    def test_pre_roll_derivation_is_honest(self):
        # 50 frames × 30ms = 1.5s (NOT the 300ms the old docstring claimed)
        assert tb.FRAME_DURATION_S == tb.FRAME_SAMPLES / tb.SAMPLE_RATE
        assert tb.PRE_ROLL_DURATION_S == tb.PRE_ROLL_FRAMES * tb.FRAME_DURATION_S
        assert tb.PRE_ROLL_DURATION_S == 1.5

    def test_cooldown_family(self):
        assert tb.POST_TTS_COOLDOWN_S == 2.0
        assert tb.POST_TTS_COOLDOWN_MAX_S == 5.0
        assert tb.SPEECH_GATE_HOLDOVER_S == 3.0
        assert tb.dynamic_cooldown_s(0.0) == 2.0
        assert tb.dynamic_cooldown_s(4.0) == 2.0 + 4.0 * tb.POST_TTS_COOLDOWN_SCALE
        assert tb.dynamic_cooldown_s(60.0) == 5.0  # capped

    def test_silence_timeouts(self):
        assert tb.SILENCE_TIMEOUT_S == 30.0
        assert tb.PROGRAMME_SILENCE_TIMEOUT_S["interview"] == 180.0
        assert tb.INTERVIEW_QUESTION_SILENCE_S == 15.0  # distinct concept, distinct name

    def test_llm_bounds(self):
        assert tb.SPONTANEOUS_LLM_TIMEOUT_S == 60.0
        assert tb.CONVERSATION_LLM_REQUEST_TIMEOUT_S == 15.0
        assert tb.INTERACTIVE_TURN_BUDGET_S == 90.0
        assert tb.PREP_LLM_TIMEOUT_S == 1200.0
        assert tb.BARGE_IN_STT_TIMEOUT_S == 2.0


class TestTurnBudget:
    def test_marks_accumulate_leg_ms(self):
        b = tb.TurnBudget(kind="interactive", turn=3)
        ms = b.mark("stt")
        assert ms >= 0.0
        assert b.legs["stt"] == ms

    def test_mark_with_explicit_t0(self):
        b = tb.TurnBudget()
        t0 = time.monotonic() - 0.05
        ms = b.mark("llm_ttft", t0=t0)
        assert 45.0 <= ms < 1000.0

    def test_add_accumulates(self):
        b = tb.TurnBudget()
        b.add("synth", 100.0)
        b.add("synth", 50.0)
        assert b.legs["synth"] == 150.0

    def test_remaining_and_overrun(self):
        b = tb.TurnBudget(budget_s=0.001)
        time.sleep(0.005)
        assert b.remaining_s() == 0.0
        assert b.overrun

    def test_not_overrun_within_budget(self):
        b = tb.TurnBudget(budget_s=60.0)
        assert not b.overrun
        assert 0.0 < b.remaining_s() <= 60.0

    def test_receipt_line(self):
        b = tb.TurnBudget(kind="spontaneous", budget_s=60.0, turn=7)
        b.mark("stt")
        b.note(route="LOCAL", outcome="spoken")
        line = b.receipt()
        assert line.startswith("TIMING turn")
        assert "kind=spontaneous" in line
        assert "stt=" in line
        assert "route=LOCAL" in line
        assert "outcome=spoken" in line
        assert "budget=60000ms" in line
        assert "overrun=false" in line
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/hapax_daimonion/test_turn_budget.py -x -q`
Expected: FAIL — `ModuleNotFoundError`/`ImportError` for `turn_budget`.

- [ ] **Step 3: Implement `agents/hapax_daimonion/turn_budget.py`** — every constant carries its derivation; `TurnBudget` dataclass with `mark/add/note/elapsed_s/remaining_s/overrun/receipt/emit`. `emit()` logs the receipt and (optionally) writes the witness via a local import of `record_turn_timing` (Task 2).

- [ ] **Step 4: Run to verify pass** (witness emit test comes in Task 2)

Run: `uv run pytest tests/hapax_daimonion/test_turn_budget.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit** `feat(voice): turn_budget.py timing SSOT — constants with derivations + TurnBudget object`

### Task 2: Witness `record_turn_timing`

**Files:**
- Modify: `agents/hapax_daimonion/voice_output_witness.py` (add `last_turn_timing` field + `record_turn_timing()`)
- Test: extend `tests/hapax_daimonion/test_turn_budget.py`

- [ ] **Step 1: Failing tests** — `record_turn_timing` writes `last_turn_timing` into the witness JSON at a tmp path, preserves the existing `status`, and `TurnBudget.emit(witness_path=...)` round-trips:

```python
class TestWitnessTiming:
    def test_record_turn_timing_writes_and_preserves_status(self, tmp_path):
        from agents.hapax_daimonion import voice_output_witness as vw

        path = tmp_path / "witness.json"
        vw.record_tts_synthesis(status="completed", text="hello there", pcm=b"\x00" * 4800, path=path)
        before = vw.read_voice_output_witness(path=path)
        w = vw.record_turn_timing(
            kind="interactive", turn=4, legs={"stt": 312.0}, notes={"route": "LOCAL"},
            total_ms=10400.0, budget_ms=90000.0, overrun=False, path=path,
        )
        assert w.last_turn_timing["legs"]["stt"] == 312.0
        assert w.status == before.status  # timing receipt never clobbers lifecycle status

    def test_budget_emit_writes_witness(self, tmp_path):
        path = tmp_path / "witness.json"
        b = tb.TurnBudget(kind="interactive", turn=1)
        b.mark("stt")
        b.emit(witness_path=path)
        from agents.hapax_daimonion.voice_output_witness import read_voice_output_witness
        assert read_voice_output_witness(path=path).last_turn_timing["kind"] == "interactive"
```

- [ ] **Step 2: Run — FAIL.** **Step 3: Implement** (field + function mirroring `_merge_and_publish` but reusing the loaded payload's `status`). **Step 4: Run — PASS.** **Step 5: Commit** `feat(voice): witness gains last_turn_timing + record_turn_timing`

### Task 3: Consolidate constants — consumers import the SSOT

**Files:**
- Modify: `agents/hapax_daimonion/conversation_helpers.py` (silence timeouts, `_MAX_ACCUMULATION_S` → import/alias)
- Modify: `agents/hapax_daimonion/conversation_buffer.py` (FRAME/SAMPLE/PRE_ROLL/cooldown → import; fix the two lying docstrings; `set_speaking` uses `dynamic_cooldown_s`)
- Modify: `agents/hapax_daimonion/conversation_pipeline.py` (`_ECHO_TTL_S` ×2 → `ECHO_DETECT_TTL_S`/`ECHO_STRIP_TTL_S`; `_SPONTANEOUS_LLM_TIMEOUT_S` → import; `kwargs["timeout"] = 15` → `CONVERSATION_LLM_REQUEST_TIMEOUT_S`)
- Modify: `agents/hapax_daimonion/cpal/runner.py` (`_INTERVIEW_SILENCE_DEFAULT_S` → `INTERVIEW_QUESTION_SILENCE_S`; `_echo_cooldown_s = 2.0` → `POST_TTS_COOLDOWN_S`; two `asyncio.sleep(3.0)` → `SPEECH_GATE_HOLDOVER_S`)
- Modify: `agents/hapax_daimonion/speech_classifier.py` (`_STT_TIMEOUT_S` → `BARGE_IN_STT_TIMEOUT_S` alias)
- Modify: `agents/hapax_daimonion/config.py` (`silence_timeout_s: int = int(SILENCE_TIMEOUT_S)`)
- Modify: `agents/hapax_daimonion/daily_segment_prep.py` (`_PREP_LLM_TIMEOUT_S` → alias of `PREP_LLM_TIMEOUT_S`)
- Modify: `agents/hapax_daimonion/angle_resolver.py` (add `timeout=PREP_LLM_TIMEOUT_S` — the one unbounded LLM call)
- Test: extend `tests/hapax_daimonion/test_turn_budget.py` with the regression pin

- [ ] **Step 1: Failing regression-pin tests** (source-scan style, like `tests/test_wgsl_node_affordance_coverage.py`):

```python
from pathlib import Path

DAIMONION = Path(__file__).resolve().parents[2] / "agents" / "hapax_daimonion"


class TestConsolidationPins:
    def test_no_duplicate_echo_ttl_definitions(self):
        src = (DAIMONION / "conversation_pipeline.py").read_text()
        assert "_ECHO_TTL_S = " not in src  # both contradictory locals are dead
        assert "ECHO_DETECT_TTL_S" in src and "ECHO_STRIP_TTL_S" in src

    def test_no_bare_turn_timeout_literals(self):
        src = (DAIMONION / "conversation_pipeline.py").read_text()
        assert "timeout=90.0" not in src
        assert '"timeout"] = 15' not in src
        assert "_SPONTANEOUS_LLM_TIMEOUT_S = " not in src  # imported, not redefined

    def test_runner_holdover_uses_constant(self):
        src = (DAIMONION / "cpal" / "runner.py").read_text()
        assert "asyncio.sleep(3.0)" not in src
        assert "SPEECH_GATE_HOLDOVER_S" in src
        assert "_echo_cooldown_s = 2.0" not in src

    def test_buffer_docstrings_tell_truth(self):
        src = (DAIMONION / "conversation_buffer.py").read_text()
        assert "300ms" not in src           # the pre-roll lie
        assert "cooldown removed" not in src.lower()  # the cooldown lie
        assert "PRE_ROLL_FRAMES = 50" not in src      # imported from SSOT

    def test_every_daimonion_llm_call_is_bounded(self):
        """Every litellm completion call site in the daimonion carries a timeout."""
        offenders = []
        for py in DAIMONION.rglob("*.py"):
            lines = py.read_text().splitlines()
            for i, line in enumerate(lines):
                if "acompletion(" in line or "litellm.completion(" in line:
                    window = "\n".join(lines[i : i + 30])
                    if "timeout" not in window:
                        offenders.append(f"{py.name}:{i + 1}")
        assert not offenders, f"unbounded LLM calls: {offenders}"
```

- [ ] **Step 2: Run — FAIL** (echo TTLs, literals, docstrings, angle_resolver all still on main's shape).
- [ ] **Step 3: Implement the modifications.** Back-compat aliases keep old names importable (`_SILENCE_TIMEOUT_S`, `_MAX_ACCUMULATION_S`, `PRE_ROLL_FRAMES`, `POST_TTS_COOLDOWN_S`, `_STT_TIMEOUT_S`, `_PREP_LLM_TIMEOUT_S`) so existing imports/tests don't break.
- [ ] **Step 4: Run new pins + the existing suite for touched modules:**
`uv run pytest tests/hapax_daimonion/ tests/test_voice.py tests/test_voice_imagination_wiring.py tests/test_experiential_proofs.py -q`
Expected: PASS (or only failures already present on main — verify by A/B with `git stash`).
- [ ] **Step 5: Commit** `feat(voice): timing constants consolidated into turn_budget SSOT — contradictions die`

### Task 4: Thread TurnBudget STT→route→LLM→synth→playback + receipt

**Files:**
- Modify: `agents/hapax_daimonion/conversation_pipeline.py`
- Test: extend `tests/hapax_daimonion/test_turn_budget.py`

Threading map:
1. `process_utterance`: create `TurnBudget(kind="interactive", budget_s=INTERACTIVE_TURN_BUDGET_S, turn=self.turn_count)`, store `self._turn_budget`; in the `finally`, `budget.emit(witness=engaged)` where `engaged` = outcome is not an early rejection (no_transcript/echo/duplicate keep log-only receipts; spoken/canned/llm_timeout/error also write the witness).
2. `_process_utterance_inner`: `budget.mark("stt")` after transcribe; `budget.note(route=…, model=…)` after routing; terminal `budget.note(outcome=…)` on every early return (no_transcript, music_rejected, echo_rejected, echo_stripped_empty, duplicate, canned, spoken, llm_timeout, llm_error).
3. The 90s literal becomes the deadline object: `await asyncio.wait_for(llm_task, timeout=self._turn_budget.remaining_s())` — STT time now truthfully counts against the turn.
4. `_generate_and_speak`: `budget.mark("llm_ttft", t0=_t_llm_start)` at first token (keep the existing per-leg TIMING log line); `budget.mark("llm_total", t0=_t_llm_start)` after the stream drains.
5. `_speak_sentence`: first synthesis of the turn → `budget.mark("ttfa")` (time-to-first-audio from utterance start — the interview-bar metric); every synthesis → `budget.add("synth", tts_ms)`.
6. Overrun policy (interactive → canned PCM, never a 15s spoken apology): on `TimeoutError`, play the failure phrase through the bridge presynth cache (`_play_guarded_pcm`) and only fall back to live synth if the cache misses. Add the two failure phrases to `bridge_engine._CANNED_RESPONSES` so `presynthesize_all` covers them.

- [ ] **Step 1: Failing tests:**

```python
class TestTurnReceipt:
    def _make_pipeline(self):  # mirrors tests/test_experiential_proofs.py fixture
        from unittest.mock import AsyncMock, MagicMock
        from agents.hapax_daimonion.conversation_pipeline import ConversationPipeline, ConvState
        p = ConversationPipeline(stt=AsyncMock(), tts_manager=MagicMock(), system_prompt="t")
        p._running = True
        p.state = ConvState.LISTENING
        p.messages = [{"role": "system", "content": "t"}]
        p._audio_output = None
        return p

    def test_turn_receipt_emitted_with_stt_leg(self, caplog):
        import asyncio, logging
        p = self._make_pipeline()
        p.stt.transcribe = AsyncMock(return_value="hello there my friend")

        async def _fake_generate(self_):
            self_._turn_budget.note(outcome="spoken")
            self_.messages.append({"role": "assistant", "content": "hi"})
        with caplog.at_level(logging.INFO), patch.object(ConversationPipeline, "_generate_and_speak", _fake_generate):
            asyncio.run(p.process_utterance(b"\x00" * 3200))
        receipts = [r.message for r in caplog.records if r.message.startswith("TIMING turn")]
        assert len(receipts) == 1
        assert "stt=" in receipts[0] and "kind=interactive" in receipts[0]

    def test_echo_rejected_turn_still_receipts_log_only(self, caplog, tmp_path, monkeypatch):
        ...  # outcome=echo_rejected in receipt; witness file untouched
```

- [ ] **Step 2: FAIL → Step 3: implement → Step 4: PASS** (plus existing suites rerun). **Step 5: Commit** `feat(voice): TurnBudget threaded through the interactive turn — per-leg receipt lines`

### Task 5: Spontaneous path — budget receipts + lock no longer wedgeable

**Files:**
- Modify: `agents/hapax_daimonion/conversation_pipeline.py` (split `generate_spontaneous_speech` → `compose_spontaneous_speech` + `speak_spontaneous_text`; keep the original as compose→speak wrapper; receipts on every terminal)
- Modify: `agents/hapax_daimonion/cpal/runner.py` (exploration-surfacing site: compose OUTSIDE `_speech_lock`; re-check lock/`_processing_utterance` post-compose; lock held only for speak+holdover; keep legacy ladder for pipelines without the new methods via real-class check, not `hasattr` — MagicMock auto-attrs would lie)
- Test: extend `tests/hapax_daimonion/test_turn_budget.py`; update `tests/test_voice_imagination_wiring.py` wiring assertions deliberately

- [ ] **Step 1: Failing tests** — compose returns text without touching `_speak_sentence`; wrapper preserves behavior; lock-hold during compose is zero (instrument a fake lock); spontaneous timeout → `record_drop(reason="spontaneous_speech_llm_timeout")`, never a spoken error; receipt `kind=spontaneous` emitted.
- [ ] **Step 2: FAIL → Step 3: implement → Step 4: PASS + update wiring tests.** **Step 5: Commit** `feat(voice): spontaneous speech composes outside the speech lock — wedge dies`

### Task 6: Full verification + PR

- [ ] `uv run ruff check agents/hapax_daimonion tests/hapax_daimonion && uv run ruff format --check` (scoped)
- [ ] Full daimonion-adjacent suite A/B vs origin/main (known pre-existing env failures per memory: A/B before attributing)
- [ ] Push, open PR with receipts table (constants killed per file, contradictions resolved, lock-hold delta), then `uv run --no-sync bash scripts/cc-close voice-p1-turnbudget-20260610 --pr <N>` — frontier_review_required ⇒ ends at pr_open awaiting acceptance.yaml.

**Self-review notes:** Spec coverage — §5e items: one module ✓(T1), constants+derivations ✓(T1,T3), deadline object threaded ✓(T4), per-leg accounting to witness/TIMING ✓(T2,T4), overrun policy drop-with-witness/canned-PCM ✓(T4,T5), spontaneous real timeout ✓(already on main; constant moves to SSOT T3), silence/echo/pre-roll contradictions die ✓(T3), every LLM call bounded ✓(T3 angle_resolver + pin test), lock wedge ✓(T5), local-fast beliefs → config (already landed on main via `LOCAL_FAST_SUBSTRATE`; pin remains in router docstring — verified, no action). Out of scope per spec: barge-in path deletion (voice-p2), cooldown RE-CALIBRATION (post-substrate; values are consolidated, not retuned).
