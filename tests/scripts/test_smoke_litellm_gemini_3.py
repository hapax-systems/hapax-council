"""Tests for ``scripts/smoke-litellm-gemini-3.py``.

The smoke script's job is "ping each Gemini 3 alias once, report
OK/ERR + latency, exit non-zero on any failure." These tests pin the
contracts that don't require a live LiteLLM connection:

  - Default alias list matches the route-evaluation recommendation
    (the four Phase A aliases).
  - Per-row formatting is stable (CI greps for "ERR " on failure).
  - Factory errors and call-time errors both surface as ERR rows.
  - The CLI returns exit code 1 when any alias fails and 0 when all
    succeed.

The live call path is mocked because exercising it requires a valid
``LITELLM_API_KEY`` and would burn API quota on every test run.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "smoke-litellm-gemini-3.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("smoke_litellm_gemini_3", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = _load_script()


# ── Default alias list ────────────────────────────────────────────────


class TestDefaultAliases:
    def test_default_aliases_match_phase_a(self) -> None:
        # Phase A substrate per the route-evaluation doc: 4 NEW aliases.
        assert smoke.DEFAULT_ALIASES == (
            "fast-3",
            "long-context-3",
            "extraction",
            "scouting",
        )

    def test_default_prompt_is_minimal(self) -> None:
        # Smoke prompt should be ~1 token to keep cost negligible.
        assert smoke.DEFAULT_PROMPT == "ping"


# ── Row formatting ────────────────────────────────────────────────────


class TestFormatRow:
    def test_ok_row_format(self) -> None:
        row = smoke._format_row("fast-3", 123.4, None)
        assert row == "fast-3: OK (latency=123ms)"

    def test_err_row_format(self) -> None:
        row = smoke._format_row("scouting", None, "401: invalid api key")
        assert row.startswith("scouting: ERR ")
        assert "401" in row

    def test_err_row_does_not_say_ok(self) -> None:
        # CI grep for `: ERR ` must not also fire on `: OK `.
        row = smoke._format_row("x", None, "boom")
        assert " OK " not in row


# ── Smoke-one error paths ─────────────────────────────────────────────


class TestSmokeOneErrors:
    def test_factory_error_surfaces_as_err(self) -> None:
        # If get_model() itself raises, no LiteLLM call happens.
        with patch.object(smoke, "_smoke_one", wraps=smoke._smoke_one):
            with patch("shared.config.get_model", side_effect=RuntimeError("no provider")):
                alias, latency, err = asyncio.run(smoke._smoke_one("fast-3", "ping"))
        assert alias == "fast-3"
        assert latency is None
        assert err is not None
        assert "factory-error" in err
        assert "RuntimeError" in err

    def test_agent_run_error_surfaces_as_err(self) -> None:
        # Factory works but the LiteLLM call raises.
        fake_model = object()
        fake_agent_cls = type(
            "FakeAgent",
            (),
            {
                "__init__": lambda self, m: None,
                "run": AsyncMock(side_effect=ConnectionError("no proxy")),
            },
        )
        with patch("shared.config.get_model", return_value=fake_model):
            with patch("pydantic_ai.Agent", fake_agent_cls):
                alias, latency, err = asyncio.run(smoke._smoke_one("scouting", "ping"))
        assert alias == "scouting"
        assert latency is None
        assert err is not None
        assert "ConnectionError" in err

    def test_empty_output_surfaces_as_err(self) -> None:
        fake_model = object()
        empty_result = SimpleNamespace(output=None)
        with patch("shared.config.get_model", return_value=fake_model):
            fake_agent_cls = type(
                "FakeAgent",
                (),
                {
                    "__init__": lambda self, m: None,
                    "run": AsyncMock(return_value=empty_result),
                },
            )
            with patch("pydantic_ai.Agent", fake_agent_cls):
                alias, latency, err = asyncio.run(smoke._smoke_one("fast-3", "ping"))
        assert alias == "fast-3"
        assert latency is None
        assert err == "empty-output"

    def test_success_returns_latency_no_error(self) -> None:
        fake_model = object()
        ok_result = SimpleNamespace(output="pong")
        with patch("shared.config.get_model", return_value=fake_model):
            fake_agent_cls = type(
                "FakeAgent",
                (),
                {
                    "__init__": lambda self, m: None,
                    "run": AsyncMock(return_value=ok_result),
                },
            )
            with patch("pydantic_ai.Agent", fake_agent_cls):
                alias, latency, err = asyncio.run(smoke._smoke_one("fast-3", "ping"))
        assert alias == "fast-3"
        assert err is None
        assert latency is not None
        assert latency >= 0.0


# ── Main() exit code ─────────────────────────────────────────────────


class TestMainExitCode:
    def test_main_returns_zero_when_all_succeed(self, capsys) -> None:
        async def _all_ok(aliases, prompt):
            return [(a, 1.0, None) for a in aliases]

        with patch.object(smoke, "_smoke_all", _all_ok):
            rc = smoke.main(["--alias", "fast-3"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "fast-3: OK" in captured.out

    def test_main_returns_one_when_any_fails(self, capsys) -> None:
        async def _mixed(aliases, prompt):
            return [(aliases[0], 1.0, None), (aliases[1], None, "boom")]

        with patch.object(smoke, "_smoke_all", _mixed):
            rc = smoke.main(["--alias", "a", "--alias", "b"])
        assert rc == 1
        captured = capsys.readouterr()
        assert "a: OK" in captured.out
        assert "b: ERR" in captured.out


# ── CLI flag handling ───────────────────────────────────────────────


class TestCli:
    def test_alias_flag_is_repeatable(self, capsys) -> None:
        seen: list[str] = []

        async def _capture(aliases, prompt):
            seen.extend(aliases)
            return [(a, 1.0, None) for a in aliases]

        with patch.object(smoke, "_smoke_all", _capture):
            rc = smoke.main(["--alias", "x", "--alias", "y", "--alias", "z"])
        assert rc == 0
        assert seen == ["x", "y", "z"]

    def test_no_alias_flag_uses_defaults(self, capsys) -> None:
        seen: list[str] = []

        async def _capture(aliases, prompt):
            seen.extend(aliases)
            return [(a, 1.0, None) for a in aliases]

        with patch.object(smoke, "_smoke_all", _capture):
            rc = smoke.main([])
        assert rc == 0
        assert seen == list(smoke.DEFAULT_ALIASES)

    def test_prompt_flag_is_passed_through(self) -> None:
        seen_prompt = []

        async def _capture(aliases, prompt):
            seen_prompt.append(prompt)
            return [(a, 1.0, None) for a in aliases]

        with patch.object(smoke, "_smoke_all", _capture):
            smoke.main(["--alias", "x", "--prompt", "custom"])
        assert seen_prompt == ["custom"]
