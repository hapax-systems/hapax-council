"""Python ABI splits preserve audio, older caps, and compatible root wheels.

Recheck the real root graph without syncing the working environment::

    uv run --no-project --with pytest --with packaging python -m pytest \
        --noconftest -o addopts= tests/test_dependency_resolution_markers.py -q

The locked plans use private copies of the manifests and lock. uv may provision
the requested Python interpreter, but --dry-run never installs the audio stack.
They run in the ordinary suite too; an unavailable interpreter/resolver is a
failure, not a skipped compatibility claim. To mutation-check an edge, delete
or misroute its Essentia entry in the root audio or host lock section, run the
matching locked-install-plan case, then restore the exact lock and rerun it.
Keep the standalone Essentia package records intact: those alone cannot prove
that an extra actually installs the package.
"""

import os
import re
import shutil
import subprocess
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
        _, _, _, tags = parse_wheel_filename(filename)
        if any(
            tag.interpreter == abi
            and tag.abi == abi
            and tag.platform.startswith("manylinux")
            and tag.platform.endswith("_x86_64")
            for tag in tags
        ):
            matching_wheels.append(wheel)
    assert matching_wheels, f"{package_name} must actually be installable for Linux {abi}"


def test_python_and_platform_support_are_preserved():
    project = _project()
    assert project["project"]["requires-python"] == ">=3.12"
    assert project["tool"]["uv"]["environments"] == ["sys_platform == 'linux'"]


@pytest.mark.integration
@pytest.mark.parametrize("extra", ["audio", "host"])
@pytest.mark.parametrize("python_version", ["3.12", "3.13", "3.14"])
def test_locked_install_plan_reaches_root_audio_edges(tmp_path, python_version, extra):
    """Exercise uv's actual extra expansion, edge selection, and wheel planning."""
    project = tmp_path / "project"
    project.mkdir()
    for name in ["pyproject.toml", "uv.lock"]:
        shutil.copy2(ROOT / name, project / name)
    # These editable path dependencies need their real metadata for --locked's
    # freshness check; no package code/build or working-tree venv is needed.
    for source in _project()["tool"]["uv"]["sources"].values():
        if "path" in source:
            relative = Path(source["path"]) / "pyproject.toml"
            (project / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, project / relative)

    lock = project / "uv.lock"
    original_lock = lock.read_bytes()
    environment = tmp_path / "planned-env"
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("UV_") and key != "VIRTUAL_ENV"
    }
    env.update(UV_PROJECT_ENVIRONMENT=str(environment), TMPDIR=str(tmp_path), NO_COLOR="1")
    command = [
        "uv",
        "sync",
        "--locked",
        "--dry-run",
        "--no-default-groups",
        "--python",
        python_version,
        "--extra",
        extra,
        "--project",
        str(project),
    ]
    result = subprocess.run(
        command, cwd=project, env=env, capture_output=True, text=True, timeout=180
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"{' '.join(command)}\n{output}"
    assert lock.read_bytes() == original_lock, "The plan must use the submitted lock unchanged"
    assert not environment.exists(), "Compatibility checks must not install an audio environment"
    expected = {
        "essentia": "2.1b6.dev1438" if python_version == "3.14" else "2.1b6.dev1389",
        "spacy": "3.8.16" if python_version == "3.14" else "3.8.14",
    }
    for name, version in expected.items():
        selected = re.findall(rf"^\s*\+ {name}==([^\s]+)", output, re.MULTILINE)
        assert selected == [version], (
            f"Python {python_version} root [{extra}] must install {name}=={version}, "
            f"got {selected}; a lock package record without a reachable edge is insufficient.\n"
            f"{output}"
        )
