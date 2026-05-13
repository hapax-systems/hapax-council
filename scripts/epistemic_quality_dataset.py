#!/usr/bin/env python3
"""Build and validate the EQI Phase 0 calibration dataset ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESEARCH_ROOT = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-research"
DEFAULT_CC_TASK_ROOT = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
SCHEMA_PATH = REPO_ROOT / "schemas" / "epistemic-quality-golden-dataset.schema.json"

TIER_COUNTS = {"A": 50, "B": 30, "C": 70, "D": 50}
TIER_DESCRIPTIONS = {
    "A": "operator_written_analysis",
    "B": "published_or_peer_reviewed_reference",
    "C": "agent_output_or_system_claim",
    "D": "known_bad_or_adversarial",
}
VALID_PRIVACY = {"public", "internal", "public_synthetic"}
VALID_TEXT_STATUS = {
    "ready",
    "operator_source_required",
    "external_source_required",
    "agent_source_review_required",
}
VALID_LABEL_STATUS = {"unlabeled", "blocked_source_required", "complete"}
AXES = (
    "claim_evidence_alignment",
    "hedge_calibration",
    "quantifier_precision",
    "source_grounding",
)

_SECRET_PATTERNS = (
    re.compile(r"\b(api[_-]?key|token|password|secret|pass show)\b", re.I),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
    re.compile(r"\b[A-Za-z0-9_=-]{32,}\b"),
)


@dataclass(frozen=True)
class SourceGroup:
    tier: str
    source_kind: str
    root: Path
    patterns: tuple[str, ...]
    privacy_class: str = "internal"


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def excerpt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_safe_excerpt(text: str) -> bool:
    if len(text) < 120 or len(text) > 1600:
        return False
    return not any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def iter_markdown_blocks(path: Path) -> list[tuple[int, str]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    blocks: list[tuple[int, str]] = []
    line = 1
    current: list[str] = []
    start_line = 1
    in_frontmatter = False
    for lineno, raw_line in enumerate(raw.splitlines(), start=1):
        stripped = raw_line.strip()
        if lineno == 1 and stripped == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            continue
        if not stripped:
            if current:
                text = normalize_text("\n".join(current))
                if is_safe_excerpt(text):
                    blocks.append((start_line, text))
                current = []
            line = lineno + 1
            start_line = line
            continue
        if stripped.startswith("```"):
            if current:
                text = normalize_text("\n".join(current))
                if is_safe_excerpt(text):
                    blocks.append((start_line, text))
                current = []
            start_line = lineno + 1
            continue
        if not current:
            start_line = lineno
        current.append(stripped)
    if current:
        text = normalize_text("\n".join(current))
        if is_safe_excerpt(text):
            blocks.append((start_line, text))
    return blocks


def source_ref(root: Path, path: Path, line: int, source_kind: str) -> str:
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    return f"{source_kind}:{rel.as_posix()}:{line}"


def collect_ready_records(
    *,
    group: SourceGroup,
    count: int,
    start_index: int,
) -> list[dict[str, Any]]:
    files: list[Path] = []
    for pattern in group.patterns:
        files.extend(sorted(group.root.glob(pattern)))
    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for path in sorted(set(files)):
        if not path.is_file():
            continue
        for line, text in iter_markdown_blocks(path):
            digest = excerpt_hash(text)
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            record_id = f"eqi-v0-{group.tier}-{start_index + len(records):03d}"
            records.append(
                {
                    "id": record_id,
                    "tier": group.tier,
                    "tier_description": TIER_DESCRIPTIONS[group.tier],
                    "source_kind": group.source_kind,
                    "source_ref": source_ref(group.root, path, line, group.source_kind),
                    "privacy_class": group.privacy_class,
                    "authority_ceiling": "candidate_unlabeled",
                    "domain_partition": infer_domain(text),
                    "text_status": "ready",
                    "excerpt": text,
                    "excerpt_hash": digest,
                    "label_status": "unlabeled",
                    "labels": {},
                    "relabel_required": False,
                }
            )
            if len(records) >= count:
                return records
    return records


def infer_domain(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("test", "runtime", "service", "metric", "qdrant")):
        return "technical"
    if any(term in lowered for term in ("paper", "citation", "theory", "hypothesis")):
        return "scientific"
    if any(term in lowered for term in ("operator", "journal", "weblog", "launch")):
        return "narrative"
    return "mixed"


def source_slot_records(
    *,
    tier: str,
    count: int,
    source_kind: str,
    source_ref_prefix: str,
    text_status: str,
    slot_label: str,
    blocker_reason: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index in range(count):
        record_id = f"eqi-v0-{tier}-{index + 1:03d}"
        text = (
            f"{slot_label} {index + 1:03d}: {blocker_reason}. Direct text is intentionally not bundled "
            "until a reviewer attaches a source-appropriate excerpt or local citation note."
        )
        records.append(
            {
                "id": record_id,
                "tier": tier,
                "tier_description": TIER_DESCRIPTIONS[tier],
                "source_kind": source_kind,
                "source_ref": f"{source_ref_prefix}:{index + 1:03d}",
                "privacy_class": "internal",
                "authority_ceiling": "candidate_unlabeled_source_required",
                "domain_partition": "scientific" if tier == "B" else "mixed",
                "text_status": text_status,
                "excerpt": text,
                "excerpt_hash": excerpt_hash(text),
                "label_status": "blocked_source_required",
                "labels": {},
                "relabel_required": False,
            }
        )
    return records


def external_reference_records(count: int) -> list[dict[str, Any]]:
    references = [
        "Burns et al. ICLR 2023 truth directions in language-model hidden states",
        "Marks and Tegmark COLM 2024 geometry of truth in language models",
        "Li et al. NeurIPS 2023 inference-time intervention and truthful direction work",
        "Ben-David and Lu 2010 impossibility results for cross-domain transfer",
        "MultiFC 2019 multi-domain fact-checking dataset and cross-domain failure modes",
        "MERMAID 2025 mixture-of-experts requirement for cross-domain factuality",
        "Shumailov et al. Nature 2024 model-collapse and synthetic contamination",
        "RAGAS retrieval-augmented generation evaluation framework",
        "ARES automated RAG evaluation framework",
        "TRAIL agent-trace information-flow analysis",
        "COMPASS multi-agent provenance and process-mining analysis",
        "Tajik et al. information-flow analysis across agent/tool traces",
        "Data Shapley data valuation literature",
        "ClaimBuster automated factual-claim detection",
        "Factiverse source-grounded fact checking",
    ]
    records: list[dict[str, Any]] = []
    for index in range(count):
        record_id = f"eqi-v0-B-{index + 1:03d}"
        ref = references[index % len(references)]
        text = (
            f"Reference slot {index + 1:03d}: {ref}. Direct source text is intentionally not bundled in this "
            "candidate ledger until a lawful excerpt or locally stored citation note is attached."
        )
        records.append(
            {
                "id": record_id,
                "tier": "B",
                "tier_description": TIER_DESCRIPTIONS["B"],
                "source_kind": "external_reference_slot",
                "source_ref": f"reference-slot:{index + 1:03d}",
                "privacy_class": "internal",
                "authority_ceiling": "candidate_unlabeled_external_source_required",
                "domain_partition": "scientific",
                "text_status": "external_source_required",
                "excerpt": text,
                "excerpt_hash": excerpt_hash(text),
                "label_status": "blocked_source_required",
                "labels": {},
                "relabel_required": False,
            }
        )
    return records


def synthetic_bad_records(count: int) -> list[dict[str, Any]]:
    metadata_stub = (
        "Drive item metadata only: title={n}, mimeType=application/pdf, webViewLink present, "
        "content unavailable, author unknown, modifiedTime stale. This is inventory, not evidence."
    )
    auto_generated = (
        "The system definitively proves {n} production-grade governance outcomes across all "
        "surfaces with zero failures and complete safety, without needing further receipts."
    )
    hedged_false = (
        "It may be somewhat reasonable to say that {n} citations prove the benchmark is fully "
        "replicated, although no replication run, source corpus, or evaluation denominator is attached."
    )
    confident_wrong = (
        "Codex is an Anthropic product and therefore the Claude route is always the correct "
        "implementation path for OpenAI API work item {n}."
    )
    templates = (
        [metadata_stub] * 20 + [auto_generated] * 15 + [hedged_false] * 10 + [confident_wrong] * 5
    )
    records: list[dict[str, Any]] = []
    for index, template in enumerate(templates[:count], start=1):
        record_id = f"eqi-v0-D-{index:03d}"
        text = template.format(n=index)
        records.append(
            {
                "id": record_id,
                "tier": "D",
                "tier_description": TIER_DESCRIPTIONS["D"],
                "source_kind": "synthetic_known_bad_fixture",
                "source_ref": f"synthetic:eqi-known-bad:{index:03d}",
                "privacy_class": "public_synthetic",
                "authority_ceiling": "candidate_unlabeled",
                "domain_partition": "mixed",
                "text_status": "ready",
                "excerpt": text,
                "excerpt_hash": excerpt_hash(text),
                "label_status": "unlabeled",
                "labels": {},
                "relabel_required": False,
            }
        )
    return records


def spaced_selection(records: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count <= 0 or not records:
        return []
    if len(records) <= count:
        return records[:]
    step = len(records) / count
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index in range(count):
        record = records[min(int(index * step), len(records) - 1)]
        rid = str(record["id"])
        if rid in seen:
            continue
        selected.append(record)
        seen.add(rid)
    for record in records:
        if len(selected) >= count:
            break
        rid = str(record["id"])
        if rid not in seen:
            selected.append(record)
            seen.add(rid)
    return selected


def assign_relabel_subset(records: list[dict[str, Any]], target: int = 40) -> None:
    for record in records:
        record["relabel_required"] = False
    ready_by_tier = {
        tier: [
            record
            for record in records
            if record["tier"] == tier and record["text_status"] == "ready"
        ]
        for tier in TIER_COUNTS
    }
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    tier_quota = max(1, target // len(TIER_COUNTS))
    for tier in TIER_COUNTS:
        for record in spaced_selection(
            ready_by_tier[tier], min(tier_quota, len(ready_by_tier[tier]))
        ):
            rid = str(record["id"])
            if rid not in seen:
                selected.append(record)
                seen.add(rid)
    ready_remaining = [
        record
        for record in records
        if record["text_status"] == "ready" and str(record["id"]) not in seen
    ]
    for record in spaced_selection(ready_remaining, target - len(selected)):
        rid = str(record["id"])
        if rid not in seen:
            selected.append(record)
            seen.add(rid)
    for record in selected[:target]:
        record["relabel_required"] = True


def default_source_groups(
    research_root: Path, cc_task_root: Path
) -> tuple[SourceGroup, SourceGroup]:
    tier_a = SourceGroup(
        tier="A",
        source_kind="hapax_research",
        root=research_root,
        patterns=(
            "weblog/*.md",
            "foundations/*.md",
            "ledgers/*.md",
            "speculative/*.md",
        ),
    )
    tier_c = SourceGroup(
        tier="C",
        source_kind="cc_task",
        root=cc_task_root,
        patterns=("active/*.md", "closed/*.md"),
    )
    return tier_a, tier_c


def build_records(
    research_root: Path,
    cc_task_root: Path,
    *,
    allow_internal_autoselect: bool = False,
) -> list[dict[str, Any]]:
    tier_a, tier_c = default_source_groups(research_root, cc_task_root)
    records: list[dict[str, Any]] = []
    if allow_internal_autoselect:
        records.extend(
            collect_ready_records(
                group=tier_a,
                count=TIER_COUNTS["A"],
                start_index=1,
            )
        )
    else:
        records.extend(
            source_slot_records(
                tier="A",
                count=TIER_COUNTS["A"],
                source_kind="operator_analysis_source_slot",
                source_ref_prefix="operator-analysis-source-slot",
                text_status="operator_source_required",
                slot_label="Tier A operator analysis source slot",
                blocker_reason="operator-authored analysis must be explicitly confirmed before Tier A can act as high-calibration substrate",
            )
        )
    records.extend(external_reference_records(TIER_COUNTS["B"]))
    if allow_internal_autoselect:
        records.extend(
            collect_ready_records(
                group=tier_c,
                count=TIER_COUNTS["C"],
                start_index=1,
            )
        )
    else:
        records.extend(
            source_slot_records(
                tier="C",
                count=TIER_COUNTS["C"],
                source_kind="agent_output_review_slot",
                source_ref_prefix="agent-output-review-slot",
                text_status="agent_source_review_required",
                slot_label="Tier C agent output source slot",
                blocker_reason="agent output must pass privacy and source review before inclusion",
            )
        )
    records.extend(synthetic_bad_records(TIER_COUNTS["D"]))
    assign_relabel_subset(records)
    return records


def validate_records(records: list[dict[str, Any]], expected_counts: dict[str, int]) -> list[str]:
    errors: list[str] = []
    ids: set[str] = set()
    hashes: set[str] = set()
    counts = {tier: 0 for tier in expected_counts}
    relabel_count = 0
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    schema_validator = jsonschema.Draft202012Validator(schema)
    for idx, record in enumerate(records, start=1):
        rid = str(record.get("id", ""))
        for schema_error in sorted(schema_validator.iter_errors(record), key=str):
            path = ".".join(str(part) for part in schema_error.path) or "<record>"
            errors.append(f"{rid or f'record {idx}'}: schema {path}: {schema_error.message}")
        if not rid:
            errors.append(f"record {idx}: missing id")
        elif rid in ids:
            errors.append(f"{rid}: duplicate id")
        ids.add(rid)
        tier = record.get("tier")
        if tier not in expected_counts:
            errors.append(f"{rid}: bad tier {tier!r}")
        else:
            counts[str(tier)] += 1
        if record.get("privacy_class") not in VALID_PRIVACY:
            errors.append(f"{rid}: bad or missing privacy_class")
        if record.get("text_status") not in VALID_TEXT_STATUS:
            errors.append(f"{rid}: bad or missing text_status")
        if not record.get("source_ref"):
            errors.append(f"{rid}: missing source_ref")
        if record.get("label_status") not in VALID_LABEL_STATUS:
            errors.append(f"{rid}: bad or missing label_status")
        digest = record.get("excerpt_hash")
        if not digest:
            errors.append(f"{rid}: missing excerpt_hash")
        elif digest in hashes:
            errors.append(f"{rid}: duplicate excerpt_hash")
        elif digest != excerpt_hash(str(record.get("excerpt", ""))):
            errors.append(f"{rid}: excerpt_hash does not match excerpt")
        hashes.add(str(digest))
        label_status = record.get("label_status")
        if label_status == "complete":
            labels = record.get("labels")
            if not isinstance(labels, dict) or set(labels) != set(AXES):
                errors.append(f"{rid}: label_status complete without all axes")
        if record.get("relabel_required") is True:
            if record.get("text_status") != "ready":
                errors.append(f"{rid}: relabel_required set on non-ready record")
            relabel_count += 1
    for tier, expected in expected_counts.items():
        if counts[tier] != expected:
            errors.append(f"tier {tier}: expected {expected}, got {counts[tier]}")
    if relabel_count != 40:
        errors.append(f"relabel subset: expected 40, got {relabel_count}")
    return errors


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def write_labeling_pack(path: Path, manifest_path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    counts = {tier: sum(1 for record in records if record["tier"] == tier) for tier in TIER_COUNTS}
    status_counts = {
        status: sum(1 for record in records if record["text_status"] == status)
        for status in sorted(VALID_TEXT_STATUS)
    }
    relabel = sum(1 for record in records if record["relabel_required"])
    path.write_text(
        "\n".join(
            [
                "---",
                'title: "Epistemic Quality Phase 0 Labeling Pack V0"',
                "date: 2026-05-13",
                "request: REQ-20260512-epistemic-quality-infrastructure",
                "cc_task: epistemic-quality-phase0-golden-dataset-ledger",
                "status: candidate_unlabeled",
                "---",
                "",
                "# Epistemic Quality Phase 0 Labeling Pack V0",
                "",
                f"Manifest: `{manifest_path}`",
                "",
                "## Counts",
                "",
                *(f"- Tier {tier}: {count}" for tier, count in counts.items()),
                f"- Relabel subset: {relabel}",
                *(f"- `{status}` records: {count}" for status, count in status_counts.items()),
                "",
                "## Label Axes",
                "",
                "- `claim_evidence_alignment`: 1 means the claim outruns evidence; 5 means the claim ceiling matches attached evidence.",
                "- `hedge_calibration`: 1 means hedging/certainty is badly mismatched; 5 means confidence language is well calibrated.",
                "- `quantifier_precision`: 1 means vague or fake precision; 5 means quantities are exact, scoped, or explicitly absent.",
                "- `source_grounding`: 1 means source-free or metadata-only; 5 means independently traceable source grounding.",
                "",
                "## Labeling Examples And Non-Examples",
                "",
                "- Strong `claim_evidence_alignment` example: a claim says a local test passed and cites the exact command, fixture, timestamp, and failure scope.",
                "- Weak `claim_evidence_alignment` non-example: a claim says a system is production-ready because related metadata or inventory rows exist.",
                "- Strong `hedge_calibration` example: a hypothesis is explicitly scoped as unvalidated when the evidence is only a plausible mechanism.",
                "- Weak `hedge_calibration` non-example: a false or source-free claim is padded with hedges and therefore appears cautious without becoming grounded.",
                "- Strong `quantifier_precision` example: a count includes denominator, freshness, data source, and uncertainty or explicitly says no count is available.",
                "- Weak `quantifier_precision` non-example: a phrase like many, most, or zero failures appears without a measurement source.",
                "- Strong `source_grounding` example: the excerpt cites primary or independently reachable source material, not only a filename or drive metadata.",
                "- Weak `source_grounding` non-example: title, mime type, modified time, or web link metadata is treated as evidence for document contents.",
                "",
                "## Authority Ceiling",
                "",
                "- `candidate_unlabeled`: source text exists but labels are not ground truth.",
                "- `candidate_unlabeled_source_required`: the row is a slot, not a labelable example.",
                "- Blocked slots must receive source-appropriate excerpts or local citation notes before labels can be entered.",
                "",
                "## Hard Methodology Notes",
                "",
                "- These records are candidates, not ground truth.",
                "- Model-generated labels are not acceptable ground-truth labels.",
                "- The safe default build emits Tier A, B, and C source slots; opt-in internal autoselection is for controlled fixture or review use only.",
                "- Phase 0 cannot pass until required labels exist and the delayed relabel reliability check is recorded.",
                "- Scores measure epistemic quality markers, not propositional truth.",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def parse_counts(raw: list[str]) -> dict[str, int]:
    counts = dict(TIER_COUNTS)
    for item in raw:
        tier, _, value = item.partition("=")
        if tier not in counts or not value.isdigit():
            raise ValueError(f"bad tier count override: {item}")
        counts[tier] = int(value)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build candidate JSONL manifest")
    build.add_argument("--research-root", type=Path, default=DEFAULT_RESEARCH_ROOT)
    build.add_argument("--cc-task-root", type=Path, default=DEFAULT_CC_TASK_ROOT)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--labeling-pack", type=Path)
    build.add_argument(
        "--allow-internal-autoselect",
        action="store_true",
        help="opt in to broad internal markdown sampling for fixture/testing use; safe default emits source-review slots",
    )

    validate = sub.add_parser("validate", help="validate candidate JSONL manifest")
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--tier-count", action="append", default=[])

    args = parser.parse_args(argv)

    if args.command == "build":
        records = build_records(
            args.research_root,
            args.cc_task_root,
            allow_internal_autoselect=args.allow_internal_autoselect,
        )
        errors = validate_records(records, TIER_COUNTS)
        if errors:
            for error in errors:
                print(error)
            return 1
        write_jsonl(args.output, records)
        if args.labeling_pack:
            write_labeling_pack(args.labeling_pack, args.output, records)
        print(f"wrote {len(records)} records to {args.output}")
        return 0

    if args.command == "validate":
        counts = parse_counts(args.tier_count)
        records = read_jsonl(args.manifest)
        errors = validate_records(records, counts)
        if errors:
            for error in errors:
                print(error)
            return 1
        print(f"validated {len(records)} records")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
