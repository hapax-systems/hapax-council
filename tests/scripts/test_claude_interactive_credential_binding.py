"""Credential proof validity and disclosure; all values and observations are synthetic."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from shared.quota_spend_ledger import (
    claude_interactive_credential_admitted,
    load_quota_spend_ledger,
    subscription_quota_state_for_route,
)
from tests.scripts.test_claude_interactive_launch_auth import bound_ledger, dispatch, launch_fixture
from tests.scripts.test_hapax_claude_subscription_quota_admission import _run
from tests.scripts.test_hapax_quota_telemetry_writer import _claude_admission, _run_writer

ROUTE = "claude.interactive.full"


@pytest.mark.parametrize(
    "defect",
    [
        "none",
        "expired-proof",
        "expired-snapshot",
        "wall",
        "old-ledger",
        "wrong-route",
        "different-credential",
    ],
)
def test_credential_proof_cannot_extend_quota(tmp_path, defect):
    path = bound_ledger(tmp_path)
    data = json.loads(path.read_text())
    snapshot = next(s for s in data["quota_snapshots"] if s["route_id"] == ROUTE)
    now = datetime.now(UTC)
    token = "synthetic-subscription-access-token"
    if defect == "expired-proof":
        now = datetime.fromisoformat(snapshot["fresh_until"])
        snapshot["fresh_until"] = (now + timedelta(hours=1)).isoformat()
        # Another current receipt cannot extend this expired proof.
        ref = snapshot["evidence_refs"][0]
        ref = ref.replace(
            ref.split(":fresh_until:")[1].split(":credential_binding:")[0],
            (now + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        proof = ref.split(":credential_binding:")[1].split(":")[0]
        snapshot["evidence_refs"].append(ref.replace(proof, "0" * 64))
    elif defect == "expired-snapshot":
        now = datetime.fromisoformat(snapshot["fresh_until"])
    elif defect == "wall":
        snapshot["subscription_quota_state"] = "exhausted"
    elif defect == "old-ledger":
        data["captured_at"] = (now - timedelta(hours=2)).isoformat()
    elif defect == "wrong-route":
        original = snapshot["evidence_refs"][0]
        proof = original.split(":credential_binding:")[1].split(":")[0]
        snapshot["evidence_refs"] = [
            r.replace(ROUTE, "claude.review.opus") for r in snapshot["evidence_refs"]
        ]
        snapshot["evidence_refs"].append(original.replace(proof, "0" * 64))
    elif defect == "different-credential":
        token = "synthetic-distinct-account-b"
    path.write_text(json.dumps(data))
    assert claude_interactive_credential_admitted(
        load_quota_spend_ledger(path), token, now=now
    ) is (defect == "none")


def test_status_projection_keeps_observation_without_credential_proof(tmp_path):
    path = bound_ledger(tmp_path)
    ledger = load_quota_spend_ledger(path)
    state, refs = subscription_quota_state_for_route(ledger, ROUTE, now=datetime.now(UTC))
    assert state.value == "fresh"
    assert any(r.endswith(":account-live-quota:observed") for r in refs)
    assert all(":credential_binding:" not in r for r in refs)
    assert ":credential_binding:" in path.read_text()


@pytest.mark.parametrize("proof", ["", "a" * 63, "synthetic-sensitive-binding"])
def test_writer_refuses_malformed_binding_without_disclosure(tmp_path, capsys, proof):
    rc = _run(
        [
            "--receipt-dir",
            str(tmp_path),
            "--evidence-ref",
            "claude-subscription-headroom-observed-20260924t080000z",
            "--credential-binding",
            proof,
        ]
    )
    assert rc == 2
    assert not list(tmp_path.glob("*.yaml"))
    assert "synthetic-sensitive-binding" not in capsys.readouterr().err


@pytest.mark.parametrize("proof", ["", "a" * 63, "synthetic-sensitive-binding"])
def test_telemetry_refuses_malformed_binding_without_disclosure(tmp_path, proof):
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, route_id=ROUTE, observed_at="2026-06-09T23:55:00Z")
    receipt = next(relay.glob("*.yaml"))
    receipt.write_text(receipt.read_text() + f"credential_binding: {proof}\n")
    result, ledger = _run_writer(tmp_path)
    assert result.returncode == 0
    snapshots = json.loads(ledger.read_text())["quota_snapshots"]
    assert all(
        s["subscription_quota_state"] != "fresh" for s in snapshots if s["route_id"] == ROUTE
    )
    assert "synthetic-sensitive-binding" not in ledger.read_text() + result.stdout + result.stderr


def test_unmeasured_cli_version_holds_before_launch(tmp_path):
    env, _, _, observed, _ = launch_fixture(tmp_path)
    (tmp_path / "cli-version.txt").write_text("2.1.282 (Claude Code)")
    result = dispatch(tmp_path, env)
    assert result.returncode != 0
    assert not observed.exists()
