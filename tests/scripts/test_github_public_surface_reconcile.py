from __future__ import annotations

import runpy
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "github-public-surface-reconcile.py"


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self) -> bytes:
        return self._body


def _module() -> dict[str, Any]:
    return runpy.run_path(str(SCRIPT))


def test_gh_json_falls_back_to_public_rest_on_authenticated_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    module = _module()
    subprocess_module = module["subprocess"]
    request_module = module["request"]
    fallback_urls: list[str] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(
            args,
            1,
            stdout="",
            stderr="gh: API rate limit exceeded for user ID 418460 (HTTP 403)\n",
        )

    def fake_urlopen(github_request: Any, *, timeout: int) -> _Response:
        assert timeout == 30
        fallback_urls.append(github_request.full_url)
        return _Response(b'{"full_name":"hapax-systems/hapax-council","visibility":"public"}')

    monkeypatch.setattr(subprocess_module, "run", fake_run)
    monkeypatch.setattr(request_module, "urlopen", fake_urlopen)

    with caplog.at_level("WARNING"):
        payload, error = module["_gh_json"]("repos/hapax-systems/hapax-council")

    assert error is None
    assert payload == {"full_name": "hapax-systems/hapax-council", "visibility": "public"}
    assert fallback_urls == ["https://api.github.com/repos/hapax-systems/hapax-council"]
    assert module["PUBLIC_GITHUB_FALLBACK_ENDPOINTS"] == {"repos/hapax-systems/hapax-council"}
    assert (
        "public_unauthenticated_fallback:gh api repos/hapax-systems/hapax-council"
        in module["_source_refs"]()
    )
    assert "using public unauthenticated fallback" in caplog.text
    assert "next action: refresh with authenticated gh api" in caplog.text


def test_gh_json_falls_back_to_public_rest_on_secondary_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    subprocess_module = module["subprocess"]
    request_module = module["request"]

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(
            args,
            1,
            stdout="",
            stderr="gh: You have exceeded a secondary rate limit (HTTP 403)\n",
        )

    def fake_urlopen(github_request: Any, *, timeout: int) -> _Response:
        del github_request
        assert timeout == 30
        return _Response(b'{"full_name":"hapax-systems/hapax-council"}')

    monkeypatch.setattr(subprocess_module, "run", fake_run)
    monkeypatch.setattr(request_module, "urlopen", fake_urlopen)

    payload, error = module["_gh_json"]("repos/hapax-systems/hapax-council")

    assert error is None
    assert payload == {"full_name": "hapax-systems/hapax-council"}


def test_gh_json_does_not_public_fallback_for_non_rate_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    subprocess_module = module["subprocess"]
    request_module = module["request"]

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(
            args,
            1,
            stdout="",
            stderr="gh: Not Found (HTTP 404)\n",
        )

    def fake_urlopen(*args: object, **kwargs: object) -> _Response:
        del args, kwargs
        raise AssertionError("public fallback should not run")

    monkeypatch.setattr(subprocess_module, "run", fake_run)
    monkeypatch.setattr(request_module, "urlopen", fake_urlopen)

    payload, error = module["_gh_json"]("repos/hapax-systems/missing")

    assert payload is None
    assert error == "gh: Not Found (HTTP 404)"
