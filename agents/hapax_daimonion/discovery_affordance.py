"""Novel capability discovery — the recursive meta-affordance.

When no existing capability matches an intention, the exploration tracker
emits boredom/curiosity impingements. This affordance matches those signals
and searches for capabilities that could fulfill the unresolved need.

Discovery (searching for what's possible) is read-only and safe.
Acquisition (installing/configuring) requires operator consent.
"""

from __future__ import annotations

import hashlib
import logging

from shared.impingement import Impingement
from shared.tavily_client import (
    TavilyBudgetExceeded,
    TavilyClient,
    TavilyConfigError,
    TavilyPolicyViolation,
    TavilyRequestError,
    TavilySearchRequest,
)

log = logging.getLogger("capability.discovery")

DISCOVERY_AFFORDANCE: tuple[str, str] = (
    "capability_discovery",
    "Discover and acquire new capabilities when no existing capability matches an intention. "
    "Find tools, services, or resources that could fulfill unmet cognitive needs.",
)


class CapabilityDiscoveryHandler:
    """Handles the capability_discovery affordance."""

    consent_required: bool = True

    def extract_intent(self, impingement: Impingement) -> str:
        content = impingement.content or {}
        narrative = content.get("narrative", "")
        if narrative:
            return narrative
        return f"unresolved intent from {impingement.source}"

    def search(self, intent: str) -> list[dict]:
        """Search for capabilities matching the intent via Tavily.

        Returns a list of {name, description, source} dicts for propose().
        Discovery remains read-only; acquisition is still gated by operator consent.
        """
        try:
            response = TavilyClient().search(
                TavilySearchRequest(
                    query=f"{intent} software tool service capability",
                    lane="discovery_affordance",
                    max_results=4,
                    search_depth="basic",
                    include_answer=False,
                )
            )
        except TavilyConfigError:
            log.debug("No Tavily API key found; discovery search skipped")
            return []
        except (TavilyBudgetExceeded, TavilyPolicyViolation, TavilyRequestError):
            intent_hash = hashlib.sha256(intent.encode()).hexdigest()
            log.debug("Discovery search failed for intent_hash=%s", intent_hash, exc_info=True)
            return []
        return [
            {
                "name": result.title or result.url or "web",
                "description": result.content[:200],
                "source": result.url or "tavily",
            }
            for result in response.results
        ]

    def propose(self, capabilities: list[dict]) -> None:
        for cap in capabilities:
            log.info(
                "Discovered potential capability: %s — %s (from %s)",
                cap.get("name", "unknown"),
                cap.get("description", ""),
                cap.get("source", "unknown"),
            )
