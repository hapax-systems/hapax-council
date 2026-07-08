from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-public-surface-claims.py"


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


def _freshness_envelope(**overrides: object) -> dict[str, object]:
    checked_at = datetime.now(tz=UTC).replace(microsecond=0) - timedelta(minutes=5)
    expires_at = checked_at + timedelta(seconds=1800)
    payload: dict[str, object] = {
        "schema_version": 1,
        "surface_id": "github.readme.hapax-systems/example.README.md",
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
