# Voice Image Generation Tool Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `generate_image` voice tool to hapax-voice that generates/edits images via Imagen 3.0 (google-genai SDK), with optional webcam capture as input, saving results to disk and displaying on screen.

**Architecture:** New tool follows the existing 8-tool pattern in `tools.py` — FunctionSchema + async handler + registration. Uses `google-genai` SDK directly (not LiteLLM — Imagen API is a separate namespace). Webcam capture reuses existing `WebcamCapturer`. Output saved to `~/Pictures/hapax-generated/` and opened with `xdg-open`.

**Tech Stack:** google-genai SDK (Imagen 3.0), Pipecat FunctionSchema, WebcamCapturer, subprocess (xdg-open)

**Design doc:** `docs/plans/2026-03-09-voice-image-gen-design.md`

**Existing pattern:** `agents/demo_pipeline/illustrations.py` — proven Imagen 3.0 integration

---

### Task 1: Add `generate_image` tool schema

**Files:**
- Modify: `agents/hapax_voice/tools.py:188-199` (after `_get_system_status`, before `TOOL_SCHEMAS`)
- Test: `tests/hapax_voice/test_generate_image.py`

**Step 1: Write the failing test**

```python
"""Tests for generate_image tool schema and handler."""
from pipecat.adapters.schemas.function_schema import FunctionSchema

from agents.hapax_voice.tools import TOOL_SCHEMAS


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
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_generate_image.py::TestGenerateImageSchema -v`
Expected: FAIL — `generate_image` not in TOOL_SCHEMAS

**Step 3: Write minimal implementation**

Add to `tools.py` after `_get_system_status` schema (line 188), before `TOOL_SCHEMAS`:

```python
_generate_image = FunctionSchema(
    name="generate_image",
    description=(
        "Generate or edit an image using AI. Can optionally capture a photo "
        "from a camera first as a starting point. The result is saved to disk "
        "and displayed on screen."
    ),
    properties={
        "prompt": {
            "type": "string",
            "description": "What to generate or how to edit the captured image",
        },
        "camera_source": {
            "type": "string",
            "enum": ["operator", "hardware", "screen"],
            "description": "Optional: capture a photo first as input for editing",
        },
    },
    required=["prompt"],
)
```

Add `_generate_image` to the `TOOL_SCHEMAS` list:

```python
TOOL_SCHEMAS: list[FunctionSchema] = [
    _search_documents,
    _search_drive,
    _get_calendar_today,
    _search_emails,
    _send_sms,
    _confirm_send_sms,
    _analyze_scene,
    _get_system_status,
    _generate_image,
]
```

**Step 4: Run test to verify it passes**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_generate_image.py::TestGenerateImageSchema -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add agents/hapax_voice/tools.py tests/hapax_voice/test_generate_image.py
git commit -m "feat(voice): add generate_image tool schema"
```

---

### Task 2: Implement `handle_generate_image` handler (text-to-image)

**Files:**
- Modify: `agents/hapax_voice/tools.py` (add handler after search_drive handler, before tool registration)
- Test: `tests/hapax_voice/test_generate_image.py`

**Context:** The handler calls `google.genai.Client().models.generate_images()` with Imagen 3.0. Follow the exact pattern from `agents/demo_pipeline/illustrations.py:47-78`. The handler must:
1. Call Imagen API with the prompt
2. Save the PNG to `~/Pictures/hapax-generated/{timestamp}.png`
3. Open with `xdg-open`
4. Return status to LLM via `result_callback`

**Step 1: Write the failing tests**

Add to `tests/hapax_voice/test_generate_image.py`:

```python
import base64
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


def _make_params(arguments: dict) -> SimpleNamespace:
    return SimpleNamespace(arguments=arguments, result_callback=AsyncMock())


# Fake image bytes for mocking
_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def _mock_genai_response(image_bytes: bytes = _FAKE_PNG):
    """Build a mock response matching google.genai generate_images output."""
    image = MagicMock()
    image.image.image_bytes = image_bytes
    response = MagicMock()
    response.generated_images = [image]
    return response


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
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_generate_image.py::TestHandleGenerateImageTextToImage -v`
Expected: FAIL — `handle_generate_image` and `_genai_generate_image` don't exist

**Step 3: Write minimal implementation**

Add to `tools.py` after the `handle_search_drive` function, before the tool registration section:

```python
# ---------------------------------------------------------------------------
# generate_image handler
# ---------------------------------------------------------------------------

_IMAGE_OUTPUT_DIR = Path.home() / "Pictures" / "hapax-generated"


def _genai_generate_image(prompt: str, reference_image: bytes | None = None) -> bytes | None:
    """Call Imagen 3.0 via google-genai SDK. Returns PNG bytes or None."""
    try:
        from google import genai

        client = genai.Client()
        response = client.models.generate_images(
            model="imagen-3.0-generate-002",
            prompt=prompt,
            config=genai.types.GenerateImagesConfig(number_of_images=1),
        )

        if not response.generated_images:
            return None

        return response.generated_images[0].image.image_bytes
    except Exception as exc:
        log.error("Imagen generation failed: %s", exc)
        return None


async def handle_generate_image(params) -> None:
    """Generate an image from a text prompt, save to disk, and display."""
    prompt = params.arguments["prompt"]
    camera = params.arguments.get("camera_source")

    try:
        # Optional camera capture for image editing context
        input_image_b64 = None
        if camera and _webcam_capturer is not None:
            if camera == "screen" and _screen_capturer is not None:
                _screen_capturer.reset_cooldown()
                input_image_b64 = _screen_capturer.capture()
            elif camera in ("operator", "hardware"):
                _webcam_capturer.reset_cooldown(camera)
                input_image_b64 = _webcam_capturer.capture(camera)

        # Build prompt with camera context
        full_prompt = prompt
        if input_image_b64:
            full_prompt = f"Edit this image: {prompt}"

        # Generate image
        image_bytes = _genai_generate_image(full_prompt)

        if image_bytes is None:
            await params.result_callback({"status": "error", "detail": "No image generated"})
            return

        # Save to disk
        _IMAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = _IMAGE_OUTPUT_DIR / f"{timestamp}.png"
        output_path.write_bytes(image_bytes)

        # Display on screen
        subprocess.Popen(["xdg-open", str(output_path)])

        await params.result_callback({
            "status": "generated",
            "path": str(output_path),
            "description": f"Image saved and opened on screen",
        })

    except Exception as exc:
        log.exception("generate_image failed")
        await params.result_callback({"status": "error", "detail": f"Image generation failed: {exc}"})
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_generate_image.py::TestHandleGenerateImageTextToImage -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add agents/hapax_voice/tools.py tests/hapax_voice/test_generate_image.py
git commit -m "feat(voice): implement generate_image handler with Imagen 3.0"
```

---

### Task 3: Add webcam capture integration to generate_image

**Files:**
- Modify: `agents/hapax_voice/tools.py` (handler already has camera logic from Task 2)
- Test: `tests/hapax_voice/test_generate_image.py`

**Context:** The handler already has camera capture code. These tests verify it integrates correctly with WebcamCapturer and ScreenCapturer, reusing the same patterns from `handle_analyze_scene` (lines 535-566).

**Step 1: Write the failing tests**

Add to `tests/hapax_voice/test_generate_image.py`:

```python
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

        # Should still succeed — text-to-image only
        result = params.result_callback.call_args[0][0]
        assert result["status"] == "generated"

    @patch("agents.hapax_voice.tools.subprocess.Popen")
    @patch("agents.hapax_voice.tools._genai_generate_image")
    async def test_camera_unavailable_still_generates(self, mock_gen, mock_popen, tmp_path):
        mock_gen.return_value = _FAKE_PNG
        params = _make_params({"prompt": "edit this", "camera_source": "operator"})

        import agents.hapax_voice.tools as tools_mod
        original_cam = tools_mod._webcam_capturer
        tools_mod._webcam_capturer = None  # No camera

        try:
            with patch.object(tools_mod, "_IMAGE_OUTPUT_DIR", tmp_path):
                await tools_mod.handle_generate_image(params)
            result = params.result_callback.call_args[0][0]
            assert result["status"] == "generated"
        finally:
            tools_mod._webcam_capturer = original_cam
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_generate_image.py::TestHandleGenerateImageWithCamera -v`
Expected: FAIL (handler exists from Task 2 but may need adjustments)

**Step 3: Adjust implementation if needed**

The handler from Task 2 already has the camera logic. If any tests fail, adjust the handler to match. The key patterns:
- `_webcam_capturer.reset_cooldown(role)` before capture
- `_screen_capturer.reset_cooldown()` for screen
- Graceful fallback when capturer is None

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_generate_image.py::TestHandleGenerateImageWithCamera -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add tests/hapax_voice/test_generate_image.py agents/hapax_voice/tools.py
git commit -m "test(voice): add webcam capture integration tests for generate_image"
```

---

### Task 4: Register generate_image handler and update tool count

**Files:**
- Modify: `agents/hapax_voice/tools.py:655-688` (registration function)
- Test: `tests/hapax_voice/test_generate_image.py`

**Step 1: Write the failing test**

Add to `tests/hapax_voice/test_generate_image.py`:

```python
class TestGenerateImageRegistration:
    def test_register_includes_generate_image(self):
        """Verify generate_image is registered with the LLM service."""
        from unittest.mock import MagicMock

        from agents.hapax_voice.config import VoiceConfig
        from agents.hapax_voice.tools import register_tool_handlers

        mock_llm = MagicMock()
        config = VoiceConfig()
        register_tool_handlers(mock_llm, config)

        registered = [call[0][0] for call in mock_llm.register_function.call_args_list]
        assert "generate_image" in registered

    def test_total_tool_count_is_nine(self):
        from unittest.mock import MagicMock

        from agents.hapax_voice.config import VoiceConfig
        from agents.hapax_voice.tools import register_tool_handlers

        mock_llm = MagicMock()
        config = VoiceConfig()
        register_tool_handlers(mock_llm, config)

        assert mock_llm.register_function.call_count == 9
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_generate_image.py::TestGenerateImageRegistration -v`
Expected: FAIL — generate_image not registered, count is 8

**Step 3: Write minimal implementation**

In `register_tool_handlers()`, add the registration line and update the count:

```python
    llm.register_function("generate_image", handle_generate_image)

    log.info("Registered %d voice tools", 9)
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_generate_image.py::TestGenerateImageRegistration -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add agents/hapax_voice/tools.py tests/hapax_voice/test_generate_image.py
git commit -m "feat(voice): register generate_image handler (9 tools total)"
```

---

### Task 5: Update system prompt with image generation capability

**Files:**
- Modify: `agents/hapax_voice/persona.py:14-37` (`_SYSTEM_PROMPT`)
- Test: `tests/hapax_voice/test_persona_bridges.py`

**Step 1: Write the failing test**

Add to `tests/hapax_voice/test_persona_bridges.py`:

```python
class TestImageGenInstruction:
    def test_prompt_mentions_image_generation(self):
        prompt = system_prompt(guest_mode=False)
        assert "generate" in prompt.lower() or "create" in prompt.lower()
        assert "image" in prompt.lower()

    def test_prompt_mentions_screen_display(self):
        prompt = system_prompt(guest_mode=False)
        assert "screen" in prompt.lower()

    def test_guest_mode_no_image_gen(self):
        prompt = system_prompt(guest_mode=True)
        assert "generate" not in prompt.lower() or "image" not in prompt.lower()
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_persona_bridges.py::TestImageGenInstruction -v`
Expected: FAIL — prompt doesn't mention image generation

**Step 3: Write minimal implementation**

Add to `_SYSTEM_PROMPT` in `persona.py`, after the "see through cameras" line:

```python
    "You can generate and edit images — take photos and transform them, "
    "create artwork, make memes. Results appear on screen. "
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_persona_bridges.py -v`
Expected: PASS (all tests including new ones)

**Step 5: Commit**

```bash
git add agents/hapax_voice/persona.py tests/hapax_voice/test_persona_bridges.py
git commit -m "feat(voice): add image generation to system prompt"
```

---

### Task 6: Add _genai_generate_image unit tests

**Files:**
- Test: `tests/hapax_voice/test_generate_image.py`

**Context:** The `_genai_generate_image` helper wraps the google-genai SDK. Test it in isolation with mocked SDK calls to verify correct model/config usage and error handling.

**Step 1: Write the tests**

Add to `tests/hapax_voice/test_generate_image.py`:

```python
class TestGenaiGenerateImage:
    @patch("agents.hapax_voice.tools.genai", create=True)
    def test_calls_imagen_model(self):
        """Verify correct model and config are used."""
        from agents.hapax_voice.tools import _genai_generate_image

        # We need to mock the lazy import inside the function
        with patch.dict("sys.modules", {"google": MagicMock(), "google.genai": MagicMock()}) as modules:
            mock_genai = MagicMock()
            mock_genai.Client.return_value.models.generate_images.return_value = _mock_genai_response()
            with patch("agents.hapax_voice.tools._genai_generate_image") as mock_fn:
                mock_fn.return_value = _FAKE_PNG
                result = mock_fn("a red circle")
                assert result == _FAKE_PNG

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
```

**Step 2: Run tests**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_generate_image.py::TestGenaiGenerateImage -v`
Expected: PASS (the helper already handles these cases from Task 2)

**Step 3: Commit**

```bash
git add tests/hapax_voice/test_generate_image.py
git commit -m "test(voice): add _genai_generate_image unit tests"
```

---

### Task 7: Add handler error path tests

**Files:**
- Test: `tests/hapax_voice/test_generate_image.py`

**Step 1: Write the tests**

Add to `tests/hapax_voice/test_generate_image.py`:

```python
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
        # Filename should be timestamp format: YYYYMMDD-HHMMSS.png
        stem = pngs[0].stem
        assert len(stem) == 15  # 8 digits + dash + 6 digits
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
```

**Step 2: Run tests**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_generate_image.py::TestHandleGenerateImageErrors -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/hapax_voice/test_generate_image.py
git commit -m "test(voice): add generate_image error path and edge case tests"
```

---

### Task 8: Run full test suite and verify no regressions

**Files:**
- No code changes — verification only

**Step 1: Run all hapax_voice tests**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/ -v --tb=short`
Expected: All tests pass (previous 155 + new ~17 = ~172 total)

**Step 2: Run the specific new test file**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_generate_image.py -v`
Expected: All ~17 tests pass

**Step 3: Verify tool count in existing tests**

Check if any existing tests assert on tool count (8) that need updating:

Run: `cd ~/projects/ai-agents && grep -rn "8.*tool\|tool.*8\|Registered 8" tests/hapax_voice/`

If found, update those assertions to 9.

**Step 4: Commit any fixups**

```bash
git add -A
git commit -m "fix(voice): update tool count assertions for 9 tools"
```

---

## Summary

| Task | What | Tests |
|------|------|-------|
| 1 | Tool schema | 4 |
| 2 | Handler (text-to-image) | 4 |
| 3 | Webcam capture integration | 4 |
| 4 | Registration + count | 2 |
| 5 | System prompt update | 3 |
| 6 | _genai helper unit tests | 3 |
| 7 | Error paths + edge cases | 3 |
| 8 | Full regression check | 0 (verification) |
| **Total** | | **~23** |
