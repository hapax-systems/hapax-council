"""Consent voice session runner for VoiceDaemon."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger("hapax_daimonion")


async def run_consent_session(daemon: VoiceDaemon) -> None:
    """Run a voice consent session for a detected guest.

    Builds a separate Pipecat pipeline with the consent system prompt
    and consent-only tools. The LLM explains what the system records
    and understands the guest's natural language response.

    Guards:
    - Only runs when main voice session is inactive
    - Sets _consent_session_active flag to prevent concurrent launches
    - Times out after consent_session_timeout_s
    """
    if daemon._consent_session_active:
        return

    daemon._consent_session_active = True
    daemon.event_log.emit("consent_session_start")
    log.info("Starting consent voice session for detected guest")
    consent_state = None

    try:
        from agents.hapax_daimonion.consent_session import (
            CONSENT_SYSTEM_PROMPT,
            CONSENT_TOOL_SCHEMAS,
            build_consent_tools_for_llm,
        )
        from agents.hapax_daimonion.pipeline import _build_llm, _build_stt, _build_tts

        stt = _build_stt(daemon.cfg.local_stt_model)
        llm = _build_llm(daemon.cfg.llm_model, CONSENT_SYSTEM_PROMPT)
        tts = _build_tts(daemon.cfg.tts_voice)

        consent_state = build_consent_tools_for_llm(
            llm,
            consent_tracker=daemon.consent_tracker,
            event_log=daemon.event_log,
        )

        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.pipeline.task import PipelineTask
        from pipecat.processors.aggregators.openai_llm_context import (
            LLMContext,
            LLMContextAggregatorPair,
        )
        from pipecat.transports.local.audio import LocalAudioTransport

        transport = LocalAudioTransport(input_name=daemon.cfg.audio_input_source)
        context = LLMContext(
            messages=[{"role": "system", "content": CONSENT_SYSTEM_PROMPT}],
            tools=CONSENT_TOOL_SCHEMAS,
        )
        context_aggregator = LLMContextAggregatorPair(context)

        pipeline = Pipeline(
            processors=[
                transport.input(),
                stt,
                context_aggregator.user(),
                llm,
                tts,
                transport.output(),
                context_aggregator.assistant(),
            ]
        )

        task = PipelineTask(pipeline)

        from pipecat.pipeline.runner import PipelineRunner

        runner = PipelineRunner()

        async def _run_with_timeout():
            try:
                await asyncio.wait_for(
                    runner.run(task),
                    timeout=daemon.cfg.consent_session_timeout_s,
                )
            except TimeoutError:
                log.info("Consent session timed out — curtailment continues")
                await task.cancel()

        await _run_with_timeout()

        if consent_state.resolved:
            log.info(
                "Consent session resolved: %s (scope: %s)",
                consent_state.decision,
                consent_state.scope,
            )
        else:
            log.info("Consent session ended without resolution")

    except Exception:
        log.exception("Consent session failed (non-fatal, curtailment continues)")
    finally:
        daemon._consent_session_active = False
        daemon.event_log.emit(
            "consent_session_end",
            resolved=getattr(consent_state, "resolved", False)
            if consent_state is not None
            else False,
        )
