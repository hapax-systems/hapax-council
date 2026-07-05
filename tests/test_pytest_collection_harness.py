"""Regression pins for repo-root pytest package collection."""

from __future__ import annotations

import importlib
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SRC_ROOTS = {
    ".",
    "packages/agentgov/src",
    "packages/hapax-axioms/src",
    "packages/hapax-refusals/src",
    "packages/hapax-swarm/src",
    "packages/hapax-velocity-meter/src",
}


def _pytest_options() -> dict[str, object]:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"][
        "pytest"
    ]["ini_options"]


def test_root_pytest_uses_importlib_for_package_test_basenames() -> None:
    options = _pytest_options()

    assert "--import-mode=importlib" in str(options["addopts"])
    assert set(options["pythonpath"]) == PACKAGE_SRC_ROOTS


def test_duplicate_package_test_basenames_collect_from_repo_root() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--collect-only",
            "packages/agentgov/tests/test_consent_label.py",
            "packages/agentgov/tests/test_veto_chain_laws.py",
            "packages/hapax-axioms/tests/test_cli.py",
            "packages/hapax-velocity-meter/tests/test_cli.py",
            "packages/hapax-refusals/tests/test_claim.py",
            "packages/hapax-swarm/tests/test_claim.py",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "packages/agentgov/tests/test_consent_label.py::" in result.stdout
    assert "packages/agentgov/tests/test_veto_chain_laws.py::" in result.stdout
    assert "packages/hapax-axioms/tests/test_cli.py::test_list_axioms" in result.stdout
    assert "packages/hapax-velocity-meter/tests/test_cli.py::test_list_axioms" in result.stdout
    assert "packages/hapax-refusals/tests/test_claim.py::TestClaimSpec::" in result.stdout
    assert "packages/hapax-swarm/tests/test_claim.py::TestClaimSpec::" in result.stdout


def test_package_src_roots_import_under_root_pytest() -> None:
    for module_name in (
        "agentgov",
        "hapax_axioms",
        "hapax_refusals",
        "hapax_swarm",
        "hapax_velocity_meter",
    ):
        assert importlib.import_module(module_name)


def test_agentgov_strategy_shim_reexports_package_strategies() -> None:
    root_strategies = importlib.import_module("tests.strategies")
    package_strategies = importlib.import_module("packages.agentgov.tests.strategies")

    assert Path(root_strategies.__file__).resolve() == REPO_ROOT / "tests" / "strategies.py"
    for name in root_strategies.__all__:
        assert getattr(root_strategies, name) is getattr(package_strategies, name)


def test_configured_pythonpath_resolves_package_test_strategies() -> None:
    configured_paths = [
        str((REPO_ROOT / str(path)).resolve()) for path in _pytest_options()["pythonpath"]
    ]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib.util, pathlib, sys; "
                f"sys.path[:] = {configured_paths!r}; "
                "spec = importlib.util.find_spec('packages.agentgov.tests.strategies'); "
                "assert spec is not None and spec.origin; "
                "print(pathlib.Path(spec.origin).as_posix())"
            ),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith("packages/agentgov/tests/strategies.py")
