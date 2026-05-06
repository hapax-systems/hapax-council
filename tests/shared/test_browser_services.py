"""Tests for shared.browser_services.

Python-side mirror of the Rust ServiceRegistry — loads
``~/.hapax/browser-services.json`` and provides domain allowlist
checking + URL resolution. 56 LOC, untested before this commit.

Tests monkeypatch ``REGISTRY_PATH`` to a tmp file so the operator's
real ~/.hapax/browser-services.json is never read or mutated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared import browser_services


@pytest.fixture
def fake_registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect REGISTRY_PATH to a tmp file. Returns the path."""
    path = tmp_path / "browser-services.json"
    monkeypatch.setattr(browser_services, "REGISTRY_PATH", path)
    return path


# ── load_registry ──────────────────────────────────────────────────


class TestLoadRegistry:
    def test_missing_file_returns_empty_dict(self, fake_registry: Path) -> None:
        assert not fake_registry.exists()
        assert browser_services.load_registry() == {}

    def test_well_formed_json_loaded(self, fake_registry: Path) -> None:
        data = {"github": {"base": "https://github.com", "patterns": {"pr": "/{repo}/pull/{n}"}}}
        fake_registry.write_text(json.dumps(data))
        assert browser_services.load_registry() == data

    def test_malformed_json_returns_empty(self, fake_registry: Path) -> None:
        """Parse failure logs a warning + returns ``{}`` (fail-open —
        a corrupt registry shouldn't crash callers)."""
        fake_registry.write_text("{ this is not json")
        assert browser_services.load_registry() == {}


# ── is_allowed ─────────────────────────────────────────────────────


class TestIsAllowed:
    def test_url_in_registered_service_returns_true(self, fake_registry: Path) -> None:
        fake_registry.write_text(json.dumps({"gh": {"base": "https://github.com", "patterns": {}}}))
        assert browser_services.is_allowed("https://github.com/foo/bar")

    def test_url_outside_any_service_returns_false(self, fake_registry: Path) -> None:
        fake_registry.write_text(json.dumps({"gh": {"base": "https://github.com", "patterns": {}}}))
        assert not browser_services.is_allowed("https://example.com/foo")

    def test_empty_registry_returns_false(self, fake_registry: Path) -> None:
        assert not browser_services.is_allowed("https://anything.com")

    def test_service_without_base_matches_everything_pin(self, fake_registry: Path) -> None:
        """Regression pin for current behaviour: a service entry with
        no `base` field falls through to `svc.get("base", "")` →
        `url.startswith("")` returns True for any URL. This pins the
        documented behaviour so a future fix (rejecting empty-base
        services) is a deliberate, test-flipping change rather than
        an accidental drift."""
        fake_registry.write_text(json.dumps({"weird": {"patterns": {}}}))
        assert browser_services.is_allowed("https://anything.com")


# ── resolve_url ────────────────────────────────────────────────────


class TestResolveUrl:
    def test_unknown_service_returns_none(self, fake_registry: Path) -> None:
        fake_registry.write_text(json.dumps({}))
        assert browser_services.resolve_url("missing", "pr") is None

    def test_unknown_pattern_returns_none(self, fake_registry: Path) -> None:
        fake_registry.write_text(json.dumps({"gh": {"base": "https://github.com", "patterns": {}}}))
        assert browser_services.resolve_url("gh", "missing") is None

    def test_resolves_simple_pattern(self, fake_registry: Path) -> None:
        fake_registry.write_text(
            json.dumps(
                {
                    "gh": {
                        "base": "https://github.com",
                        "patterns": {"home": "/"},
                    }
                }
            )
        )
        assert browser_services.resolve_url("gh", "home") == "https://github.com/"

    def test_substitutes_params(self, fake_registry: Path) -> None:
        fake_registry.write_text(
            json.dumps(
                {
                    "gh": {
                        "base": "https://github.com",
                        "patterns": {"pr": "/{repo}/pull/{n}"},
                    }
                }
            )
        )
        url = browser_services.resolve_url(
            "gh", "pr", {"repo": "ryanklee/hapax-council", "n": "2085"}
        )
        assert url == "https://github.com/ryanklee/hapax-council/pull/2085"

    def test_default_repo_filled_when_present(self, fake_registry: Path) -> None:
        """When a service declares ``default_repo``, the {repo} placeholder
        is filled even if not supplied via params."""
        fake_registry.write_text(
            json.dumps(
                {
                    "gh": {
                        "base": "https://github.com",
                        "patterns": {"issue": "/{repo}/issues/{n}"},
                        "default_repo": "ryanklee/hapax-council",
                    }
                }
            )
        )
        url = browser_services.resolve_url("gh", "issue", {"n": "42"})
        assert url == "https://github.com/ryanklee/hapax-council/issues/42"

    def test_explicit_repo_param_overrides_default(self, fake_registry: Path) -> None:
        """When both params['repo'] and default_repo are set, params wins
        because the param substitution loop runs before the default fill."""
        fake_registry.write_text(
            json.dumps(
                {
                    "gh": {
                        "base": "https://github.com",
                        "patterns": {"home": "/{repo}"},
                        "default_repo": "fallback",
                    }
                }
            )
        )
        url = browser_services.resolve_url("gh", "home", {"repo": "explicit"})
        assert url == "https://github.com/explicit"

    def test_none_params_treated_as_empty(self, fake_registry: Path) -> None:
        """``params=None`` must not crash; it's treated as no substitutions."""
        fake_registry.write_text(
            json.dumps(
                {
                    "gh": {
                        "base": "https://github.com",
                        "patterns": {"static": "/static"},
                    }
                }
            )
        )
        assert browser_services.resolve_url("gh", "static") == "https://github.com/static"


import pytest


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_load_registry_non_dict_root_returns_empty(fake_registry, payload, kind):
    """Pin load_registry against non-dict JSON. is_allowed and
    resolve_url immediately call registry.values() / registry.get() —
    a non-dict root previously raised AttributeError out of browser
    allowlist enforcement."""
    fake_registry.write_text(payload)
    assert browser_services.load_registry() == {}, f"non-dict root={kind} must yield empty dict"
    # Critical: downstream callers must work without raising.
    assert browser_services.is_allowed("https://example.com") is False
    assert browser_services.resolve_url("any", "any") is None
