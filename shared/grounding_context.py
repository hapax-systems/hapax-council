"""Grounding context envelope and clause verifier.

Provides ``GroundingContextEnvelope`` as the mandatory turn artifact
for voice and autonomous narration, with clause-level deterministic
verification before TTS.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

type ClauseVerdictKind = Literal["safe", "refused", "corrected"]


class ClauseVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ClauseVerdictKind
    reason: str | None = None
    original: str = ""
    corrected: str | None = None


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


class TurnVerificationLog(BaseModel):
    model_config = ConfigDict(frozen=True)

    turn_id: str
    context_hash: str
    recruited_tools: list[str]
    clauses_checked: int = 0
    clauses_safe: int = 0
    clauses_refused: int = 0
    clauses_corrected: int = 0
    verdicts: list[ClauseVerdict] = Field(default_factory=list)


_STALE_KEYWORDS = frozenset({"now", "currently", "live", "current"})
_ANTICIPATORY_WORDS = frozenset(
    {
        "expected",
        "likely",
        "predicted",
        "anticipate",
        "probably",
        "will",
        "might",
        "could",
        "may",
        "perhaps",
    }
)
_FACTUAL_VERBS = frozenset({"is", "are", "happening", "has", "was"})
_DEICTIC_PHRASES = (
    "look at this",
    "look at that",
    "see this",
    "this screen",
    "what you see",
    "on screen now",
    "visible here",
)
_CORRECTION_TEMPLATES: dict[str, str] = {
    "stale_now": "That cannot be verified from the current temporal impression.",
    "protention_as_fact": "That is anticipated but not yet confirmed.",
    "deictic_visual": "A visual reference cannot be grounded without tool output.",
    "below_floor": "That claim does not meet the required evidence floor.",
}


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

        forbidden: list[str] = []
        if source_freshness != "fresh":
            forbidden.append("present-tense current-world factual claims")
            forbidden.append("live deictic visual references without visual tool output")

        has_protention = bool(temporal_bands.get("protention"))
        if has_protention:
            forbidden.append("protention stated as fact without anticipatory language")

        data: dict[str, Any] = {
            "turn_id": turn_id,
            "assembled_at": time.time(),
            "source_freshness": source_freshness,
            "temporal_bands": temporal_bands,
            "phenomenal_lines": phenomenal_lines,
            "available_tools": available_tools,
            "recruited_tools": recruited_tools or [],
            "forbidden_assertions": forbidden,
        }

        content_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
        data["context_hash"] = hashlib.sha256(content_bytes).hexdigest()

        return GroundingContextEnvelope(**data)

    @staticmethod
    def render_xml(envelope: GroundingContextEnvelope) -> str:
        """Render the envelope as XML for the system prompt."""
        lines = ["<grounding_context>"]

        lines.append(f"  <source_freshness>{envelope.source_freshness}</source_freshness>")

        if envelope.recruited_tools:
            lines.append("  <recruited_tools>")
            for t in envelope.recruited_tools:
                lines.append(f"    <tool>{t}</tool>")
            lines.append("  </recruited_tools>")

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
        verdict = GroundingContextVerifier.verify_clause_structured(envelope, sentence)
        if verdict.kind == "safe":
            return True, None
        return False, verdict.reason

    @staticmethod
    def verify_clause_structured(
        envelope: GroundingContextEnvelope, sentence: str
    ) -> ClauseVerdict:
        """Structured clause verification with correction suggestions."""
        s = sentence.lower()
        words = set(s.replace(".", "").replace(",", "").replace("!", "").replace("?", "").split())

        if envelope.source_freshness != "fresh":
            if words.intersection(_STALE_KEYWORDS):
                return ClauseVerdict(
                    kind="refused",
                    reason="stale impression cannot ground 'now' or 'currently'",
                    original=sentence,
                    corrected=_CORRECTION_TEMPLATES["stale_now"],
                )

        if (
            "protention stated as fact without anticipatory language"
            in envelope.forbidden_assertions
        ):
            if words.intersection(_FACTUAL_VERBS) and not words.intersection(_ANTICIPATORY_WORDS):
                return ClauseVerdict(
                    kind="corrected",
                    reason="protention stated as fact",
                    original=sentence,
                    corrected=_CORRECTION_TEMPLATES["protention_as_fact"],
                )

        if (
            "live deictic visual references without visual tool output"
            in envelope.forbidden_assertions
        ):
            if any(phrase in s for phrase in _DEICTIC_PHRASES):
                return ClauseVerdict(
                    kind="refused",
                    reason="ungrounded deictic visual reference",
                    original=sentence,
                    corrected=_CORRECTION_TEMPLATES["deictic_visual"],
                )

        if envelope.claims and not envelope.claims[0]:
            if words.intersection(_FACTUAL_VERBS) and envelope.source_freshness != "fresh":
                return ClauseVerdict(
                    kind="refused",
                    reason="factual claim with empty claim envelope",
                    original=sentence,
                    corrected=_CORRECTION_TEMPLATES["below_floor"],
                )

        return ClauseVerdict(kind="safe", original=sentence)

    @staticmethod
    def log_turn_verification(
        envelope: GroundingContextEnvelope, verdicts: list[ClauseVerdict]
    ) -> TurnVerificationLog:
        """Build a structured log entry for a turn's clause verification."""
        entry = TurnVerificationLog(
            turn_id=envelope.turn_id,
            context_hash=envelope.context_hash,
            recruited_tools=list(envelope.recruited_tools),
            clauses_checked=len(verdicts),
            clauses_safe=sum(1 for v in verdicts if v.kind == "safe"),
            clauses_refused=sum(1 for v in verdicts if v.kind == "refused"),
            clauses_corrected=sum(1 for v in verdicts if v.kind == "corrected"),
            verdicts=verdicts,
        )
        log.info(
            "grounding turn %s: %d checked, %d safe, %d refused, %d corrected "
            "(context_hash=%s, tools=%s)",
            entry.turn_id,
            entry.clauses_checked,
            entry.clauses_safe,
            entry.clauses_refused,
            entry.clauses_corrected,
            entry.context_hash[:12],
            entry.recruited_tools,
        )
        return entry
