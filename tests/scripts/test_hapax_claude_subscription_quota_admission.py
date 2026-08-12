"""Tests for ``scripts/hapax-claude-subscription-quota-admission``."""

from __future__ import annotations

import json
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-claude-subscription-quota-admission"


def _load_module() -> ModuleType:
    loader = SourceFileLoader("hapax_claude_subscription_quota_admission_under_test", str(SCRIPT))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


def _run(argv: list[str]) -> int:
    return _load_module().main(argv)


def test_writes_short_lived_safe_account_live_receipt(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    receipt_dir = tmp_path / "receipts"

    rc = _run(
        [
            "--receipt-dir",
            str(receipt_dir),
            "--now",
            "2026-07-08T14:00:00Z",
            "--evidence-ref",
            "claude-subscription-headroom-observed-20260708t1400z",
            "--observation",
            "subscription_quota_headroom_observed",
            "--stale-after-seconds",
            "900",
            "--json",
        ]
    )

    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["route_id"] == "claude.headless.full"
    assert summary["capacity_pool"] == "subscription_quota"
    assert summary["auth_surface"] == "subscription"
    assert summary["observation"] == "subscription_quota_headroom_observed"
    assert summary["observed_at"] == "2026-07-08T14:00:00Z"
    assert summary["fresh_until"] == "2026-07-08T14:15:00Z"
    assert summary["account_live_quota_observed"] is True
    assert summary["lane_presence_used_as_quota_evidence"] is False

    path = Path(summary["path"])
    assert "claude-subscription-quota-admission" in path.name
    assert "claude-headless-full" in path.name
    receipt = path.read_text(encoding="utf-8")
    assert "schema: hapax.claude_quota_admission.v1" in receipt
    assert "status: quota_available" in receipt
    assert "provider: anthropic-claude-subscription" in receipt
    assert "route_id: claude.headless.full" in receipt
    assert "capacity_pool: subscription_quota" in receipt
    assert "auth_surface: subscription" in receipt
    assert "observation: subscription_quota_headroom_observed" in receipt
    assert "evidence_ref: claude-subscription-headroom-observed-20260708t1400z" in receipt
    assert "secret_source: claude:operator-session-subscription" in receipt
    assert "account_live_quota_observed: true" in receipt
    assert "lane_presence_used_as_quota_evidence: false" in receipt
    assert "positive_admission: true" in receipt
    # short-lived + owner-only (no world/group access to a governed receipt)
    assert path.stat().st_mode & 0o777 == 0o600


def test_never_persists_secret_or_content(tmp_path: Path) -> None:
    rc = _run(
        [
            "--receipt-dir",
            str(tmp_path),
            "--evidence-ref",
            "claude-subscription-headroom-observed-20260708t1400z",
        ]
    )
    assert rc == 0
    receipt = next(tmp_path.glob("claude-subscription-quota-admission-*.yaml"))
    body = receipt.read_text(encoding="utf-8")
    assert "secret_value_persisted: false" in body
    assert "prompt_or_output_persisted: false" in body


def test_default_receipt_names_are_route_distinct_for_same_second(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "receipts"
    base_args = [
        "--receipt-dir",
        str(receipt_dir),
        "--now",
        "2026-07-08T14:00:00Z",
        "--evidence-ref",
        "claude-subscription-headroom-observed-20260708t1400z",
    ]

    headless_rc = _run([*base_args, "--route-id", "claude.headless.full"])
    review_rc = _run([*base_args, "--route-id", "claude.review.opus"])

    assert headless_rc == 0
    assert review_rc == 0
    names = {path.name for path in receipt_dir.glob("*.yaml")}
    assert names == {
        "claude-subscription-quota-admission-claude-headless-full-20260708t140000z.yaml",
        "claude-subscription-quota-admission-claude-review-opus-20260708t140000z.yaml",
    }


def test_rejects_secretish_evidence_ref_fails_closed(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    receipt_dir = tmp_path / "receipts"
    rc = _run(
        [
            "--receipt-dir",
            str(receipt_dir),
            "--evidence-ref",
            "claude-secret-headroom-20260708",
        ]
    )
    assert rc == 2
    assert "unsafe evidence-ref" in capsys.readouterr().err
    # fail-closed: nothing written on an unsafe observation
    assert not receipt_dir.exists() or not any(receipt_dir.iterdir())


def test_rejects_billing_identifier_evidence_ref(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    for ref in (
        "claude-billing-cus_123-headroom-20260708",
        "claude-subscription-sub_123-headroom-20260708",
        "claude-subscription-id-123-headroom-20260708",
        "claude-subscription_id_123_headroom-20260708",
        "claude-subscription+id+123-headroom-20260708",
        "claude-account-acct_123-headroom-20260708",
        "claude-billing+cus_123-headroom-20260708",
        "claude-billing-cus.123-headroom-20260708",
        "claude-account-acct.123-headroom-20260708",
        "claude-subscription-sub.123-headroom-20260708",
        "claude-cus123-headroom-20260708",
        "claude-sub123-headroom-20260708",
        "claude-acct123-headroom-20260708",
        "claude-in123-headroom-20260708",
        "claude-ch123-headroom-20260708",
        "claude-invoice7-headroom-20260708",
        "claude-billingcus123-headroom-20260708",
        "claude-in_123-headroom-20260708",
        "claude-ch_123-headroom-20260708",
    ):
        rc = _run(["--receipt-dir", str(tmp_path), "--evidence-ref", ref])
        assert rc == 2
        assert "billing/account identifiers must not be persisted" in capsys.readouterr().err
    assert not any(tmp_path.glob("*.yaml"))


def test_rejects_unsupported_evidence_ref_shape(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    rc = _run(
        [
            "--receipt-dir",
            str(tmp_path),
            "--evidence-ref",
            "claude-si-1abc-headroom",
        ]
    )

    assert rc == 2
    assert "expected a claude subscription headroom witness reference" in capsys.readouterr().err
    assert not any(tmp_path.glob("*.yaml"))


def test_rejects_lane_presence_evidence_ref(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    # lane/tmux/session presence must never be laundered into quota evidence.
    for ref in (
        "tmux-claude-headroom-20260708",
        "hapax-claude-eta-present-20260708",
        "eta",
        "theta",
        "cx-eta",
        "cx-theta",
        "claude-session-observed-20260708t1400z",
        "claude-lane-observed-20260708t1400z",
        "claude-sessions-observed-20260708t1400z",
        "claude-lanes-observed-20260708t1400z",
        "claude-session2-observed-20260708t1400z",
        "claude-lane2-observed-20260708t1400z",
        "claude-headroom-eta2-observed",
        "eta2",
        "eta+present",
        "claude+headroom+eta+observed",
        "tmux2-headroom",
        "vbe-3-headroom",
        "mu-headroom",
    ):
        rc = _run(["--receipt-dir", str(tmp_path), "--evidence-ref", ref])
        assert rc == 2
        assert "lane/tmux/session presence must not be used as quota evidence" in (
            capsys.readouterr().err
        )
    assert not any(tmp_path.glob("*.yaml"))


def test_rejects_unknown_observation(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    rc = _run(
        [
            "--receipt-dir",
            str(tmp_path),
            "--evidence-ref",
            "claude-subscription-headroom-observed-20260708t1400z",
            "--observation",
            "lane_exists",
        ]
    )
    assert rc == 2
    assert "invalid --observation" in capsys.readouterr().err
    assert not any(tmp_path.glob("*.yaml"))


def test_rejects_out_of_bounds_stale_after(tmp_path: Path) -> None:
    for stale in ("30", "99999"):
        rc = _run(
            [
                "--receipt-dir",
                str(tmp_path),
                "--evidence-ref",
                "claude-subscription-headroom-observed-20260708t1400z",
                "--stale-after-seconds",
                stale,
            ]
        )
        assert rc == 2
    assert not any(tmp_path.glob("*.yaml"))


def test_rejects_invalid_now(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    rc = _run(
        [
            "--receipt-dir",
            str(tmp_path),
            "--now",
            "not-a-date",
            "--evidence-ref",
            "claude-subscription-headroom-observed-20260708t1400z",
        ]
    )

    assert rc == 2
    assert "invalid --now" in capsys.readouterr().err
    assert not any(tmp_path.glob("*.yaml"))


def test_rejects_unsafe_receipt_name(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    rc = _run(
        [
            "--receipt-dir",
            str(tmp_path),
            "--receipt-name",
            "bad#claude-subscription-quota-admission.yaml",
            "--evidence-ref",
            "claude-subscription-headroom-observed-20260708t1400z",
        ]
    )

    assert rc == 2
    assert "unsafe receipt name" in capsys.readouterr().err
    assert not any(tmp_path.glob("*.yaml"))


def test_rejects_billing_identifier_receipt_name(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    for name in (
        "claude-subscription-quota-admission-cus_123.yaml",
        "claude-subscription-quota-admission-subscription-id-123.yaml",
        "claude-subscription-quota-admission-subscription_id_123.yaml",
        "claude-subscription-quota-admission-subscription+id+123.yaml",
        "claude-subscription-quota-admission-invoice7.yaml",
        "claude-subscription-quota-admission-billing+cus_123.yaml",
        "claude-subscription-quota-admission-cus.123.yaml",
        "claude-subscription-quota-admission-acct.123.yaml",
        "claude-subscription-quota-admission-sub.123.yaml",
        "claude-subscription-quota-admission-cus123.yaml",
        "claude-subscription-quota-admission-sub123.yaml",
        "claude-subscription-quota-admission-acct123.yaml",
        "claude-subscription-quota-admission-in123.yaml",
        "claude-subscription-quota-admission-ch123.yaml",
        "claude-subscription-quota-admission-billingcus123.yaml",
        "claude-subscription-quota-admission-ch_123.yaml",
    ):
        rc = _run(
            [
                "--receipt-dir",
                str(tmp_path),
                "--receipt-name",
                name,
                "--evidence-ref",
                "claude-subscription-headroom-observed-20260708t1400z",
            ]
        )

        assert rc == 2
        assert "billing/account identifiers must not be persisted" in capsys.readouterr().err
    assert not any(tmp_path.glob("*.yaml"))


def test_rejects_lane_presence_receipt_name(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    for name in (
        "eta-claude-subscription-quota-admission.yaml",
        "claude-subscription-quota-admission-eta2.yaml",
        "claude-subscription-quota-admission-eta+present.yaml",
        "claude-subscription-quota-admission-session2.yaml",
        "claude-subscription-quota-admission-lane2.yaml",
    ):
        rc = _run(
            [
                "--receipt-dir",
                str(tmp_path),
                "--receipt-name",
                name,
                "--evidence-ref",
                "claude-subscription-headroom-observed-20260708t1400z",
            ]
        )

        assert rc == 2
        assert "receipt name" in capsys.readouterr().err
    assert not any(tmp_path.glob("*.yaml"))


def test_rejects_receipt_name_without_claude_admission_label(
    tmp_path: Path,
    capsys,
) -> None:  # noqa: ANN001
    rc = _run(
        [
            "--receipt-dir",
            str(tmp_path),
            "--receipt-name",
            "safe-but-wrong.yaml",
            "--evidence-ref",
            "claude-subscription-headroom-observed-20260708t1400z",
        ]
    )

    assert rc == 2
    assert "receipt name must contain 'claude-subscription-quota-admission'" in (
        capsys.readouterr().err
    )
    assert not any(tmp_path.glob("*.yaml"))


def test_write_oserror_returns_one(tmp_path: Path, monkeypatch, capsys) -> None:  # noqa: ANN001
    module = _load_module()

    def _boom(path, fields):  # noqa: ANN001, ANN202
        raise OSError("disk full")

    monkeypatch.setattr(module, "_write_flat_yaml_atomic", _boom)
    rc = module.main(
        [
            "--receipt-dir",
            str(tmp_path),
            "--evidence-ref",
            "claude-subscription-headroom-observed-20260708t1400z",
        ]
    )
    assert rc == 1
    assert "failed to write receipt" in capsys.readouterr().err


# --- --from-transcript: measurement instead of attestation -------------------------
#
# The default path takes whatever --evidence-ref the caller types; it validates the
# *shape* of the claim, never that the observation happened. --from-transcript closes
# that: the evidence ref and observed_at are both derived from a real completed Claude
# turn, so a timer firing on a cadence asserts something that was actually checked.


def _fake_observation(stamp: str, witness: str):  # noqa: ANN202
    from datetime import UTC, datetime

    class _Obs:
        observed_at = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(UTC)

    _Obs.witness = witness
    return _Obs()


def _subscription_session(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """The auth evidence --from-transcript now requires before it will read anything.

    A measured receipt claims the turns were served BY THE SUBSCRIPTION, so the account marker
    and the session identity are preconditions rather than decoration. Faking the transcript
    alone no longer produces a receipt — which is exactly the change these tests were updated
    for, and a test that kept passing without this would have proved the guard was skippable.
    """
    from shared.claude_auth_surface import API_KEY_ENV_VARS, CLAUDE_CONFIG_ENV, SESSION_ID_ENV

    config = tmp_path / "claude.json"
    config.write_text(
        json.dumps(
            {
                "oauthAccount": {
                    "billingType": "google_play_subscription",
                    "organizationType": "claude_max",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(CLAUDE_CONFIG_ENV, str(config))
    monkeypatch.setenv(SESSION_ID_ENV, "8e98d395-97d6-4ff0-9619-e61927dcfdb0")
    for var in API_KEY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_from_transcript_stamps_the_turns_time_not_now(  # noqa: ANN001
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """observed_at must be the turn's own timestamp. Stamping `now` would open a
    freshness window wider than the evidence supports."""
    module = _load_module()
    import shared.claude_transcript_quota as ctq

    _subscription_session(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ctq,
        "latest_transcript_observation",
        lambda **_kw: _fake_observation(
            "2026-08-11T16:47:25Z",
            "claude-subscription-headroom-observed-20260811t164725z",
        ),
    )

    rc = module.main(
        [
            "--receipt-dir",
            str(tmp_path),
            "--from-transcript",
            "--route-id",
            "claude.review.opus",
            "--stale-after-seconds",
            "3600",
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["observed_at"] == "2026-08-11T16:47:25Z"
    assert payload["fresh_until"] == "2026-08-11T17:47:25Z"
    assert payload["observation"] == "subscription_quota_headroom_observed"
    assert payload["lane_presence_used_as_quota_evidence"] is False


def test_from_transcript_fails_closed_when_no_observation(  # noqa: ANN001
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Idle estate, stale turn, clock skew -- all arrive here, and all must write
    nothing. A timer that mints anyway is attesting a fact nobody checked."""
    module = _load_module()
    import shared.claude_transcript_quota as ctq

    def _unavailable(**_kw):  # noqa: ANN202
        raise ctq.TranscriptQuotaUnavailable("freshest completed turn is 5000s old")

    # Auth satisfied on purpose, so the refusal under test is the STALE TURN rather than the auth
    # gate standing in front of it. A test that passes for the wrong reason proves nothing.
    _subscription_session(tmp_path, monkeypatch)
    monkeypatch.setattr(ctq, "latest_transcript_observation", _unavailable)

    rc = module.main(["--receipt-dir", str(tmp_path), "--from-transcript"])

    assert rc == 2
    assert "no live transcript observation" in capsys.readouterr().err
    assert not any(tmp_path.glob("*.yaml"))


def test_from_transcript_refuses_when_the_session_carries_a_gateway(  # noqa: ANN001
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A live turn is not evidence of a SUBSCRIPTION turn.

    Measured on this host 2026-08-12: ANTHROPIC_AUTH_TOKEN and ANTHROPIC_BASE_URL are both set in
    the working session, so turns there may be served through a gateway and the transcript looks
    identical either way. The measured path must refuse rather than mint a subscription claim it
    cannot support — and it must refuse even though the transcript observation itself succeeds.
    """
    module = _load_module()
    import shared.claude_transcript_quota as ctq

    _subscription_session(tmp_path, monkeypatch)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example.test")
    monkeypatch.setattr(
        ctq,
        "latest_transcript_observation",
        lambda **_kw: _fake_observation(
            "2026-08-11T16:47:25Z",
            "claude-subscription-headroom-observed-20260811t164725z",
        ),
    )

    rc = module.main(["--receipt-dir", str(tmp_path), "--from-transcript"])

    assert rc == 2
    assert "ANTHROPIC_BASE_URL" in capsys.readouterr().err
    assert not any(tmp_path.glob("*.yaml")), "a receipt was written despite an unprovable claim"


def test_from_transcript_refuses_outside_a_claude_session(  # noqa: ANN001
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Run from cron, the observing process's environment says nothing about the turns it reads."""
    from shared.claude_auth_surface import SESSION_ID_ENV

    module = _load_module()
    import shared.claude_transcript_quota as ctq

    _subscription_session(tmp_path, monkeypatch)
    monkeypatch.delenv(SESSION_ID_ENV, raising=False)
    monkeypatch.setattr(
        ctq,
        "latest_transcript_observation",
        lambda **_kw: _fake_observation(
            "2026-08-11T16:47:25Z",
            "claude-subscription-headroom-observed-20260811t164725z",
        ),
    )

    rc = module.main(["--receipt-dir", str(tmp_path), "--from-transcript"])

    assert rc == 2
    assert not any(tmp_path.glob("*.yaml"))


def test_the_measured_path_reads_only_its_own_sessions_transcript(  # noqa: ANN001
    tmp_path: Path, monkeypatch
) -> None:
    """The auth evidence covers one session, so the scan must be bounded to that session.

    Asserted on the argument actually passed, because the pairing is invisible otherwise: a scan
    that quietly widened would still return a fresh turn and still mint a receipt.
    """
    module = _load_module()
    import shared.claude_transcript_quota as ctq

    _subscription_session(tmp_path, monkeypatch)
    seen: dict = {}

    def _record(**kw):  # noqa: ANN202
        seen.update(kw)
        return _fake_observation(
            "2026-08-11T16:47:25Z",
            "claude-subscription-headroom-observed-20260811t164725z",
        )

    monkeypatch.setattr(ctq, "latest_transcript_observation", _record)

    module.main(["--receipt-dir", str(tmp_path), "--from-transcript"])

    assert seen.get("session_id") == "8e98d395-97d6-4ff0-9619-e61927dcfdb0"


def test_from_transcript_refuses_a_hand_supplied_evidence_ref(  # noqa: ANN001
    tmp_path: Path, capsys
) -> None:
    """Measured and attested are different claims; do not let one wear the other."""
    rc = _run(
        [
            "--receipt-dir",
            str(tmp_path),
            "--from-transcript",
            "--evidence-ref",
            "claude-subscription-headroom-observed-20260708t1400z",
        ]
    )

    assert rc == 2
    assert "do not pass both" in capsys.readouterr().err
    assert not any(tmp_path.glob("*.yaml"))


def test_from_transcript_cannot_claim_the_operator_observation(  # noqa: ANN001
    tmp_path: Path, capsys
) -> None:
    """A transcript witnesses liveness, never an operator's confirmation of headroom.
    Only the operator can make that claim."""
    rc = _run(
        [
            "--receipt-dir",
            str(tmp_path),
            "--from-transcript",
            "--observation",
            "operator_confirmed_subscription_headroom",
        ]
    )

    assert rc == 2
    assert "can only support" in capsys.readouterr().err
    assert not any(tmp_path.glob("*.yaml"))


def test_evidence_ref_still_required_without_from_transcript(  # noqa: ANN001
    tmp_path: Path, capsys
) -> None:
    rc = _run(["--receipt-dir", str(tmp_path)])

    assert rc == 2
    assert "--evidence-ref is required" in capsys.readouterr().err
    assert not any(tmp_path.glob("*.yaml"))


def test_rejects_out_of_bounds_max_observation_age(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    """The knob that can hollow out the whole mode.

    `--max-observation-age-seconds 999999` would mint from a turn observed yesterday --
    returning the measured path to an attestation, quietly, with no other signal that
    anything changed. It gets the same clamp as its `--stale-after-seconds` sibling.
    """
    for age in ("30", "999999"):
        rc = _run(
            [
                "--receipt-dir",
                str(tmp_path),
                "--from-transcript",
                "--max-observation-age-seconds",
                age,
            ]
        )

        assert rc == 2
        assert "--max-observation-age-seconds must be between" in capsys.readouterr().err
    assert not any(tmp_path.glob("*.yaml"))


def test_max_observation_age_is_checked_before_the_transcript_is_read(  # noqa: ANN001
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The clamp must reject the argument, not merely be ignored downstream.

    Without ordering, an out-of-bounds value could still be handed to the observer -- the
    refusal has to happen before any observation is attempted, or a wide window is doing
    real work before anyone complains about it.
    """
    module = _load_module()
    import shared.claude_transcript_quota as ctq

    def _must_not_run(**_kw):  # noqa: ANN202
        raise AssertionError("observer was called despite an out-of-bounds window")

    monkeypatch.setattr(ctq, "latest_transcript_observation", _must_not_run)

    rc = module.main(
        [
            "--receipt-dir",
            str(tmp_path),
            "--from-transcript",
            "--max-observation-age-seconds",
            "999999",
        ]
    )

    assert rc == 2
    assert "--max-observation-age-seconds must be between" in capsys.readouterr().err


def test_the_recovery_hint_matches_the_mode_it_is_printed_in(  # noqa: ANN001
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """An error message that names an impossible next action is worse than none.

    Under --from-transcript the tool DERIVES the evidence-ref and refuses a supplied one,
    so the attested path's hint -- "pass a sanitized --evidence-ref" -- is advice the caller
    cannot take. Each mode gets the hint that is actually actionable in it.
    """
    module = _load_module()
    import shared.claude_transcript_quota as ctq

    def _unavailable(**_kw):  # noqa: ANN202
        raise ctq.TranscriptQuotaUnavailable("freshest completed turn is 5000s old")

    # Auth satisfied on purpose, so the refusal under test is the STALE TURN rather than the auth
    # gate standing in front of it. A test that passes for the wrong reason proves nothing.
    _subscription_session(tmp_path, monkeypatch)
    monkeypatch.setattr(ctq, "latest_transcript_observation", _unavailable)

    rc = module.main(["--receipt-dir", str(tmp_path), "--from-transcript"])
    measured_err = capsys.readouterr().err

    assert rc == 2
    assert "do not supply --evidence-ref" in measured_err
    assert "pass a sanitized --evidence-ref" not in measured_err

    rc = _run(["--receipt-dir", str(tmp_path), "--evidence-ref", "not a safe ref"])
    attested_err = capsys.readouterr().err

    assert rc == 2
    assert "pass a sanitized --evidence-ref" in attested_err
