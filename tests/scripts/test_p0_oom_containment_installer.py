from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "scripts" / "install-p0-oom-containment"
MANIFEST = REPO_ROOT / "config" / "root-required" / "oom-containment.files"
PROFILE_TABLE = Path("config/root-required/oom-host-profiles.tsv")


def run_installer(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    clean_env = os.environ.copy()
    for selector in (
        "HAPAX_ROOT_REQUIRED_INSTALLER_TEST_MODE",
        "HAPAX_OOM_INSTALL_SUDO",
        "HAPAX_RUNTIME_AUTHORITY_TASK",
        "HAPAX_ROOT_REQUIRED_SEALED_SOURCE_FDS",
        "HAPAX_ROOT_REQUIRED_FINALIZE_GATE",
    ):
        clean_env.pop(selector, None)
    if env:
        clean_env.update(env)
    return subprocess.run(
        [str(INSTALLER), *args],
        check=False,
        capture_output=True,
        text=True,
        env=clean_env,
        timeout=15,
    )


def staged_source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    entries = [
        line
        for line in MANIFEST.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    for entry in entries:
        source_path = REPO_ROOT / entry
        destination = source / entry
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
    return source


def rewrite(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_source_validator_is_executable() -> None:
    assert INSTALLER.stat().st_mode & 0o111


def test_shipped_source_package_validates_without_live_claim() -> None:
    result = run_installer("--check", "--no-runtime")

    assert result.returncode == 0, result.stderr
    assert "source validation complete" in result.stdout
    assert "non-authoritative, no live state" in result.stdout


def test_default_mode_is_source_check() -> None:
    result = run_installer()

    assert result.returncode == 0, result.stderr
    assert "source validation complete" in result.stdout


@pytest.mark.parametrize(
    "mode",
    ("--install", "--verify-live", "--authenticated-sealed-source"),
)
def test_production_modes_refuse_before_source_or_tool_lookup(mode: str, tmp_path: Path) -> None:
    marker = tmp_path / "tool-ran"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ("dirname", "pwd", "python3", "getent", "flock", "systemctl", "docker"):
        fake = fake_bin / name
        fake.write_text(
            f"#!/usr/bin/bash\nprintf ran > {marker!s}\nexit 99\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)

    result = run_installer(
        mode,
        "--source",
        str(tmp_path / "absent-source"),
        "--unknown-after-production-mode",
        env={
            "PATH": str(fake_bin),
            "BASH_ENV": str(fake_bin / "python3"),
            "HAPAX_ROOT_REQUIRED_INSTALLER_TEST_MODE": "1",
            "HAPAX_OOM_INSTALL_SUDO": str(fake_bin / "systemctl"),
        },
    )

    assert result.returncode == 77
    assert result.stdout == ""
    assert "no source, account, lock, tool, or live-state lookup was attempted" in result.stderr
    assert not marker.exists()


def test_production_refusal_precedes_every_external_lookup_in_source() -> None:
    body = INSTALLER.read_text(encoding="utf-8")
    refusal = body.index('if [ "$_production_requested" -eq 1 ]')
    refusal_exit = body.index("exit 77", refusal)
    first_external = min(body.index("/usr/bin/dirname"), body.index("/usr/bin/python3"))
    selector_lookup = body.index("HAPAX_ROOT_REQUIRED_INSTALLER_TEST_MODE", refusal_exit)

    assert refusal < refusal_exit < first_external
    assert refusal_exit < selector_lookup


def test_production_token_cannot_be_hidden_as_source_value() -> None:
    result = run_installer("--source", "--install")

    assert result.returncode == 77
    assert "no source, account, lock, tool, or live-state lookup was attempted" in result.stderr


def test_retired_test_selector_cannot_reopen_source_check() -> None:
    result = run_installer("--check", env={"HAPAX_ROOT_REQUIRED_INSTALLER_TEST_MODE": "1"})

    assert result.returncode == 2
    assert "is retired for this source-only validator" in result.stderr


def test_missing_source_argument_is_actionable() -> None:
    result = run_installer("--source")

    assert result.returncode == 2
    assert "source directory is required" in result.stderr


def test_unknown_argument_refuses() -> None:
    result = run_installer("--definitely-unknown")

    assert result.returncode == 2
    assert "unknown argument" in result.stderr


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    (
        ("hapax-appendix\t59\t61", "hapax-appendix\t62\t61", "invalid inclusive MemTotal interval"),
        (
            "appendix\t46G\t54G",
            "appendix\t58G\t59G",
            "app ceilings must be ordered below interval floor",
        ),
        ("48G\t56G\t16384", "58G\t59G\t16384", "UID ceilings must be ordered below interval floor"),
        ("56G\t16384", "56G\t4096", "zram must be 8192 MiB or larger"),
        ("56G\t16384", "56G\t30720", "zram must be 8192 MiB or larger"),
    ),
)
def test_profile_table_rejects_unsafe_bounds(
    tmp_path: Path, old: str, new: str, expected: str
) -> None:
    source = staged_source(tmp_path)
    rewrite(source / PROFILE_TABLE, old, new)

    result = run_installer("--source", str(source), "--check")

    assert result.returncode == 1
    assert expected in result.stderr


def test_profile_table_requires_exact_host_set(tmp_path: Path) -> None:
    source = staged_source(tmp_path)
    rewrite(source / PROFILE_TABLE, "hapax-podium", "other-host")

    result = run_installer("--source", str(source), "--check")

    assert result.returncode == 1
    assert "host profile set must be exactly" in result.stderr


def test_profile_config_must_match_table(tmp_path: Path) -> None:
    source = staged_source(tmp_path)
    config = source / "config/root-required/oom-host-policy/appendix/app.slice.conf"
    rewrite(config, "MemoryMax=54G", "MemoryMax=53G")

    result = run_installer("--source", str(source), "--check")

    assert result.returncode == 1
    assert "expected Slice.MemoryMax=54G" in result.stderr


@pytest.mark.parametrize(
    ("relative", "old", "new", "expected"),
    (
        (
            "appendix/app.slice.conf",
            "MemorySwapMax=8G",
            "MemorySwapMax=infinity",
            "expected Slice.MemorySwapMax=8G",
        ),
        (
            "appendix/user@1000.service.conf",
            "OOMPolicy=continue",
            "OOMPolicy=stop",
            "expected Service.OOMPolicy=continue",
        ),
        (
            "podium/zram-generator.conf",
            "compression-algorithm = zstd",
            "compression-algorithm = lz4",
            "expected zram0.compression-algorithm=zstd",
        ),
        (
            "podium/app.slice.conf",
            "MemoryMin=8G",
            "MemoryMin=8G\nManagedOOMMemoryPressure=kill",
            "expected exactly Slice options",
        ),
    ),
)
def test_profile_config_rejects_noncanonical_or_extra_policy(
    tmp_path: Path, relative: str, old: str, new: str, expected: str
) -> None:
    source = staged_source(tmp_path)
    config = source / "config/root-required/oom-host-policy" / relative
    rewrite(config, old, new)

    result = run_installer("--source", str(source), "--check")

    assert result.returncode == 1
    assert expected in result.stderr


def test_profile_tree_rejects_unmanifested_extra_file(tmp_path: Path) -> None:
    source = staged_source(tmp_path)
    extra = source / "config/root-required/oom-host-policy/appendix/override.conf"
    extra.write_text("[Slice]\nMemoryMax=1G\n", encoding="utf-8")

    result = run_installer("--source", str(source), "--check")

    assert result.returncode == 1
    assert "policy tree must contain exactly" in result.stderr


def test_manifest_must_own_every_profile_file(tmp_path: Path) -> None:
    source = staged_source(tmp_path)
    manifest = source / "config/root-required/oom-containment.files"
    rewrite(
        manifest,
        "config/root-required/oom-host-policy/podium/zram-generator.conf\n",
        "",
    )

    result = run_installer("--source", str(source), "--check")

    assert result.returncode == 1
    assert "omits host policy files" in result.stderr


@pytest.mark.parametrize(
    "entry",
    (
        "/etc/passwd",
        "../escape",
        "scripts/../README.md",
        "scripts//README.md",
        "./README.md",
        "space in/path",
        "backslash\\path",
        ".",
    ),
)
def test_manifest_rejects_unsafe_or_non_normalized_paths(tmp_path: Path, entry: str) -> None:
    source = staged_source(tmp_path)
    manifest = source / "config/root-required/oom-containment.files"
    manifest.write_text(
        manifest.read_text(encoding="utf-8") + f"{entry}\n",
        encoding="utf-8",
    )

    result = run_installer("--source", str(source), "--check")

    assert result.returncode == 1
    assert "unsafe or non-normalized manifest entry" in result.stderr


def test_manifest_entry_cannot_be_a_symlink(tmp_path: Path) -> None:
    source = staged_source(tmp_path)
    profile = source / PROFILE_TABLE
    replacement = profile.with_suffix(".real")
    profile.rename(replacement)
    profile.symlink_to(replacement.name)

    result = run_installer("--source", str(source), "--check")

    assert result.returncode == 1
    assert "non-symlink regular file" in result.stderr
