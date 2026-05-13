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


def _phase0_fixture_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    global_index = 0
    domains = ["scientific", "technical", "narrative", "mixed"]
    for tier, count in eqd.TIER_COUNTS.items():
        for tier_index in range(1, count + 1):
            global_index += 1
            record_id = f"eqi-v0-{tier}-{tier_index:03d}"
            if tier == "D":
                source_ref = f"synthetic:eqi-known-bad:{tier_index:03d}"
            else:
                source_ref = f"fixture:{tier}:{tier_index:03d}"
            excerpt = (
                f"Fixture {record_id} contains a scoped calibration claim with evidence context, "
                f"domain variation, and source grounding. It is long enough to behave like a "
                f"real manifest row without using private source material."
            )
            records.append(
                {
                    "id": record_id,
                    "tier": tier,
                    "tier_description": eqd.TIER_DESCRIPTIONS[tier],
                    "source_kind": "fixture",
                    "source_ref": source_ref,
                    "privacy_class": "public_synthetic",
                    "authority_ceiling": "candidate_unlabeled_not_public_authority",
                    "domain_partition": domains[global_index % len(domains)],
                    "text_status": "ready",
                    "excerpt": excerpt,
                    "excerpt_hash": eqd.excerpt_hash(excerpt),
                    "label_status": "unlabeled",
                    "labels": {},
                    "relabel_required": False,
                }
            )
    eqd.assign_relabel_subset(records)
    return records


def _axis_values(record: dict[str, object]) -> dict[str, int]:
    tier = str(record["tier"])
    source_ref = str(record["source_ref"])
    if tier == "D" and source_ref.startswith("synthetic:eqi-known-bad:"):
        index = int(source_ref.rsplit(":", 1)[-1])
        if 36 <= index <= 45:
            return {axis: 1 for axis in eqd.AXES}
    numeric = int(str(record["id"]).rsplit("-", 1)[-1])
    return {axis: ((numeric + offset - 1) % 5) + 1 for offset, axis in enumerate(eqd.AXES, start=1)}


def _label_rows(
    records: list[dict[str, object]],
    manifest_hash: str,
    *,
    label_round: str = eqd.ROUND_ONE_LABEL_ROUND,
    relabel_only: bool = False,
    days_after_round1: int = 0,
    label_origin: str = "operator",
) -> list[dict[str, object]]:
    labeled_at = f"2026-05-{13 + days_after_round1:02d}T05:00:00Z"
    selected = [
        record for record in records if not relabel_only or record.get("relabel_required") is True
    ]
    return [
        {
            "manifest_id": record["id"],
            "manifest_hash": manifest_hash,
            "source_ref": record["source_ref"],
            "source_text_hash": record["excerpt_hash"],
            "label_round": label_round,
            "labeler": "operator",
            "label_origin": label_origin,
            "labeled_at": labeled_at,
            "provenance": f"fixture-{label_round}",
            "labels": _axis_values(record),
        }
        for record in selected
    ]


def _score_rows(
    records: list[dict[str, object]], manifest_hash: str, *, vacuous_score: float = 1.0
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in records:
        axis_scores = {axis: float(value) for axis, value in _axis_values(record).items()}
        source_ref = str(record["source_ref"])
        if source_ref.startswith("synthetic:eqi-known-bad:"):
            index = int(source_ref.rsplit(":", 1)[-1])
            if 36 <= index <= 45:
                axis_scores = {axis: vacuous_score for axis in eqd.AXES}
        rows.append(
            {
                "manifest_id": record["id"],
                "manifest_hash": manifest_hash,
                "source_text_hash": record["excerpt_hash"],
                "scorer": "fixture-scorer",
                "scored_at": "2026-05-13T05:05:00Z",
                "axis_scores": axis_scores,
            }
        )
    return rows


def _write_gate_inputs(
    tmp_path: Path,
    *,
    include_relabel: bool = True,
    drop_label: bool = False,
    label_origin: str = "operator",
    vacuous_score: float = 1.0,
) -> tuple[Path, Path, Path, Path | None, Path, Path]:
    records = _phase0_fixture_records()
    manifest = tmp_path / "manifest.jsonl"
    eqd.write_jsonl(manifest, records)
    manifest_hash = eqd.file_sha256(manifest)
    labels = _label_rows(records, manifest_hash, label_origin=label_origin)
    if drop_label:
        labels = labels[:-1]
    label_path = tmp_path / "labels.jsonl"
    eqd.write_jsonl(label_path, labels)
    score_path = tmp_path / "scores.jsonl"
    eqd.write_jsonl(score_path, _score_rows(records, manifest_hash, vacuous_score=vacuous_score))
    relabel_path = None
    if include_relabel:
        relabel_path = tmp_path / "relabels.jsonl"
        eqd.write_jsonl(
            relabel_path,
            _label_rows(
                records,
                manifest_hash,
                label_round=eqd.RELABEL_LABEL_ROUND,
                relabel_only=True,
                days_after_round1=8,
            ),
        )
    report_json = tmp_path / "report.json"
    report_md = tmp_path / "report.md"
    return manifest, label_path, score_path, relabel_path, report_json, report_md


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


def test_validate_gate_passes_with_human_labels_scores_and_relabels(tmp_path: Path) -> None:
    manifest, labels, scores, relabels, report_json, report_md = _write_gate_inputs(tmp_path)
    assert relabels is not None

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate-gate",
            "--manifest",
            str(manifest),
            "--labels",
            str(labels),
            "--scores",
            str(scores),
            "--relabel-labels",
            str(relabels),
            "--report-json",
            str(report_json),
            "--report-md",
            str(report_md),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["status"] == eqd.PHASE0_PASS_STATUS
    assert report["predicates"]["phase0_hard_gate_passed"] is True
    assert report["predicates"]["relabel_kappa_ge_0_75"] is True
    assert "Phase 0 Validation Gate Report" in report_md.read_text(encoding="utf-8")


def test_validate_gate_reports_relabel_pending_without_relabel_artifact(tmp_path: Path) -> None:
    manifest, labels, scores, relabels, report_json, report_md = _write_gate_inputs(
        tmp_path, include_relabel=False
    )
    assert relabels is None

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate-gate",
            "--manifest",
            str(manifest),
            "--labels",
            str(labels),
            "--scores",
            str(scores),
            "--report-json",
            str(report_json),
            "--report-md",
            str(report_md),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["status"] == "relabel_pending"
    assert report["predicates"]["phase0_hard_gate_passed"] is False


def test_validate_gate_rejects_missing_label_rows(tmp_path: Path) -> None:
    manifest, labels, scores, relabels, report_json, report_md = _write_gate_inputs(
        tmp_path, drop_label=True
    )
    assert relabels is not None

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate-gate",
            "--manifest",
            str(manifest),
            "--labels",
            str(labels),
            "--scores",
            str(scores),
            "--relabel-labels",
            str(relabels),
            "--report-json",
            str(report_json),
            "--report-md",
            str(report_md),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["status"] == "not_enough_labels"
    assert any(
        "missing round1 label rows" in error for error in report["label_validation"]["errors"]
    )


def test_validate_gate_rejects_model_generated_ground_truth(tmp_path: Path) -> None:
    manifest, labels, scores, relabels, report_json, report_md = _write_gate_inputs(
        tmp_path, label_origin="model"
    )
    assert relabels is not None

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate-gate",
            "--manifest",
            str(manifest),
            "--labels",
            str(labels),
            "--scores",
            str(scores),
            "--relabel-labels",
            str(relabels),
            "--report-json",
            str(report_json),
            "--report-md",
            str(report_md),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["status"] == "not_enough_labels"
    assert any(
        "model-generated labels are not ground truth" in error
        for error in report["label_validation"]["errors"]
    )


def test_validate_gate_fails_vacuous_hedging_adversary(tmp_path: Path) -> None:
    manifest, labels, scores, relabels, report_json, report_md = _write_gate_inputs(
        tmp_path, vacuous_score=5.0
    )
    assert relabels is not None

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate-gate",
            "--manifest",
            str(manifest),
            "--labels",
            str(labels),
            "--scores",
            str(scores),
            "--relabel-labels",
            str(relabels),
            "--report-json",
            str(report_json),
            "--report-md",
            str(report_md),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["status"] == "labels_present_gate_failed"
    assert report["predicates"]["vacuous_hedging_not_above_tier_a_median"] is False
