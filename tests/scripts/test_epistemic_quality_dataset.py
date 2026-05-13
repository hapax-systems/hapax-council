from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import scripts.epistemic_quality_dataset as eqd

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "epistemic_quality_dataset.py"


def _write_blocks(path: Path, count: int, prefix: str) -> None:
    blocks = [
        (
            f"{prefix} block {idx} records a scoped claim with enough detail for calibration "
            f"testing. It includes evidence language, limits, and a concrete source relation "
            f"without credentials or private operational payloads."
        )
        for idx in range(count)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(blocks), encoding="utf-8")


def test_build_and_validate_manifest_from_fixture_roots(tmp_path: Path) -> None:
    research_root = tmp_path / "research"
    tasks_root = tmp_path / "tasks"
    _write_blocks(research_root / "weblog" / "operator.md", 60, "operator")
    _write_blocks(tasks_root / "active" / "task.md", 80, "agent")

    manifest = tmp_path / "manifest.jsonl"
    labeling_pack = tmp_path / "labeling.md"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "build",
            "--research-root",
            str(research_root),
            "--cc-task-root",
            str(tasks_root),
            "--output",
            str(manifest),
            "--labeling-pack",
            str(labeling_pack),
            "--allow-internal-autoselect",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    records = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 200
    assert sum(1 for record in records if record["tier"] == "A") == 50
    assert sum(1 for record in records if record["tier"] == "B") == 30
    assert sum(1 for record in records if record["tier"] == "C") == 70
    assert sum(1 for record in records if record["tier"] == "D") == 50
    assert sum(1 for record in records if record["relabel_required"]) == 40
    assert sum(1 for record in records if record["text_status"] == "external_source_required") == 30
    assert all(record["text_status"] == "ready" for record in records if record["relabel_required"])
    labeling_text = labeling_pack.read_text(encoding="utf-8")
    assert "Labeling Examples And Non-Examples" in labeling_text
    assert "Authority Ceiling" in labeling_text


def test_default_build_uses_source_review_slots(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "build",
            "--output",
            str(manifest),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    records = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 200
    assert sum(1 for record in records if record["text_status"] == "operator_source_required") == 50
    assert sum(1 for record in records if record["text_status"] == "external_source_required") == 30
    assert (
        sum(1 for record in records if record["text_status"] == "agent_source_review_required")
        == 70
    )
    assert sum(1 for record in records if record["text_status"] == "ready") == 50
    assert all(record["tier"] == "D" for record in records if record["relabel_required"])


def test_validate_rejects_duplicate_excerpt_hash(tmp_path: Path) -> None:
    records = eqd.synthetic_bad_records(2)
    records[1]["excerpt_hash"] = records[0]["excerpt_hash"]
    manifest = tmp_path / "manifest.jsonl"
    eqd.write_jsonl(manifest, records)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate",
            str(manifest),
            "--tier-count",
            "A=0",
            "--tier-count",
            "B=0",
            "--tier-count",
            "C=0",
            "--tier-count",
            "D=2",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "duplicate excerpt_hash" in result.stdout


def test_validate_rejects_premature_complete_labels(tmp_path: Path) -> None:
    records = eqd.synthetic_bad_records(1)
    records[0]["label_status"] = "complete"
    records[0]["labels"] = {"claim_evidence_alignment": 5}
    manifest = tmp_path / "manifest.jsonl"
    eqd.write_jsonl(manifest, records)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate",
            str(manifest),
            "--tier-count",
            "A=0",
            "--tier-count",
            "B=0",
            "--tier-count",
            "C=0",
            "--tier-count",
            "D=1",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "label_status complete without all axes" in result.stdout


def test_validate_rejects_unknown_label_axis(tmp_path: Path) -> None:
    records = eqd.synthetic_bad_records(1)
    records[0]["labels"] = {"invented_axis": 3}
    manifest = tmp_path / "manifest.jsonl"
    eqd.write_jsonl(manifest, records)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate",
            str(manifest),
            "--tier-count",
            "A=0",
            "--tier-count",
            "B=0",
            "--tier-count",
            "C=0",
            "--tier-count",
            "D=1",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "schema labels" in result.stdout
    assert "invented_axis" in result.stdout


def test_validate_rejects_hash_mismatch(tmp_path: Path) -> None:
    records = eqd.synthetic_bad_records(1)
    records[0]["excerpt"] = "changed excerpt text after hashing"
    manifest = tmp_path / "manifest.jsonl"
    eqd.write_jsonl(manifest, records)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate",
            str(manifest),
            "--tier-count",
            "A=0",
            "--tier-count",
            "B=0",
            "--tier-count",
            "C=0",
            "--tier-count",
            "D=1",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "excerpt_hash does not match excerpt" in result.stdout


def test_validate_rejects_relabel_on_blocked_record(tmp_path: Path) -> None:
    records = eqd.source_slot_records(
        tier="A",
        count=1,
        source_kind="operator_analysis_source_slot",
        source_ref_prefix="operator-analysis-source-slot",
        text_status="operator_source_required",
        slot_label="Tier A operator analysis source slot",
        blocker_reason="operator-authored analysis must be confirmed",
    )
    records[0]["relabel_required"] = True
    manifest = tmp_path / "manifest.jsonl"
    eqd.write_jsonl(manifest, records)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate",
            str(manifest),
            "--tier-count",
            "A=1",
            "--tier-count",
            "B=0",
            "--tier-count",
            "C=0",
            "--tier-count",
            "D=0",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "relabel_required set on non-ready record" in result.stdout


def test_secret_like_blocks_are_not_selected(tmp_path: Path) -> None:
    doc = tmp_path / "secret.md"
    doc.write_text(
        "This block contains api_key and must be filtered even though it is long enough "
        "to otherwise appear in the dataset candidate ledger.\n\n"
        "This second block is safe and has enough detail to be accepted as a candidate "
        "without exposing credentials, tokens, passwords, or private operational payloads.",
        encoding="utf-8",
    )

    blocks = eqd.iter_markdown_blocks(doc)

    assert len(blocks) == 1
    assert "second block" in blocks[0][1]


def test_curate_builds_ready_manifest_and_source_notes(tmp_path: Path) -> None:
    research_root = tmp_path / "research"
    _write_blocks(
        research_root / "weblog" / "2026-05-07-grounded-agent-communication-lab-journal.md",
        30,
        "operator-public-a",
    )
    _write_blocks(
        research_root
        / "weblog"
        / "2026-05-08-formal-method-value-braid-operator-surfaces-lab-journal-part-1.md",
        30,
        "operator-public-b",
    )
    _write_blocks(
        research_root / "audit" / "2026-05-12-full-corpus-hardening-audit.md",
        80,
        "agent-audit",
    )

    manifest = tmp_path / "curated.jsonl"
    source_notes = tmp_path / "source-notes.jsonl"
    labeling_pack = tmp_path / "labeling.md"
    report = tmp_path / "report.md"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "curate",
            "--research-root",
            str(research_root),
            "--output",
            str(manifest),
            "--source-notes",
            str(source_notes),
            "--labeling-pack",
            str(labeling_pack),
            "--curation-report",
            str(report),
            "--curated-at",
            "2026-05-13T03:52:50Z",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    records = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    notes = [json.loads(line) for line in source_notes.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 200
    assert len(notes) == 200
    assert sum(1 for record in records if record["tier"] == "A") == 50
    assert sum(1 for record in records if record["tier"] == "B") == 30
    assert sum(1 for record in records if record["tier"] == "C") == 70
    assert sum(1 for record in records if record["tier"] == "D") == 50
    assert all(record["text_status"] == "ready" for record in records)
    assert sum(1 for record in records if record["relabel_required"]) == 40
    assert {record["tier"] for record in records if record["relabel_required"]} == {
        "A",
        "B",
        "C",
        "D",
    }
    assert all(note["curation_status"] == "ready" for note in notes)
    assert "does not pass the Phase 0 hard gate" in report.read_text(encoding="utf-8")


def test_source_note_validation_rejects_local_path() -> None:
    records = eqd.synthetic_bad_records(1)
    notes = [
        {
            "manifest_id": records[0]["id"],
            "tier": records[0]["tier"],
            "source_ref": records[0]["source_ref"],
            "excerpt_or_note_hash": records[0]["excerpt_hash"],
            "privacy_class": records[0]["privacy_class"],
            "authorship_status": "synthetic_fixture",
            "rights_status": "synthetic_owned",
            "curation_status": "ready",
            "curator": "codex",
            "curated_at": "2026-05-13T03:52:50Z",
            "blocker_reason": None,
            "manual_privacy_note": "leaks /home/hapax/private/path",
            "source_role": "known_bad_or_adversarial_fixture",
            "authority_ceiling": records[0]["authority_ceiling"],
        }
    ]

    errors = eqd.validate_source_notes(records, notes)

    assert any("local_path" in error for error in errors)
