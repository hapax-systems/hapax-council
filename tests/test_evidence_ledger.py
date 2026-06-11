"""Tests for shared.evidence_ledger — ledger, trace graph, receipts, tier enforcement.

ISAP: SLICE-005-EVIDENCE-TRACE (CASE-SDLC-REFORM-001)
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from unittest.mock import Mock, patch

from shared.evidence_ledger import (
    EvidenceEntry,
    EvidenceLedger,
    LegibilityEvidenceRecord,
    LegibilityEvidenceRegistry,
    ReceiptEnvelope,
    TierComplianceResult,
    TraceGraph,
    TraceLink,
    check_tier_compliance,
    collect_command_evidence,
    collect_local_api_evidence,
    collect_package_registry_evidence,
    collect_public_url_evidence,
    collect_systemd_inventory_evidence,
)


def _entry(
    evidence_id: str = "EVD-001",
    case_id: str = "CASE-TEST",
    kind: str = "test",
    ts: float | None = None,
    ttl: float = 86400.0,
) -> EvidenceEntry:
    return EvidenceEntry(
        evidence_id=evidence_id,
        case_id=case_id,
        kind=kind,
        claim="test claim",
        producer="test",
        timestamp_utc=ts or time.time(),
        freshness_ttl_s=ttl,
    )


class TestEvidenceEntry:
    def test_fresh_when_recent(self) -> None:
        e = _entry(ts=time.time() - 100, ttl=86400)
        assert e.is_fresh()

    def test_stale_when_old(self) -> None:
        e = _entry(ts=time.time() - 200_000, ttl=86400)
        assert not e.is_fresh()

    def test_traces_to_field(self) -> None:
        e = _entry()
        e.traces_to = ["REQ-001", "NEED-002"]
        assert len(e.traces_to) == 2


class TestEvidenceLedger:
    def test_append_and_read(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path)
        e = _entry(case_id="CASE-A")
        ledger.append(e)
        entries = ledger.entries_for_case("CASE-A")
        assert len(entries) == 1
        assert entries[0].evidence_id == "EVD-001"

    def test_multiple_entries(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path)
        for i in range(5):
            ledger.append(_entry(evidence_id=f"EVD-{i}", case_id="CASE-B"))
        assert len(ledger.entries_for_case("CASE-B")) == 5

    def test_empty_case(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path)
        assert ledger.entries_for_case("CASE-NONE") == []

    def test_fresh_and_stale_split(self, tmp_path: Path) -> None:
        now = time.time()
        ledger = EvidenceLedger(tmp_path)
        ledger.append(_entry("EVD-F", "CASE-C", ts=now - 100, ttl=86400))
        ledger.append(_entry("EVD-S", "CASE-C", ts=now - 200_000, ttl=86400))
        assert len(ledger.fresh_entries("CASE-C", now)) == 1
        assert len(ledger.stale_entries("CASE-C", now)) == 1


class TestReceiptEnvelope:
    def test_append_and_read_receipt(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path)
        r = ReceiptEnvelope(
            receipt_id="RCP-001",
            case_id="CASE-D",
            stage="S7",
            action="pytest",
            outcome="pass",
            producer="delta",
        )
        ledger.append_receipt(r)
        receipts = ledger.receipts_for_case("CASE-D")
        assert len(receipts) == 1
        assert receipts[0].outcome == "pass"

    def test_filters_by_case(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path)
        ledger.append_receipt(
            ReceiptEnvelope(
                receipt_id="R1",
                case_id="CASE-X",
                stage="S7",
                action="test",
                outcome="pass",
                producer="t",
            )
        )
        ledger.append_receipt(
            ReceiptEnvelope(
                receipt_id="R2",
                case_id="CASE-Y",
                stage="S8",
                action="deploy",
                outcome="pass",
                producer="t",
            )
        )
        assert len(ledger.receipts_for_case("CASE-X")) == 1
        assert len(ledger.receipts_for_case("CASE-Y")) == 1


class TestTraceGraph:
    def test_add_and_query(self, tmp_path: Path) -> None:
        graph = TraceGraph(tmp_path)
        graph.add_link(TraceLink(source_id="REQ-001", target_id="EVD-001"))
        graph.add_link(TraceLink(source_id="REQ-001", target_id="EVD-002"))
        graph.add_link(TraceLink(source_id="REQ-002", target_id="EVD-003"))
        assert len(graph.links_from("REQ-001")) == 2
        assert len(graph.links_to("EVD-003")) == 1
        assert len(graph.all_links()) == 3

    def test_unlinked_requirements(self, tmp_path: Path) -> None:
        graph = TraceGraph(tmp_path)
        graph.add_link(TraceLink(source_id="REQ-001", target_id="EVD-001"))
        unlinked = graph.unlinked_requirements(["REQ-001", "REQ-002", "REQ-003"])
        assert unlinked == ["REQ-002", "REQ-003"]

    def test_empty_graph(self, tmp_path: Path) -> None:
        graph = TraceGraph(tmp_path)
        assert graph.all_links() == []
        assert graph.unlinked_requirements(["REQ-001"]) == ["REQ-001"]


class TestTierCompliance:
    def test_t0_compliant(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path)
        ledger.append(_entry("E1", "CASE-T0", kind="test"))
        ledger.append(_entry("E2", "CASE-T0", kind="ci"))
        result = check_tier_compliance("CASE-T0", "T0", ledger)
        assert result.compliant
        assert result.missing_kinds == set()

    def test_t0_missing_ci(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path)
        ledger.append(_entry("E1", "CASE-T0B", kind="test"))
        result = check_tier_compliance("CASE-T0B", "T0", ledger)
        assert not result.compliant
        assert "ci" in result.missing_kinds

    def test_t1_requires_readback(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path)
        ledger.append(_entry("E1", "CASE-T1", kind="test"))
        ledger.append(_entry("E2", "CASE-T1", kind="ci"))
        result = check_tier_compliance("CASE-T1", "T1", ledger)
        assert not result.compliant
        assert "readback" in result.missing_kinds

    def test_t2_requires_axiom_scan(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path)
        for kind in ("test", "ci", "readback", "review"):
            ledger.append(_entry(f"E-{kind}", "CASE-T2", kind=kind))
        result = check_tier_compliance("CASE-T2", "T2", ledger)
        assert not result.compliant
        assert "axiom_scan" in result.missing_kinds

    def test_t3_full_compliance(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path)
        for kind in ("test", "ci", "readback", "review", "axiom_scan", "assurance_argument"):
            ledger.append(_entry(f"E-{kind}", "CASE-T3", kind=kind))
        result = check_tier_compliance("CASE-T3", "T3", ledger)
        assert result.compliant

    def test_stale_evidence_not_counted(self, tmp_path: Path) -> None:
        now = time.time()
        ledger = EvidenceLedger(tmp_path)
        ledger.append(_entry("E1", "CASE-STALE", kind="test", ts=now - 200_000, ttl=86400))
        ledger.append(_entry("E2", "CASE-STALE", kind="ci", ts=now - 10, ttl=86400))
        result = check_tier_compliance("CASE-STALE", "T0", ledger, now=now)
        assert not result.compliant
        assert result.stale_count == 1

    def test_empty_case_non_compliant(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path)
        result = check_tier_compliance("CASE-EMPTY", "T0", ledger)
        assert not result.compliant

    def test_serialization_roundtrip(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path)
        ledger.append(_entry("E1", "CASE-RT", kind="test"))
        result = check_tier_compliance("CASE-RT", "T0", ledger)
        data = result.model_dump(mode="json")
        rt = TierComplianceResult.model_validate(data)
        assert rt.case_id == "CASE-RT"


class TestLegibilityEvidenceRecord:
    def test_freshness_uses_ttl(self) -> None:
        record = LegibilityEvidenceRecord(
            evidence_id="EV-1",
            kind="command",
            collected_at_epoch=100.0,
            value_summary="ok",
            freshness_ttl_s=10.0,
        )
        assert record.is_fresh(109.0)
        assert not record.is_fresh(111.0)

    def test_mirrors_to_tier_evidence_entry(self) -> None:
        record = LegibilityEvidenceRecord(
            evidence_id="EV-1",
            kind="public_url",
            source_url="https://example.test",
            value_summary="status=200",
            privacy_class="public",
            public_safe=True,
        )
        entry = record.to_evidence_entry(case_id="CASE-LEGIBILITY", traces_to=["REQ-1"])
        assert entry.case_id == "CASE-LEGIBILITY"
        assert entry.kind == "runtime_observation"
        assert entry.path_or_url == "https://example.test"
        assert entry.traces_to == ["REQ-1"]


class TestLegibilityEvidenceRegistry:
    def test_append_read_and_mirror(self, tmp_path: Path) -> None:
        registry = LegibilityEvidenceRegistry(tmp_path)
        record = LegibilityEvidenceRecord(
            evidence_id="EV-1",
            kind="command",
            value_summary="exit=0 stdout=ok",
        )
        registry.append(record, mirror_case_id="CASE-LEGIBILITY")

        records = registry.all_records()
        assert [r.evidence_id for r in records] == ["EV-1"]
        mirrored = EvidenceLedger(tmp_path).entries_for_case("CASE-LEGIBILITY")
        assert [entry.evidence_id for entry in mirrored] == ["EV-1"]

    def test_fresh_and_stale_records(self, tmp_path: Path) -> None:
        registry = LegibilityEvidenceRegistry(tmp_path)
        registry.append(
            LegibilityEvidenceRecord(
                evidence_id="EV-F",
                kind="command",
                value_summary="fresh",
                collected_at_epoch=100.0,
                freshness_ttl_s=20.0,
            )
        )
        registry.append(
            LegibilityEvidenceRecord(
                evidence_id="EV-S",
                kind="command",
                value_summary="stale",
                collected_at_epoch=50.0,
                freshness_ttl_s=20.0,
            )
        )
        assert [record.evidence_id for record in registry.fresh_records(110.0)] == ["EV-F"]
        assert [record.evidence_id for record in registry.stale_records(110.0)] == ["EV-S"]


class TestLegibilityCollectors:
    def test_command_success_redacts_secret_like_stdout(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["echo"],
            returncode=0,
            stdout="token=abc123\n",
            stderr="",
        )
        with patch("shared.evidence_ledger.subprocess.run", return_value=completed):
            record = collect_command_evidence(["echo", "token=abc123"])

        assert record.kind == "command"
        assert record.status == "ok"
        assert "token=[REDACTED]" in record.value_summary
        assert record.redaction_notes == "secret-like text redacted"

    def test_command_failure_is_structured_failure_evidence(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["false"],
            returncode=2,
            stdout="",
            stderr="bad",
        )
        with patch("shared.evidence_ledger.subprocess.run", return_value=completed):
            record = collect_command_evidence(["false"])

        assert record.kind == "collection_failure"
        assert record.status == "failed"
        assert record.error == "bad"
        assert record.failure_behavior == "fail_closed"

    def test_public_url_extracts_title(self) -> None:
        response = Mock()
        response.status = 200
        response.headers = {"content-type": "text/html"}
        response.read.return_value = b"<html><title>Example Page</title></html>"
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock(return_value=response)

        record = collect_public_url_evidence("https://example.test", opener=opener)

        assert record.kind == "public_url"
        assert record.privacy_class == "public"
        assert record.public_safe is True
        assert "title=Example Page" in record.value_summary

    def test_package_registry_extracts_version(self) -> None:
        response = Mock()
        response.status = 200
        response.headers = {"content-type": "application/json"}
        response.read.return_value = b'{"info": {"version": "1.2.3"}}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock(return_value=response)

        record = collect_package_registry_evidence("demo-package", opener=opener)

        assert record.kind == "package_registry"
        assert record.privacy_class == "public_registry"
        assert "version=1.2.3" in record.value_summary

    def test_local_api_is_not_public_safe(self) -> None:
        response = Mock()
        response.status = 200
        response.headers = {"content-type": "application/json"}
        response.read.return_value = b'{"healthy": true}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock(return_value=response)

        record = collect_local_api_evidence("http://127.0.0.1:8051/api/health", opener=opener)

        assert record.kind == "local_api"
        assert record.privacy_class == "local_private"
        assert record.public_safe is False
        assert 'body={"healthy": true}' in record.value_summary

    def test_systemd_inventory_counts_services_and_timers(self) -> None:
        service_files = subprocess.CompletedProcess(
            args=["systemctl"], returncode=0, stdout="a.service enabled\nc.service disabled\n"
        )
        timer_files = subprocess.CompletedProcess(
            args=["systemctl"], returncode=0, stdout="b.timer enabled\n"
        )
        active_timers = subprocess.CompletedProcess(
            args=["systemctl"], returncode=0, stdout="next left last passed b.timer b.service\n"
        )
        with patch(
            "shared.evidence_ledger.subprocess.run",
            side_effect=[service_files, timer_files, active_timers],
        ):
            record = collect_systemd_inventory_evidence()

        assert record.kind == "systemd_inventory"
        assert record.value_summary == (
            "user=True service_unit_file_count=2 timer_unit_file_count=1 active_timer_count=1"
        )
