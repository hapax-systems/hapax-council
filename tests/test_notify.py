"""Tests for shared/notify.py — notification dispatch.

All I/O is mocked. No real HTTP requests or subprocess calls.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from shared.notify import (
    _DESKTOP_URGENCY,
    _dismiss_existing_intake_notifications,
    _send_desktop,
    briefing_uri,
    nudges_uri,
    obsidian_uri,
    send_notification,
    send_webhook,
)

# ── Configuration tests ──────────────────────────────────────────────────────


def test_desktop_urgency_mapping():
    assert _DESKTOP_URGENCY["min"] == "low"
    assert _DESKTOP_URGENCY["default"] == "normal"
    assert _DESKTOP_URGENCY["high"] == "critical"
    assert _DESKTOP_URGENCY["urgent"] == "critical"


# ── _send_desktop tests ──────────────────────────────────────────────────────


class TestSendDesktop:
    @patch("shared.notify._run_subprocess")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        result = _send_desktop("Title", "Message")
        assert result is True
        mock_run.assert_called_once()

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "notify-send"
        assert "--urgency=normal" in cmd
        assert "--app-name=LLM Stack" in cmd
        assert "Title" in cmd
        assert "Message" in cmd

    @patch("shared.notify._run_subprocess")
    def test_high_priority_urgency(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        _send_desktop("T", "M", priority="high")
        cmd = mock_run.call_args[0][0]
        assert "--urgency=critical" in cmd

    @patch("shared.notify._run_subprocess")
    def test_replace_id_coalesces_desktop_notification(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        _send_desktop('T "quoted"', "M\nnext", priority="urgent", replace_id=12345)
        cmd = mock_run.call_args[0][0]
        assert cmd[:8] == [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.freedesktop.Notifications",
            "--object-path",
            "/org/freedesktop/Notifications",
            "--method",
        ]
        assert "org.freedesktop.Notifications.Notify" in cmd
        assert "12345" in cmd
        assert json.loads(cmd[9]) == "LLM Stack"
        assert json.loads(cmd[11]) == "dialog-error"
        assert json.loads(cmd[12]) == 'T "quoted"'
        assert json.loads(cmd[13]) == "M\nnext"
        assert '{"urgency": <byte 2>, "desktop-entry": <"org.hapax.system">}' in cmd

    @patch("shared.notify._run_subprocess", side_effect=FileNotFoundError)
    def test_no_notify_send(self, mock_run):
        result = _send_desktop("T", "M")
        assert result is False

    @patch("shared.notify._run_subprocess")
    def test_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        result = _send_desktop("T", "M")
        assert result is False


def test_dismiss_existing_intake_notifications_uses_mako_marker():
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd == ["makoctl", "list", "-j"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    [
                        {"id": 11, "body": "SDLC intake: p0-incident-demo\nold"},
                        {"id": 12, "body": "unrelated"},
                        {"id": 13, "body": "SDLC intake: p0-incident-demo\nnewer"},
                        {"body": "SDLC intake: p0-incident-demo without id"},
                    ]
                ),
            )
        return SimpleNamespace(returncode=0, stdout="")

    with patch("shared.notify._run_subprocess", side_effect=fake_run):
        _dismiss_existing_intake_notifications("p0-incident-demo")

    assert calls[0][0] == ["makoctl", "list", "-j"]
    assert [call[0] for call in calls[1:]] == [
        ["makoctl", "dismiss", "--no-history", "-n", "11"],
        ["makoctl", "dismiss", "--no-history", "-n", "13"],
    ]


# ── send_notification (unified) tests ────────────────────────────────────────


@patch("shared.notify._logos_is_active", return_value=False)
@patch("shared.notify._emit_watershed_event")
@patch("shared.notify._is_duplicate", return_value=False)
class TestSendNotification:
    @patch("shared.notify._send_desktop", return_value=True)
    def test_desktop_succeeds(self, mock_desktop, _dedup, _watershed, _logos):
        result = send_notification("Title", "Message")
        assert result is True
        mock_desktop.assert_called_once()

    @patch("shared.notify._send_desktop", return_value=False)
    def test_desktop_fails(self, mock_desktop, _dedup, _watershed, _logos):
        result = send_notification("Title", "Message")
        assert result is False

    @patch("shared.notify._send_desktop", return_value=True)
    def test_passes_priority(self, mock_desktop, _dedup, _watershed, _logos):
        send_notification("T", "M", priority="urgent", tags=["skull"])
        mock_desktop.assert_called_once_with("T", "M", priority="urgent")

    @patch("shared.notify._dismiss_existing_intake_notifications")
    @patch("shared.p0_incident_intake.record_notification")
    @patch("shared.notify._send_desktop", return_value=True)
    def test_technical_alert_records_p0_intake_and_replace_id(
        self,
        mock_desktop,
        mock_record,
        mock_dismiss,
        _dedup,
        _watershed,
        _logos,
    ):
        mock_record.return_value = SimpleNamespace(
            technical=True,
            task_id="p0-incident-stack-failed-abc123",
            replace_id=456,
            click_url="obsidian://open?vault=Personal&file=20-projects/example",
        )

        result = send_notification(
            "Stack Failed",
            "1 check failed",
            priority="high",
            tags=["rotating_light"],
        )

        assert result is True
        mock_record.assert_called_once_with(
            "Stack Failed",
            "1 check failed",
            priority="high",
            tags=["rotating_light"],
            technical=None,
        )
        mock_desktop.assert_called_once_with(
            "Stack Failed",
            "1 check failed\nSDLC intake: p0-incident-stack-failed-abc123",
            priority="high",
            replace_id=456,
        )
        mock_dismiss.assert_called_once_with("p0-incident-stack-failed-abc123")

    @patch("shared.p0_incident_intake.record_notification", side_effect=OSError("state locked"))
    @patch("shared.notify._send_desktop", return_value=True)
    def test_technical_intake_failure_logs_next_action(
        self,
        mock_desktop,
        _mock_record,
        _dedup,
        _watershed,
        _logos,
        caplog,
    ):
        with caplog.at_level("WARNING", logger="shared.notify"):
            result = send_notification("LUFS panic-cap", "too hot", priority="high")

        assert result is True
        assert "notify: p0 incident intake failed; next action:" in caplog.text
        assert "~/.cache/hapax/p0-incident-intake/state.json" in caplog.text
        assert "scripts/hapax-p0-incident-intake notification" in caplog.text
        assert "--technical" in caplog.text
        mock_desktop.assert_called_once_with("LUFS panic-cap", "too hot", priority="high")


# ── send_webhook tests ───────────────────────────────────────────────────────


class TestSendWebhook:
    @patch("shared.notify.urlopen")
    def test_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = send_webhook("http://localhost:5678/webhook/health", {"status": "ok"})
        assert result is True

        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "http://localhost:5678/webhook/health"
        assert req.get_header("Content-type") == "application/json"

    @patch("shared.notify.urlopen", side_effect=OSError("connection refused"))
    def test_failure(self, mock_urlopen):
        result = send_webhook("http://bad-url/webhook", {"x": 1})
        assert result is False


# ── Obsidian URI helpers ────────────────────────────────────────────────────


class TestObsidianUri:
    def test_obsidian_uri_basic(self):
        uri = obsidian_uri("30-system/briefings/2026-03-04.md")
        assert uri.startswith("obsidian://open?vault=")
        assert "file=30-system" in uri
        assert ".md" not in uri

    def test_obsidian_uri_no_extension(self):
        uri = obsidian_uri("30-system/nudges")
        assert "nudges" in uri
        assert ".md" not in uri

    def test_briefing_uri(self):
        uri = briefing_uri("2026-03-04")
        assert "briefings" in uri
        assert "2026-03-04" in uri

    def test_nudges_uri(self):
        uri = nudges_uri()
        assert "nudges" in uri
