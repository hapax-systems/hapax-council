"""Research convergence and finding persistence rule."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from agents.session_conductor.rules import HookEvent, HookResponse, RuleBase
from agents.session_conductor.state import (
    MAX_RESEARCH_ROUNDS,
    TopicState,
)
from agents.session_conductor.topology import TopologyConfig

log = logging.getLogger(__name__)

DEFAULT_CONTEXT_DIR = Path.home() / ".cache" / "hapax" / "relay" / "context"

_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "and",
        "or",
        "all",
        "any",
        "some",
        "this",
        "that",
        "with",
        "from",
        "by",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "have",
        "has",
        "had",
        "it",
        "its",
        "not",
        "no",
        "nor",
        "so",
        "yet",
        "both",
        "either",
        "each",
        "few",
        "more",
        "most",
        "other",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "up",
        "down",
        "out",
        "off",
        "over",
        "under",
        "then",
        "once",
        "about",
        "against",
        "between",
        "own",
        "same",
        "than",
        "too",
        "very",
        "research",
        "investigate",
        "explore",
        "find",
        "look",
        "check",
    }
)

_BULLET_RE = re.compile(r"^\s*[-*•]\s+\S", re.MULTILINE)
_NUMBERED_RE = re.compile(r"^\s*\d+\.\s+\S", re.MULTILINE)


def extract_topic_slug(text: str) -> str:
    """Strip stop words, take up to 3 distinctive words, join with '-'."""
    words = re.sub(r"[^a-z0-9\s]", "", text.lower()).split()
    distinctive = [w for w in words if w not in _STOP_WORDS and len(w) > 2]
    chosen = distinctive[:3]
    return "-".join(chosen) if chosen else "unknown"


def count_findings(text: str) -> int:
    """Count bullet points and numbered items in text."""
    bullets = len(_BULLET_RE.findall(text))
    numbered = len(_NUMBERED_RE.findall(text))
    return bullets + numbered


class ConvergenceRule(RuleBase):
    """Track research topic rounds and block when convergence is detected."""

    def __init__(
        self,
        topology: TopologyConfig,
        context_dir: Path | None = None,
    ) -> None:
        super().__init__(topology)
        self.context_dir = context_dir or DEFAULT_CONTEXT_DIR
        self.context_dir.mkdir(parents=True, exist_ok=True)
        # slug -> TopicState, lives for the session
        self._session_topics: dict[str, TopicState] = {}

    def _find_matching_topic(self, prompt: str) -> TopicState | None:
        for topic in self._session_topics.values():
            if topic.matches_prompt(prompt):
                return topic
        return None

    def on_pre_tool_use(self, event: HookEvent) -> HookResponse | None:
        if event.tool_name != "Agent":
            return None

        prompt: str = event.tool_input.get("prompt", "")
        if not prompt:
            return None

        topic = self._find_matching_topic(prompt)

        if topic is not None:
            if topic.is_capped():
                log.debug("ConvergenceRule: blocking capped topic %s", topic.slug)
                return HookResponse.block(
                    f"Research topic '{topic.slug}' has reached the maximum of "
                    f"{MAX_RESEARCH_ROUNDS} rounds. Move on."
                )
            if topic.is_converging():
                log.debug("ConvergenceRule: blocking converging topic %s", topic.slug)
                return HookResponse.block(
                    f"Research topic '{topic.slug}' is converging (diminishing returns). "
                    "No further research needed."
                )
            # Inject prior findings if the context file exists and has content
            if topic.prior_file.exists():
                prior_text = topic.prior_file.read_text().strip()
                if prior_text:
                    injected = f"{prompt}\n\n---\nPrior findings on '{topic.slug}':\n{prior_text}"
                    log.debug("ConvergenceRule: injecting prior findings for topic %s", topic.slug)
                    return HookResponse(
                        action="rewrite",
                        message=f"Injected prior findings for topic '{topic.slug}'",
                        rewrite={"prompt": injected},
                    )

        return None

    def on_post_tool_use(self, event: HookEvent) -> HookResponse | None:
        if event.tool_name != "Agent":
            return None

        prompt: str = event.tool_input.get("prompt", "")
        output: str = event.user_message or ""

        slug = extract_topic_slug(prompt)
        findings_count = count_findings(output)

        topic = self._session_topics.get(slug)
        if topic is None:
            prior_file = self.context_dir / f"{slug}.md"
            topic = TopicState(
                slug=slug,
                rounds=0,
                findings_per_round=[],
                first_seen=datetime.now(),
                prior_file=prior_file,
            )
            self._session_topics[slug] = topic

        topic.rounds += 1
        topic.findings_per_round.append(findings_count)

        # Persist findings to context file
        try:
            existing = topic.prior_file.read_text() if topic.prior_file.exists() else ""
            topic.prior_file.write_text(existing + output)
            log.debug(
                "ConvergenceRule: persisted %d findings for topic %s (round %d)",
                findings_count,
                slug,
                topic.rounds,
            )
        except OSError:
            log.exception("ConvergenceRule: failed to persist findings for topic %s", slug)

        return None
