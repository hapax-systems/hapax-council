"""Tests for scripts/phase-5-post-swap-smoke.py — Phase 5 go/no-go gate.

Live LLM calls are mocked via unittest.mock to avoid requiring a
running LiteLLM gateway or consuming real API quota. The pure
helper functions (percentile, check_capable_tier, grading parse)
are tested directly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "phase-5-post-swap-smoke.py"
_spec = importlib.util.spec_from_file_location("phase_5_post_swap_smoke", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
smoke = importlib.util.module_from_spec(_spec)
sys.modules["phase_5_post_swap_smoke"] = smoke
_spec.loader.exec_module(smoke)  # type: ignore[union-attr]


class TestPercentile:
    def test_empty_list_returns_zero(self) -> None:
        assert smoke.percentile([], 0.5) == 0.0

    def test_single_value(self) -> None:
        assert smoke.percentile([100.0], 0.5) == 100.0
        assert smoke.percentile([100.0], 0.95) == 100.0

    def test_p50_of_odd_list(self) -> None:
        assert smoke.percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.5) == 3.0

    def test_p95_of_sorted_list(self) -> None:
        # 100 values — p95 should be at index 94-95 (interpolated)
        values = [float(i) for i in range(100)]
        result = smoke.percentile(values, 0.95)
        assert 93.0 <= result <= 96.0


class TestCheckCapableTier:
    def test_claude_opus_passes(self) -> None:
        # Patch MODELS in the imported shared.config module
        with patch.dict("shared.config.MODELS", {"capable": "claude-opus-4-6"}, clear=False):
            ok, value = smoke.check_capable_tier()
        assert ok is True
        assert value == "claude-opus-4-6"

    def test_anthropic_prefix_passes(self) -> None:
        with patch.dict(
            "shared.config.MODELS",
            {"capable": "anthropic/claude-opus-4-6"},
            clear=False,
        ):
            ok, value = smoke.check_capable_tier()
        assert ok is True

    def test_non_claude_fails(self) -> None:
        with patch.dict(
            "shared.config.MODELS",
            {"capable": "openai/Hermes-3-Llama-3.1-70B"},
            clear=False,
        ):
            ok, value = smoke.check_capable_tier()
        assert ok is False
        assert "claude" in value.lower() or "opus" in value.lower() or "hermes" in value.lower()

    def test_claude_but_not_opus_fails(self) -> None:
        with patch.dict("shared.config.MODELS", {"capable": "claude-haiku-3-5"}, clear=False):
            ok, value = smoke.check_capable_tier()
        assert ok is False

    def test_empty_capable_fails(self) -> None:
        with patch.dict("shared.config.MODELS", {"capable": ""}, clear=False):
            ok, value = smoke.check_capable_tier()
        assert ok is False
        assert "empty" in value.lower()


class TestRunPromptWithHermes:
    """Mocks httpx.post. Verifies request shape + response parsing."""

    def _mock_response(self, text: str, status_code: int = 200) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = {"choices": [{"message": {"content": text}}]}
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    def test_happy_path_parses_response(self) -> None:
        prompt = smoke.BENCHMARK_PROMPTS[0]
        with patch("httpx.post") as mock_post:
            mock_post.return_value = self._mock_response("Sure, let's move on.")
            result = smoke.run_prompt_with_hermes(prompt, "http://localhost:4000", "local-fast")
        assert result.error == ""
        assert result.response_text == "Sure, let's move on."
        assert result.response_word_count == 4
        assert result.word_limit_pass is True  # 4 << 35 * 1.2

    def test_word_limit_violation(self) -> None:
        prompt = smoke.BENCHMARK_PROMPTS[0]  # word_limit=35
        long_text = " ".join(["word"] * 100)  # way over limit
        with patch("httpx.post") as mock_post:
            mock_post.return_value = self._mock_response(long_text)
            result = smoke.run_prompt_with_hermes(prompt, "http://localhost:4000", "local-fast")
        assert result.word_limit_pass is False

    def test_http_error_captured(self) -> None:
        prompt = smoke.BENCHMARK_PROMPTS[0]
        with patch("httpx.post") as mock_post:
            mock_post.side_effect = RuntimeError("connection refused")
            result = smoke.run_prompt_with_hermes(prompt, "http://localhost:4000", "local-fast")
        assert result.error != ""
        assert "connection refused" in result.error


class TestGradeResponseWithJudge:
    def _judge_response(self, judge_text: str) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": judge_text}}]}
        return mock_resp

    def test_pass_verdict(self) -> None:
        prompt = smoke.BENCHMARK_PROMPTS[0]
        with patch("httpx.post") as mock_post:
            mock_post.return_value = self._judge_response("PASS: followed the directive cleanly.")
            ok, reasoning = smoke.grade_response_with_judge(
                prompt, "some response", "http://localhost:4000", "capable"
            )
        assert ok is True
        assert "PASS" in reasoning

    def test_fail_verdict(self) -> None:
        prompt = smoke.BENCHMARK_PROMPTS[0]
        with patch("httpx.post") as mock_post:
            mock_post.return_value = self._judge_response("FAIL: ignored the directive.")
            ok, reasoning = smoke.grade_response_with_judge(
                prompt, "some response", "http://localhost:4000", "capable"
            )
        assert ok is False

    def test_judge_invocation_error(self) -> None:
        prompt = smoke.BENCHMARK_PROMPTS[0]
        with patch("httpx.post") as mock_post:
            mock_post.side_effect = RuntimeError("judge unreachable")
            ok, reasoning = smoke.grade_response_with_judge(
                prompt, "some response", "http://localhost:4000", "capable"
            )
        assert ok is False
        assert "judge request failed" in reasoning


class TestRunSmokeDryRun:
    """End-to-end dry run — runs only the CAPABLE tier check, skips
    benchmark + latency. Useful for CI and for fast operator sanity
    checks before spending time on a full run."""

    def test_dry_run_passes_with_valid_capable(self) -> None:
        with patch.dict("shared.config.MODELS", {"capable": "claude-opus-4-6"}, clear=False):
            args = smoke.build_parser().parse_args(["--dry-run"])
            result = smoke.run_smoke(args)
        assert result.ok is True
        assert result.exit_code == 0
        assert result.dry_run is True
        assert result.capable_tier_ok is True

    def test_dry_run_fails_with_invalid_capable(self) -> None:
        with patch.dict(
            "shared.config.MODELS",
            {"capable": "openai/Hermes-3-Llama-3.1-70B"},
            clear=False,
        ):
            args = smoke.build_parser().parse_args(["--dry-run"])
            result = smoke.run_smoke(args)
        assert result.ok is False
        assert result.exit_code == 4
        assert "CAPABLE tier verification failed" in result.reason


class TestBenchmarkPromptsShape:
    """Static checks on the canned prompts — ensure the coverage is
    exactly what the Phase 5 spec §3.1 step 13 calls for."""

    def test_five_prompts_exist(self) -> None:
        assert len(smoke.BENCHMARK_PROMPTS) == 5

    def test_all_five_directive_strategies_covered(self) -> None:
        expected_ids = {
            "advance",
            "rephrase",
            "elaborate",
            "present_reasoning",
            "ungrounded_caution",
        }
        actual_ids = {p.id for p in smoke.BENCHMARK_PROMPTS}
        assert actual_ids == expected_ids

    def test_all_prompts_have_nonempty_fields(self) -> None:
        for p in smoke.BENCHMARK_PROMPTS:
            assert p.user_text
            assert p.directive
            assert p.word_limit > 0
            assert p.expected_behavior_description


class TestBuildParser:
    def test_default_latency_threshold(self) -> None:
        args = smoke.build_parser().parse_args([])
        assert args.latency_threshold_ms == 1500

    def test_capable_check_only_flag(self) -> None:
        args = smoke.build_parser().parse_args(["--capable-check-only"])
        assert args.capable_check_only is True

    def test_benchmark_only_flag(self) -> None:
        args = smoke.build_parser().parse_args(["--benchmark-only"])
        assert args.benchmark_only is True

    def test_dry_run_flag(self) -> None:
        args = smoke.build_parser().parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_json_flag(self) -> None:
        args = smoke.build_parser().parse_args(["--json"])
        assert args.as_json is True
