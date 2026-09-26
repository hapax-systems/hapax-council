"""search_snippets renders one Tavily search without calling the network."""

from __future__ import annotations

from shared.tavily_client import (
    TavilySearchResponse,
    TavilySearchResult,
    search_snippets,
)


class _FakeClient:
    def __init__(self) -> None:
        self.request = None

    def search(self, request):
        self.request = request
        return TavilySearchResponse(
            query=request.query,
            results=[
                TavilySearchResult(
                    title="Stigmergy",
                    url="https://example.com/stigmergy",
                    content="indirect coordination",
                )
            ],
        )


def test_search_snippets_renders_title_url_and_content() -> None:
    client = _FakeClient()
    text = search_snippets("stigmergy", lane="scout_horizon", max_results=3, client=client)
    assert client.request is not None
    assert client.request.lane == "scout_horizon"
    assert client.request.max_results == 3
    assert "Stigmergy" in text
    assert "https://example.com/stigmergy" in text
    assert "indirect coordination" in text
