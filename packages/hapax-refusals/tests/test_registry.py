"""RefusalEvent / RefusalRegistry tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from hapax_refusals.registry import (
    REASON_MAX_CHARS,
    RefusalEvent,
    RefusalRegistry,
)


def _event(reason: str = "test reason") -> RefusalEvent:
    return RefusalEvent(
        timestamp=datetime(2026, 4, 25, 12, 0, 0, tzinfo=UTC),
        axiom="claim_below_floor",
        surface="refusal_gate:director",
        reason=reason,
    )


class TestRefusalEvent:
    def test_constructs_with_required_fields(self) -> None:
        e = _event()
        assert e.axiom == "claim_below_floor"
        assert e.public is False
        assert e.refusal_brief_link is None

    def test_reason_max_length_enforced(self) -> None:
        too_long = "x" * (REASON_MAX_CHARS + 1)
        with pytest.raises(ValidationError):
            RefusalEvent(
                timestamp=datetime.now(UTC),
                axiom="a",
                surface="s",
                reason=too_long,
            )

    def test_reason_at_cap_accepted(self) -> None:
        at_cap = "x" * REASON_MAX_CHARS
        e = RefusalEvent(
            timestamp=datetime.now(UTC),
            axiom="a",
            surface="s",
            reason=at_cap,
        )
        assert len(e.reason) == REASON_MAX_CHARS

    def test_empty_axiom_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RefusalEvent(
                timestamp=datetime.now(UTC),
                axiom="",
                surface="s",
                reason="r",
            )

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RefusalEvent(  # type: ignore[call-arg]
                timestamp=datetime.now(UTC),
                axiom="a",
                surface="s",
                reason="r",
                extra="boom",
            )

    def test_frozen(self) -> None:
        e = _event()
        with pytest.raises(ValidationError):
            e.public = True  # type: ignore[misc]


class TestRefusalRegistry:
    def test_writes_one_jsonl_line(self, tmp_path: Path) -> None:
        log = tmp_path / "log.jsonl"
        reg = RefusalRegistry(log_path=log)
        ok = reg.append(_event("test reason"))
        assert ok is True
        lines = log.read_text().strip().splitlines()
        assert len(lines) == 1
        decoded = json.loads(lines[0])
        assert decoded["axiom"] == "claim_below_floor"
        assert decoded["surface"] == "refusal_gate:director"
        assert decoded["reason"] == "test reason"

    def test_appends_multiple_events(self, tmp_path: Path) -> None:
        log = tmp_path / "log.jsonl"
        reg = RefusalRegistry(log_path=log)
        for i in range(5):
            assert reg.append(_event(f"reason-{i}")) is True
        lines = log.read_text().strip().splitlines()
        assert len(lines) == 5

    def test_creates_parent_dir(self, tmp_path: Path) -> None:
        log = tmp_path / "deeper" / "still" / "log.jsonl"
        reg = RefusalRegistry(log_path=log)
        assert reg.append(_event()) is True
        assert log.exists()

    def test_log_path_property(self, tmp_path: Path) -> None:
        log = tmp_path / "log.jsonl"
        reg = RefusalRegistry(log_path=log)
        assert reg.log_path == log

    def test_default_path_uses_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        custom = tmp_path / "env.jsonl"
        monkeypatch.setenv("HAPAX_REFUSALS_LOG_PATH", str(custom))
        reg = RefusalRegistry()
        assert reg.log_path == custom

    def test_oserror_returns_false_not_raises(self, tmp_path: Path) -> None:
        # Create a directory where the log file should be — open() will fail.
        log = tmp_path / "log.jsonl"
        log.mkdir()
        reg = RefusalRegistry(log_path=log)
        assert reg.append(_event()) is False

    def test_thread_safe_appends(self, tmp_path: Path) -> None:
        """Concurrent appends from multiple threads never interleave bytes."""
        import threading

        log = tmp_path / "log.jsonl"
        reg = RefusalRegistry(log_path=log)
        errors: list[Exception] = []
        n_threads = 8
        n_events_per_thread = 25

        def worker(tid: int) -> None:
            try:
                for i in range(n_events_per_thread):
                    reg.append(_event(f"t{tid}-e{i}"))
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        lines = log.read_text().strip().splitlines()
        assert len(lines) == n_threads * n_events_per_thread
        for line in lines:
            json.loads(line)  # every line is a complete JSON object
