"""Actuation subsystem setup for VoiceDaemon."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger("hapax_daimonion")


def setup_actuation(daemon: VoiceDaemon) -> None:
    """Wire MC/OBS governance -> ScheduleQueue/ExecutorRegistry."""
    if daemon.cfg.mc_enabled:
        try:
            _setup_mc_actuation(daemon)
        except Exception:
            log.exception("MC actuation setup failed")

    if daemon.cfg.obs_enabled:
        try:
            _setup_obs_actuation(daemon)
        except Exception:
            log.exception("OBS actuation setup failed")

    # Feedback behaviors: actuation events -> perception behaviors (closed loop)
    from agents.hapax_daimonion.feedback import wire_feedback_behaviors

    feedback_behaviors = wire_feedback_behaviors(
        actuation_event=daemon.executor_registry.actuation_event,
        watermark=daemon.perception.min_watermark,
    )
    daemon.perception.behaviors.update(feedback_behaviors)
    log.info("Feedback behaviors wired: %s", list(feedback_behaviors.keys()))


def _setup_mc_actuation(daemon: VoiceDaemon) -> None:
    """Wire MC governance pipeline to AudioExecutor."""
    from agents.hapax_daimonion.audio_executor import AudioExecutor
    from agents.hapax_daimonion.commands import Schedule
    from agents.hapax_daimonion.mc_governance import compose_mc_governance
    from agents.hapax_daimonion.primitives import Event
    from agents.hapax_daimonion.sample_bank import SampleBank

    sample_bank = SampleBank(
        base_dir=Path(daemon.cfg.mc_sample_dir).expanduser(),
        sample_rate=daemon.cfg.mc_sample_rate,
    )
    count = sample_bank.load()
    if count == 0:
        log.info("No MC samples found, MC actuation disabled")
        return

    ensure_shared_pa(daemon)

    audio_exec = AudioExecutor(pa=daemon._shared_pa, sample_bank=sample_bank)
    daemon.executor_registry.register(audio_exec)

    midi_backend = daemon.perception.registered_backends.get("midi_clock")
    if midi_backend is None:
        log.info("No MIDI clock backend, MC governance cannot fire")
        return

    mc_tick: Event[float] = Event()
    mc_output = compose_mc_governance(
        trigger=mc_tick,
        behaviors=daemon.perception.behaviors,
    )

    def _on_mc_schedule(timestamp: float, schedule: Schedule | None) -> None:
        if schedule is not None and schedule.command.action != "silence":
            daemon.schedule_queue.enqueue(schedule)
            daemon.event_log.emit(
                "mc_schedule_enqueued",
                action=schedule.command.action,
                wall_time=schedule.wall_time,
            )

    mc_output.subscribe(_on_mc_schedule)
    daemon._mc_tick_event = mc_tick
    log.info("MC actuation wired: MIDI -> governance -> schedule -> audio")


def _setup_obs_actuation(daemon: VoiceDaemon) -> None:
    """Wire OBS governance pipeline to OBSExecutor."""
    from agents.hapax_daimonion.commands import Command
    from agents.hapax_daimonion.obs_executor import OBSExecutor
    from agents.hapax_daimonion.obs_governance import compose_obs_governance
    from agents.hapax_daimonion.primitives import Event

    obs_exec = OBSExecutor(
        host=daemon.cfg.obs_host,
        port=daemon.cfg.obs_port,
    )
    daemon.executor_registry.register(obs_exec)

    obs_tick: Event[float] = Event()
    obs_output = compose_obs_governance(
        trigger=obs_tick,
        behaviors=daemon.perception.behaviors,
    )

    def _on_obs_command(timestamp: float, cmd: Command | None) -> None:
        if cmd is None:
            return
        from agents.hapax_daimonion.arbiter import ResourceClaim
        from agents.hapax_daimonion.resource_config import DEFAULT_PRIORITIES, RESOURCE_MAP

        resource = RESOURCE_MAP.get(cmd.action)
        if resource:
            claim = ResourceClaim(
                resource=resource,
                chain=cmd.trigger_source,
                priority=DEFAULT_PRIORITIES.get((resource, cmd.trigger_source), 0),
                command=cmd,
            )
            daemon.arbiter.claim(claim)
        else:
            daemon.executor_registry.dispatch(cmd)
        daemon.event_log.emit(
            "obs_command_dispatched",
            action=cmd.action,
            transition=cmd.params.get("transition", ""),
        )

    obs_output.subscribe(_on_obs_command)
    daemon._obs_tick_event = obs_tick
    log.info("OBS actuation wired: perception -> governance -> command -> scene")


def ensure_shared_pa(daemon: VoiceDaemon) -> None:
    """Create shared PyAudio instance if not already created."""
    if daemon._shared_pa is not None:
        return
    try:
        import pyaudio

        daemon._shared_pa = pyaudio.PyAudio()
    except Exception:
        log.warning("PyAudio not available, audio executors will be unavailable")
