"""Tests for the publisher daemon's checkout-ready guard.

Specifically pins the remote-URL normalization that lets the daemon
accept either SSH or HTTPS clones of the external repo. Before this
guard, the bootstrap script's HTTPS clone made the daemon refuse to
push because the configured remote default is SSH — breaking the
end-to-end CDN sync for no semantic reason.
"""

from __future__ import annotations

import pytest

from agents.hapax_assets_publisher.daemon import _normalize_remote


class TestNormalizeRemote:
    """Both schemes for the same repo must normalize to the same string."""

    def test_ssh_and_https_match_for_same_repo(self) -> None:
        ssh = _normalize_remote("git@github.com:ryanklee/hapax-assets.git")
        https = _normalize_remote("https://github.com/ryanklee/hapax-assets.git")
        assert ssh == https
        assert ssh == "github.com/ryanklee/hapax-assets"

    def test_http_and_https_match(self) -> None:
        assert _normalize_remote(
            "https://github.com/ryanklee/hapax-assets.git"
        ) == _normalize_remote("http://github.com/ryanklee/hapax-assets.git")

    def test_ssh_url_form_matches_short_ssh(self) -> None:
        assert _normalize_remote(
            "ssh://git@github.com/ryanklee/hapax-assets.git"
        ) == _normalize_remote("git@github.com:ryanklee/hapax-assets.git")

    def test_trailing_dot_git_optional(self) -> None:
        assert _normalize_remote("https://github.com/ryanklee/hapax-assets") == _normalize_remote(
            "https://github.com/ryanklee/hapax-assets.git"
        )

    def test_whitespace_stripped(self) -> None:
        assert (
            _normalize_remote("  https://github.com/ryanklee/hapax-assets.git\n")
            == "github.com/ryanklee/hapax-assets"
        )

    def test_different_repos_do_not_match(self) -> None:
        assert _normalize_remote(
            "https://github.com/ryanklee/hapax-assets.git"
        ) != _normalize_remote("https://github.com/ryanklee/hapax-council.git")

    def test_unknown_scheme_returns_input_minus_dot_git(self) -> None:
        # Belt-and-suspenders: unrecognized scheme falls through to the
        # stripped input so the comparison still works on exact-string
        # matches between two identical configured/probed remotes.
        assert _normalize_remote("file:///tmp/repo.git") == "file:///tmp/repo"


@pytest.mark.parametrize(
    "url_a,url_b",
    [
        (
            "git@github.com:ryanklee/hapax-assets.git",
            "https://github.com/ryanklee/hapax-assets",
        ),
        (
            "https://github.com/ryanklee/hapax-assets.git",
            "git@github.com:ryanklee/hapax-assets",
        ),
        (
            "ssh://git@github.com/ryanklee/hapax-assets",
            "https://github.com/ryanklee/hapax-assets.git",
        ),
    ],
)
def test_paired_schemes_for_same_repo_match(url_a: str, url_b: str) -> None:
    assert _normalize_remote(url_a) == _normalize_remote(url_b)
