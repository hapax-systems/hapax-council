from __future__ import annotations

import json
from pathlib import Path

import httpx

from agents.unb_airy.literature_bridge import (
    CrossRefClient,
    JsonFileCache,
    LiteratureBridge,
    LiteratureLink,
    PaperCitationMetadata,
    SemanticScholarClient,
    SimpleRateLimiter,
    assertion_value_score,
    infer_relation,
    run_literature_bridge,
    write_literature_links_to_frontmatter,
)


def _assertion(score: object = 0.9) -> dict[str, object]:
    return {
        "assertion_id": "a1",
        "text": "Agent governance hooks reduce unsafe autonomous code changes.",
        "atomic_facts": ["governance hooks reduce unsafe changes"],
        "source_type": "governance",
        "source_uri": "spec.md",
        "confidence": 0.9,
        "domain": "ai-governance",
        "assertion_type": "claim",
        "score": {"composite": score},
    }


def _semantic_payload() -> dict[str, object]:
    return {
        "total": 1,
        "data": [
            {
                "paperId": "s2-1",
                "title": "Governance Hooks for Safer Autonomous Agents",
                "abstract": "Governance hooks reduce unsafe autonomous code changes.",
                "year": 2025,
                "venue": "AI Safety",
                "url": "https://semanticscholar.org/paper/s2-1",
                "authors": [{"authorId": "42", "name": "Ada Researcher"}],
                "externalIds": {"DOI": "10.1234/example"},
                "citationCount": 25,
                "influentialCitationCount": 3,
                "openAccessPdf": {"url": "https://example.test/paper.pdf"},
                "isOpenAccess": True,
            }
        ],
    }


def _crossref_payload() -> dict[str, object]:
    return {
        "status": "ok",
        "message": {
            "DOI": "10.1234/example",
            "title": ["Governance Hooks for Safer Autonomous Agents"],
            "container-title": ["AI Safety"],
            "published-print": {"date-parts": [[2025, 1, 1]]},
            "type": "journal-article",
            "publisher": "Example Press",
        },
    }


def test_semantic_scholar_search_uses_fields_headers_and_cache(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path == "/graph/v1/paper/search"
        assert request.url.params["query"] == "agent governance"
        assert request.url.params["fields"]
        assert request.headers["x-api-key"] == "secret"
        return httpx.Response(200, json=_semantic_payload())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    s2 = SemanticScholarClient(
        http_client=client,
        api_key="secret",
        cache=JsonFileCache(tmp_path),
        rate_limiter=SimpleRateLimiter(min_interval_s=0),
    )

    first = s2.search_papers("agent governance", limit=2)
    second = s2.search_papers("agent governance", limit=2)

    assert len(first) == 1
    assert first[0].semantic_scholar_id == "s2-1"
    assert first[0].doi == "10.1234/example"
    assert len(second) == 1
    assert len(seen) == 1


def test_bridge_enriches_only_high_value_assertions_and_verifies_doi(tmp_path: Path) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/graph/v1/paper/search":
            return httpx.Response(200, json=_semantic_payload())
        if request.url.path in {"/works/10.1234%2Fexample", "/works/10.1234/example"}:
            return httpx.Response(200, json=_crossref_payload())
        return httpx.Response(404)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    cache = JsonFileCache(tmp_path)
    bridge = LiteratureBridge(
        semantic_scholar=SemanticScholarClient(
            http_client=http_client,
            cache=cache,
            rate_limiter=SimpleRateLimiter(min_interval_s=0),
        ),
        crossref=CrossRefClient(
            http_client=http_client,
            cache=cache,
            rate_limiter=SimpleRateLimiter(min_interval_s=0),
        ),
        min_score=0.7,
        papers_per_assertion=1,
    )

    enriched = bridge.enrich_assertions([_assertion(0.95), _assertion(0.2)])

    assert len(enriched[0]["literature_links"]) == 1
    link = enriched[0]["literature_links"][0]
    assert link["relation"] == "support"
    assert link["paper"]["crossref"]["published_year"] == 2025
    assert "literature_links" not in enriched[1]
    assert requests == ["/graph/v1/paper/search", "/works/10.1234/example"]


def test_run_literature_bridge_writes_json_output(tmp_path: Path) -> None:
    input_path = tmp_path / "assertions.json"
    output_path = tmp_path / "enriched.json"
    input_path.write_text(json.dumps({"assertions": [_assertion()]}), encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/graph/v1/paper/search":
            return httpx.Response(200, json=_semantic_payload())
        return httpx.Response(200, json=_crossref_payload())

    records = run_literature_bridge(
        input_path=input_path,
        output_path=output_path,
        cache_dir=tmp_path / "cache",
        api_key=None,
        min_score=0.7,
        papers_per_assertion=1,
        include_unscored=False,
        write_source_frontmatter=False,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert records[0]["literature_links"][0]["paper"]["semantic_scholar_id"] == "s2-1"
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved[0]["literature_links"][0]["paper"]["doi"] == "10.1234/example"


def test_crossref_404_leaves_paper_unverified(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    crossref = CrossRefClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        cache=JsonFileCache(tmp_path),
        rate_limiter=SimpleRateLimiter(min_interval_s=0),
    )

    assert crossref.lookup_doi("10.404/missing") is None


def test_frontmatter_writer_stores_literature_links(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("---\ntitle: Test\n---\nBody\n", encoding="utf-8")
    link = LiteratureLink(
        assertion_id="a1",
        relation="extend",
        confidence=0.5,
        query="q",
        paper=PaperCitationMetadata(semantic_scholar_id="s2", title="Paper"),
    )

    write_literature_links_to_frontmatter(note, [link])

    text = note.read_text(encoding="utf-8")
    assert "literature_links:" in text
    assert "semantic_scholar_id: s2" in text
    assert text.endswith("Body\n")


def test_score_detection_and_relation_heuristics() -> None:
    assert assertion_value_score({"value_score": {"composite_score": "0.81"}}) == 0.81
    assert assertion_value_score({"tags": ["score:0.72"]}) == 0.72
    assert assertion_value_score({"score": True}) is None

    paper = PaperCitationMetadata(
        semantic_scholar_id="s2",
        title="A challenge to autonomous agent safety claims",
        abstract="This paper challenges common claims.",
    )
    assert infer_relation("autonomous agent safety claims", paper) == "contradict"
