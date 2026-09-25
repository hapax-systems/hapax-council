"""Contracts for retirement of the root-to-user OOM score bridge."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENFORCER = REPO_ROOT / "scripts" / "hapax-oom-score-enforce"
TRIGGER = REPO_ROOT / "scripts" / "hapax-oom-score-trigger"
SUDOERS = REPO_ROOT / "config" / "root-required" / "hapax-oom-score-enforce.sudoers"
PROTECTED_UNITS = (
    "pipewire.service",
    "pipewire-pulse.service",
    "wireplumber.service",
    "hapax-daimonion.service",
    "studio-compositor.service",
    "hapax-imagination.service",
)


def _run(
    script: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(script), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


@pytest.mark.parametrize(
    "args",
    [("--apply",), *(("--apply-unit", unit) for unit in PROTECTED_UNITS)],
)
def test_retired_enforcer_accepts_only_legacy_surface_without_mutation(
    args: tuple[str, ...],
) -> None:
    result = _run(ENFORCER, *args)

    assert result.returncode == 0, result.stderr
    assert "retired" in result.stdout
    assert "no process state was changed" in result.stdout


@pytest.mark.parametrize(
    "args",
    (
        (),
        ("--apply", "extra"),
        ("--apply-unit",),
        ("--apply-unit", "attacker.service"),
        ("--unknown",),
    ),
)
def test_retired_enforcer_rejects_every_other_request(args: tuple[str, ...]) -> None:
    result = _run(ENFORCER, *args)

    assert result.returncode == 2


@pytest.mark.parametrize("unit", PROTECTED_UNITS)
def test_retired_trigger_is_a_non_mutating_compatibility_sentinel(unit: str) -> None:
    result = _run(TRIGGER, unit)

    assert result.returncode == 0, result.stderr
    assert "retired" in result.stdout
    assert "no process state was changed" in result.stdout


def test_retired_trigger_rejects_nonallowlisted_unit() -> None:
    result = _run(TRIGGER, "attacker.service")

    assert result.returncode == 2
    assert "refusing non-retired" in result.stderr


@pytest.mark.parametrize(
    "script,args", ((ENFORCER, ("--apply",)), (TRIGGER, ("pipewire.service",)))
)
def test_retired_entrypoints_ignore_shell_startup_and_path_injection(
    tmp_path: Path, script: Path, args: tuple[str, ...]
) -> None:
    marker = tmp_path / "startup-ran"
    startup = tmp_path / "bash-env"
    startup.write_text(f"printf injected > {marker}\n", encoding="utf-8")
    hostile_bin = tmp_path / "bin"
    hostile_bin.mkdir()
    for name in ("sudo", "systemctl", "python3", "runuser"):
        stub = hostile_bin / name
        stub.write_text(f"#!/usr/bin/bash\nprintf called > {marker}\nexit 99\n", encoding="utf-8")
        stub.chmod(stat.S_IRWXU)
    env = {
        **os.environ,
        "PATH": str(hostile_bin),
        "BASH_ENV": str(startup),
        "ENV": str(startup),
        "CDPATH": str(tmp_path),
    }

    result = _run(script, *args, env=env)

    assert result.returncode == 0, result.stderr
    assert not marker.exists()


def test_retirement_sources_expose_no_negative_write_or_sudo_bridge() -> None:
    enforcer = ENFORCER.read_text(encoding="utf-8")
    trigger = TRIGGER.read_text(encoding="utf-8")
    sudoers = SUDOERS.read_text(encoding="utf-8")

    for script, body in ((ENFORCER, enforcer), (TRIGGER, trigger)):
        assert body.startswith("#!/usr/bin/bash -p\n")
        parsed = subprocess.run(
            ["/usr/bin/bash", "-n", str(script)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert parsed.returncode == 0, parsed.stderr
        for forbidden in (
            "/proc/",
            "oom_score_adj",
            "systemctl",
            "runuser",
            '"$SUDO"',
            "/usr/bin/sudo",
        ):
            assert forbidden not in body

    assert "HAPAX_OOM_SCORE_ENFORCE" not in sudoers
    assert "--apply-unit" not in sudoers
    assert "NOPASSWD:NOSETENV: HAPAX_ROOT_REQUIRED_AUDIT" in sudoers
