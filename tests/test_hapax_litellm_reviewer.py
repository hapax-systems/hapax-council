"""Tests for ``scripts/hapax-litellm-reviewer`` — the LiteLLM-backed review-seat
adapter that serves as the per-family fallback route (eval-plane resilience).

The adapter mirrors ``scripts/hapax-glmcp-reviewer``: it reads a blind review
prompt on stdin, POSTs it to the local LiteLLM gateway (``:4000``) under a
``--model`` alias, and writes the model reply to stdout. It is the one artifact
that makes the operator-confirmed OpenRouter/GLM tail reachable from a review
seat whose direct provider argv failed. These tests stub the ``pass`` secret
read and the HTTP opener so no network or gpg is exercised.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_ADAPTER = _SCRIPTS / "hapax-litellm-reviewer"


def _load() -> ModuleType:
    # The adapter is a no-.py executable; spec_from_file_location needs an
    # explicit loader for an extensionless path (unlike cc-pr-review-dispatch.py).
    if "hapax_litellm_reviewer" in sys.modules:
        return sys.modules["hapax_litellm_reviewer"]
    loader = SourceFileLoader("hapax_litellm_reviewer", str(_ADAPTER))
    spec = importlib.util.spec_from_loader("hapax_litellm_reviewer", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hapax_litellm_reviewer"] = module
    spec.loader.exec_module(module)
    return module


adapter = _load()


class _FakeResponse:
    """Minimal context-manager response standing in for an httplib response."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


def _openai_body(content: str) -> bytes:
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


@pytest.fixture
def fake_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "read_secret", lambda entry: "fake-litellm-key")


def _stub_stdout_stdin(monkeypatch: pytest.MonkeyPatch, prompt: str) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(prompt))


def test_help_prints_usage_and_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    rc = adapter.main(["--help"])

    assert rc == 0
    assert "hapax-litellm-reviewer" in capsys.readouterr().out


def test_check_mode_verifies_secret_and_loopback_base(
    fake_secret: None, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = adapter.main(["--model", "glm", "--check"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "hapax-litellm-reviewer" in out
    assert "127.0.0.1:4000" in out
    assert "glm" in out


def test_main_reads_stdin_posts_to_litellm_and_returns_message_content(
    monkeypatch: pytest.MonkeyPatch, fake_secret: None, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, Any] = {}

    def fake_open(request: Any, *, timeout: float) -> _FakeResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return _FakeResponse(
            _openai_body("```yaml\nverdict: accept\nfindings: []\nchecklist: {}\n```")
        )

    monkeypatch.setattr(adapter, "open_no_redirect", fake_open)
    _stub_stdout_stdin(monkeypatch, "REVIEW PACKET BODY")

    rc = adapter.main(["--model", "claude-sonnet"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "verdict: accept" in out
    request = captured["request"]
    assert request.full_url == "http://127.0.0.1:4000/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer fake-litellm-key"
    body = json.loads(request.data)
    assert body["model"] == "claude-sonnet"
    assert body["stream"] is False
    assert isinstance(body["messages"], list) and len(body["messages"]) == 2
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user"]
    assert "REVIEW PACKET BODY" in body["messages"][1]["content"]
    # the bare-fence contract rides the system message
    assert "yaml" in body["messages"][0]["content"].lower()


def test_main_http_error_exits_nonzero_with_status(
    monkeypatch: pytest.MonkeyPatch, fake_secret: None, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_open(_request: Any, *, timeout: float) -> _FakeResponse:
        raise urllib.error.HTTPError(
            "http://127.0.0.1:4000/v1/chat/completions",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"error":"invalid api key"}'),
        )

    monkeypatch.setattr(adapter, "open_no_redirect", fake_open)
    _stub_stdout_stdin(monkeypatch, "REVIEW PACKET")

    rc = adapter.main(["--model", "glm"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "401" in err


def test_main_empty_stdin_is_config_error_exit_two(
    monkeypatch: pytest.MonkeyPatch, fake_secret: None, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_stdout_stdin(monkeypatch, "   ")

    rc = adapter.main(["--model", "glm"])

    assert rc == 2
    assert "hapax-litellm-reviewer" in capsys.readouterr().err


def test_load_config_refuses_non_loopback_base_without_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HAPAX_LITELLM_REVIEW_BASE_URL", "https://evil.example/v1")
    # the pass-backed key must never be sent to a non-loopback host without review
    with pytest.raises(adapter.ConfigError):
        adapter.load_config(model="glm")


def test_main_refuses_redirect_protecting_authorization(
    monkeypatch: pytest.MonkeyPatch, fake_secret: None, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_open(_request: Any, *, timeout: float) -> _FakeResponse:
        raise urllib.error.HTTPError(
            "http://127.0.0.1:4000/v1/chat/completions",
            302,
            "Found",
            {"Location": "http://attacker.example/capture"},
            io.BytesIO(b""),
        )

    monkeypatch.setattr(adapter, "open_no_redirect", fake_open)
    _stub_stdout_stdin(monkeypatch, "REVIEW PACKET")

    rc = adapter.main(["--model", "glm"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "redirect" in err.lower()


def test_main_gateway_error_body_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, fake_secret: None, capsys: pytest.CaptureFixture[str]
) -> None:
    # LiteLLM can return HTTP 200 with a JSON 'error' body when a downstream provider
    # fails after the gateway accepts the request. That must surface as a process
    # failure (rc 1) so the fallback walker / classifier sees a route failure, not a
    # clean exit.
    def fake_open(_request: Any, *, timeout: float) -> _FakeResponse:
        return _FakeResponse(
            b'{"error":{"message":"upstream provider error","type":"provider_error"}}'
        )

    monkeypatch.setattr(adapter, "open_no_redirect", fake_open)
    _stub_stdout_stdin(monkeypatch, "REVIEW PACKET")

    rc = adapter.main(["--model", "glm"])

    assert rc == 1
    assert "gateway error" in capsys.readouterr().err.lower()


def test_main_content_as_list_of_parts_is_joined(
    monkeypatch: pytest.MonkeyPatch, fake_secret: None, capsys: pytest.CaptureFixture[str]
) -> None:
    # OpenRouter / OpenAI legitimately return content as a list of message parts;
    # the primary real-world response shape for the supply this adapter reaches.
    body = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": [
                            {
                                "type": "text",
                                "text": "```yaml\nverdict: accept\nfindings: []\nchecklist: {}\n```",
                            }
                        ]
                    }
                }
            ]
        }
    ).encode("utf-8")

    def fake_open(_request: Any, *, timeout: float) -> _FakeResponse:
        return _FakeResponse(body)

    monkeypatch.setattr(adapter, "open_no_redirect", fake_open)
    _stub_stdout_stdin(monkeypatch, "REVIEW PACKET")

    rc = adapter.main(["--model", "claude-sonnet"])

    assert rc == 0
    assert "verdict: accept" in capsys.readouterr().out
