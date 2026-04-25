"""Tests for ``shared.governance.publisher_kit.BasePublisher``.

The kit ships standalone with green tests; per-surface refactors land in
PUB-P1-A/B/C tickets. These tests use a ``_FakePublisher`` subclass with
deterministic stubs to validate the run-once/cursor/tail/allowlist/
dry-run/Counter cycle.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import pytest
from prometheus_client import CollectorRegistry

from shared.governance.publisher_kit import BasePublisher


def _write_events(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event) + "\n")


# ── Fake publisher subclass with deterministic stubs ────────────────


@dataclass
class _FakeComposed:
    text: str


class _FakePublisher(BasePublisher[_FakeComposed]):
    SURFACE = "fake-surface"
    STATE_KIND = "broadcast.boundary"
    EVENT_TYPE = "broadcast_rotated"
    METRIC_NAME = "test_fake_publisher_total"
    METRIC_DESCRIPTION = "Fake publisher posts attempted, by outcome."
    LEGAL_NAME_GUARD_FIELDS = ()

    def __init__(
        self,
        *,
        event_path: Path,
        cursor_path: Path,
        registry: CollectorRegistry,
        compose_text: str = "fake post",
        send_result: str = "ok",
        send_raises: bool = False,
        compose_raises: bool = False,
        credentials_present: tuple[bool, str] = (True, ""),
        dry_run: bool = False,
    ) -> None:
        super().__init__(
            event_path=event_path,
            cursor_path=cursor_path,
            registry=registry,
            dry_run=dry_run,
        )
        self._compose_text = compose_text
        self._send_result = send_result
        self._send_raises = send_raises
        self._compose_raises = compose_raises
        self._creds = credentials_present
        self.compose_calls = 0
        self.send_calls = 0

    def compose(self, event: dict) -> _FakeComposed:
        self.compose_calls += 1
        if self._compose_raises:
            raise RuntimeError("compose failure")
        return _FakeComposed(text=self._compose_text)

    def send(self, composed: _FakeComposed) -> str:
        self.send_calls += 1
        if self._send_raises:
            raise RuntimeError("send failure")
        return self._send_result

    def credentials_present(self) -> tuple[bool, str]:
        return self._creds


def _make(tmp_path, **kwargs) -> _FakePublisher:
    return _FakePublisher(
        event_path=tmp_path / "events.jsonl",
        cursor_path=tmp_path / "cursor.txt",
        registry=CollectorRegistry(),
        **kwargs,
    )


@pytest.fixture
def _allowlist_allow():
    """Patch ``allowlist_check`` to return ``allow`` so test fixtures
    don't need a YAML contract on disk for the fake surface."""
    with mock.patch(
        "shared.governance.publisher_kit.allowlist_check",
        return_value=mock.Mock(decision="allow", reason=""),
    ) as m:
        yield m


# ── ClassVar validation ─────────────────────────────────────────────


class TestClassVarValidation:
    def test_missing_classvar_raises(self, tmp_path):
        class _Bad(BasePublisher[str]):
            SURFACE = ""  # missing
            STATE_KIND = "broadcast.boundary"
            EVENT_TYPE = "broadcast_rotated"
            METRIC_NAME = "test_bad_total"

            def compose(self, event):
                return "x"

            def send(self, composed):
                return "ok"

        with pytest.raises(TypeError, match="must set ClassVar 'SURFACE'"):
            _Bad(
                event_path=tmp_path / "e.jsonl",
                cursor_path=tmp_path / "c.txt",
                registry=CollectorRegistry(),
            )


# ── Cursor + tail ───────────────────────────────────────────────────


class TestCursor:
    def test_missing_event_file(self, tmp_path):
        publisher = _make(tmp_path)
        assert publisher.run_once() == 0

    def test_persists_cursor(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": "broadcast_rotated", "id": "x"}])
        publisher = _make(tmp_path)
        publisher.run_once()
        assert int((tmp_path / "cursor.txt").read_text()) == bus.stat().st_size

    def test_no_cursor_advance_on_zero_events(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": "stream_started"}])
        publisher = _make(tmp_path)
        publisher.run_once()
        assert not (tmp_path / "cursor.txt").exists()


# ── Event filtering ─────────────────────────────────────────────────


class TestEventFiltering:
    def test_skips_non_target_event_type(self, tmp_path, _allowlist_allow):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                {"event_type": "stream_started"},
                {"event_type": "broadcast_rotated", "id": "x"},
            ],
        )
        publisher = _make(tmp_path)
        publisher.run_once()
        assert publisher.compose_calls == 1
        assert publisher.send_calls == 1


# ── Allowlist gating ────────────────────────────────────────────────


class TestAllowlistGate:
    def test_deny_short_circuits(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": "broadcast_rotated", "id": "x"}])
        with mock.patch(
            "shared.governance.publisher_kit.allowlist_check",
            return_value=mock.Mock(decision="deny", reason="test"),
        ):
            publisher = _make(tmp_path)
            publisher.run_once()
        assert publisher.compose_calls == 0
        assert publisher.send_calls == 0


# ── Dry run ─────────────────────────────────────────────────────────


class TestDryRun:
    def test_dry_run_does_not_send(self, tmp_path, _allowlist_allow):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": "broadcast_rotated", "id": "x"}])
        publisher = _make(tmp_path, dry_run=True)
        publisher.run_once()
        assert publisher.compose_calls == 1
        assert publisher.send_calls == 0


# ── Credentials gate ────────────────────────────────────────────────


class TestCredentialsGate:
    def test_no_credentials_skips_send(self, tmp_path, _allowlist_allow):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": "broadcast_rotated", "id": "x"}])
        publisher = _make(tmp_path, credentials_present=(False, "missing token"))
        publisher.run_once()
        assert publisher.compose_calls == 1
        assert publisher.send_calls == 0


# ── Compose error ───────────────────────────────────────────────────


class TestComposeError:
    def test_compose_error_does_not_send(self, tmp_path, _allowlist_allow):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": "broadcast_rotated", "id": "x"}])
        publisher = _make(tmp_path, compose_raises=True)
        publisher.run_once()
        assert publisher.compose_calls == 1
        assert publisher.send_calls == 0


# ── Counter labels ──────────────────────────────────────────────────


class TestCounterLabels:
    def test_ok_label_increments(self, tmp_path, _allowlist_allow):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": "broadcast_rotated", "id": "x"}])
        publisher = _make(tmp_path, send_result="ok")
        publisher.run_once()
        sample = publisher.posts_total.labels(result="ok")._value.get()
        assert sample == 1.0

    def test_dry_run_label_increments(self, tmp_path, _allowlist_allow):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": "broadcast_rotated", "id": "x"}])
        publisher = _make(tmp_path, dry_run=True)
        publisher.run_once()
        sample = publisher.posts_total.labels(result="dry_run")._value.get()
        assert sample == 1.0

    def test_denied_label_on_allowlist_deny(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": "broadcast_rotated", "id": "x"}])
        with mock.patch(
            "shared.governance.publisher_kit.allowlist_check",
            return_value=mock.Mock(decision="deny", reason="test"),
        ):
            publisher = _make(tmp_path)
            publisher.run_once()
        sample = publisher.posts_total.labels(result="denied")._value.get()
        assert sample == 1.0


# ── Legal-name guard ────────────────────────────────────────────────


class TestLegalNameGuard:
    def test_no_guard_fields_passes_through(self, tmp_path, _allowlist_allow):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": "broadcast_rotated", "id": "x"}])
        publisher = _make(tmp_path)
        publisher.run_once()
        assert publisher.send_calls == 1

    def test_guard_field_substitutes_referent(self, tmp_path, monkeypatch, _allowlist_allow):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [{"event_type": "broadcast_rotated", "id": "x", "vod_segment_id": "seg-1"}],
        )

        class _GuardedPublisher(_FakePublisher):
            LEGAL_NAME_GUARD_FIELDS = ("text",)

            def __init__(self, **kw):
                super().__init__(**kw)
                self.last_sent: _FakeComposed | None = None

            def send(self, composed):
                self.last_sent = composed
                return "ok"

        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "")
        publisher = _GuardedPublisher(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            registry=CollectorRegistry(),
            compose_text="hello {operator}",
        )
        publisher.run_once()
        assert publisher.last_sent is not None
        assert "{operator}" not in publisher.last_sent.text
