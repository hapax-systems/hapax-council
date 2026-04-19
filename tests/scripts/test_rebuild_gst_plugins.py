"""Tests for scripts/rebuild-gst-plugins.sh.

The script rebuilds Rust GStreamer plugins (cargo build --release),
installs the built ``.so`` to ``/usr/lib/gstreamer-1.0/`` via sudo, and
restarts affected services. We do not want tests to invoke real cargo,
real sudo, or real systemctl. Instead, we point the script at shim
binaries (via env vars the script exposes for this purpose) that record
their invocations into a log file we can assert against.

We cover four invariants:

- Source unchanged → no-op (no cargo, no install, no restart).
- Source newer than stamp → cargo build invoked.
- Built .so newer than installed .so → install invoked.
- Install succeeds → service restart invoked.
- Build failure → no install, no restart.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "rebuild-gst-plugins.sh"


@pytest.fixture
def harness(tmp_path: Path) -> dict[str, Path]:
    """Build a sandbox that mimics the real layout.

    Layout produced:

        tmp_path/
          repo/
            gst-plugin-glfeedback/
              src/lib.rs          (stub source file)
              target/release/     (created by the fake cargo shim)
          install_dir/
            libgstglfeedback.so   (created/touched as needed per test)
          state/                  (script state dir)
          bin/
            cargo                 (shim — writes target/release/... + logs call)
            sudo                  (shim — invokes rest of args, logs call)
            systemctl             (shim — logs call)
            curl                  (shim — logs call; no-op for ntfy)
          log.txt                 (shared shim log)
    """
    repo = tmp_path / "repo"
    plugin_dir = repo / "gst-plugin-glfeedback"
    src = plugin_dir / "src"
    src.mkdir(parents=True)
    (src / "lib.rs").write_text("// stub\n")

    install_dir = tmp_path / "install_dir"
    install_dir.mkdir()

    state_dir = tmp_path / "state"
    state_dir.mkdir()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "log.txt"

    # cargo shim: if args are "build --release", creates the built .so and
    # logs the call. Otherwise just logs.
    built_so = plugin_dir / "target" / "release" / "libgstglfeedback.so"
    cargo_shim = bin_dir / "cargo"
    cargo_shim.write_text(
        f"""#!/usr/bin/env bash
echo "cargo $*" >> {log_file}
if [[ "$1" == "build" && "$2" == "--release" ]]; then
    mkdir -p "{built_so.parent}"
    : > "{built_so}"
fi
exit 0
"""
    )

    # A cargo shim that always fails (swap in per-test).
    cargo_fail_shim = bin_dir / "cargo_fail"
    cargo_fail_shim.write_text(
        f"""#!/usr/bin/env bash
echo "cargo $*" >> {log_file}
exit 1
"""
    )

    # sudo shim: logs + executes the rest of args transparently.
    sudo_shim = bin_dir / "sudo"
    sudo_shim.write_text(
        f"""#!/usr/bin/env bash
echo "sudo $*" >> {log_file}
# Strip -n if present
if [[ "$1" == "-n" ]]; then shift; fi
"$@"
exit $?
"""
    )

    # systemctl shim: logs the call, succeeds.
    systemctl_shim = bin_dir / "systemctl"
    systemctl_shim.write_text(
        f"""#!/usr/bin/env bash
echo "systemctl $*" >> {log_file}
exit 0
"""
    )

    # curl shim for ntfy — log only, don't hit network.
    curl_shim = bin_dir / "curl"
    curl_shim.write_text(
        f"""#!/usr/bin/env bash
echo "curl $*" >> {log_file}
exit 0
"""
    )

    for shim in (cargo_shim, cargo_fail_shim, sudo_shim, systemctl_shim, curl_shim):
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    return {
        "repo": repo,
        "plugin_dir": plugin_dir,
        "src": src,
        "built_so": built_so,
        "install_dir": install_dir,
        "installed_so": install_dir / "libgstglfeedback.so",
        "state_dir": state_dir,
        "bin_dir": bin_dir,
        "log": log_file,
        "cargo": cargo_shim,
        "cargo_fail": cargo_fail_shim,
        "sudo": sudo_shim,
        "systemctl": systemctl_shim,
        "curl": curl_shim,
    }


def _run(harness: dict[str, Path], **overrides: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "HAPAX_GST_REPO": str(harness["repo"]),
            "HAPAX_GST_INSTALL_DIR": str(harness["install_dir"]),
            "HAPAX_GST_STATE_DIR": str(harness["state_dir"]),
            "HAPAX_GST_CARGO": str(harness["cargo"]),
            "HAPAX_GST_SUDO": str(harness["sudo"]),
            "HAPAX_GST_SYSTEMCTL": str(harness["systemctl"]),
            "HAPAX_GST_NTFY_CURL": str(harness["curl"]),
        }
    )
    env.update(overrides)
    return subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _log(harness: dict[str, Path]) -> str:
    if not harness["log"].exists():
        return ""
    return harness["log"].read_text()


# ---------- tests ----------


def test_noop_when_source_unchanged(harness: dict[str, Path]) -> None:
    """If a stamp already reflects current source mtime, no rebuild fires."""
    # Seed the stamp file with the current newest mtime in src/.
    stamp = harness["state_dir"] / "last-build-gst-plugin-glfeedback.ts"
    newest = max(int(p.stat().st_mtime) for p in harness["src"].rglob("*") if p.is_file())
    stamp.write_text(str(newest + 10))  # +10s safety

    # Pre-create an installed .so with a NEWER mtime than built so install
    # path would also be a no-op.
    harness["installed_so"].touch()

    result = _run(harness)
    assert result.returncode == 0, result.stdout + result.stderr

    log = _log(harness)
    assert "cargo" not in log, f"cargo should not run when source unchanged: {log}"
    assert "systemctl" not in log, f"systemctl should not run: {log}"


def test_build_invoked_when_source_newer_than_stamp(harness: dict[str, Path]) -> None:
    """Source newer than stamp → cargo build --release is invoked."""
    # No stamp file → script must build.
    # Do NOT pre-create installed_so so install also fires after build.

    result = _run(harness)
    assert result.returncode == 0, result.stdout + result.stderr

    log = _log(harness)
    assert "cargo build --release" in log, f"expected cargo build; got: {log}"
    assert harness["built_so"].exists(), "cargo shim should have created the .so"


def test_install_invoked_when_built_so_newer_than_installed(
    harness: dict[str, Path],
) -> None:
    """Built .so newer than installed .so → install via sudo is invoked."""
    # Pre-create an OLDER installed .so (mtime in the past).
    harness["installed_so"].touch()
    # Set install mtime to 1 day in the past.
    past = time.time() - 86400
    os.utime(harness["installed_so"], (past, past))

    result = _run(harness)
    assert result.returncode == 0, result.stdout + result.stderr

    log = _log(harness)
    assert "cargo build --release" in log
    assert "sudo" in log, f"sudo install should fire when built > installed: {log}"
    # The installed .so should now exist (shim executes the cp).
    assert harness["installed_so"].exists()


def test_restart_invoked_only_after_successful_install(
    harness: dict[str, Path],
) -> None:
    """systemctl --user restart fires only after a successful install."""
    # Pre-create OLDER installed .so so install path fires.
    harness["installed_so"].touch()
    past = time.time() - 86400
    os.utime(harness["installed_so"], (past, past))

    result = _run(harness)
    assert result.returncode == 0, result.stdout + result.stderr

    log = _log(harness)
    assert "systemctl --user restart studio-compositor.service" in log, (
        f"expected systemctl restart of studio-compositor.service: {log}"
    )
    # Ordering: sudo/install happens before systemctl.
    sudo_idx = log.find("sudo")
    systemctl_idx = log.find("systemctl --user restart")
    assert sudo_idx != -1 and systemctl_idx != -1
    assert sudo_idx < systemctl_idx, f"systemctl must run after sudo install; log ordering:\n{log}"


def test_build_failure_skips_install_and_restart(harness: dict[str, Path]) -> None:
    """When cargo build fails, install and restart must NOT fire."""
    # Swap cargo for the failing variant.
    # Pre-create OLDER installed .so so the only reason to skip install is build failure.
    harness["installed_so"].touch()
    past = time.time() - 86400
    os.utime(harness["installed_so"], (past, past))

    result = _run(harness, HAPAX_GST_CARGO=str(harness["cargo_fail"]))
    # Script returns 0 overall (per-plugin error is swallowed by || true in main).
    assert result.returncode == 0, result.stdout + result.stderr

    log = _log(harness)
    assert "cargo build --release" in log
    assert "sudo" not in log, f"install must NOT fire when build failed: {log}"
    assert "systemctl --user restart" not in log, f"restart must NOT fire when build failed: {log}"


def test_force_flag_rebuilds_even_when_stamp_is_current(harness: dict[str, Path]) -> None:
    """--force should always rebuild regardless of timestamps."""
    stamp = harness["state_dir"] / "last-build-gst-plugin-glfeedback.ts"
    newest = max(int(p.stat().st_mtime) for p in harness["src"].rglob("*") if p.is_file())
    stamp.write_text(str(newest + 10))

    env = os.environ.copy()
    env.update(
        {
            "HAPAX_GST_REPO": str(harness["repo"]),
            "HAPAX_GST_INSTALL_DIR": str(harness["install_dir"]),
            "HAPAX_GST_STATE_DIR": str(harness["state_dir"]),
            "HAPAX_GST_CARGO": str(harness["cargo"]),
            "HAPAX_GST_SUDO": str(harness["sudo"]),
            "HAPAX_GST_SYSTEMCTL": str(harness["systemctl"]),
            "HAPAX_GST_NTFY_CURL": str(harness["curl"]),
            "HAPAX_GST_SKIP_RESTART": "1",
        }
    )
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), "--force"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    log = _log(harness)
    assert "cargo build --release" in log
    # SKIP_RESTART honoured.
    assert "systemctl" not in log, f"HAPAX_GST_SKIP_RESTART=1 must suppress restart: {log}"


def test_missing_plugin_dir_is_soft_skip(tmp_path: Path, harness: dict[str, Path]) -> None:
    """If the plugin source directory is missing, the script must not crash."""
    # Remove the plugin dir entirely.
    shutil.rmtree(harness["plugin_dir"])

    result = _run(harness)
    assert result.returncode == 0, result.stdout + result.stderr
    log = _log(harness)
    assert "cargo" not in log
    assert "sudo" not in log
