"""Tests for snapshot + delta computation.

The monitor must operate exclusively on entry NAMES and never decrypt or
read ``.gpg`` file contents. Tests cover snapshot walking, delta
computation, and missing-store fallback.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.hapax_cred_monitor.monitor import (
    Snapshot,
    compute_delta,
    walk_pass_store,
)


def _make_pass_store(root: Path, entries: list[str]) -> Path:
    """Create a fake pass store under ``root`` with ``.gpg`` files at the
    given entry names. The ``.gpg`` bodies are deliberately non-secret
    sentinel bytes — tests must never read them, only walk filenames.
    """
    store = root / ".password-store"
    store.mkdir(parents=True, exist_ok=True)
    for name in entries:
        path = store / f"{name}.gpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        # Sentinel content: if any code path reads this, the redaction
        # test asserts that this string never reaches stdout/log/state.
        path.write_bytes(b"DO_NOT_READ_THIS_VALUE_SENTINEL")
    return store


class TestWalkPassStore:
    def test_yields_entry_names_without_gpg_suffix(self, tmp_path: Path) -> None:
        store = _make_pass_store(tmp_path, ["api/anthropic", "orcid/orcid"])
        snap = walk_pass_store(store)
        assert "api/anthropic" in snap.entries
        assert "orcid/orcid" in snap.entries
        assert all(not e.endswith(".gpg") for e in snap.entries)

    def test_returns_sorted_tuple(self, tmp_path: Path) -> None:
        store = _make_pass_store(tmp_path, ["zenodo/api-token", "api/anthropic", "orcid/orcid"])
        snap = walk_pass_store(store)
        assert list(snap.entries) == sorted(snap.entries)

    def test_handles_nested_directories(self, tmp_path: Path) -> None:
        store = _make_pass_store(
            tmp_path, ["bluesky/operator-app-password", "google/oauth-client-id"]
        )
        snap = walk_pass_store(store)
        assert "bluesky/operator-app-password" in snap.entries
        assert "google/oauth-client-id" in snap.entries

    def test_missing_store_returns_empty_snapshot(self, tmp_path: Path) -> None:
        snap = walk_pass_store(tmp_path / "nonexistent-store")
        assert snap.entries == ()
        assert snap.captured_at  # still timestamped
        assert "nonexistent-store" in snap.store_path

    def test_records_capture_timestamp(self, tmp_path: Path) -> None:
        store = _make_pass_store(tmp_path, ["api/anthropic"])
        snap = walk_pass_store(store)
        assert snap.captured_at.endswith("Z")
        assert "T" in snap.captured_at  # ISO-8601 shape


class TestComputeDelta:
    def _snap(self, *names: str) -> Snapshot:
        return Snapshot(entries=tuple(sorted(names)), captured_at="t", store_path="p")

    def test_arrival_only(self) -> None:
        prior = self._snap("api/anthropic")
        current = self._snap("api/anthropic", "orcid/orcid")
        delta = compute_delta(prior, current)
        assert delta.arrived == frozenset({"orcid/orcid"})
        assert delta.departed == frozenset()
        assert delta.is_change() is True

    def test_departure_only(self) -> None:
        prior = self._snap("api/anthropic", "orcid/orcid")
        current = self._snap("api/anthropic")
        delta = compute_delta(prior, current)
        assert delta.arrived == frozenset()
        assert delta.departed == frozenset({"orcid/orcid"})
        assert delta.is_change() is True

    def test_no_change(self) -> None:
        prior = self._snap("api/anthropic", "orcid/orcid")
        current = self._snap("api/anthropic", "orcid/orcid")
        delta = compute_delta(prior, current)
        assert delta.arrived == frozenset()
        assert delta.departed == frozenset()
        assert delta.is_change() is False

    def test_first_run_from_empty_prior(self) -> None:
        prior = self._snap()
        current = self._snap("api/anthropic", "orcid/orcid")
        delta = compute_delta(prior, current)
        assert delta.arrived == frozenset({"api/anthropic", "orcid/orcid"})
        assert delta.departed == frozenset()


@pytest.fixture
def fake_store(tmp_path: Path) -> Path:
    return _make_pass_store(tmp_path, ["api/anthropic", "orcid/orcid", "zenodo/api-token"])


def test_walk_does_not_open_gpg_files(fake_store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If walk_pass_store ever reads ``.gpg`` bytes, the test fails.

    Patches ``Path.read_bytes`` and ``Path.read_text`` and ``open`` to fail
    if invoked on a ``.gpg`` path. ``Path.rglob`` and ``Path.is_dir`` are
    metadata-only and remain available.
    """
    real_read_bytes = Path.read_bytes
    real_read_text = Path.read_text
    real_open = Path.open

    def guard(method_name: str):
        def _wrapped(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if str(self).endswith(".gpg"):
                raise AssertionError(
                    f"cred monitor MUST NOT call {method_name} on .gpg files; got {self}"
                )
            return {
                "read_bytes": real_read_bytes,
                "read_text": real_read_text,
                "open": real_open,
            }[method_name](self, *args, **kwargs)

        return _wrapped

    monkeypatch.setattr(Path, "read_bytes", guard("read_bytes"))
    monkeypatch.setattr(Path, "read_text", guard("read_text"))
    monkeypatch.setattr(Path, "open", guard("open"))

    snap = walk_pass_store(fake_store)
    assert "api/anthropic" in snap.entries
    assert "orcid/orcid" in snap.entries
    assert "zenodo/api-token" in snap.entries
