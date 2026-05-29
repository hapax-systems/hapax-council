"""401-resilience: a stale env client_id auto-heals via a fresh scrape, and a
failed fetch never empties a non-empty last-good playlist.

Incident (2026-05-29): a stale ``SOUNDCLOUD_CLIENT_ID`` pinned in the
environment overrode the auto-scrape, so ``api.resolve()`` returned HTTP 401.
``sclib`` then indexed the bool error body (``obj['kind']``) and raised
``TypeError: 'bool' object is not subscriptable``; the adapter swallowed it to
``[]`` and ``main`` wrote 0 tracks, clobbering the operator's banked set.

These tests pin the two durable guarantees:

1. A fetch that fails while using an *env-pinned* client_id re-scrapes a fresh
   id and retries once — the env id is a hint, not gospel.
2. ``main`` never overwrites a non-empty ``soundcloud.jsonl`` with 0 tracks
   when a configured source's fetch errored; only a genuine, successful empty
   result may empty the file.

Library-agnostic and hermetic: the ``sclib`` client is a ``MagicMock`` and the
env + scrape are stubbed, so no real network call happens.
"""

from __future__ import annotations

import json
import os
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from agents.soundcloud_adapter import __main__ as sc

STALE_ENV_ID = "STALEcafef00dcafef00dcafef00dcafe"  # 32 chars
FRESH_SCRAPED_ID = "FRESHbeefbeefbeefbeefbeefbeefbee"  # 32 chars


def _sclib_track(title: str, permalink: str) -> SimpleNamespace:
    return SimpleNamespace(
        title=title,
        artist="Oudepode",
        permalink_url=permalink,
        duration=120_000,
        genre="",
    )


def _auth_error(kind: str) -> Exception:
    """Reproduce the two real shapes a 401 takes through sclib.

    ``typeerror`` is the documented downstream symptom (``obj['kind']`` on a
    bool error body); ``http401`` is the raw urllib ``HTTPError``.
    """
    if kind == "typeerror":
        return TypeError("'bool' object is not subscriptable")
    return urllib.error.HTTPError(
        "https://api.soundcloud.com/resolve",
        401,
        "Unauthorized",
        hdrs={},  # type: ignore[arg-type]
        fp=None,
    )


# --- 1. auto-heal: stale env id -> fresh scrape + retry succeeds -----------


@pytest.mark.parametrize("kind", ["typeerror", "http401"])
def test_fetch_set_stale_env_id_scrapes_fresh_and_retries(kind: str) -> None:
    mock_client = mock.MagicMock()
    mock_api = mock.MagicMock()
    mock_client.SoundcloudAPI.return_value = mock_api
    playlist = SimpleNamespace(
        tracks=[
            _sclib_track("Banked A", "https://soundcloud.com/o/a"),
            _sclib_track("Banked B", "https://soundcloud.com/o/b"),
        ]
    )
    # First resolve (stale env id) fails; second (fresh scraped id) succeeds.
    mock_api.resolve.side_effect = [_auth_error(kind), playlist]

    with (
        mock.patch.dict("os.environ", {"SOUNDCLOUD_CLIENT_ID": STALE_ENV_ID}),
        mock.patch.object(sc, "_scrape_client_id", return_value=FRESH_SCRAPED_ID) as scrape,
    ):
        out = sc.fetch_set(
            "https://soundcloud.com/o/sets/banked/s-tok",
            client_spec=(mock_client, "sclib"),
        )

    assert [r["title"] for r in out] == ["Banked A", "Banked B"]
    assert mock_api.resolve.call_count == 2  # failed once, retried once
    scrape.assert_called_once()  # exactly one fresh scrape
    built_ids = [c.kwargs.get("client_id") for c in mock_client.SoundcloudAPI.call_args_list]
    assert STALE_ENV_ID in built_ids  # tried the env hint first
    assert FRESH_SCRAPED_ID in built_ids  # then the freshly scraped id


def test_fetch_likes_stale_env_id_scrapes_fresh_and_retries() -> None:
    mock_client = mock.MagicMock()
    mock_api = mock.MagicMock()
    mock_client.SoundcloudAPI.return_value = mock_api
    user = SimpleNamespace(tracks=[_sclib_track("Like A", "https://soundcloud.com/o/la")])
    mock_api.resolve.side_effect = [_auth_error("typeerror"), user]

    with (
        mock.patch.dict("os.environ", {"SOUNDCLOUD_CLIENT_ID": STALE_ENV_ID}),
        mock.patch.object(sc, "_scrape_client_id", return_value=FRESH_SCRAPED_ID),
    ):
        out = sc.fetch_likes("oudepode", client_spec=(mock_client, "sclib"))

    assert [r["title"] for r in out] == ["Like A"]
    assert mock_api.resolve.call_count == 2


def test_fetch_set_scraped_id_failure_does_not_double_scrape() -> None:
    """When the id was already freshly scraped (env empty), a resolve failure
    is NOT retried — re-scraping yields the same id. Degrades to []."""
    mock_client = mock.MagicMock()
    mock_api = mock.MagicMock()
    mock_client.SoundcloudAPI.return_value = mock_api
    mock_api.resolve.side_effect = _auth_error("http401")

    with (
        mock.patch.dict("os.environ"),
        mock.patch.object(sc, "_scrape_client_id", return_value=FRESH_SCRAPED_ID) as scrape,
    ):
        os.environ.pop("SOUNDCLOUD_CLIENT_ID", None)
        out = sc.fetch_set("u", client_spec=(mock_client, "sclib"))

    assert out == []
    scrape.assert_called_once()  # only the initial resolution scrape
    assert mock_api.resolve.call_count == 1  # no retry on an already-fresh id


# --- 2. total auth failure is contained (no TypeError escapes) -------------


@pytest.mark.parametrize("kind", ["typeerror", "http401"])
def test_fetch_set_total_auth_failure_returns_empty_no_raise(kind: str) -> None:
    """Even when the fresh-scrape retry also fails, the adapter degrades to []
    — the 401/TypeError never escapes — and the outcome is flagged failed."""
    mock_client = mock.MagicMock()
    mock_api = mock.MagicMock()
    mock_client.SoundcloudAPI.return_value = mock_api

    def _always_raise(*_a: object, **_k: object) -> None:
        raise _auth_error(kind)

    mock_api.resolve.side_effect = _always_raise

    with (
        mock.patch.dict("os.environ", {"SOUNDCLOUD_CLIENT_ID": STALE_ENV_ID}),
        mock.patch.object(sc, "_scrape_client_id", return_value=FRESH_SCRAPED_ID),
    ):
        out = sc.fetch_set("u", client_spec=(mock_client, "sclib"))
        outcome = sc._fetch_set("u", client_spec=(mock_client, "sclib"))

    assert out == []
    assert outcome.tracks == []
    assert outcome.failed is True


# --- boundary: no library / no config is a genuine empty, not a failure ----


def test_fetch_set_no_library_is_genuine_empty_not_failure() -> None:
    """No SC client library installed is a stable config state, not a fetch
    failure — it must NOT flag the source failed, so main is free to write an
    empty file (pins tests/shared/test_music_repo.py
    ::test_main_writes_empty_jsonl_when_lib_missing)."""
    with mock.patch.object(sc, "_try_import_client", return_value=None):
        outcome = sc._fetch_set("u", client_spec=None)
    assert outcome.tracks == []
    assert outcome.failed is False


def test_fetch_likes_no_library_is_genuine_empty_not_failure() -> None:
    with mock.patch.object(sc, "_try_import_client", return_value=None):
        outcome = sc._fetch_likes("u", client_spec=None)
    assert outcome.tracks == []
    assert outcome.failed is False


# --- client_id resolution source tagging -----------------------------------


def test_resolve_client_id_with_source_env() -> None:
    with mock.patch.dict("os.environ", {"SOUNDCLOUD_CLIENT_ID": STALE_ENV_ID}):
        cid, source = sc._resolve_client_id_with_source()
    assert cid == STALE_ENV_ID
    assert source == "env"


def test_resolve_client_id_with_source_scraped() -> None:
    with (
        mock.patch.dict("os.environ"),
        mock.patch.object(sc, "_scrape_client_id", return_value=FRESH_SCRAPED_ID),
    ):
        os.environ.pop("SOUNDCLOUD_CLIENT_ID", None)
        cid, source = sc._resolve_client_id_with_source()
    assert cid == FRESH_SCRAPED_ID
    assert source == "scraped"


def test_resolve_client_id_with_source_none() -> None:
    with (
        mock.patch.dict("os.environ"),
        mock.patch.object(sc, "_scrape_client_id", return_value=None),
    ):
        os.environ.pop("SOUNDCLOUD_CLIENT_ID", None)
        cid, source = sc._resolve_client_id_with_source()
    assert cid is None
    assert source == "none"


# --- 3. main never clobbers a non-empty playlist on fetch failure ----------


def _seed_repo(path: Path, n: int) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "path": f"https://soundcloud.com/o/{i}",
            "title": f"T{i}",
            "source": "soundcloud-oudepode",
        }
        for i in range(n)
    ]
    text = "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


def test_main_preserves_last_good_when_all_sources_fail(tmp_path: Path) -> None:
    repo = tmp_path / "soundcloud.jsonl"
    before = _seed_repo(repo, 8)

    with (
        mock.patch.object(sc, "SOUNDCLOUD_REPO_PATH", repo),
        mock.patch.dict(
            "os.environ",
            {
                "HAPAX_SOUNDCLOUD_USER_ID": "12345",
                "HAPAX_SOUNDCLOUD_BANKED_URL": "https://soundcloud.com/o/sets/banked/s-tok",
            },
        ),
        mock.patch.object(
            sc, "_fetch_likes", return_value=sc._FetchOutcome(tracks=[], failed=True)
        ),
        mock.patch.object(sc, "_fetch_set", return_value=sc._FetchOutcome(tracks=[], failed=True)),
    ):
        rc = sc.main(["--auto"])

    assert rc == 1  # surfaced as failure (systemd OnFailure=notify-failure)
    assert repo.read_text(encoding="utf-8") == before  # last-good intact, NOT clobbered


def test_main_overwrites_with_genuine_empty_success(tmp_path: Path) -> None:
    """A successful fetch that genuinely returns zero tracks DOES empty the
    file — only failures are protected."""
    repo = tmp_path / "soundcloud.jsonl"
    _seed_repo(repo, 5)

    with (
        mock.patch.object(sc, "SOUNDCLOUD_REPO_PATH", repo),
        mock.patch.dict("os.environ", {"HAPAX_SOUNDCLOUD_USER_ID": "12345"}),
        mock.patch.object(
            sc, "_fetch_likes", return_value=sc._FetchOutcome(tracks=[], failed=False)
        ),
    ):
        os.environ.pop("HAPAX_SOUNDCLOUD_BANKED_URL", None)
        os.environ.pop("HAPAX_SOUNDCLOUD_USERNAME", None)
        rc = sc.main(["--auto"])

    assert rc == 0
    assert repo.read_text(encoding="utf-8").strip() == ""  # genuinely emptied


def test_main_partial_success_still_writes(tmp_path: Path) -> None:
    """If at least one source yields tracks, main writes them even when another
    source failed — only the all-empty case is protected (documented scope)."""
    repo = tmp_path / "soundcloud.jsonl"
    _seed_repo(repo, 8)
    good = sc._FetchOutcome(
        tracks=[{"path": "https://soundcloud.com/o/new", "title": "New", "tags": ["soundcloud"]}],
        failed=False,
    )

    with (
        mock.patch.object(sc, "SOUNDCLOUD_REPO_PATH", repo),
        mock.patch.dict(
            "os.environ",
            {
                "HAPAX_SOUNDCLOUD_USER_ID": "12345",
                "HAPAX_SOUNDCLOUD_BANKED_URL": "https://x/s-tok",
            },
        ),
        mock.patch.object(sc, "_fetch_likes", return_value=good),
        mock.patch.object(sc, "_fetch_set", return_value=sc._FetchOutcome(tracks=[], failed=True)),
    ):
        rc = sc.main(["--auto"])

    assert rc == 0
    lines = [ln for ln in repo.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["path"] == "https://soundcloud.com/o/new"
