"""Mode A: deliberative council labeling over an EQI-manifest dataset."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.deliberative_council.engine import deliberate
from agents.deliberative_council.models import (
    ConvergenceStatus,
    CouncilConfig,
    CouncilInput,
    CouncilMode,
    CouncilVerdict,
)
from agents.deliberative_council.rubrics import EpistemicQualityRubric

_log = logging.getLogger(__name__)

LABEL_ORIGIN_RATIFIED = "deliberative_council_ratified"
REVIEW_QUEUE_LABEL_ORIGIN = "deliberative_council_review_pending"

AXES = (
    "claim_evidence_alignment",
    "hedge_calibration",
    "quantifier_precision",
    "source_grounding",
)


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _build_label_row(
    record: dict[str, Any],
    verdict: CouncilVerdict,
    manifest_hash: str,
    label_round: str,
) -> dict[str, Any]:
    """Build a ratified label row from a converged verdict."""
    scores = verdict.scores
    labels = {axis: scores[axis] for axis in AXES if scores.get(axis) is not None}
    return {
        "manifest_id": record["id"],
        "manifest_hash": manifest_hash,
        "source_ref": record["source_ref"],
        "source_text_hash": record.get("excerpt_hash") or _text_sha256(record.get("excerpt", "")),
        "label_round": label_round,
        "labeler": "deliberative_council",
        "label_origin": LABEL_ORIGIN_RATIFIED,
        "labeled_at": _now_iso(),
        "provenance": json.dumps(
            {
                "convergence_status": verdict.convergence_status.value,
                "models_used": verdict.receipt.get("models_used", []),
                "phases_completed": verdict.receipt.get("phases_completed", []),
                "shortcircuited": verdict.receipt.get("shortcircuited", False),
                "disagreement_log": verdict.disagreement_log,
            }
        ),
        "labels": labels,
    }


def _build_review_row(
    record: dict[str, Any],
    verdict: CouncilVerdict,
    manifest_hash: str,
    label_round: str,
) -> dict[str, Any]:
    """Build a review-queue row for contested or hung verdicts."""
    return {
        "manifest_id": record["id"],
        "manifest_hash": manifest_hash,
        "source_ref": record["source_ref"],
        "source_text_hash": record.get("excerpt_hash") or _text_sha256(record.get("excerpt", "")),
        "label_round": label_round,
        "labeler": "deliberative_council",
        "label_origin": REVIEW_QUEUE_LABEL_ORIGIN,
        "labeled_at": _now_iso(),
        "convergence_status": verdict.convergence_status.value,
        "disagreement_log": verdict.disagreement_log,
        "receipt": verdict.receipt,
        "scores_raw": {k: v for k, v in verdict.scores.items() if v is not None},
        "confidence_bands": {k: list(v) for k, v in verdict.confidence_bands.items()},
    }


async def _label_record(
    record: dict[str, Any],
    manifest_hash: str,
    label_round: str,
    config: CouncilConfig,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return (label_row, review_row) — exactly one will be non-None."""
    inp = CouncilInput(
        text=record.get("excerpt", ""),
        source_ref=record.get("source_ref", record["id"]),
    )
    rubric = EpistemicQualityRubric()
    try:
        verdict = await deliberate(inp, CouncilMode.LABELING, rubric, config)
    except Exception as exc:
        _log.error("deliberate() failed for %s: %s", record["id"], exc)
        error_verdict = CouncilVerdict(
            scores={},
            confidence_bands={},
            convergence_status=ConvergenceStatus.HUNG,
            disagreement_log=[f"deliberate() exception: {exc}"],
            research_findings=[],
            evidence_matrix=None,
            receipt={"error": str(exc)},
        )
        return None, _build_review_row(record, error_verdict, manifest_hash, label_round)

    if verdict.convergence_status == ConvergenceStatus.CONVERGED:
        return _build_label_row(record, verdict, manifest_hash, label_round), None
    else:
        return None, _build_review_row(record, verdict, manifest_hash, label_round)


async def run_labeling(
    manifest_path: Path,
    output_path: Path,
    *,
    review_queue_path: Path | None = None,
    label_round: str = "round1",
    config: CouncilConfig | None = None,
    concurrency: int = 4,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Label a manifest dataset; return (label_rows, review_rows)."""
    if config is None:
        config = CouncilConfig()

    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    records: list[dict[str, Any]] = json.loads(manifest_path.read_text())

    sem = asyncio.Semaphore(concurrency)

    async def _bounded(
        record: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        async with sem:
            return await _label_record(record, manifest_hash, label_round, config)

    results = await asyncio.gather(*(_bounded(r) for r in records))

    label_rows = [lr for lr, _ in results if lr is not None]
    review_rows = [rr for _, rr in results if rr is not None]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(label_rows, indent=2))

    if review_queue_path is not None:
        review_queue_path.parent.mkdir(parents=True, exist_ok=True)
        review_queue_path.write_text(json.dumps(review_rows, indent=2))

    return label_rows, review_rows


def run_ratification(
    review_queue_path: Path,
    ratification_path: Path,
    output_path: Path,
    manifest_path: Path,
    *,
    label_round: str = "round1",
) -> list[dict[str, Any]]:
    """Read review queue + operator ratification rows; write final label rows.

    Ratification file must be a JSON array of objects with:
      manifest_id, labels (dict of axis -> int 1-5), rationale (str, optional)
    """
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    review_rows: list[dict[str, Any]] = json.loads(review_queue_path.read_text())
    ratification_rows: list[dict[str, Any]] = json.loads(ratification_path.read_text())

    manifest_records: list[dict[str, Any]] = json.loads(manifest_path.read_text())
    record_by_id = {r["id"]: r for r in manifest_records}
    review_by_id = {r["manifest_id"]: r for r in review_rows}

    ratified: list[dict[str, Any]] = []
    for row in ratification_rows:
        manifest_id = str(row.get("manifest_id", ""))
        if not manifest_id:
            _log.warning("ratification row missing manifest_id, skipping")
            continue
        record = record_by_id.get(manifest_id)
        if record is None:
            _log.warning("ratification row %s not in manifest, skipping", manifest_id)
            continue
        review = review_by_id.get(manifest_id, {})
        labels = row.get("labels", {})
        ratified.append(
            {
                "manifest_id": manifest_id,
                "manifest_hash": manifest_hash,
                "source_ref": record["source_ref"],
                "source_text_hash": record.get("excerpt_hash")
                or _text_sha256(record.get("excerpt", "")),
                "label_round": label_round,
                "labeler": "operator",
                "label_origin": LABEL_ORIGIN_RATIFIED,
                "labeled_at": _now_iso(),
                "provenance": json.dumps(
                    {
                        "ratification_source": "operator",
                        "original_convergence_status": review.get("convergence_status", "unknown"),
                        "original_disagreement_log": review.get("disagreement_log", []),
                        "rationale": row.get("rationale", ""),
                    }
                ),
                "labels": labels,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(ratified, indent=2))
    return ratified
