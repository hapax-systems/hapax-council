#!/usr/bin/env python3
"""Review eligible segment candidates and write selected-release manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.hapax_daimonion.daily_segment_prep import (
    DEFAULT_PREP_DIR,
    load_prepped_programmes,
    publish_selected_release_feedback,
)
from shared.segment_candidate_selection import (
    read_candidate_ledger,
    review_segment_candidate_set,
    write_selected_release_manifest,
)
from shared.segment_prep_contract import (
    SEGMENT_PREP_DIAGNOSTIC_AUTHORITY,
    SEGMENT_PREP_OUTCOME_VERSION,
    validate_segment_prep_outcome,
)
from shared.segment_prep_pause import (
    SegmentPrepPaused,
    SegmentPrepPauseError,
    assert_segment_prep_allowed,
)


def _load_receipts(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        receipts = data.get("excellence_receipts") or data.get("team_critique_receipts") or []
        if isinstance(receipts, list):
            return [item for item in receipts if isinstance(item, dict)]
    raise SystemExit(f"receipt file must contain a list or receipts object: {path}")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_json(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return _sha256_text(text)


def _terminal_no_release_outcome(today: Path, receipt: Mapping[str, Any]) -> Path:
    """Write a diagnostic-only terminal outcome for failed release review."""

    now = datetime.now(tz=UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    manifest = receipt.get("selected_release_manifest")
    manifest = manifest if isinstance(manifest, dict) else {}
    outcome = {
        "segment_prep_outcome_version": SEGMENT_PREP_OUTCOME_VERSION,
        "outcome_type": "no_release",
        "authority": SEGMENT_PREP_DIAGNOSTIC_AUTHORITY,
        "prep_session_id": f"segment-release-review-{stamp}",
        "model_id": None,
        "reason_code": "selected_release_review_failed",
        "blocking_gaps": list(manifest.get("violations") or []),
        "review_gaps": list(manifest.get("review_gaps") or []),
        "criteria": list(receipt.get("criteria") or []),
        "source_refs": [],
        "counts": {
            "eligible_artifact_count": manifest.get("eligible_artifact_count", 0),
            "reviewed_candidate_count": manifest.get("reviewed_candidate_count", 0),
            "selected_count": manifest.get("selected_count", 0),
            "target_selected_count": manifest.get("target_selected_count", 0),
        },
        "release_boundary": {
            "listed_in_manifest": False,
            "selected_release_eligible": False,
            "runtime_pool_eligible": False,
        },
        "review_receipt_sha256": receipt.get("segment_candidate_selection_sha256"),
        "recorded_at": now.isoformat(),
    }
    outcome["outcome_sha256"] = _sha256_json(outcome)
    failures = validate_segment_prep_outcome(outcome)
    if failures:
        raise RuntimeError(f"no_release outcome validation failed: {failures}")
    path = today / "outcomes" / f"{stamp}.no_release.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(outcome, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
    tmp.replace(path)
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Review eligible segment candidates and build selected-release-manifest.json."
    )
    parser.add_argument("--prep-dir", type=Path, default=DEFAULT_PREP_DIR)
    parser.add_argument("--receipts", type=Path, default=None)
    parser.add_argument("--selected-count", type=int, default=10)
    parser.add_argument("--receipt-out", type=Path, default=None)
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args(argv)

    today = args.prep_dir / datetime.now(tz=UTC).strftime("%Y-%m-%d")
    today.mkdir(parents=True, exist_ok=True)
    artifacts = load_prepped_programmes(
        args.prep_dir,
        require_selected=False,
        strict_release_contract=True,
    )
    receipt = review_segment_candidate_set(
        artifacts,
        read_candidate_ledger(today),
        _load_receipts(args.receipts),
        selected_count=args.selected_count,
    )
    if args.write_manifest:
        if receipt["ok"]:
            try:
                authority_state = assert_segment_prep_allowed("runtime_pool_load")
            except (SegmentPrepPaused, SegmentPrepPauseError) as exc:
                receipt["ok"] = False
                receipt["write_manifest_blocked"] = {
                    "reason": "segment_prep_authority_gate",
                    "error": str(exc),
                }
                receipt["terminal_outcome_path"] = str(_terminal_no_release_outcome(today, receipt))
            else:
                receipt["authority_mode"] = authority_state.mode
                write_selected_release_manifest(today, receipt["selected_release_manifest"])
                receipt["selected_release_publication"] = publish_selected_release_feedback(
                    prep_dir=args.prep_dir,
                    review_receipt=receipt,
                )
                if receipt["selected_release_publication"].get("ok") is not True:
                    receipt["ok"] = False
                    receipt["selected_release_publication_blocked"] = True
                    selected_manifest_path = today / "selected-release-manifest.json"
                    try:
                        selected_manifest_path.unlink()
                    except FileNotFoundError:
                        pass
                    receipt["terminal_outcome_path"] = str(
                        _terminal_no_release_outcome(today, receipt)
                    )
        else:
            receipt["terminal_outcome_path"] = str(_terminal_no_release_outcome(today, receipt))
    receipt["closure_ok"] = receipt["ok"] is True
    rendered = json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False)
    if args.receipt_out is not None:
        args.receipt_out.parent.mkdir(parents=True, exist_ok=True)
        args.receipt_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if receipt["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
