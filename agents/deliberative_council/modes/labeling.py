"""Mode A: deliberative council labeling over an EQI-manifest dataset."""

from __future__ import annotations

import asyncio
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
from scripts.epistemic_quality_dataset import file_sha256, read_jsonl, write_jsonl

_log = logging.getLogger(__name__)

LABEL_ORIGIN_RATIFIED = "deliberative_council_ratified"
REVIEW_QUEUE_LABEL_ORIGIN = "deliberative_council_review_pending"

AXES = (
    "claim_evidence_alignment",
    "hedge_calibration",
    "quantifier_precision",
    "source_grounding",
)

HUMAN_LABEL_ORIGINS = frozenset({"operator", "human_annotator"})


def _text_sha256(text: str) -> str:
    import hashlib

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
    """Label a manifest dataset; return (label_rows, review_rows).

    review_queue_path is required when any contested/hung rows are expected.
    If omitted and review rows are produced, a ValueError is raised.
    """
    if config is None:
        config = CouncilConfig()

    manifest_hash = file_sha256(manifest_path)
    records: list[dict[str, Any]] = read_jsonl(manifest_path)

    sem = asyncio.Semaphore(concurrency)

    async def _bounded(
        record: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        async with sem:
            return await _label_record(record, manifest_hash, label_round, config)

    results = await asyncio.gather(*(_bounded(r) for r in records))

    label_rows = [lr for lr, _ in results if lr is not None]
    review_rows = [rr for _, rr in results if rr is not None]

    write_jsonl(output_path, label_rows)

    if review_rows:
        if review_queue_path is None:
            raise ValueError(
                f"{len(review_rows)} contested/hung records require a review_queue_path"
            )
        write_jsonl(review_queue_path, review_rows)
    elif review_queue_path is not None:
        write_jsonl(review_queue_path, [])

    return label_rows, review_rows


def run_ratification(
    review_queue_path: Path,
    ratification_path: Path,
    output_path: Path,
    manifest_path: Path,
    *,
    label_round: str = "round1",
) -> list[dict[str, Any]]:
    """Read review queue + operator ratification rows (JSONL); write final label rows (JSONL).

    Ratification file must be JSONL, one object per line, each with:
      manifest_id, labels (dict of axis -> int 1-5), rationale (str, optional)
    """
    manifest_hash = file_sha256(manifest_path)
    review_rows: list[dict[str, Any]] = read_jsonl(review_queue_path)
    ratification_rows: list[dict[str, Any]] = read_jsonl(ratification_path)

    manifest_records: list[dict[str, Any]] = read_jsonl(manifest_path)
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

    write_jsonl(output_path, ratified)
    return ratified
