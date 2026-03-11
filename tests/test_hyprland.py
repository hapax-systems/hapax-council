import json
from unittest.mock import patch, MagicMock

from shared.hyprland import (
    HyprlandIPC,
    WindowInfo,
    WorkspaceInfo,
)


class TestHyprlandQuery:
    def test_get_active_window_parses_json(self):
        fake_json = json.dumps({
            "address": "0x1234",
            "class": "foot",
            "title": "~/projects",
            "workspace": {"id": 1, "name": "1"},
            "pid": 42,
            "at": [0, 0],
            "size": [800, 600],
            "floating": False,
            "fullscreen": False,
            "mapped": True,
        })
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=fake_json, returncode=0
            )
            ipc = HyprlandIPC()
            win = ipc.get_active_window()

        assert win is not None
        assert win.app_class == "foot"
        assert win.title == "~/projects"
        assert win.workspace_id == 1
        assert win.pid == 42
        mock_run.assert_called_once_with(
            ["hyprctl", "-j", "activewindow"],
            capture_output=True, text=True, timeout=5,
        )

    def test_get_active_window_returns_none_on_error(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            ipc = HyprlandIPC()
            assert ipc.get_active_window() is None

    def test_get_clients_returns_list(self):
        fake_json = json.dumps([
            {
                "address": "0x1", "class": "foot", "title": "term",
                "workspace": {"id": 1, "name": "1"}, "pid": 10,
                "at": [0, 0], "size": [800, 600],
                "floating": False, "fullscreen": False, "mapped": True,
            },
            {
                "address": "0x2", "class": "google-chrome", "title": "Tab",
                "workspace": {"id": 3, "name": "3"}, "pid": 20,
                "at": [0, 0], "size": [1920, 1080],
                "floating": False, "fullscreen": False, "mapped": True,
            },
        ])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=fake_json, returncode=0
            )
            ipc = HyprlandIPC()
            clients = ipc.get_clients()

        assert len(clients) == 2
        assert clients[0].app_class == "foot"
        assert clients[1].workspace_id == 3

    def test_get_workspaces_returns_list(self):
        fake_json = json.dumps([
            {"id": 1, "name": "1", "windows": 3,
             "lastwindowtitle": "foot", "monitor": "DP-1"},
            {"id": 3, "name": "3", "windows": 1,
             "lastwindowtitle": "Chrome", "monitor": "DP-1"},
        ])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=fake_json, returncode=0
            )
            ipc = HyprlandIPC()
            workspaces = ipc.get_workspaces()

        assert len(workspaces) == 2
        assert workspaces[0].window_count == 3


class TestHyprlandDispatch:
    def test_dispatch_calls_hyprctl(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ipc = HyprlandIPC()
            ipc.dispatch("workspace", "3")

        mock_run.assert_called_once_with(
            ["hyprctl", "dispatch", "workspace", "3"],
            capture_output=True, text=True, timeout=5,
        )

    def test_batch_sends_semicolon_joined(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ipc = HyprlandIPC()
            ipc.batch([
                "dispatch workspace 3",
                "dispatch exec foot",
            ])

        mock_run.assert_called_once_with(
            ["hyprctl", "--batch", "dispatch workspace 3 ; dispatch exec foot"],
            capture_output=True, text=True, timeout=5,
        )

    def test_dispatch_returns_false_on_missing_hyprctl(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            ipc = HyprlandIPC()
            assert ipc.dispatch("workspace", "3") is False
