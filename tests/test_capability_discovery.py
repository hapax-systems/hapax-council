"""Tests for novel capability discovery meta-affordance."""

from agents.hapax_daimonion.discovery_affordance import (
    DISCOVERY_AFFORDANCE,
    CapabilityDiscoveryHandler,
)
from shared.tavily_client import (
    TavilyConfigError,
    TavilyPolicyViolation,
    TavilySearchResponse,
    TavilySearchResult,
)


def test_discovery_affordance_exists():
    name, desc = DISCOVERY_AFFORDANCE
    assert name == "capability_discovery"
    assert "discover" in desc.lower() or "find" in desc.lower()


def test_discovery_handler_extracts_unresolved_intent():
    from shared.impingement import Impingement, ImpingementType

    imp = Impingement(
        source="exploration.boredom",
        type=ImpingementType.BOREDOM,
        timestamp=0.0,
        strength=0.8,
        content={"narrative": "I wonder what that song sounds like"},
    )
    handler = CapabilityDiscoveryHandler()
    intent = handler.extract_intent(imp)
    assert "song" in intent.lower()


def test_discovery_handler_consent_required():
    handler = CapabilityDiscoveryHandler()
    assert handler.consent_required is True


def test_discovery_handler_search_uses_tavily(monkeypatch):
    calls = []

    class FakeClient:
        def search(self, request):
            calls.append(request)
            return TavilySearchResponse(
                results=[
                    TavilySearchResult(
                        title="Example Tool",
                        url="https://example.com/tool",
                        content="A useful capability.",
                    )
                ]
            )

    monkeypatch.setattr(
        "agents.hapax_daimonion.discovery_affordance.TavilyClient",
        lambda: FakeClient(),
    )

    results = CapabilityDiscoveryHandler().search("need better visual search")

    assert results == [
        {
            "name": "Example Tool",
            "description": "A useful capability.",
            "source": "https://example.com/tool",
        }
    ]
    assert calls[0].lane == "discovery_affordance"


def test_discovery_handler_search_skips_without_tavily_key(monkeypatch):
    class FakeClient:
        def search(self, request):
            raise TavilyConfigError("missing key")

    monkeypatch.setattr(
        "agents.hapax_daimonion.discovery_affordance.TavilyClient",
        lambda: FakeClient(),
    )

    assert CapabilityDiscoveryHandler().search("need a tool") == []


def test_discovery_handler_search_error_log_redacts_intent(monkeypatch, caplog):
    raw_intent = "from: private@example.com internal only capability"

    class FakeClient:
        def search(self, request):
            raise TavilyPolicyViolation("query rejected")

    monkeypatch.setattr(
        "agents.hapax_daimonion.discovery_affordance.TavilyClient",
        lambda: FakeClient(),
    )

    with caplog.at_level("DEBUG", logger="capability.discovery"):
        assert CapabilityDiscoveryHandler().search(raw_intent) == []
    assert raw_intent not in caplog.text
    assert "intent_hash=" in caplog.text
