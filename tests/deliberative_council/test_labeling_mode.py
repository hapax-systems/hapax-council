"""Tests for Mode A council labeling — no live API calls."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agents.deliberative_council.models import (
    ConvergenceStatus,
    CouncilVerdict,
)
from agents.deliberative_council.modes.labeling import (
    AXES,
    LABEL_ORIGIN_RATIFIED,
    run_labeling,
    run_ratification,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_AXES_SCORES = {ax: 3 for ax in AXES}

_CONVERGED_VERDICT = CouncilVerdict(
    scores=_AXES_SCORES,
    confidence_bands={ax: (2, 4) for ax in AXES},
    convergence_status=ConvergenceStatus.CONVERGED,
    disagreement_log=[],
    research_findings=[],
    evidence_matrix=None,
    receipt={
        "shortcircuited": True,
        "models_used": ["opus", "balanced"],
        "phases_completed": [1],
    },
)

_CONTESTED_VERDICT = CouncilVerdict(
    scores={ax: (3 if ax != "hedge_calibration" else 1) for ax in AXES},
    confidence_bands={ax: (1, 5) for ax in AXES},
    convergence_status=ConvergenceStatus.CONTESTED,
    disagreement_log=["hedge_calibration: IQR=2.5 values=[1, 3, 5]"],
    research_findings=[],
    evidence_matrix=None,
    receipt={"shortcircuited": False, "models_used": ["opus"], "phases_completed": [1, 2, 3, 4, 5]},
)

_HUNG_VERDICT = CouncilVerdict(
    scores={},
    confidence_bands={},
    convergence_status=ConvergenceStatus.HUNG,
    disagreement_log=["All models failed in Phase 1"],
    research_findings=[],
    evidence_matrix=None,
    receipt={"error": "all_models_failed"},
)


def _make_manifest(tmp: Path, records: list[dict] | None = None) -> Path:
    if records is None:
        records = [
            {
                "id": "eqi-v0-A-001",
                "source_ref": "council:docs/test.md:1",
                "excerpt": "The system showed consistent improvement.",
                "excerpt_hash": hashlib.sha256(
                    b"The system showed consistent improvement."
                ).hexdigest(),
            },
            {
                "id": "eqi-v0-A-002",
                "source_ref": "council:docs/test.md:2",
                "excerpt": "Results were inconclusive and require further study.",
                "excerpt_hash": hashlib.sha256(
                    b"Results were inconclusive and require further study."
                ).hexdigest(),
            },
        ]
    p = tmp / "manifest.json"
    p.write_text(json.dumps(records))
    return p


# ---------------------------------------------------------------------------
# test_labeling_output_format_matches_gate
# ---------------------------------------------------------------------------


def test_labeling_output_format_matches_gate(tmp_path: Path) -> None:
    """Every ratified label row must pass validate_label_rows from epistemic_quality_dataset."""
    from scripts.epistemic_quality_dataset import validate_label_rows

    manifest_path = _make_manifest(tmp_path)
    output_path = tmp_path / "labels.json"
    review_path = tmp_path / "review.json"

    records = json.loads(manifest_path.read_text())
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    import asyncio

    with patch(
        "agents.deliberative_council.modes.labeling.deliberate",
        new=AsyncMock(return_value=_CONVERGED_VERDICT),
    ):
        label_rows, _ = asyncio.run(
            run_labeling(manifest_path, output_path, review_queue_path=review_path)
        )

    assert len(label_rows) == 2

    expected_ids = {r["id"] for r in records}
    errors, valid_by_id = validate_label_rows(
        records,
        label_rows,
        manifest_hash=manifest_hash,
        expected_ids=expected_ids,
        expected_round="round1",
    )
    assert errors == [], f"Gate validation errors: {errors}"
    assert len(valid_by_id) == 2


# ---------------------------------------------------------------------------
# test_labeling_origin_is_deliberative_council_ratified
# ---------------------------------------------------------------------------


def test_labeling_origin_is_deliberative_council_ratified(tmp_path: Path) -> None:
    """Converged records must have label_origin == 'deliberative_council_ratified'."""
    import asyncio

    manifest_path = _make_manifest(tmp_path)
    output_path = tmp_path / "labels.json"

    with patch(
        "agents.deliberative_council.modes.labeling.deliberate",
        new=AsyncMock(return_value=_CONVERGED_VERDICT),
    ):
        label_rows, review_rows = asyncio.run(run_labeling(manifest_path, output_path))

    assert all(row["label_origin"] == LABEL_ORIGIN_RATIFIED for row in label_rows)
    assert review_rows == []


# ---------------------------------------------------------------------------
# test_contested_records_flagged_for_operator
# ---------------------------------------------------------------------------


def test_contested_records_flagged_for_operator(tmp_path: Path) -> None:
    """CONTESTED verdicts must land in the review queue, not in label output."""
    import asyncio

    manifest_path = _make_manifest(tmp_path)
    output_path = tmp_path / "labels.json"
    review_path = tmp_path / "review.json"

    with patch(
        "agents.deliberative_council.modes.labeling.deliberate",
        new=AsyncMock(return_value=_CONTESTED_VERDICT),
    ):
        label_rows, review_rows = asyncio.run(
            run_labeling(manifest_path, output_path, review_queue_path=review_path)
        )

    assert label_rows == []
    assert len(review_rows) == 2
    for row in review_rows:
        assert row["convergence_status"] == ConvergenceStatus.CONTESTED
        assert row["disagreement_log"]
        assert "manifest_id" in row
        assert "receipt" in row


# ---------------------------------------------------------------------------
# test_hung_records_require_operator_adjudication
# ---------------------------------------------------------------------------


def test_hung_records_require_operator_adjudication(tmp_path: Path) -> None:
    """HUNG verdicts must go to review queue and never appear in label output."""
    import asyncio

    manifest_path = _make_manifest(tmp_path)
    output_path = tmp_path / "labels.json"
    review_path = tmp_path / "review.json"

    with patch(
        "agents.deliberative_council.modes.labeling.deliberate",
        new=AsyncMock(return_value=_HUNG_VERDICT),
    ):
        label_rows, review_rows = asyncio.run(
            run_labeling(manifest_path, output_path, review_queue_path=review_path)
        )

    assert label_rows == []
    assert len(review_rows) == 2
    for row in review_rows:
        assert row["convergence_status"] == ConvergenceStatus.HUNG


# ---------------------------------------------------------------------------
# test_ratification_produces_valid_label_rows
# ---------------------------------------------------------------------------


def test_ratification_produces_valid_label_rows(tmp_path: Path) -> None:
    """run_ratification must emit label rows with label_origin=deliberative_council_ratified."""
    import asyncio

    from scripts.epistemic_quality_dataset import validate_label_rows

    manifest_path = _make_manifest(tmp_path)
    output_path = tmp_path / "labels.json"
    review_path = tmp_path / "review.json"

    # First produce review rows (all hung)
    with patch(
        "agents.deliberative_council.modes.labeling.deliberate",
        new=AsyncMock(return_value=_HUNG_VERDICT),
    ):
        asyncio.run(run_labeling(manifest_path, output_path, review_queue_path=review_path))

    # Operator writes ratification rows
    ratification_rows = [
        {
            "manifest_id": "eqi-v0-A-001",
            "labels": {ax: 3 for ax in AXES},
            "rationale": "Operator reviewed evidence, assigned scores.",
        },
        {
            "manifest_id": "eqi-v0-A-002",
            "labels": {ax: 2 for ax in AXES},
            "rationale": "Inconclusive — scored conservatively.",
        },
    ]
    rat_path = tmp_path / "ratification.json"
    rat_path.write_text(json.dumps(ratification_rows))

    final_output = tmp_path / "final_labels.json"
    ratified = run_ratification(
        review_queue_path=review_path,
        ratification_path=rat_path,
        output_path=final_output,
        manifest_path=manifest_path,
    )

    assert len(ratified) == 2
    assert all(r["label_origin"] == LABEL_ORIGIN_RATIFIED for r in ratified)

    records = json.loads(manifest_path.read_text())
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    expected_ids = {r["id"] for r in records}
    errors, valid_by_id = validate_label_rows(
        records,
        ratified,
        manifest_hash=manifest_hash,
        expected_ids=expected_ids,
        expected_round="round1",
    )
    assert errors == [], f"Gate validation errors on ratified rows: {errors}"
    assert len(valid_by_id) == 2
