"""Smoke tests for ``scripts/audit-notification-loopback-trace.sh``.

Exercises the early-exit branches that don't require live PipeWire / a
spawned playback node — the full dynamic trace can only be verified by
the operator with a running PipeWire graph and is covered by manual
runs (this is an audit-closeout deliverable, not a CI fitness gate).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "audit-notification-loopback-trace.sh"


def test_script_exists_and_is_executable() -> None:
    assert SCRIPT.exists(), f"missing: {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), f"not executable: {SCRIPT}"


def test_script_passes_bash_syntax_check() -> None:
    proc = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"bash -n failed:\n{proc.stderr}"


def test_unknown_arg_returns_usage_error() -> None:
    proc = subprocess.run(
        [str(SCRIPT), "--bogus"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "usage" in proc.stderr.lower()


def test_skips_when_pw_dump_missing(tmp_path: Path) -> None:
    """Sandbox PATH so pw-dump is absent → script exits 0 with a warning."""

    # Build a PATH that contains only what's needed (jq, python3, basic
    # coreutils) and omits pw-dump entirely.
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()

    for tool in ("jq", "python3", "bash", "head", "rm", "sleep", "kill", "mktemp"):
        real = shutil.which(tool)
        if real is None:
            pytest.skip(f"required host tool {tool} unavailable")
        (shim_dir / tool).symlink_to(real)

    proc = subprocess.run(
        [str(SCRIPT)],
        capture_output=True,
        text=True,
        env={"PATH": str(shim_dir)},
        check=False,
    )

    assert proc.returncode == 0, f"expected clean skip; got {proc.returncode}: {proc.stderr}"
    assert "pw-dump not present" in proc.stderr or "skipping" in proc.stderr.lower()


def test_skips_on_empty_pipewire_graph(tmp_path: Path) -> None:
    """pw-dump returning [] must result in an exit-0 skip, not a crash."""

    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    for tool in ("jq", "python3", "bash", "head", "rm", "sleep", "kill", "mktemp"):
        real = shutil.which(tool)
        if real is None:
            pytest.skip(f"required host tool {tool} unavailable")
        (shim_dir / tool).symlink_to(real)

    fake_pw_dump = shim_dir / "pw-dump"
    fake_pw_dump.write_text("#!/usr/bin/env bash\nprintf '[]'\n")
    fake_pw_dump.chmod(0o755)

    proc = subprocess.run(
        [str(SCRIPT)],
        capture_output=True,
        text=True,
        env={"PATH": str(shim_dir)},
        check=False,
    )

    assert proc.returncode == 0
    assert "empty PipeWire graph" in proc.stderr or "skipping" in proc.stderr.lower()


def test_skips_when_broadcast_sink_absent(tmp_path: Path) -> None:
    """Graph without hapax-livestream node → exit 0 (no leak possible)."""

    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    for tool in ("jq", "python3", "bash", "head", "rm", "sleep", "kill", "mktemp"):
        real = shutil.which(tool)
        if real is None:
            pytest.skip(f"required host tool {tool} unavailable")
        (shim_dir / tool).symlink_to(real)

    fake_pw_dump = shim_dir / "pw-dump"
    fake_pw_dump.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'[{"type":"PipeWire:Interface:Node","id":1,"info":{"props":{"node.name":"some-other-sink"}}}]\'\n'
    )
    fake_pw_dump.chmod(0o755)

    proc = subprocess.run(
        [str(SCRIPT)],
        capture_output=True,
        text=True,
        env={"PATH": str(shim_dir)},
        check=False,
    )

    assert proc.returncode == 0
    assert "hapax-livestream not present" in proc.stderr or "skipping" in proc.stderr.lower()
