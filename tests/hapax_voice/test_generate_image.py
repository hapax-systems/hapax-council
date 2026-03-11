"""Tests for generate_image tool schema and handler."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from agents.hapax_voice.tools import TOOL_SCHEMAS


def _make_params(arguments: dict) -> SimpleNamespace:
    return SimpleNamespace(arguments=arguments, result_callback=AsyncMock())


_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


class TestGenerateImageSchema:
    def test_generate_image_in_tool_schemas(self):
        names = [s.name for s in TOOL_SCHEMAS]
        assert "generate_image" in names

    def test_prompt_is_required(self):
        schema = next(s for s in TOOL_SCHEMAS if s.name == "generate_image")
        assert "prompt" in schema.required

    def test_camera_source_is_optional(self):
        schema = next(s for s in TOOL_SCHEMAS if s.name == "generate_image")
        assert "camera_source" not in schema.required

    def test_camera_source_enum_values(self):
        schema = next(s for s in TOOL_SCHEMAS if s.name == "generate_image")
        cam = schema.properties["camera_source"]
        assert set(cam["enum"]) == {"operator", "hardware", "screen"}


class TestHandleGenerateImageTextToImage:
    @patch("agents.hapax_voice.tools.subprocess.Popen")
    @patch("agents.hapax_voice.tools._genai_generate_image")
    async def test_saves_png_to_output_dir(self, mock_gen, mock_popen, tmp_path):
        mock_gen.return_value = _FAKE_PNG
        params = _make_params({"prompt": "a red circle"})

        from agents.hapax_voice.tools import handle_generate_image

        with patch("agents.hapax_voice.tools._IMAGE_OUTPUT_DIR", tmp_path):
            await handle_generate_image(params)

        pngs = list(tmp_path.glob("*.png"))
        assert len(pngs) == 1
        assert pngs[0].read_bytes() == _FAKE_PNG

    @patch("agents.hapax_voice.tools.subprocess.Popen")
    @patch("agents.hapax_voice.tools._genai_generate_image")
    async def test_opens_with_xdg_open(self, mock_gen, mock_popen, tmp_path):
        mock_gen.return_value = _FAKE_PNG
        params = _make_params({"prompt": "a red circle"})

        from agents.hapax_voice.tools import handle_generate_image

        with patch("agents.hapax_voice.tools._IMAGE_OUTPUT_DIR", tmp_path):
            await handle_generate_image(params)

        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert args[0] == "xdg-open"
        assert args[1].endswith(".png")

    @patch("agents.hapax_voice.tools.subprocess.Popen")
    @patch("agents.hapax_voice.tools._genai_generate_image")
    async def test_result_callback_reports_success(self, mock_gen, mock_popen, tmp_path):
        mock_gen.return_value = _FAKE_PNG
        params = _make_params({"prompt": "a red circle"})

        from agents.hapax_voice.tools import handle_generate_image

        with patch("agents.hapax_voice.tools._IMAGE_OUTPUT_DIR", tmp_path):
            await handle_generate_image(params)

        result = params.result_callback.call_args[0][0]
        assert result["status"] == "generated"
        assert "path" in result

    @patch("agents.hapax_voice.tools._genai_generate_image")
    async def test_no_image_returns_error(self, mock_gen, tmp_path):
        mock_gen.return_value = None
        params = _make_params({"prompt": "a red circle"})

        from agents.hapax_voice.tools import handle_generate_image

        with patch("agents.hapax_voice.tools._IMAGE_OUTPUT_DIR", tmp_path):
            await handle_generate_image(params)

        result = params.result_callback.call_args[0][0]
        assert "error" in result.get("status", "") or "error" in str(result)


class TestHandleGenerateImageWithCamera:
    @patch("agents.hapax_voice.tools.subprocess.Popen")
    @patch("agents.hapax_voice.tools._genai_generate_image")
    async def test_captures_from_webcam_when_operator(self, mock_gen, mock_popen, tmp_path):
        mock_gen.return_value = _FAKE_PNG
        params = _make_params({"prompt": "make it a cartoon", "camera_source": "operator"})

        import agents.hapax_voice.tools as tools_mod

        mock_cam = MagicMock()
        mock_cam.capture.return_value = "base64data"
        original_cam = tools_mod._webcam_capturer
        tools_mod._webcam_capturer = mock_cam

        try:
            with patch.object(tools_mod, "_IMAGE_OUTPUT_DIR", tmp_path):
                await tools_mod.handle_generate_image(params)
            mock_cam.capture.assert_called_once_with("operator")
        finally:
            tools_mod._webcam_capturer = original_cam

    @patch("agents.hapax_voice.tools.subprocess.Popen")
    @patch("agents.hapax_voice.tools._genai_generate_image")
    async def test_captures_from_screen_capturer(self, mock_gen, mock_popen, tmp_path):
        mock_gen.return_value = _FAKE_PNG
        params = _make_params({"prompt": "improve the lighting", "camera_source": "screen"})

        import agents.hapax_voice.tools as tools_mod

        mock_screen = MagicMock()
        mock_screen.capture.return_value = "screen_b64"
        original_screen = tools_mod._screen_capturer
        tools_mod._screen_capturer = mock_screen

        try:
            with patch.object(tools_mod, "_IMAGE_OUTPUT_DIR", tmp_path):
                await tools_mod.handle_generate_image(params)
            mock_screen.capture.assert_called_once()
        finally:
            tools_mod._screen_capturer = original_screen

    @patch("agents.hapax_voice.tools.subprocess.Popen")
    @patch("agents.hapax_voice.tools._genai_generate_image")
    async def test_no_camera_skips_capture(self, mock_gen, mock_popen, tmp_path):
        mock_gen.return_value = _FAKE_PNG
        params = _make_params({"prompt": "album art for boom bap"})

        import agents.hapax_voice.tools as tools_mod

        with patch.object(tools_mod, "_IMAGE_OUTPUT_DIR", tmp_path):
            await tools_mod.handle_generate_image(params)

        result = params.result_callback.call_args[0][0]
        assert result["status"] == "generated"

    @patch("agents.hapax_voice.tools.subprocess.Popen")
    @patch("agents.hapax_voice.tools._genai_generate_image")
    async def test_camera_unavailable_still_generates(self, mock_gen, mock_popen, tmp_path):
        mock_gen.return_value = _FAKE_PNG
        params = _make_params({"prompt": "edit this", "camera_source": "operator"})

        import agents.hapax_voice.tools as tools_mod

        original_cam = tools_mod._webcam_capturer
        tools_mod._webcam_capturer = None

        try:
            with patch.object(tools_mod, "_IMAGE_OUTPUT_DIR", tmp_path):
                await tools_mod.handle_generate_image(params)
            result = params.result_callback.call_args[0][0]
            assert result["status"] == "generated"
        finally:
            tools_mod._webcam_capturer = original_cam


class TestGenerateImageRegistration:
    def test_register_includes_generate_image(self):
        from unittest.mock import MagicMock

        from agents.hapax_voice.config import VoiceConfig
        from agents.hapax_voice.tools import register_tool_handlers

        mock_llm = MagicMock()
        config = VoiceConfig()
        register_tool_handlers(mock_llm, config)

        registered = [call[0][0] for call in mock_llm.register_function.call_args_list]
        assert "generate_image" in registered

    def test_total_tool_count(self):
        from unittest.mock import MagicMock

        from agents.hapax_voice.config import VoiceConfig
        from agents.hapax_voice.tools import register_tool_handlers

        mock_llm = MagicMock()
        config = VoiceConfig()
        register_tool_handlers(mock_llm, config)

        assert mock_llm.register_function.call_count == 14


class TestGenaiGenerateImage:
    def test_returns_none_on_empty_response(self):
        with patch("google.genai.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_response = MagicMock()
            mock_response.generated_images = []
            mock_client.models.generate_images.return_value = mock_response

            from agents.hapax_voice.tools import _genai_generate_image

            result = _genai_generate_image("test prompt")
            assert result is None

    def test_returns_none_on_exception(self):
        with patch("google.genai.Client") as mock_client_cls:
            mock_client_cls.side_effect = Exception("API error")

            from agents.hapax_voice.tools import _genai_generate_image

            result = _genai_generate_image("test prompt")
            assert result is None

    def test_returns_image_bytes_on_success(self):
        with patch("google.genai.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            fake_image = MagicMock()
            fake_image.image.image_bytes = b"fake-png-bytes"
            mock_response = MagicMock()
            mock_response.generated_images = [fake_image]
            mock_client.models.generate_images.return_value = mock_response

            from agents.hapax_voice.tools import _genai_generate_image

            result = _genai_generate_image("a red circle")
            assert result == b"fake-png-bytes"


class TestHandleGenerateImageErrors:
    @patch("agents.hapax_voice.tools._genai_generate_image")
    async def test_api_exception_returns_error(self, mock_gen, tmp_path):
        mock_gen.side_effect = Exception("Network timeout")
        params = _make_params({"prompt": "anything"})

        from agents.hapax_voice.tools import handle_generate_image

        with patch("agents.hapax_voice.tools._IMAGE_OUTPUT_DIR", tmp_path):
            await handle_generate_image(params)

        result = params.result_callback.call_args[0][0]
        assert "error" in result.get("status", "")

    @patch("agents.hapax_voice.tools.subprocess.Popen")
    @patch("agents.hapax_voice.tools._genai_generate_image")
    async def test_timestamp_in_filename(self, mock_gen, mock_popen, tmp_path):
        mock_gen.return_value = _FAKE_PNG
        params = _make_params({"prompt": "test"})

        from agents.hapax_voice.tools import handle_generate_image

        with patch("agents.hapax_voice.tools._IMAGE_OUTPUT_DIR", tmp_path):
            await handle_generate_image(params)

        pngs = list(tmp_path.glob("*.png"))
        assert len(pngs) == 1
        stem = pngs[0].stem
        assert len(stem) == 15  # YYYYMMDD-HHMMSS
        assert stem[8] == "-"

    @patch("agents.hapax_voice.tools.subprocess.Popen")
    @patch("agents.hapax_voice.tools._genai_generate_image")
    async def test_output_dir_created_if_missing(self, mock_gen, mock_popen, tmp_path):
        mock_gen.return_value = _FAKE_PNG
        params = _make_params({"prompt": "test"})
        nested = tmp_path / "sub" / "dir"

        from agents.hapax_voice.tools import handle_generate_image

        with patch("agents.hapax_voice.tools._IMAGE_OUTPUT_DIR", nested):
            await handle_generate_image(params)

        assert nested.exists()
        assert len(list(nested.glob("*.png"))) == 1
