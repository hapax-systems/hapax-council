"""Tests for ``scripts/hapax-claude-subscription-quota-admission``."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import ModuleType

import pytest

import shared.durable_jsonl_sink as sink_mod
from shared.platform_capability_registry import ResolvedSubscriptionPool

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-claude-subscription-quota-admission"
PACE_SCRIPT = REPO_ROOT / "scripts" / "hapax-claude-pool-pace"


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


def test_probe_receipt_records_the_fixed_environment_scrub(tmp_path: Path, capsys) -> None:
    rc = _run(
        [
            "--receipt-dir",
            str(tmp_path),
            "--evidence-ref",
            "claude-subscription-headroom-observed-20260708t1400z",
            "--probe-environment-scrubbed",
            "--json",
        ]
    )

    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    expected = [
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_MODEL",
    ]
    assert summary["probe_environment_scrubbed"] == expected
    body = Path(summary["path"]).read_text(encoding="utf-8")
    assert f"probe_environment_scrubbed: {','.join(expected)}" in body


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
    interactive_rc = _run([*base_args, "--route-id", "claude.interactive.full"])

    assert headless_rc == 0
    assert interactive_rc == 0
    names = {path.name for path in receipt_dir.glob("*.yaml")}
    assert names == {
        "claude-subscription-quota-admission-claude-headless-full-20260708t140000z.yaml",
        "claude-subscription-quota-admission-claude-interactive-full-20260708t140000z.yaml",
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


# --- A route bound to one declared subscription pool (claude.review.opus -> max-2) ---------------
#
# The reading's pool is the config dir the probe ran under (CLAUDE_CONFIG_DIR, or the CLI default
# ~/.claude), plus the receipt dir, headless traces, pace marker and durable sink its pace reading
# came from. Every one of them must be the route's declared pool, or nothing is written.

POOL_NOW = datetime(2026, 9, 25, 23, 0, 0, tzinfo=UTC)
POOL_WEEKLY_RESET = POOL_NOW - timedelta(hours=24) + timedelta(hours=168)  # line at now: 16.4 %
REVIEW_ROUTE = "claude.review.opus"


def _pace_module() -> ModuleType:
    loader = SourceFileLoader("hapax_claude_pool_pace_for_pool_binding", str(PACE_SCRIPT))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


def _stamp(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def _window_receipt(receipt_dir: Path, *, weekly_used: float, observed_at: datetime) -> None:
    """The probe-backed reading the pace governor reads, in the pool's own receipt dir."""
    stamp = observed_at.strftime("%Y%m%dt%H%M%Sz")
    (
        receipt_dir / f"claude-subscription-quota-admission-claude-headless-full-{stamp}.yaml"
    ).write_text(
        "\n".join(
            [
                "schema: hapax.claude_quota_admission.v1",
                "status: quota_available",
                "provider: anthropic-claude-subscription",
                "route_id: claude.headless.full",
                "capacity_pool: subscription_quota",
                "auth_surface: subscription",
                "observation: subscription_quota_headroom_observed",
                f"observed_at: {_stamp(observed_at)}",
                "stale_after_seconds: 1800",
                f"evidence_ref: claude-subscription-headroom-observed-{stamp}",
                "secret_source: claude:operator-session-subscription",
                "secret_value_persisted: false",
                "prompt_or_output_persisted: false",
                "billing_mode: operator_session_subscription",
                "account_live_quota_observed: true",
                "lane_presence_used_as_quota_evidence: false",
                "positive_admission: true",
                "probe_environment_scrubbed: true",
                "subscription_served: true",
                f"seven_day_used_percent: {weekly_used}",
                f"seven_day_resets_at: {_stamp(POOL_WEEKLY_RESET)}",
                "five_hour_used_percent: 1.0",
                f"five_hour_resets_at: {_stamp(observed_at + timedelta(hours=3))}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _headless_glob(binding: ResolvedSubscriptionPool) -> str:
    return str(binding.headless_dir / "*" / "output.jsonl")


def _bound_pool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    *,
    weekly_used: float = 5.0,
    reading_at: datetime = POOL_NOW,
) -> ResolvedSubscriptionPool:
    """A declared pool on disk, its pace reading ledgered, and the process running inside it."""
    root = tmp_path / "pool-max-2"
    binding = ResolvedSubscriptionPool(
        route_id=REVIEW_ROUTE,
        pool="max-2",
        config_dir=root / "config",
        receipt_dir=root / "receipts",
        headless_dir=root / "headless",
        pace_activation=root / "pace" / "activation.json",
        durable_sink_root=root / "durable",
    )
    for directory in (
        binding.config_dir,
        binding.receipt_dir,
        binding.headless_dir,
        binding.pace_activation.parent,
        binding.durable_sink_root,
    ):
        directory.mkdir(parents=True)
    binding.pace_activation.write_text(
        json.dumps({"activated_at": _stamp(POOL_NOW), "by": "seat", "reason": "test"}) + "\n",
        encoding="utf-8",
    )
    _window_receipt(binding.receipt_dir, weekly_used=weekly_used, observed_at=reading_at)
    monkeypatch.setattr(sink_mod, "_mount_fstype_for_path", lambda _path: "btrfs")
    monkeypatch.setenv(sink_mod.DEFAULT_ROOT_ENV, str(binding.durable_sink_root))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(binding.config_dir))
    pace = _pace_module()
    state = pace.read_state(binding.receipt_dir, _headless_glob(binding), now=POOL_NOW)
    if state.get("weekly_used_percent") is not None:
        pace.append_reading(pace.reading_payload(state), now=POOL_NOW)
    monkeypatch.setattr(
        module,
        "_declared_pool_binding",
        lambda route_id: binding if route_id == REVIEW_ROUTE else None,
    )
    return binding


def _bound_args(binding: ResolvedSubscriptionPool, **override: str) -> list[str]:
    values = {
        "--receipt-dir": str(binding.receipt_dir),
        "--pace-receipt-dir": str(binding.receipt_dir),
        "--pace-headless-glob": _headless_glob(binding),
        "--pace-activation": str(binding.pace_activation),
    }
    values.update({f"--{key.replace('_', '-')}": value for key, value in override.items()})
    argv = [
        "--route-id",
        REVIEW_ROUTE,
        "--now",
        _stamp(POOL_NOW),
        "--pace-now",
        _stamp(POOL_NOW),
        "--evidence-ref",
        "claude-subscription-headroom-observed-20260925t2300z",
        "--stale-after-seconds",
        "900",
        "--json",
    ]
    for flag, value in values.items():
        argv += [flag, value]
    return argv


def _review_receipts(directory: Path) -> list[Path]:
    return sorted(directory.glob("*claude-review-opus*.yaml")) if directory.is_dir() else []


def test_bound_route_mints_from_its_declared_pool_and_names_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:  # noqa: ANN001
    module = _load_module()
    binding = _bound_pool(tmp_path, monkeypatch, module)

    rc = module.main(_bound_args(binding))

    assert rc == 0, capsys.readouterr().err
    summary = json.loads(capsys.readouterr().out)
    assert summary["pool"] == "max-2"
    [receipt] = _review_receipts(binding.receipt_dir)
    assert receipt.name == (
        "claude-subscription-quota-admission-claude-review-opus-pool-max-2-20260925t230000z.yaml"
    )
    body = receipt.read_text(encoding="utf-8")
    assert "route_id: claude.review.opus\n" in body
    assert "pool: max-2\n" in body


def test_bound_route_refuses_a_reading_from_the_default_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:  # noqa: ANN001
    """The unsafe case: the account-1 observer (no CLAUDE_CONFIG_DIR, so ~/.claude) never mints
    the max-2-bound route, however healthy its own reading."""
    module = _load_module()
    binding = _bound_pool(tmp_path, monkeypatch, module)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")

    rc = module.main(_bound_args(binding))

    assert rc == 2
    err = capsys.readouterr().err
    assert "bound to subscription pool max-2" in err
    assert "config_dir" in err
    assert _review_receipts(binding.receipt_dir) == []


def test_bound_route_refuses_a_reading_from_a_conflicting_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:  # noqa: ANN001
    module = _load_module()
    binding = _bound_pool(tmp_path, monkeypatch, module)
    other = tmp_path / "another-pool-config"
    other.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(other))

    rc = module.main(_bound_args(binding))

    assert rc == 2
    assert "config_dir" in capsys.readouterr().err
    assert _review_receipts(binding.receipt_dir) == []


@pytest.mark.parametrize(
    "surface",
    [
        "receipt_dir",
        "pace_receipt_dir",
        "pace_headless_glob",
        "pace_activation",
        "durable_sink_root",
    ],
)
def test_bound_route_refuses_any_surface_from_another_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, surface: str
) -> None:  # noqa: ANN001
    """A reading is the pool's only if its receipts, traces, pace marker and ledger are the pool's."""
    module = _load_module()
    binding = _bound_pool(tmp_path, monkeypatch, module)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    override: dict[str, str] = {}
    if surface == "durable_sink_root":
        monkeypatch.setenv(sink_mod.DEFAULT_ROOT_ENV, str(elsewhere))
    elif surface == "pace_headless_glob":
        override[surface] = str(elsewhere / "*" / "output.jsonl")
    elif surface == "pace_activation":
        override[surface] = str(elsewhere / "activation.json")
    else:
        override[surface] = str(elsewhere)

    rc = module.main(_bound_args(binding, **override))

    assert rc == 2
    assert surface in capsys.readouterr().err
    assert _review_receipts(binding.receipt_dir) == []
    assert _review_receipts(elsewhere) == []


def test_bound_route_refuses_without_a_durable_sink_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:  # noqa: ANN001
    module = _load_module()
    binding = _bound_pool(tmp_path, monkeypatch, module)
    monkeypatch.delenv(sink_mod.DEFAULT_ROOT_ENV)

    rc = module.main(_bound_args(binding))

    assert rc == 2
    assert "durable_sink_root" in capsys.readouterr().err
    assert _review_receipts(binding.receipt_dir) == []


def test_bound_route_over_its_line_stays_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:  # noqa: ANN001
    """The pool matches, but its own reading is over its line: the pace gate refuses (exit 3)."""
    module = _load_module()
    binding = _bound_pool(tmp_path, monkeypatch, module, weekly_used=40.0)

    rc = module.main(_bound_args(binding))

    assert rc == 3
    assert "pace_line_exceeded" in capsys.readouterr().err
    assert _review_receipts(binding.receipt_dir) == []


def test_bound_route_with_a_stale_pool_reading_stays_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:  # noqa: ANN001
    module = _load_module()
    binding = _bound_pool(tmp_path, monkeypatch, module, reading_at=POOL_NOW - timedelta(hours=2))

    rc = module.main(_bound_args(binding))

    assert rc == 3
    assert _review_receipts(binding.receipt_dir) == []


def test_bound_route_refuses_a_custom_receipt_name_that_drops_the_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:  # noqa: ANN001
    module = _load_module()
    binding = _bound_pool(tmp_path, monkeypatch, module)

    rc = module.main(
        [
            *_bound_args(binding),
            "--receipt-name",
            "claude-subscription-quota-admission-claude-review-opus-custom.yaml",
        ]
    )

    assert rc == 2
    assert "pool-max-2" in capsys.readouterr().err
    assert _review_receipts(binding.receipt_dir) == []


@pytest.mark.parametrize("route_id", ["claude.review.opus", "claude.headless.full"])
def test_an_unreadable_pool_binding_mints_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, route_id: str
) -> None:  # noqa: ANN001
    """Whether a route is bound cannot be known without the registry: refuse every route."""
    module = _load_module()

    def _unreadable(_route_id: str) -> None:
        raise module.PoolBindingRefused("the route pool binding could not be read (OSError)")

    monkeypatch.setattr(module, "_declared_pool_binding", _unreadable)

    rc = module.main(
        [
            "--receipt-dir",
            str(tmp_path),
            "--route-id",
            route_id,
            "--evidence-ref",
            "claude-subscription-headroom-observed-20260708t1400z",
        ]
    )

    assert rc == 2
    assert "could not be read" in capsys.readouterr().err
    assert not any(tmp_path.glob("*.yaml"))


def test_unbound_route_receipt_carries_no_pool(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    rc = _run(
        [
            "--receipt-dir",
            str(tmp_path),
            "--route-id",
            "claude.headless.full",
            "--evidence-ref",
            "claude-subscription-headroom-observed-20260708t1400z",
            "--json",
        ]
    )

    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert "pool" not in summary
    body = Path(summary["path"]).read_text(encoding="utf-8")
    assert "\npool:" not in body
    assert "-pool-" not in Path(summary["path"]).name


def test_the_registry_binds_the_review_route_and_only_it() -> None:
    """The writer reads the real declaration: claude.review.opus bills max-2; the account-1
    routes stay unbound (the CLI default config dir)."""
    module = _load_module()
    binding = module._declared_pool_binding(REVIEW_ROUTE)
    assert binding is not None
    assert binding.pool == "max-2"
    assert binding.config_dir == Path.home() / ".claude-max-2"
    assert module._declared_pool_binding("claude.headless.full") is None
    assert module._declared_pool_binding("claude.interactive.full") is None
