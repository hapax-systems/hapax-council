"""Regression guards for the python-prod dependency bump safety caps."""

import re
import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parents[1]
NEXT_ACTION = (
    "Restore the python-prod review caps in pyproject.toml, regenerate uv.lock, "
    "then rerun uv lock --check and this test before review dispatch."
)

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


def _load_pyproject() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _load_lock_package_entries() -> dict[str, list[dict]]:
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    entries: dict[str, list[dict]] = {}
    for package in lock["package"]:
        entries.setdefault(package["name"], []).append(package)
    return entries


def _dependency_group(pyproject: dict, group_path: str) -> list[str]:
    section, name = group_path.rsplit(".", maxsplit=1)
    if section == "project":
        return pyproject["project"][name]
    if section == "project.optional-dependencies":
        return pyproject["project"]["optional-dependencies"][name]
    raise AssertionError(f"unknown dependency group path: {group_path}")


def _requirements_by_name(requirements: list[str]) -> dict[str, Requirement]:
    return {
        Requirement(requirement).name.lower(): Requirement(requirement)
        for requirement in requirements
    }


def test_review_blocked_python_prod_specs_keep_abi_and_major_caps() -> None:
    pyproject = _load_pyproject()

    for (group_path, package_name), expected_specifier in REQUIRED_SPECS.items():
        requirements = _requirements_by_name(_dependency_group(pyproject, group_path))

        assert package_name in requirements, (
            f"{package_name} missing from {group_path}. {NEXT_ACTION}"
        )
        assert requirements[package_name].specifier == SpecifierSet(expected_specifier), (
            f"{package_name} in {group_path} must keep specifier {expected_specifier}. "
            f"{NEXT_ACTION}"
        )


def test_review_blocked_python_prod_lock_resolves_inside_safe_specs() -> None:
    pyproject = _load_pyproject()
    packages_by_name = _load_lock_package_entries()

    for (group_path, package_name), expected_specifier in REQUIRED_SPECS.items():
        package_entries = packages_by_name.get(package_name, [])
        assert package_entries, f"{package_name} missing from uv.lock. {NEXT_ACTION}"

        specifier = _requirements_by_name(_dependency_group(pyproject, group_path))[
            package_name
        ].specifier
        assert specifier == SpecifierSet(expected_specifier), (
            f"{package_name} in {group_path} drifted before lock validation. {NEXT_ACTION}"
        )
        for package in package_entries:
            resolved = Version(package["version"])
            assert resolved in specifier, (
                f"{package_name}=={package['version']} from uv.lock violates "
                f"{group_path} specifier {specifier}. {NEXT_ACTION}"
            )


def test_essentia_lock_keeps_python_312_and_313_wheels_available() -> None:
    packages_by_name = _load_lock_package_entries()
    essentia_entries = packages_by_name.get("essentia", [])
    assert essentia_entries, f"essentia missing from uv.lock. {NEXT_ACTION}"

    wheels = [wheel for package in essentia_entries for wheel in package["wheels"]]
    wheel_urls = {wheel["url"] for wheel in wheels}
    wheel_tags = {
        match.group("tag")
        for url in wheel_urls
        if (match := re.search(r"-(?P<tag>cp\d+)-(?P=tag)-", url))
    }

    assert "cp312" in wheel_tags, f"essentia must keep a Python 3.12 wheel. {NEXT_ACTION}"
    assert "cp313" in wheel_tags, f"essentia must keep a Python 3.13 wheel. {NEXT_ACTION}"
    assert "cp314" not in wheel_tags, (
        "essentia must not regress to the cp314-only wheel set that blocked the "
        f"review. {NEXT_ACTION}"
    )


def test_core_dependency_runtime_smoke_paths() -> None:
    import cv2
    import litellm
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from mcp.types import Implementation, TextContent
    from mistralai.client import Mistral
    from PIL import Image
    from pydantic import BaseModel
    from qdrant_client.models import Distance, VectorParams

    class Payload(BaseModel):
        value: int

    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, int]:
        return Payload(value=7).model_dump()

    assert TestClient(app).get("/health").json() == {"value": 7}
    assert VectorParams(size=3, distance=Distance.COSINE).size == 3
    assert Implementation(name="hapax-smoke", version="0").name == "hapax-smoke"
    assert TextContent(type="text", text="ok").text == "ok"
    assert Mistral(api_key="test-key")
    assert Image.new("RGB", (1, 1)).size == (1, 1)
    assert cv2.__version__
    assert Version(version("torchvision")) in SpecifierSet(">=0.25,<0.26")
    assert litellm
    assert version("litellm")


def test_logos_and_google_dependency_runtime_smoke_paths() -> None:
    pytest.importorskip("googleapiclient.discovery")
    pytest.importorskip("google_auth_oauthlib.flow")
    pytest.importorskip("google.cloud.pubsub_v1")
    pytest.importorskip("langfuse")
    pytest.importorskip("sse_starlette.sse")

    from google.auth.credentials import AnonymousCredentials
    from google.cloud import pubsub_v1
    from google_auth_oauthlib.flow import Flow
    from langfuse import Langfuse
    from sse_starlette.sse import EventSourceResponse
    from uvicorn import Config

    assert AnonymousCredentials().expired is False
    assert pubsub_v1.PublisherClient
    assert Flow.from_client_config
    assert Langfuse
    assert EventSourceResponse
    assert Config("example:app").host == "127.0.0.1"


def test_audio_and_tui_dependency_runtime_smoke_paths() -> None:
    pytest.importorskip("essentia")
    pytest.importorskip("mediapipe")
    pytest.importorskip("soundfile")
    pytest.importorskip("textual")

    import essentia
    import mediapipe as mp
    import soundfile
    from textual.app import ComposeResult

    assert essentia.__version__.startswith("2.1-beta6")
    assert mp.__version__
    assert soundfile.__version__
    assert Version(version("torchcodec")) in SpecifierSet("==0.10.*")
    assert ComposeResult
