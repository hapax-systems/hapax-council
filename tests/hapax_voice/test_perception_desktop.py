import time
from unittest.mock import MagicMock

from agents.hapax_voice.perception import EnvironmentState, PerceptionEngine
from shared.hyprland import WindowInfo


def test_environment_state_has_desktop_fields():
    state = EnvironmentState(timestamp=time.monotonic())
    assert state.active_window is None
    assert state.window_count == 0
    assert state.active_workspace_id == 0


def test_environment_state_with_active_window():
    win = WindowInfo(
        address="0x1", app_class="foot", title="~/projects",
        workspace_id=1, pid=42, x=0, y=0, width=800, height=600,
        floating=False, fullscreen=False,
    )
    state = EnvironmentState(
        timestamp=time.monotonic(),
        active_window=win,
        window_count=3,
        active_workspace_id=1,
    )
    assert state.active_window.app_class == "foot"
    assert state.window_count == 3


def test_perception_engine_tick_includes_desktop():
    presence = MagicMock()
    presence.latest_vad_confidence = 0.0
    presence.face_detected = False
    presence.face_count = 0

    ws_monitor = MagicMock()

    engine = PerceptionEngine(
        presence=presence,
        workspace_monitor=ws_monitor,
    )

    # Simulate hyprland data
    win = WindowInfo(
        address="0x1", app_class="foot", title="term",
        workspace_id=1, pid=1, x=0, y=0, width=800, height=600,
        floating=False, fullscreen=False,
    )
    engine.update_desktop_state(active_window=win, window_count=4, active_workspace_id=1)

    state = engine.tick()
    assert state.active_window is not None
    assert state.active_window.app_class == "foot"
    assert state.window_count == 4
