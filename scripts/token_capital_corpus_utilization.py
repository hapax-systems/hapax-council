#!/usr/bin/env python3
"""Define and measure Token Capital corpus-utilization denominators."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import rag_documents_v2_shadow as rag_shadow

DEFAULT_COLLECTION = "documents_v2"
DEFAULT_OUTPUT_DIR = Path("reports/token-capital-utilization")
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_SOURCE_PROFILE = "audit-publication"
TEXT_DENOMINATOR_EXTENSIONS = {".html", ".md", ".py", ".txt"}
TOKEN_ESTIMATE_CHARS_PER_TOKEN = 4

ARTIFACT_CLASS_BY_CATEGORY = {
    "audit": "research_audit",
    "handoff": "research_coordination",
    "foundation": "research_basis",
    "lab_journal": "research_basis",
    "ledger": "research_basis",
    "exposition": "research_publication_draft",
    "request": "work_state",
    "cc_task": "work_state",
    "repo_docs": "implementation_docs",
    "repo_scripts": "implementation_substrate",
    "repo_agents": "implementation_substrate",
    "repo_shared": "implementation_substrate",
    "agentgov": "implementation_substrate",
}

AUTHORITY_BY_ARTIFACT_CLASS = {
    "research_audit": "audit_evidence",
    "research_coordination": "handoff_context",
    "research_basis": "hypothesis_or_repair_basis",
    "research_publication_draft": "draft_non_authoritative",
    "work_state": "coordination_state",
    "implementation_docs": "implementation_context",
    "implementation_substrate": "implementation_trace",
}


@dataclass(frozen=True)
class CorpusRecord:
    path: Path
    display_path: str
    source_category: str
    artifact_class: str
    claim_authority: str
    extension: str
    included: bool
    exclusion_reasons: tuple[str, ...]
    char_count: int
    word_count: int
    estimated_tokens: int
    sha256: str | None


def display_path(path: Path) -> str:
    text = str(path)
    home = str(Path.home())
    if text.startswith(home):
        return "$HOME" + text[len(home) :]
    return text


def _frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        return {}
    try:
        _, raw, _body = text.split("---", 2)
    except ValueError:
        return {}
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def read_text(path: Path, *, max_bytes: int = 10_000_000) -> str:
    try:
        with path.open("rb") as file:
            data = file.read(max_bytes)
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return math.ceil(len(text) / TOKEN_ESTIMATE_CHARS_PER_TOKEN)


def artifact_class_for_path(path: Path) -> tuple[str, str, str]:
    category = rag_shadow.classify_source_path(path)
    artifact_class = ARTIFACT_CLASS_BY_CATEGORY.get(category, "other")
    authority = AUTHORITY_BY_ARTIFACT_CLASS.get(artifact_class, "non_authoritative")
    return category, artifact_class, authority


def exclusion_reasons(path: Path, text: str, frontmatter: Mapping[str, Any]) -> tuple[str, ...]:
    reasons: list[str] = []
    ext = path.suffix.lower()
    if ext not in TEXT_DENOMINATOR_EXTENSIONS:
        reasons.append("binary_or_unsupported_text_extraction")
    elif not text.strip():
        reasons.append("empty_or_unreadable")
    content_tier = str(frontmatter.get("content_tier", "")).lower()
    if frontmatter.get("is_metadata_only") is True or content_tier in {
        "metadata_only",
        "metadata-only",
        "stub",
        "inventory",
    }:
        reasons.append("metadata_only_inventory")
    if frontmatter.get("retrieval_eligible") is False:
        reasons.append("retrieval_ineligible")
    if "/.meta/" in str(path):
        reasons.append("metadata_sidecar")
    return tuple(dict.fromkeys(reasons))


def build_record(path: Path) -> CorpusRecord:
    ext = path.suffix.lower() or "<none>"
    text = read_text(path) if ext in TEXT_DENOMINATOR_EXTENSIONS else ""
    frontmatter = _frontmatter(text)
    reasons = exclusion_reasons(path, text, frontmatter)
    category, artifact_class, authority = artifact_class_for_path(path)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None
    return CorpusRecord(
        path=path,
        display_path=display_path(path),
        source_category=category,
        artifact_class=artifact_class,
        claim_authority=authority,
        extension=ext,
        included=not reasons,
        exclusion_reasons=reasons,
        char_count=len(text),
        word_count=len(text.split()) if text else 0,
        estimated_tokens=estimate_tokens(text),
        sha256=digest,
    )


def discover_records(source_profile: str) -> list[CorpusRecord]:
    source_dirs = rag_shadow.default_source_dirs(source_profile)
    files = rag_shadow.discover_source_files(source_dirs)
    return [build_record(path) for path in files]


def _sum(records: Sequence[CorpusRecord], attr: str) -> int:
    return sum(int(getattr(record, attr)) for record in records)


def _count_by(records: Sequence[CorpusRecord], attr: str) -> dict[str, int]:
    return dict(sorted(Counter(str(getattr(record, attr)) for record in records).items()))


def _token_sum_by(records: Sequence[CorpusRecord], attr: str) -> dict[str, int]:
    totals: dict[str, int] = {}
    for record in records:
        key = str(getattr(record, attr))
        totals[key] = totals.get(key, 0) + record.estimated_tokens
    return dict(sorted(totals.items()))


def denominator_summary(records: Sequence[CorpusRecord]) -> dict[str, Any]:
    included = [record for record in records if record.included]
    excluded = [record for record in records if not record.included]
    exclusion_counts: Counter[str] = Counter()
    for record in excluded:
        exclusion_counts.update(record.exclusion_reasons)
    return {
        "definition": {
            "included_extensions": sorted(TEXT_DENOMINATOR_EXTENSIONS),
            "token_estimate": f"ceil(characters/{TOKEN_ESTIMATE_CHARS_PER_TOKEN})",
            "scope": (
                "Generated or operator-authored persisted text in the approved "
                "audit-publication evidence profile; binary/parser-dependent "
                "files are counted as exclusions until their extracted text is "
                "available to this denominator tool."
            ),
        },
        "files_discovered": len(records),
        "files_in_denominator": len(included),
        "files_excluded": len(excluded),
        "estimated_tokens_in_denominator": _sum(included, "estimated_tokens"),
        "chars_in_denominator": _sum(included, "char_count"),
        "words_in_denominator": _sum(included, "word_count"),
        "included_by_artifact_class": _count_by(included, "artifact_class"),
        "included_tokens_by_artifact_class": _token_sum_by(included, "artifact_class"),
        "included_by_source_category": _count_by(included, "source_category"),
        "included_tokens_by_source_category": _token_sum_by(included, "source_category"),
        "included_by_claim_authority": _count_by(included, "claim_authority"),
        "excluded_by_reason": dict(sorted(exclusion_counts.items())),
        "excluded_by_extension": _count_by(excluded, "extension"),
    }


def record_to_json(record: CorpusRecord) -> dict[str, Any]:
    return {
        "path": record.display_path,
        "source_category": record.source_category,
        "artifact_class": record.artifact_class,
        "claim_authority": record.claim_authority,
        "extension": record.extension,
        "included": record.included,
        "exclusion_reasons": list(record.exclusion_reasons),
        "char_count": record.char_count,
        "word_count": record.word_count,
        "estimated_tokens": record.estimated_tokens,
        "sha256": record.sha256,
    }


def qdrant_source_index(
    *,
    collection: str,
    qdrant_url: str,
    client: Any | None = None,
    scroll_limit: int = 512,
) -> dict[str, Any]:
    if client is None:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=qdrant_url)
    offset = None
    chunk_count_by_source: Counter[str] = Counter()
    point_count = 0
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            limit=scroll_limit,
            offset=offset,
            with_payload=["source"],
            with_vectors=False,
        )
        point_count += len(points)
        for point in points:
            payload = getattr(point, "payload", None) or {}
            if isinstance(payload, Mapping) and payload.get("source"):
                chunk_count_by_source[str(payload["source"])] += 1
        if offset is None:
            break
    return {
        "collection": collection,
        "point_count_scrolled": point_count,
        "distinct_source_count": len(chunk_count_by_source),
        "chunk_count_by_source": dict(chunk_count_by_source),
    }


def _source_strings_from_query_report(query: Mapping[str, Any]) -> list[str]:
    sources: list[str] = []
    for hit in query.get("hits", []) or []:
        if isinstance(hit, Mapping) and hit.get("source"):
            sources.append(str(hit["source"]))
    for context in query.get("contexts", []) or []:
        if isinstance(context, Mapping) and context.get("source"):
            sources.append(str(context["source"]))
    return sources


def sources_from_eval_report(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    retrieved_sources: set[str] = set()
    answer_context_sources: set[str] = set()
    if isinstance(data.get("queries"), list):
        for query in data["queries"]:
            if isinstance(query, Mapping):
                retrieved_sources.update(_source_strings_from_query_report(query))
    if isinstance(data.get("variants"), list):
        for variant in data["variants"]:
            if not isinstance(variant, Mapping):
                continue
            for query in variant.get("queries", []) or []:
                if isinstance(query, Mapping):
                    context_sources = _source_strings_from_query_report(query)
                    retrieved_sources.update(context_sources)
                    answer_context_sources.update(context_sources)
    summary = data.get("retrieval_summary", {})
    if not isinstance(summary, Mapping):
        summary = {}
    return {
        "path": display_path(path),
        "suite_id": data.get("suite_id"),
        "answer_mode": data.get("answer_mode"),
        "retrieved_sources": sorted(retrieved_sources),
        "answer_context_sources": sorted(answer_context_sources),
        "golden_label_utilization_rate": summary.get("golden_label_utilization_rate"),
        "golden_label_utilization_numerator": summary.get("golden_label_utilization_numerator"),
        "golden_label_utilization_denominator": summary.get("golden_label_utilization_denominator"),
    }


def utilization_summary(
    records: Sequence[CorpusRecord],
    *,
    qdrant_index: Mapping[str, Any] | None,
    eval_reports: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    included = [record for record in records if record.included]
    denominator_paths = {str(record.path): record for record in included}
    denominator_count = len(denominator_paths)
    indexed_sources = set()
    if qdrant_index:
        indexed_sources = set(qdrant_index.get("chunk_count_by_source", {}))
    retrieved_sources = {
        source for report in eval_reports for source in report.get("retrieved_sources", [])
    }
    answer_context_sources = {
        source for report in eval_reports for source in report.get("answer_context_sources", [])
    }

    def rate(sources: set[str]) -> dict[str, Any]:
        matched = sorted(source for source in sources if source in denominator_paths)
        return {
            "matched_file_count": len(matched),
            "denominator_file_count": denominator_count,
            "file_rate": round(len(matched) / denominator_count, 4) if denominator_count else None,
            "matched_token_estimate": sum(
                denominator_paths[source].estimated_tokens for source in matched
            ),
            "matched_files_sample": [display_path(Path(source)) for source in matched[:25]],
        }

    return {
        "indexed_in_qdrant": rate(indexed_sources),
        "retrieved_in_eval_reports": rate(retrieved_sources),
        "used_as_answer_context": rate(answer_context_sources),
        "downstream_contribution": {
            "status": "not_measured",
            "reason": (
                "No durable action/artifact influence ledger is consumed by this "
                "denominator report. Retrieval and answer-context use are not "
                "treated as economic value or appreciation."
            ),
        },
    }


def build_report(
    *,
    source_profile: str,
    collection: str,
    qdrant_url: str,
    records: Sequence[CorpusRecord],
    qdrant_index: Mapping[str, Any] | None,
    eval_reports: Sequence[Mapping[str, Any]],
    include_file_records: bool = False,
) -> dict[str, Any]:
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_profile": source_profile,
        "collection": collection,
        "qdrant_url": qdrant_url,
        "denominator": denominator_summary(records),
        "qdrant_index": {
            key: value
            for key, value in (qdrant_index or {}).items()
            if key != "chunk_count_by_source"
        }
        if qdrant_index
        else None,
        "eval_reports": [
            {key: value for key, value in report.items() if not key.endswith("_sources")}
            for report in eval_reports
        ],
        "utilization": utilization_summary(
            records,
            qdrant_index=qdrant_index,
            eval_reports=eval_reports,
        ),
        "claim_ceiling": {
            "status": "measurement_infrastructure_only",
            "reason": (
                "This report defines denominator and numerator semantics. It "
                "does not prove token appreciation, compounding value, or "
                "publication-grade Token Capital claims."
            ),
        },
    }
    if include_file_records:
        report["file_records"] = [record_to_json(record) for record in records]
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    denominator = report["denominator"]
    utilization = report["utilization"]
    lines = [
        "# Token Capital Corpus Utilization Denominator",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Source profile: `{report['source_profile']}`",
        f"- Collection: `{report['collection']}`",
        "",
        "## Denominator",
        "",
        f"- Files discovered: `{denominator['files_discovered']}`",
        f"- Files in denominator: `{denominator['files_in_denominator']}`",
        f"- Files excluded: `{denominator['files_excluded']}`",
        f"- Estimated denominator tokens: `{denominator['estimated_tokens_in_denominator']}`",
        f"- Token estimate method: `{denominator['definition']['token_estimate']}`",
        "",
        "## Included Artifact Classes",
        "",
    ]
    for key, count in denominator["included_by_artifact_class"].items():
        tokens = denominator["included_tokens_by_artifact_class"].get(key, 0)
        lines.append(f"- `{key}`: {count} files, {tokens} estimated tokens")
    lines.extend(["", "## Exclusions", ""])
    for key, count in denominator["excluded_by_reason"].items():
        lines.append(f"- `{key}`: {count}")
    if not denominator["excluded_by_reason"]:
        lines.append("- none")
    lines.extend(["", "## Utilization Semantics", ""])
    for key in ("indexed_in_qdrant", "retrieved_in_eval_reports", "used_as_answer_context"):
        item = utilization[key]
        lines.append(
            "- `{key}`: {num}/{den} files (`{rate}`), {tokens} estimated tokens".format(
                key=key,
                num=item["matched_file_count"],
                den=item["denominator_file_count"],
                rate=item["file_rate"],
                tokens=item["matched_token_estimate"],
            )
        )
    downstream = utilization["downstream_contribution"]
    lines.extend(
        [
            f"- `downstream_contribution`: `{downstream['status']}`",
            f"- Downstream reason: {downstream['reason']}",
            "",
            "## Audit-Golden Comparison Inputs",
            "",
        ]
    )
    for eval_report in report.get("eval_reports", []):
        lines.append(
            "- `{path}` suite=`{suite}` answer_mode=`{mode}` golden_label_utilization=`{num}/{den}` (`{rate}`)".format(
                path=eval_report.get("path"),
                suite=eval_report.get("suite_id"),
                mode=eval_report.get("answer_mode"),
                num=eval_report.get("golden_label_utilization_numerator"),
                den=eval_report.get("golden_label_utilization_denominator"),
                rate=eval_report.get("golden_label_utilization_rate"),
            )
        )
    lines.extend(
        [
            "",
            "## Claim Ceiling",
            "",
            f"- Status: `{report['claim_ceiling']['status']}`",
            f"- Reason: {report['claim_ceiling']['reason']}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _resolve_outputs(output: Path | None) -> tuple[Path, Path]:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if output is None:
        output = DEFAULT_OUTPUT_DIR / f"token-capital-utilization-{timestamp}.json"
    if output.suffix.lower() == ".md":
        return output.with_suffix(".json"), output
    if output.suffix.lower() == ".json":
        return output, output.with_suffix(".md")
    return (
        output / f"token-capital-utilization-{timestamp}.json",
        output / f"token-capital-utilization-{timestamp}.md",
    )


def write_report(report: Mapping[str, Any], output: Path | None) -> tuple[Path, Path]:
    json_path, markdown_path = _resolve_outputs(output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-profile", default=DEFAULT_SOURCE_PROFILE)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--qdrant-url", default=os.environ.get("QDRANT_URL", DEFAULT_QDRANT_URL))
    parser.add_argument("--skip-qdrant", action="store_true")
    parser.add_argument("--eval-report", action="append", type=Path, default=[])
    parser.add_argument("--include-file-records", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    records = discover_records(args.source_profile)
    qdrant_index = None
    if not args.skip_qdrant:
        qdrant_index = qdrant_source_index(
            collection=args.collection,
            qdrant_url=args.qdrant_url,
        )
    eval_reports = [sources_from_eval_report(path) for path in args.eval_report]
    report = build_report(
        source_profile=args.source_profile,
        collection=args.collection,
        qdrant_url=args.qdrant_url,
        records=records,
        qdrant_index=qdrant_index,
        eval_reports=eval_reports,
        include_file_records=args.include_file_records,
    )
    json_path, markdown_path = write_report(report, args.output)
    print(f"wrote JSON: {json_path}")
    print(f"wrote Markdown: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
