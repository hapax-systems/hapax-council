import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (
    ROOT
    / "docs/research/evidence/2026-05-20-epistemic-quality-phase0-artifact-disposition-receipts.json"
)


def test_artifact_receipt_records_have_required_fields() -> None:
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    records = data["artifact_records"]
    required = {
        "artifact_id",
        "kind",
        "canonical_path",
        "privacy_class",
        "source_refs",
        "request_backlink",
        "task_backlinks",
        "disposition",
        "freshness",
        "authority_ceiling",
        "sha256",
    }

    assert len(records) >= 12
    for record in records:
        assert required <= set(record), record["artifact_id"]
        assert record["privacy_class"]
        assert record["source_refs"], record["artifact_id"]
        assert record["task_backlinks"], record["artifact_id"]
        assert record["disposition"]
        assert record["authority_ceiling"]
        assert re.fullmatch(r"[a-f0-9]{64}", record["sha256"]), record["artifact_id"]
        assert record["freshness"]["observed_at"].endswith("Z"), record["artifact_id"]
        assert record["freshness"]["stale_when"], record["artifact_id"]


def test_failed_phase0_predicates_and_consumer_denials_are_explicit() -> None:
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    predicates = data["phase0_predicates"]

    assert predicates["phase0_hard_gate_passed"] is False
    assert predicates["labels_complete"] is False
    assert predicates["scores_complete"] is False
    assert predicates["reliability_gate_passed"] is False

    blockers = {blocker["predicate"]: blocker for blocker in data["blocking_predicates"]}
    assert blockers["labels_complete"]["value"] is False
    assert blockers["scores_complete"]["value"] is False
    assert blockers["reliability_gate_passed"]["value"] is False
    assert "blocker" in blockers["scores_complete"]

    denials = data["consumer_authority_denials"]
    assert denials["publication"]["authority_granted"] is False
    assert denials["token_capital"]["authority_granted"] is False
    assert denials["publication"]["denied_authority"]
    assert denials["token_capital"]["denied_authority"]
