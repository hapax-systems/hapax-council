"""Passive gateway metadata cannot decide the saved subscription's admission."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
import yaml

from tests.scripts.test_claude_account_live_observe_per_route import obs
from tests.scripts.test_claude_probe_subscription_boundary import (
    subscription_probe_home as subscription_probe_home,
)

NOW = datetime(2026, 9, 24, 11, 0, tzinfo=UTC)


@pytest.mark.parametrize("surface", ["headless", "transcript"])
@pytest.mark.parametrize("offset_seconds", [-60, 0, 60])
@pytest.mark.parametrize(
    "outcome",
    [
        "served",
        "wall",
        "wall-text",
        "no-evidence",
        "missing-binary",
        "timeout",
        "no-probe",
        "dry-run",
    ],
)
@pytest.mark.usefixtures("subscription_probe_home")
def test_unbound_wall_is_diagnostic_while_subscription_probe_decides(
    tmp_path, monkeypatch, capsys, surface, offset_seconds, outcome
):
    # Both passive formats lack account/auth/billing proof. Even a tied or
    # future-dated gateway wall cannot overrule the controlled subscription.
    at = NOW + timedelta(seconds=offset_seconds)
    wall = {
        "is_error": True,
        "error": {"type": "rate_limit_error", "message": "gateway rate limit exceeded"},
        "model": "claude-opus-5",
    }
    record = {"timestamp": at.isoformat()}
    if surface == "headless":
        record.update(type="result", **wall)
    else:
        record.update(type="assistant", message=wall)
    source = tmp_path / "gateway.jsonl"
    source.write_text(json.dumps(record) + "\n")
    receipts = tmp_path / "receipts"
    real_run = subprocess.run
    provider_calls = []

    def provider_run(argv, **kwargs):
        if argv == list(obs.PROBE_ARGV):
            provider_calls.append(argv)
            assert kwargs["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "synthetic-subscription-access-token"
            assert not obs.provider_redirect_env(kwargs["env"])
            assert kwargs["cwd"] == kwargs["env"]["HOME"]
            if outcome == "missing-binary":
                raise FileNotFoundError("synthetic-sensitive-exception-detail")
            if outcome == "timeout":
                raise subprocess.TimeoutExpired(argv, 180, output="synthetic-sensitive-output")
            if outcome == "wall-text":
                return subprocess.CompletedProcess(argv, 1, "", "You have hit your usage limit")
            response = {
                "model": "claude-opus-5",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "is_error": outcome != "served",
            }
            if outcome == "wall":
                response["error"] = {"type": "rate_limit_error", "message": "usage limit reached"}
            return subprocess.CompletedProcess(argv, 0, json.dumps(response), "")
        assert str(obs.ADMISSION_WRITER) in argv
        return real_run(argv, **kwargs)

    monkeypatch.setattr(obs.subprocess, "run", provider_run)
    mode = ["--no-probe"] if outcome == "no-probe" else ["--probe"]
    if outcome == "dry-run":
        mode.append("--dry-run")
    rc = obs.main(
        [
            "--headless-glob",
            str(source if surface == "headless" else tmp_path / "absent"),
            "--transcript-glob",
            str(source if surface == "transcript" else tmp_path / "absent"),
            "--now",
            NOW.isoformat(),
            "--receipt-dir",
            str(receipts),
            "--json",
            *mode,
        ]
    )
    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert len(provider_calls) == (0 if outcome in {"no-probe", "dry-run"} else 1)
    expected_verdict, expected_rc = {
        "served": ("served", 0),
        "wall": ("walled", 3),
        "wall-text": ("walled", 3),
        "no-evidence": ("no_evidence", 4),
        "missing-binary": ("probe_failed", 7),
        "timeout": ("probe_failed", 7),
        "no-probe": ("no_evidence", 4),
        "dry-run": ("no_evidence", 4),
    }[outcome]
    assert (payload["verdict"], rc) == (expected_verdict, expected_rc)
    assert payload["passive"] == {
        "verdict": "walled",
        "observed_at": at.isoformat().replace("+00:00", "Z"),
        "source": "headless-result" if surface == "headless" else "session-transcript",
        "subscription_bound": False,
        "observation_count": 1,
    }
    written = list(receipts.glob("*.yaml"))
    if outcome == "served":
        assert len(written) == len(obs.DEFAULT_ROUTE_IDS)
        assert payload["source"] == "active-probe"
        for path in written:
            receipt = yaml.safe_load(path.read_text())
            assert receipt["status"] == "quota_available"
            assert receipt["auth_surface"] == "subscription"
            assert receipt["observed_at"] == NOW
    elif outcome in {"wall", "wall-text"}:
        assert len(written) == 1
        receipt = yaml.safe_load(written[0].read_text())
        assert receipt["status"] == "quota_blocked"
        assert receipt["credential_binding"]
        assert not payload.get("receipts")
    else:
        assert not written
        assert not payload.get("receipts")
    if outcome in {"missing-binary", "timeout"}:
        assert "command -v claude" in payload["hint"]
        assert (
            "systemctl --user status hapax-claude-account-live-observe.service" in payload["hint"]
        )
        assert "hapax-claude-account-live-observe --probe --json" in payload["hint"]
    assert "synthetic-sensitive" not in output.out + output.err
    assert "synthetic-subscription-access-token" not in output.out + output.err
