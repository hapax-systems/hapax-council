"""Pin _sdlc_status._fetch_github_items against non-dict cache JSON.

Thirty-ninth site in the SHM corruption-class trail. The github cache
reader called ``data[\"items\"]`` and iterated it inside an
``except (json.JSONDecodeError, KeyError, OSError)`` clause — non-dict
JSON root caused TypeError (or AttributeError) which escaped the catch
and crashed the SDLC pipeline status collector.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agents import _sdlc_status as ss


@pytest.mark.parametrize(
    "payload,kind",
    [
        ("null", "null"),
        ('"a string"', "string"),
        ("[1, 2, 3]", "list"),
        ("42", "int"),
    ],
)
def test_fetch_github_items_non_dict_cache_does_not_crash(
    tmp_path: Path, payload: str, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt github-cache JSON with non-dict root must not crash
    the cache-hit branch. The function should fall through to the
    network-fetch path; we mock that to a deterministic empty result."""
    cache = tmp_path / "github-cache.json"
    cache.write_text(payload)
    monkeypatch.setattr(ss, "GITHUB_CACHE", cache)
    # Mock the gh subprocess so we don't hit the network; force it to
    # return empty so the test is deterministic regardless of cache state.
    with patch("agents._sdlc_status.subprocess.run") as mock_run:
        mock_run.return_value.stdout = "[]"
        mock_run.return_value.returncode = 0
        items, cached = ss._fetch_github_items()
    # The corrupt cache must be ignored without crashing — the function
    # falls through to the fetch path. cached=False indicates fall-through.
    assert isinstance(items, list), f"non-dict cache root={kind} must not crash"


def test_fetch_github_items_dict_cache_with_items_returns_cached(tmp_path, monkeypatch):
    """Sanity pin: dict cache root with items list returns cached=True."""
    import json

    cache = tmp_path / "github-cache.json"
    cache.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "number": 1234,
                        "title": "Test PR",
                        "kind": "pr",
                        "stage": "review",
                        "review_round": 0,
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(ss, "GITHUB_CACHE", cache)
    items, cached = ss._fetch_github_items()
    assert cached is True
    assert len(items) == 1
    assert items[0].number == 1234


def test_fetch_github_items_dict_cache_non_list_items_does_not_crash(tmp_path, monkeypatch):
    """Pin: dict cache root with non-list `items` field must not crash."""
    cache = tmp_path / "github-cache.json"
    cache.write_text('{"items": "not a list"}')
    monkeypatch.setattr(ss, "GITHUB_CACHE", cache)
    with patch("agents._sdlc_status.subprocess.run") as mock_run:
        mock_run.return_value.stdout = "[]"
        mock_run.return_value.returncode = 0
        items, cached = ss._fetch_github_items()
    assert isinstance(items, list)
