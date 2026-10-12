"""Python ABI splits preserve audio, older caps, and compatible root wheels."""

import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from packaging.markers import Marker, default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import parse_wheel_filename
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
OLD_SPEC = SpecifierSet(">=2.1b6.dev1091,<=2.1b6.dev1389")
NEW_SPEC = SpecifierSet("==2.1b6.dev1438")


def _environment(python_version):
    return {
        **default_environment(),
        "python_version": python_version,
        "python_full_version": f"{python_version}.0",
        "sys_platform": "linux",
        "platform_machine": "x86_64",
        "extra": "audio",
    }


def _project():
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def _essentia_requirements(python_version):
    requirements = [
        Requirement(item) for item in _project()["project"]["optional-dependencies"]["audio"]
    ]
    return [
        item
        for item in requirements
        if item.name == "essentia"
        and (item.marker is None or item.marker.evaluate(_environment(python_version)))
    ]


@pytest.mark.parametrize("python_version", ["3.12", "3.13", "3.14"])
def test_one_audio_requirement_preserves_each_supported_python_split(python_version):
    selected = _essentia_requirements(python_version)
    assert len(selected) == 1, "Essentia markers must neither overlap nor drop supported audio"
    expected = NEW_SPEC if python_version == "3.14" else OLD_SPEC
    assert selected[0].specifier == expected, "Preserve the older ceiling and narrow cp314 choice"


@pytest.mark.parametrize("python_version", ["3.12", "3.13", "3.14"])
def test_spacy_compatibility_constraint_only_applies_to_python314(python_version):
    requirements = [
        Requirement(item) for item in _project()["tool"]["uv"]["constraint-dependencies"]
    ]
    selected = [
        item
        for item in requirements
        if item.name == "spacy"
        and (item.marker is None or item.marker.evaluate(_environment(python_version)))
    ]
    if python_version == "3.14":
        assert len(selected) == 1
        assert selected[0].specifier == SpecifierSet(">=3.8.16")
    else:
        assert not selected, "Do not raise older Python's transitive spaCy floor"


@pytest.mark.parametrize("package_name", ["essentia", "spacy"])
@pytest.mark.parametrize("python_version", ["3.12", "3.13", "3.14"])
def test_selected_lock_has_a_linux_wheel_for_the_requested_python_abi(python_version, package_name):
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    environment = _environment(python_version)
    packages = [
        item
        for item in lock["package"]
        if item["name"] == package_name
        and (
            not item.get("resolution-markers")
            or any(Marker(marker).evaluate(environment) for marker in item["resolution-markers"])
        )
    ]
    assert len(packages) == 1, f"The lock must select exactly one compatible {package_name}"
    package = packages[0]
    if package_name == "essentia":
        selected = _essentia_requirements(python_version)
        assert len(selected) == 1
        assert Version(package["version"]) in selected[0].specifier
    elif python_version == "3.14":
        assert Version(package["version"]) in SpecifierSet(">=3.8.16")
    abi = "cp" + python_version.replace(".", "")
    matching_wheels = []
    for wheel in package.get("wheels", []):
        filename = unquote(Path(urlsplit(wheel["url"]).path).name)
        _, version, _, tags = parse_wheel_filename(filename)
        if any(
            tag.interpreter == abi
            and tag.abi == abi
            and tag.platform.startswith("manylinux")
            and tag.platform.endswith("_x86_64")
            for tag in tags
        ):
            assert version == Version(package["version"])
            matching_wheels.append(wheel)
    assert matching_wheels, f"{package_name} must actually be installable for Linux {abi}"


def test_python_and_platform_support_are_preserved():
    project = _project()
    assert project["project"]["requires-python"] == ">=3.12"
    assert project["tool"]["uv"]["environments"] == ["sys_platform == 'linux'"]
