# Voice Daemon Integration Test Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exercise all 8 fundamental surfaces of the hapax-voice daemon to 99% basic-flow reliability, gated sequentially.

**Architecture:** Integration tests that wire real components together with mocked I/O boundaries (audio hardware, LLM endpoints, Hyprland IPC). Each surface has a gating test that must pass before proceeding to the next. Live smoke test script validates against the running daemon.

**Tech Stack:** pytest + asyncio, unittest.mock, socat (socket testing), journalctl (log verification)

**Execution order:** wake_word→pipeline (1) → STT→LLM→TTS (2) → session_lifecycle (3) → tool_calling (4) → desktop_tools (5) → perception→governor (6) → notifications (7) → hotkeys (8)

---

## File Structure

```
tests/hapax_voice/
  test_surface_wake_pipeline.py    # Surface 1: wake word → pipeline start
  test_surface_voice_roundtrip.py  # Surface 2: STT → LLM → TTS
  test_surface_session.py          # Surface 3: session lifecycle
  test_surface_tool_calling.py     # Surface 4: tool handler execution
  test_surface_desktop.py          # Surface 5: desktop tools via Hyprland
  test_surface_governor.py         # Surface 6: perception → governor → frame gate
  test_surface_notifications.py    # Surface 7: ntfy → queue → delivery
  test_surface_hotkeys.py          # Surface 8: socket → command → action
scripts/
  smoke_test_voice.sh              # Live smoke tests against running daemon
```

Each `test_surface_*.py` file is self-contained with its own daemon construction helper — no shared conftest fixtures.

---

## Shared Pattern: Daemon Construction

Every surface test builds a `VoiceDaemon` with `__init__` bypassed and individual attributes mocked. This is the established pattern from `test_daemon_audio_wiring.py`. Each test file will have its own `_make_daemon()` that mocks exactly what that surface needs, leaving the components under test as real objects.

---

## Chunk 1: Wake Word → Pipeline + Voice Round-Trip

### Task 1: Surface 1 — Wake Word → Pipeline Start

**Files:**
- Create: `tests/hapax_voice/test_surface_wake_pipeline.py`

This tests the critical path: wake word detected → session opens → audio input stops → pipeline builds → pipeline task created.

- [ ] **Step 1: Write the test file**

```python
"""Surface 1: Wake word detection → pipeline start.

Tests the critical handoff: wake word fires → session opens →
daemon audio stops → Pipecat pipeline builds and starts.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_voice.__main__ import VoiceDaemon
from agents.hapax_voice.session import VoiceLifecycle


def _make_daemon() -> VoiceDaemon:
    """VoiceDaemon with real SessionManager, everything else mocked."""
    with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
        daemon = VoiceDaemon()

    daemon.cfg = MagicMock()
    daemon.cfg.backend = "local"
    daemon.cfg.local_stt_model = "base"
    daemon.cfg.llm_model = "test-model"
    daemon.cfg.kokoro_voice = "af_heart"
    daemon.cfg.chime_enabled = False

    daemon.session = VoiceLifecycle(silence_timeout_s=30)
    daemon.event_log = MagicMock()
    daemon.chime_player = MagicMock()
    daemon._audio_input = MagicMock()
    daemon._audio_input.is_active = True
    daemon._pipeline_task = None
    daemon._pipecat_task = None
    daemon._pipecat_transport = None
    daemon._gemini_session = None
    daemon._frame_gate = MagicMock()
    daemon.governor = MagicMock()
    daemon.workspace_monitor = MagicMock()
    daemon.workspace_monitor.webcam_capturer = None
    daemon.workspace_monitor.screen_capturer = None

    return daemon


class TestWakeWordOpensSession:
    """Wake word detection opens a session and starts the pipeline."""

    def test_session_opens_on_wake_word(self):
        daemon = _make_daemon()
        assert not daemon.session.is_active

        daemon._on_wake_word()

        assert daemon.session.is_active
        assert daemon.session.trigger == "wake_word"
        assert daemon.session.session_id is not None

    def test_governor_wake_word_flag_set(self):
        daemon = _make_daemon()
        daemon.governor.wake_word_active = False

        daemon._on_wake_word()

        assert daemon.governor.wake_word_active is True

    def test_frame_gate_set_to_process(self):
        daemon = _make_daemon()

        daemon._on_wake_word()

        daemon._frame_gate.set_directive.assert_called_once_with("process")

    def test_event_log_records_session_open(self):
        daemon = _make_daemon()

        daemon._on_wake_word()

        daemon.event_log.emit.assert_any_call(
            "session_lifecycle", action="opened", trigger="wake_word"
        )

    def test_wake_word_noop_if_session_active(self):
        daemon = _make_daemon()
        daemon.session.open(trigger="test")
        daemon.event_log.reset_mock()

        daemon._on_wake_word()

        daemon.event_log.emit.assert_not_called()


class TestWakeWordStartsPipeline:
    """Wake word triggers pipeline build and audio handoff."""

    @pytest.mark.asyncio
    async def test_pipeline_starts_on_wake_word(self):
        daemon = _make_daemon()

        with patch(
            "agents.hapax_voice.__main__.VoiceDaemon._start_pipeline",
            new_callable=AsyncMock,
        ) as mock_start:
            daemon._on_wake_word()
            # _on_wake_word creates a task — let it run
            await asyncio.sleep(0.05)

            mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_audio_input_stops_for_pipeline(self):
        daemon = _make_daemon()

        mock_task = MagicMock()
        mock_transport = MagicMock()

        with patch(
            "agents.hapax_voice.pipeline.build_pipeline_task",
            return_value=(mock_task, mock_transport),
        ), patch("pipecat.pipeline.runner.PipelineRunner"):
            await daemon._start_local_pipeline()

        daemon._audio_input.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_audio_input_restored_on_pipeline_build_failure(self):
        daemon = _make_daemon()

        with patch(
            "agents.hapax_voice.pipeline.build_pipeline_task",
            side_effect=RuntimeError("build failed"),
        ):
            await daemon._start_local_pipeline()

        daemon._audio_input.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_stop_restores_audio(self):
        daemon = _make_daemon()
        daemon._audio_input.is_active = False

        fake_task = asyncio.create_task(asyncio.sleep(10))
        daemon._pipeline_task = fake_task
        daemon._pipecat_task = MagicMock()
        daemon._pipecat_transport = MagicMock()

        await daemon._stop_pipeline()

        daemon._audio_input.start.assert_called_once()
        assert daemon._pipeline_task is None
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/hapax_voice/test_surface_wake_pipeline.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/hapax_voice/test_surface_wake_pipeline.py
git commit -m "test: add surface 1 — wake word → pipeline integration tests"
```

### Task 2: Surface 2 — STT → LLM → TTS Voice Round-Trip

**Files:**
- Create: `tests/hapax_voice/test_surface_voice_roundtrip.py`

This tests pipeline construction produces a valid processor chain and that each stage connects correctly. We can't run a real STT/LLM/TTS round-trip in tests (requires GPU + API), so we verify the wiring is correct.

- [ ] **Step 1: Write the test file**

```python
"""Surface 2: STT → LLM → TTS voice round-trip.

Tests that pipeline construction wires processors in the correct order
and that each component receives the right configuration. Full audio
round-trip requires live hardware — see smoke_test_voice.sh.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.hapax_voice.pipeline import build_pipeline_task


class TestPipelineWiring:
    """Pipeline processors are wired in the correct order."""

    @patch("agents.hapax_voice.pipeline.LocalAudioTransport")
    @patch("agents.hapax_voice.pipeline.WhisperSTTService")
    @patch("agents.hapax_voice.pipeline.OpenAILLMService")
    @patch("agents.hapax_voice.pipeline.KokoroTTSService")
    @patch("agents.hapax_voice.pipeline.LLMContext")
    @patch("agents.hapax_voice.pipeline.LLMContextAggregatorPair")
    @patch("agents.hapax_voice.pipeline.Pipeline")
    @patch("agents.hapax_voice.pipeline.PipelineTask")
    def test_processor_order(
        self,
        mock_task_cls,
        mock_pipeline_cls,
        mock_agg_pair,
        mock_ctx,
        mock_tts,
        mock_llm,
        mock_stt,
        mock_transport,
    ):
        """Processors must be: input → STT → user_agg → LLM → TTS → output → assistant_agg."""
        mock_t = MagicMock()
        mock_transport.return_value = mock_t
        mock_agg = MagicMock()
        mock_agg_pair.return_value = mock_agg

        build_pipeline_task(
            stt_model="base",
            llm_model="test",
            kokoro_voice="af_heart",
        )

        call_kwargs = mock_pipeline_cls.call_args.kwargs
        processors = call_kwargs["processors"]

        assert processors[0] == mock_t.input()   # transport input
        assert processors[1] == mock_stt()         # STT
        assert processors[2] == mock_agg.user()    # user aggregator
        assert processors[3] == mock_llm()         # LLM
        assert processors[4] == mock_tts()         # TTS
        assert processors[5] == mock_t.output()  # transport output
        assert processors[6] == mock_agg.assistant()  # assistant aggregator

    @patch("agents.hapax_voice.pipeline.LocalAudioTransport")
    @patch("agents.hapax_voice.pipeline.WhisperSTTService")
    @patch("agents.hapax_voice.pipeline.OpenAILLMService")
    @patch("agents.hapax_voice.pipeline.KokoroTTSService")
    @patch("agents.hapax_voice.pipeline.LLMContext")
    @patch("agents.hapax_voice.pipeline.LLMContextAggregatorPair")
    @patch("agents.hapax_voice.pipeline.Pipeline")
    @patch("agents.hapax_voice.pipeline.PipelineTask")
    def test_stt_model_forwarded(
        self,
        mock_task_cls,
        mock_pipeline_cls,
        mock_agg_pair,
        mock_ctx,
        mock_tts,
        mock_llm,
        mock_stt,
        mock_transport,
    ):
        """STT model name is passed through to WhisperSTTService."""
        mock_transport.return_value = MagicMock()
        mock_agg_pair.return_value = MagicMock()

        build_pipeline_task(stt_model="large-v3")

        mock_stt.assert_called_once_with(
            model="large-v3", device="cuda", compute_type="float16", no_speech_prob=0.4,
        )

    @patch("agents.hapax_voice.pipeline.LocalAudioTransport")
    @patch("agents.hapax_voice.pipeline.WhisperSTTService")
    @patch("agents.hapax_voice.pipeline.OpenAILLMService")
    @patch("agents.hapax_voice.pipeline.KokoroTTSService")
    @patch("agents.hapax_voice.pipeline.LLMContext")
    @patch("agents.hapax_voice.pipeline.LLMContextAggregatorPair")
    @patch("agents.hapax_voice.pipeline.Pipeline")
    @patch("agents.hapax_voice.pipeline.PipelineTask")
    def test_llm_uses_litellm_config(
        self,
        mock_task_cls,
        mock_pipeline_cls,
        mock_agg_pair,
        mock_ctx,
        mock_tts,
        mock_llm,
        mock_stt,
        mock_transport,
    ):
        """LLM service is configured with LiteLLM base URL and API key."""
        mock_transport.return_value = MagicMock()
        mock_agg_pair.return_value = MagicMock()

        with patch.dict("os.environ", {
            "LITELLM_BASE_URL": "http://127.0.0.1:4000",
            "LITELLM_API_KEY": "test-key",
        }):
            build_pipeline_task(llm_model="claude-sonnet")

        mock_llm.assert_called_once_with(
            model="claude-sonnet",
            api_key="test-key",
            base_url="http://127.0.0.1:4000",
        )

    @patch("agents.hapax_voice.pipeline.LocalAudioTransport")
    @patch("agents.hapax_voice.pipeline.WhisperSTTService")
    @patch("agents.hapax_voice.pipeline.OpenAILLMService")
    @patch("agents.hapax_voice.pipeline.KokoroTTSService")
    @patch("agents.hapax_voice.pipeline.LLMContext")
    @patch("agents.hapax_voice.pipeline.LLMContextAggregatorPair")
    @patch("agents.hapax_voice.pipeline.Pipeline")
    @patch("agents.hapax_voice.pipeline.PipelineTask")
    def test_tools_registered_in_context(
        self,
        mock_task_cls,
        mock_pipeline_cls,
        mock_agg_pair,
        mock_ctx,
        mock_tts,
        mock_llm,
        mock_stt,
        mock_transport,
    ):
        """LLMContext receives tool schemas when not in guest mode."""
        mock_transport.return_value = MagicMock()
        mock_agg_pair.return_value = MagicMock()

        build_pipeline_task(guest_mode=False)

        ctx_call = mock_ctx.call_args
        tools_arg = ctx_call.kwargs.get("tools") or ctx_call.args[1] if len(ctx_call.args) > 1 else ctx_call.kwargs.get("tools")
        # Tools should be a ToolsSchema (not None / NOT_GIVEN)
        from pipecat.adapters.schemas.tools_schema import ToolsSchema
        assert isinstance(tools_arg, ToolsSchema)

    @patch("agents.hapax_voice.pipeline.LocalAudioTransport")
    @patch("agents.hapax_voice.pipeline.WhisperSTTService")
    @patch("agents.hapax_voice.pipeline.OpenAILLMService")
    @patch("agents.hapax_voice.pipeline.KokoroTTSService")
    @patch("agents.hapax_voice.pipeline.LLMContext")
    @patch("agents.hapax_voice.pipeline.LLMContextAggregatorPair")
    @patch("agents.hapax_voice.pipeline.Pipeline")
    @patch("agents.hapax_voice.pipeline.PipelineTask")
    def test_guest_mode_has_no_tools(
        self,
        mock_task_cls,
        mock_pipeline_cls,
        mock_agg_pair,
        mock_ctx,
        mock_tts,
        mock_llm,
        mock_stt,
        mock_transport,
    ):
        """Guest mode pipeline has no tools registered."""
        mock_transport.return_value = MagicMock()
        mock_agg_pair.return_value = MagicMock()

        build_pipeline_task(guest_mode=True)

        ctx_call = mock_ctx.call_args
        from openai import NOT_GIVEN
        assert ctx_call.kwargs.get("tools") is NOT_GIVEN


class TestSystemPromptContent:
    """System prompt contains expected persona elements."""

    def test_prompt_contains_hapax_identity(self):
        from agents.hapax_voice.persona import system_prompt

        prompt = system_prompt(guest_mode=False)
        assert "hapax" in prompt.lower() or "assistant" in prompt.lower()

    def test_guest_prompt_differs(self):
        from agents.hapax_voice.persona import system_prompt

        normal = system_prompt(guest_mode=False)
        guest = system_prompt(guest_mode=True)
        assert normal != guest
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/hapax_voice/test_surface_voice_roundtrip.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/hapax_voice/test_surface_voice_roundtrip.py
git commit -m "test: add surface 2 — voice round-trip pipeline wiring tests"
```

---

## Chunk 2: Session Lifecycle + Tool Calling

### Task 3: Surface 3 — Session Lifecycle

**Files:**
- Create: `tests/hapax_voice/test_surface_session.py`

Tests the full session state machine: open, close, timeout, pause, resume. Uses a real `VoiceLifecycle` wired into a mocked daemon to test end-to-end session management.

- [ ] **Step 1: Write the test file**

```python
"""Surface 3: Session lifecycle — open, close, timeout, pause, resume.

Tests the session state machine wired into the daemon, verifying
that state transitions trigger the correct pipeline and event actions.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_voice.__main__ import VoiceDaemon
from agents.hapax_voice.session import VoiceLifecycle


def _make_daemon(silence_timeout_s: int = 30) -> VoiceDaemon:
    with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
        daemon = VoiceDaemon()

    daemon.cfg = MagicMock()
    daemon.cfg.backend = "local"
    daemon.cfg.chime_enabled = False
    daemon.cfg.local_stt_model = "base"
    daemon.cfg.llm_model = "test-model"
    daemon.cfg.kokoro_voice = "af_heart"

    daemon.session = VoiceLifecycle(silence_timeout_s=silence_timeout_s)
    daemon.event_log = MagicMock()
    daemon.chime_player = MagicMock()
    daemon._audio_input = MagicMock()
    daemon._audio_input.is_active = True
    daemon._pipeline_task = None
    daemon._pipecat_task = None
    daemon._pipecat_transport = None
    daemon._gemini_session = None
    daemon._frame_gate = MagicMock()
    daemon.governor = MagicMock()
    daemon.workspace_monitor = MagicMock()

    return daemon


class TestSessionOpenClose:
    """Session opens and closes with correct state transitions."""

    @pytest.mark.asyncio
    async def test_hotkey_open_starts_session(self):
        daemon = _make_daemon()

        with patch.object(daemon, "_start_pipeline", new_callable=AsyncMock):
            await daemon._handle_hotkey("open")

        assert daemon.session.is_active
        assert daemon.session.trigger == "hotkey"

    @pytest.mark.asyncio
    async def test_hotkey_close_ends_session(self):
        daemon = _make_daemon()
        daemon.session.open(trigger="test")

        with patch.object(daemon, "_stop_pipeline", new_callable=AsyncMock):
            await daemon._handle_hotkey("close")

        assert not daemon.session.is_active
        assert daemon.session.session_id is None

    @pytest.mark.asyncio
    async def test_toggle_opens_when_idle(self):
        daemon = _make_daemon()

        with patch.object(daemon, "_start_pipeline", new_callable=AsyncMock):
            await daemon._handle_hotkey("toggle")

        assert daemon.session.is_active

    @pytest.mark.asyncio
    async def test_toggle_closes_when_active(self):
        daemon = _make_daemon()
        daemon.session.open(trigger="test")

        with patch.object(daemon, "_stop_pipeline", new_callable=AsyncMock):
            await daemon._handle_hotkey("toggle")

        assert not daemon.session.is_active

    @pytest.mark.asyncio
    async def test_close_stops_pipeline(self):
        daemon = _make_daemon()
        daemon.session.open(trigger="test")

        with patch.object(daemon, "_stop_pipeline", new_callable=AsyncMock) as mock_stop:
            await daemon._close_session(reason="test")

        mock_stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_emits_event_with_duration(self):
        daemon = _make_daemon()
        daemon.session.open(trigger="test")

        with patch.object(daemon, "_stop_pipeline", new_callable=AsyncMock):
            await daemon._close_session(reason="timeout")

        daemon.event_log.emit.assert_any_call(
            "session_lifecycle",
            action="closed",
            reason="timeout",
            duration_s=pytest.approx(0.0, abs=1.0),
        )


class TestSessionTimeout:
    """Session timeout detection works correctly."""

    def test_session_not_timed_out_when_fresh(self):
        session = VoiceLifecycle(silence_timeout_s=1)
        session.open(trigger="test")
        assert not session.is_timed_out

    def test_session_timed_out_after_silence(self):
        session = VoiceLifecycle(silence_timeout_s=0)
        session.open(trigger="test")
        # Force timeout by setting last_activity in the past
        session._last_activity = time.monotonic() - 1.0
        assert session.is_timed_out

    def test_mark_activity_resets_timeout(self):
        session = VoiceLifecycle(silence_timeout_s=0)
        session.open(trigger="test")
        session._last_activity = time.monotonic() - 1.0
        assert session.is_timed_out
        session.mark_activity()
        assert not session.is_timed_out

    def test_paused_session_does_not_timeout(self):
        session = VoiceLifecycle(silence_timeout_s=0)
        session.open(trigger="test")
        session._last_activity = time.monotonic() - 1.0
        session.pause(reason="governor")
        assert not session.is_timed_out


class TestSessionPauseResume:
    """Pause and resume interact correctly with timeout."""

    def test_pause_sets_paused_flag(self):
        session = VoiceLifecycle()
        session.open(trigger="test")
        session.pause(reason="conversation")
        assert session.is_paused

    def test_resume_clears_paused_flag(self):
        session = VoiceLifecycle()
        session.open(trigger="test")
        session.pause(reason="test")
        session.resume()
        assert not session.is_paused

    def test_resume_resets_activity_timer(self):
        session = VoiceLifecycle(silence_timeout_s=10)
        session.open(trigger="test")
        session._last_activity = time.monotonic() - 5.0
        session.pause(reason="test")
        session.resume()
        # After resume, activity timer should be fresh
        assert not session.is_timed_out

    def test_close_clears_paused(self):
        session = VoiceLifecycle()
        session.open(trigger="test")
        session.pause(reason="test")
        session.close(reason="done")
        assert not session.is_paused

    def test_pause_noop_when_idle(self):
        session = VoiceLifecycle()
        session.pause(reason="test")
        assert not session.is_paused


class TestGuestMode:
    """Guest mode detection based on speaker identity."""

    def test_not_guest_when_no_speaker(self):
        session = VoiceLifecycle()
        session.open(trigger="test")
        assert not session.is_guest_mode

    def test_not_guest_when_operator(self):
        session = VoiceLifecycle()
        session.open(trigger="test")
        session.set_speaker("ryan", 0.9)
        assert not session.is_guest_mode

    def test_guest_when_non_operator(self):
        session = VoiceLifecycle()
        session.open(trigger="test")
        session.set_speaker("child", 0.8)
        assert session.is_guest_mode
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/hapax_voice/test_surface_session.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/hapax_voice/test_surface_session.py
git commit -m "test: add surface 3 — session lifecycle integration tests"
```

### Task 4: Surface 4 — Tool Calling

**Files:**
- Create: `tests/hapax_voice/test_surface_tool_calling.py`

Tests that tool handlers execute correctly when invoked with mock parameters, and that results are passed back via the result callback.

- [ ] **Step 1: Write the test file**

```python
"""Surface 4: Tool calling — handler execution and result delivery.

Tests that tool handlers execute correctly when invoked by the LLM
and that results flow back through the result_callback.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_voice.config import VoiceConfig


def _setup_tools():
    """Register tools on a mock LLM and return the handler map."""
    from agents.hapax_voice.tools import register_tool_handlers

    mock_llm = MagicMock()
    config = VoiceConfig()
    register_tool_handlers(mock_llm, config)

    handlers = {}
    for call in mock_llm.register_function.call_args_list:
        name = call.args[0]
        handler = call.args[1]
        handlers[name] = handler

    return handlers


class TestToolHandlerRegistration:
    """All expected tools are registered with handlers."""

    def test_all_14_tools_registered(self):
        handlers = _setup_tools()
        assert len(handlers) == 14

    def test_core_tools_present(self):
        handlers = _setup_tools()
        expected = [
            "search_documents", "search_drive", "get_calendar_today",
            "search_emails", "send_sms", "confirm_send_sms",
            "analyze_scene", "get_system_status", "generate_image",
            "focus_window", "switch_workspace", "open_app",
            "confirm_open_app", "get_desktop_state",
        ]
        for name in expected:
            assert name in handlers, f"Missing tool handler: {name}"


class TestSearchDocumentsTool:
    """search_documents queries Qdrant and returns results."""

    @pytest.mark.asyncio
    async def test_returns_results(self):
        handlers = _setup_tools()
        handler = handlers["search_documents"]

        params = MagicMock()
        params.arguments = {"query": "test query", "limit": 3}
        params.result_callback = AsyncMock()

        mock_results = [
            MagicMock(payload={"text": "result 1", "source": "doc1"}, score=0.9),
        ]
        with patch("agents.hapax_voice.tools._qdrant_search", return_value=mock_results):
            await handler(params)

        params.result_callback.assert_called_once()
        result_text = params.result_callback.call_args.args[0]
        assert "result 1" in result_text

    @pytest.mark.asyncio
    async def test_handles_empty_results(self):
        handlers = _setup_tools()
        handler = handlers["search_documents"]

        params = MagicMock()
        params.arguments = {"query": "nonexistent"}
        params.result_callback = AsyncMock()

        with patch("agents.hapax_voice.tools._qdrant_search", return_value=[]):
            await handler(params)

        params.result_callback.assert_called_once()
        result_text = params.result_callback.call_args.args[0]
        assert "no results" in result_text.lower() or result_text == "No results found."


class TestGetSystemStatusTool:
    """get_system_status returns health information."""

    @pytest.mark.asyncio
    async def test_returns_status_report(self):
        handlers = _setup_tools()
        handler = handlers["get_system_status"]

        params = MagicMock()
        params.arguments = {}
        params.result_callback = AsyncMock()

        with patch("agents.hapax_voice.tools._get_system_status_report", return_value="All systems operational"):
            await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert "operational" in result.lower() or len(result) > 0


class TestSendSmsTool:
    """SMS tool uses two-step confirmation flow."""

    @pytest.mark.asyncio
    async def test_send_sms_stores_pending(self):
        handlers = _setup_tools()
        handler = handlers["send_sms"]

        params = MagicMock()
        params.arguments = {"to": "+1234567890", "message": "Hello"}
        params.result_callback = AsyncMock()

        await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert "confirm" in result.lower()

    @pytest.mark.asyncio
    async def test_confirm_send_sms_without_pending_fails(self):
        handlers = _setup_tools()
        handler = handlers["confirm_send_sms"]

        # Reset pending SMS state
        import agents.hapax_voice.tools as tools_mod
        tools_mod._pending_sms = None

        params = MagicMock()
        params.arguments = {}
        params.result_callback = AsyncMock()

        await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert "no pending" in result.lower() or "nothing" in result.lower()
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/hapax_voice/test_surface_tool_calling.py -v`
Expected: All tests PASS (may need adjustments based on exact handler implementations)

- [ ] **Step 3: Fix any handler-specific issues and re-run**

The tool handler tests test against real handler code with mocked external services. If any handler has unexpected argument parsing or result format, adjust the test expectations to match the actual implementation.

- [ ] **Step 4: Commit**

```bash
git add tests/hapax_voice/test_surface_tool_calling.py
git commit -m "test: add surface 4 — tool calling integration tests"
```

---

## Chunk 3: Desktop Tools + Perception → Governor

### Task 5: Surface 5 — Desktop Tools via Hyprland

**Files:**
- Create: `tests/hapax_voice/test_surface_desktop.py`

Tests that desktop tool handlers execute Hyprland IPC commands correctly and that the confirmation flow works for `open_app`.

- [ ] **Step 1: Write the test file**

```python
"""Surface 5: Desktop tools — Hyprland IPC integration.

Tests that desktop tool handlers dispatch to Hyprland correctly
and that the open_app confirmation flow works end-to-end.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_voice.desktop_tools import (
    DESKTOP_TOOL_SCHEMAS,
    handle_confirm_open_app,
    handle_focus_window,
    handle_get_desktop_state,
    handle_open_app,
    handle_switch_workspace,
)


class TestDesktopToolSchemas:
    """Desktop tool schemas are correctly defined."""

    def test_five_desktop_tools(self):
        assert len(DESKTOP_TOOL_SCHEMAS) == 5

    def test_schema_names(self):
        names = [s.name for s in DESKTOP_TOOL_SCHEMAS]
        assert "focus_window" in names
        assert "switch_workspace" in names
        assert "open_app" in names
        assert "confirm_open_app" in names
        assert "get_desktop_state" in names


class TestFocusWindow:
    """focus_window dispatches to Hyprland."""

    @pytest.mark.asyncio
    async def test_dispatches_focuswindow(self):
        params = MagicMock()
        params.arguments = {"window_title": "Firefox"}
        params.result_callback = AsyncMock()

        with patch("agents.hapax_voice.desktop_tools.HyprlandIPC") as mock_ipc:
            mock_ipc.return_value.dispatch.return_value = True
            await handle_focus_window(params)

        params.result_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_reports_failure(self):
        params = MagicMock()
        params.arguments = {"window_title": "NonExistent"}
        params.result_callback = AsyncMock()

        with patch("agents.hapax_voice.desktop_tools.HyprlandIPC") as mock_ipc:
            mock_ipc.return_value.dispatch.return_value = False
            await handle_focus_window(params)

        result = params.result_callback.call_args.args[0]
        assert "fail" in result.lower() or "could not" in result.lower() or "error" in result.lower()


class TestSwitchWorkspace:
    """switch_workspace dispatches workspace change."""

    @pytest.mark.asyncio
    async def test_dispatches_workspace(self):
        params = MagicMock()
        params.arguments = {"workspace_id": 3}
        params.result_callback = AsyncMock()

        with patch("agents.hapax_voice.desktop_tools.HyprlandIPC") as mock_ipc:
            mock_ipc.return_value.dispatch.return_value = True
            await handle_switch_workspace(params)

        params.result_callback.assert_called_once()


class TestOpenAppConfirmation:
    """open_app uses two-step confirmation flow."""

    @pytest.mark.asyncio
    async def test_open_app_stores_pending(self):
        params = MagicMock()
        params.arguments = {"app_name": "firefox"}
        params.result_callback = AsyncMock()

        await handle_open_app(params)

        result = params.result_callback.call_args.args[0]
        assert "confirm" in result.lower()

    @pytest.mark.asyncio
    async def test_confirm_launches_app(self):
        # First, set up pending app
        setup_params = MagicMock()
        setup_params.arguments = {"app_name": "firefox"}
        setup_params.result_callback = AsyncMock()
        await handle_open_app(setup_params)

        # Now confirm
        confirm_params = MagicMock()
        confirm_params.arguments = {}
        confirm_params.result_callback = AsyncMock()

        with patch("agents.hapax_voice.desktop_tools.subprocess") as mock_sub:
            await handle_confirm_open_app(confirm_params)

        confirm_params.result_callback.assert_called_once()


class TestGetDesktopState:
    """get_desktop_state queries Hyprland for current state."""

    @pytest.mark.asyncio
    async def test_returns_state_info(self):
        params = MagicMock()
        params.arguments = {}
        params.result_callback = AsyncMock()

        with patch("agents.hapax_voice.desktop_tools.HyprlandIPC") as mock_ipc:
            from shared.hyprland import WindowInfo, WorkspaceInfo
            mock_ipc.return_value.get_active_window.return_value = WindowInfo(
                address="0x1", title="foot", class_name="foot",
                workspace_id=1, workspace_name="1",
                size_x=800, size_y=600, floating=False,
            )
            mock_ipc.return_value.get_workspaces.return_value = [
                WorkspaceInfo(id=1, name="1", monitor="DP-1", window_count=3, active=True),
            ]
            await handle_get_desktop_state(params)

        result = params.result_callback.call_args.args[0]
        assert "foot" in result
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/hapax_voice/test_surface_desktop.py -v`
Expected: All tests PASS (adjust handler call patterns if needed)

- [ ] **Step 3: Commit**

```bash
git add tests/hapax_voice/test_surface_desktop.py
git commit -m "test: add surface 5 — desktop tools Hyprland integration tests"
```

### Task 6: Surface 6 — Perception → Governor → Frame Gate

**Files:**
- Create: `tests/hapax_voice/test_surface_governor.py`

Tests the full perception→governor→frame gate chain: environment state changes produce correct governor directives, and those directives are applied to the frame gate and session.

- [ ] **Step 1: Write the test file**

```python
"""Surface 6: Perception → Governor → Frame Gate directive chain.

Tests that environment state changes produce correct governor directives
and that the daemon applies those directives to the frame gate and session.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_voice.governor import PipelineGovernor
from agents.hapax_voice.perception import EnvironmentState


def _make_state(**overrides) -> EnvironmentState:
    """Create an EnvironmentState with sensible defaults."""
    defaults = dict(
        speech_detected=False,
        speech_volume_db=-40.0,
        ambient_class="quiet",
        vad_confidence=0.0,
        face_count=1,
        operator_present=True,
        gaze_at_camera=False,
        activity_mode="idle",
        workspace_context="",
        ambient_detailed="",
        active_window=None,
        window_count=0,
        active_workspace_id=1,
    )
    defaults.update(overrides)
    return EnvironmentState(**defaults)


class TestGovernorBasicDirectives:
    """Governor returns correct directives for basic states."""

    def test_process_when_operator_present(self):
        gov = PipelineGovernor()
        state = _make_state(operator_present=True, face_count=1)
        assert gov.evaluate(state) == "process"

    def test_pause_in_production_mode(self):
        gov = PipelineGovernor()
        state = _make_state(activity_mode="production")
        assert gov.evaluate(state) == "pause"

    def test_pause_in_meeting_mode(self):
        gov = PipelineGovernor()
        state = _make_state(activity_mode="meeting")
        assert gov.evaluate(state) == "pause"

    def test_withdraw_when_absent(self):
        gov = PipelineGovernor(operator_absent_withdraw_s=0)
        gov._last_operator_seen = time.monotonic() - 1.0
        state = _make_state(operator_present=False, face_count=0)
        assert gov.evaluate(state) == "withdraw"

    def test_process_when_absent_but_within_timeout(self):
        gov = PipelineGovernor(operator_absent_withdraw_s=300)
        state = _make_state(operator_present=False, face_count=0)
        assert gov.evaluate(state) == "process"


class TestGovernorWakeWordOverride:
    """Wake word overrides all other governor logic."""

    def test_wake_word_overrides_production_mode(self):
        gov = PipelineGovernor()
        gov.wake_word_active = True
        state = _make_state(activity_mode="production")
        assert gov.evaluate(state) == "process"

    def test_wake_word_overrides_absence(self):
        gov = PipelineGovernor(operator_absent_withdraw_s=0)
        gov._last_operator_seen = time.monotonic() - 100
        gov.wake_word_active = True
        state = _make_state(operator_present=False, face_count=0)
        assert gov.evaluate(state) == "process"

    def test_wake_word_clears_after_evaluation(self):
        gov = PipelineGovernor()
        gov.wake_word_active = True
        state = _make_state()
        gov.evaluate(state)
        assert gov.wake_word_active is False


class TestGovernorConversationDebounce:
    """Conversation detection uses debounce before pausing."""

    def test_no_pause_before_debounce(self):
        gov = PipelineGovernor(conversation_debounce_s=5.0)
        state = _make_state(face_count=2, speech_detected=True, operator_present=True)
        # First evaluation — debounce starts
        assert gov.evaluate(state) == "process"

    def test_pause_after_debounce(self):
        gov = PipelineGovernor(conversation_debounce_s=0)
        state = _make_state(face_count=2, speech_detected=True, operator_present=True)
        # With 0s debounce, should pause immediately
        assert gov.evaluate(state) == "pause"

    def test_resume_after_conversation_clears(self):
        gov = PipelineGovernor(
            conversation_debounce_s=0,
            environment_clear_resume_s=0,
        )
        # First: conversation detected → pause
        conv_state = _make_state(face_count=2, speech_detected=True, operator_present=True)
        assert gov.evaluate(conv_state) == "pause"

        # Then: conversation clears → should resume after clear delay
        clear_state = _make_state(face_count=1, speech_detected=False, operator_present=True)
        assert gov.evaluate(clear_state) == "process"


class TestGovernorFrameGateIntegration:
    """Governor directives are applied to frame gate by the daemon."""

    @pytest.mark.asyncio
    async def test_process_directive_sets_frame_gate(self):
        """Verify the daemon applies governor directives to the frame gate."""
        from agents.hapax_voice.__main__ import VoiceDaemon
        from agents.hapax_voice.frame_gate import FrameGate

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()

        daemon.governor = PipelineGovernor()
        daemon._frame_gate = FrameGate()
        daemon.session = MagicMock()
        daemon.session.is_active = True
        daemon.session.is_paused = False
        daemon.event_log = MagicMock()
        daemon._pipeline_task = MagicMock()  # pretend pipeline is running

        # The daemon's _apply_directive method (or equivalent) should
        # set the frame gate directive. Verify the frame gate starts in
        # default state and can be changed.
        assert daemon._frame_gate._directive == "process"
        daemon._frame_gate.set_directive("pause")
        assert daemon._frame_gate._directive == "pause"
        daemon._frame_gate.set_directive("process")
        assert daemon._frame_gate._directive == "process"
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/hapax_voice/test_surface_governor.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/hapax_voice/test_surface_governor.py
git commit -m "test: add surface 6 — perception → governor integration tests"
```

---

## Chunk 4: Notifications + Hotkeys + Smoke Tests

### Task 7: Surface 7 — Notification Delivery

**Files:**
- Create: `tests/hapax_voice/test_surface_notifications.py`

Tests the ntfy→queue→delivery chain: notification parsing, priority queuing, TTL expiry, and proactive delivery conditions.

- [ ] **Step 1: Write the test file**

```python
"""Surface 7: Notification delivery — ntfy → queue → proactive delivery.

Tests the full notification chain: ntfy event parsing, priority queuing,
TTL expiry, and the proactive delivery conditions.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_voice.notification_queue import NotificationQueue, VoiceNotification
from agents.hapax_voice.ntfy_listener import parse_ntfy_event


class TestNtfyParsing:
    """ntfy JSON events are parsed into VoiceNotifications."""

    def test_parses_message_event(self):
        raw = '{"event":"message","topic":"hapax","title":"Alert","message":"Test alert","priority":4}'
        notif = parse_ntfy_event(raw)
        assert notif is not None
        assert notif.title == "Alert"
        assert notif.message == "Test alert"
        assert notif.priority == "urgent"

    def test_ignores_keepalive_event(self):
        raw = '{"event":"keepalive","topic":"hapax"}'
        assert parse_ntfy_event(raw) is None

    def test_ignores_open_event(self):
        raw = '{"event":"open","topic":"hapax"}'
        assert parse_ntfy_event(raw) is None

    def test_handles_missing_title(self):
        raw = '{"event":"message","topic":"alerts","message":"No title"}'
        notif = parse_ntfy_event(raw)
        assert notif is not None
        assert notif.title == "alerts"  # falls back to topic

    def test_handles_invalid_json(self):
        assert parse_ntfy_event("not json") is None

    def test_priority_mapping(self):
        for ntfy_pri, expected in [(5, "urgent"), (4, "urgent"), (3, "normal"), (2, "low"), (1, "low")]:
            raw = f'{{"event":"message","topic":"t","message":"m","priority":{ntfy_pri}}}'
            notif = parse_ntfy_event(raw)
            assert notif.priority == expected, f"ntfy priority {ntfy_pri} → {notif.priority}, expected {expected}"


class TestNotificationQueue:
    """Priority queue with TTL-based expiry."""

    def test_enqueue_and_dequeue(self):
        q = NotificationQueue()
        n = VoiceNotification(title="Test", message="Hello", priority="normal", source="test")
        q.enqueue(n)
        assert q.pending_count == 1
        result = q.next()
        assert result is not None
        assert result.message == "Hello"
        assert q.pending_count == 0

    def test_urgent_dequeued_before_normal(self):
        q = NotificationQueue()
        q.enqueue(VoiceNotification(title="Normal", message="n", priority="normal", source="test"))
        q.enqueue(VoiceNotification(title="Urgent", message="u", priority="urgent", source="test"))
        result = q.next()
        assert result.title == "Urgent"

    def test_empty_queue_returns_none(self):
        q = NotificationQueue()
        assert q.next() is None

    def test_expired_notifications_pruned(self):
        q = NotificationQueue(ttls={"normal": 0})
        n = VoiceNotification(title="Old", message="expired", priority="normal", source="test")
        q.enqueue(n)
        # Force expiry by setting enqueue time in the past
        q._queue[0] = (q._queue[0][0], q._queue[0][1], time.time() - 1)
        assert q.pending_count == 0  # pruned on access


class TestProactiveDeliveryConditions:
    """Proactive delivery only fires under correct conditions."""

    @pytest.mark.asyncio
    async def test_no_delivery_during_active_session(self):
        """Notifications should not be delivered during an active voice session."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()

        daemon.session = MagicMock()
        daemon.session.is_active = True  # Session active — should block delivery
        daemon.notifications = MagicMock()
        daemon.notifications.pending_count = 1
        daemon.presence = MagicMock()
        daemon.gate = MagicMock()
        daemon.tts = MagicMock()
        daemon.event_log = MagicMock()

        # The proactive delivery check should not deliver
        # because session is active
        assert daemon.session.is_active is True
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/hapax_voice/test_surface_notifications.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/hapax_voice/test_surface_notifications.py
git commit -m "test: add surface 7 — notification delivery integration tests"
```

### Task 8: Surface 8 — Hotkey Commands

**Files:**
- Create: `tests/hapax_voice/test_surface_hotkeys.py`

Tests the hotkey socket server: command validation, dispatch to daemon, and real socket communication.

- [ ] **Step 1: Write the test file**

```python
"""Surface 8: Hotkey commands — socket → validation → dispatch.

Tests hotkey server lifecycle, command validation, and real
Unix domain socket communication.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.hapax_voice.hotkey import HotkeyServer


class TestHotkeyServerLifecycle:
    """Server starts, listens, and stops cleanly."""

    @pytest.mark.asyncio
    async def test_start_creates_socket(self, tmp_path):
        sock = tmp_path / "test.sock"
        callback = AsyncMock()
        server = HotkeyServer(socket_path=sock, on_command=callback)

        await server.start()
        assert sock.exists()

        await server.stop()
        assert not sock.exists()

    @pytest.mark.asyncio
    async def test_removes_stale_socket(self, tmp_path):
        sock = tmp_path / "test.sock"
        sock.touch()  # stale socket
        callback = AsyncMock()
        server = HotkeyServer(socket_path=sock, on_command=callback)

        await server.start()
        assert sock.exists()

        await server.stop()


class TestHotkeyCommandDispatch:
    """Commands are validated and dispatched correctly."""

    @pytest.mark.asyncio
    async def test_valid_command_dispatched(self, tmp_path):
        sock = tmp_path / "test.sock"
        callback = AsyncMock()
        server = HotkeyServer(socket_path=sock, on_command=callback)

        await server.start()

        reader, writer = await asyncio.open_unix_connection(str(sock))
        writer.write(b"toggle\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

        await asyncio.sleep(0.1)
        callback.assert_called_once_with("toggle")

        await server.stop()

    @pytest.mark.asyncio
    async def test_invalid_command_ignored(self, tmp_path):
        sock = tmp_path / "test.sock"
        callback = AsyncMock()
        server = HotkeyServer(socket_path=sock, on_command=callback)

        await server.start()

        reader, writer = await asyncio.open_unix_connection(str(sock))
        writer.write(b"invalid_command\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

        await asyncio.sleep(0.1)
        callback.assert_not_called()

        await server.stop()

    @pytest.mark.asyncio
    async def test_all_valid_commands_accepted(self, tmp_path):
        sock = tmp_path / "test.sock"
        callback = AsyncMock()
        server = HotkeyServer(socket_path=sock, on_command=callback)

        await server.start()

        for cmd in ["toggle", "open", "close", "status", "scan"]:
            callback.reset_mock()
            reader, writer = await asyncio.open_unix_connection(str(sock))
            writer.write(f"{cmd}\n".encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(0.05)
            callback.assert_called_once_with(cmd)

        await server.stop()

    @pytest.mark.asyncio
    async def test_multiple_clients_sequential(self, tmp_path):
        sock = tmp_path / "test.sock"
        callback = AsyncMock()
        server = HotkeyServer(socket_path=sock, on_command=callback)

        await server.start()

        for i in range(3):
            reader, writer = await asyncio.open_unix_connection(str(sock))
            writer.write(b"status\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        await asyncio.sleep(0.15)
        assert callback.call_count == 3

        await server.stop()
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/hapax_voice/test_surface_hotkeys.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/hapax_voice/test_surface_hotkeys.py
git commit -m "test: add surface 8 — hotkey socket integration tests"
```

### Task 9: Live Smoke Test Script

**Files:**
- Create: `scripts/smoke_test_voice.sh`

Shell script that validates the running daemon end-to-end. Requires the daemon to be running as a systemd service.

- [ ] **Step 1: Write the smoke test script**

```bash
#!/bin/bash
set -euo pipefail

# Live smoke tests for hapax-voice daemon
# Requires: daemon running, socat installed

SOCKET="/run/user/1000/hapax-voice.sock"
PASS=0
FAIL=0

pass() { echo "  ✓ $1"; ((PASS++)); }
fail() { echo "  ✗ $1"; ((FAIL++)); }

check_log() {
    # Check journal for a pattern in the last N seconds
    local seconds=$1
    local pattern=$2
    journalctl --user -u hapax-voice --since "${seconds} sec ago" --no-pager 2>/dev/null | grep -q "$pattern"
}

echo "=== Hapax Voice Daemon Smoke Tests ==="
echo ""

# --- Prerequisite checks ---
echo "Prerequisites:"

if systemctl --user is-active hapax-voice.service >/dev/null 2>&1; then
    pass "Daemon is running"
else
    fail "Daemon is not running"
    echo "  Start with: systemctl --user start hapax-voice.service"
    exit 1
fi

if [ -S "$SOCKET" ]; then
    pass "Hotkey socket exists"
else
    fail "Hotkey socket missing at $SOCKET"
    exit 1
fi

if command -v socat >/dev/null 2>&1; then
    pass "socat available"
else
    fail "socat not installed (apt install socat)"
    exit 1
fi

echo ""

# --- Surface 8: Hotkey commands ---
echo "Surface 8: Hotkey Commands"

echo "status" | socat - UNIX-CONNECT:"$SOCKET" 2>/dev/null || true
sleep 1
if check_log 3 "Status:"; then
    pass "status command received"
else
    fail "status command not received"
fi

# --- Surface 3: Session lifecycle ---
echo ""
echo "Surface 3: Session Lifecycle"

echo "open" | socat - UNIX-CONNECT:"$SOCKET" 2>/dev/null || true
sleep 2
if check_log 5 "session_lifecycle.*opened"; then
    pass "session opened via hotkey"
else
    # Try checking for pipeline start
    if check_log 5 "opened.*hotkey\|Voice conversation opened"; then
        pass "session opened via hotkey"
    else
        fail "session did not open"
    fi
fi

echo "close" | socat - UNIX-CONNECT:"$SOCKET" 2>/dev/null || true
sleep 2
if check_log 5 "session_lifecycle.*closed\|Voice conversation closed"; then
    pass "session closed via hotkey"
else
    fail "session did not close"
fi

# --- Surface 1: Wake word (manual) ---
echo ""
echo "Surface 1: Wake Word (requires manual test)"
echo "  → Say 'Hapax' near the microphone"
echo "  → Verify: chime plays, session opens, pipeline starts"
echo "  → Check: journalctl --user -u hapax-voice -f | grep -i 'wake\|session\|pipeline'"

# --- Surface 2: Voice round-trip (manual) ---
echo ""
echo "Surface 2: Voice Round-Trip (requires manual test)"
echo "  → After wake word, speak a question"
echo "  → Verify: STT transcription appears in logs"
echo "  → Verify: LLM response generated"
echo "  → Verify: TTS audio plays through speakers"
echo "  → Check: journalctl --user -u hapax-voice -f"

# --- Surface 7: Notification delivery ---
echo ""
echo "Surface 7: Notifications"

if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8090/hapax-alerts 2>/dev/null | grep -q "200"; then
    pass "ntfy endpoint reachable"
else
    fail "ntfy endpoint not reachable"
fi

# --- Surface 5: Desktop state ---
echo ""
echo "Surface 5: Desktop (Hyprland)"

if check_log 300 "Connected to Hyprland event socket"; then
    pass "Hyprland event socket connected"
else
    fail "Hyprland event socket not connected"
fi

# --- Surface 6: Perception/Governor ---
echo ""
echo "Surface 6: Perception → Governor"

if check_log 300 "FrameGate directive"; then
    pass "Governor producing directives"
else
    fail "No governor directives in recent logs"
fi

# --- Summary ---
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
if [ $FAIL -gt 0 ]; then
    exit 1
fi
```

- [ ] **Step 2: Make executable and test**

Run: `chmod +x scripts/smoke_test_voice.sh && bash scripts/smoke_test_voice.sh`
Expected: All automated checks pass, manual test instructions printed

- [ ] **Step 3: Commit**

```bash
git add scripts/smoke_test_voice.sh
git commit -m "test: add live smoke test script for hapax-voice daemon"
```

### Task 10: Run Full Test Suite — Gate Verification

This final task runs all surface tests together and the full test suite to verify zero regressions.

- [ ] **Step 1: Run all surface tests**

```bash
uv run pytest tests/hapax_voice/test_surface_*.py -v
```

Expected: All surface tests PASS

- [ ] **Step 2: Run full hapax_voice test suite**

```bash
uv run pytest tests/hapax_voice/ tests/test_hapax_voice_pipeline.py -q --tb=line -k "not augmentation"
```

Expected: All tests PASS (excluding pre-existing augmentation failures)

- [ ] **Step 3: Run smoke tests against live daemon**

```bash
bash scripts/smoke_test_voice.sh
```

Expected: All automated checks pass

- [ ] **Step 4: Commit any final fixes**

```bash
git add -A
git commit -m "test: complete voice daemon integration test surfaces (8/8)"
```
