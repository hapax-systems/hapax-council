"""Regression guards for the python-prod dependency bump safety caps."""

import re
import subprocess
import sys
import textwrap
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
    ("project.dependencies", "ollama"): ">=0.6.2",
    ("project.dependencies", "pydantic"): ">=2.13.4",
    ("project.dependencies", "pydantic-ai"): ">=1.99.0,<2",
    ("project.dependencies", "qdrant-client"): ">=1.18.0",
    ("project.dependencies", "python-json-logger"): ">=3.3.0,<4",
    ("project.dependencies", "litellm"): ">=1.90.3",
    ("project.dependencies", "torchvision"): ">=0.25,<0.26",
    ("project.dependencies", "mistralai"): ">=2.5.2",
    ("project.dependencies", "model2vec"): ">=0.8.2",
    ("project.dependencies", "pillow"): ">=12.3.0",
    ("project.dependencies", "pygobject"): ">=3.56.3",
    ("project.dependencies", "fastapi"): ">=0.139.0",
    ("project.dependencies", "werkzeug"): ">=3.1.8",
    ("project.dependencies", "opencv-python-headless"): ">=4.13.0.92,<5",
    ("project.dependencies", "google-cloud-monitoring"): ">=2.31.0",
    ("project.dependencies", "mcp"): ">=1.28.1",
    ("project.optional-dependencies.logos-api", "fastapi"): ">=0.139.0",
    ("project.optional-dependencies.logos-api", "uvicorn"): ">=0.49.0",
    ("project.optional-dependencies.sync-pipeline", "google-api-python-client"): ">=2.198.0",
    ("project.optional-dependencies.sync-pipeline", "google-auth-oauthlib"): ">=1.4.0",
    ("project.optional-dependencies.mail-monitor", "google-api-python-client"): ">=2.198.0",
    ("project.optional-dependencies.mail-monitor", "google-auth"): ">=2.55.1",
    ("project.optional-dependencies.mail-monitor", "google-auth-oauthlib"): ">=1.4.0",
    ("project.optional-dependencies.mail-monitor", "google-cloud-pubsub"): ">=2.39.0",
    ("project.optional-dependencies.audio", "mediapipe"): ">=0.10.35",
    ("project.optional-dependencies.audio", "opencv-python-headless"): ">=4.10.0,<5",
    ("project.optional-dependencies.audio", "pipecat-ai"): ">=1.4.0",
    ("project.optional-dependencies.audio", "pyannote-audio"): ">=4.0.7",
    ("project.optional-dependencies.audio", "omegaconf"): ">=2.3.1",
    ("project.optional-dependencies.audio", "pvporcupine"): ">=4.0.3",
    ("project.optional-dependencies.audio", "soundfile"): ">=0.14.0",
    ("project.optional-dependencies.audio", "torchcodec"): "==0.10.*",
    ("project.optional-dependencies.audio", "essentia"): ">=2.1b6.dev1091,<=2.1b6.dev1389",
    ("project.optional-dependencies.logos-api", "langfuse"): ">=3.14.5,<4",
    ("project.optional-dependencies.logos-api", "sse-starlette"): ">=2.0.0,<3",
    ("project.optional-dependencies.sync-pipeline", "langfuse"): ">=3.14.5,<4",
    ("project.optional-dependencies.ci", "matplotlib"): ">=3.11.0",
    ("project.optional-dependencies.ci", "playwright"): ">=1.61.0",
    ("project.optional-dependencies.ci", "pillow"): ">=12.3.0",
    ("project.optional-dependencies.ci", "pyrefly"): ">=0.62,<1",
    ("project.optional-dependencies.studio", "ultralytics"): ">=8.4.87",
    ("project.optional-dependencies.tui", "textual"): ">=3.0,<4",
    ("project.optional-dependencies.rerank", "sentence-transformers"): ">=5.6.0",
    ("tool.uv.override-dependencies", "torch"): ">=2.10,<2.11",
    ("tool.uv.override-dependencies", "torchaudio"): ">=2.10,<2.11",
    ("tool.uv.override-dependencies", "pillow"): ">=12.3.0",
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
    if group_path == "tool.uv.override-dependencies":
        return pyproject["tool"]["uv"]["override-dependencies"]

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


def _run_clean_python(script: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        pytest.fail(
            "clean Python smoke path failed. "
            f"{NEXT_ACTION}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}",
            pytrace=False,
        )


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


def test_torch_abi_stack_keeps_override_and_lockstep_pairing() -> None:
    pyproject = _load_pyproject()
    packages_by_name = _load_lock_package_entries()
    overrides = _requirements_by_name(pyproject["tool"]["uv"]["override-dependencies"])

    for package_name in ("torch", "torchaudio"):
        assert package_name in overrides, (
            f"{package_name} must stay in [tool.uv] override-dependencies. {NEXT_ACTION}"
        )
        assert overrides[package_name].specifier == SpecifierSet(">=2.10,<2.11"), (
            f"{package_name} override must keep the 2.10 ABI band. {NEXT_ACTION}"
        )

    locked_versions = {
        package_name: Version(packages_by_name[package_name][0]["version"])
        for package_name in ("torch", "torchaudio", "torchvision", "torchcodec")
    }
    assert locked_versions["torch"] in SpecifierSet(">=2.10,<2.11"), NEXT_ACTION
    assert locked_versions["torchaudio"] in SpecifierSet(">=2.10,<2.11"), NEXT_ACTION
    assert locked_versions["torchvision"] in SpecifierSet(">=0.25,<0.26"), NEXT_ACTION
    assert locked_versions["torchcodec"] in SpecifierSet("==0.10.*"), NEXT_ACTION
    assert (locked_versions["torch"].major, locked_versions["torch"].minor) == (
        locked_versions["torchaudio"].major,
        locked_versions["torchaudio"].minor,
    ), NEXT_ACTION
    assert (locked_versions["torch"].major, locked_versions["torch"].minor) == (
        2,
        10,
    ), NEXT_ACTION
    assert (locked_versions["torchvision"].major, locked_versions["torchvision"].minor) == (
        0,
        25,
    ), NEXT_ACTION
    assert (locked_versions["torchcodec"].major, locked_versions["torchcodec"].minor) == (
        0,
        10,
    ), NEXT_ACTION

    torchvision_dependencies = {
        dependency["name"] for dependency in packages_by_name["torchvision"][0]["dependencies"]
    }
    assert "torch" in torchvision_dependencies, (
        f"torchvision must continue declaring a torch runtime edge. {NEXT_ACTION}"
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
    assert litellm.get_llm_provider("gpt-4o-mini")[1] == "openai"
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
    publisher = pubsub_v1.PublisherClient(credentials=AnonymousCredentials())
    assert publisher.topic_path("project-id", "topic-id") == "projects/project-id/topics/topic-id"
    flow = Flow.from_client_config(
        {
            "installed": {
                "client_id": "id.apps.googleusercontent.com",
                "client_secret": "secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        },
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    assert flow.oauth2session.scope == ["https://www.googleapis.com/auth/gmail.readonly"]

    async def events():
        yield {"event": "ping", "data": "ok"}

    assert EventSourceResponse(events()).media_type == "text/event-stream"
    langfuse = Langfuse(
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="http://127.0.0.1:1",
    )
    assert type(langfuse).__name__ == "Langfuse"
    langfuse.shutdown()
    assert Config("example:app").host == "127.0.0.1"


def test_audio_and_tui_dependency_runtime_smoke_paths() -> None:
    pytest.importorskip("essentia")
    pytest.importorskip("mediapipe")
    pytest.importorskip("soundfile")
    pytest.importorskip("textual")
    pytest.importorskip("torchcodec")

    import essentia
    import mediapipe as mp
    import soundfile
    from textual.app import ComposeResult

    assert essentia.__version__.startswith("2.1-beta6")
    assert mp.__version__
    assert soundfile.__version__
    assert Version(version("torchcodec")) in SpecifierSet("==0.10.*")
    assert ComposeResult


def test_torch_torchvision_clean_subprocess_abi_smoke_path() -> None:
    _run_clean_python(
        f"""
        from importlib.metadata import version
        import importlib.util

        from packaging.specifiers import SpecifierSet
        from packaging.version import Version

        NEXT_ACTION = {NEXT_ACTION!r}

        import torch
        import torchvision

        assert Version(torch.__version__) in SpecifierSet(">=2.10,<2.11"), NEXT_ACTION
        assert Version(torchvision.__version__) in SpecifierSet(">=0.25,<0.26"), (
            NEXT_ACTION
        )
        if importlib.util.find_spec("torchcodec") is not None:
            assert Version(version("torchcodec")) in SpecifierSet("==0.10.*"), NEXT_ACTION
        """
    )


def test_additional_bumped_dependency_runtime_smoke_paths() -> None:
    _run_clean_python(
        f"""
        from importlib.metadata import version
        import importlib.util

        from google.auth.credentials import AnonymousCredentials
        from google.cloud import pubsub_v1
        from google.cloud import monitoring_v3
        import gi
        from matplotlib.figure import Figure
        from model2vec import StaticModel
        from ollama import Client as OllamaClient
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from werkzeug.datastructures import Headers

        NEXT_ACTION = {NEXT_ACTION!r}

        assert StaticModel.__name__ == "StaticModel", NEXT_ACTION
        assert gi.version_info >= (3, 56, 3), NEXT_ACTION
        assert OllamaClient(host="http://127.0.0.1:1"), NEXT_ACTION
        assert Headers([("X-Test", "ok")])["X-Test"] == "ok", NEXT_ACTION
        figure = Figure(figsize=(1, 1))
        axes = figure.subplots()
        axes.plot([0, 1], [1, 0])
        assert len(figure.axes) == 1, NEXT_ACTION
        assert PlaywrightTimeoutError.__name__ == "TimeoutError", NEXT_ACTION
        monitoring_client = monitoring_v3.MetricServiceClient(
            credentials=AnonymousCredentials()
        )
        monitoring_request = monitoring_v3.ListTimeSeriesRequest(
            name="projects/test-project"
        )
        assert type(monitoring_client).__name__ == "MetricServiceClient", NEXT_ACTION
        assert monitoring_request.name == "projects/test-project", NEXT_ACTION
        publisher = pubsub_v1.PublisherClient(credentials=AnonymousCredentials())
        assert publisher.topic_path("project-id", "topic-id") == (
            "projects/project-id/topics/topic-id"
        ), NEXT_ACTION

        if importlib.util.find_spec("pipecat") is not None:
            import pipecat

            assert Version(pipecat.__version__) in SpecifierSet(">=1.4.0"), NEXT_ACTION
        if importlib.util.find_spec("omegaconf") is not None:
            from omegaconf import OmegaConf

            config = OmegaConf.create({{"audio": {{"enabled": True}}}})
            assert config.audio.enabled is True, NEXT_ACTION
        if importlib.util.find_spec("pvporcupine") is not None:
            import pvporcupine

            assert "porcupine" in pvporcupine.KEYWORDS, NEXT_ACTION
        if importlib.util.find_spec("pyannote.audio") is not None:
            assert Version(version("pyannote.audio")) in SpecifierSet(">=4.0.7"), (
                NEXT_ACTION
            )
        """
    )


def test_optional_studio_and_rerank_dependency_runtime_smoke_paths() -> None:
    _run_clean_python(
        f"""
        import importlib.util
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version
        from importlib.metadata import version

        NEXT_ACTION = {NEXT_ACTION!r}

        if importlib.util.find_spec("ultralytics") is not None:
            from ultralytics import YOLO

            assert YOLO.__name__ == "YOLO", NEXT_ACTION
            assert Version(version("ultralytics")) in SpecifierSet(">=8.4.87"), (
                NEXT_ACTION
            )
        if importlib.util.find_spec("sentence_transformers") is not None:
            from sentence_transformers import InputExample

            example = InputExample(texts=["left", "right"], label=1.0)
            assert example.texts == ["left", "right"], NEXT_ACTION
            assert example.label == 1.0, NEXT_ACTION
            assert Version(version("sentence-transformers")) in SpecifierSet(">=5.6.0"), (
                NEXT_ACTION
            )
        """
    )
