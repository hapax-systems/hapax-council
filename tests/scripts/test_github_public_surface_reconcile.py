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


def test_gh_json_uses_authenticated_graphql_on_repo_rest_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    module = _module()
    subprocess_module = module["subprocess"]
    request_module = module["request"]

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        if "graphql" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=(
                    '{"data":{"repository":{"nameWithOwner":"hapax-systems/hapax-council",'
                    '"visibility":"PUBLIC","isPrivate":false,"isArchived":false,'
                    '"url":"https://github.com/hapax-systems/hapax-council",'
                    '"defaultBranchRef":{"name":"main","target":{"oid":"abc123"}},'
                    '"description":"Council","homepageUrl":"https://hapax.example",'
                    '"licenseInfo":{"spdxId":"NOASSERTION","name":"Other"},'
                    '"hasIssuesEnabled":true,"hasDiscussionsEnabled":false,'
                    '"hasWikiEnabled":false,"hasProjectsEnabled":false,'
                    '"pushedAt":"2026-07-08T15:00:00Z"}}}'
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(
            args,
            1,
            stdout="",
            stderr="gh: API rate limit exceeded for user ID 418460 (HTTP 403)\n",
        )

    def fake_urlopen(*args: object, **kwargs: object) -> _Response:
        del args, kwargs
        raise AssertionError("public fallback should not run when GraphQL succeeds")

    monkeypatch.setattr(subprocess_module, "run", fake_run)
    monkeypatch.setattr(request_module, "urlopen", fake_urlopen)

    with caplog.at_level("WARNING"):
        payload, error = module["_gh_json"]("repos/hapax-systems/hapax-council")

    assert error is None
    assert payload["full_name"] == "hapax-systems/hapax-council"
    assert payload["visibility"] == "public"
    assert payload["default_branch"] == "main"
    assert payload["license"]["spdx_id"] == "NOASSERTION"
    assert module["PUBLIC_GITHUB_FALLBACK_ENDPOINTS"] == set()
    assert module["AUTHENTICATED_GRAPHQL_FALLBACK_ENDPOINTS"] == {
        "repos/hapax-systems/hapax-council"
    }
    assert (
        "authenticated_graphql_fallback:gh api graphql repos/hapax-systems/hapax-council"
        in module["_source_refs"]()
    )
    assert "using authenticated GraphQL fallback" in caplog.text


def test_authenticated_graphql_fallback_shapes_branch_topics_tags_and_community(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    subprocess_module = module["subprocess"]

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        query_arg = next(arg for arg in args if arg.startswith("query="))
        if "ref(qualifiedName" in query_arg:
            stdout = '{"data":{"repository":{"ref":{"target":{"oid":"abc123"}}}}}'
        elif "repositoryTopics" in query_arg:
            stdout = (
                '{"data":{"repository":{"repositoryTopics":{"nodes":['
                '{"topic":{"name":"ai-governance"}},{"topic":{"name":"single-operator"}}'
                "]}}}}"
            )
        elif 'refs(refPrefix:"refs/tags/"' in query_arg:
            stdout = (
                '{"data":{"repository":{"refs":{"nodes":[{"name":"v1.0.0"},{"name":"v0.9.0"}]}}}}'
            )
        elif 'object(expression:"HEAD:.github/ISSUE_TEMPLATE")' in query_arg:
            stdout = (
                '{"data":{"repository":{"description":"Council",'
                '"object":{"entries":[{"name":"config.yml","type":"blob"}]}}}}'
            )
        else:
            raise AssertionError(f"unexpected GraphQL query: {query_arg}")
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess_module, "run", fake_run)

    branch_payload, branch_error = module["_authenticated_graphql_json"](
        "repos/hapax-systems/hapax-council/branches/main"
    )
    topics_payload, topics_error = module["_authenticated_graphql_json"](
        "repos/hapax-systems/hapax-council/topics"
    )
    tags_payload, tags_error = module["_authenticated_graphql_json"](
        "repos/hapax-systems/hapax-council/tags?per_page=100"
    )
    community_payload, community_error = module["_authenticated_graphql_json"](
        "repos/hapax-systems/hapax-council/community/profile"
    )

    assert branch_error is None
    assert branch_payload == {"name": "main", "commit": {"sha": "abc123"}}
    assert topics_error is None
    assert topics_payload == {"names": ["ai-governance", "single-operator"]}
    assert tags_error is None
    assert tags_payload == [{"name": "v1.0.0"}, {"name": "v0.9.0"}]
    assert community_error is None
    assert community_payload == {
        "health_percentage": None,
        "description": "Council",
        "files": {"issue_template": None},
    }


def test_authenticated_graphql_fallback_reports_graphql_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    subprocess_module = module["subprocess"]

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(
            args,
            0,
            stdout='{"errors":[{"message":"rate-limited by GraphQL"}]}',
            stderr="",
        )

    monkeypatch.setattr(subprocess_module, "run", fake_run)

    payload, error = module["_authenticated_graphql_json"]("repos/hapax-systems/hapax-council")

    assert payload is None
    assert "rate-limited by GraphQL" in error


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
