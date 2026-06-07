"""Candidate-set review and selected-release manifest helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.segment_live_event_quality import LIVE_EVENT_GOOD_FLOOR
from shared.segment_prep_contract import CANDIDATE_LEDGER, SELECTED_RELEASE_MANIFEST

SEGMENT_CANDIDATE_SELECTION_VERSION = 1
AUTO_EXCELLENCE_RECEIPT_VERSION = 1
AUTO_EXCELLENCE_REVIEWER = "auto:segment_candidate_selection.derive_excellence_receipt"
# Roles whose live-event rubric defines required action mechanics. A role OUTSIDE
# this set (e.g. lecture, rant, interview) earns the live-event ``role_standard_fit``
# dimension vacuously — the points are awarded with no role-specific mechanic to
# satisfy. Auto-derivation flags this so the manifest records that the points were not
# mechanic-earned (anti-gaming transparency); it never silently inflates a verdict and
# never auto-rejects an otherwise floor-clearing artifact.
ROLES_WITH_LIVE_EVENT_REQUIRED_ACTIONS = frozenset({"iceberg", "react", "tier_list", "top_10"})
PASSING_VERDICTS = {"approved", "pass", "passed", "selected"}
REQUIRED_RELEASE_RECEIPT_FIELDS = (
    "receipt_id",
    "reviewer",
    "checked_at",
    "programme_id",
    "notes",
)
INTERVIEW_RELEASE_RECEIPT_FIELDS = (
    "topic_consent_receipt",
    "answer_authority_receipt",
    "release_scope_receipt",
    "layout_readback_receipt",
)
REQUIRED_CANDIDATE_LEDGER_FIELDS = frozenset(
    {
        "candidate_ledger_version",
        "programme_id",
        "artifact_name",
        "artifact_path",
        "artifact_sha256",
        "segment_quality_overall",
        "segment_live_event_score",
        "manifest_eligible",
        "prep_contract_ok",
        "runtime_pool_eligible",
        "selected_release_required",
    }
)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_json(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return _sha256_text(text)


def _artifact_name(artifact: Mapping[str, Any]) -> str:
    path = artifact.get("artifact_path") or artifact.get("artifact_path_diagnostic")
    if isinstance(path, str) and path.strip():
        return Path(path).name
    programme_id = artifact.get("programme_id")
    if isinstance(programme_id, str) and programme_id:
        return f"{programme_id}.json"
    return ""


def _artifact_role(artifact: Mapping[str, Any]) -> str:
    role = artifact.get("role")
    if isinstance(role, str):
        return role.strip().lower()
    if isinstance(role, Mapping):
        value = role.get("value")
        if isinstance(value, str):
            return value.strip().lower()
    contract = artifact.get("segment_prep_contract")
    if isinstance(contract, Mapping):
        rundown = contract.get("rundown_card")
        if isinstance(rundown, Mapping):
            value = rundown.get("role")
            if isinstance(value, str):
                return value.strip().lower()
    return ""


def _interview_release_missing_fields(artifact: Mapping[str, Any]) -> list[str]:
    if _artifact_role(artifact) != "interview":
        return []
    report = artifact.get("selected_release_interview_report")
    if not isinstance(report, Mapping) or report.get("ok") is not True:
        return ["selected_release_interview_report"]
    missing = [
        field
        for field in INTERVIEW_RELEASE_RECEIPT_FIELDS
        if not isinstance(report.get(field), str) or not str(report.get(field)).strip()
    ]
    mode = str(report.get("mode") or "").strip()
    if mode != "public_release":
        missing.append("mode=public_release")
    question_ladder = report.get("question_ladder")
    if not isinstance(question_ladder, Sequence) or isinstance(question_ladder, (str, bytes)):
        question_ladder = []
    expected_question_ids = {
        str(question.get("question_id") or question.get("id") or "").strip()
        for question in question_ladder
        if isinstance(question, Mapping)
    }
    expected_question_ids.discard("")
    if not expected_question_ids:
        missing.append("question_ladder")
    raw_turn_receipts = report.get("turn_receipts")
    turn_receipts = (
        raw_turn_receipts
        if isinstance(raw_turn_receipts, Sequence)
        and not isinstance(raw_turn_receipts, (str, bytes))
        else []
    )
    valid_turn_receipts = [
        item
        for item in turn_receipts
        if isinstance(item, Mapping)
        and str(item.get("question_id") or "").strip()
        and str(item.get("answer_receipt_id") or "").strip()
        and str(item.get("release_decision_id") or "").strip()
        and str(item.get("layout_readback_receipt") or "").strip()
    ]
    if (
        not isinstance(raw_turn_receipts, Sequence)
        or isinstance(raw_turn_receipts, (str, bytes))
        or len(valid_turn_receipts) != len(turn_receipts)
    ):
        missing.append("turn_receipts")
    receipt_question_ids = {
        str(item.get("question_id") or "").strip() for item in valid_turn_receipts
    }
    missing_question_receipts = sorted(expected_question_ids - receipt_question_ids)
    if missing_question_receipts:
        missing.append("turn_receipts:missing_question_ids")
    return missing


def _receipt_by_artifact(
    excellence_receipts: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Mapping[str, Any]]:
    receipts: dict[str, Mapping[str, Any]] = {}
    for receipt in excellence_receipts or ():
        artifact_sha = str(receipt.get("artifact_sha256") or "").strip()
        verdict = str(receipt.get("verdict") or receipt.get("status") or "").strip().lower()
        if artifact_sha and verdict in PASSING_VERDICTS:
            receipts[artifact_sha] = receipt
    return receipts


def _release_receipt_missing_fields(
    receipt: Mapping[str, Any],
    artifact: Mapping[str, Any],
) -> list[str]:
    missing = [
        field
        for field in REQUIRED_RELEASE_RECEIPT_FIELDS
        if not isinstance(receipt.get(field), str) or not str(receipt.get(field)).strip()
    ]
    receipt_programme_id = str(receipt.get("programme_id") or "").strip()
    artifact_programme_id = str(artifact.get("programme_id") or "").strip()
    if (
        receipt_programme_id
        and artifact_programme_id
        and receipt_programme_id != artifact_programme_id
    ):
        missing.append("programme_id_mismatch")
    return missing


def _selection_score(artifact: Mapping[str, Any]) -> tuple[float, float, str]:
    live_event = artifact.get("segment_live_event_report")
    quality = artifact.get("segment_quality_report")
    live_score = float(live_event.get("score") or 0) if isinstance(live_event, Mapping) else 0.0
    quality_score = float(quality.get("overall") or 0) if isinstance(quality, Mapping) else 0.0
    return (live_score, quality_score, str(artifact.get("programme_id") or ""))


def read_candidate_ledger(today: Path) -> list[dict[str, Any]]:
    path = today / CANDIDATE_LEDGER
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            rows.append({"invalid_jsonl_line": line})
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _valid_candidate_ledger_rows(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    valid: list[Mapping[str, Any]] = []
    for row in rows:
        if "invalid_jsonl_line" in row:
            continue
        if set(REQUIRED_CANDIDATE_LEDGER_FIELDS) - set(row):
            continue
        if row.get("candidate_ledger_version") != SEGMENT_CANDIDATE_SELECTION_VERSION:
            continue
        for key in ("programme_id", "artifact_name", "artifact_path", "artifact_sha256"):
            if not isinstance(row.get(key), str) or not str(row.get(key)).strip():
                break
        else:
            if (
                row.get("manifest_eligible") is True
                and row.get("prep_contract_ok") is True
                and row.get("runtime_pool_eligible") is False
                and row.get("selected_release_required") is True
                and isinstance(row.get("segment_quality_overall"), int | float)
                and isinstance(row.get("segment_live_event_score"), int | float)
            ):
                valid.append(row)
    return valid


def _ledger_artifact_hashes(rows: Sequence[Mapping[str, Any]]) -> set[str]:
    hashes: set[str] = set()
    for row in rows:
        artifact_sha = row.get("artifact_sha256")
        if isinstance(artifact_sha, str) and artifact_sha.strip():
            hashes.add(artifact_sha.strip())
    return hashes


def _live_event_dimension(report: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    for dim in report.get("dimensions") or ():
        if isinstance(dim, Mapping) and dim.get("name") == name:
            return dim
    return {}


def _live_event_criterion_vector(report: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Compact, re-checkable vector of the live-event dimensions (name -> passed/points)."""
    vector: dict[str, dict[str, Any]] = {}
    for dim in report.get("dimensions") or ():
        if not isinstance(dim, Mapping):
            continue
        name = str(dim.get("name") or "").strip()
        if not name:
            continue
        vector[name] = {"passed": bool(dim.get("passed")), "points": dim.get("points")}
    return vector


def _anti_gaming_flags(
    *, role_standard_fit_vacuous: bool, clears_floor_without_vacuous_role_fit: bool
) -> list[str]:
    flags: list[str] = []
    if role_standard_fit_vacuous:
        flags.append("role_standard_fit_points_awarded_vacuously")
        if not clears_floor_without_vacuous_role_fit:
            flags.append("clears_floor_only_via_vacuous_role_fit_points")
    return flags


def derive_excellence_receipt(
    artifact: Mapping[str, Any],
    *,
    checked_at: str,
    reviewer: str = AUTO_EXCELLENCE_REVIEWER,
) -> dict[str, Any]:
    """Auto-derive an auditable excellence receipt from a prepared artifact.

    Operator decision OD-2: auto-derivation is permitted ONLY when it is transparent and
    re-checkable. The receipt therefore records the computed live-event criterion vector
    and the scores that produced the verdict, keyed by ``artifact_sha256`` — never a bare
    boolean. A verdict is ``approved`` only when the deterministic live-event report
    already clears ``LIVE_EVENT_GOOD_FLOOR``; this gate is read, never weakened.
    """
    live = artifact.get("segment_live_event_report")
    live = live if isinstance(live, Mapping) else {}
    quality = artifact.get("segment_quality_report")
    quality = quality if isinstance(quality, Mapping) else {}
    artifact_sha = str(artifact.get("artifact_sha256") or "").strip()
    programme_id = str(artifact.get("programme_id") or "").strip()
    role = _artifact_role(artifact)

    raw_score = live.get("score")
    live_score = float(raw_score) if isinstance(raw_score, int | float) else None
    band = str(live.get("band") or "")
    report_ok = live.get("ok") is True

    role_fit_dim = _live_event_dimension(live, "role_standard_fit")
    observed = role_fit_dim.get("observed")
    required_action_kinds = (
        observed.get("required_action_kinds") if isinstance(observed, Mapping) else None
    )
    role_fit_passed = bool(role_fit_dim.get("passed"))
    raw_points = role_fit_dim.get("points")
    role_fit_points = float(raw_points) if isinstance(raw_points, int | float) else 0.0
    role_standard_fit_vacuous = bool(
        role_fit_passed
        and not (required_action_kinds or [])
        and role not in ROLES_WITH_LIVE_EVENT_REQUIRED_ACTIONS
    )
    adjusted_live_event_score = (
        live_score - role_fit_points
        if (live_score is not None and role_standard_fit_vacuous)
        else live_score
    )
    clears_floor_without_vacuous_role_fit = (
        adjusted_live_event_score is not None and adjusted_live_event_score >= LIVE_EVENT_GOOD_FLOOR
    )

    criteria = [
        {
            "name": "live_event_score_meets_floor",
            "passed": live_score is not None and live_score >= LIVE_EVENT_GOOD_FLOOR,
            "observed": {"live_event_score": live_score, "floor": LIVE_EVENT_GOOD_FLOOR},
        },
        {
            "name": "live_event_band_good_or_excellent",
            "passed": band in {"good", "excellent"},
            "observed": {"band": band},
        },
        {
            "name": "live_event_report_ok",
            "passed": report_ok,
            "observed": {"ok": live.get("ok")},
        },
    ]
    passed = all(item["passed"] for item in criteria)
    criterion_vector = _live_event_criterion_vector(live)
    dimension_points_total = sum(
        float(entry["points"])
        for entry in criterion_vector.values()
        if isinstance(entry.get("points"), int | float)
    )
    scores = {
        "live_event_score": live_score,
        "live_event_band": band,
        "live_event_floor": LIVE_EVENT_GOOD_FLOOR,
        "live_event_dimension_points_total": dimension_points_total,
        "adjusted_live_event_score": adjusted_live_event_score,
        "quality_overall": quality.get("overall"),
    }
    receipt = {
        "auto_excellence_receipt_version": AUTO_EXCELLENCE_RECEIPT_VERSION,
        "artifact_sha256": artifact_sha,
        "programme_id": programme_id,
        "role": role,
        "verdict": "approved" if passed else "rejected",
        "reviewer": reviewer,
        "checked_at": checked_at,
        "receipt_id": f"auto-excellence:{programme_id or artifact_sha[:12] or 'unknown'}",
        "notes": (
            "Auto-derived excellence receipt: live-event criterion vector and scores "
            f"recomputed from the prepared artifact; verdict gates on live_event_score >= "
            f"{LIVE_EVENT_GOOD_FLOOR}. Role-standard-fit "
            f"{'vacuous (no role-required actions)' if role_standard_fit_vacuous else 'mechanic-bound'}."
        ),
        "auto_derived": True,
        "criteria": criteria,
        "criterion_vector": criterion_vector,
        "scores": scores,
        "role_standard_fit_vacuous": role_standard_fit_vacuous,
        "clears_floor_without_vacuous_role_fit": clears_floor_without_vacuous_role_fit,
        "anti_gaming_flags": _anti_gaming_flags(
            role_standard_fit_vacuous=role_standard_fit_vacuous,
            clears_floor_without_vacuous_role_fit=clears_floor_without_vacuous_role_fit,
        ),
    }
    receipt["auto_excellence_receipt_sha256"] = _sha256_json(
        {key: value for key, value in receipt.items() if key != "auto_excellence_receipt_sha256"}
    )
    return receipt


def derive_excellence_receipts(
    eligible_artifacts: Sequence[Mapping[str, Any]],
    *,
    checked_at: str,
    reviewer: str = AUTO_EXCELLENCE_REVIEWER,
) -> list[dict[str, Any]]:
    """Auto-derive one auditable excellence receipt per eligible artifact."""
    return [
        derive_excellence_receipt(artifact, checked_at=checked_at, reviewer=reviewer)
        for artifact in eligible_artifacts
        if str(artifact.get("artifact_sha256") or "").strip()
    ]


def _excellence_receipt_record(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Auditable per-artifact excellence record embedded into the manifest.

    Carries the criterion vector + scores for auto-derived receipts so the chosen
    candidate is re-checkable from the manifest alone; degrades to the receipt identity
    fields for externally-authored (manual-review) receipts.
    """
    record: dict[str, Any] = {
        "receipt_id": receipt.get("receipt_id"),
        "reviewer": receipt.get("reviewer"),
        "checked_at": receipt.get("checked_at"),
        "verdict": receipt.get("verdict") or receipt.get("status"),
        "auto_derived": bool(receipt.get("auto_derived")),
    }
    for key in (
        "criterion_vector",
        "scores",
        "role_standard_fit_vacuous",
        "clears_floor_without_vacuous_role_fit",
        "anti_gaming_flags",
        "auto_excellence_receipt_sha256",
    ):
        if key in receipt:
            record[key] = receipt[key]
    return record


def selected_release_manifest(
    eligible_artifacts: Sequence[Mapping[str, Any]],
    excellence_receipts: Sequence[Mapping[str, Any]] | None,
    *,
    selected_count: int = 10,
) -> dict[str, Any]:
    """Build a selected-release manifest from eligible artifacts and review receipts."""
    receipt_by_sha = _receipt_by_artifact(excellence_receipts)
    reviewed_candidates: list[Mapping[str, Any]] = []
    violations: list[dict[str, Any]] = []
    review_gaps: list[dict[str, Any]] = []
    ranked_eligible = sorted(
        enumerate(eligible_artifacts),
        key=lambda item: _selection_score(item[1]),
        reverse=True,
    )
    release_window = ranked_eligible[:selected_count]
    release_window_indexes = {index for index, _artifact in release_window}

    def add_review_gap(
        reason: str,
        *,
        index: int,
        artifact_sha256: str = "",
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"reason": reason}
        if artifact_sha256:
            payload["artifact_sha256"] = artifact_sha256
        else:
            payload["index"] = index
        if extra:
            payload.update(dict(extra))
        review_gaps.append(payload)
        if index in release_window_indexes:
            violations.append(
                {
                    "reason": f"release_window_{reason}",
                    **{key: value for key, value in payload.items() if key != "reason"},
                }
            )

    for index, artifact in ranked_eligible:
        in_release_window = index in release_window_indexes
        artifact_sha = str(artifact.get("artifact_sha256") or "").strip()
        name = _artifact_name(artifact)
        live_event = artifact.get("segment_live_event_report")
        live_score = float(live_event.get("score") or 0) if isinstance(live_event, Mapping) else 0.0
        if not artifact_sha:
            add_review_gap("eligible_artifact_missing_hash", index=index)
            continue
        if not name:
            add_review_gap(
                "eligible_artifact_missing_name",
                index=index,
                artifact_sha256=artifact_sha,
            )
            continue
        if artifact_sha not in receipt_by_sha:
            add_review_gap(
                "eligible_artifact_missing_excellence_receipt",
                index=index,
                artifact_sha256=artifact_sha,
            )
            continue
        receipt = receipt_by_sha[artifact_sha]
        receipt_missing = _release_receipt_missing_fields(receipt, artifact)
        if receipt_missing:
            add_review_gap(
                "eligible_artifact_incomplete_excellence_receipt",
                index=index,
                artifact_sha256=artifact_sha,
                extra={"missing": receipt_missing},
            )
            continue
        if live_score < LIVE_EVENT_GOOD_FLOOR:
            add_review_gap(
                "eligible_artifact_live_event_below_release_floor",
                index=index,
                artifact_sha256=artifact_sha,
                extra={"live_event_score": live_score},
            )
            continue
        interview_missing = _interview_release_missing_fields(artifact)
        if interview_missing:
            add_review_gap(
                "interview_artifact_missing_selected_release_receipts",
                index=index,
                artifact_sha256=artifact_sha,
                extra={"missing": interview_missing},
            )
            continue
        if in_release_window:
            reviewed_candidates.append(artifact)

    selected = sorted(reviewed_candidates, key=_selection_score, reverse=True)[:selected_count]
    selected_names = [_artifact_name(artifact) for artifact in selected]
    reviewed_names = [_artifact_name(artifact) for artifact in reviewed_candidates]
    implicit_first = bool(
        selected_names
        and reviewed_names
        and selected_names == reviewed_names[: len(selected_names)]
        and len(reviewed_names) > len(selected_names)
    )
    if implicit_first:
        violations.append(
            {"reason": "selection_matches_first_eligible_slice_without_ranking_evidence"}
        )
    if not selected:
        violations.append({"reason": "no_reviewed_release_candidates"})

    manifest = {
        "selected_release_manifest_version": SEGMENT_CANDIDATE_SELECTION_VERSION,
        "selected_at": datetime.now(tz=UTC).isoformat(),
        "selection_gate": "shared.segment_candidate_selection.selected_release_manifest",
        "eligible_artifact_count": len(eligible_artifacts),
        "release_window_count": len(release_window),
        "reviewed_candidate_count": len(reviewed_candidates),
        "selected_count": len(selected),
        "target_selected_count": selected_count,
        "programmes": selected_names,
        "selected_artifacts": [
            {
                "programme_id": artifact.get("programme_id"),
                "artifact_name": _artifact_name(artifact),
                "artifact_sha256": artifact.get("artifact_sha256"),
                "quality_overall": (artifact.get("segment_quality_report") or {}).get("overall")
                if isinstance(artifact.get("segment_quality_report"), Mapping)
                else None,
                "live_event_score": (artifact.get("segment_live_event_report") or {}).get("score")
                if isinstance(artifact.get("segment_live_event_report"), Mapping)
                else None,
                "live_event_band": (artifact.get("segment_live_event_report") or {}).get("band")
                if isinstance(artifact.get("segment_live_event_report"), Mapping)
                else None,
                "receipt_id": receipt_by_sha[str(artifact.get("artifact_sha256") or "")].get(
                    "receipt_id"
                ),
                "reviewer": receipt_by_sha[str(artifact.get("artifact_sha256") or "")].get(
                    "reviewer"
                ),
                "checked_at": receipt_by_sha[str(artifact.get("artifact_sha256") or "")].get(
                    "checked_at"
                ),
                "excellence_receipt": _excellence_receipt_record(
                    receipt_by_sha[str(artifact.get("artifact_sha256") or "")]
                ),
            }
            for artifact in selected
        ],
        "review_gaps": review_gaps,
        "violations": violations,
        "ok": not violations and bool(selected),
    }
    manifest["selected_release_manifest_sha256"] = _sha256_json(manifest)
    return manifest


def review_segment_candidate_set(
    eligible_artifacts: Sequence[Mapping[str, Any]],
    candidate_ledger_rows: Sequence[Mapping[str, Any]] | None,
    excellence_receipts: Sequence[Mapping[str, Any]] | None = None,
    *,
    selected_count: int = 10,
) -> dict[str, Any]:
    """Review a full candidate set and return a selection manifest plus receipt."""
    manifest = selected_release_manifest(
        eligible_artifacts,
        excellence_receipts,
        selected_count=selected_count,
    )
    ledger_rows = list(candidate_ledger_rows or [])
    valid_ledger_rows = _valid_candidate_ledger_rows(ledger_rows)
    invalid_ledger_count = len(ledger_rows) - len(valid_ledger_rows)
    ledger_hashes = _ledger_artifact_hashes(valid_ledger_rows)
    selected_hashes = {
        str(item.get("artifact_sha256") or "").strip()
        for item in manifest.get("selected_artifacts") or []
        if isinstance(item, Mapping)
    }
    missing_selected_ledger_hashes = sorted(
        hash_ for hash_ in selected_hashes if hash_ not in ledger_hashes
    )
    criteria = [
        {
            "name": "candidate_set.has_ledger",
            "passed": bool(valid_ledger_rows),
            "detail": "candidate attempts, rejections, and eligible artifacts must be auditable",
            "observed": {
                "candidate_ledger_rows": len(ledger_rows),
                "valid_candidate_ledger_rows": len(valid_ledger_rows),
            },
        },
        {
            "name": "candidate_set.ledger_rows_valid_json",
            "passed": invalid_ledger_count == 0,
            "detail": "candidate ledger rows must be parseable JSON objects",
            "observed": {"invalid_ledger_rows": invalid_ledger_count},
        },
        {
            "name": "candidate_set.has_more_than_release_when_possible",
            "passed": len(eligible_artifacts) >= min(selected_count, 1),
            "detail": "selection must be made from eligible reviewed candidates",
            "observed": {"eligible_artifact_count": len(eligible_artifacts)},
        },
        {
            "name": "candidate_set.selected_manifest_ok",
            "passed": manifest["ok"] is True,
            "detail": "selected-release manifest requires excellence receipts and live-event floor",
            "observed": {
                "violations": manifest["violations"],
                "selected_count": manifest["selected_count"],
            },
        },
        {
            "name": "candidate_set.selected_artifacts_have_ledger_rows",
            "passed": not selected_hashes or not missing_selected_ledger_hashes,
            "detail": "every selected artifact hash must have a valid candidate-ledger row",
            "observed": {"missing_artifact_sha256": missing_selected_ledger_hashes},
        },
    ]
    receipt = {
        "segment_candidate_selection_version": SEGMENT_CANDIDATE_SELECTION_VERSION,
        "ok": all(item["passed"] for item in criteria),
        "criteria": criteria,
        "selected_release_manifest": manifest,
    }
    receipt["segment_candidate_selection_sha256"] = _sha256_json(receipt)
    return receipt


def write_selected_release_manifest(today: Path, manifest: Mapping[str, Any]) -> Path:
    if manifest.get("ok") is not True or not manifest.get("selected_artifacts"):
        raise ValueError("selected-release manifest must be ok=true with selected artifacts")
    path = today / SELECTED_RELEASE_MANIFEST
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(dict(manifest), indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return path
