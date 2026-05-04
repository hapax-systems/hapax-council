"""Grounding context envelope and clause verifier."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GroundingContextEnvelope(BaseModel):
    """Canonical grounding context for a conversational turn."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    turn_id: str
    assembled_at: float
    source_freshness: str
    temporal_bands: dict[str, Any]
    phenomenal_lines: list[str]
    claims: list[str] = Field(default_factory=list)
    claim_floor: str = "diagnostic"
    available_tools: list[str] = Field(default_factory=list)
    recruited_tools: list[str] = Field(default_factory=list)
    required_witnesses: list[str] = Field(default_factory=list)
    forbidden_assertions: list[str] = Field(default_factory=list)
    context_hash: str


class GroundingContextVerifier:
    """Verifies that TTS clauses do not violate the grounding envelope."""

    @staticmethod
    def build_envelope(
        turn_id: str,
        temporal_bands: dict[str, Any],
        phenomenal_lines: list[str],
        available_tools: list[str],
        recruited_tools: list[str] | None = None,
    ) -> GroundingContextEnvelope:
        """Assemble the context envelope prior to prompt generation."""
        impression = temporal_bands.get("impression", {})
        source_freshness = impression.get("freshness", "missing")

        forbidden = []
        if source_freshness != "fresh":
            forbidden.append("present-tense current-world factual claims")
            forbidden.append("live deictic visual references without visual tool output")

        has_protention = bool(temporal_bands.get("protention"))
        if has_protention:
            forbidden.append("protention stated as fact without anticipatory language")

        data = {
            "turn_id": turn_id,
            "assembled_at": time.time(),
            "source_freshness": source_freshness,
            "temporal_bands": temporal_bands,
            "phenomenal_lines": phenomenal_lines,
            "available_tools": available_tools,
            "recruited_tools": recruited_tools or [],
            "forbidden_assertions": forbidden,
        }

        # Calculate context hash deterministically
        content_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
        data["context_hash"] = hashlib.sha256(content_bytes).hexdigest()

        return GroundingContextEnvelope(**data)

    @staticmethod
    def render_xml(envelope: GroundingContextEnvelope) -> str:
        """Render the envelope as XML for the system prompt."""
        lines = ["<grounding_context>"]

        if envelope.phenomenal_lines:
            lines.append("  <phenomenal_situation>")
            for line in envelope.phenomenal_lines:
                lines.append(f"    {line}")
            lines.append("  </phenomenal_situation>")

        if envelope.forbidden_assertions:
            lines.append("  <forbidden_assertions>")
            for f in envelope.forbidden_assertions:
                lines.append(f"    <forbidden>{f}</forbidden>")
            lines.append("  </forbidden_assertions>")

        lines.append("</grounding_context>")
        return "\n".join(lines)

    @staticmethod
    def verify_clause(envelope: GroundingContextEnvelope, sentence: str) -> tuple[bool, str | None]:
        """Verify a single clause before TTS.

        Returns (True, None) if safe.
        Returns (False, reason) if it violates grounding constraints.
        """
        s = sentence.lower()
        words = set(s.replace(".", "").replace(",", "").replace("!", "").replace("?", "").split())

        # 1. Stale "now/currently" check
        if envelope.source_freshness != "fresh":
            if words.intersection({"now", "currently", "live", "current"}):
                return False, "stale impression cannot ground 'now' or 'currently'"

        # 2. Protention stated as fact
        # If we have a protention but no fresh impression, we cannot state facts as if they happened.
        if (
            "protention stated as fact without anticipatory language"
            in envelope.forbidden_assertions
        ):
            anticipatory_words = {
                "expected",
                "likely",
                "predicted",
                "anticipate",
                "probably",
                "will",
                "might",
                "could",
            }
            if words.intersection({"is", "are", "happening", "has"}) and not words.intersection(
                anticipatory_words
            ):
                return False, "protention stated as fact"

        # 3. Ungrounded deictic visual references
        if (
            "live deictic visual references without visual tool output"
            in envelope.forbidden_assertions
        ):
            deictic_phrases = [
                "look at this",
                "look at that",
                "see this",
                "this screen",
                "what you see",
            ]
            if any(phrase in s for phrase in deictic_phrases):
                return False, "ungrounded deictic visual reference"

        # 4. Below-floor current-world claims
        # Handled by freshness and protention checks broadly.

        return True, None
