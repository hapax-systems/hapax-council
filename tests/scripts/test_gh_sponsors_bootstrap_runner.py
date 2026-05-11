"""Contract tests for scripts/gh-sponsors-bootstrap-runner.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gh-sponsors-bootstrap-runner.py"
EXAMPLE = Path(__file__).resolve().parents[2] / "config" / "gh-sponsors-tiers.toml.example"


@pytest.fixture(scope="module")
def runner_mod() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gh_sponsors_bootstrap_runner", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _config(path: Path, *, duplicate_slug: bool = False, amount: int = 500) -> Path:
    second_slug = "supporter" if duplicate_slug else "one-time"
    path.write_text(
        f"""
schema_version = 1

[profile]
account = "hapax-llc"
legal_name = "Hapax LLC"
display_name = "Hapax"
description = "Operator-authored public research infrastructure."
profile_url_pass_key = "github-sponsors/profile-url"
tier_id_pass_key_prefix = "github-sponsors/tiers"

[[tiers]]
slug = "supporter"
kind = "monthly"
amount_usd_cents = {amount}
title = "Supporter"
description = "Monthly support."

[[tiers]]
slug = "{second_slug}"
kind = "one_time"
amount_usd_cents = 2500
title = "One-time"
description = "One-time support."
""".lstrip(),
        encoding="utf-8",
    )
    return path


def test_example_config_loads_and_builds_plan(runner_mod: ModuleType) -> None:
    config = runner_mod.load_config(EXAMPLE)
    plan = runner_mod.build_plan(config)
    cassette = runner_mod.build_cassette(config)

    assert plan["profile"]["account"] == "hapax-systems"
    assert len(plan["tiers"]) == 4
    assert [tier["amount_usd_cents"] for tier in plan["tiers"]] == [
        100,
        500,
        1000,
        2500,
    ]
    assert plan["safety"]["dry_run_default"] is True
    assert plan["safety"]["does_not_touch_repo_sponsorships"] is True
    assert "github-sponsors/tiers/five-dollar" in {tier["pass_key"] for tier in plan["tiers"]}
    assert cassette["actions"][0]["action"] == "goto"
    assert {action["action"] for action in cassette["actions"]} >= {
        "fill_profile",
        "create_tier",
    }


def test_duplicate_tier_slugs_fail_closed(runner_mod: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(runner_mod.ConfigError, match="unique"):
        runner_mod.load_config(_config(tmp_path / "tiers.toml", duplicate_slug=True))


def test_non_positive_amount_fails_closed(runner_mod: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(runner_mod.ConfigError, match="positive"):
        runner_mod.load_config(_config(tmp_path / "tiers.toml", amount=0))


def test_main_dry_run_writes_plan_and_never_opens_browser(
    runner_mod: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_runner(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("dry run should not open Playwright")

    rc = runner_mod.main(
        [
            "--config",
            str(_config(tmp_path / "tiers.toml")),
            "--output-dir",
            str(tmp_path / "out"),
        ],
        portal_runner=fail_runner,
        env={},
    )

    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    out_dir = Path(summary["output_dir"])
    plan = json.loads((out_dir / "bootstrap-plan.json").read_text(encoding="utf-8"))
    cassette = json.loads((out_dir / "dry-run-cassette.json").read_text(encoding="utf-8"))
    assert plan["dashboard_url"].endswith("/sponsors/hapax-llc/dashboard")
    assert cassette["actions"][0]["url"] == plan["dashboard_url"]
    assert summary["applied"] is False
    assert summary["profile_url"] == "https://github.com/sponsors/hapax-llc"
    assert (out_dir / "pass-store-plan.sh").exists()


def test_apply_requires_live_env_and_does_not_open_browser(
    runner_mod: ModuleType,
    tmp_path: Path,
) -> None:
    called = False

    def runner(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return {}

    rc = runner_mod.main(
        [
            "--config",
            str(_config(tmp_path / "tiers.toml")),
            "--output-dir",
            str(tmp_path / "out"),
            "--apply",
        ],
        portal_runner=runner,
        env={},
    )

    assert rc == 2
    assert called is False


def test_apply_can_capture_tier_ids_and_write_pass_when_explicitly_gated(
    runner_mod: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    writes: list[tuple[str, str]] = []

    def runner(config: Any, *, output_dir: Path, apply: bool) -> dict[str, Any]:
        assert apply is True
        assert config.profile.account == "hapax-llc"
        return {
            "profile_url": "https://github.com/sponsors/hapax-llc",
            "tier_ids": {"supporter": "tier_123", "one-time": "tier_456"},
            "screenshot_path": str(output_dir / "preview.png"),
        }

    rc = runner_mod.main(
        [
            "--config",
            str(_config(tmp_path / "tiers.toml")),
            "--output-dir",
            str(tmp_path / "out"),
            "--apply",
            "--write-pass",
        ],
        portal_runner=runner,
        pass_writer=lambda key, value: writes.append((key, value)),
        env={runner_mod.LIVE_ENV: "1"},
    )

    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["applied"] is True
    keys = {key for key, _value in writes}
    assert keys == {
        "github-sponsors/profile-url",
        "github-sponsors/tiers/supporter",
        "github-sponsors/tiers/one-time",
    }
    supporter = dict(writes)["github-sponsors/tiers/supporter"]
    assert json.loads(supporter)["tier_id"] == "tier_123"


def test_write_pass_requires_apply(runner_mod: ModuleType, tmp_path: Path) -> None:
    rc = runner_mod.main(
        [
            "--config",
            str(_config(tmp_path / "tiers.toml")),
            "--output-dir",
            str(tmp_path / "out"),
            "--write-pass",
        ],
        env={},
    )

    assert rc == 2


def test_script_does_not_enable_repo_sponsorships() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "has_sponsorships=true" not in text
    assert "has_sponsorships = true" not in text
    assert ".github/FUNDING.yml" not in text
