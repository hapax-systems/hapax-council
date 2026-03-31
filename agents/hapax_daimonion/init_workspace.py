"""Workspace monitor and consent initialization for VoiceDaemon."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger("hapax_daimonion")


def init_workspace(daemon: VoiceDaemon) -> None:
    """Initialize workspace monitor, cameras, and consent principals."""
    from agents.hapax_daimonion.workspace_monitor import WorkspaceMonitor

    cameras = _build_camera_configs(daemon)
    daemon.workspace_monitor = WorkspaceMonitor(
        enabled=daemon.cfg.screen_monitor_enabled,
        poll_interval_s=daemon.cfg.screen_poll_interval_s,
        capture_cooldown_s=daemon.cfg.screen_capture_cooldown_s,
        proactive_min_confidence=daemon.cfg.screen_proactive_min_confidence,
        proactive_cooldown_s=daemon.cfg.screen_proactive_cooldown_s,
        recapture_idle_s=daemon.cfg.screen_recapture_idle_s,
        cameras=cameras if cameras else None,
        face_interval_s=daemon.cfg.presence_face_interval_s,
        face_min_confidence=daemon.cfg.presence_face_min_confidence,
    )
    daemon.workspace_monitor.set_notification_queue(daemon.notifications)
    daemon.workspace_monitor.set_presence(daemon.presence)

    # Consent registry
    from agents._governance import ConsentRegistry, Principal, PrincipalKind

    daemon.consent_registry = ConsentRegistry()
    _consent_count = daemon.consent_registry.load()
    log.info("Loaded %d consent contracts", _consent_count)

    daemon._operator_principal = Principal(id="operator", kind=PrincipalKind.SOVEREIGN)
    daemon._daemon_principal = daemon._operator_principal.delegate(
        child_id="hapax-daimonion",
        scope=frozenset(
            {
                "audio",
                "video",
                "transcription",
                "presence",
                "biometrics",
                "workspace",
                "notifications",
            }
        ),
    )


def _build_camera_configs(daemon: VoiceDaemon) -> list:
    """Build camera configs from daemon config."""
    from agents.hapax_daimonion.screen_models import CameraConfig

    cameras: list[CameraConfig] = []
    if not daemon.cfg.webcam_enabled:
        return cameras
    cameras.append(
        CameraConfig(
            device=daemon.cfg.webcam_brio_device,
            role="operator",
            width=daemon.cfg.webcam_capture_width,
            height=daemon.cfg.webcam_capture_height,
        )
    )
    cameras.append(
        CameraConfig(
            device=daemon.cfg.webcam_c920_device,
            role="hardware",
            width=daemon.cfg.webcam_capture_width,
            height=daemon.cfg.webcam_capture_height,
        )
    )
    if daemon.cfg.webcam_ir_device:
        cameras.append(
            CameraConfig(
                device=daemon.cfg.webcam_ir_device,
                role="ir",
                width=340,
                height=340,
                input_format="rawvideo",
                pixel_format="gray",
            )
        )
    return cameras
