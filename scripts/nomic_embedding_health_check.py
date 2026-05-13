#!/usr/bin/env python3
"""Verify the local Nomic embedding runtime before RAG work uses it."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL_ALIAS = "nomic-embed-cpu"
DEFAULT_BASE_MODEL = "nomic-embed-text-v2-moe"
DEFAULT_EXPECTED_DIMENSIONS = 768
DEFAULT_TIMEOUT_SECONDS = 10.0
HEALTH_CHECK_INPUT = "search_query: hapax nomic embedding health check"


@dataclass(frozen=True)
class HttpResponse:
    status: int
    data: Any | None
    body: str


RequestJson = Callable[[str, str, Mapping[str, Any] | None, float], HttpResponse]


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def request_json(
    method: str,
    url: str,
    payload: Mapping[str, Any] | None,
    timeout: float,
) -> HttpResponse:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    parsed: Any | None = None
    if body:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = None
    return HttpResponse(status=status, data=parsed, body=body)


def _failure(code: str, message: str, remediation: str) -> dict[str, str]:
    return {"code": code, "message": message, "remediation": remediation}


def _model_bases(model_names: Sequence[str]) -> set[str]:
    return {name.split(":", 1)[0] for name in model_names}


def _model_present(model_names: Sequence[str], model: str) -> bool:
    return model in model_names or model in _model_bases(model_names)


def _storage_inaccessible_text(text: str) -> bool:
    lowered = text.lower()
    storage_markers = ("permission denied", "operation not permitted", "/store/ollama")
    return any(marker in lowered for marker in storage_markers)


def _extract_model_names(data: Any) -> list[str] | None:
    if not isinstance(data, Mapping):
        return None
    models = data.get("models")
    if not isinstance(models, list):
        return None
    names: list[str] = []
    for item in models:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return sorted(names)


def _extract_embedding_dimensions(data: Any) -> list[int] | None:
    if not isinstance(data, Mapping):
        return None
    embeddings = data.get("embeddings")
    if not isinstance(embeddings, list) or not embeddings:
        return None
    dimensions: list[int] = []
    for embedding in embeddings:
        if not isinstance(embedding, list):
            return None
        dimensions.append(len(embedding))
    return dimensions


def run_health_check(
    *,
    ollama_url: str,
    model_alias: str,
    expected_dimensions: int,
    base_model: str | None = DEFAULT_BASE_MODEL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    requester: RequestJson = request_json,
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    failures: list[dict[str, str]] = []

    tags_url = _join_url(ollama_url, "/api/tags")
    try:
        tags_response = requester("GET", tags_url, None, timeout)
    except Exception as exc:
        failures.append(
            _failure(
                "api_unavailable",
                f"Cannot reach Ollama API at {tags_url}: {exc}",
                "Start or repair the local Ollama service, then rerun this command.",
            )
        )
        return {
            "ok": False,
            "ollama_url": ollama_url,
            "model_alias": model_alias,
            "base_model": base_model,
            "expected_dimensions": expected_dimensions,
            "checks": {"api_reachable": {"ok": False, "url": tags_url}},
            "failures": failures,
        }

    checks["api_reachable"] = {"ok": tags_response.status == 200, "status": tags_response.status}
    if tags_response.status != 200:
        if _storage_inaccessible_text(tags_response.body):
            failures.append(
                _failure(
                    "storage_inaccessible",
                    f"Ollama listed models with HTTP {tags_response.status}; response indicates storage access failure.",
                    "Repair the Ollama storage mount or permissions, restart Ollama, and rerun this command.",
                )
            )
        else:
            failures.append(
                _failure(
                    "api_unavailable",
                    f"Ollama /api/tags returned HTTP {tags_response.status}.",
                    "Start or repair the local Ollama service, then rerun this command.",
                )
            )
        return {
            "ok": False,
            "ollama_url": ollama_url,
            "model_alias": model_alias,
            "base_model": base_model,
            "expected_dimensions": expected_dimensions,
            "checks": checks,
            "failures": failures,
        }

    model_names = _extract_model_names(tags_response.data)
    if model_names is None:
        failures.append(
            _failure(
                "invalid_tags_response",
                "Ollama /api/tags did not return a JSON object with a models list.",
                "Check the Ollama API response and rerun this command.",
            )
        )
        return {
            "ok": False,
            "ollama_url": ollama_url,
            "model_alias": model_alias,
            "base_model": base_model,
            "expected_dimensions": expected_dimensions,
            "checks": checks,
            "failures": failures,
        }

    checks["models_listed"] = {"ok": True, "models": model_names}
    checks["alias_present"] = {"ok": _model_present(model_names, model_alias)}
    if not checks["alias_present"]["ok"]:
        failures.append(
            _failure(
                "alias_absent",
                f"Required embedding alias {model_alias!r} is absent from Ollama.",
                f"Create the alias with `ollama cp {base_model or '<base-model>'} {model_alias}`.",
            )
        )

    if base_model:
        checks["base_model_present"] = {"ok": _model_present(model_names, base_model)}
        if not checks["base_model_present"]["ok"]:
            failures.append(
                _failure(
                    "base_model_absent",
                    f"Base embedding model {base_model!r} is absent from Ollama.",
                    f"Pull the base model with `ollama pull {base_model}` before creating the alias.",
                )
            )

    if not checks["alias_present"]["ok"]:
        return {
            "ok": False,
            "ollama_url": ollama_url,
            "model_alias": model_alias,
            "base_model": base_model,
            "expected_dimensions": expected_dimensions,
            "checks": checks,
            "failures": failures,
        }

    embed_url = _join_url(ollama_url, "/api/embed")
    embed_payload = {"model": model_alias, "input": [HEALTH_CHECK_INPUT]}
    try:
        embed_response = requester("POST", embed_url, embed_payload, timeout)
    except Exception as exc:
        failures.append(
            _failure(
                "api_unavailable",
                f"Cannot reach Ollama embedding endpoint at {embed_url}: {exc}",
                "Start or repair the local Ollama service, then rerun this command.",
            )
        )
        checks["embed_request"] = {"ok": False, "url": embed_url}
    else:
        checks["embed_request"] = {
            "ok": embed_response.status == 200,
            "status": embed_response.status,
        }
        if embed_response.status != 200:
            failures.append(
                _failure(
                    "embed_request_failed",
                    f"Ollama /api/embed returned HTTP {embed_response.status}.",
                    "Check that the alias can be loaded by Ollama, then rerun this command.",
                )
            )
        else:
            dimensions = _extract_embedding_dimensions(embed_response.data)
            checks["embedding_dimensions"] = {
                "ok": dimensions == [expected_dimensions],
                "observed": dimensions,
                "expected": expected_dimensions,
            }
            if dimensions is None:
                failures.append(
                    _failure(
                        "invalid_embed_response",
                        "Ollama /api/embed did not return a non-empty embeddings list.",
                        "Inspect the local Ollama response and model alias configuration.",
                    )
                )
            elif dimensions != [expected_dimensions]:
                failures.append(
                    _failure(
                        "wrong_dimension",
                        f"Expected one {expected_dimensions}-dimensional embedding, got dimensions {dimensions}.",
                        "Restore the 768-dimensional Nomic embedding alias before RAG work continues.",
                    )
                )

    return {
        "ok": not failures,
        "ollama_url": ollama_url,
        "model_alias": model_alias,
        "base_model": base_model,
        "expected_dimensions": expected_dimensions,
        "checks": checks,
        "failures": failures,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_URL))
    parser.add_argument(
        "--model-alias",
        default=os.environ.get("EMBEDDING_MODEL", DEFAULT_MODEL_ALIAS),
        help="Configured embedding alias that RAG callers use.",
    )
    parser.add_argument(
        "--base-model",
        default=os.environ.get("NOMIC_BASE_MODEL", DEFAULT_BASE_MODEL),
        help="Underlying model expected to exist before the alias is copied.",
    )
    parser.add_argument(
        "--no-base-model-check",
        action="store_true",
        help="Skip the base-model presence check and validate only the configured alias.",
    )
    parser.add_argument(
        "--expected-dimensions",
        type=int,
        default=int(os.environ.get("EXPECTED_EMBED_DIMENSIONS", DEFAULT_EXPECTED_DIMENSIONS)),
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_health_check(
        ollama_url=args.ollama_url,
        model_alias=args.model_alias,
        base_model=None if args.no_base_model_check else args.base_model,
        expected_dimensions=args.expected_dimensions,
        timeout=args.timeout,
    )
    indent = 2 if args.pretty else None
    print(json.dumps(report, indent=indent, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
