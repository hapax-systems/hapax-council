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
