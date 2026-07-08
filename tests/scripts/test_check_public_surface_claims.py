from __future__ import annotations

import json
import runpy
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shared.github_public_surface import GitHubPublicSurfaceReport
from shared.publication_freshness import (
    PublicationFreshnessSnapshot,
    PublicSurfaceFreshnessEnvelope,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-public-surface-claims.py"
GITHUB_REPORT = REPO_ROOT / "docs/repo-pres/github-public-surface-live-state-reconcile.json"
TEST_FRESHNESS_SURFACE_ID = "github.readme.hapax-systems/example.README.md"


def _write_token_report(
    path: Path,
    *,
    existence_status: str = "denied",
    allowed_claim_ids: list[str] | None = None,
) -> Path:
    path.write_text(
        json.dumps(
            {
                "allowed_claim_ids": allowed_claim_ids or [],
                "claim_classes": {
                    "token_capital_existence_proof": {"status": existence_status},
                    "compounding_value": {"status": "denied"},
                    "answer_faithfulness": {"status": "not_upgraded"},
                    "downstream_contribution": {"status": "not_measured"},
                },
                "forbidden_public_claims": [
                    {
                        "claim_id": "token_capital_existence_proof",
                        "pattern": r"\bexistence[-\s]+proof\b",
                        "reason": "Current post-RAG evidence denies existence-proof language.",
                    },
                    {
                        "claim_id": "compounding_value",
                        "pattern": r"\b(token\s+)?compounding\b|\bcompounding\s+value\b",
                        "reason": "Downstream contribution is not measured.",
                    },
                    {
                        "claim_id": "answer_faithfulness",
                        "pattern": (
                            r"\banswer[-\s]+faithfulness\s+(?:is\s+)?"
                            r"(?:solved|proven|repaired)\b"
                        ),
                        "reason": "Generated answers are currently weak.",
                    },
                    {
                        "claim_id": "downstream_contribution",
                        "pattern": (
                            r"\bdownstream\s+(?:value|contribution)\s+(?:is\s+)?"
                            r"(?:proven|demonstrated|measured)\b"
                        ),
                        "reason": "No downstream contribution ledger has been consumed.",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_source_reconciliation(
    path: Path,
    *,
    unreconciled_items: list[str] | None = None,
    disposition: str = "api_only_with_committed_receipt",
) -> Path:
    items = unreconciled_items or []
    path.write_text(
        json.dumps(
            {
                "summary": {"unreconciled_items": items},
                "rows": [
                    {
                        "item_id": item if items else "support",
                        "disposition": (
                            "unreconciled_no_source_or_receipt" if items else disposition
                        ),
                    }
                    for item in (items or ["support"])
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_github_envelope(path: Path, **overrides: object) -> Path:
    payload = {
        "surface": "release_notes",
        "repo": "ryanklee/hapax-council",
        "source_commit": "abc123",
        "current_source_commit": "abc123",
        "current_source_refs": ["CLAUDE.md"],
        "license_present": True,
        "notice_present": True,
        "citation_present": True,
        "codemeta_present": True,
        "zenodo_present": True,
        "declared_license": "PolyForm-Strict-1.0.0",
        "github_detected_license": "PolyForm-Strict-1.0.0",
        "contributing_present": True,
        "has_issues": False,
        "has_discussions": False,
        "has_wiki": False,
        "sponsor_surface_active": False,
        "settings_witness_refs": ["gh:repos/ryanklee/hapax-council"],
        "research_status": "spec_ready",
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_publication_freshness_state(
    path: Path,
    *,
    generated_at: str = "2026-05-01T00:50:00Z",
    blockers: list[str] | None = None,
    envelopes: list[dict[str, object]] | None = None,
) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": generated_at,
                "producer": "shared.publication_freshness",
                "claim_ceiling": "freshness_witness_only",
                "envelopes": envelopes
                if envelopes is not None
                else [
                    _freshness_envelope(
                        freshness_result="match",
                        rendered_hash="abc123",
                        readback_hash="abc123",
                    )
                ],
                "blockers": blockers or [],
                "warnings": [],
                "anti_overclaim": [
                    (
                        "freshness_witness_does_not_grant_truth_rights_privacy_egress_"
                        "support_monetization_or_research_validity"
                    )
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_profile_report_without_required_readme(path: Path) -> Path:
    payload = json.loads(GITHUB_REPORT.read_text(encoding="utf-8"))
    profile_repo = next(
        repo
        for repo in payload["profile_repo_candidates"]
        if repo["repo_id"] == "hapax-systems/.github"
    )
    profile_repo["files"] = {}
    payload["live_repos"] = []
    payload["profile_repo_candidates"] = [profile_repo]
    payload["local_evidence"]["package_surfaces"] = []
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_old_profile_report_with_readme(path: Path) -> Path:
    payload = json.loads(GITHUB_REPORT.read_text(encoding="utf-8"))
    profile_repo = next(
        repo
        for repo in payload["profile_repo_candidates"]
        if repo["repo_id"] == "hapax-systems/.github"
    )
    payload["generated_at"] = "2020-01-01T00:00:00Z"
    profile_repo["default_branch"] = "main"
    profile_repo["default_branch_sha"] = "a" * 40
    profile_repo["pushed_at"] = "2020-01-01T00:00:00Z"
    profile_repo["files"] = {
        "profile/README.md": {
            "path": "profile/README.md",
            "exists": True,
            "sha": "abc1234",
            "size": 123,
            "html_url": "https://github.com/hapax-systems/.github/blob/main/profile/README.md",
            "evidence": "fixture",
        }
    }
    payload["live_repos"] = []
    payload["profile_repo_candidates"] = [profile_repo]
    payload["local_evidence"]["package_surfaces"] = []
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _freshness_envelope(**overrides: object) -> dict[str, object]:
    checked_at = datetime.now(tz=UTC).replace(microsecond=0) - timedelta(minutes=5)
    expires_at = checked_at + timedelta(seconds=1800)
    payload: dict[str, object] = {
        "schema_version": 1,
        "surface_id": TEST_FRESHNESS_SURFACE_ID,
        "surface_type": "github.readme",
        "source_ref": "docs/repo-pres/example.md",
        "source_of_truth": "fixture",
        "evidence_refs": ["fixture-readback"],
        "checked_at": _isoformat_z(checked_at),
        "ttl_s": 1800,
        "expires_at": _isoformat_z(expires_at),
        "freshness_result": "missing",
        "blocks": [],
    }
    payload.update(overrides)
    return payload


def _isoformat_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _gate_module() -> dict[str, object]:
    return runpy.run_path(str(SCRIPT))


def _run_gate(
    doc: Path,
    token_report: Path,
    source_reconciliation: Path,
    *extra_args: str,
) -> subprocess.CompletedProcess[str]:
    effective_extra_args = list(extra_args)
    if "--publication-freshness-state" not in effective_extra_args:
        freshness_state = _write_publication_freshness_state(doc.parent / "freshness-state.json")
        effective_extra_args.extend(["--publication-freshness-state", str(freshness_state)])
    if (
        "--required-publication-freshness-surface-id" not in effective_extra_args
        and "--github-public-surface-report" not in effective_extra_args
    ):
        effective_extra_args.extend(
            [
                "--skip-live-github-public-surface-refresh",
                "--required-publication-freshness-surface-id",
                TEST_FRESHNESS_SURFACE_ID,
            ]
        )
    elif (
        "--required-publication-freshness-surface-id" in effective_extra_args
        and "--skip-live-github-public-surface-refresh" not in effective_extra_args
    ):
        effective_extra_args.append("--skip-live-github-public-surface-refresh")
    try:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--token-claim-report",
                str(token_report),
                "--source-reconciliation",
                str(source_reconciliation),
                *effective_extra_args,
                str(doc),
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"public surface gate timed out; stdout={exc.stdout!r} stderr={exc.stderr!r}"
        ) from exc


def test_public_surface_claim_gate_fails_absolute_claim(tmp_path: Path) -> None:
    doc = tmp_path / "bad.md"
    doc.write_text("No test results, no push.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")

    result = _run_gate(doc, token_report, source_reconciliation)

    assert result.returncode == 1
    assert "Hapax.PublicClaimOverreach" in result.stdout


def test_public_surface_claim_gate_passes_scoped_claim(tmp_path: Path) -> None:
    doc = tmp_path / "good.md"
    doc.write_text(
        "Missing test evidence blocks the governed push path.\n",
        encoding="utf-8",
    )
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")

    result = _run_gate(doc, token_report, source_reconciliation)

    assert result.returncode == 0
    assert result.stdout == ""


def test_public_surface_claim_gate_warnings_fail_escalates(tmp_path: Path) -> None:
    doc = tmp_path / "warn.md"
    doc.write_text("This is an existence proof.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")

    result = _run_gate(doc, token_report, source_reconciliation, "--warnings-fail")

    assert result.returncode == 1
    assert "Hapax.PublicClaimOverreach" in result.stdout


def test_public_surface_gate_offline_mode_cannot_authorize_release(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "offline-release.md"
    doc.write_text("Bounded public copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")

    result = _run_gate(doc, token_report, source_reconciliation, "--warnings-fail")

    assert result.returncode == 1
    assert "Publication freshness ran in offline diagnostic mode" in result.stdout
    assert "cannot authorize release/public-current claims" in result.stdout


def test_public_surface_claim_gate_ignores_unsupported_file_suffix(tmp_path: Path) -> None:
    doc = tmp_path / "bad.txt"
    doc.write_text("No test results, no push.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")

    result = _run_gate(doc, token_report, source_reconciliation)

    assert result.returncode == 0
    assert result.stdout == ""


def test_public_surface_gate_allows_bounded_repair_case_language(tmp_path: Path) -> None:
    doc = tmp_path / "repair.md"
    doc.write_text(
        "Nomic availability is repaired and documents_v2 is a non-destructive repair case.\n",
        encoding="utf-8",
    )
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")

    result = _run_gate(doc, token_report, source_reconciliation)

    assert result.returncode == 0
    assert result.stdout == ""


def test_public_surface_gate_fails_denied_token_capital_upgrade_language(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "bad-token-capital.md"
    doc.write_text(
        (
            "Token Capital is an existence proof.\n"
            "The corpus demonstrates compounding value.\n"
            "Answer faithfulness is proven.\n"
            "Downstream value demonstrated.\n"
        ),
        encoding="utf-8",
    )
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")

    result = _run_gate(doc, token_report, source_reconciliation)

    assert result.returncode == 1
    assert "Hapax.TokenCapitalClaimCeiling" in result.stdout
    assert "token_capital_existence_proof" in result.stdout
    assert "compounding_value" in result.stdout
    assert "answer_faithfulness" in result.stdout
    assert "downstream_contribution" in result.stdout


def test_public_surface_gate_honors_future_claim_permission(tmp_path: Path) -> None:
    doc = tmp_path / "future.md"
    doc.write_text("This future receipt allows existence proof wording.\n", encoding="utf-8")
    token_report = _write_token_report(
        tmp_path / "token-report.json",
        existence_status="bounded_supported",
        allowed_claim_ids=["token_capital_existence_proof"],
    )
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")

    result = _run_gate(doc, token_report, source_reconciliation)

    assert result.returncode == 0
    assert "Hapax.TokenCapitalClaimCeiling" not in result.stdout


def test_public_surface_gate_fails_missing_source_disposition(tmp_path: Path) -> None:
    doc = tmp_path / "safe.md"
    doc.write_text("Scoped governed-path copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(
        tmp_path / "source-report.json",
        unreconciled_items=["unbacked-entry"],
    )

    result = _run_gate(doc, token_report, source_reconciliation)

    assert result.returncode == 1
    assert "Hapax.PublicSurfaceSourceDisposition" in result.stdout
    assert "unbacked-entry" in result.stdout


def test_public_surface_gate_allows_api_only_receipt_disposition(tmp_path: Path) -> None:
    doc = tmp_path / "safe.md"
    doc.write_text("Scoped governed-path copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(
        tmp_path / "source-report.json",
        disposition="api_only_with_committed_receipt",
    )

    result = _run_gate(doc, token_report, source_reconciliation)

    assert result.returncode == 0
    assert result.stdout == ""


def test_public_surface_gate_fails_publication_freshness_blocker(tmp_path: Path) -> None:
    doc = tmp_path / "fresh.md"
    doc.write_text("Bounded public copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")
    freshness_state = _write_publication_freshness_state(
        tmp_path / "freshness-state.json",
        blockers=["github.readme.hapax-systems/example.README.md:missing:public_current"],
    )

    result = _run_gate(
        doc,
        token_report,
        source_reconciliation,
        "--publication-freshness-state",
        str(freshness_state),
    )

    assert result.returncode == 1
    assert "Hapax.PublicationFreshness" in result.stdout
    assert "github.readme.hapax-systems/example.README.md" in result.stdout
    assert (
        "Next action: refresh the publication freshness audit/live-state readback" in result.stdout
    )


def test_public_surface_gate_allows_local_required_file_pending_post_merge_readback(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "fresh-pending-local.md"
    doc.write_text("Bounded public copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")
    pending_surface_id = "github.security_governance.hapax-systems/hapax-council.GOVERNANCE.md"
    freshness_state = _write_publication_freshness_state(
        tmp_path / "freshness-state.json",
        blockers=[f"{pending_surface_id}:missing:public_current,release_authorized"],
    )

    result = _run_gate(
        doc,
        token_report,
        source_reconciliation,
        "--publication-freshness-state",
        str(freshness_state),
    )

    assert result.returncode == 0
    assert "awaiting post-merge public readback" in result.stdout
    assert pending_surface_id in result.stdout


def test_public_surface_gate_keeps_existing_required_file_missing_blocker(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "fresh-existing-missing.md"
    doc.write_text("Bounded public copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")
    existing_surface_id = "github.readme.hapax-systems/hapax-council.README.md"
    freshness_state = _write_publication_freshness_state(
        tmp_path / "freshness-state.json",
        blockers=[f"{existing_surface_id}:missing:public_current,release_authorized"],
    )

    result = _run_gate(
        doc,
        token_report,
        source_reconciliation,
        "--publication-freshness-state",
        str(freshness_state),
    )

    assert result.returncode == 1
    assert "Publication freshness has public-current blockers" in result.stdout
    assert existing_surface_id in result.stdout
    assert "awaiting post-merge public readback" not in result.stdout


def test_public_surface_gate_missing_publication_freshness_state_exits_2(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "fresh-missing.md"
    doc.write_text("Bounded public copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")

    result = _run_gate(
        doc,
        token_report,
        source_reconciliation,
        "--publication-freshness-state",
        str(tmp_path / "missing-freshness-state.json"),
    )

    assert result.returncode == 2
    assert "publication freshness state not found" in result.stderr


def test_public_surface_gate_empty_publication_freshness_state_blocks(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "fresh-empty.md"
    doc.write_text("Bounded public copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")
    freshness_state = _write_publication_freshness_state(
        tmp_path / "freshness-state.json",
        envelopes=[],
    )

    result = _run_gate(
        doc,
        token_report,
        source_reconciliation,
        "--publication-freshness-state",
        str(freshness_state),
    )

    assert result.returncode == 1
    assert "Publication freshness state has no surface envelopes" in result.stdout


def test_public_surface_gate_recomputes_freshness_blockers_from_envelopes(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "fresh-forged.md"
    doc.write_text("Bounded public copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")
    freshness_state = _write_publication_freshness_state(
        tmp_path / "freshness-state.json",
        blockers=[],
        envelopes=[_freshness_envelope()],
    )

    result = _run_gate(
        doc,
        token_report,
        source_reconciliation,
        "--publication-freshness-state",
        str(freshness_state),
    )

    assert result.returncode == 1
    assert "Hapax.PublicationFreshness" in result.stdout
    assert "missing" in result.stdout


def test_public_surface_gate_blocks_missing_required_freshness_witness(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "fresh-incomplete.md"
    doc.write_text("Bounded public copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")
    missing_required_id = "github.security_governance.hapax-systems/example.GOVERNANCE.md"
    freshness_state = _write_publication_freshness_state(
        tmp_path / "freshness-state.json",
        blockers=[],
        envelopes=[
            _freshness_envelope(
                freshness_result="match",
                rendered_hash="abc123",
                readback_hash="abc123",
            )
        ],
    )

    result = _run_gate(
        doc,
        token_report,
        source_reconciliation,
        "--publication-freshness-state",
        str(freshness_state),
        "--required-publication-freshness-surface-id",
        TEST_FRESHNESS_SURFACE_ID,
        "--required-publication-freshness-surface-id",
        missing_required_id,
    )

    assert result.returncode == 1
    assert "Hapax.PublicationFreshness" in result.stdout
    assert "omits required public-surface witnesses" in result.stdout
    assert missing_required_id in result.stdout


def test_public_surface_gate_rejects_forged_witness_against_live_report(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "fresh-forged-report.md"
    doc.write_text("Bounded public copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")
    github_report = _write_profile_report_without_required_readme(tmp_path / "github-report.json")
    forged_surface_id = "github.profile.hapax-systems/.github.profile/README.md"
    freshness_state = _write_publication_freshness_state(
        tmp_path / "freshness-state.json",
        blockers=[],
        envelopes=[
            _freshness_envelope(
                surface_id=forged_surface_id,
                surface_type="github.profile",
                source_ref="docs/repo-pres/github-public-surface-live-state-reconcile.json",
                source_of_truth="github_public_surface_report",
                evidence_refs=["gh:contents/hapax-systems/.github/profile/README.md"],
                freshness_result="match",
                rendered_hash="abc123",
                readback_hash="abc123",
            )
        ],
    )

    result = _run_gate(
        doc,
        token_report,
        source_reconciliation,
        "--publication-freshness-state",
        str(freshness_state),
        "--skip-live-github-public-surface-refresh",
        "--github-public-surface-report",
        str(github_report),
    )

    assert result.returncode == 1
    assert "Hapax.PublicationFreshness" in result.stdout
    assert "does not match live report evidence" in result.stdout
    assert forged_surface_id in result.stdout
    assert "freshness_result expected missing observed match" in result.stdout


def test_public_surface_gate_rejects_custom_report_without_offline_switch(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "fresh-custom-report.md"
    doc.write_text("Bounded public copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")
    github_report = _write_profile_report_without_required_readme(tmp_path / "github-report.json")
    freshness_state = _write_publication_freshness_state(
        tmp_path / "freshness-state.json",
        blockers=[],
        envelopes=[],
    )

    result = _run_gate(
        doc,
        token_report,
        source_reconciliation,
        "--publication-freshness-state",
        str(freshness_state),
        "--github-public-surface-report",
        str(github_report),
    )

    assert result.returncode == 2
    assert "custom --github-public-surface-report requires" in result.stderr
    assert "--skip-live-github-public-surface-refresh" in result.stderr


def test_public_surface_gate_rejects_explicit_required_ids_without_offline_switch(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "fresh-explicit-required-id.md"
    doc.write_text("Bounded public copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")
    freshness_state = _write_publication_freshness_state(
        tmp_path / "freshness-state.json",
        blockers=[],
        envelopes=[
            _freshness_envelope(
                freshness_result="match",
                rendered_hash="abc123",
                readback_hash="abc123",
            )
        ],
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--token-claim-report",
            str(token_report),
            "--source-reconciliation",
            str(source_reconciliation),
            "--publication-freshness-state",
            str(freshness_state),
            "--required-publication-freshness-surface-id",
            TEST_FRESHNESS_SURFACE_ID,
            str(doc),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 2
    assert "--required-publication-freshness-surface-id requires" in result.stderr
    assert "--skip-live-github-public-surface-refresh" in result.stderr


def test_live_expected_comparison_allows_independent_freshness_timestamp(
    tmp_path: Path,
) -> None:
    checked_at = datetime.now(tz=UTC).replace(microsecond=0) - timedelta(minutes=5)
    expected_checked_at = checked_at + timedelta(minutes=1)
    observed = PublicSurfaceFreshnessEnvelope.model_validate(
        _freshness_envelope(
            checked_at=_isoformat_z(checked_at),
            expires_at=_isoformat_z(checked_at + timedelta(seconds=1800)),
            freshness_result="match",
            source_hash="same-source",
            rendered_hash="same-content",
            published_hash="same-content",
            readback_hash="same-content",
        )
    )
    expected = PublicSurfaceFreshnessEnvelope.model_validate(
        _freshness_envelope(
            checked_at=_isoformat_z(expected_checked_at),
            expires_at=_isoformat_z(expected_checked_at + timedelta(seconds=1800)),
            freshness_result="match",
            source_hash="same-source",
            rendered_hash="same-content",
            published_hash="same-content",
            readback_hash="same-content",
        )
    )
    state = PublicationFreshnessSnapshot(
        generated_at=_isoformat_z(datetime.now(tz=UTC).replace(microsecond=0)),
        envelopes=(observed,),
    )
    gate = _gate_module()
    check_publication_freshness_state = gate["check_publication_freshness_state"]

    live_findings = check_publication_freshness_state(
        state,
        state_path=tmp_path / "freshness-state.json",
        required_surface_ids=(TEST_FRESHNESS_SURFACE_ID,),
        expected_envelopes=(expected,),
        compare_expected_temporal_fields=False,
    )
    offline_findings = check_publication_freshness_state(
        state,
        state_path=tmp_path / "freshness-state.json",
        required_surface_ids=(TEST_FRESHNESS_SURFACE_ID,),
        expected_envelopes=(expected,),
        compare_expected_temporal_fields=True,
    )

    assert live_findings == []
    assert len(offline_findings) == 1
    assert "checked_at expected" in offline_findings[0].message


def test_public_surface_gate_blocks_live_state_drift_finding(tmp_path: Path) -> None:
    payload = json.loads(GITHUB_REPORT.read_text(encoding="utf-8"))
    payload["drift_findings"] = [
        {
            "finding_id": "github.license.example.registry-mismatch",
            "severity": "blocking",
            "category": "license_detection",
            "surface": "hapax-systems/example",
            "status": "blocked",
            "summary": "GitHub detected license does not match the repo registry policy.",
            "expected": "GitHub public license surfaces align to MIT.",
            "observed": "GitHub detects NOASSERTION.",
            "evidence_refs": ["fixture"],
            "blocks": ["github-public-claim-evidence-gate"],
        }
    ]
    report = GitHubPublicSurfaceReport.model_validate(payload)
    gate = _gate_module()
    check_github_public_surface_drift = gate["check_github_public_surface_drift"]

    findings = check_github_public_surface_drift(
        report,
        report_path=tmp_path / "github-report.json",
    )

    assert len(findings) == 1
    assert findings[0].level == "error"
    assert "blocks release/public-current claims" in findings[0].message
    assert "github.license.example.registry-mismatch" in findings[0].message


def test_public_surface_gate_allows_documented_polyform_license_detection(
    tmp_path: Path,
) -> None:
    payload = json.loads(GITHUB_REPORT.read_text(encoding="utf-8"))
    payload["drift_findings"] = [
        {
            "finding_id": "github.license.hapax-council.apache-vs-polyform",
            "severity": "blocking",
            "category": "license_detection",
            "surface": "hapax-systems/hapax-council",
            "status": "blocked",
            "summary": "GitHub/root license detection contradicts the repo registry policy.",
            "expected": "GitHub public license surfaces align to PolyForm-Strict-1.0.0.",
            "observed": "GitHub detects NOASSERTION.",
            "evidence_refs": ["fixture"],
            "blocks": ["github-readme-profile-current-project-refresh"],
        }
    ]
    report = GitHubPublicSurfaceReport.model_validate(payload)
    gate = _gate_module()
    check_github_public_surface_drift = gate["check_github_public_surface_drift"]

    findings = check_github_public_surface_drift(
        report,
        report_path=tmp_path / "github-report.json",
    )

    assert findings == []


def test_public_surface_gate_rejects_redated_live_report_witness(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "fresh-redated-report.md"
    doc.write_text("Bounded public copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")
    github_report = _write_old_profile_report_with_readme(tmp_path / "github-report.json")
    forged_surface_id = "github.profile.hapax-systems/.github.profile/README.md"
    freshness_state = _write_publication_freshness_state(
        tmp_path / "freshness-state.json",
        blockers=[],
        envelopes=[
            _freshness_envelope(
                surface_id=forged_surface_id,
                surface_type="github.profile",
                source_ref="docs/repo-pres/github-public-surface-live-state-reconcile.json",
                source_of_truth="github_public_surface_report",
                evidence_refs=["gh:contents/hapax-systems/.github/profile/README.md"],
                freshness_result="match",
                rendered_hash="abc1234",
                readback_hash="abc1234",
            )
        ],
    )

    result = _run_gate(
        doc,
        token_report,
        source_reconciliation,
        "--publication-freshness-state",
        str(freshness_state),
        "--skip-live-github-public-surface-refresh",
        "--github-public-surface-report",
        str(github_report),
    )

    assert result.returncode == 1
    assert "Hapax.PublicationFreshness" in result.stdout
    assert "does not match live report evidence" in result.stdout
    assert forged_surface_id in result.stdout
    assert "checked_at expected 2020-01-01T00:00:00Z" in result.stdout


def test_public_surface_gate_blocks_future_dated_freshness_snapshot(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "fresh-future-snapshot.md"
    doc.write_text("Bounded public copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")
    future_generated_at = _isoformat_z(
        datetime.now(tz=UTC).replace(microsecond=0) + timedelta(days=1)
    )
    freshness_state = _write_publication_freshness_state(
        tmp_path / "freshness-state.json",
        generated_at=future_generated_at,
        blockers=[],
        envelopes=[
            _freshness_envelope(
                freshness_result="match",
                rendered_hash="abc123",
                readback_hash="abc123",
            )
        ],
    )

    result = _run_gate(
        doc,
        token_report,
        source_reconciliation,
        "--publication-freshness-state",
        str(freshness_state),
    )

    assert result.returncode == 1
    assert "Hapax.PublicationFreshness" in result.stdout
    assert "future-dated witnesses" in result.stdout
    assert "snapshot.generated_at" in result.stdout


def test_public_surface_gate_blocks_future_dated_freshness_envelope(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "fresh-future-envelope.md"
    doc.write_text("Bounded public copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")
    future_checked_at = datetime.now(tz=UTC).replace(microsecond=0) + timedelta(days=1)
    future_expires_at = future_checked_at + timedelta(seconds=1800)
    freshness_state = _write_publication_freshness_state(
        tmp_path / "freshness-state.json",
        blockers=[],
        envelopes=[
            _freshness_envelope(
                checked_at=_isoformat_z(future_checked_at),
                expires_at=_isoformat_z(future_expires_at),
                freshness_result="match",
                rendered_hash="abc123",
                readback_hash="abc123",
            )
        ],
    )

    result = _run_gate(
        doc,
        token_report,
        source_reconciliation,
        "--publication-freshness-state",
        str(freshness_state),
    )

    assert result.returncode == 1
    assert "Hapax.PublicationFreshness" in result.stdout
    assert "future-dated witnesses" in result.stdout
    assert "github.readme.hapax-systems/example.README.md.checked_at" in result.stdout


def test_public_surface_gate_marks_expired_freshness_state_stale(tmp_path: Path) -> None:
    doc = tmp_path / "fresh-expired.md"
    doc.write_text("Bounded public copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")
    freshness_state = _write_publication_freshness_state(
        tmp_path / "freshness-state.json",
        blockers=[],
        envelopes=[
            _freshness_envelope(
                checked_at="2000-01-01T00:00:00Z",
                expires_at="2000-01-01T00:30:00Z",
                freshness_result="match",
                rendered_hash="abc123",
                readback_hash="abc123",
            )
        ],
    )

    result = _run_gate(
        doc,
        token_report,
        source_reconciliation,
        "--publication-freshness-state",
        str(freshness_state),
    )

    assert result.returncode == 1
    assert "Hapax.PublicationFreshness" in result.stdout
    assert "stale" in result.stdout


def test_public_surface_gate_rejects_forged_oversized_freshness_ttl(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "fresh-forged-ttl.md"
    doc.write_text("Bounded public copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")
    freshness_state = _write_publication_freshness_state(
        tmp_path / "freshness-state.json",
        blockers=[],
        envelopes=[
            _freshness_envelope(
                checked_at="2020-01-01T00:00:00Z",
                ttl_s=315_360_000,
                expires_at="2029-12-29T00:00:00Z",
                freshness_result="match",
                rendered_hash="abc123",
                readback_hash="abc123",
            )
        ],
    )

    result = _run_gate(
        doc,
        token_report,
        source_reconciliation,
        "--publication-freshness-state",
        str(freshness_state),
    )

    assert result.returncode == 2
    assert "publication freshness state is malformed" in result.stderr
    assert "ttl_s must be <=" in result.stderr
    assert "Next action: regenerate or repair the state" in result.stderr


def test_public_surface_gate_reports_malformed_freshness_state_generated_at(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "fresh-bad-generated-at.md"
    doc.write_text("Bounded public copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")
    freshness_state = _write_publication_freshness_state(
        tmp_path / "freshness-state.json",
        generated_at="not-a-timestamp",
        blockers=[],
        envelopes=[
            _freshness_envelope(
                freshness_result="match",
                rendered_hash="abc123",
                readback_hash="abc123",
            )
        ],
    )

    result = _run_gate(
        doc,
        token_report,
        source_reconciliation,
        "--publication-freshness-state",
        str(freshness_state),
    )

    assert result.returncode == 1
    assert "Hapax.PublicationFreshness" in result.stdout
    assert "malformed timestamp snapshot.generated_at" in result.stdout
    assert "Next action: regenerate the publication freshness audit/live-state" in result.stdout


def test_public_surface_gate_malformed_freshness_state_exits_2_with_next_action(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "fresh-malformed.md"
    doc.write_text("Bounded public copy.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")
    freshness_state = tmp_path / "freshness-state.json"
    freshness_state.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")

    result = _run_gate(
        doc,
        token_report,
        source_reconciliation,
        "--publication-freshness-state",
        str(freshness_state),
    )

    assert result.returncode == 2
    assert "publication freshness state is malformed" in result.stderr
    assert "Next action: regenerate or repair the state" in result.stderr


def test_public_surface_gate_json_includes_v2_rule_ids(tmp_path: Path) -> None:
    doc = tmp_path / "bad.md"
    doc.write_text("Token Capital is an existence proof.\n", encoding="utf-8")
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")

    result = _run_gate(doc, token_report, source_reconciliation, "--json")

    assert result.returncode == 1
    findings = json.loads(result.stdout)
    assert {finding["rule"] for finding in findings} >= {
        "Hapax.PublicClaimOverreach",
        "Hapax.TokenCapitalClaimCeiling",
    }


def test_public_surface_gate_missing_required_receipt_exits_2(tmp_path: Path) -> None:
    doc = tmp_path / "safe.md"
    doc.write_text("Scoped governed-path copy.\n", encoding="utf-8")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")

    result = _run_gate(doc, tmp_path / "missing-token-report.json", source_reconciliation)

    assert result.returncode == 2
    assert "token claim report not found" in result.stderr


def test_public_surface_gate_applies_github_material_envelope(tmp_path: Path) -> None:
    doc = tmp_path / "release.md"
    doc.write_text(
        "This release is an empirically validated public artifact ready for monetization.\n",
        encoding="utf-8",
    )
    token_report = _write_token_report(tmp_path / "token-report.json")
    source_reconciliation = _write_source_reconciliation(tmp_path / "source-report.json")
    github_envelope = _write_github_envelope(tmp_path / "github-envelope.json")

    result = _run_gate(
        doc,
        token_report,
        source_reconciliation,
        "--github-material-envelope",
        str(github_envelope),
    )

    assert result.returncode == 1
    assert "Hapax.GitHubPublicClaimEvidenceGate" in result.stdout
    assert "research_status" in result.stdout
    assert "monetization" in result.stdout
