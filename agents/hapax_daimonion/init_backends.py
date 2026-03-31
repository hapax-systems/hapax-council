"""Perception backend registration for VoiceDaemon."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger("hapax_daimonion")


def register_perception_backends(daemon: VoiceDaemon) -> None:
    """Instantiate and register available perception backends."""
    try:
        from agents.hapax_daimonion.backends.pipewire import PipeWireBackend

        daemon.perception.register_backend(PipeWireBackend())
    except Exception:
        daemon.degradation_registry.record("backends", "PipeWireBackend", "info", "not available")

    try:
        from agents.hapax_daimonion.backends.hyprland import HyprlandBackend

        daemon.perception.register_backend(HyprlandBackend())
    except Exception:
        daemon.degradation_registry.record("backends", "HyprlandBackend", "info", "not available")

    try:
        from agents.hapax_daimonion.backends.watch import WatchBackend

        daemon.perception.register_backend(WatchBackend())
    except Exception:
        daemon.degradation_registry.record("backends", "WatchBackend", "info", "not available")

    try:
        from agents.hapax_daimonion.backends.health import HealthBackend

        daemon.perception.register_backend(HealthBackend())
    except Exception:
        daemon.degradation_registry.record("backends", "HealthBackend", "info", "not available")

    try:
        from agents.hapax_daimonion.backends.circadian import CircadianBackend

        daemon.perception.register_backend(CircadianBackend())
    except Exception:
        daemon.degradation_registry.record("backends", "CircadianBackend", "info", "not available")

    try:
        from agents.hapax_daimonion.backends.studio_ingestion import StudioIngestionBackend

        daemon.perception.register_backend(StudioIngestionBackend())
    except Exception:
        daemon.degradation_registry.record(
            "backends", "StudioIngestionBackend", "info", "not available"
        )

    try:
        from agents.hapax_daimonion.backends.vision import VisionBackend

        webcam = getattr(daemon.workspace_monitor, "_webcam_capturer", None)
        if webcam is not None:
            daemon.perception.register_backend(VisionBackend(webcam_capturer=webcam))
    except Exception:
        daemon.degradation_registry.record("backends", "VisionBackend", "warning", "not available")

    try:
        from agents.hapax_daimonion.backends.devices import DeviceStateBackend

        daemon.perception.register_backend(DeviceStateBackend())
    except Exception:
        daemon.degradation_registry.record(
            "backends", "DeviceStateBackend", "info", "not available"
        )

    try:
        from agents.hapax_daimonion.backends.local_llm import LocalLLMBackend

        daemon._local_llm_backend = LocalLLMBackend()
        daemon.perception.register_backend(daemon._local_llm_backend)
    except Exception:
        daemon._local_llm_backend = None
        daemon.degradation_registry.record("backends", "LocalLLMBackend", "info", "not available")

    try:
        from agents.hapax_daimonion.backends.midi_clock import MidiClockBackend

        daemon.perception.register_backend(
            MidiClockBackend(
                port_name=daemon.cfg.midi_port_name,
                beats_per_bar=daemon.cfg.midi_beats_per_bar,
            )
        )
    except Exception:
        daemon.degradation_registry.record("backends", "MidiClockBackend", "info", "not available")

    try:
        from agents.hapax_daimonion.backends.input_activity import InputActivityBackend

        daemon.perception.register_backend(
            InputActivityBackend(idle_threshold_s=daemon.cfg.input_idle_threshold_s)
        )
    except Exception:
        daemon.degradation_registry.record(
            "backends", "InputActivityBackend", "info", "not available"
        )

    try:
        from agents.hapax_daimonion.backends.contact_mic import ContactMicBackend

        daemon.perception.register_backend(
            ContactMicBackend(source_name=daemon.cfg.contact_mic_source)
        )
    except Exception:
        daemon.degradation_registry.record("backends", "ContactMicBackend", "info", "not available")

    try:
        from agents.hapax_daimonion.backends.mixer_input import MixerInputBackend

        daemon.perception.register_backend(MixerInputBackend())
    except Exception:
        daemon.degradation_registry.record("backends", "MixerInputBackend", "info", "not available")

    try:
        from agents.hapax_daimonion.backends.ir_presence import IrPresenceBackend

        daemon.perception.register_backend(IrPresenceBackend())
    except Exception:
        daemon.degradation_registry.record("backends", "IrPresenceBackend", "info", "not available")

    try:
        from agents.hapax_daimonion.backends.bt_presence import BTPresenceBackend

        daemon.perception.register_backend(BTPresenceBackend())
    except Exception:
        daemon.degradation_registry.record("backends", "BTPresenceBackend", "info", "not available")

    try:
        from agents.hapax_daimonion.backends.phone_media import PhoneMediaBackend

        daemon.perception.register_backend(PhoneMediaBackend())
    except Exception:
        daemon.degradation_registry.record("backends", "PhoneMediaBackend", "info", "not available")

    try:
        from agents.hapax_daimonion.backends.phone_messages import PhoneMessagesBackend

        daemon.perception.register_backend(PhoneMessagesBackend())
    except Exception:
        daemon.degradation_registry.record(
            "backends", "PhoneMessagesBackend", "info", "not available"
        )

    try:
        from agents.hapax_daimonion.backends.phone_calls import PhoneCallsBackend

        daemon.perception.register_backend(PhoneCallsBackend())
    except Exception:
        daemon.degradation_registry.record("backends", "PhoneCallsBackend", "info", "not available")

    try:
        from agents.hapax_daimonion.backends.phone_awareness import PhoneAwarenessBackend

        daemon.perception.register_backend(PhoneAwarenessBackend())
    except Exception:
        daemon.degradation_registry.record(
            "backends", "PhoneAwarenessBackend", "info", "not available"
        )

    # Bayesian presence engine (fuses all signals into presence probability)
    if daemon.cfg.presence_bayesian_enabled:
        try:
            from agents.hapax_daimonion.presence_engine import PresenceEngine

            daemon._presence_engine = PresenceEngine(
                prior=daemon.cfg.presence_prior,
                enter_threshold=daemon.cfg.presence_enter_threshold,
                exit_threshold=daemon.cfg.presence_exit_threshold,
                enter_ticks=daemon.cfg.presence_enter_ticks,
                exit_ticks=daemon.cfg.presence_exit_ticks,
                signal_weights=daemon.cfg.presence_signal_weights,
            )
            daemon.perception.register_backend(daemon._presence_engine)
        except Exception:
            daemon._presence_engine = None
            daemon.degradation_registry.record(
                "backends", "PresenceEngine", "warning", "not available"
            )
    else:
        daemon._presence_engine = None

    counts = daemon.degradation_registry.count_by_severity()
    if counts:
        log.info(
            "Backend registration complete: %d degraded (%s)",
            sum(counts.values()),
            ", ".join(f"{k}={v}" for k, v in counts.items()),
        )
