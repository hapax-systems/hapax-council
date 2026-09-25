"""Synthetic requests through the real observer, receipts, telemetry and child guard."""

import json
import shlex
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from shared.quota_spend_ledger import (
    claude_interactive_credential_admitted,
    claude_subscription_credential_binding,
    claude_subscription_wall_observed_at,
    load_quota_spend_ledger,
    subscription_quota_state_for_route,
)
from tests.scripts.test_claude_account_live_observe_per_route import obs
from tests.scripts.test_claude_interactive_installed_copy import installed_fixture, run_installed
from tests.scripts.test_claude_interactive_launch_auth import dispatch, launch_fixture
from tests.scripts.test_hapax_quota_telemetry_writer import _run_writer, _wall_receipt

ROUTE = "claude.interactive.full"
TOKEN = "synthetic-subscription-access-token"


def observe(tmp_path, monkeypatch, capsys, env, at, outcome, *, receipts=None):
    real_run = subprocess.run

    def provider(argv, **kwargs):
        if argv != list(obs.PROBE_ARGV):
            return real_run(argv, **kwargs)
        assert kwargs["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == TOKEN
        if outcome == "failed":
            raise FileNotFoundError("synthetic-sensitive-instrument-failure")
        if outcome == "wall-text":
            return subprocess.CompletedProcess(argv, 1, "", "You have hit your usage limit")
        record = {"model": "claude-opus-5", "usage": {"input_tokens": 1, "output_tokens": 1}}
        if outcome == "wall":
            record.update(is_error=True, error={"message": "usage limit reached"})
        return subprocess.CompletedProcess(argv, 0, json.dumps(record), "")

    with monkeypatch.context() as context:
        for key in list(obs.provider_redirect_env()):
            context.delenv(key)
        context.setenv("CLAUDE_CONFIG_DIR", env["CLAUDE_CONFIG_DIR"])
        context.setattr(obs.subprocess, "run", provider)
        rc = obs.main(
            [
                "--headless-glob",
                str(tmp_path / "absent"),
                "--transcript-glob",
                str(tmp_path / "absent"),
                "--receipt-dir",
                str(receipts or tmp_path / "relay-receipts"),
                "--now",
                at.isoformat(),
                "--route-id",
                ROUTE,
                "--json",
            ]
        )
    output = capsys.readouterr()
    assert TOKEN not in output.out + output.err
    assert "synthetic-sensitive" not in output.out + output.err
    return rc, json.loads(output.out)


def admitted(tmp_path, monkeypatch, capsys):
    env, _, _, child, _ = launch_fixture(tmp_path)
    now = datetime.now(UTC).replace(microsecond=0)
    rc, _ = observe(tmp_path, monkeypatch, capsys, env, now - timedelta(minutes=2), "served")
    assert rc == 0
    writer, ledger = _run_writer(tmp_path, now=now.isoformat())
    assert writer.returncode == 0, writer.stderr
    assert claude_interactive_credential_admitted(load_quota_spend_ledger(ledger), TOKEN, now=now)
    env["HAPAX_QUOTA_SPEND_LEDGER"] = str(ledger)
    env["HAPAX_RELAY_RECEIPT_DIR"] = str(tmp_path / "relay-receipts")
    return env, child, ledger, now


@pytest.mark.parametrize("outcome", ["wall", "wall-text"])
def test_bound_refusal_revokes_earlier_ledger_before_telemetry_refresh(
    tmp_path, monkeypatch, capsys, outcome
):
    env, _, ledger, now = admitted(tmp_path, monkeypatch, capsys)
    before = ledger.read_bytes()
    positive = {p: p.read_bytes() for p in (tmp_path / "relay-receipts").glob("*.yaml")}
    rc, payload = observe(tmp_path, monkeypatch, capsys, env, now - timedelta(seconds=30), outcome)
    assert rc == 3
    with monkeypatch.context() as context:
        for key, value in env.items():
            context.setenv(key, value)
        assert not obs._interactive_credential_admitted(TOKEN)
    assert ledger.read_bytes() == before
    assert all(p.read_bytes() == content for p, content in positive.items())
    walls = list((tmp_path / "relay-receipts").glob("*-quota-wall.yaml"))
    assert len(walls) == 1
    receipt = yaml.safe_load(walls[0].read_text())
    assert receipt["status"] == "quota_blocked"
    assert receipt["auth_surface"] == "subscription"
    assert receipt["credential_binding"]
    assert TOKEN not in walls[0].read_text()
    assert "hapax-claude-account-live-observe --probe" in payload["hint"]
    writer, ledger = _run_writer(tmp_path, now=now.isoformat())
    assert writer.returncode == 0, writer.stderr
    for route in obs.DEFAULT_ROUTE_IDS:
        state, _ = subscription_quota_state_for_route(
            load_quota_spend_ledger(ledger), route, now=now
        )
        assert state.value == "exhausted"


def test_instrument_failure_does_not_mint_a_quota_wall(tmp_path, monkeypatch, capsys):
    env, _, ledger, now = admitted(tmp_path, monkeypatch, capsys)
    rc, _ = observe(tmp_path, monkeypatch, capsys, env, now, "failed")
    assert rc == 7
    assert not list((tmp_path / "relay-receipts").glob("*-quota-wall.yaml"))
    assert claude_interactive_credential_admitted(load_quota_spend_ledger(ledger), TOKEN, now=now)


def test_tmux_child_rechecks_new_bound_refusal(tmp_path, monkeypatch, capsys):
    env, child, _, now = admitted(tmp_path, monkeypatch, capsys)
    staged = tmp_path / "staged"
    rc, _ = observe(
        tmp_path, monkeypatch, capsys, env, now - timedelta(seconds=30), "wall", receipts=staged
    )
    assert rc == 3
    walls = list(staged.glob("*-quota-wall.yaml"))
    assert len(walls) == 1
    tmux = tmp_path / "bin/tmux"
    tmux.write_text(
        tmux.read_text().replace(
            'exec "$runner"',
            f"cp {shlex.quote(str(walls[0]))} {shlex.quote(env['HAPAX_RELAY_RECEIPT_DIR'])}/\n"
            "export HAPAX_RELAY_RECEIPT_DIR=/synthetic-wrong-receipts\n"
            'exec "$runner"',
        )
    )
    result = dispatch(tmp_path, env)
    assert result.returncode != 0, result.stdout + result.stderr
    assert not child.exists()


@pytest.mark.parametrize("bound", [False, True])
def test_wall_authority_and_observation_order(tmp_path, monkeypatch, capsys, bound):
    env, _, _, now = admitted(tmp_path, monkeypatch, capsys)
    if bound:
        rc, _ = observe(tmp_path, monkeypatch, capsys, env, now - timedelta(seconds=90), "wall")
        assert rc == 3
    else:
        _wall_receipt(
            tmp_path / "relay-receipts",
            "theta",
            (now + timedelta(hours=6)).isoformat(),
            detected_at=(now - timedelta(seconds=90)).isoformat(),
        )
    # A newer genuine serve must supersede a predicted future reset.
    rc, _ = observe(tmp_path, monkeypatch, capsys, env, now - timedelta(seconds=30), "served")
    assert rc == 0
    if bound:
        for path in (tmp_path / "relay-receipts").glob("*-quota-wall.yaml"):
            text = path.read_text()
            path.write_text(
                text.replace(
                    "resets_at: unknown", f"resets_at: {(now + timedelta(hours=6)).isoformat()}"
                )
            )
    writer, ledger = _run_writer(tmp_path, now=now.isoformat())
    assert writer.returncode == 0, writer.stderr
    state, _ = subscription_quota_state_for_route(load_quota_spend_ledger(ledger), ROUTE, now=now)
    assert state.value == "fresh"
    with monkeypatch.context() as context:
        for key, value in env.items():
            context.setenv(key, value)
        assert obs._interactive_credential_admitted(TOKEN)


def test_newer_gateway_wall_cannot_revoke_subscription_headroom(tmp_path, monkeypatch, capsys):
    _, _, _, now = admitted(tmp_path, monkeypatch, capsys)
    _wall_receipt(
        tmp_path / "relay-receipts",
        "theta",
        (now + timedelta(hours=6)).isoformat(),
        detected_at=(now - timedelta(seconds=30)).isoformat(),
    )
    writer, ledger = _run_writer(tmp_path, now=now.isoformat())
    assert writer.returncode == 0, writer.stderr
    state, _ = subscription_quota_state_for_route(load_quota_spend_ledger(ledger), ROUTE, now=now)
    assert state.value == "fresh"
    assert json.loads(writer.stdout)["quota_walls"] == {"claude": 1}


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "quota_available"),
        ("provider", "gateway"),
        ("auth_surface", "api"),
        ("source", "passive-transcript"),
        ("observation", "session_present"),
        ("credential_binding", "malformed"),
        ("detected_at", "malformed"),
        ("detected_at", "2026-06-10T00:00:00"),
        ("detected_at", "2026-06-10T00:00:01Z"),
        ("detected_at", "2026-06-08T23:59:59Z"),
    ],
)
def test_unbound_wall_fields_cannot_claim_subscription_authority(tmp_path, field, value):
    at = datetime(2026, 6, 10, tzinfo=UTC)
    observation = obs.Observation(
        "wall",
        at,
        "active-probe",
        credential_binding=claude_subscription_credential_binding(TOKEN, at),
    )
    path = obs.publish_bound_wall(observation, tmp_path)
    fields = dict(line.split(": ", 1) for line in path.read_text().splitlines())
    assert claude_subscription_wall_observed_at(fields, now=at) == at
    fields[field] = value
    assert claude_subscription_wall_observed_at(fields, now=at) is None


@pytest.mark.parametrize("damage", ["malformed", "unreadable", "unbound", "future"])
def test_damaged_controlled_wall_holds_child(tmp_path, monkeypatch, capsys, damage):
    env, _, _, now = admitted(tmp_path, monkeypatch, capsys)
    rc, _ = observe(tmp_path, monkeypatch, capsys, env, now - timedelta(seconds=30), "wall")
    assert rc == 3
    path = next((tmp_path / "relay-receipts").glob("*-quota-wall.yaml"))
    if damage == "malformed":
        path.write_text("not a receipt")
    elif damage == "unreadable":
        path.unlink()
        path.mkdir()
    elif damage == "unbound":
        path.write_text(path.read_text().replace("auth_surface: subscription", "auth_surface: api"))
    else:
        text = path.read_text()
        start = text.index("detected_at:")
        end = text.index("\n", start)
        path.write_text(
            text[:start] + f"detected_at: {(now + timedelta(hours=1)).isoformat()}" + text[end:]
        )
    with monkeypatch.context() as context:
        for key, value in env.items():
            context.setenv(key, value)
        assert not obs._interactive_credential_admitted(TOKEN)


@pytest.mark.parametrize("same_credential", [True, False])
def test_same_time_refusal_only_revokes_matching_credential(
    tmp_path, monkeypatch, capsys, same_credential
):
    env, _, ledger, now = admitted(tmp_path, monkeypatch, capsys)
    at = now - timedelta(minutes=2)
    observation = obs.Observation(
        "wall",
        at,
        "active-probe",
        credential_binding=claude_subscription_credential_binding(
            TOKEN if same_credential else "synthetic-distinct-account-b", at
        ),
    )
    path = obs.publish_bound_wall(observation, tmp_path / "relay-receipts")
    fields = dict(line.split(": ", 1) for line in path.read_text().splitlines())
    assert claude_interactive_credential_admitted(
        load_quota_spend_ledger(ledger), TOKEN, now=now, quota_walls=[fields]
    ) is (not same_credential)


def test_bound_wall_appearing_during_auth_check_holds_exec(tmp_path, monkeypatch, capsys):
    env, _, _, now = admitted(tmp_path, monkeypatch, capsys)
    staged = tmp_path / "staged"
    assert (
        observe(
            tmp_path, monkeypatch, capsys, env, now - timedelta(seconds=30), "wall", receipts=staged
        )[0]
        == 3
    )
    wall = next(staged.glob("*-quota-wall.yaml"))
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    def check(argv, **kwargs):
        if "--version" in argv:
            return subprocess.CompletedProcess(argv, 0, "2.1.281 (Claude Code)", "")
        wall.rename(Path(env["HAPAX_RELAY_RECEIPT_DIR"]) / wall.name)
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps(
                {
                    "loggedIn": True,
                    "authMethod": "oauth_token",
                    "apiProvider": "firstParty",
                    "apiKeySource": None,
                }
            ),
            "",
        )

    calls = []
    monkeypatch.setattr(obs.subprocess, "run", check)
    monkeypatch.setattr(obs.os, "execvpe", lambda *args: calls.append(args))
    assert obs.interactive_subscription(["claude"], execute=True) == 4
    assert not calls


def test_wall_publication_failure_reports_no_durable_revocation(tmp_path, monkeypatch, capsys):
    env, _, _, now = admitted(tmp_path, monkeypatch, capsys)
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("blocked")
    rc, payload = observe(tmp_path, monkeypatch, capsys, env, now, "wall", receipts=blocked)
    assert rc == 5
    assert payload["wall_receipt_write_failed"] is True
    assert "earlier telemetry is not revoked" in payload["hint"]
    assert "receipt-directory permissions" in payload["hint"]


@pytest.mark.parametrize("terminal", ["none", "tmux"])
def test_installed_copy_refuses_new_bound_wall(tmp_path, monkeypatch, capsys, terminal):
    env, installed, _, _, workdir, child, _ = installed_fixture(tmp_path, explicit=True)
    env["HAPAX_RELAY_RECEIPT_DIR"] = str(tmp_path / "relay-receipts")
    rc, _ = observe(tmp_path, monkeypatch, capsys, env, datetime.now(UTC), "wall")
    assert rc == 3
    result = run_installed(env, installed, workdir, terminal=terminal)
    assert result.returncode != 0
    assert "current quota evidence does not bind the launch credential" in result.stderr
    assert not child.exists()
