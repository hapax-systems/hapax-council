"""Regression guards for the python-prod dependency bump safety caps."""

import asyncio
import re
import subprocess
import sys
import textwrap
import tomllib
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
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

REQUIRED_EXTRAS = {
    ("project.optional-dependencies.audio", "pipecat-ai"): frozenset({"openai", "silero"}),
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


def _optional_distribution_installed(distribution: str) -> bool:
    try:
        version(distribution)
    except PackageNotFoundError:
        return False
    return True


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
        expected_extras = REQUIRED_EXTRAS.get((group_path, package_name), frozenset())
        assert requirements[package_name].extras == expected_extras, (
            f"{package_name} in {group_path} must keep extras {sorted(expected_extras)}. "
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


def test_ci_typecheck_exercises_locked_pyrefly_version() -> None:
    packages_by_name = _load_lock_package_entries()
    locked_pyrefly = packages_by_name["pyrefly"][0]["version"]
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    expected_command = f"uv run --no-project --with pyrefly=={locked_pyrefly} pyrefly check"
    assert expected_command in workflow, (
        f"CI typecheck must exercise the same pyrefly version resolved by uv.lock. {NEXT_ACTION}"
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


def test_core_dependency_runtime_smoke_paths() -> None:
    import cv2
    import litellm
    from fastapi import FastAPI
    from mcp.server.fastmcp import FastMCP
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

    async def smoke_fastmcp_registration() -> None:
        server = FastMCP("hapax-smoke")

        @server.tool()
        def echo(value: int) -> dict[str, int]:
            return {"value": value}

        tools = await server.list_tools()
        assert any(tool.name == "echo" for tool in tools), NEXT_ACTION
        content, structured = await server.call_tool("echo", {"value": 7})
        assert structured == {"value": 7}, NEXT_ACTION
        assert content and content[0].text, NEXT_ACTION

    assert health() == {"value": 7}, NEXT_ACTION
    assert any(route.path == "/health" for route in app.routes), NEXT_ACTION
    assert VectorParams(size=3, distance=Distance.COSINE).size == 3, NEXT_ACTION
    asyncio.run(smoke_fastmcp_registration())
    assert Implementation(name="hapax-smoke", version="0").name == "hapax-smoke", NEXT_ACTION
    assert TextContent(type="text", text="ok").text == "ok", NEXT_ACTION
    assert Mistral(api_key="test-key"), NEXT_ACTION
    assert Image.new("RGB", (1, 1)).size == (1, 1), NEXT_ACTION
    assert cv2.__version__, NEXT_ACTION
    assert Version(version("torchvision")) in SpecifierSet(">=0.25,<0.26"), NEXT_ACTION
    assert litellm.get_llm_provider("gpt-4o-mini")[1] == "openai", NEXT_ACTION
    assert version("litellm"), NEXT_ACTION


def test_logos_and_google_dependency_runtime_smoke_paths() -> None:
    exercised: list[str] = []

    if _optional_distribution_installed("google-api-python-client"):
        discovery = import_module("googleapiclient.discovery")
        assert discovery.build.__name__ == "build", NEXT_ACTION
        exercised.append("google-api-python-client")

    if _optional_distribution_installed("google-cloud-pubsub"):
        from google.auth.credentials import AnonymousCredentials

        pubsub_v1 = import_module("google.cloud.pubsub_v1")
        assert AnonymousCredentials().expired is False, NEXT_ACTION
        publisher = pubsub_v1.PublisherClient(credentials=AnonymousCredentials())
        assert publisher.topic_path("project-id", "topic-id") == (
            "projects/project-id/topics/topic-id"
        ), NEXT_ACTION
        exercised.append("google-cloud-pubsub")

    if _optional_distribution_installed("google-auth-oauthlib"):
        flow_module = import_module("google_auth_oauthlib.flow")
        flow = flow_module.Flow.from_client_config(
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
        assert flow.oauth2session.scope == ["https://www.googleapis.com/auth/gmail.readonly"], (
            NEXT_ACTION
        )
        exercised.append("google-auth-oauthlib")

    if _optional_distribution_installed("sse-starlette"):
        event_module = import_module("sse_starlette.sse")

        async def events():
            yield {"event": "ping", "data": "ok"}

        assert event_module.EventSourceResponse(events()).media_type == "text/event-stream", (
            NEXT_ACTION
        )
        exercised.append("sse-starlette")

    if _optional_distribution_installed("langfuse"):
        langfuse_module = import_module("langfuse")
        langfuse = langfuse_module.Langfuse(
            public_key="pk-lf-test",
            secret_key="sk-lf-test",
            host="http://127.0.0.1:1",
        )
        assert type(langfuse).__name__ == "Langfuse", NEXT_ACTION
        langfuse.shutdown()
        exercised.append("langfuse")

    if _optional_distribution_installed("uvicorn"):
        uvicorn_config = import_module("uvicorn").Config
        assert uvicorn_config("example:app").host == "127.0.0.1", NEXT_ACTION
        exercised.append("uvicorn")

    if not exercised:
        pytest.skip("logos/google optional dependencies are not installed")


def test_audio_and_tui_dependency_runtime_smoke_paths() -> None:
    exercised: list[str] = []

    if _optional_distribution_installed("essentia"):
        essentia = import_module("essentia")
        assert essentia.__version__.startswith("2.1-beta6"), NEXT_ACTION
        exercised.append("essentia")

    if _optional_distribution_installed("mediapipe"):
        mediapipe = import_module("mediapipe")
        assert mediapipe.__version__, NEXT_ACTION
        exercised.append("mediapipe")

    if _optional_distribution_installed("soundfile"):
        soundfile = import_module("soundfile")
        assert soundfile.__version__, NEXT_ACTION
        exercised.append("soundfile")

    if _optional_distribution_installed("textual"):
        textual_app = import_module("textual.app")
        assert textual_app.ComposeResult, NEXT_ACTION
        exercised.append("textual")

    if _optional_distribution_installed("torchcodec"):
        assert Version(version("torchcodec")) in SpecifierSet("==0.10.*"), NEXT_ACTION
        _run_clean_python(
            f"""
            import torchcodec

            NEXT_ACTION = {NEXT_ACTION!r}

            assert torchcodec.__name__ == "torchcodec", NEXT_ACTION
            """
        )
        exercised.append("torchcodec")

    if not exercised:
        pytest.skip("audio/tui optional dependencies are not installed")


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
        from matplotlib.figure import Figure
        from model2vec import StaticModel
        from ollama import Client as OllamaClient
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from werkzeug.datastructures import Headers

        NEXT_ACTION = {NEXT_ACTION!r}

        assert StaticModel.__name__ == "StaticModel", NEXT_ACTION
        if importlib.util.find_spec("gi") is not None:
            import gi

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
            from pipecat.audio.vad.silero import SileroVADAnalyzer
            from pipecat.services.openai.llm import OpenAILLMService

            assert Version(pipecat.__version__) in SpecifierSet(">=1.4.0"), NEXT_ACTION
            assert SileroVADAnalyzer.__name__ == "SileroVADAnalyzer", NEXT_ACTION
            assert OpenAILLMService.__name__ == "OpenAILLMService", NEXT_ACTION
        if importlib.util.find_spec("omegaconf") is not None:
            from omegaconf import OmegaConf

            config = OmegaConf.create({{"audio": {{"enabled": True}}}})
            assert config.audio.enabled is True, NEXT_ACTION
        if importlib.util.find_spec("pvporcupine") is not None:
            import pvporcupine

            assert "porcupine" in pvporcupine.KEYWORDS, NEXT_ACTION
        if (
            importlib.util.find_spec("pyannote") is not None
            and importlib.util.find_spec("pyannote.audio") is not None
        ):
            assert Version(version("pyannote.audio")) in SpecifierSet(">=4.0.7"), (
                NEXT_ACTION
            )
        """
    )


def test_optional_studio_and_rerank_dependency_runtime_smoke_paths() -> None:
    if not (
        _optional_distribution_installed("ultralytics")
        or _optional_distribution_installed("sentence-transformers")
    ):
        pytest.skip("studio/rerank optional dependencies are not installed")

    _run_clean_python(
        f"""
        import importlib.util
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version
        from importlib.metadata import version

        NEXT_ACTION = {NEXT_ACTION!r}
        exercised = []

        if importlib.util.find_spec("ultralytics") is not None:
            from ultralytics import YOLO

            assert YOLO.__name__ == "YOLO", NEXT_ACTION
            assert Version(version("ultralytics")) in SpecifierSet(">=8.4.87"), (
                NEXT_ACTION
            )
            exercised.append("ultralytics")
        if importlib.util.find_spec("sentence_transformers") is not None:
            from sentence_transformers import InputExample

            example = InputExample(texts=["left", "right"], label=1.0)
            assert example.texts == ["left", "right"], NEXT_ACTION
            assert example.label == 1.0, NEXT_ACTION
            assert Version(version("sentence-transformers")) in SpecifierSet(">=5.6.0"), (
                NEXT_ACTION
            )
            exercised.append("sentence-transformers")
        assert exercised, NEXT_ACTION
        """
    )
