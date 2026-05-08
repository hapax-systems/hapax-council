"""Tests for shared.evidence_ledger — ledger, trace graph, receipts, tier enforcement.

ISAP: SLICE-005-EVIDENCE-TRACE (CASE-SDLC-REFORM-001)
"""

from __future__ import annotations

import time
from pathlib import Path

from shared.evidence_ledger import (
    EvidenceEntry,
    EvidenceLedger,
    ReceiptEnvelope,
    TierComplianceResult,
    TraceGraph,
    TraceLink,
    check_tier_compliance,
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
