"""OBSExecutor — scene switching via obs-websocket 5.x (obsws-python).

Implements the Executor protocol. Handles scene switching with transition
control: cut (0ms), dissolve (500ms), fade (1000ms).
"""

from __future__ import annotations

import logging
from typing import Any

from agents.hapax_daimonion.commands import Command

log = logging.getLogger(__name__)

_TRANSITION_DURATIONS = {
    "cut": 0,
    "dissolve": 500,
    "fade": 1000,
}


class OBSExecutor:
    """Executor for OBS scene switching.

    handles = {"wide_ambient", "gear_closeup", "face_cam", "rapid_cut"}
    """

    def __init__(self, host: str = "localhost", port: int = 4455) -> None:
        self._host = host
        self._port = port
        self._client: Any = None

    @property
    def name(self) -> str:
        return "obs"

    @property
    def handles(self) -> frozenset[str]:
        return frozenset({"wide_ambient", "gear_closeup", "face_cam", "rapid_cut"})

    def execute(self, command: Command) -> None:
        """Switch OBS scene with the specified transition."""
        client = self._get_client()
        if client is None:
            log.debug("OBS not connected, skipping scene switch: %s", command.action)
            return

        transition = command.params.get("transition", "dissolve")
        duration = _TRANSITION_DURATIONS.get(transition, 500)
        scene_name = command.action

        try:
            # Set transition type and duration
            client.set_current_scene_transition(transitionName=transition.capitalize())
            client.set_current_scene_transition_duration(transitionDuration=duration)
            # Switch scene
            client.set_current_program_scene(sceneName=scene_name)
            log.debug("OBS scene → %s (transition=%s, %dms)", scene_name, transition, duration)
        except Exception as exc:
            log.warning("OBS scene switch failed: %s", exc)
            self._client = None  # force reconnect on next call

    def _get_client(self) -> Any:
        """Get or create obs-websocket client. Returns None if unavailable."""
        if self._client is not None:
            return self._client
        try:
            import obsws_python

            self._client = obsws_python.ReqClient(host=self._host, port=self._port)
            log.info("Connected to OBS at %s:%d", self._host, self._port)
            return self._client
        except Exception as exc:
            log.debug("OBS connection failed: %s", exc)
            return None

    def available(self) -> bool:
        try:
            import obsws_python  # noqa: F401

            return True
        except ImportError:
            return False

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None
