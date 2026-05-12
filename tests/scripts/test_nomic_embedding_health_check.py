from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "nomic_embedding_health_check.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("_nomic_embedding_health_check", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _requester(module, responses: dict[tuple[str, str], Any]):
    def fake_request(method: str, url: str, _payload: dict[str, Any] | None, _timeout: float):
        value = responses[(method, url)]
        if isinstance(value, Exception):
            raise value
        status, data, body = value
        return module.HttpResponse(status=status, data=data, body=body)

    return fake_request


def _run(module, responses: dict[tuple[str, str], Any], **kwargs):
    return module.run_health_check(
        ollama_url="http://ollama.test",
        model_alias="nomic-embed-cpu",
        base_model=kwargs.pop("base_model", "nomic-embed-text-v2-moe"),
        expected_dimensions=kwargs.pop("expected_dimensions", 768),
        requester=_requester(module, responses),
        **kwargs,
    )


def _ok_responses(dimensions: int = 768):
    return {
        ("GET", "http://ollama.test/api/tags"): (
            200,
            {
                "models": [
                    {"name": "nomic-embed-cpu:latest"},
                    {"name": "nomic-embed-text-v2-moe:latest"},
                ]
            },
            "{}",
        ),
        ("POST", "http://ollama.test/api/embed"): (
            200,
            {"embeddings": [[0.1] * dimensions]},
            "{}",
        ),
    }


def test_health_check_accepts_alias_base_model_and_768_dimensions() -> None:
    module = _load_module()

    report = _run(module, _ok_responses())

    assert report["ok"] is True
    assert report["checks"]["alias_present"]["ok"] is True
    assert report["checks"]["base_model_present"]["ok"] is True
    assert report["checks"]["embedding_dimensions"]["observed"] == [768]
    assert report["failures"] == []


def test_health_check_reports_api_unavailable() -> None:
    module = _load_module()
    report = _run(
        module,
        {
            ("GET", "http://ollama.test/api/tags"): OSError("connection refused"),
        },
    )

    assert report["ok"] is False
    assert report["failures"][0]["code"] == "api_unavailable"


def test_health_check_reports_storage_inaccessible() -> None:
    module = _load_module()
    report = _run(
        module,
        {
            ("GET", "http://ollama.test/api/tags"): (
                500,
                None,
                "open /store/ollama/models: permission denied",
            ),
        },
    )

    assert report["ok"] is False
    assert report["failures"][0]["code"] == "storage_inaccessible"


def test_health_check_reports_absent_alias_and_base_model() -> None:
    module = _load_module()
    report = _run(
        module,
        {
            ("GET", "http://ollama.test/api/tags"): (
                200,
                {"models": [{"name": "other-model:latest"}]},
                "{}",
            ),
        },
    )

    assert report["ok"] is False
    assert [failure["code"] for failure in report["failures"]] == [
        "alias_absent",
        "base_model_absent",
    ]


def test_health_check_still_checks_dimensions_when_only_base_model_is_absent() -> None:
    module = _load_module()
    report = _run(
        module,
        {
            ("GET", "http://ollama.test/api/tags"): (
                200,
                {"models": [{"name": "nomic-embed-cpu:latest"}]},
                "{}",
            ),
            ("POST", "http://ollama.test/api/embed"): (
                200,
                {"embeddings": [[0.1] * 768]},
                "{}",
            ),
        },
    )

    assert report["ok"] is False
    assert report["checks"]["embedding_dimensions"]["observed"] == [768]
    assert [failure["code"] for failure in report["failures"]] == ["base_model_absent"]


def test_health_check_reports_wrong_dimension() -> None:
    module = _load_module()
    report = _run(module, _ok_responses(dimensions=384))

    assert report["ok"] is False
    assert report["checks"]["embedding_dimensions"]["observed"] == [384]
    assert report["failures"][0]["code"] == "wrong_dimension"
