"""Tests for the guarded WirePlumber link deny policy installer."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-wireplumber-link-deny-policy"


def _run(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "python", str(SCRIPT), *args],
        cwd=REPO_ROOT,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_check_source_confirms_generated_artifacts() -> None:
    result = _run(["--check-source"])

    assert result.returncode == 0, result.stdout + result.stderr


def test_install_dry_run_does_not_require_runtime_authorization(tmp_path: Path) -> None:
    result = _run(
        [
            "--install",
            "--dry-run",
            "--installed-wireplumber-dir",
            str(tmp_path / "wireplumber"),
        ]
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "DRY RUN:" in result.stdout
    assert not (tmp_path / "wireplumber").exists()


def test_live_install_requires_explicit_runtime_authorization(tmp_path: Path) -> None:
    result = _run(
        [
            "--install",
            "--installed-wireplumber-dir",
            str(tmp_path / "wireplumber"),
        ],
        env={"HAPAX_AUDIO_WIREPLUMBER_DENY_RUNTIME_AUTHORIZED": "0"},
    )

    assert result.returncode != 0
    assert "refusing live WirePlumber writes" in result.stderr


def test_authorized_install_to_temp_dir_then_check_installed(tmp_path: Path) -> None:
    installed_dir = tmp_path / "wireplumber"
    installed_data_dir = tmp_path / "wireplumber-data"
    result = _run(
        [
            "--install",
            "--installed-wireplumber-dir",
            str(installed_dir),
            "--installed-wireplumber-data-dir",
            str(installed_data_dir),
        ],
        env={"HAPAX_AUDIO_WIREPLUMBER_DENY_RUNTIME_AUTHORIZED": "1"},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (installed_dir / "wireplumber.conf.d" / "98-hapax-link-deny.conf").exists()
    assert (installed_data_dir / "scripts" / "hapax" / "link-deny.lua").exists()
    assert not (installed_dir / "scripts" / "hapax" / "link-deny.lua").exists()

    check = _run(
        [
            "--check-installed",
            "--installed-wireplumber-dir",
            str(installed_dir),
            "--installed-wireplumber-data-dir",
            str(installed_data_dir),
        ]
    )

    assert check.returncode == 0, check.stdout + check.stderr


def test_authorized_install_removes_legacy_config_script(tmp_path: Path) -> None:
    installed_dir = tmp_path / "wireplumber"
    installed_data_dir = tmp_path / "wireplumber-data"
    legacy_script = installed_dir / "scripts" / "hapax" / "link-deny.lua"
    legacy_script.parent.mkdir(parents=True)
    legacy_script.write_text("-- stale legacy script\n", encoding="utf-8")

    result = _run(
        [
            "--install",
            "--installed-wireplumber-dir",
            str(installed_dir),
            "--installed-wireplumber-data-dir",
            str(installed_data_dir),
        ],
        env={"HAPAX_AUDIO_WIREPLUMBER_DENY_RUNTIME_AUTHORIZED": "1"},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not legacy_script.exists()


def test_authorized_install_does_not_remove_script_when_config_and_data_dirs_overlap(
    tmp_path: Path,
) -> None:
    installed_dir = tmp_path / "wireplumber"

    result = _run(
        [
            "--install",
            "--installed-wireplumber-dir",
            str(installed_dir),
            "--installed-wireplumber-data-dir",
            str(installed_dir),
        ],
        env={"HAPAX_AUDIO_WIREPLUMBER_DENY_RUNTIME_AUTHORIZED": "1"},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (installed_dir / "scripts" / "hapax" / "link-deny.lua").exists()

    check = _run(
        [
            "--check-installed",
            "--installed-wireplumber-dir",
            str(installed_dir),
            "--installed-wireplumber-data-dir",
            str(installed_dir),
        ]
    )

    assert check.returncode == 0, check.stdout + check.stderr
