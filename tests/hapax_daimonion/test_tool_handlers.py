"""Tests for voice tool handler implementations."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_qdrant():
    """Mock Qdrant client with query_points returning fake results."""
    client = MagicMock()
    point = MagicMock()
    point.payload = {
        "filename": "test.md",
        "text": "Sample document text",
        "source_service": "obsidian",
    }
    point.score = 0.85
    response = MagicMock()
    response.points = [point]
    client.query_points.return_value = response
    return client


@pytest.fixture
def mock_embed():
    """Mock embed function returning a fake 768-dim vector."""
    return MagicMock(return_value=[0.1] * 768)


@pytest.fixture
def mock_fn_params():
    """Create a mock FunctionCallParams with result_callback."""
    params = MagicMock()
    params.result_callback = AsyncMock()
    return params


class TestSearchDocumentsHandler:
    @pytest.mark.asyncio
    async def test_basic_search(self, mock_fn_params, mock_qdrant, mock_embed):
        from agents.hapax_daimonion.tools import handle_search_documents

        mock_fn_params.arguments = {"query": "meeting notes"}

        with (
            patch("agents.hapax_daimonion.tools.get_qdrant_grpc", return_value=mock_qdrant),
            patch("agents.hapax_daimonion.tools.embed", mock_embed),
        ):
            await handle_search_documents(mock_fn_params)

        mock_embed.assert_called_once_with("meeting notes", prefix="search_query")
        mock_qdrant.query_points.assert_called_once()
        query_filter = mock_qdrant.query_points.call_args.kwargs.get("query_filter")
        assert query_filter is not None
        assert query_filter.must_not
        assert query_filter.must_not[0].key == "retrieval_eligible"
        mock_fn_params.result_callback.assert_awaited_once()
        result = mock_fn_params.result_callback.call_args[0][0]
        assert "test.md" in result
        assert "Sample document text" in result

    @pytest.mark.asyncio
    async def test_source_filter(self, mock_fn_params, mock_qdrant, mock_embed):
        from agents.hapax_daimonion.tools import handle_search_documents

        mock_fn_params.arguments = {"query": "budget", "source_filter": "gdrive"}

        with (
            patch("agents.hapax_daimonion.tools.get_qdrant_grpc", return_value=mock_qdrant),
            patch("agents.hapax_daimonion.tools.embed", mock_embed),
        ):
            await handle_search_documents(mock_fn_params)

        call_kwargs = mock_qdrant.query_points.call_args
        query_filter = call_kwargs.kwargs.get("query_filter")
        assert query_filter is not None
        assert query_filter.must_not
        assert query_filter.must_not[0].key == "retrieval_eligible"

    @pytest.mark.asyncio
    async def test_no_results(self, mock_fn_params, mock_embed):
        from agents.hapax_daimonion.tools import handle_search_documents

        mock_fn_params.arguments = {"query": "nonexistent"}
        empty_client = MagicMock()
        empty_response = MagicMock()
        empty_response.points = []
        empty_client.query_points.return_value = empty_response

        with (
            patch("agents.hapax_daimonion.tools.get_qdrant_grpc", return_value=empty_client),
            patch("agents.hapax_daimonion.tools.embed", mock_embed),
        ):
            await handle_search_documents(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "no relevant" in result.lower() or "no results" in result.lower()

    @pytest.mark.asyncio
    async def test_error_handling(self, mock_fn_params):
        from agents.hapax_daimonion.tools import handle_search_documents

        mock_fn_params.arguments = {"query": "test"}

        with patch(
            "agents.hapax_daimonion.tools.get_qdrant_grpc",
            side_effect=RuntimeError("connection failed"),
        ):
            await handle_search_documents(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "failed" in result.lower() or "error" in result.lower()


class TestGetCalendarTodayHandler:
    @pytest.fixture(autouse=True)
    def _stream_private(self):
        """LRR Phase 6 §4.F: handle_get_calendar_today fail-closed
        redacts to a broadcast-safe stub when _stream_is_publicly_visible
        returns True. Tests of the actual API path need to mock the
        gate to False; the privacy-redaction path is exercised by
        the dedicated TestPrivacyGate suite (if/when added)."""
        with patch(
            "agents.hapax_daimonion.tools._stream_is_publicly_visible",
            return_value=False,
        ):
            yield

    @pytest.mark.asyncio
    async def test_returns_events(self, mock_fn_params):
        from agents.hapax_daimonion.tools import handle_get_calendar_today

        mock_fn_params.arguments = {}

        mock_service = MagicMock()
        mock_events = MagicMock()
        mock_service.events.return_value = mock_events
        mock_list = MagicMock()
        mock_events.list.return_value = mock_list
        mock_list.execute.return_value = {
            "items": [
                {
                    "summary": "Team standup",
                    "start": {"dateTime": "2026-03-09T09:00:00-05:00"},
                    "end": {"dateTime": "2026-03-09T09:30:00-05:00"},
                    "attendees": [{"email": "alice@example.com"}],
                },
                {
                    "summary": "Lunch",
                    "start": {"date": "2026-03-09"},
                    "end": {"date": "2026-03-09"},
                },
            ]
        }

        with patch("agents.hapax_daimonion.tools.build_service", return_value=mock_service):
            await handle_get_calendar_today(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "Team standup" in result
        assert "Lunch" in result

    @pytest.mark.asyncio
    async def test_no_events(self, mock_fn_params):
        from agents.hapax_daimonion.tools import handle_get_calendar_today

        mock_fn_params.arguments = {}

        mock_service = MagicMock()
        mock_events = MagicMock()
        mock_service.events.return_value = mock_events
        mock_list = MagicMock()
        mock_events.list.return_value = mock_list
        mock_list.execute.return_value = {"items": []}

        with patch("agents.hapax_daimonion.tools.build_service", return_value=mock_service):
            await handle_get_calendar_today(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "clear" in result.lower() or "no" in result.lower()

    @pytest.mark.asyncio
    async def test_api_error(self, mock_fn_params):
        from agents.hapax_daimonion.tools import handle_get_calendar_today

        mock_fn_params.arguments = {}

        with patch(
            "agents.hapax_daimonion.tools.build_service", side_effect=Exception("auth failed")
        ):
            await handle_get_calendar_today(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "failed" in result.lower()


class TestSearchEmailsHandler:
    @pytest.fixture(autouse=True)
    def _stream_private(self):
        """Same broadcast-safe redaction gate as TestGetCalendarTodayHandler.
        handle_search_emails fail-closes to _BROADCAST_SAFE_EMAIL_STUB
        when stream is publicly visible; mock the gate to False so the
        actual qdrant/gmail paths can be tested."""
        with patch(
            "agents.hapax_daimonion.tools._stream_is_publicly_visible",
            return_value=False,
        ):
            yield

    @pytest.mark.asyncio
    async def test_qdrant_search_default(self, mock_fn_params, mock_qdrant, mock_embed):
        from agents.hapax_daimonion.tools import handle_search_emails

        mock_fn_params.arguments = {"query": "invoice from Sarah"}

        with (
            patch("agents.hapax_daimonion.tools.get_qdrant_grpc", return_value=mock_qdrant),
            patch("agents.hapax_daimonion.tools.embed", mock_embed),
        ):
            await handle_search_emails(mock_fn_params)

        mock_qdrant.query_points.assert_called_once()
        mock_fn_params.result_callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recent_only_uses_gmail_api(self, mock_fn_params):
        from agents.hapax_daimonion.tools import handle_search_emails

        mock_fn_params.arguments = {"query": "from:sarah", "recent_only": True}

        mock_service = MagicMock()
        mock_users = MagicMock()
        mock_service.users.return_value = mock_users
        mock_messages = MagicMock()
        mock_users.messages.return_value = mock_messages
        mock_list = MagicMock()
        mock_messages.list.return_value = mock_list
        mock_list.execute.return_value = {"messages": [{"id": "msg1", "threadId": "t1"}]}
        mock_get = MagicMock()
        mock_messages.get.return_value = mock_get
        mock_get.execute.return_value = {
            "id": "msg1",
            "snippet": "Hi, here is the invoice...",
            "payload": {
                "headers": [
                    {"name": "From", "value": "sarah@example.com"},
                    {"name": "Subject", "value": "Invoice Q1"},
                    {"name": "Date", "value": "Mon, 9 Mar 2026 10:00:00 -0500"},
                ],
            },
        }

        with patch("agents.hapax_daimonion.tools.build_service", return_value=mock_service):
            await handle_search_emails(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "Invoice Q1" in result or "sarah" in result.lower()

    @pytest.mark.asyncio
    async def test_no_results(self, mock_fn_params, mock_embed):
        from agents.hapax_daimonion.tools import handle_search_emails

        mock_fn_params.arguments = {"query": "nonexistent"}
        empty_client = MagicMock()
        empty_response = MagicMock()
        empty_response.points = []
        empty_client.query_points.return_value = empty_response

        with (
            patch("agents.hapax_daimonion.tools.get_qdrant_grpc", return_value=empty_client),
            patch("agents.hapax_daimonion.tools.embed", mock_embed),
        ):
            await handle_search_emails(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "no" in result.lower()


class TestSendSmsHandler:
    @pytest.mark.asyncio
    async def test_prepare_sms_returns_confirmation(self, mock_fn_params):
        from agents.hapax_daimonion.tools import _pending_sms, handle_send_sms

        _pending_sms.clear()
        mock_fn_params.arguments = {"recipient": "Wife", "message": "Running late"}

        mock_cfg = MagicMock()
        mock_cfg.sms_contacts = {"Wife": "+15551234567"}

        with patch("agents.hapax_daimonion.tools._daimonion_config", mock_cfg):
            await handle_send_sms(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert result["status"] == "pending_confirmation"
        assert "+15551234567" in result["phone"]
        assert len(_pending_sms) == 1

    @pytest.mark.asyncio
    async def test_unknown_recipient(self, mock_fn_params):
        from agents.hapax_daimonion.tools import handle_send_sms

        mock_fn_params.arguments = {"recipient": "Unknown Person", "message": "Hello"}

        mock_cfg = MagicMock()
        mock_cfg.sms_contacts = {"Wife": "+15551234567"}

        with patch("agents.hapax_daimonion.tools._daimonion_config", mock_cfg):
            await handle_send_sms(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_phone_number_as_recipient(self, mock_fn_params):
        from agents.hapax_daimonion.tools import _pending_sms, handle_send_sms

        _pending_sms.clear()
        mock_fn_params.arguments = {"recipient": "+15559876543", "message": "Hello"}

        mock_cfg = MagicMock()
        mock_cfg.sms_contacts = {}

        with patch("agents.hapax_daimonion.tools._daimonion_config", mock_cfg):
            await handle_send_sms(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert result["status"] == "pending_confirmation"
        assert result["phone"] == "+15559876543"


class TestConfirmSendSmsHandler:
    @pytest.mark.asyncio
    async def test_confirm_sends_sms(self, mock_fn_params):
        import time

        from agents.hapax_daimonion.tools import _pending_sms, handle_confirm_send_sms

        _pending_sms.clear()
        _pending_sms["test-123"] = {
            "phone": "+15551234567",
            "message": "Running late",
            "recipient": "Wife",
            "created_at": time.monotonic(),
        }
        mock_fn_params.arguments = {"confirmation_id": "test-123"}

        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {"state": "Pending"}

        mock_cfg = MagicMock()
        mock_cfg.sms_gateway_host = "192.168.1.42:8080"
        mock_cfg.sms_gateway_user = "user"
        mock_cfg.sms_gateway_pass_key = "sms/pass"

        with (
            patch("agents.hapax_daimonion.tools.httpx") as mock_httpx,
            patch("agents.hapax_daimonion.tools._daimonion_config", mock_cfg),
            patch("agents.hapax_daimonion.tools._get_sms_password", return_value="secret"),
        ):
            mock_httpx.post.return_value = mock_response
            await handle_confirm_send_sms(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert result["status"] == "sent"
        assert "test-123" not in _pending_sms

    @pytest.mark.asyncio
    async def test_invalid_confirmation_id(self, mock_fn_params):
        from agents.hapax_daimonion.tools import _pending_sms, handle_confirm_send_sms

        _pending_sms.clear()
        mock_fn_params.arguments = {"confirmation_id": "nonexistent"}

        await handle_confirm_send_sms(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert result["status"] == "error"


class TestAnalyzeSceneHandler:
    @pytest.mark.asyncio
    async def test_captures_and_analyzes(self, mock_fn_params):
        from agents.hapax_daimonion.tools import handle_analyze_scene

        mock_fn_params.arguments = {"question": "What equipment is visible?"}

        mock_webcam = MagicMock()
        mock_webcam.has_camera.return_value = True
        mock_webcam.capture.return_value = "base64_image_data"
        mock_webcam.reset_cooldown = MagicMock()

        mock_screen = MagicMock()
        mock_screen.capture.return_value = "base64_screen_data"
        mock_screen.reset_cooldown = MagicMock()

        with (
            patch("agents.hapax_daimonion.tools._webcam_capturer", mock_webcam),
            patch("agents.hapax_daimonion.tools._screen_capturer", mock_screen),
            patch(
                "agents.hapax_daimonion.tools._vision_analyze",
                return_value="I can see a mixer and two SP-404s",
            ),
        ):
            await handle_analyze_scene(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "mixer" in result.lower() or "SP-404" in result

    @pytest.mark.asyncio
    async def test_no_cameras_available(self, mock_fn_params):
        from agents.hapax_daimonion.tools import handle_analyze_scene

        mock_fn_params.arguments = {}

        mock_webcam = MagicMock()
        mock_webcam.has_camera.return_value = False
        mock_webcam.capture.return_value = None

        mock_screen = MagicMock()
        mock_screen.capture.return_value = None

        with (
            patch("agents.hapax_daimonion.tools._webcam_capturer", mock_webcam),
            patch("agents.hapax_daimonion.tools._screen_capturer", mock_screen),
        ):
            await handle_analyze_scene(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "couldn't capture" in result.lower() or "no images" in result.lower()

    @pytest.mark.asyncio
    async def test_specific_cameras(self, mock_fn_params):
        from agents.hapax_daimonion.tools import handle_analyze_scene

        mock_fn_params.arguments = {
            "cameras": ["hardware"],
            "question": "How is the mic positioned?",
        }

        mock_webcam = MagicMock()
        mock_webcam.capture.return_value = "base64_hw_image"
        mock_webcam.reset_cooldown = MagicMock()

        with (
            patch("agents.hapax_daimonion.tools._webcam_capturer", mock_webcam),
            patch("agents.hapax_daimonion.tools._screen_capturer", None),
            patch(
                "agents.hapax_daimonion.tools._vision_analyze",
                return_value="The mic is angled at 45 degrees",
            ),
        ):
            await handle_analyze_scene(mock_fn_params)

        # Should only capture hardware camera, not screen
        mock_webcam.capture.assert_called_once_with("hardware")
        result = mock_fn_params.result_callback.call_args[0][0]
        assert "mic" in result.lower()


class TestGetSystemStatusHandler:
    @pytest.mark.asyncio
    async def test_returns_status_summary(self, mock_fn_params):
        from agents.hapax_daimonion.tools import handle_get_system_status

        mock_fn_params.arguments = {}

        mock_results = [
            {
                "name": "docker.daemon",
                "group": "docker",
                "status": "healthy",
                "message": "Docker 27.0",
            },
            {"name": "gpu.vram", "group": "gpu", "status": "healthy", "message": "10GB/24GB used"},
        ]

        with patch("agents.hapax_daimonion.tools._run_health_checks", return_value=mock_results):
            await handle_get_system_status(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "docker" in result.lower()

    @pytest.mark.asyncio
    async def test_category_filter(self, mock_fn_params):
        from agents.hapax_daimonion.tools import handle_get_system_status

        mock_fn_params.arguments = {"category": "gpu"}

        mock_results = [
            {"name": "gpu.vram", "group": "gpu", "status": "healthy", "message": "10GB/24GB"},
        ]

        with patch("agents.hapax_daimonion.tools._run_health_checks", return_value=mock_results):
            await handle_get_system_status(mock_fn_params)

        mock_fn_params.result_callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_results(self, mock_fn_params):
        from agents.hapax_daimonion.tools import handle_get_system_status

        mock_fn_params.arguments = {}

        with patch("agents.hapax_daimonion.tools._run_health_checks", return_value=[]):
            await handle_get_system_status(mock_fn_params)

        result = mock_fn_params.result_callback.call_args[0][0]
        assert "no" in result.lower()
