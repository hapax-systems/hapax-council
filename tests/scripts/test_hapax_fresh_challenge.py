"""A fresh challenge cannot become an undeclared or unwitnessed inference call."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared.platform_capability_registry import (
    CapacityPool,
    ExecutionDescriptor,
    Mode,
    Platform,
    QualityFloor,
    RouteState,
)
from shared.quota_spend_ledger import SubscriptionQuotaState

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/hapax-fresh-challenge"
SID = "01900000-1234-7000-8000-123456789abc"


@pytest.fixture
def helper():
    loader = importlib.machinery.SourceFileLoader("hapax_fresh_challenge_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    yield module
    sys.modules.pop(loader.name, None)


@pytest.fixture
def admitted(helper, monkeypatch):
    route = SimpleNamespace(
        route_id="codex.headless.full",
        platform=Platform.CODEX,
        mode=Mode.HEADLESS,
        route_state=RouteState.ACTIVE,
        blocked_reasons=[],
        paid_provider=None,
        capacity_pool=CapacityPool.SUBSCRIPTION_QUOTA,
        mutability=SimpleNamespace(provider_spend=False),
        quality_envelope=SimpleNamespace(
            eligible_quality_floors=[QualityFloor.FRONTIER_REVIEW_REQUIRED]
        ),
        execution_descriptor=ExecutionDescriptor(model_id="gpt-6-astra", effort="medium"),
    )
    registry = SimpleNamespace(require=lambda _: route)
    sources = SimpleNamespace(
        registry=registry,
        registry_error=None,
        non_supply_observation_errors=(),
        surface_delta_blockers_by_route={},
        quota_ledger=object(),
        quota_error=None,
        quota_ledger_source="live",
        quota_live_error=None,
    )
    monkeypatch.setattr(
        helper,
        "load_dispatch_policy_sources",
        lambda: sources,
    )
    monkeypatch.setattr(
        helper,
        "check_route_freshness",
        lambda _: SimpleNamespace(ok=True, blocked_reasons=(), errors=()),
    )
    monkeypatch.setattr(
        helper,
        "subscription_quota_state_for_route",
        lambda *_: (SubscriptionQuotaState.FRESH, ("quota:fixture",)),
    )
    monkeypatch.setattr(
        helper,
        "load_platform_capability_receipts",
        lambda *_args, **_kwargs: {
            "codex": SimpleNamespace(
                routes=["codex.headless.full"],
                receipt_id="receipt-fixture",
                cli=SimpleNamespace(available=True, version="codex-cli 0.160.0"),
            )
        },
    )
    monkeypatch.setattr(helper.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(
        helper.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["/usr/bin/codex", "--version"], 0, "codex-cli 0.160.0\n", ""
        ),
    )
    route.sources = sources
    return route


def test_unknown_route_refuses_before_any_binary_or_provider_call(helper, monkeypatch):
    monkeypatch.setattr(
        helper.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("unknown route launched a subprocess"),
    )
    with pytest.raises(helper.ChallengeHold, match="unsupported_route"):
        helper.admit_route("api.headless.openrouter")


def test_unknown_quota_refuses_without_fallback(helper, admitted, monkeypatch):
    monkeypatch.setattr(
        helper,
        "subscription_quota_state_for_route",
        lambda *_: (SubscriptionQuotaState.UNKNOWN, ("quota:unknown",)),
    )
    with pytest.raises(helper.ChallengeHold, match="quota_not_fresh"):
        helper.admit_route("codex.headless.full")


def test_surface_hold_and_fixture_ledger_refuse(helper, admitted):
    admitted.sources.surface_delta_blockers_by_route["codex.headless.full"] = ("operator_hold",)
    with pytest.raises(helper.ChallengeHold, match="registry_or_surface_hold"):
        helper.admit_route("codex.headless.full")
    admitted.sources.surface_delta_blockers_by_route.clear()
    admitted.sources.quota_ledger_source = "fixtures"
    with pytest.raises(helper.ChallengeHold, match="quota_ledger_not_live"):
        helper.admit_route("codex.headless.full")


def test_paid_surface_and_wrong_cli_version_refuse(helper, admitted, monkeypatch):
    admitted.paid_provider = "provider"
    with pytest.raises(helper.ChallengeHold, match="paid_route_forbidden"):
        helper.admit_route("codex.headless.full")
    admitted.paid_provider = None
    monkeypatch.setattr(
        helper.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["/usr/bin/codex", "--version"], 0, "codex-cli 0.158.0\n", ""
        ),
    )
    with pytest.raises(helper.ChallengeHold, match="cli_version_mismatch"):
        helper.admit_route("codex.headless.full")


def test_strict_verdict(helper):
    assert helper.parse_verdict('{"verdict":"gap","gap":"No rollback evidence"}') == (
        "gap",
        "No rollback evidence",
    )
    with pytest.raises(helper.ChallengeHold, match="invalid_verdict"):
        helper.parse_verdict('{"verdict":"allow","gap":""}')
    with pytest.raises(helper.ChallengeHold, match="invalid_verdict"):
        helper.parse_verdict('{"verdict":[],"gap":""}')


def test_challenge_environment_excludes_provider_keys(helper, tmp_path):
    env = helper.challenge_environment(
        tmp_path,
        {
            "PATH": "/usr/bin",
            "OPENAI_API_KEY": "do-not-copy",  # pragma: allowlist secret
            "ANTHROPIC_API_KEY": "do-not-copy",  # pragma: allowlist secret
            "HAPAX_PAID_BUDGET": "do-not-copy",  # pragma: allowlist secret
        },
    )
    assert env["CODEX_HOME"] == str(tmp_path)
    assert "OPENAI_API_KEY" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "HAPAX_PAID_BUDGET" not in env


def test_prompt_contains_only_three_case_fields(helper):
    prompt = helper.build_prompt("stop unit", "journal says idle", "require recovery")
    assert json.loads(prompt.splitlines()[-1]) == {
        "act": "stop unit",
        "evidence": "journal says idle",
        "governing_rule": "require recovery",
    }
    with pytest.raises(helper.ChallengeHold, match="input_exceeds_small_context"):
        helper.build_prompt("stop", "x" * 13_000, "rule")


def test_native_stream_refuses_tool_use(helper):
    stream = "\n".join(
        json.dumps(row)
        for row in (
            {"type": "thread.started", "thread_id": "thread-fixture"},
            {"type": "turn.started"},
            {"type": "item.started", "item": {"type": "command_execution"}},
            {"type": "turn.completed"},
        )
    )
    with pytest.raises(helper.ChallengeHold, match="challenge_used_tools"):
        helper._thread_id(stream)
    with pytest.raises(helper.ChallengeHold, match="native_stream_malformed"):
        helper._thread_id("[]")


@pytest.mark.parametrize(
    "forged_model,observed_model,observed_effort",
    [
        (False, "gpt-6-astra", "medium"),
        (True, "gpt-6-astra", "medium"),
        (False, "gpt-5.5", "medium"),
        (False, "gpt-6-astra", "high"),
        (False, None, None),
    ],
)
def test_one_shot_challenge_uses_native_rollout_not_answer_model(
    helper, tmp_path, monkeypatch, forged_model, observed_model, observed_effort
):
    auth_dir = tmp_path / ".codex"
    auth_dir.mkdir()
    (auth_dir / "auth.json").write_text("synthetic fixture, no credential")
    monkeypatch.setattr(helper.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        helper,
        "admit_route",
        lambda _: helper.Admission(
            "codex.headless.full",
            "/usr/bin/codex",
            "gpt-6-astra",
            "medium",
            "receipt-fixture",
            ("quota:fixture",),
            ExecutionDescriptor(model_id="gpt-6-astra", effort="medium"),
        ),
    )

    def fake_run(command, *, input, env, **_kwargs):
        assert command[:2] == ["/usr/bin/codex", "exec"]
        assert "--sandbox" in command and command[command.index("--sandbox") + 1] == "read-only"
        assert 'model="gpt-6-astra"' in command
        assert 'model_reasoning_effort="medium"' in command
        assert "OPENAI_API_KEY" not in env
        assert json.loads(input.splitlines()[-1])["act"] == "proposed act"
        answer = {"verdict": "gap", "gap": "missing recovery"}
        if forged_model:
            answer["model"] = "forged"
        Path(command[command.index("--output-last-message") + 1]).write_text(json.dumps(answer))
        sessions = Path(env["CODEX_HOME"]) / "sessions/2026/10/03"
        sessions.mkdir(parents=True)
        stamp = datetime.now(UTC).isoformat()
        (sessions / f"rollout-2026-10-03T00-00-00-{SID}.jsonl").write_text(
            "\n".join(
                json.dumps(row)
                for row in (
                    {
                        "type": "session_meta",
                        "timestamp": stamp,
                        "payload": {"id": SID, "cwd": command[command.index("--cd") + 1]},
                    },
                    {
                        "type": "turn_context",
                        "timestamp": stamp,
                        "payload": {"model": observed_model, "effort": observed_effort},
                    },
                )
            )
            + "\n"
        )
        return subprocess.CompletedProcess(
            command,
            0,
            "\n".join(
                json.dumps(row)
                for row in (
                    {"type": "thread.started", "thread_id": SID},
                    {"type": "turn.started"},
                    {"type": "turn.completed"},
                )
            ),
            "",
        )

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    if (observed_model, observed_effort) != ("gpt-6-astra", "medium"):
        with pytest.raises(helper.ChallengeHold, match="execution_identity_unverified"):
            helper.run_challenge("proposed act", "evidence", "rule", "codex.headless.full")
    elif forged_model:
        with pytest.raises(helper.ChallengeHold, match="invalid_verdict"):
            helper.run_challenge("proposed act", "evidence", "rule", "codex.headless.full")
    else:
        result = helper.run_challenge("proposed act", "evidence", "rule", "codex.headless.full")
        assert result["observed_model"] == "gpt-6-astra"
        assert result["verdict"] == "gap"
        assert result["authority"] == "advisory_only"
