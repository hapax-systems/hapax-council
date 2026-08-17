"""Codex subscription-quota admission writer guards.

The one real hazard this writer must close is evidence laundering: Codex has a live saved-login
``codex exec`` sentinel in the telemetry writer that proves AUTH, and a valid login says nothing
about remaining subscription quota. These tests pin that auth evidence, lane presence, and
free-form observations can never become quota evidence, and that every refusal is fail-closed
(non-zero exit, nothing written).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "hapax-codex-quota-admission"


def _load_module():
    spec = importlib.util.spec_from_loader(
        "hapax_codex_quota_admission",
        importlib.machinery.SourceFileLoader("hapax_codex_quota_admission", str(SCRIPT)),
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hapax_codex_quota_admission"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


mod = _load_module()

VALID_REF = "codex-subscription-headroom-observed-20260809t1630z"


def _run(tmp_path: Path, *args: str) -> int:
    return mod.main(["--receipt-dir", str(tmp_path), *args])


def _receipts(tmp_path: Path) -> list[Path]:
    return sorted(tmp_path.glob("*.yaml"))


def _fields(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition(": ")
        out[key] = value
    return out


def test_valid_observation_writes_a_positive_admission(tmp_path: Path) -> None:
    assert _run(tmp_path, "--evidence-ref", VALID_REF) == 0
    written = _receipts(tmp_path)
    assert len(written) == 1
    fields = _fields(written[0])
    assert fields["schema"] == "hapax.codex_quota_admission.v1"
    assert fields["route_id"] == "codex.headless.full"
    assert fields["capacity_pool"] == "subscription_quota"
    # The registry records auth_surface "oauth" for codex routes; a mismatch here would make the
    # receipt unfoldable against the route it names.
    assert fields["auth_surface"] == "oauth"
    assert fields["account_live_quota_observed"] == "true"
    assert fields["lane_presence_used_as_quota_evidence"] == "false"
    assert fields["saved_login_auth_probe_used_as_quota_evidence"] == "false"
    assert fields["positive_admission"] == "true"
    assert fields["secret_value_persisted"] == "false"
    assert fields["prompt_or_output_persisted"] == "false"


@pytest.mark.parametrize(
    "ref",
    [
        "codex-exec-auth-sentinel-20260809t1630z",
        "codex-saved-login-ok-20260809t1630z",
        "codex-auth-probe-passed-20260809t1630z",
        "codex-login-sentinel-green-20260809t1630z",
    ],
)
def test_saved_login_auth_evidence_is_refused_as_quota_evidence(
    tmp_path: Path, ref: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """A valid saved login proves auth, never headroom.

    Asserting the message, not just the exit code: the witness allowlist refuses these refs anyway,
    so an exit-code-only assertion stays green with the auth check deleted and pins nothing. What is
    actually under test is that the refusal names the auth/headroom confusion — the mistake Codex's
    live ``codex exec`` sentinel invites.
    """
    assert _run(tmp_path, "--evidence-ref", ref) == 2
    assert _receipts(tmp_path) == []
    message = capsys.readouterr().err
    assert "proves auth, not quota headroom" in message


@pytest.mark.parametrize(
    "ref",
    [
        "hapax-codex-cx-mondlc-present",
        "hapax-claude-beta-present",
        "cx-crit-lane-running",
        "vbe-3-session-present",
        "tmux-pane-alive",
        "beta-lane-exists",
    ],
)
def test_lane_presence_is_refused_as_quota_evidence(
    tmp_path: Path, ref: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Same reasoning as the auth case: assert the diagnostic, since the allowlist refuses anyway."""
    assert _run(tmp_path, "--evidence-ref", ref) == 2
    assert _receipts(tmp_path) == []
    assert "lane/tmux/session presence" in capsys.readouterr().err


def test_free_form_observation_is_refused(tmp_path: Path) -> None:
    assert _run(tmp_path, "--evidence-ref", VALID_REF, "--observation", "looks_fine") == 2
    assert _receipts(tmp_path) == []


def test_operator_confirmation_is_an_allowed_observation(tmp_path: Path) -> None:
    ref = "codex-operator-confirmed-subscription-headroom-20260809t1630z"
    assert (
        _run(
            tmp_path,
            "--evidence-ref",
            ref,
            "--observation",
            "operator_confirmed_subscription_headroom",
        )
        == 0
    )
    assert len(_receipts(tmp_path)) == 1


def test_unknown_route_is_refused(tmp_path: Path) -> None:
    assert _run(tmp_path, "--evidence-ref", VALID_REF, "--route-id", "claude.headless.full") == 2
    assert _receipts(tmp_path) == []


def test_spark_route_is_allowed(tmp_path: Path) -> None:
    assert _run(tmp_path, "--evidence-ref", VALID_REF, "--route-id", "codex.headless.spark") == 0
    assert _fields(_receipts(tmp_path)[0])["route_id"] == "codex.headless.spark"


@pytest.mark.parametrize("seconds", ["30", "7200"])
def test_stale_after_bounds_are_enforced(tmp_path: Path, seconds: str) -> None:
    """Short-lived by construction: a long window would let one observation stand as stale evidence."""
    assert _run(tmp_path, "--evidence-ref", VALID_REF, "--stale-after-seconds", seconds) == 2
    assert _receipts(tmp_path) == []


@pytest.mark.parametrize(
    "ref",
    [
        "codex-headroom-sk-abcdefghijklmnop-20260809t1630z",
        "codex-subscription-headroom-observed-bearer-20260809t1630z",
    ],
)
def test_secretish_refs_are_refused(tmp_path: Path, ref: str) -> None:
    assert _run(tmp_path, "--evidence-ref", ref) == 2
    assert _receipts(tmp_path) == []


def test_receipt_name_must_be_identifiable(tmp_path: Path) -> None:
    assert _run(tmp_path, "--evidence-ref", VALID_REF, "--receipt-name", "something-else.yaml") == 2
    assert _receipts(tmp_path) == []


def _rollout(
    tmp_path: Path,
    *,
    observed: str,
    used_percent: float = 2.0,
    window: int = 10080,
    secret: str = "OPERATOR PROMPT: do not leak me",
) -> Path:
    """A rollout shaped like Codex CLI's, including content the extractor must never touch."""
    sessions = tmp_path / "sessions" / "2026" / "08" / "09"
    sessions.mkdir(parents=True, exist_ok=True)
    path = sessions / "rollout-2026-08-09T11-29-08-019fe75b.jsonl"
    lines = [
        json.dumps({"timestamp": observed, "type": "event_msg", "payload": {"message": secret}}),
        json.dumps(
            {
                "timestamp": observed,
                "type": "event_msg",
                "payload": {
                    "rate_limits": {
                        "limit_id": "codex",
                        "primary": {
                            "used_percent": used_percent,
                            "window_minutes": window,
                            "resets_at": 1786825858,
                        },
                        "secondary": None,
                        "credits": {"has_credits": True, "unlimited": False, "balance": "9245.38"},
                    }
                },
            }
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path / "sessions"


def test_from_rollout_mints_a_measured_observation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The headroom number Codex already wrote to disk is a measurement, not an attestation."""
    sessions = _rollout(tmp_path, observed="2026-08-09T21:19:03.426Z")
    rc = mod.main(
        [
            "--receipt-dir",
            str(tmp_path / "r"),
            "--json",
            "--from-rollout",
            "--sessions-dir",
            str(sessions),
            "--now",
            "2026-08-09T21:25:00Z",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["observation"] == "subscription_quota_headroom_observed"
    # Stamped with the observation's own time, never "now" — a later stamp would overstate it.
    assert out["observed_at"] == "2026-08-09T21:19:03Z"
    assert out["measured"]["primary_remaining_percent"] == 98.0
    assert out["measured"]["provider_calls_made"] == 0
    written = sorted((tmp_path / "r").glob("*.yaml"))
    assert len(written) == 1
    fields = _fields(written[0])
    assert fields["evidence_ref"] == "codex-subscription-headroom-observed-20260809t2119z"
    assert fields["account_live_quota_observed"] == "true"


def test_from_rollout_never_carries_rollout_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Rollouts hold operator prompts and model output. Only the numbers may leave."""
    secret = "OPERATOR PROMPT: nuclear codes and /home/someone/private/path"
    sessions = _rollout(tmp_path, observed="2026-08-09T21:19:03.426Z", secret=secret)
    assert (
        mod.main(
            [
                "--receipt-dir",
                str(tmp_path / "r"),
                "--json",
                "--from-rollout",
                "--sessions-dir",
                str(sessions),
                "--now",
                "2026-08-09T21:25:00Z",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    receipt = (sorted((tmp_path / "r").glob("*.yaml"))[0]).read_text(encoding="utf-8")
    for blob in (captured.out, captured.err, receipt):
        assert "nuclear codes" not in blob
        assert "/home/someone" not in blob
        assert "OPERATOR PROMPT" not in blob


def test_from_rollout_refuses_a_stale_observation(tmp_path: Path) -> None:
    sessions = _rollout(tmp_path, observed="2026-08-09T10:00:00Z")
    assert (
        mod.main(
            [
                "--receipt-dir",
                str(tmp_path / "r"),
                "--from-rollout",
                "--sessions-dir",
                str(sessions),
                "--now",
                "2026-08-09T21:25:00Z",
            ]
        )
        == 2
    )
    assert not list((tmp_path / "r").glob("*.yaml"))


def test_from_rollout_refuses_an_exhausted_window(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A full window is a wall, not headroom — admitting on fumes is the failure to avoid."""
    sessions = _rollout(tmp_path, observed="2026-08-09T21:19:03Z", used_percent=100.0)
    assert (
        mod.main(
            [
                "--receipt-dir",
                str(tmp_path / "r"),
                "--from-rollout",
                "--sessions-dir",
                str(sessions),
                "--now",
                "2026-08-09T21:25:00Z",
            ]
        )
        == 2
    )
    assert "quota wall, not headroom" in capsys.readouterr().err
    assert not list((tmp_path / "r").glob("*.yaml"))


def test_from_rollout_refuses_when_no_snapshot_exists(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "rollout-empty.jsonl").write_text('{"timestamp":"x","type":"event_msg"}\n')
    assert (
        mod.main(
            [
                "--receipt-dir",
                str(tmp_path / "r"),
                "--from-rollout",
                "--sessions-dir",
                str(sessions),
                "--now",
                "2026-08-09T21:25:00Z",
            ]
        )
        == 2
    )


def test_unstamped_witness_is_refused(tmp_path: Path) -> None:
    """The allowlist requires a timestamped witness, so a bare claim cannot admit."""
    assert _run(tmp_path, "--evidence-ref", "codex-subscription-headroom-observed") == 2
    assert _receipts(tmp_path) == []
