#!/usr/bin/env python3
"""Deterministic public-surface claim gate for weblog and omg copy."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
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


def load_github_public_surface_report_for_gate(
    path: Path,
    *,
    skip_live_refresh: bool,
) -> GitHubPublicSurfaceReport:
    if skip_live_refresh:
        return load_github_public_surface_report(path)
    if path != DEFAULT_GITHUB_PUBLIC_SURFACE_REPORT:
        raise RequiredInputError(
            "custom --github-public-surface-report requires "
            "--skip-live-github-public-surface-refresh. Next action: rerun without the "
            "custom report for a fresh GitHub readback, or use the explicit offline flag "
            "only for focused tests/emergency offline diagnosis."
        )
    return refresh_live_github_public_surface_report()


def refresh_live_github_public_surface_report() -> GitHubPublicSurfaceReport:
    with tempfile.TemporaryDirectory(prefix="hapax-public-surface-") as temp_dir:
        temp_root = Path(temp_dir)
        report_path = temp_root / "github-public-surface-live-state-reconcile.json"
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "github-public-surface-reconcile.py"),
                    "--output",
                    str(report_path),
                    "--markdown",
                    str(temp_root / "github-public-surface-live-state-reconcile.md"),
                    "--vault-markdown",
                    str(temp_root / "vault-github-public-surface-live-state-reconcile.md"),
                    "--schema",
                    str(temp_root / "github-public-surface-live-state-report.schema.json"),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            detail = _first_nonempty_line(exc.stderr, exc.stdout) or "timed out after 120s"
            raise RequiredInputError(
                "fresh GitHub public-surface reconcile failed: "
                f"{detail}. Next action: rerun scripts/github-public-surface-reconcile.py "
                "with GitHub credentials/rate limit available and hold release until the "
                "public-surface claim gate passes."
            ) from exc
        if result.returncode != 0:
            detail = _first_nonempty_line(result.stderr, result.stdout) or (
                f"exit code {result.returncode}"
            )
            raise RequiredInputError(
                "fresh GitHub public-surface reconcile failed: "
                f"{detail}. Next action: rerun scripts/github-public-surface-reconcile.py "
                "with GitHub credentials/rate limit available and hold release until the "
                "public-surface claim gate passes."
            )
        return load_github_public_surface_report(report_path)


def _first_nonempty_line(*values: str | None) -> str | None:
    for value in values:
        if not value:
            continue
        for line in value.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
    return None


def expected_freshness_envelopes_from_report(
    report: GitHubPublicSurfaceReport,
) -> tuple[PublicSurfaceFreshnessEnvelope, ...]:
    events = events_from_github_public_surface_report(
        report,
        generated_at=report.generated_at,
    )
    return github_events_to_freshness_envelopes(events, checked_at=report.generated_at)


def check_github_public_surface_drift(
    report: GitHubPublicSurfaceReport,
    *,
    report_path: Path,
) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for drift in report.drift_findings:
        if not _drift_finding_blocks_release(drift):
            continue
        if _drift_finding_is_documented_nonrelease_drift(drift):
            continue
        pending_path = _pending_post_merge_drift_path(drift)
        if pending_path is not None:
            findings.append(
                LintFinding(
                    file=str(report_path),
                    line=1,
                    level="info",
                    rule=GITHUB_PUBLIC_CLAIM_RULE,
                    message=(
                        "GitHub public-surface drift is supplied by this PR but still "
                        f"awaiting post-merge readback for {pending_path}: "
                        f"{drift.finding_id}. Next action: after merge, refresh the "
                        "GitHub public-surface reconcile before claiming public_current."
                    ),
                )
            )
            continue
        findings.append(
            LintFinding(
                file=str(report_path),
                line=1,
                level="error",
                rule=GITHUB_PUBLIC_CLAIM_RULE,
                message=(
                    "GitHub public-surface drift blocks release/public-current claims: "
                    f"{drift.finding_id} ({drift.severity}, {drift.category}, "
                    f"{drift.surface}) blocks {', '.join(drift.blocks) or '<unspecified>'}. "
                    f"{drift.summary} Observed: {drift.observed}. Next action: resolve the "
                    "live-state drift or narrow the public claim before release."
                ),
            )
        )
    return findings


def _drift_finding_blocks_release(drift: Any) -> bool:
    return bool(getattr(drift, "blocks", ())) or getattr(drift, "severity", "") == "blocking"


def _drift_finding_is_documented_nonrelease_drift(drift: Any) -> bool:
    if _drift_finding_is_custom_license_detection(drift):
        return True
    if _drift_finding_has_issue_redirect_config(drift):
        return True
    if _drift_finding_has_readme_freshness_delegation(drift):
        return True
    if _drift_finding_has_documented_metadata_license_posture(drift):
        return True
    return getattr(drift, "category", "") == "closed_repo_pres_claims"


def _drift_finding_is_custom_license_detection(drift: Any) -> bool:
    if getattr(drift, "category", "") != "license_detection":
        return False
    expected = str(getattr(drift, "expected", ""))
    observed = str(getattr(drift, "observed", ""))
    surface = str(getattr(drift, "surface", ""))
    if "PolyForm-Strict-1.0.0" in expected and "NOASSERTION" in observed:
        return True
    return (
        surface == "hapax-systems/hapax-constitution"
        and "CC-BY-NC-ND-4.0" in expected
        and "Apache-2.0" in observed
    )


def _drift_finding_has_issue_redirect_config(drift: Any) -> bool:
    if getattr(drift, "finding_id", "") != "github.settings.issues-enabled-without-template":
        return False
    config = REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml"
    try:
        text = config.read_text(encoding="utf-8")
    except OSError:
        return False
    return "blank_issues_enabled: false" in text and "contact_links:" in text


def _drift_finding_has_readme_freshness_delegation(drift: Any) -> bool:
    if getattr(drift, "finding_id", "") != "github.readme.current-project-spine-stale":
        return False
    try:
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    except OSError:
        return False
    normalized = " ".join(text.split())
    required_phrases = (
        "Public-current readback is not asserted by this README",
        "live GitHub public-surface reconcile",
        "publication freshness audit",
        "release gate output",
    )
    return all(phrase in normalized for phrase in required_phrases)


def _drift_finding_has_documented_metadata_license_posture(drift: Any) -> bool:
    if getattr(drift, "finding_id", "") != "github.metadata.citation-codemeta-zenodo-coherence":
        return False
    expected_files = {
        "CITATION.cff": "PolyForm-Strict-1.0.0",
        "codemeta.json": "polyformproject.org/licenses/strict/1.0.0",
        ".zenodo.json": "other-closed",
        "LICENSE": "PolyForm Strict License 1.0.0",
    }
    for rel_path, expected_text in expected_files.items():
        try:
            text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        except OSError:
            return False
        if expected_text not in text:
            return False
    return True


def _pending_post_merge_drift_path(drift: Any) -> str | None:
    finding_id = str(getattr(drift, "finding_id", ""))
    if finding_id == "github.governance.root-file-missing":
        return "GOVERNANCE.md" if _git_path_status("GOVERNANCE.md") == "A" else None
    if finding_id == "github.readme.current-project-spine-stale":
        return "README.md" if _git_path_status("README.md") == "A" else None
    if finding_id == "github.metadata.citation-codemeta-zenodo-coherence":
        metadata_paths = ("CITATION.cff", "codemeta.json", ".zenodo.json")
        if any(_git_path_status(path) == "A" for path in metadata_paths):
            return "CITATION.cff/codemeta.json/.zenodo.json"
    return None


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
    compare_expected_temporal_fields: bool = True,
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
            compare_temporal_fields=compare_expected_temporal_fields,
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
    blocking_blockers, pending_post_merge_surfaces = _split_pending_post_merge_blockers(blockers)
    if pending_post_merge_surfaces:
        findings.append(
            LintFinding(
                file=str(state_path),
                line=1,
                level="info",
                rule=PUBLICATION_FRESHNESS_RULE,
                message=(
                    "Publication freshness has required public files supplied by this PR "
                    "but still awaiting post-merge public readback: "
                    f"{', '.join(pending_post_merge_surfaces)}. Next action: after merge, "
                    "refresh the publication freshness audit/live-state readback before "
                    "claiming public_current."
                ),
            )
        )
    if not blocking_blockers:
        return findings
    findings.append(
        LintFinding(
            file=str(state_path),
            line=1,
            level="error",
            rule=PUBLICATION_FRESHNESS_RULE,
            message=(
                "Publication freshness has public-current blockers: "
                f"{', '.join(blocking_blockers)}. Next action: refresh the publication freshness "
                "audit/live-state readback and hold release until the blockers clear."
            ),
        )
    )
    return findings


def _split_pending_post_merge_blockers(
    blockers: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    blocking: list[str] = []
    pending_post_merge: list[str] = []
    for blocker in blockers:
        surface_id, freshness_result, blocks = _parse_freshness_blocker(blocker)
        block_set = set(blocks)
        if (
            freshness_result == "missing"
            and "release_authorized" in block_set
            and _local_required_public_file_newly_supplied(surface_id)
        ):
            pending_post_merge.append(surface_id)
            remaining_blocks = tuple(block for block in blocks if block != "release_authorized")
            if any(block != "public_current" for block in remaining_blocks):
                blocking.append(f"{surface_id}:{freshness_result}:{','.join(remaining_blocks)}")
            continue
        blocking.append(blocker)
    return tuple(blocking), tuple(pending_post_merge)


def _parse_freshness_blocker(blocker: str) -> tuple[str, str, tuple[str, ...]]:
    parts = blocker.split(":", 2)
    if len(parts) != 3:
        return blocker, "", ()
    surface_id, freshness_result, block_text = parts
    return surface_id, freshness_result, tuple(block for block in block_text.split(",") if block)


def _local_required_public_file_newly_supplied(surface_id: str) -> bool:
    marker = "hapax-systems/hapax-council."
    if marker not in surface_id:
        return False
    relative_path = surface_id.split(marker, 1)[1]
    if not relative_path:
        return False
    candidate = (REPO_ROOT / relative_path).resolve()
    try:
        candidate.relative_to(REPO_ROOT)
    except ValueError:
        return False
    if not candidate.is_file():
        return False
    relative = candidate.relative_to(REPO_ROOT).as_posix()
    return _git_path_status(relative) == "A"


def _git_path_status(relative_path: str) -> str | None:
    base_ref = _git_merge_base()
    if base_ref is None:
        return None
    result = subprocess.run(
        ["git", "diff", "--name-status", f"{base_ref}...HEAD", "--", relative_path],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    if result.returncode != 0:
        return None
    first_line = _first_nonempty_line(result.stdout)
    if first_line is None:
        return None
    return first_line.split(maxsplit=1)[0]


def _git_merge_base() -> str | None:
    for base_ref in ("origin/main", "main"):
        result = subprocess.run(
            ["git", "merge-base", "HEAD", base_ref],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
        if result.returncode == 0:
            merge_base = _first_nonempty_line(result.stdout)
            if merge_base:
                return merge_base
    return None


def _check_expected_freshness_envelopes(
    *,
    state_path: Path,
    observed_by_surface_id: dict[str, PublicSurfaceFreshnessEnvelope],
    expected_envelopes: tuple[PublicSurfaceFreshnessEnvelope, ...],
    compare_temporal_fields: bool,
) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for expected in expected_envelopes:
        observed = observed_by_surface_id.get(expected.surface_id)
        if observed is None:
            continue
        mismatches = _expected_envelope_mismatches(
            expected=expected,
            observed=observed,
            compare_temporal_fields=compare_temporal_fields,
        )
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
    compare_temporal_fields: bool,
) -> list[str]:
    fields = [
        "freshness_result",
        "source_ref",
        "source_of_truth",
        "evidence_refs",
        "source_hash",
        "rendered_hash",
        "published_hash",
        "readback_hash",
    ]
    if compare_temporal_fields:
        fields[1:1] = ["checked_at", "ttl_s", "expires_at"]
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
        help=(
            "offline machine-readable GitHub public-surface report used only with "
            "--skip-live-github-public-surface-refresh; default gate runs refresh live GitHub "
            "state before deriving required witnesses"
        ),
    )
    parser.add_argument(
        "--skip-live-github-public-surface-refresh",
        action="store_true",
        help=(
            "use --github-public-surface-report as the witness source instead of refreshing "
            "live GitHub state; intended for focused tests and emergency offline diagnosis"
        ),
    )
    parser.add_argument(
        "--required-publication-freshness-surface-id",
        action="append",
        default=[],
        help=(
            "explicit required freshness surface id; primarily for focused tests. "
            "Requires --skip-live-github-public-surface-refresh; if omitted, the required "
            "universe is derived from a fresh live GitHub public-surface readback."
        ),
    )
    args = parser.parse_args(argv)

    try:
        if (
            args.required_publication_freshness_surface_id
            and not args.skip_live_github_public_surface_refresh
        ):
            raise RequiredInputError(
                "--required-publication-freshness-surface-id requires "
                "--skip-live-github-public-surface-refresh. Next action: rerun without explicit "
                "required ids so the gate derives and checks the required universe from fresh "
                "live GitHub readback, or use the offline switch only for focused tests/"
                "emergency offline diagnosis."
            )
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
        github_public_surface_report: GitHubPublicSurfaceReport | None = None
        if not required_surface_ids:
            github_public_surface_report = load_github_public_surface_report_for_gate(
                args.github_public_surface_report,
                skip_live_refresh=args.skip_live_github_public_surface_refresh,
            )
            expected_envelopes = expected_freshness_envelopes_from_report(
                github_public_surface_report
            )
            required_surface_ids = tuple(envelope.surface_id for envelope in expected_envelopes)
    except RequiredInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    paths = args.paths or list(DEFAULT_TARGETS)
    if github_public_surface_report is not None:
        findings.extend(
            check_github_public_surface_drift(
                github_public_surface_report,
                report_path=args.github_public_surface_report,
            )
        )
    findings.extend(
        check_publication_freshness_state(
            publication_freshness_state,
            state_path=args.publication_freshness_state,
            required_surface_ids=required_surface_ids,
            expected_envelopes=expected_envelopes,
            compare_expected_temporal_fields=args.skip_live_github_public_surface_refresh,
        )
    )
    if args.skip_live_github_public_surface_refresh and args.warnings_fail:
        findings.append(
            LintFinding(
                file=str(args.publication_freshness_state),
                line=1,
                level="warning",
                rule=PUBLICATION_FRESHNESS_RULE,
                message=(
                    "Publication freshness ran in offline diagnostic mode. This mode can "
                    "support focused tests or emergency diagnosis, but it cannot authorize "
                    "release/public-current claims. Next action: rerun without "
                    "--skip-live-github-public-surface-refresh so the gate binds witnesses "
                    "to fresh live GitHub readback."
                ),
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
