import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_daimonion.screen_analyzer import ScreenAnalyzer
from agents.hapax_daimonion.screen_models import ScreenAnalysis
from shared.fix_capabilities.background_admission import BackgroundCapabilityAdmission


def _admission(*, admitted: bool = True) -> BackgroundCapabilityAdmission:
    return BackgroundCapabilityAdmission(
        capability_name="hapax_daimonion.screen_analyzer.vision",
        route_id="api.headless.provider_gateway",
        model_alias="gemini-flash",
        admitted=admitted,
        denied_reason=None if admitted else "provider_gateway_evidence_absent",
        reason_codes=("policy_launch",) if admitted else ("provider_gateway_evidence_absent",),
        task_id="task-x",
        authority_case="CASE-CAPACITY-ROUTING-001",
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
        route_decision_id="rd-test",
    )


@pytest.mark.asyncio
async def test_analyzer_returns_screen_analysis():
    analyzer = ScreenAnalyzer(model="gemini-flash", admission_gate=lambda: _admission())

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(
        {
            "app": "foot",
            "context": "Running pytest",
            "summary": "Terminal showing test output with 3 failures.",
            "issues": [{"severity": "error", "description": "3 tests failed", "confidence": 0.92}],
            "suggestions": ["Check test_pipeline.py for assertion errors"],
            "keywords": ["pytest", "test failure"],
        }
    )

    with patch("agents.hapax_daimonion.screen_analyzer.AsyncOpenAI") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await analyzer.analyze("base64encodedimage==")

    assert isinstance(result, ScreenAnalysis)
    assert result.app == "foot"
    assert len(result.issues) == 1
    assert result.issues[0].confidence == 0.92


@pytest.mark.asyncio
async def test_analyzer_returns_none_on_failure():
    analyzer = ScreenAnalyzer(model="gemini-flash", admission_gate=lambda: _admission())

    with patch("agents.hapax_daimonion.screen_analyzer.AsyncOpenAI") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API down"))
        mock_client_cls.return_value = mock_client

        result = await analyzer.analyze("base64data==")

    assert result is None


@pytest.mark.asyncio
async def test_analyzer_denies_before_openai_client():
    analyzer = ScreenAnalyzer(
        model="gemini-flash", admission_gate=lambda: _admission(admitted=False)
    )

    with patch("agents.hapax_daimonion.screen_analyzer.AsyncOpenAI") as mock_client_cls:
        result = await analyzer.analyze("base64data==")

    assert result is None
    mock_client_cls.assert_not_called()


def test_analyzer_loads_static_context(tmp_path):
    ctx_file = tmp_path / "screen_context.md"
    ctx_file.write_text("# System Context\nQdrant on 6333\n")

    analyzer = ScreenAnalyzer(model="gemini-flash", context_path=ctx_file)
    assert "Qdrant on 6333" in analyzer._system_prompt


def test_analyzer_works_without_context_file():
    analyzer = ScreenAnalyzer(model="gemini-flash", context_path="/nonexistent/path.md")
    assert "screen" in analyzer._system_prompt.lower()


def test_analyzer_reuses_client():
    """AsyncOpenAI client should be created once and reused."""
    analyzer = ScreenAnalyzer(model="gemini-flash")

    with patch("agents.hapax_daimonion.screen_analyzer.AsyncOpenAI") as mock_cls:
        mock_cls.return_value = MagicMock()
        client1 = analyzer._get_client()
        client2 = analyzer._get_client()

    assert client1 is client2
    assert mock_cls.call_count == 1


def test_analyzer_reload_context(tmp_path):
    """reload_context should rebuild the system prompt."""
    ctx_file = tmp_path / "screen_context.md"
    ctx_file.write_text("# V1\nOriginal context\n")

    analyzer = ScreenAnalyzer(model="gemini-flash", context_path=ctx_file)
    assert "Original context" in analyzer._system_prompt

    ctx_file.write_text("# V2\nUpdated context\n")
    analyzer.reload_context(ctx_file)
    assert "Updated context" in analyzer._system_prompt
    assert "Original context" not in analyzer._system_prompt
