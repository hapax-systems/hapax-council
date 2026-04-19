"""Tests for shared.audit_registry and shared.audit_dispatcher.

Scaffolding contract:

- Every ``AuditPoint`` defaults to ``enabled=False``.
- ``active_points()`` returns an empty list in the default registry.
- The registry carries at least three Gemini call-site entries.
- ``enqueue_audit`` is a no-op when the point is disabled.
- ``enqueue_audit`` writes a JSONL record when enabled.
- ``run_audit_cycle`` processes the queue without invoking any LLM.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from shared import audit_dispatcher
from shared.audit_registry import (
    AUDIT_POINTS,
    AuditPoint,
    active_points,
    by_auditor,
    by_severity_floor,
    get_by_id,
)

# --- Registry -------------------------------------------------------------


class TestAuditPointDefaults:
    def test_enabled_defaults_false(self) -> None:
        ap = AuditPoint(
            audit_id="test",
            provider="gemini-flash",
            call_site="x.py:1",
            purpose="test",
            auditor="claude-sonnet",
            severity_floor="low",
        )
        assert ap.enabled is False

    def test_sampling_rate_defaults_one(self) -> None:
        ap = AuditPoint(
            audit_id="test",
            provider="gemini-flash",
            call_site="x.py:1",
            purpose="test",
            auditor="claude-sonnet",
            severity_floor="low",
        )
        assert ap.sampling_rate == 1.0

    def test_dimensions_defaults_empty(self) -> None:
        ap = AuditPoint(
            audit_id="test",
            provider="gemini-flash",
            call_site="x.py:1",
            purpose="test",
            auditor="claude-sonnet",
            severity_floor="low",
        )
        assert ap.dimensions == ()

    def test_frozen_dataclass(self) -> None:
        ap = AuditPoint(
            audit_id="test",
            provider="gemini-flash",
            call_site="x.py:1",
            purpose="test",
            auditor="claude-sonnet",
            severity_floor="low",
        )
        with pytest.raises(Exception):
            ap.enabled = True  # type: ignore[misc]


class TestRegistrySeed:
    def test_registry_has_at_least_three_entries(self) -> None:
        assert len(AUDIT_POINTS) >= 3

    def test_every_entry_disabled_by_default(self) -> None:
        for point in AUDIT_POINTS:
            assert point.enabled is False, f"{point.audit_id} is enabled in scaffolding"

    def test_every_entry_has_gemini_provider(self) -> None:
        for point in AUDIT_POINTS:
            assert "gemini" in point.provider.lower(), (
                f"{point.audit_id} provider {point.provider!r} does not look like Gemini"
            )

    def test_audit_ids_unique(self) -> None:
        ids = [p.audit_id for p in AUDIT_POINTS]
        assert len(ids) == len(set(ids)), "duplicate audit_id in registry"

    def test_every_call_site_includes_line(self) -> None:
        for point in AUDIT_POINTS:
            assert ":" in point.call_site, (
                f"{point.audit_id} call_site {point.call_site!r} missing line number"
            )

    def test_enumerated_call_sites_present(self) -> None:
        required_ids = {
            "gemini-dmn-multimodal",
            "gemini-vision-tool",
            "gemini-workspace-analyzer",
            "gemini-daimonion-conversation",
            "gemini-live-session",
        }
        present = {p.audit_id for p in AUDIT_POINTS}
        missing = required_ids - present
        assert not missing, f"required audit points missing: {missing}"


# --- Query helpers --------------------------------------------------------


class TestRegistryQueries:
    def test_active_points_empty_when_all_disabled(self) -> None:
        assert active_points() == []

    def test_get_by_id_returns_point(self) -> None:
        point = get_by_id("gemini-dmn-multimodal")
        assert point is not None
        assert point.call_site.startswith("agents/dmn/ollama.py")

    def test_get_by_id_returns_none_for_unknown(self) -> None:
        assert get_by_id("does-not-exist") is None

    def test_by_auditor_includes_sonnet(self) -> None:
        sonnet = by_auditor("claude-sonnet")
        assert len(sonnet) >= 1
        assert all(p.auditor == "claude-sonnet" for p in sonnet)

    def test_by_severity_floor_includes_critical(self) -> None:
        critical = by_severity_floor("critical")
        assert len(critical) >= 1
        assert all(p.severity_floor == "critical" for p in critical)


# --- Dispatcher: no-op when disabled --------------------------------------


def _reset_counters() -> None:
    for counter in (
        audit_dispatcher._enqueued_total,
        audit_dispatcher._completed_total,
        audit_dispatcher._dropped_total,
    ):
        if counter is None:
            continue
        try:
            counter.clear()
        except AttributeError:
            pass


@pytest.fixture(autouse=True)
def _reroute_audit_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(audit_dispatcher, "AUDIT_QUEUE_PATH", tmp_path / "queue.jsonl")
    monkeypatch.setattr(audit_dispatcher, "AUDIT_FINDINGS_DIR", tmp_path / "findings")
    _reset_counters()
    yield
    _reset_counters()


class TestDispatcherDisabled:
    def test_enqueue_noop_when_disabled(self) -> None:
        point = get_by_id("gemini-dmn-multimodal")
        assert point is not None
        assert point.enabled is False

        audit_dispatcher.enqueue_audit(
            point,
            input_context={"prompt": "hi", "route": "test"},
            provider_output="irrelevant",
        )

        assert not audit_dispatcher.AUDIT_QUEUE_PATH.exists()

    def test_active_registry_empty_confirms_scaffolding(self) -> None:
        assert active_points() == []


class TestDispatcherEnabled:
    def test_enqueue_writes_record_when_enabled(self) -> None:
        enabled_point = AuditPoint(
            audit_id="gemini-test-enabled",
            provider="gemini-flash",
            call_site="x.py:1",
            purpose="test",
            auditor="claude-sonnet",
            severity_floor="medium",
            enabled=True,
        )

        audit_dispatcher.enqueue_audit(
            enabled_point,
            input_context={"prompt": "hello", "route": "test"},
            provider_output="mock output",
        )

        assert audit_dispatcher.AUDIT_QUEUE_PATH.exists()
        lines = audit_dispatcher.AUDIT_QUEUE_PATH.read_text().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["audit_id"] == "gemini-test-enabled"
        assert record["provider"] == "gemini-flash"
        assert record["auditor"] == "claude-sonnet"
        assert record["severity_floor"] == "medium"
        assert record["input_context"] == {"prompt": "hello", "route": "test"}
        assert record["provider_output"] == "mock output"

    def test_enqueue_appends_multiple_records(self) -> None:
        enabled_point = AuditPoint(
            audit_id="gemini-test-multi",
            provider="gemini-flash",
            call_site="x.py:1",
            purpose="test",
            auditor="claude-sonnet",
            severity_floor="low",
            enabled=True,
        )
        for i in range(3):
            audit_dispatcher.enqueue_audit(
                enabled_point,
                input_context={"index": i},
                provider_output=f"out-{i}",
            )

        lines = audit_dispatcher.AUDIT_QUEUE_PATH.read_text().splitlines()
        assert len(lines) == 3

    def test_enqueue_respects_backpressure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(audit_dispatcher, "AUDIT_QUEUE_MAX_DEPTH", 2)
        enabled_point = AuditPoint(
            audit_id="gemini-test-backpressure",
            provider="gemini-flash",
            call_site="x.py:1",
            purpose="test",
            auditor="claude-sonnet",
            severity_floor="low",
            enabled=True,
        )
        for i in range(5):
            audit_dispatcher.enqueue_audit(
                enabled_point,
                input_context={"index": i},
                provider_output=f"out-{i}",
            )

        lines = audit_dispatcher.AUDIT_QUEUE_PATH.read_text().splitlines()
        assert len(lines) == 2


class TestRunAuditCycle:
    def test_cycle_returns_zero_on_empty_queue(self) -> None:
        processed = asyncio.run(audit_dispatcher.run_audit_cycle())
        assert processed == 0

    def test_cycle_processes_enqueued_records_without_llm(self) -> None:
        enabled_point = AuditPoint(
            audit_id="gemini-cycle-test",
            provider="gemini-flash",
            call_site="x.py:1",
            purpose="test",
            auditor="claude-sonnet",
            severity_floor="medium",
            enabled=True,
        )
        audit_dispatcher.enqueue_audit(
            enabled_point,
            input_context={"k": "v"},
            provider_output="abc",
        )

        processed = asyncio.run(audit_dispatcher.run_audit_cycle())
        assert processed == 1

        assert (
            not audit_dispatcher.AUDIT_QUEUE_PATH.exists()
            or audit_dispatcher.AUDIT_QUEUE_PATH.read_text() == ""
        )

        findings = list(audit_dispatcher.AUDIT_FINDINGS_DIR.glob("*.md"))
        assert len(findings) == 1
        body = findings[0].read_text()
        assert "Placeholder finding" in body
        assert "gemini-cycle-test" in body
