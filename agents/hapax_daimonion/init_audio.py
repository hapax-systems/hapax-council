"""Audio processing initialization for VoiceDaemon."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger("hapax_daimonion")


def init_audio_processing(daemon: VoiceDaemon) -> None:
    """Initialize echo canceller, preprocessor, noise reference, speaker ID, bridge."""
    daemon._echo_canceller = None
    if daemon.cfg.aec_enabled:
        try:
            from agents.hapax_daimonion.echo_canceller import EchoCanceller

            daemon._echo_canceller = EchoCanceller(frame_size=480, tail_ms=daemon.cfg.aec_tail_ms)
        except Exception:
            log.warning("Echo canceller init failed", exc_info=True)

    from agents.hapax_daimonion.audio_preprocess import AudioPreprocessor

    daemon._audio_preprocessor = AudioPreprocessor()

    from agents.hapax_daimonion.multi_mic import NoiseReference, discover_pipewire_sources

    _room = discover_pipewire_sources(daemon.cfg.noise_ref_room_patterns)
    _struct = discover_pipewire_sources(daemon.cfg.noise_ref_structure_patterns)
    log.info("Noise reference: %d room, %d structure", len(_room), len(_struct))
    daemon._noise_reference = NoiseReference(room_sources=_room, structure_sources=_struct)
    daemon._noise_reference.start()

    _init_speaker_id(daemon)

    from agents.hapax_daimonion.bridge_engine import BridgeEngine

    daemon._bridge_engine = BridgeEngine()


def _init_speaker_id(daemon: VoiceDaemon) -> None:
    """Initialize speaker identification if enrollment exists."""
    daemon._speaker_identifier = None
    try:
        from agents.hapax_daimonion.speaker_id import SpeakerIdentifier

        enrollment_path = Path.home() / ".local/share/hapax-daimonion/speaker_embedding.npy"
        if enrollment_path.exists():
            daemon._speaker_identifier = SpeakerIdentifier(enrollment_path=enrollment_path)
            import numpy as np

            daemon._speaker_identifier.extract_embedding(np.zeros(16000, dtype=np.float32), 16000)
            log.info("Speaker identifier loaded from %s", enrollment_path)
        else:
            log.warning("No speaker enrollment at %s — gating disabled", enrollment_path)
    except Exception:
        log.warning("Speaker identifier init failed", exc_info=True)


def init_salience(daemon: VoiceDaemon) -> None:
    """Initialize salience-based model routing."""
    daemon._salience_router = None
    daemon._salience_embedder = None
    daemon._salience_concern_graph = None
    daemon._salience_diagnostics = None
    daemon._context_distillation: str = ""
    if not daemon.cfg.salience_enabled:
        return
    try:
        from agents.hapax_daimonion.salience.concern_graph import ConcernGraph
        from agents.hapax_daimonion.salience.embedder import Embedder
        from agents.hapax_daimonion.salience_router import SalienceRouter

        daemon._salience_embedder = Embedder(model_name=daemon.cfg.salience_model)
        if daemon._salience_embedder.available:
            daemon._salience_concern_graph = ConcernGraph(dim=daemon._salience_embedder.dim)
            daemon._salience_router = SalienceRouter(
                embedder=daemon._salience_embedder,
                concern_graph=daemon._salience_concern_graph,
                thresholds=daemon.cfg.salience_thresholds,
                weights=daemon.cfg.salience_weights,
            )
            from agents.hapax_daimonion.salience.diagnostics import SalienceDiagnostics

            daemon._salience_diagnostics = SalienceDiagnostics(
                router=daemon._salience_router,
                concern_graph=daemon._salience_concern_graph,
            )
            log.info("Salience router initialized (%dd)", daemon._salience_embedder.dim)
        else:
            log.warning("Salience embedder unavailable, heuristic routing")
    except Exception:
        log.warning("Salience router init failed, heuristic routing", exc_info=True)
