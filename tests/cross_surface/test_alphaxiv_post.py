"""Tests for the retired ``agents.cross_surface.alphaxiv_post`` shim."""

from __future__ import annotations

from unittest import mock

from agents.cross_surface.alphaxiv_post import publish_artifact


class _FakeArtifact:
    slug = "test"


def test_publish_artifact_refuses_without_network(monkeypatch):
    monkeypatch.setenv("HAPAX_ALPHAXIV_TOKEN", "tok")
    monkeypatch.setenv("HAPAX_ALPHAXIV_API_URL", "https://api.alphaxiv.org")
    with mock.patch("requests.post") as posted:
        assert publish_artifact(_FakeArtifact()) == "denied"
    posted.assert_not_called()
