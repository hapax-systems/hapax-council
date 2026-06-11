"""TurnBudget SSOT tests — voice-p1-turnbudget-20260610 (CASE-VOICE-FOUNDATION-20260610).

One timing module threaded STT→route→LLM→synth→playback (audit v2 §5e):
constants consolidated with derivations, the duplicated silence-timeout/
echo-TTL/pre-roll contradictions dead, every daimonion LLM call bounded,
TIMING receipt lines in log + witness.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from agents.hapax_daimonion import turn_budget as tb

DAIMONION = Path(__file__).resolve().parents[2] / "agents" / "hapax_daimonion"


class TestConstants:
    def test_echo_ttls_are_distinct_named_concepts(self):
        # The old code defined _ECHO_TTL_S twice in one file (30.0 in
        # _is_echo, 8.0 in _strip_echo_prefix) — same name, two values.
        # The contradiction dies by giving each concept its own name.
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
        # Post-question backchannel suppression is a DISTINCT concept from
        # the interview session silence timeout (180s) — distinct name.
        assert tb.INTERVIEW_QUESTION_SILENCE_S == 15.0

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


class TestWitnessTiming:
    def test_record_turn_timing_writes_and_preserves_status(self, tmp_path):
        from agents.hapax_daimonion import voice_output_witness as vw

        path = tmp_path / "witness.json"
        vw.record_tts_synthesis(
            status="completed", text="hello there", pcm=b"\x00" * 4800, path=path
        )
        before = vw.read_voice_output_witness(path=path)
        w = vw.record_turn_timing(
            kind="interactive",
            turn=4,
            legs={"stt": 312.0},
            notes={"route": "LOCAL"},
            total_ms=10400.0,
            budget_ms=90000.0,
            overrun=False,
            path=path,
        )
        assert w.last_turn_timing["legs"]["stt"] == 312.0
        assert w.last_turn_timing["kind"] == "interactive"
        # A timing receipt is accounting, not a lifecycle event — it must
        # never clobber the witness status the watchdog reads.
        assert w.status == before.status

    def test_budget_emit_writes_witness(self, tmp_path):
        from agents.hapax_daimonion.voice_output_witness import read_voice_output_witness

        path = tmp_path / "witness.json"
        b = tb.TurnBudget(kind="interactive", turn=1)
        b.mark("stt")
        b.emit(witness_path=path)
        assert read_voice_output_witness(path=path).last_turn_timing["kind"] == "interactive"

    def test_budget_emit_log_only(self, tmp_path, caplog):
        path = tmp_path / "witness.json"
        b = tb.TurnBudget(kind="interactive", turn=1)
        b.note(outcome="echo_rejected")
        with caplog.at_level(logging.INFO):
            b.emit(witness=False, witness_path=path)
        assert any(r.message.startswith("TIMING turn") for r in caplog.records)
        assert not path.exists()


class TestConsolidationPins:
    """Source-scan regression pins — the scatter must not regrow."""

    def test_no_duplicate_echo_ttl_definitions(self):
        src = (DAIMONION / "conversation_pipeline.py").read_text()
        assert "_ECHO_TTL_S = " not in src  # both contradictory locals are dead
        assert "ECHO_DETECT_TTL_S" in src
        assert "ECHO_STRIP_TTL_S" in src

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
        assert "300ms" not in src  # the pre-roll lie
        assert "cooldown removed" not in src.lower()  # the cooldown lie
        assert "PRE_ROLL_FRAMES = 50" not in src  # imported from SSOT

    def test_every_daimonion_llm_call_is_bounded(self):
        """Every litellm completion call site in the daimonion carries a timeout.

        Audit v2 §5e: "every LLM call bounded". litellm's default timeout is
        600s — one wedged request silences a voice path for ten minutes.
        """
        offenders = []
        for py in DAIMONION.rglob("*.py"):
            lines = py.read_text().splitlines()
            for i, line in enumerate(lines):
                if "acompletion(" in line or "litellm.completion(" in line:
                    if line.lstrip().startswith("#"):
                        continue  # mention in a comment, not a call site
                    # timeout may be a kwarg in the call (forward window) or
                    # set on a kwargs dict just above a `**kwargs` call.
                    window = "\n".join(lines[max(0, i - 12) : i + 30])
                    if "timeout" not in window:
                        offenders.append(f"{py.name}:{i + 1}")
        assert not offenders, f"unbounded LLM calls: {offenders}"


class _FakeDelta:
    def __init__(self, content):
        self.content = content
        self.tool_calls = None


class _FakeChoice:
    def __init__(self, content, finish_reason=None):
        self.delta = _FakeDelta(content)
        self.finish_reason = finish_reason


class _FakeChunk:
    def __init__(self, content, finish_reason=None):
        self.choices = [_FakeChoice(content, finish_reason)]


def _make_pipeline():
    """Minimal pipeline with mocked STT/TTS — mirrors test_experiential_proofs fixture."""
    from agents.hapax_daimonion.conversation_pipeline import ConversationPipeline, ConvState

    p = ConversationPipeline(stt=AsyncMock(), tts_manager=MagicMock(), system_prompt="t")
    p._running = True
    p.state = ConvState.LISTENING
    p.messages = [{"role": "system", "content": "t"}]
    p._audio_output = None
    return p


class TestTurnReceipt:
    def test_turn_receipt_emitted_with_stt_leg(self, caplog):
        from agents.hapax_daimonion.conversation_pipeline import ConversationPipeline

        p = _make_pipeline()
        p.stt.transcribe = AsyncMock(return_value="hello there my friend")

        async def _fake_generate(self_):
            self_._turn_budget.note(outcome="spoken")
            self_.messages.append({"role": "assistant", "content": "hi"})

        with (
            caplog.at_level(logging.INFO),
            patch.object(ConversationPipeline, "_generate_and_speak", _fake_generate),
            patch("agents.hapax_daimonion.turn_budget.record_turn_timing", MagicMock()),
        ):
            asyncio.run(p.process_utterance(b"\x00" * 3200))

        receipts = [r.message for r in caplog.records if r.message.startswith("TIMING turn")]
        assert len(receipts) == 1
        assert "stt=" in receipts[0]
        assert "kind=interactive" in receipts[0]
        assert "outcome=spoken" in receipts[0]

    def test_echo_rejected_turn_receipts_log_only(self, caplog, tmp_path, monkeypatch):
        p = _make_pipeline()
        p.stt.transcribe = AsyncMock(return_value="exact echo text")
        p._recent_tts_texts = [(time.monotonic(), "exact echo text")]
        witness = MagicMock()
        monkeypatch.setattr("agents.hapax_daimonion.turn_budget.record_turn_timing", witness)

        with caplog.at_level(logging.INFO):
            asyncio.run(p.process_utterance(b"\x00" * 3200))

        receipts = [r.message for r in caplog.records if r.message.startswith("TIMING turn")]
        assert len(receipts) == 1
        assert "outcome=echo_rejected" in receipts[0]
        witness.assert_not_called()  # early rejections never spam the witness


class TestSpontaneousLockDiscipline:
    def test_compose_does_not_speak(self):
        """compose_spontaneous_speech returns text without touching TTS."""
        p = _make_pipeline()
        p._speak_sentence = AsyncMock()
        impingement = MagicMock(
            content={"narrative": "the GPU is idle"}, source="exploration", strength=0.5
        )

        fake_response = MagicMock()
        fake_response.choices = [MagicMock(message=MagicMock(content="GPU's idle."))]
        with patch("litellm.acompletion", AsyncMock(return_value=fake_response)):
            text = asyncio.run(p.compose_spontaneous_speech(impingement, destination="private"))

        assert text == "GPU's idle."
        p._speak_sentence.assert_not_called()

    def test_compose_llm_timeout_drops_with_witness(self, monkeypatch):
        """Spontaneous overrun policy: drop-with-witness, never a spoken error."""
        p = _make_pipeline()
        p._speak_sentence = AsyncMock()
        impingement = MagicMock(
            content={"narrative": "something"}, source="exploration", strength=0.5
        )
        drops = []
        monkeypatch.setattr(
            "agents.hapax_daimonion.voice_output_witness.record_drop",
            lambda **kw: drops.append(kw),
        )
        # Receipt emission must not touch the production /dev/shm witness.
        monkeypatch.setattr("agents.hapax_daimonion.turn_budget.record_turn_timing", MagicMock())
        with patch("litellm.acompletion", AsyncMock(side_effect=TimeoutError())):
            text = asyncio.run(p.compose_spontaneous_speech(impingement, destination="private"))
        assert text is None
        assert any(d["reason"] == "spontaneous_speech_llm_timeout" for d in drops)
        p._speak_sentence.assert_not_called()

    def test_generate_wrapper_composes_then_speaks(self):
        p = _make_pipeline()
        p.compose_spontaneous_speech = AsyncMock(return_value="hi there")
        p.speak_spontaneous_text = AsyncMock()
        impingement = MagicMock(content={"narrative": "x"}, source="exploration", strength=0.5)
        asyncio.run(p.generate_spontaneous_speech(impingement))
        p.speak_spontaneous_text.assert_awaited_once()
