"""Tests for browser agent and service registry."""

import json
from pathlib import Path
from unittest.mock import patch

from agents.browser_agent import resolve_task_to_url
from shared.browser_services import is_allowed, load_registry, resolve_url

MOCK_REGISTRY = {
    "github": {
        "base": "https://github.com/ryanklee",
        "patterns": {
            "pr": "/{repo}/pull/{id}",
            "issue": "/{repo}/issues/{id}",
            "repo": "/{repo}",
        },
        "default_repo": "hapax-council",
    },
    "grafana": {
        "base": "http://localhost:3000",
        "patterns": {
            "board": "/d/{id}",
            "explore": "/explore",
        },
    },
}


class TestServiceRegistry:
    def test_resolve_github_pr(self, tmp_path: Path):
        registry_file = tmp_path / "browser-services.json"
        registry_file.write_text(json.dumps(MOCK_REGISTRY))
        with patch("shared.browser_services.REGISTRY_PATH", registry_file):
            url = resolve_url("github", "pr", {"id": "145"})
            assert url == "https://github.com/ryanklee/hapax-council/pull/145"

    def test_resolve_github_issue(self, tmp_path: Path):
        registry_file = tmp_path / "browser-services.json"
        registry_file.write_text(json.dumps(MOCK_REGISTRY))
        with patch("shared.browser_services.REGISTRY_PATH", registry_file):
            url = resolve_url("github", "issue", {"id": "42"})
            assert url == "https://github.com/ryanklee/hapax-council/issues/42"

    def test_resolve_grafana_board(self, tmp_path: Path):
        registry_file = tmp_path / "browser-services.json"
        registry_file.write_text(json.dumps(MOCK_REGISTRY))
        with patch("shared.browser_services.REGISTRY_PATH", registry_file):
            url = resolve_url("grafana", "board", {"id": "api-latency"})
            assert url == "http://localhost:3000/d/api-latency"

    def test_resolve_unknown_service(self, tmp_path: Path):
        registry_file = tmp_path / "browser-services.json"
        registry_file.write_text(json.dumps(MOCK_REGISTRY))
        with patch("shared.browser_services.REGISTRY_PATH", registry_file):
            url = resolve_url("unknown", "pr", {"id": "1"})
            assert url is None

    def test_is_allowed_github(self, tmp_path: Path):
        registry_file = tmp_path / "browser-services.json"
        registry_file.write_text(json.dumps(MOCK_REGISTRY))
        with patch("shared.browser_services.REGISTRY_PATH", registry_file):
            assert is_allowed("https://github.com/ryanklee/hapax-council/pull/145")
            assert not is_allowed("https://evil.example.com/steal-data")

    def test_missing_registry(self, tmp_path: Path):
        registry_file = tmp_path / "nonexistent.json"
        with patch("shared.browser_services.REGISTRY_PATH", registry_file):
            registry = load_registry()
            assert registry == {}


class TestTaskResolution:
    def test_resolve_pr_task(self, tmp_path: Path):
        registry_file = tmp_path / "browser-services.json"
        registry_file.write_text(json.dumps(MOCK_REGISTRY))
        with patch("shared.browser_services.REGISTRY_PATH", registry_file):
            url = resolve_task_to_url("check PR 145")
            assert url == "https://github.com/ryanklee/hapax-council/pull/145"

    def test_resolve_pr_with_hash(self, tmp_path: Path):
        registry_file = tmp_path / "browser-services.json"
        registry_file.write_text(json.dumps(MOCK_REGISTRY))
        with patch("shared.browser_services.REGISTRY_PATH", registry_file):
            url = resolve_task_to_url("check PR #145")
            assert url == "https://github.com/ryanklee/hapax-council/pull/145"

    def test_resolve_issue(self, tmp_path: Path):
        registry_file = tmp_path / "browser-services.json"
        registry_file.write_text(json.dumps(MOCK_REGISTRY))
        with patch("shared.browser_services.REGISTRY_PATH", registry_file):
            url = resolve_task_to_url("look at issue 42")
            assert url == "https://github.com/ryanklee/hapax-council/issues/42"

    def test_resolve_direct_url(self):
        url = resolve_task_to_url("https://example.com/page")
        assert url == "https://example.com/page"

    def test_resolve_unrecognized(self, tmp_path: Path):
        registry_file = tmp_path / "browser-services.json"
        registry_file.write_text(json.dumps(MOCK_REGISTRY))
        with patch("shared.browser_services.REGISTRY_PATH", registry_file):
            url = resolve_task_to_url("do something vague")
            assert url is None
