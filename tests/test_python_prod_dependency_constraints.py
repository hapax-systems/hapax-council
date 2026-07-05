"""Regression guards for the python-prod dependency bump safety caps."""

import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_SPECS = {
    ("project.dependencies", "pydantic-ai"): ">=1.99.0,<2",
    ("project.dependencies", "python-json-logger"): ">=3.3.0,<4",
    ("project.dependencies", "torchvision"): ">=0.25,<0.26",
    ("project.dependencies", "opencv-python-headless"): ">=4.13.0.92,<5",
    ("project.optional-dependencies.audio", "opencv-python-headless"): ">=4.10.0,<5",
    ("project.optional-dependencies.audio", "torchcodec"): "==0.10.*",
    ("project.optional-dependencies.audio", "essentia"): ">=2.1b6.dev1091,<=2.1b6.dev1389",
    ("project.optional-dependencies.logos-api", "langfuse"): ">=3.14.5,<4",
    ("project.optional-dependencies.logos-api", "sse-starlette"): ">=2.0.0,<3",
    ("project.optional-dependencies.sync-pipeline", "langfuse"): ">=3.14.5,<4",
    ("project.optional-dependencies.ci", "pyrefly"): ">=0.62,<1",
    ("project.optional-dependencies.tui", "textual"): ">=3.0,<4",
}

LOCKED_VERSIONS = {
    "pydantic-ai": "1.107.0",
    "python-json-logger": "3.3.0",
    "torchvision": "0.25.0",
    "torchcodec": "0.10.0",
    "essentia": "2.1b6.dev1389",
    "langfuse": "3.15.0",
    "sse-starlette": "2.4.1",
    "opencv-python-headless": "4.13.0.92",
    "pyrefly": "0.64.1",
    "textual": "3.7.1",
}


def _load_pyproject() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _load_lock_packages() -> dict[str, dict]:
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    return {package["name"]: package for package in lock["package"]}


def _dependency_group(pyproject: dict, group_path: str) -> list[str]:
    section, name = group_path.rsplit(".", maxsplit=1)
    if section == "project":
        return pyproject["project"][name]
    if section == "project.optional-dependencies":
        return pyproject["project"]["optional-dependencies"][name]
    raise AssertionError(f"unknown dependency group path: {group_path}")


def test_review_blocked_python_prod_specs_keep_abi_and_major_caps() -> None:
    pyproject = _load_pyproject()

    for (group_path, package_name), expected_specifier in REQUIRED_SPECS.items():
        requirements = {
            Requirement(requirement).name.lower(): Requirement(requirement)
            for requirement in _dependency_group(pyproject, group_path)
        }

        assert package_name in requirements
        assert requirements[package_name].specifier == SpecifierSet(expected_specifier)


def test_review_blocked_python_prod_lock_resolves_to_safe_versions() -> None:
    packages = _load_lock_packages()

    for package_name, expected_version in LOCKED_VERSIONS.items():
        assert packages[package_name]["version"] == expected_version


def test_essentia_lock_keeps_python_312_and_313_wheels_available() -> None:
    packages = _load_lock_packages()
    wheels = packages["essentia"]["wheels"]
    wheel_urls = {wheel["url"] for wheel in wheels}

    assert any("cp312-cp312" in url for url in wheel_urls)
    assert any("cp313-cp313" in url for url in wheel_urls)
    assert not all("cp314" in url for url in wheel_urls)
