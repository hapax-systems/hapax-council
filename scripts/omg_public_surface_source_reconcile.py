#!/usr/bin/env python3
"""Reconcile live omg.lol public surfaces with local source-of-truth evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.publication_hardening.lint import OVERCLAIM_PATTERNS

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "docs"
    / "research"
    / "evidence"
    / "2026-05-13-public-surface-source-of-truth-reconciliation.json"
)
DEFAULT_MARKDOWN = DEFAULT_OUTPUT.with_suffix(".md")
DEFAULT_VAULT_MARKDOWN = (
    Path.home()
    / "Documents"
    / "Personal"
    / "20-projects"
    / "hapax-research"
    / "audit"
    / "2026-05-13-public-surface-source-of-truth-reconciliation.md"
)
DEFAULT_STATE_ROOT = Path.home() / "hapax-state" / "publish"
DEFAULT_PUBLICATION_LOG = Path.home() / "hapax-state" / "publication" / "publication-log.jsonl"
DEFAULT_RESEARCH_ROOTS = (
    Path.home() / "projects" / "hapax-research",
    Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-research",
)
SOURCE_SUBDIRS = (
    "weblog",
    "lab-journals",
    "foundations",
    "ledgers",
    "audit",
    "audits",
)
RECEIPT_REFS = (
    REPO_ROOT / "docs/research/evidence/2026-05-12-public-surface-claim-inventory.md",
    Path.home()
    / "Documents"
    / "Personal"
    / "20-projects"
    / "hapax-research"
    / "audit"
    / "2026-05-12-weblog-archive-public-claim-hardening-receipt.md",
)
TOKEN_CAPITAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("token capital", re.compile(r"\btoken\s+capital\b", re.I)),
    ("rag", re.compile(r"\bRAG\b")),
    ("documents_v2", re.compile(r"\bdocuments_v2\b", re.I)),
    ("nomic", re.compile(r"\bnomic\b", re.I)),
    ("shapley", re.compile(r"\bshapley\b", re.I)),
    ("existence proof", re.compile(r"\bexistence[-\s]+proof\b", re.I)),
    ("compounding", re.compile(r"\bcompounding\b", re.I)),
    ("appreciating asset", re.compile(r"\bappreciating\s+assets?\b", re.I)),
)

ENTRY_CEILING_OVERRIDES: dict[str, str] = {
    "entry-006-may-10-11": "withdrawn public archive notice until repaired source is republished",
    "gaps-in-token-economic-theory-toward-a-theory-of-token-capital": (
        "withdrawn; Token Capital remains below existence-proof, compounding, "
        "and Shapley-value language"
    ),
    "may-10-lab-journal-llc-grants-visibility": (
        "withdrawn pending public-safe legal, grant, payment-rail, tax, and privacy receipts"
    ),
    "support": "receive-only support framing; activity metrics only, no failure-free governance claim",
    "page_template": "publication-hygiene artifact only; not a public claim page",
}


@dataclass(frozen=True)
class LiveItem:
    surface: str
    item_id: str
    title: str
    kind: str
    location: str
    public_url: str
    source: str
    modified: str | None = None

    @property
    def source_sha256(self) -> str:
        return _sha256_text(self.source) if self.source else ""

    @property
    def source_len(self) -> int:
        return len(self.source)

    @property
    def keys(self) -> set[str]:
        return source_keys(self.item_id, self.title, self.location)


@dataclass(frozen=True)
class SourceCandidate:
    kind: str
    ref: str
    keys: frozenset[str]
    status: str | None = None
    text_sha256: str | None = None
    text_len: int | None = None

    def to_report(self, live_sha: str) -> dict[str, object]:
        return {
            "kind": self.kind,
            "ref": self.ref,
            "status": self.status,
            "text_sha256": self.text_sha256,
            "text_len": self.text_len,
            "exact_live_match": bool(self.text_sha256 and self.text_sha256 == live_sha),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--publication-log", type=Path, default=DEFAULT_PUBLICATION_LOG)
    parser.add_argument("--research-root", action="append", type=Path, dest="research_roots")
    parser.add_argument(
        "--live-json", type=Path, help="Fixture/live capture JSON; skips API calls."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--vault-markdown", type=Path, default=DEFAULT_VAULT_MARKDOWN)
    parser.add_argument("--no-vault-markdown", action="store_true")
    parser.add_argument("--generated-at", default=_now_iso())
    parser.add_argument(
        "--fail-on-unreconciled",
        action="store_true",
        help="Exit non-zero if any live item has no source candidate or receipt.",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    research_roots = tuple(args.research_roots or DEFAULT_RESEARCH_ROOTS)
    live_items = (
        live_items_from_json(args.live_json)
        if args.live_json
        else collect_live_items_from_omg_lol()
    )
    candidates = collect_source_candidates(
        repo_root=repo_root,
        state_root=args.state_root.expanduser(),
        publication_log=args.publication_log.expanduser(),
        research_roots=tuple(path.expanduser() for path in research_roots),
    )
    report = build_report(
        live_items,
        candidates,
        repo_root=repo_root,
        generated_at=args.generated_at,
    )
    write_json(args.output, report)
    markdown = report_to_markdown(report)
    write_text(args.markdown, markdown)
    if not args.no_vault_markdown and args.vault_markdown:
        write_text(args.vault_markdown, markdown)

    print(f"wrote {args.output}")
    print(f"wrote {args.markdown}")
    if not args.no_vault_markdown and args.vault_markdown:
        print(f"wrote {args.vault_markdown}")

    if args.fail_on_unreconciled and report["summary"]["unreconciled_items"]:
        return 2
    return 0


def collect_live_items_from_omg_lol() -> list[LiveItem]:
    from shared.omg_lol_client import OmgLolClient

    client = OmgLolClient()
    items: list[LiveItem] = []
    web_payload = client.get_web("hapax") or {}
    web_response = web_payload.get("response") if isinstance(web_payload, dict) else {}
    if isinstance(web_response, dict):
        content = _string_or_empty(web_response.get("content"))
        items.append(
            LiveItem(
                surface="hapax.omg.lol",
                item_id="landing-page",
                title="hapax.omg.lol landing page",
                kind="landing_page",
                location="/",
                public_url="https://hapax.omg.lol/",
                source=content,
                modified=_string_or_none(web_response.get("modified")),
            )
        )

    entries_payload = client.list_entries("hapax") or {}
    response = entries_payload.get("response") if isinstance(entries_payload, dict) else {}
    entries = response.get("entries") if isinstance(response, dict) else []
    if isinstance(entries, list):
        items.extend(_live_items_from_entries(entries))
    return items


def live_items_from_json(path: Path) -> list[LiveItem]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    items: list[LiveItem] = []
    landing = payload.get("landing_page") if isinstance(payload, dict) else None
    if isinstance(landing, dict):
        content = _string_or_empty(landing.get("content") or landing.get("source"))
        items.append(
            LiveItem(
                surface="hapax.omg.lol",
                item_id=_string_or_empty(landing.get("item_id")) or "landing-page",
                title=_string_or_empty(landing.get("title")) or "hapax.omg.lol landing page",
                kind=_string_or_empty(landing.get("kind")) or "landing_page",
                location=_string_or_empty(landing.get("location")) or "/",
                public_url=_string_or_empty(landing.get("public_url")) or "https://hapax.omg.lol/",
                source=content,
                modified=_string_or_none(landing.get("modified")),
            )
        )

    entries: object = []
    if isinstance(payload, dict):
        entries = payload.get("entries", [])
        if not entries and isinstance(payload.get("response"), dict):
            entries = payload["response"].get("entries", [])
    if isinstance(entries, list):
        items.extend(_live_items_from_entries(entries))
    return items


def _live_items_from_entries(entries: list[object]) -> list[LiveItem]:
    live: list[LiveItem] = []
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        entry_id = _string_or_empty(raw.get("entry") or raw.get("id"))
        location = _string_or_empty(raw.get("location"))
        if not entry_id and not location:
            continue
        public_url = _string_or_empty(raw.get("public_url"))
        if not public_url:
            public_url = "https://hapax.weblog.lol" + (location or f"/weblog/{entry_id}")
        live.append(
            LiveItem(
                surface="hapax.weblog.lol",
                item_id=entry_id or _last_path_segment(location),
                title=_string_or_empty(raw.get("title")),
                kind=_string_or_empty(raw.get("type")) or "weblog_entry",
                location=location,
                public_url=public_url,
                source=_string_or_empty(raw.get("source") or raw.get("content")),
                modified=_string_or_none(raw.get("date") or raw.get("modified")),
            )
        )
    return live


def collect_source_candidates(
    *,
    repo_root: Path,
    state_root: Path,
    publication_log: Path,
    research_roots: tuple[Path, ...],
) -> list[SourceCandidate]:
    candidates: list[SourceCandidate] = []
    candidates.extend(_repo_file_candidates(repo_root))
    candidates.extend(_research_file_candidates(research_roots))
    candidates.extend(_publish_state_candidates(state_root))
    candidates.extend(_publish_log_candidates(state_root / "log"))
    candidates.extend(_publication_log_candidates(publication_log))
    return _dedupe_candidates(candidates)


def _repo_file_candidates(repo_root: Path) -> list[SourceCandidate]:
    paths: list[Path] = []
    static_index = repo_root / "agents" / "omg_web_builder" / "static" / "index.html"
    paths.append(static_index)
    for rel in (
        "docs/publication-drafts",
        "docs/refusal-briefs",
        "docs/research/evidence",
        "docs/research",
    ):
        root = repo_root / rel
        if root.exists():
            paths.extend(sorted(p for p in root.rglob("*") if p.suffix in {".html", ".md"}))
    candidates = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        kind = "repo_landing_source" if path == static_index else "repo_file"
        candidates.append(
            SourceCandidate(
                kind=kind,
                ref=_display_path(path),
                keys=frozenset(_path_candidate_keys(path, text)),
                status="committed_source",
                text_sha256=_sha256_text(text),
                text_len=len(text),
            )
        )
    return candidates


def _research_file_candidates(research_roots: tuple[Path, ...]) -> list[SourceCandidate]:
    candidates: list[SourceCandidate] = []
    seen: set[Path] = set()
    for root in research_roots:
        if not root.exists():
            continue
        for subdir in SOURCE_SUBDIRS:
            source_dir = root / subdir
            if not source_dir.exists():
                continue
            for path in sorted(source_dir.rglob("*")):
                if path in seen or not path.is_file() or path.suffix not in {".md", ".jsonl"}:
                    continue
                seen.add(path)
                text = path.read_text(encoding="utf-8", errors="replace")
                candidates.append(
                    SourceCandidate(
                        kind="research_file",
                        ref=_display_path(path),
                        keys=frozenset(_path_candidate_keys(path, text)),
                        status="local_research_source",
                        text_sha256=_sha256_text(text),
                        text_len=len(text),
                    )
                )
    return candidates


def _publish_state_candidates(state_root: Path) -> list[SourceCandidate]:
    candidates: list[SourceCandidate] = []
    for state_name in ("published", "draft", "failed"):
        root = state_root / state_name
        if not root.exists():
            continue
        for path in sorted(root.glob("*.json")):
            payload = _read_json_object(path)
            if payload is None:
                continue
            slug = _string_or_empty(payload.get("slug")) or path.stem
            title = _string_or_empty(payload.get("title"))
            body = _string_or_empty(payload.get("body_md"))
            source_path = _string_or_empty(payload.get("source_path"))
            keys = source_keys(slug, title, source_path, path.stem)
            status = _string_or_none(payload.get("approval")) or state_name
            candidates.append(
                SourceCandidate(
                    kind=f"publish_state_{state_name}",
                    ref=_display_path(path),
                    keys=frozenset(keys),
                    status=status,
                    text_sha256=_sha256_text(body) if body else None,
                    text_len=len(body) if body else None,
                )
            )
    return candidates


def _publish_log_candidates(log_root: Path) -> list[SourceCandidate]:
    candidates: list[SourceCandidate] = []
    if not log_root.exists():
        return candidates
    for path in sorted(log_root.glob("*.json")):
        payload = _read_json_object(path)
        if payload is None:
            continue
        slug = _string_or_empty(payload.get("slug")) or _slug_from_log_filename(path.name)
        surface = _string_or_empty(payload.get("surface"))
        result = _string_or_none(payload.get("result"))
        candidates.append(
            SourceCandidate(
                kind="publish_log",
                ref=_display_path(path),
                keys=frozenset(source_keys(slug, surface, path.stem)),
                status=result,
            )
        )
    return candidates


def _publication_log_candidates(path: Path) -> list[SourceCandidate]:
    candidates: list[SourceCandidate] = []
    if not path.exists():
        return candidates
    for index, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        target = _string_or_empty(payload.get("target"))
        surface = _string_or_empty(payload.get("surface"))
        if not target:
            continue
        candidates.append(
            SourceCandidate(
                kind="publication_log",
                ref=f"{_display_path(path)}:{index + 1}",
                keys=frozenset(source_keys(target, surface)),
                status=_string_or_none(payload.get("result")),
            )
        )
    return candidates


def build_report(
    live_items: list[LiveItem],
    candidates: list[SourceCandidate],
    *,
    repo_root: Path,
    generated_at: str,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in sorted(
        live_items, key=lambda value: (value.surface, value.location, value.item_id)
    ):
        matches = match_candidates(item, candidates)
        receipt_matches = receipt_candidates_for_item(item, repo_root=repo_root)
        all_matches = (*matches, *receipt_matches)
        lint_findings = live_lint_findings(item.source)
        token_hits = token_capital_hits(item.source)
        disposition = classify_disposition(item, all_matches)
        claim_ceiling = claim_ceiling_for(item, lint_findings, token_hits)
        rows.append(
            {
                "surface": item.surface,
                "item_id": item.item_id,
                "title": item.title,
                "kind": item.kind,
                "location": item.location,
                "public_url": item.public_url,
                "modified": item.modified,
                "live_source_sha256": item.source_sha256,
                "live_source_len": item.source_len,
                "disposition": disposition,
                "claim_ceiling": claim_ceiling,
                "source_candidates": [
                    candidate.to_report(item.source_sha256) for candidate in all_matches[:12]
                ],
                "claim_gate_findings": lint_findings,
                "token_capital_rag_hits": token_hits,
            }
        )

    unreconciled = [
        row["item_id"] for row in rows if row["disposition"] == "unreconciled_no_source_or_receipt"
    ]
    exact_matches = sum(
        1
        for row in rows
        if any(candidate["exact_live_match"] for candidate in row["source_candidates"])
    )
    committed_candidates = sum(
        1
        for row in rows
        if any(str(candidate["kind"]).startswith("repo_") for candidate in row["source_candidates"])
    )
    receipted_live_only = sum(
        1
        for row in rows
        if row["disposition"] in {"api_only_with_committed_receipt", "superseded_with_receipt"}
    )
    findings_count = sum(len(row["claim_gate_findings"]) for row in rows)
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "generated_by": "scripts/omg_public_surface_source_reconcile.py",
        "authority_case": "REQ-20260512-public-weblog-and-omg-claim-hardening",
        "claim_ceiling": (
            "source-of-truth receipt only; no Token Capital claim upgrade, no RAG repair "
            "claim, no downstream value claim"
        ),
        "source_refs": [
            "shared.omg_lol_client.OmgLolClient.get_web('hapax')",
            "shared.omg_lol_client.OmgLolClient.list_entries('hapax')",
            "agents/omg_web_builder/static/index.html",
            "docs/publication-drafts/*.md",
            "docs/research/evidence/2026-05-12-public-surface-claim-inventory.md",
            _display_path(DEFAULT_STATE_ROOT),
            _display_path(DEFAULT_PUBLICATION_LOG),
        ],
        "summary": {
            "live_items": len(rows),
            "exact_source_matches": exact_matches,
            "committed_source_candidates": committed_candidates,
            "receipted_live_only_items": receipted_live_only,
            "claim_gate_findings": findings_count,
            "unreconciled_items": unreconciled,
        },
        "rows": rows,
    }


def match_candidates(item: LiveItem, candidates: list[SourceCandidate]) -> list[SourceCandidate]:
    matches = [candidate for candidate in candidates if item.keys & set(candidate.keys)]

    def sort_key(candidate: SourceCandidate) -> tuple[int, str, str]:
        exact_rank = 0 if candidate.text_sha256 == item.source_sha256 else 1
        kind_rank = {
            "repo_landing_source": 0,
            "repo_file": 1,
            "publish_state_published": 2,
            "publish_state_draft": 3,
            "publish_state_failed": 4,
            "research_file": 5,
            "publish_log": 6,
            "publication_log": 7,
        }.get(candidate.kind, 9)
        return exact_rank, f"{kind_rank:02d}", candidate.ref

    return sorted(matches, key=sort_key)


def receipt_candidates_for_item(item: LiveItem, *, repo_root: Path) -> tuple[SourceCandidate, ...]:
    candidates: list[SourceCandidate] = []
    keys = item.keys
    receipt_paths = (
        repo_root / "docs/research/evidence/2026-05-12-public-surface-claim-inventory.md",
        *RECEIPT_REFS,
    )
    seen_paths: set[Path] = set()
    for path in receipt_paths:
        resolved = path if path.is_absolute() else repo_root / path
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        if not resolved.exists():
            continue
        text = resolved.read_text(encoding="utf-8", errors="replace")
        receipt_keys = source_keys(*keys)
        if any(key and key in _slugify(text) for key in receipt_keys):
            candidates.append(
                SourceCandidate(
                    kind="committed_receipt",
                    ref=_display_path(resolved),
                    keys=frozenset(keys),
                    status="source_of_truth_disposition_receipt",
                    text_sha256=_sha256_text(text),
                    text_len=len(text),
                )
            )
    return tuple(candidates)


def classify_disposition(item: LiveItem, candidates: tuple[SourceCandidate, ...]) -> str:
    if item.item_id in {
        "entry-006-may-10-11",
        "gaps-in-token-economic-theory-toward-a-theory-of-token-capital",
        "may-10-lab-journal-llc-grants-visibility",
    }:
        return "superseded_with_receipt"
    if item.item_id == "page_template":
        return "publication_hygiene_cleanup"
    if any(candidate.text_sha256 == item.source_sha256 for candidate in candidates):
        return "committed_or_local_source_exact_match"
    if any(candidate.kind == "repo_landing_source" for candidate in candidates):
        return "committed_source_exists_live_drift"
    if any(candidate.kind.startswith("repo_") for candidate in candidates):
        return "committed_source_candidate_live_may_drift"
    if any(candidate.kind.startswith("publish_state_") for candidate in candidates):
        return "publish_state_source_candidate_live_may_drift"
    if any(candidate.kind == "research_file" for candidate in candidates):
        return "research_source_candidate_live_may_drift"
    if any(candidate.kind == "committed_receipt" for candidate in candidates):
        return "api_only_with_committed_receipt"
    return "unreconciled_no_source_or_receipt"


def claim_ceiling_for(
    item: LiveItem,
    lint_findings: list[dict[str, object]],
    token_hits: list[str],
) -> str:
    if item.item_id in ENTRY_CEILING_OVERRIDES:
        return ENTRY_CEILING_OVERRIDES[item.item_id]
    if token_hits:
        return (
            "Token Capital/RAG language must remain audit-ceiling or hypothesis only; "
            "no existence-proof, compounding, answer-faithfulness, or downstream-value claim"
        )
    if lint_findings:
        return "claim text requires public-surface hardening before stronger reuse"
    return "dated public archive/source witness only; no stronger current-state claim"


def live_lint_findings(text: str) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for pattern, level, message in OVERCLAIM_PATTERNS:
            if pattern.search(line):
                findings.append(
                    {
                        "line": line_no,
                        "level": level,
                        "rule": "Hapax.PublicClaimOverreach",
                        "message": message,
                        "text": line.strip()[:180],
                    }
                )
    return findings


def token_capital_hits(text: str) -> list[str]:
    return sorted({label for label, pattern in TOKEN_CAPITAL_PATTERNS if pattern.search(text)})


def report_to_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "---",
        'title: "Public Surface Source-Of-Truth Reconciliation"',
        f"date: {report['generated_at'][:10]}",
        f"authority_case: {report['authority_case']}",
        "status: receipt",
        "mutation_surface: source_docs",
        "---",
        "",
        "# Public Surface Source-Of-Truth Reconciliation",
        "",
        "This receipt reconciles live `hapax.omg.lol` and `hapax.weblog.lol`",
        "surface state with committed drafts, local publish state, publication logs,",
        "research sources, and prior hardening receipts. It is read-only and does not",
        "upgrade any public claim.",
        "",
        "## Summary",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Live items: `{summary['live_items']}`",
        f"- Exact source matches: `{summary['exact_source_matches']}`",
        f"- Items with committed source candidates: `{summary['committed_source_candidates']}`",
        f"- Receipted live-only/API-patch items: `{summary['receipted_live_only_items']}`",
        f"- Claim-gate findings: `{summary['claim_gate_findings']}`",
        f"- Unreconciled items: `{len(summary['unreconciled_items'])}`",
        "",
        "Claim ceiling: source-of-truth receipt only. The Token Capital/RAG ceiling",
        "remains below existence-proof, full repair, answer-faithfulness, compounding,",
        "or downstream-value language.",
        "",
        "## Disposition Rows",
        "",
        "| Surface | Item | Disposition | Source evidence | Claim ceiling |",
        "|---|---|---|---|---|",
    ]
    for row in report["rows"]:
        evidence = _markdown_evidence(row["source_candidates"])
        lines.append(
            "| "
            + " | ".join(
                _md_cell(value)
                for value in (
                    row["surface"],
                    f"[{row['item_id']}]({row['public_url']})",
                    row["disposition"],
                    evidence,
                    row["claim_ceiling"],
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Repeatable Command",
            "",
            "```bash",
            "uv run python scripts/omg_public_surface_source_reconcile.py",
            "uv run python scripts/check-public-surface-claims.py --warnings-fail",
            "```",
            "",
            "Use the JSON companion for machine checks; use this Markdown receipt for",
            "operator review and request/cc-task closure.",
            "",
        ]
    )
    return "\n".join(lines)


def _markdown_evidence(candidates: list[dict[str, object]]) -> str:
    if not candidates:
        return "none"
    parts: list[str] = []
    for candidate in candidates[:4]:
        exact = " exact" if candidate.get("exact_live_match") else ""
        status = f" {candidate['status']}" if candidate.get("status") else ""
        parts.append(f"{candidate['kind']}{exact}{status}: `{candidate['ref']}`")
    return "<br>".join(parts)


def _path_candidate_keys(path: Path, text: str) -> set[str]:
    title = _frontmatter_field(text, "title") or _first_heading(text)
    slug = _frontmatter_field(text, "slug")
    keys = source_keys(path.stem, path.name, str(path), title or "", slug or "")
    if path.name == "index.html" and "omg_web_builder" in str(path):
        keys.add("landing-page")
    return keys


def source_keys(*values: object) -> set[str]:
    keys: set[str] = set()
    for value in values:
        if value is None:
            continue
        text = str(value)
        if not text:
            continue
        pieces = [text, _last_path_segment(text)]
        for piece in pieces:
            slug = _slugify(piece)
            if not slug:
                continue
            keys.add(slug)
            keys.add(_strip_date_prefix(slug))
            keys.add(_strip_leading_article(_strip_date_prefix(slug)))
            if slug.endswith("-2026"):
                keys.add(slug[: -len("-2026")])
    return {key for key in keys if key}


def _dedupe_candidates(candidates: list[SourceCandidate]) -> list[SourceCandidate]:
    seen: set[tuple[str, str, str | None]] = set()
    deduped: list[SourceCandidate] = []
    for candidate in candidates:
        key = (candidate.kind, candidate.ref, candidate.text_sha256)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _slug_from_log_filename(filename: str) -> str:
    for suffix in (
        ".omg-weblog.json",
        ".cross-provider-review.json",
        ".zenodo-doi.json",
        ".bluesky-post.json",
        ".mastodon-post.json",
    ):
        if filename.endswith(suffix):
            return filename[: -len(suffix)]
    return filename.removesuffix(".json")


def _frontmatter_field(text: str, field: str) -> str | None:
    pattern = re.compile(rf"^{re.escape(field)}:\s*['\"]?(.+?)['\"]?\s*$", re.I | re.M)
    match = pattern.search(text[:2000])
    if match:
        return match.group(1).strip()
    return None


def _first_heading(text: str) -> str | None:
    match = re.search(r"^#\s+(.+?)\s*$", text, re.M)
    return match.group(1).strip() if match else None


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _strip_date_prefix(slug: str) -> str:
    return re.sub(r"^\d{4}-\d{2}-\d{2}-", "", slug)


def _strip_leading_article(slug: str) -> str:
    return slug[4:] if slug.startswith("the-") else slug


def _last_path_segment(value: str) -> str:
    return value.rstrip("/").rsplit("/", 1)[-1] if value else ""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        pass
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def _string_or_empty(value: object) -> str:
    return value if isinstance(value, str) else ""


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    return None


def _md_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
