#!/usr/bin/env python3
"""Deterministic public-surface claim gate for weblog and omg copy."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.github_public_claim_gate import (
    GitHubMaterialEvidenceEnvelope,
    evaluate_github_public_claims,
    github_material_envelope_from_mapping,
)
from shared.github_public_surface import GitHubPublicSurfaceReport
from shared.github_publication_log import events_from_github_public_surface_report
from shared.publication_freshness import (
    DEFAULT_FRESHNESS_STATE,
    PublicationFreshnessSnapshot,
    PublicSurfaceFreshnessEnvelope,
    build_publication_freshness_snapshot,
    github_events_to_freshness_envelopes,
    isoformat_z,
    parse_iso_z,
)
from shared.publication_hardening.lint import LintFinding, lint_file

DEFAULT_TOKEN_CLAIM_REPORT = (
    REPO_ROOT / "docs/research/evidence/2026-05-13-token-capital-claim-regate-v2.json"
)
DEFAULT_SOURCE_RECONCILIATION = (
    REPO_ROOT
    / "docs/research/evidence/2026-05-13-public-surface-source-of-truth-reconciliation.json"
)
DEFAULT_GITHUB_PUBLIC_SURFACE_REPORT = (
    REPO_ROOT / "docs/repo-pres/github-public-surface-live-state-reconcile.json"
)
DEFAULT_TARGETS = (
    REPO_ROOT / "agents" / "omg_web_builder" / "static" / "index.html",
    REPO_ROOT / "docs" / "publication-drafts",
)
TOKEN_CLAIM_RULE = "Hapax.TokenCapitalClaimCeiling"
SOURCE_DISPOSITION_RULE = "Hapax.PublicSurfaceSourceDisposition"
GITHUB_PUBLIC_CLAIM_RULE = "Hapax.GitHubPublicClaimEvidenceGate"
PUBLICATION_FRESHNESS_RULE = "Hapax.PublicationFreshness"


class RequiredInputError(ValueError):
    """Required machine-readable receipt input is missing or malformed."""


def iter_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob("*") if p.suffix in {".html", ".md"}))
        elif path.exists():
            if path.suffix in {".html", ".md"}:
                files.append(path)
        else:
            raise FileNotFoundError(path)
    return files


def finding_to_dict(finding: LintFinding) -> dict[str, object]:
    return {
        "file": finding.file,
        "line": finding.line,
        "level": finding.level,
        "rule": finding.rule,
        "message": finding.message,
    }


def load_required_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RequiredInputError(f"{label} not found: {path}") from exc
    except OSError as exc:
        raise RequiredInputError(f"{label} is not readable: {path}: {exc}") from exc

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RequiredInputError(f"{label} is not valid JSON: {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise RequiredInputError(f"{label} must be a JSON object: {path}")
    return payload


def claim_upgrade_allowed(report: Mapping[str, Any], claim_id: str) -> bool:
    allowed_claim_ids = report.get("allowed_claim_ids", [])
    if isinstance(allowed_claim_ids, list) and claim_id in allowed_claim_ids:
        return True

    claim_classes = report.get("claim_classes", {})
    if not isinstance(claim_classes, Mapping):
        return False
    claim = claim_classes.get(claim_id)
    if not isinstance(claim, Mapping):
        return False
    return claim.get("status") in {"supported", "bounded_supported"}


def compile_forbidden_claim_patterns(
    report: Mapping[str, Any],
    *,
    report_path: Path,
) -> list[tuple[str, re.Pattern[str], str]]:
    raw_patterns = report.get("forbidden_public_claims", [])
    if not isinstance(raw_patterns, list):
        raise RequiredInputError(
            f"token claim report has non-list forbidden_public_claims: {report_path}"
        )

    compiled: list[tuple[str, re.Pattern[str], str]] = []
    for index, item in enumerate(raw_patterns):
        if not isinstance(item, Mapping):
            raise RequiredInputError(
                f"token claim report forbidden_public_claims[{index}] is not an object: {report_path}"
            )
        claim_id = item.get("claim_id")
        pattern = item.get("pattern")
        reason = item.get("reason", "Claim exceeds the current public claim ceiling.")
        if not isinstance(claim_id, str) or not isinstance(pattern, str):
            raise RequiredInputError(
                f"token claim report forbidden_public_claims[{index}] lacks claim_id/pattern: "
                f"{report_path}"
            )
        if claim_upgrade_allowed(report, claim_id):
            continue
        try:
            compiled.append((claim_id, re.compile(pattern, re.IGNORECASE), str(reason)))
        except re.error as exc:
            raise RequiredInputError(
                f"token claim report forbidden_public_claims[{index}] has invalid regex: "
                f"{report_path}: {exc}"
            ) from exc
    return compiled


def check_token_claim_ceiling(
    path: Path,
    patterns: list[tuple[str, re.Pattern[str], str]],
) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for lineno, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(),
        start=1,
    ):
        for claim_id, pattern, reason in patterns:
            if not pattern.search(line):
                continue
            findings.append(
                LintFinding(
                    file=str(path),
                    line=lineno,
                    level="error",
                    rule=TOKEN_CLAIM_RULE,
                    message=f"`{claim_id}` is not permitted by the current claim ceiling. {reason}",
                )
            )
    return findings


def check_source_disposition(
    report: Mapping[str, Any],
    *,
    report_path: Path,
) -> list[LintFinding]:
    summary = report.get("summary")
    rows = report.get("rows", [])
    if not isinstance(summary, Mapping):
        raise RequiredInputError(f"source reconciliation has no summary object: {report_path}")
    if not isinstance(rows, list):
        raise RequiredInputError(f"source reconciliation has non-list rows: {report_path}")

    unreconciled_summary = summary.get("unreconciled_items", [])
    if not isinstance(unreconciled_summary, list):
        raise RequiredInputError(
            f"source reconciliation summary.unreconciled_items is not a list: {report_path}"
        )

    bad_rows = [
        str(row.get("item_id", "<unknown>"))
        for row in rows
        if isinstance(row, Mapping)
        and row.get("disposition") == "unreconciled_no_source_or_receipt"
    ]
    unreconciled_items = sorted({*(str(item) for item in unreconciled_summary), *bad_rows})
    if not unreconciled_items:
        return []

    return [
        LintFinding(
            file=str(report_path),
            line=1,
            level="error",
            rule=SOURCE_DISPOSITION_RULE,
            message=(
                "Public surface reconciliation has live items without committed source or "
                f"explicit receipt: {', '.join(unreconciled_items)}"
            ),
        )
    ]


def load_github_material_envelope(path: Path) -> GitHubMaterialEvidenceEnvelope:
    payload = load_required_json(path, label="github material envelope")
    try:
        return github_material_envelope_from_mapping(payload)
    except (TypeError, ValueError) as exc:
        raise RequiredInputError(f"github material envelope is malformed: {path}: {exc}") from exc


def load_github_public_surface_report(path: Path) -> GitHubPublicSurfaceReport:
    payload = load_required_json(path, label="github public-surface report")
    try:
        return GitHubPublicSurfaceReport.model_validate(payload)
    except (TypeError, ValueError) as exc:
        raise RequiredInputError(
            f"github public-surface report is malformed: {path}: {exc}. "
            "Next action: regenerate the report with scripts/github-public-surface-reconcile.py "
            "and hold release until the public-surface claim gate passes."
        ) from exc


def expected_freshness_envelopes_from_report(
    report: GitHubPublicSurfaceReport,
) -> tuple[PublicSurfaceFreshnessEnvelope, ...]:
    events = events_from_github_public_surface_report(
        report,
        generated_at=report.generated_at,
    )
    return github_events_to_freshness_envelopes(events, checked_at=report.generated_at)


def check_github_material_claims(
    path: Path,
    envelope: GitHubMaterialEvidenceEnvelope,
) -> list[LintFinding]:
    verdict = evaluate_github_public_claims(path.read_text(encoding="utf-8"), envelope)
    findings: list[LintFinding] = []
    for blocked in verdict.blocked_findings:
        message = f"{blocked.claim_class.value}: {blocked.reason}"
        if blocked.correction:
            message = f"{message} Correction: {blocked.correction}"
        findings.append(
            LintFinding(
                file=str(path),
                line=1,
                level="error",
                rule=GITHUB_PUBLIC_CLAIM_RULE,
                message=message,
            )
        )
    return findings


def load_publication_freshness_state(path: Path) -> PublicationFreshnessSnapshot:
    payload = load_required_json(path, label="publication freshness state")
    try:
        return PublicationFreshnessSnapshot.model_validate(payload)
    except (TypeError, ValueError) as exc:
        raise RequiredInputError(
            f"publication freshness state is malformed: {path}: {exc}. "
            "Next action: regenerate or repair the state with "
            "scripts/publication-freshness-audit.py and hold release until the "
            "public-surface claim gate passes."
        ) from exc


def check_publication_freshness_state(
    state: PublicationFreshnessSnapshot,
    *,
    state_path: Path,
    required_surface_ids: tuple[str, ...],
    expected_envelopes: tuple[PublicSurfaceFreshnessEnvelope, ...],
) -> list[LintFinding]:
    findings: list[LintFinding] = []
    now = datetime.now(tz=UTC)
    future_witnesses: list[str] = []
    observed_by_surface_id = {envelope.surface_id: envelope for envelope in state.envelopes}
    observed_surface_ids = set(observed_by_surface_id)
    missing_required_surface_ids = sorted(set(required_surface_ids) - observed_surface_ids)
    if missing_required_surface_ids:
        findings.append(
            LintFinding(
                file=str(state_path),
                line=1,
                level="error",
                rule=PUBLICATION_FRESHNESS_RULE,
                message=(
                    "Publication freshness state omits required public-surface witnesses: "
                    f"{', '.join(missing_required_surface_ids)}. Next action: regenerate the "
                    "publication freshness audit/live-state readback and hold release until "
                    "every required public surface has a current witness."
                ),
            )
        )
    findings.extend(
        _check_expected_freshness_envelopes(
            state_path=state_path,
            observed_by_surface_id=observed_by_surface_id,
            expected_envelopes=expected_envelopes,
        )
    )
    generated_at = _parse_freshness_timestamp(
        state.generated_at,
    )
    if generated_at is None:
        findings.append(_malformed_freshness_timestamp_finding(state_path, "snapshot.generated_at"))
    elif generated_at > now:
        future_witnesses.append(f"snapshot.generated_at={state.generated_at}")
    for envelope in state.envelopes:
        checked_at = _parse_freshness_timestamp(
            envelope.checked_at,
        )
        if checked_at is None:
            findings.append(
                _malformed_freshness_timestamp_finding(
                    state_path,
                    f"{envelope.surface_id}.checked_at",
                )
            )
        elif checked_at > now:
            future_witnesses.append(f"{envelope.surface_id}.checked_at={envelope.checked_at}")
    if future_witnesses:
        findings.append(
            LintFinding(
                file=str(state_path),
                line=1,
                level="error",
                rule=PUBLICATION_FRESHNESS_RULE,
                message=(
                    "Publication freshness state contains future-dated witnesses: "
                    f"{', '.join(future_witnesses)}. Next action: regenerate the "
                    "publication freshness audit/live-state readback on the verifier clock "
                    "and hold release until no witness timestamp is in the future."
                ),
            )
        )
    if not state.envelopes:
        findings.append(
            LintFinding(
                file=str(state_path),
                line=1,
                level="error",
                rule=PUBLICATION_FRESHNESS_RULE,
                message=(
                    "Publication freshness state has no surface envelopes. Next action: "
                    "regenerate the publication freshness audit/live-state readback and "
                    "hold release until at least one current public-surface witness is present."
                ),
            )
        )
    reassessed = build_publication_freshness_snapshot(
        state.envelopes,
        generated_at=isoformat_z(now),
    )
    blockers = tuple(dict.fromkeys((*state.blockers, *reassessed.blockers)))
    if not blockers:
        return findings
    findings.append(
        LintFinding(
            file=str(state_path),
            line=1,
            level="error",
            rule=PUBLICATION_FRESHNESS_RULE,
            message=(
                "Publication freshness has public-current blockers: "
                f"{', '.join(blockers)}. Next action: refresh the publication freshness "
                "audit/live-state readback and hold release until the blockers clear."
            ),
        )
    )
    return findings


def _check_expected_freshness_envelopes(
    *,
    state_path: Path,
    observed_by_surface_id: dict[str, PublicSurfaceFreshnessEnvelope],
    expected_envelopes: tuple[PublicSurfaceFreshnessEnvelope, ...],
) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for expected in expected_envelopes:
        observed = observed_by_surface_id.get(expected.surface_id)
        if observed is None:
            continue
        mismatches = _expected_envelope_mismatches(expected=expected, observed=observed)
        if not mismatches:
            continue
        findings.append(
            LintFinding(
                file=str(state_path),
                line=1,
                level="error",
                rule=PUBLICATION_FRESHNESS_RULE,
                message=(
                    "Publication freshness witness does not match live report evidence for "
                    f"{expected.surface_id}: {', '.join(mismatches)}. Next action: regenerate "
                    "the publication freshness audit/live-state readback and hold release "
                    "until every freshness witness matches the current live report."
                ),
            )
        )
    return findings


def _expected_envelope_mismatches(
    *,
    expected: PublicSurfaceFreshnessEnvelope,
    observed: PublicSurfaceFreshnessEnvelope,
) -> list[str]:
    fields = (
        "freshness_result",
        "checked_at",
        "ttl_s",
        "expires_at",
        "source_ref",
        "source_of_truth",
        "evidence_refs",
        "source_hash",
        "rendered_hash",
        "published_hash",
        "readback_hash",
    )
    mismatches: list[str] = []
    for field in fields:
        expected_value = getattr(expected, field)
        observed_value = getattr(observed, field)
        if expected_value != observed_value:
            mismatches.append(
                f"{field} expected {_display_value(expected_value)} observed "
                f"{_display_value(observed_value)}"
            )
    return mismatches


def _display_value(value: object) -> str:
    if value is None:
        return "<none>"
    return str(value)


def _parse_freshness_timestamp(value: str) -> datetime | None:
    try:
        return parse_iso_z(value)
    except ValueError:
        return None


def _malformed_freshness_timestamp_finding(state_path: Path, label: str) -> LintFinding:
    return LintFinding(
        file=str(state_path),
        line=1,
        level="error",
        rule=PUBLICATION_FRESHNESS_RULE,
        message=(
            f"Publication freshness state has malformed timestamp {label}. "
            "Next action: regenerate the publication freshness audit/live-state "
            "readback and hold release until the public-surface claim gate passes."
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="files or directories to scan")
    parser.add_argument("--json", action="store_true", help="emit JSON findings")
    parser.add_argument(
        "--token-claim-report",
        type=Path,
        default=DEFAULT_TOKEN_CLAIM_REPORT,
        help="machine-readable Token Capital claim ceiling receipt",
    )
    parser.add_argument(
        "--source-reconciliation",
        type=Path,
        default=DEFAULT_SOURCE_RECONCILIATION,
        help="machine-readable public-surface source-of-truth reconciliation receipt",
    )
    parser.add_argument(
        "--warnings-fail",
        action="store_true",
        help="treat warnings as failures, not only errors",
    )
    parser.add_argument(
        "--github-material-envelope",
        type=Path,
        help="machine-readable envelope for GitHub README/profile/package/release claims",
    )
    parser.add_argument(
        "--publication-freshness-state",
        type=Path,
        default=DEFAULT_FRESHNESS_STATE,
        help=(
            "required machine-readable public-surface freshness snapshot from "
            "publication-freshness-audit"
        ),
    )
    parser.add_argument(
        "--github-public-surface-report",
        type=Path,
        default=DEFAULT_GITHUB_PUBLIC_SURFACE_REPORT,
        help="machine-readable GitHub public-surface report used to derive required witnesses",
    )
    parser.add_argument(
        "--required-publication-freshness-surface-id",
        action="append",
        default=[],
        help=(
            "explicit required freshness surface id; primarily for focused tests. "
            "If omitted, the required universe is derived from --github-public-surface-report."
        ),
    )
    args = parser.parse_args(argv)

    try:
        token_claim_report = load_required_json(args.token_claim_report, label="token claim report")
        source_reconciliation = load_required_json(
            args.source_reconciliation,
            label="source reconciliation",
        )
        token_claim_patterns = compile_forbidden_claim_patterns(
            token_claim_report,
            report_path=args.token_claim_report,
        )
        findings = check_source_disposition(
            source_reconciliation,
            report_path=args.source_reconciliation,
        )
        github_material_envelope = (
            load_github_material_envelope(args.github_material_envelope)
            if args.github_material_envelope is not None
            else None
        )
        publication_freshness_state = load_publication_freshness_state(
            args.publication_freshness_state
        )
        required_surface_ids = tuple(args.required_publication_freshness_surface_id)
        expected_envelopes: tuple[PublicSurfaceFreshnessEnvelope, ...] = ()
        if not required_surface_ids:
            github_public_surface_report = load_github_public_surface_report(
                args.github_public_surface_report
            )
            expected_envelopes = expected_freshness_envelopes_from_report(
                github_public_surface_report
            )
            required_surface_ids = tuple(envelope.surface_id for envelope in expected_envelopes)
    except RequiredInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    paths = args.paths or list(DEFAULT_TARGETS)
    findings.extend(
        check_publication_freshness_state(
            publication_freshness_state,
            state_path=args.publication_freshness_state,
            required_surface_ids=required_surface_ids,
            expected_envelopes=expected_envelopes,
        )
    )
    for path in iter_files(paths):
        findings.extend(lint_file(path))
        findings.extend(check_token_claim_ceiling(path, token_claim_patterns))
        if github_material_envelope is not None:
            findings.extend(check_github_material_claims(path, github_material_envelope))

    if args.json:
        print(json.dumps([finding_to_dict(f) for f in findings], indent=2, sort_keys=True))
    else:
        for finding in findings:
            print(
                f"{finding.file}:{finding.line}: {finding.level}: {finding.rule}: {finding.message}"
            )

    failing_levels = {"error", "warning"} if args.warnings_fail else {"error"}
    return 1 if any(f.level in failing_levels for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
