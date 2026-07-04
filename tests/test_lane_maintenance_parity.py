"""Parity guard for the KIND-5 dissolution (MOVE 4).

The topology-derived local-dev-respawn suppression is authored ONCE in Python
(shared.host_confinement.should_suppress_local_dev_respawn) and MIRRORED in bash
in the two lane scripts (they run in a hot loop and cannot import Python per call).

The atlas's Q0a: a layering-forced value-mirror is NOT a boutique surface *iff* a
drift-pin/parity test guards it. This is that guard — it extracts each script's
local_dev_maintenance_mode() and asserts its derivation agrees with the Python
canonical across the topology matrix. If either mirror drifts, this goes RED.
"""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path

import pytest

hc = importlib.import_module("shared.host_confinement")

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = [
    REPO_ROOT / "scripts" / "hapax-lane-supervisor",
    REPO_ROOT / "scripts" / "hapax-lane-idle-watchdog",
]

# (current_host, dispatch_host_env) — the derivation path (override unset).
DERIVATION_CASES = [
    ("hapax-podium", ""),  # podium; default target appendix -> suppress
    ("hapax-appendix", ""),  # appendix IS the default target -> provision
    ("podium", "appendix"),  # explicit target appendix -> suppress
    ("appendix", "appendix"),  # on the target -> provision
    ("hapax-appendix", "podium"),  # target moved to podium -> appendix suppresses
    ("hapax-podium", "podium"),  # target podium, on podium -> provision
    ("weird-host", "appendix"),  # a non-target host -> suppress (fail-closed spirit)
]


def _extract_func(script: Path) -> str:
    out = subprocess.run(
        ["sed", "-n", "/^local_dev_maintenance_mode()/,/^}/p", str(script)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "local_dev_maintenance_mode()" in out, f"could not extract func from {script}"
    return out


def _run_bash(func_src: str, env_overrides: dict[str, str]) -> str:
    env = {"PATH": "/usr/bin:/bin"}  # clean env — do NOT inherit the pytest process's HAPAX_*
    env.update(env_overrides)
    proc = subprocess.run(
        ["bash", "-c", f"{func_src}\nlocal_dev_maintenance_mode"],
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.stdout.strip()


def _py_expected(current: str, dispatch: str) -> str:
    target = dispatch or "appendix"  # bash's default target when unset
    block, _ = hc.should_suppress_local_dev_respawn(current, target)
    return "appendix-only" if block else "local"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda s: s.name)
@pytest.mark.parametrize("current,dispatch", DERIVATION_CASES)
def test_bash_derivation_matches_python(script: Path, current: str, dispatch: str) -> None:
    func = _extract_func(script)
    env = {"HAPAX_CURRENT_HOST": current}
    if dispatch:
        env["HAPAX_DISPATCH_HOST"] = dispatch
    bash_out = _run_bash(func, env)
    assert bash_out == _py_expected(current, dispatch), (
        f"{script.name}: current={current!r} dispatch={dispatch!r} "
        f"bash={bash_out!r} != python={_py_expected(current, dispatch)!r}"
    )


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda s: s.name)
def test_explicit_override_still_honored(script: Path) -> None:
    """The static override is preserved (backward-compat) until it becomes a
    governed claim — an explicit override wins over the topology derivation."""
    func = _extract_func(script)
    # override forces suppress even though the topology (on-target) would provision.
    forced = _run_bash(
        func,
        {
            "HAPAX_CURRENT_HOST": "appendix",
            "HAPAX_DISPATCH_HOST": "appendix",
            "HAPAX_LOCAL_DEV_MAINTENANCE_MODE": "appendix-only",
        },
    )
    assert forced == "appendix-only"
    # override forces provision even on a non-target host.
    freed = _run_bash(
        func,
        {"HAPAX_CURRENT_HOST": "podium", "HAPAX_LOCAL_DEV_MAINTENANCE_MODE": "local"},
    )
    assert freed == "local"
