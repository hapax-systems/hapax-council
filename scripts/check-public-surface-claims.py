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
from shared.publication_freshness import (
    PublicationFreshnessSnapshot,
    build_publication_freshness_snapshot,
    isoformat_z,
)
from shared.publication_hardening.lint import LintFinding, lint_file

DEFAULT_TOKEN_CLAIM_REPORT = (
    REPO_ROOT / "docs/research/evidence/2026-05-13-token-capital-claim-regate-v2.json"
)
DEFAULT_SOURCE_RECONCILIATION = (
    REPO_ROOT
    / "docs/research/evidence/2026-05-13-public-surface-source-of-truth-reconciliation.json"
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
            f"publication freshness state is malformed: {path}: {exc}"
        ) from exc


def check_publication_freshness_state(
    state: PublicationFreshnessSnapshot,
    *,
    state_path: Path,
) -> list[LintFinding]:
    reassessed = build_publication_freshness_snapshot(
        state.envelopes,
        generated_at=isoformat_z(datetime.now(tz=UTC)),
    )
    blockers = tuple(dict.fromkeys((*state.blockers, *reassessed.blockers)))
    if not blockers:
        return []
    return [
        LintFinding(
            file=str(state_path),
            line=1,
            level="error",
            rule=PUBLICATION_FRESHNESS_RULE,
            message=(f"Publication freshness has public-current blockers: {', '.join(blockers)}"),
        )
    ]


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
        help="machine-readable public-surface freshness snapshot from publication-freshness-audit",
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
        publication_freshness_state = (
            load_publication_freshness_state(args.publication_freshness_state)
            if args.publication_freshness_state is not None
            else None
        )
    except RequiredInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    paths = args.paths or list(DEFAULT_TARGETS)
    if publication_freshness_state is not None:
        findings.extend(
            check_publication_freshness_state(
                publication_freshness_state,
                state_path=args.publication_freshness_state,
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
