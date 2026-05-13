from __future__ import annotations

import json
import subprocess
import sys
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


def _run_gate(
    doc: Path,
    token_report: Path,
    source_reconciliation: Path,
    *extra_args: str,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--token-claim-report",
                str(token_report),
                "--source-reconciliation",
                str(source_reconciliation),
                *extra_args,
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
