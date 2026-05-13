#!/usr/bin/env python3
"""Re-gate Token Capital claims after post-audit RAG evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GENERATED_AT = "2026-05-13T00:00:00Z"
DEFAULT_JSON = REPO_ROOT / "docs/research/evidence/2026-05-13-token-capital-claim-regate-v2.json"
DEFAULT_MARKDOWN = REPO_ROOT / "docs/research/evidence/2026-05-13-token-capital-claim-regate-v2.md"
DEFAULT_VAULT_MARKDOWN = (
    Path.home()
    / "Documents/Personal/20-projects/hapax-research/audit/"
    / "2026-05-13-token-capital-claim-regate-v2.md"
)


@dataclass(frozen=True)
class EvidenceArtifact:
    artifact_id: str
    title: str
    path: Path
    pr: int
    role: str


DEFAULT_EVIDENCE: tuple[EvidenceArtifact, ...] = (
    EvidenceArtifact(
        artifact_id="nomic-runtime-repair",
        title="Nomic embedding runtime repair",
        path=REPO_ROOT
        / "docs/research/evidence/2026-05-12-nomic-rag-embedding-smoke-and-golden-receipt.md",
        pr=3163,
        role="embedding availability evidence",
    ),
    EvidenceArtifact(
        artifact_id="documents-v2-full-backfill",
        title="RAG documents_v2 full backfill and parser coverage",
        path=REPO_ROOT
        / "docs/research/2026-05-13-rag-documents-v2-full-backfill-and-parser-coverage.md",
        pr=3211,
        role="retrieval substrate evidence",
    ),
    EvidenceArtifact(
        artifact_id="answer-faithfulness",
        title="RAG answer faithfulness and downstream contribution evaluation",
        path=REPO_ROOT
        / "docs/research/2026-05-13-rag-answer-faithfulness-and-downstream-contribution-eval.md",
        pr=3212,
        role="answer-level evidence",
    ),
    EvidenceArtifact(
        artifact_id="corpus-utilization-denominator",
        title="Token Capital corpus utilization denominator",
        path=REPO_ROOT / "docs/research/2026-05-13-token-capital-corpus-utilization-denominator.md",
        pr=3213,
        role="corpus denominator evidence",
    ),
    EvidenceArtifact(
        artifact_id="public-surface-source-of-truth",
        title="Public surface source-of-truth reconciliation",
        path=REPO_ROOT
        / "docs/research/evidence/2026-05-13-public-surface-source-of-truth-reconciliation.md",
        pr=3214,
        role="public surface evidence",
    ),
)

CLAIM_CLASSES: dict[str, dict[str, Any]] = {
    "nomic_embedding_availability": {
        "status": "supported",
        "public_ceiling": (
            "Nomic embedding availability is repaired: the configured stable alias is "
            "available and dimensionality validation passes."
        ),
        "evidence": ["nomic-runtime-repair"],
    },
    "documents_v2_repair": {
        "status": "bounded_supported",
        "public_ceiling": (
            "documents_v2 is a non-destructive approved-corpus repair case with explicit "
            "parser coverage accounting."
        ),
        "evidence": ["documents-v2-full-backfill"],
    },
    "retrieval_improvement": {
        "status": "bounded_supported",
        "public_ceiling": (
            "Full documents_v2 materially improves golden-query retrieval over legacy "
            "documents, while remaining weaker than the focused seed."
        ),
        "evidence": ["documents-v2-full-backfill"],
    },
    "corpus_utilization_denominator": {
        "status": "measurement_infrastructure_only",
        "public_ceiling": (
            "The generated/persisted corpus denominator is explicit; indexing, retrieval, "
            "answer context, and downstream contribution remain separate numerators."
        ),
        "evidence": ["corpus-utilization-denominator"],
    },
    "answer_faithfulness": {
        "status": "not_upgraded",
        "public_ceiling": (
            "Answer-level evaluation is instrumented, but current generated answers are "
            "not publication-grade and do not support answer-faithfulness claims."
        ),
        "evidence": ["answer-faithfulness"],
    },
    "downstream_contribution": {
        "status": "not_measured",
        "public_ceiling": (
            "Downstream contribution has not been measured; no value or economic "
            "contribution claim is supported."
        ),
        "evidence": ["answer-faithfulness", "corpus-utilization-denominator"],
    },
    "public_source_of_truth": {
        "status": "supported",
        "public_ceiling": (
            "Live public weblog/OMG entries have source-of-truth disposition rows; "
            "this is a source receipt, not a Token Capital claim upgrade."
        ),
        "evidence": ["public-surface-source-of-truth"],
    },
    "token_capital_existence_proof": {
        "status": "denied",
        "public_ceiling": (
            "Denied. The current evidence supports only a hypothesis and repair-case "
            "narrative, not an existence proof."
        ),
        "evidence": [
            "documents-v2-full-backfill",
            "answer-faithfulness",
            "corpus-utilization-denominator",
        ],
    },
    "token_appreciation": {
        "status": "denied",
        "public_ceiling": (
            "Denied. There is no measurement showing generated tokens appreciate as assets."
        ),
        "evidence": ["corpus-utilization-denominator"],
    },
    "compounding_value": {
        "status": "denied",
        "public_ceiling": (
            "Denied. Retrieval and answer-context exposure do not prove compounding value."
        ),
        "evidence": ["answer-faithfulness", "corpus-utilization-denominator"],
    },
}

FORBIDDEN_PUBLIC_CLAIMS: tuple[dict[str, str], ...] = (
    {
        "claim_id": "token_capital_existence_proof",
        "pattern": r"\bexistence[-\s]+proof\b",
        "reason": "Current post-RAG evidence denies existence-proof language.",
    },
    {
        "claim_id": "token_appreciation",
        "pattern": r"\bappreciat(?:e|ing|ion)\b.*\btoken",
        "reason": "No appreciation metric or asset-value run exists.",
    },
    {
        "claim_id": "compounding_value",
        "pattern": r"\b(token\s+)?compounding\b|\bcompounding\s+value\b",
        "reason": "Downstream contribution is not measured.",
    },
    {
        "claim_id": "answer_faithfulness",
        "pattern": r"\banswer[-\s]+faithfulness\s+(?:is\s+)?(?:solved|proven|repaired)\b",
        "reason": "Generated answers are currently weak on the answer suite.",
    },
    {
        "claim_id": "downstream_contribution",
        "pattern": (
            r"\bdownstream\s+(?:value|contribution)\s+(?:is\s+)?"
            r"(?:proven|demonstrated|measured)\b"
        ),
        "reason": "No downstream contribution ledger has been consumed.",
    },
)

REQUIRED_NEXT_EVIDENCE: tuple[str, ...] = (
    "durable downstream contribution ledger",
    "materially improved generated-answer support and faithfulness",
    "ranking/source-prior diagnosis for full documents_v2",
    "future public claim gate receipt that explicitly permits stronger language",
)


def display_path(path: Path) -> str:
    path = path.expanduser()
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        pass
    home = Path.home()
    try:
        return "~/" + str(path.resolve().relative_to(home))
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence_to_row(artifact: EvidenceArtifact) -> dict[str, Any]:
    exists = artifact.path.is_file()
    return {
        "artifact_id": artifact.artifact_id,
        "title": artifact.title,
        "path": display_path(artifact.path),
        "pr": artifact.pr,
        "role": artifact.role,
        "exists": exists,
        "sha256": sha256_file(artifact.path) if exists else None,
        "bytes": artifact.path.stat().st_size if exists else None,
    }


def claim_upgrade_allowed(report: Mapping[str, Any], claim_id: str) -> bool:
    claim_classes = report.get("claim_classes", {})
    if not isinstance(claim_classes, Mapping):
        return False
    claim = claim_classes.get(claim_id)
    if not isinstance(claim, Mapping):
        return False
    return claim.get("status") in {"supported", "bounded_supported"}


def build_report(
    evidence: Sequence[EvidenceArtifact] = DEFAULT_EVIDENCE,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or DEFAULT_GENERATED_AT
    evidence_rows = [evidence_to_row(artifact) for artifact in evidence]
    missing = [row["artifact_id"] for row in evidence_rows if not row["exists"]]
    claim_classes = json.loads(json.dumps(CLAIM_CLASSES))
    denied = [claim_id for claim_id, claim in claim_classes.items() if claim["status"] == "denied"]
    not_upgraded = [
        claim_id
        for claim_id, claim in claim_classes.items()
        if claim["status"] in {"not_upgraded", "not_measured", "measurement_infrastructure_only"}
    ]
    report = {
        "generated_at": generated_at,
        "generated_by": "scripts/token_capital_claim_regate.py",
        "authority_case": "REQ-20260513-token-capital-public-surface-regate-v2",
        "overall_decision": "claim_upgrade_denied",
        "claim_ceiling": {
            "status": "hypothesis_and_repair_case_only",
            "allowed_summary": (
                "Nomic availability, documents_v2 repair-case retrieval improvement, "
                "denominator measurement infrastructure, and public source-of-truth "
                "receipts may be described with their limits."
            ),
            "denied_summary": (
                "Token Capital existence proof, token appreciation, compounding value, "
                "publication-grade answer faithfulness, and downstream contribution "
                "claims remain unsupported."
            ),
        },
        "evidence_artifacts": evidence_rows,
        "missing_evidence_artifacts": missing,
        "claim_classes": claim_classes,
        "denied_claim_ids": denied,
        "not_upgraded_claim_ids": not_upgraded,
        "forbidden_public_claims": list(FORBIDDEN_PUBLIC_CLAIMS),
        "required_next_evidence": list(REQUIRED_NEXT_EVIDENCE),
        "gate_predicates": {
            "all_dependency_receipts_present": not missing,
            "claim_upgrade_allowed": False,
            "token_capital_exists_proof_allowed": False,
            "answer_faithfulness_upgrade_allowed": False,
            "downstream_contribution_upgrade_allowed": False,
            "compounding_value_upgrade_allowed": False,
        },
    }
    report["allowed_claim_ids"] = [
        claim_id for claim_id in claim_classes if claim_upgrade_allowed(report, claim_id)
    ]
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "---",
        'title: "Token Capital Claim Re-Gate V2"',
        "date: 2026-05-13",
        f"authority_case: {report['authority_case']}",
        "status: receipt",
        "mutation_surface: source_docs",
        "---",
        "",
        "# Token Capital Claim Re-Gate V2",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        "## Decision",
        "",
        f"- Overall decision: `{report['overall_decision']}`",
        f"- Claim ceiling: `{report['claim_ceiling']['status']}`",
        f"- Allowed summary: {report['claim_ceiling']['allowed_summary']}",
        f"- Denied summary: {report['claim_ceiling']['denied_summary']}",
        "",
        "## Evidence Artifacts",
        "",
        "| Artifact | PR | Role | Present | SHA-256 |",
        "|---|---:|---|---:|---|",
    ]
    for row in report["evidence_artifacts"]:
        sha = row["sha256"][:12] if row["sha256"] else "missing"
        lines.append(
            f"| `{row['path']}` | #{row['pr']} | {row['role']} | `{row['exists']}` | `{sha}` |"
        )

    lines.extend(
        [
            "",
            "## Claim Classes",
            "",
            "| Claim class | Status | Public ceiling |",
            "|---|---|---|",
        ]
    )
    for claim_id, claim in report["claim_classes"].items():
        lines.append(f"| `{claim_id}` | `{claim['status']}` | {claim['public_ceiling']} |")

    lines.extend(
        [
            "",
            "## Forbidden Public Claim Patterns",
            "",
        ]
    )
    for item in report["forbidden_public_claims"]:
        lines.append(f"- `{item['claim_id']}`: `{item['pattern']}` - {item['reason']}")

    lines.extend(
        [
            "",
            "## Gate Predicates",
            "",
        ]
    )
    for key, value in report["gate_predicates"].items():
        lines.append(f"- `{key}`: `{value}`")

    lines.extend(
        [
            "",
            "## Required Next Evidence",
            "",
        ]
    )
    for item in report["required_next_evidence"]:
        lines.append(f"- {item}")

    return "\n".join(lines).rstrip() + "\n"


def write_report(
    report: Mapping[str, Any],
    *,
    json_path: Path,
    markdown_path: Path,
    vault_markdown_path: Path | None = None,
) -> tuple[Path, Path, Path | None]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown = render_markdown(report)
    markdown_path.write_text(markdown, encoding="utf-8")
    if vault_markdown_path is not None:
        vault_markdown_path.parent.mkdir(parents=True, exist_ok=True)
        vault_markdown_path.write_text(markdown, encoding="utf-8")
    return json_path, markdown_path, vault_markdown_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--vault-markdown", type=Path, default=DEFAULT_VAULT_MARKDOWN)
    parser.add_argument("--no-vault-markdown", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_report()
    vault_markdown = None if args.no_vault_markdown else args.vault_markdown
    write_report(
        report,
        json_path=args.output,
        markdown_path=args.markdown,
        vault_markdown_path=vault_markdown,
    )
    if report["missing_evidence_artifacts"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
