"""Tests for WorkspaceAnalyzer (multi-image Gemini Flash)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_daimonion.screen_models import WorkspaceAnalysis
from agents.hapax_daimonion.workspace_analyzer import WorkspaceAnalyzer


@pytest.mark.asyncio
async def test_analyzer_returns_workspace_analysis():
    analyzer = WorkspaceAnalyzer(model="gemini-flash")

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(
        {
            "app": "foot",
            "context": "Running pytest",
            "summary": "Terminal showing test output.",
            "issues": [],
            "suggestions": [],
            "keywords": ["pytest"],
            "operator_present": True,
            "operator_activity": "typing",
            "operator_attention": "screen",
            "gear_state": [
                {
                    "device": "MPC Live III",
                    "powered": True,
                    "display_content": "Song mode",
                    "notes": "",
                }
            ],
            "workspace_change": False,
        }
    )

    with patch("agents.hapax_daimonion.workspace_analyzer.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        result = await analyzer.analyze(
            screen_b64="screen-data",
            operator_b64="operator-data",
            hardware_b64="hardware-data",
        )

    assert isinstance(result, WorkspaceAnalysis)
    assert result.app == "foot"
    assert result.operator_present is True
    assert result.operator_activity == "typing"
    assert len(result.gear_state) == 1
    assert result.gear_state[0].device == "MPC Live III"


@pytest.mark.asyncio
async def test_analyzer_works_with_screen_only():
    """Should work with just a screenshot (cameras unavailable)."""
    analyzer = WorkspaceAnalyzer(model="gemini-flash")

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(
        {
            "app": "firefox",
            "context": "Browsing docs",
            "summary": "Web page.",
            "issues": [],
            "suggestions": [],
            "keywords": [],
        }
    )

    with patch("agents.hapax_daimonion.workspace_analyzer.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        result = await analyzer.analyze(screen_b64="screen-data")

    assert isinstance(result, WorkspaceAnalysis)
    assert result.operator_present is None  # No camera data
    assert result.gear_state == []


@pytest.mark.asyncio
async def test_analyzer_returns_none_on_failure():
    analyzer = WorkspaceAnalyzer(model="gemini-flash")

    with patch("agents.hapax_daimonion.workspace_analyzer.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API down"))
        mock_cls.return_value = mock_client

        result = await analyzer.analyze(screen_b64="data")

    assert result is None


def test_analyzer_builds_multi_image_messages():
    """Verify the message array contains labeled images."""
    analyzer = WorkspaceAnalyzer(model="gemini-flash")
    messages = analyzer._build_messages(
        screen_b64="s",
        operator_b64="o",
        hardware_b64="h",
        extra_context=None,
    )
    user_content = messages[1]["content"]
    # Should have 3 image blocks + 3 text labels + 1 instruction
    text_blocks = [b for b in user_content if b["type"] == "text"]
    image_blocks = [b for b in user_content if b["type"] == "image_url"]
    assert len(image_blocks) == 3
    assert any("SCREENSHOT" in b["text"] for b in text_blocks)
    assert any("OPERATOR" in b["text"] for b in text_blocks)
    assert any("HARDWARE" in b["text"] for b in text_blocks)


def test_analyzer_omits_missing_cameras():
    """Message array should only include provided images."""
    analyzer = WorkspaceAnalyzer(model="gemini-flash")
    messages = analyzer._build_messages(
        screen_b64="s",
        operator_b64=None,
        hardware_b64=None,
        extra_context=None,
    )
    user_content = messages[1]["content"]
    image_blocks = [b for b in user_content if b["type"] == "image_url"]
    assert len(image_blocks) == 1


# ---------------------------------------------------------------------------
# Failure-mode tests
# ---------------------------------------------------------------------------


def _make_mock_response(content: str) -> MagicMock:
    """Create a mock API response with the given content string."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    return resp


async def _run_analyze(content: str) -> object:
    """Helper: patch AsyncOpenAI, call analyze(), return result."""
    analyzer = WorkspaceAnalyzer(model="gemini-flash")
    mock_response = _make_mock_response(content)
    with patch("agents.hapax_daimonion.workspace_analyzer.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client
        return await analyzer.analyze(screen_b64="data")


@pytest.mark.asyncio
async def test_analyzer_handles_truncated_json():
    """API returns truncated JSON (max_tokens cutoff). Should return None."""
    truncated = '{"app": "vscode", "context": "editing", "summary": "cod'
    result = await _run_analyze(truncated)
    assert result is None


@pytest.mark.asyncio
async def test_analyzer_handles_non_json_response():
    """API returns plain text instead of JSON. Should return None."""
    result = await _run_analyze("I can see a screen with a terminal open.")
    assert result is None


@pytest.mark.asyncio
async def test_analyzer_handles_empty_response():
    """API returns empty string. Should return None."""
    result = await _run_analyze("")
    assert result is None


@pytest.mark.asyncio
async def test_analyzer_strips_markdown_json_fence():
    """API wraps JSON in ```json ... ```. Should parse correctly."""
    payload = json.dumps(
        {
            "app": "firefox",
            "context": "browsing",
            "summary": "Web page open.",
            "issues": [],
            "suggestions": [],
            "keywords": [],
        }
    )
    content = f"```json\n{payload}\n```"
    result = await _run_analyze(content)
    assert isinstance(result, WorkspaceAnalysis)
    assert result.app == "firefox"


@pytest.mark.asyncio
async def test_analyzer_strips_markdown_plain_fence():
    """API wraps JSON in ``` ... ``` (no language tag). Should parse correctly."""
    payload = json.dumps(
        {
            "app": "foot",
            "context": "running tests",
            "summary": "Terminal output.",
            "issues": [],
            "suggestions": [],
            "keywords": [],
        }
    )
    content = f"```\n{payload}\n```"
    result = await _run_analyze(content)
    assert isinstance(result, WorkspaceAnalysis)
    assert result.app == "foot"


@pytest.mark.asyncio
async def test_analyzer_handles_malformed_issue():
    """Issue missing required 'description' field. Issue(**i) raises TypeError → None."""
    payload = json.dumps(
        {
            "app": "vscode",
            "context": "editing",
            "summary": "Editor open.",
            "issues": [{"severity": "error", "confidence": 0.9}],  # no description
            "suggestions": [],
            "keywords": [],
        }
    )
    result = await _run_analyze(payload)
    assert result is None


@pytest.mark.asyncio
async def test_analyzer_handles_null_gear_state():
    """gear_state is null. The `or []` guard should handle it."""
    payload = json.dumps(
        {
            "app": "vscode",
            "context": "editing",
            "summary": "Editor open.",
            "issues": [],
            "suggestions": [],
            "keywords": [],
            "gear_state": None,
        }
    )
    result = await _run_analyze(payload)
    assert isinstance(result, WorkspaceAnalysis)
    assert result.gear_state == []


@pytest.mark.asyncio
async def test_analyzer_handles_gear_state_with_null_item():
    """gear_state contains a null entry. Iterating calls .get() on None → crash → None."""
    payload = json.dumps(
        {
            "app": "vscode",
            "context": "editing",
            "summary": "Editor open.",
            "issues": [],
            "suggestions": [],
            "keywords": [],
            "gear_state": [
                None,
                {"device": "SP-404", "powered": True, "display_content": "", "notes": ""},
            ],
        }
    )
    result = await _run_analyze(payload)
    assert result is None


@pytest.mark.asyncio
async def test_analyzer_handles_extra_unknown_fields():
    """API returns extra fields not in the schema. Should be silently ignored."""
    payload = json.dumps(
        {
            "app": "firefox",
            "context": "browsing",
            "summary": "Web page.",
            "issues": [],
            "suggestions": [],
            "keywords": [],
            "mood": "chill",
            "weather": "sunny",
        }
    )
    result = await _run_analyze(payload)
    assert isinstance(result, WorkspaceAnalysis)
    assert result.app == "firefox"
    assert not hasattr(result, "mood")


@pytest.mark.asyncio
async def test_analyzer_handles_missing_optional_fields():
    """API returns only app. All other fields should get defaults."""
    payload = json.dumps({"app": "vscode"})
    result = await _run_analyze(payload)
    assert isinstance(result, WorkspaceAnalysis)
    assert result.app == "vscode"
    assert result.context == ""
    assert result.summary == ""
    assert result.issues == []
    assert result.suggestions == []
    assert result.keywords == []
    assert result.operator_present is None
    assert result.operator_activity == "unknown"
    assert result.operator_attention == "unknown"
    assert result.gear_state == []
    assert result.workspace_change is False


@pytest.mark.asyncio
async def test_analyzer_handles_issue_with_extra_fields():
    """Issue with extra kwargs. Issue dataclass rejects unknown fields → None."""
    payload = json.dumps(
        {
            "app": "vscode",
            "context": "editing",
            "summary": "Editor open.",
            "issues": [
                {
                    "severity": "error",
                    "description": "build failed",
                    "confidence": 0.9,
                    "extra": "field",
                }
            ],
            "suggestions": [],
            "keywords": [],
        }
    )
    result = await _run_analyze(payload)
    assert result is None


def test_analyzer_context_file_missing(tmp_path):
    """Context file doesn't exist. Prompt should still be valid."""
    missing = tmp_path / "nonexistent" / "context.md"
    analyzer = WorkspaceAnalyzer(model="gemini-flash", context_path=missing)
    assert len(analyzer._system_prompt) > 0
    # Should contain the base prompt but not the context header
    assert "workspace awareness system" in analyzer._system_prompt
    assert "System Knowledge" not in analyzer._system_prompt


def test_analyzer_context_file_unreadable(tmp_path):
    """Context file exists but is unreadable. Should log warning and continue."""
    ctx_file = tmp_path / "context.md"
    ctx_file.write_text("some context")
    ctx_file.chmod(0o000)
    try:
        analyzer = WorkspaceAnalyzer(model="gemini-flash", context_path=ctx_file)
        assert len(analyzer._system_prompt) > 0
        assert "workspace awareness system" in analyzer._system_prompt
    finally:
        # Restore permissions so tmp_path cleanup works
        ctx_file.chmod(0o644)
