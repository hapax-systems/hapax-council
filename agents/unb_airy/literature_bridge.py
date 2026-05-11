"""External literature bridge for Unb-AIRy assertions.

The bridge enriches high-value assertion records with paper metadata from the
Semantic Scholar Academic Graph API and DOI verification metadata from Crossref.
It is intentionally deterministic: no LLM judgement is used to decide relation
labels, and network calls are cacheable and rate-limited.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx
import yaml
from pydantic import BaseModel, Field

from shared.frontmatter import parse_frontmatter

SEMANTIC_SCHOLAR_BASE_URL = "https://api.semanticscholar.org"
CROSSREF_BASE_URL = "https://api.crossref.org"
SEMANTIC_SCHOLAR_FIELDS = ",".join(
    (
        "paperId",
        "title",
        "url",
        "abstract",
        "authors",
        "year",
        "venue",
        "publicationDate",
        "externalIds",
        "citationCount",
        "influentialCitationCount",
        "openAccessPdf",
        "isOpenAccess",
        "fieldsOfStudy",
        "s2FieldsOfStudy",
    )
)

LiteratureRelation = Literal["support", "contradict", "extend"]


class LiteratureBridgeError(RuntimeError):
    """Raised when the literature bridge cannot complete a requested operation."""


class PaperAuthor(BaseModel):
    """Small author projection common to Semantic Scholar and Crossref records."""

    name: str
    author_id: str | None = None


class CrossRefWorkMetadata(BaseModel):
    """Crossref DOI verification metadata."""

    doi: str
    title: str | None = None
    container_title: str | None = None
    published_year: int | None = None
    type: str | None = None
    publisher: str | None = None


class PaperCitationMetadata(BaseModel):
    """Citation metadata stored on assertion frontmatter."""

    semantic_scholar_id: str
    title: str
    abstract: str | None = None
    year: int | None = None
    venue: str | None = None
    authors: list[PaperAuthor] = Field(default_factory=list)
    doi: str | None = None
    url: str | None = None
    external_ids: dict[str, Any] = Field(default_factory=dict)
    citation_count: int = 0
    influential_citation_count: int = 0
    open_access_pdf_url: str | None = None
    is_open_access: bool = False
    crossref: CrossRefWorkMetadata | None = None


class LiteratureLink(BaseModel):
    """A deterministic link between one internal assertion and one paper."""

    assertion_id: str
    relation: LiteratureRelation
    confidence: float
    query: str
    paper: PaperCitationMetadata
    linked_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )


@dataclass
class SimpleRateLimiter:
    """Minimal per-client rate limiter for polite API use."""

    min_interval_s: float = 1.0
    _last_request_monotonic: float = 0.0

    def wait(self) -> None:
        if self.min_interval_s <= 0:
            return
        now = time.monotonic()
        wait_s = self.min_interval_s - (now - self._last_request_monotonic)
        if wait_s > 0:
            time.sleep(wait_s)
        self._last_request_monotonic = time.monotonic()


class JsonFileCache:
    """Tiny JSON cache keyed by namespace + payload."""

    def __init__(self, root: Path | None) -> None:
        self.root = root
        if self.root is not None:
            self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, namespace: str, key: str) -> Path | None:
        if self.root is None:
            return None
        digest = hashlib.sha256(f"{namespace}:{key}".encode()).hexdigest()
        return self.root / f"{namespace}-{digest}.json"

    def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        path = self._path(namespace, key)
        if path is None or not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return raw if isinstance(raw, dict) else None

    def set(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        path = self._path(namespace, key)
        if path is None:
            return
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)


class SemanticScholarClient:
    """Synchronous Semantic Scholar Academic Graph API client."""

    def __init__(
        self,
        *,
        http_client: httpx.Client,
        api_key: str | None = None,
        cache: JsonFileCache | None = None,
        rate_limiter: SimpleRateLimiter | None = None,
        base_url: str = SEMANTIC_SCHOLAR_BASE_URL,
    ) -> None:
        self.http_client = http_client
        self.api_key = api_key
        self.cache = cache or JsonFileCache(None)
        self.rate_limiter = rate_limiter or SimpleRateLimiter()
        self.base_url = base_url.rstrip("/")

    def search_papers(self, query: str, *, limit: int = 5) -> list[PaperCitationMetadata]:
        normalized_query = " ".join(query.split())
        if not normalized_query:
            return []

        params: dict[str, str | int] = {
            "query": normalized_query,
            "limit": max(1, min(limit, 100)),
            "fields": SEMANTIC_SCHOLAR_FIELDS,
            "sort": "citationCount:desc",
        }
        cache_key = json.dumps(params, sort_keys=True)
        cached = self.cache.get("semantic-scholar-search", cache_key)
        if cached is not None:
            return [_paper_from_semantic_scholar(item) for item in cached.get("data", [])]

        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        self.rate_limiter.wait()
        response = self.http_client.get(
            f"{self.base_url}/graph/v1/paper/search",
            params=params,
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise LiteratureBridgeError("Semantic Scholar response was not a JSON object")
        self.cache.set("semantic-scholar-search", cache_key, payload)
        return [_paper_from_semantic_scholar(item) for item in payload.get("data", [])]


class CrossRefClient:
    """Synchronous Crossref DOI lookup client."""

    def __init__(
        self,
        *,
        http_client: httpx.Client,
        cache: JsonFileCache | None = None,
        rate_limiter: SimpleRateLimiter | None = None,
        base_url: str = CROSSREF_BASE_URL,
        mailto: str | None = None,
    ) -> None:
        self.http_client = http_client
        self.cache = cache or JsonFileCache(None)
        self.rate_limiter = rate_limiter or SimpleRateLimiter(min_interval_s=0.5)
        self.base_url = base_url.rstrip("/")
        self.mailto = mailto

    def lookup_doi(self, doi: str | None) -> CrossRefWorkMetadata | None:
        if not doi:
            return None
        normalized = doi.strip().lower()
        cached = self.cache.get("crossref-work", normalized)
        if cached is not None:
            return _crossref_from_payload(cached)

        headers = {"Accept": "application/json"}
        if self.mailto:
            headers["User-Agent"] = f"hapax-unb-airy-literature-bridge (mailto:{self.mailto})"

        self.rate_limiter.wait()
        response = self.http_client.get(
            f"{self.base_url}/works/{quote(normalized, safe='')}",
            headers=headers,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise LiteratureBridgeError("Crossref response was not a JSON object")
        self.cache.set("crossref-work", normalized, payload)
        return _crossref_from_payload(payload)


class LiteratureBridge:
    """Enrich assertion records with external literature links."""

    def __init__(
        self,
        *,
        semantic_scholar: SemanticScholarClient,
        crossref: CrossRefClient,
        min_score: float = 0.7,
        papers_per_assertion: int = 3,
        include_unscored: bool = False,
    ) -> None:
        self.semantic_scholar = semantic_scholar
        self.crossref = crossref
        self.min_score = min_score
        self.papers_per_assertion = papers_per_assertion
        self.include_unscored = include_unscored

    def enrich_assertions(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for record in records:
            next_record = dict(record)
            if is_high_value_assertion(next_record, min_score=self.min_score) or (
                self.include_unscored and assertion_value_score(next_record) is None
            ):
                links = self.link_assertion(next_record)
                next_record["literature_links"] = [link.model_dump(mode="json") for link in links]
                next_record["literature_bridge"] = {
                    "linked_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "query": assertion_search_query(next_record),
                    "min_score": self.min_score,
                    "papers_per_assertion": self.papers_per_assertion,
                }
            enriched.append(next_record)
        return enriched

    def link_assertion(self, record: dict[str, Any]) -> list[LiteratureLink]:
        assertion_id = str(record.get("assertion_id") or "")
        query = assertion_search_query(record)
        papers = self.semantic_scholar.search_papers(query, limit=self.papers_per_assertion)
        links: list[LiteratureLink] = []
        for paper in papers:
            crossref = self.crossref.lookup_doi(paper.doi)
            if crossref is not None:
                paper = paper.model_copy(update={"crossref": crossref})
            relation = infer_relation(record.get("text", ""), paper)
            links.append(
                LiteratureLink(
                    assertion_id=assertion_id,
                    relation=relation,
                    confidence=relation_confidence(record.get("text", ""), paper),
                    query=query,
                    paper=paper,
                )
            )
        return links


def load_assertion_records(path: Path) -> list[dict[str, Any]]:
    """Load assertion records from extractor or normalizer JSON output."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("assertions"), list):
        raw = raw["assertions"]
    if not isinstance(raw, list):
        raise LiteratureBridgeError("input must be a JSON list or an object with assertions[]")
    records: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise LiteratureBridgeError("each assertion record must be a JSON object")
        records.append(item)
    return records


def write_assertion_records(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_literature_links_to_frontmatter(path: Path, links: list[LiteratureLink]) -> None:
    """Store literature link metadata in a markdown file's YAML frontmatter."""

    frontmatter, body = parse_frontmatter(path)
    frontmatter["literature_links"] = [link.model_dump(mode="json") for link in links]
    frontmatter["literature_linked_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    rendered = yaml.safe_dump(frontmatter, sort_keys=False).strip()
    path.write_text(f"---\n{rendered}\n---\n{body}", encoding="utf-8")


def write_source_frontmatter_links(records: list[dict[str, Any]]) -> int:
    """Write links back to markdown source_uri frontmatter when possible."""

    written = 0
    for record in records:
        links_raw = record.get("literature_links")
        if not isinstance(links_raw, list) or not links_raw:
            continue
        source_uri = record.get("source_uri")
        if not isinstance(source_uri, str) or not source_uri.endswith(".md"):
            continue
        path = Path(source_uri)
        if not path.exists():
            continue
        links = [LiteratureLink.model_validate(link) for link in links_raw]
        write_literature_links_to_frontmatter(path, links)
        written += 1
    return written


def assertion_value_score(record: dict[str, Any]) -> float | None:
    """Read Phase 4 score values without depending on Phase 4's final model name."""

    candidates: list[Any] = [
        record.get("composite_score"),
        record.get("value"),
        record.get("value_score"),
        record.get("score"),
    ]
    for container in ("value_score", "score"):
        nested = record.get(container)
        if isinstance(nested, dict):
            candidates.extend(
                [
                    nested.get("composite"),
                    nested.get("composite_score"),
                    nested.get("overall"),
                    nested.get("total"),
                ]
            )
    for tag in record.get("tags", []):
        if isinstance(tag, str) and tag.startswith(("value:", "score:", "composite:")):
            candidates.append(tag.partition(":")[2])

    for candidate in candidates:
        value = _coerce_float(candidate)
        if value is not None:
            return value
    return None


def is_high_value_assertion(record: dict[str, Any], *, min_score: float) -> bool:
    score = assertion_value_score(record)
    return score is not None and score >= min_score


def assertion_search_query(record: dict[str, Any]) -> str:
    """Build a compact search query from assertion text and atomic facts."""

    text = str(record.get("text") or "").strip()
    facts = record.get("atomic_facts")
    if isinstance(facts, list) and facts:
        fact_text = " ".join(str(fact) for fact in facts[:2])
        text = f"{text} {fact_text}".strip()
    return " ".join(text.split())[:300]


def infer_relation(assertion_text: str, paper: PaperCitationMetadata) -> LiteratureRelation:
    """Deterministic, conservative relation label.

    This is a retrieval relation, not a truth judgement. It marks obvious
    challenge/friction language as contradiction candidates, strong lexical
    overlap as support, and everything else as extension.
    """

    haystack = f"{paper.title} {paper.abstract or ''}".lower()
    if any(word in haystack for word in ("contradict", "challenge", "against", "fails to")):
        return "contradict"
    overlap = _token_overlap(assertion_text, f"{paper.title} {paper.abstract or ''}")
    if overlap >= 0.18:
        return "support"
    return "extend"


def relation_confidence(assertion_text: str, paper: PaperCitationMetadata) -> float:
    overlap = _token_overlap(assertion_text, f"{paper.title} {paper.abstract or ''}")
    citation_signal = min(0.2, paper.citation_count / 1000)
    confidence = 0.35 + overlap * 0.6 + citation_signal
    return round(max(0.0, min(confidence, 1.0)), 3)


def run_literature_bridge(
    *,
    input_path: Path,
    output_path: Path,
    cache_dir: Path | None,
    api_key: str | None,
    min_score: float,
    papers_per_assertion: int,
    include_unscored: bool,
    write_source_frontmatter: bool,
    http_client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Run the bridge for tests and CLI callers."""

    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=20.0)
    try:
        cache = JsonFileCache(cache_dir)
        semantic = SemanticScholarClient(
            http_client=client,
            api_key=api_key,
            cache=cache,
            rate_limiter=SimpleRateLimiter(min_interval_s=1.0),
            base_url=os.environ.get(
                "UNB_AIRY_SEMANTIC_SCHOLAR_BASE_URL", SEMANTIC_SCHOLAR_BASE_URL
            ),
        )
        crossref = CrossRefClient(
            http_client=client,
            cache=cache,
            rate_limiter=SimpleRateLimiter(min_interval_s=0.5),
            base_url=os.environ.get("UNB_AIRY_CROSSREF_BASE_URL", CROSSREF_BASE_URL),
            mailto=os.environ.get("HAPAX_CROSSREF_MAILTO"),
        )
        bridge = LiteratureBridge(
            semantic_scholar=semantic,
            crossref=crossref,
            min_score=min_score,
            papers_per_assertion=papers_per_assertion,
            include_unscored=include_unscored,
        )
        records = load_assertion_records(input_path)
        enriched = bridge.enrich_assertions(records)
        write_assertion_records(output_path, enriched)
        if write_source_frontmatter:
            write_source_frontmatter_links(enriched)
        return enriched
    finally:
        if owns_client:
            client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Link high-value Unb-AIRy assertions to external literature.",
    )
    parser.add_argument("input", type=Path, help="Assertion JSON list or normalizer output.")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Enriched JSON output.")
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/unb-airy-literature"))
    parser.add_argument("--min-score", type=float, default=0.7)
    parser.add_argument("--papers-per-assertion", type=int, default=3)
    parser.add_argument("--include-unscored", action="store_true")
    parser.add_argument(
        "--write-source-frontmatter",
        action="store_true",
        help="Also write literature_links to markdown source_uri frontmatter.",
    )
    args = parser.parse_args(argv)

    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY") or os.environ.get("S2_API_KEY")
    try:
        enriched = run_literature_bridge(
            input_path=args.input,
            output_path=args.output,
            cache_dir=args.cache_dir,
            api_key=api_key,
            min_score=args.min_score,
            papers_per_assertion=args.papers_per_assertion,
            include_unscored=args.include_unscored,
            write_source_frontmatter=args.write_source_frontmatter,
        )
    except (httpx.HTTPError, LiteratureBridgeError, OSError, ValueError) as exc:
        print(f"literature_bridge: {exc}", file=sys.stderr)
        return 1

    linked = sum(1 for record in enriched if record.get("literature_links"))
    print(f"literature_bridge: linked {linked}/{len(enriched)} assertion(s)", file=sys.stderr)
    return 0


def _paper_from_semantic_scholar(raw: Any) -> PaperCitationMetadata:
    if not isinstance(raw, dict):
        raise LiteratureBridgeError("paper record was not a JSON object")
    external_ids = raw.get("externalIds") if isinstance(raw.get("externalIds"), dict) else {}
    open_access_pdf = raw.get("openAccessPdf") if isinstance(raw.get("openAccessPdf"), dict) else {}
    return PaperCitationMetadata(
        semantic_scholar_id=str(raw.get("paperId") or ""),
        title=str(raw.get("title") or ""),
        abstract=raw.get("abstract") if isinstance(raw.get("abstract"), str) else None,
        year=raw.get("year") if isinstance(raw.get("year"), int) else None,
        venue=raw.get("venue") if isinstance(raw.get("venue"), str) else None,
        authors=[
            PaperAuthor(name=str(author.get("name") or ""), author_id=author.get("authorId"))
            for author in raw.get("authors", [])
            if isinstance(author, dict) and author.get("name")
        ],
        doi=_doi_from_external_ids(external_ids),
        url=raw.get("url") if isinstance(raw.get("url"), str) else None,
        external_ids=external_ids,
        citation_count=int(raw.get("citationCount") or 0),
        influential_citation_count=int(raw.get("influentialCitationCount") or 0),
        open_access_pdf_url=(
            open_access_pdf.get("url") if isinstance(open_access_pdf.get("url"), str) else None
        ),
        is_open_access=bool(raw.get("isOpenAccess")),
    )


def _crossref_from_payload(payload: dict[str, Any]) -> CrossRefWorkMetadata | None:
    message = payload.get("message")
    if not isinstance(message, dict):
        return None
    doi = message.get("DOI")
    if not isinstance(doi, str) or not doi:
        return None
    return CrossRefWorkMetadata(
        doi=doi,
        title=_first_string(message.get("title")),
        container_title=_first_string(message.get("container-title")),
        published_year=_crossref_year(message),
        type=message.get("type") if isinstance(message.get("type"), str) else None,
        publisher=message.get("publisher") if isinstance(message.get("publisher"), str) else None,
    )


def _crossref_year(message: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "published", "issued"):
        value = message.get(key)
        if not isinstance(value, dict):
            continue
        parts = value.get("date-parts")
        if (
            isinstance(parts, list)
            and parts
            and isinstance(parts[0], list)
            and parts[0]
            and isinstance(parts[0][0], int)
        ):
            return parts[0][0]
    return None


def _doi_from_external_ids(external_ids: dict[str, Any]) -> str | None:
    for key in ("DOI", "doi"):
        value = external_ids.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _first_string(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result < 0:
        return None
    return min(result, 1.0)


def _token_overlap(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def _tokens(text: str) -> set[str]:
    stop = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "be",
        "by",
        "for",
        "in",
        "is",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "with",
    }
    return {
        token for token in re.findall(r"[a-z0-9][a-z0-9-]{2,}", text.lower()) if token not in stop
    }


if __name__ == "__main__":
    raise SystemExit(main())
