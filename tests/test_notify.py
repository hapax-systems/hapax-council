"""Tests for shared/notify.py — notification dispatch.

All I/O is mocked. No real HTTP requests or subprocess calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from shared.notify import (
    _DESKTOP_URGENCY,
    _NTFY_PRIORITIES,
    NTFY_BASE_URL,
    NTFY_TOPIC,
    _send_desktop,
    _send_ntfy,
    briefing_uri,
    nudges_uri,
    obsidian_uri,
    send_notification,
    send_webhook,
)

# ── Configuration tests ──────────────────────────────────────────────────────


def test_default_config():
    assert NTFY_BASE_URL == "http://localhost:8090"
    assert NTFY_TOPIC == "cockpit"


def test_ntfy_priority_mapping():
    assert _NTFY_PRIORITIES["min"] == "1"
    assert _NTFY_PRIORITIES["default"] == "3"
    assert _NTFY_PRIORITIES["urgent"] == "5"
    assert len(_NTFY_PRIORITIES) == 5


def test_desktop_urgency_mapping():
    assert _DESKTOP_URGENCY["min"] == "low"
    assert _DESKTOP_URGENCY["default"] == "normal"
    assert _DESKTOP_URGENCY["high"] == "critical"
    assert _DESKTOP_URGENCY["urgent"] == "critical"


# ── _send_ntfy tests ─────────────────────────────────────────────────────────


class TestSendNtfy:
    @patch("shared.notify.urlopen")
    def test_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _send_ntfy("Test Title", "Test message")
        assert result is True
        mock_urlopen.assert_called_once()

        # Verify the request was formed correctly
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "http://localhost:8090/cockpit"
        assert req.get_header("Title") == "Test Title"
        assert req.get_header("Priority") == "3"
        assert req.data == b"Test message"

    @patch("shared.notify.urlopen")
    def test_custom_topic(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        _send_ntfy("T", "M", topic="alerts")
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "http://localhost:8090/alerts"

    @patch("shared.notify.urlopen")
    def test_high_priority(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        _send_ntfy("T", "M", priority="high")
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Priority") == "4"

    @patch("shared.notify.urlopen")
    def test_tags(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        _send_ntfy("T", "M", tags=["warning", "robot"])
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Tags") == "warning,robot"

    @patch("shared.notify.urlopen")
    def test_click_url(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        _send_ntfy("T", "M", click_url="http://example.com")
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Click") == "http://example.com"

    @patch("shared.notify.urlopen", side_effect=OSError("connection refused"))
    def test_unreachable(self, mock_urlopen):
        result = _send_ntfy("T", "M")
        assert result is False


# ── _send_desktop tests ──────────────────────────────────────────────────────


class TestSendDesktop:
    @patch("shared.notify.subprocess.run")
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

    @patch("shared.notify.subprocess.run")
    def test_high_priority_urgency(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        _send_desktop("T", "M", priority="high")
        cmd = mock_run.call_args[0][0]
        assert "--urgency=critical" in cmd

    @patch("shared.notify.subprocess.run", side_effect=FileNotFoundError)
    def test_no_notify_send(self, mock_run):
        result = _send_desktop("T", "M")
        assert result is False

    @patch("shared.notify.subprocess.run")
    def test_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        result = _send_desktop("T", "M")
        assert result is False


# ── send_notification (unified) tests ────────────────────────────────────────


class TestSendNotification:
    @patch("shared.notify._send_desktop", return_value=True)
    @patch("shared.notify._send_ntfy", return_value=True)
    def test_both_succeed(self, mock_ntfy, mock_desktop):
        result = send_notification("Title", "Message")
        assert result is True
        mock_ntfy.assert_called_once()
        mock_desktop.assert_called_once()

    @patch("shared.notify._send_desktop", return_value=True)
    @patch("shared.notify._send_ntfy", return_value=False)
    def test_ntfy_fails_desktop_succeeds(self, mock_ntfy, mock_desktop):
        result = send_notification("Title", "Message")
        assert result is True

    @patch("shared.notify._send_desktop", return_value=False)
    @patch("shared.notify._send_ntfy", return_value=True)
    def test_ntfy_succeeds_desktop_fails(self, mock_ntfy, mock_desktop):
        result = send_notification("Title", "Message")
        assert result is True

    @patch("shared.notify._send_desktop", return_value=False)
    @patch("shared.notify._send_ntfy", side_effect=Exception("boom"))
    def test_both_fail(self, mock_ntfy, mock_desktop):
        result = send_notification("Title", "Message")
        assert result is False

    @patch("shared.notify._send_desktop", return_value=True)
    @patch("shared.notify._send_ntfy", return_value=True)
    def test_passes_priority(self, mock_ntfy, mock_desktop):
        send_notification("T", "M", priority="urgent", tags=["skull"])
        mock_ntfy.assert_called_once_with(
            "T",
            "M",
            priority="urgent",
            tags=["skull"],
            topic=None,
            click_url=None,
        )
        mock_desktop.assert_called_once_with("T", "M", priority="urgent")

    @patch("shared.notify._send_desktop", return_value=True)
    @patch("shared.notify._send_ntfy", return_value=True)
    def test_passes_topic_override(self, mock_ntfy, mock_desktop):
        send_notification("T", "M", topic="alerts")
        assert mock_ntfy.call_args[1]["topic"] == "alerts"


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
        assert ".md" not in uri  # .md stripped

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
