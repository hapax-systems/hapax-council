"""Per-turn context anchoring evaluation — lightweight mechanical scoring.

Runs after each _generate_and_speak() in the voice pipeline. No LLM call
in the hot path — pure heuristics using word overlap and keyword matching.

Three scores pushed to Langfuse via hapax_score():
  - context_anchor_success: response demonstrates awareness of established context
  - reference_accuracy: references to prior turns are factually consistent
  - acceptance_type: classifies operator response as ACCEPT/CLARIFY/IGNORE/REJECT
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)


# ── Acceptance classification keywords ──────────────────────────────────────

_ACCEPT_PATTERNS: list[str] = [
    "yeah",
    "yes",
    "right",
    "exactly",
    "correct",
    "sure",
    "okay",
    "ok",
    "got it",
    "makes sense",
    "that's right",
    "true",
    "yep",
    "mhm",
    "mm-hmm",
    "uh-huh",
    "cool",
    "nice",
    "great",
    "perfect",
    "good",
    "thanks",
    "thank you",
]

_REJECT_PATTERNS: list[str] = [
    "no",
    "nope",
    "wrong",
    "that's not",
    "that's wrong",
    "incorrect",
    "not what i",
    "you're wrong",
    "that's not right",
]

_CLARIFY_PATTERNS: list[str] = [
    "what do you mean",
    "can you explain",
    "what?",
    "huh?",
    "sorry?",
    "i don't understand",
    "say again",
    "come again",
    "elaborate",
    "what are you",
    "which one",
]


def _classify_acceptance_keywords(utterance: str) -> tuple[str, float]:
    """Keyword-based acceptance classification (fallback)."""
    lower = utterance.lower().strip()
    if not lower:
        return "IGNORE", 0.3

    for pat in _REJECT_PATTERNS:
        if pat in lower:
            return "REJECT", 0.0

    for pat in _CLARIFY_PATTERNS:
        if pat in lower:
            return "CLARIFY", 0.7

    for pat in _ACCEPT_PATTERNS:
        if pat in lower:
            return "ACCEPT", 1.0

    return "IGNORE", 0.3


# Embedding-based acceptance prototypes (Council IV Repair 3).
# Uses nomic-embed for cosine similarity against prototype utterances.
# Falls back to keyword matching if embedding service is unavailable.
_ACCEPTANCE_PROTOTYPES: dict[str, list[str]] = {
    "ACCEPT": [
        "yeah exactly",
        "right, that makes sense",
        "okay good",
        "yes that's correct",
        "got it, thanks",
        "perfect",
    ],
    "REJECT": [
        "no that's wrong",
        "I disagree with that",
        "that's not what I meant",
        "you're completely off",
        "no, stop",
    ],
    "CLARIFY": [
        "wait, what do you mean by that",
        "can you explain that differently",
        "I'm not sure I follow",
        "yeah but what about the other part",
        "hmm, let me think about that",
    ],
}

_prototype_embeddings: dict[str, list[list[float]]] | None = None


def _get_prototype_embeddings() -> dict[str, list[list[float]]] | None:
    """Lazily compute prototype embeddings."""
    global _prototype_embeddings  # noqa: PLW0603
    if _prototype_embeddings is not None:
        return _prototype_embeddings
    try:
        from shared.config import embed

        result: dict[str, list[list[float]]] = {}
        for label, texts in _ACCEPTANCE_PROTOTYPES.items():
            result[label] = [embed(t) for t in texts]
        _prototype_embeddings = result
        return result
    except Exception:
        _log.debug("Embedding unavailable for acceptance prototypes — using keyword fallback")
        return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def classify_acceptance(utterance: str) -> tuple[str, float]:
    """Classify operator utterance into acceptance type.

    Uses embedding similarity against prototype utterances when available,
    falls back to keyword matching. No generative LLM in the path.

    Returns (label, score) where score maps:
      ACCEPT=1.0, CLARIFY=0.7, IGNORE=0.3, REJECT=0.0
    """
    lower = utterance.lower().strip()
    if not lower:
        return "IGNORE", 0.3

    protos = _get_prototype_embeddings()
    if protos is None:
        return _classify_acceptance_keywords(utterance)

    try:
        from shared.config import embed

        utt_vec = embed(utterance)
        best_label = "IGNORE"
        best_sim = -1.0

        for label, proto_vecs in protos.items():
            for pvec in proto_vecs:
                sim = _cosine_similarity(utt_vec, pvec)
                if sim > best_sim:
                    best_sim = sim
                    best_label = label

        if best_sim < 0.4:
            return _classify_acceptance_keywords(utterance)

        score_map = {"ACCEPT": 1.0, "CLARIFY": 0.7, "IGNORE": 0.3, "REJECT": 0.0}
        return best_label, score_map.get(best_label, 0.3)
    except Exception:
        return _classify_acceptance_keywords(utterance)


def score_context_anchor(
    response: str,
    conversation_thread: list[str],
    recent_user_turns: list[str],
) -> float:
    """Score how well a response demonstrates awareness of conversation context.

    Measures word overlap between the response and the conversation thread
    (accumulated topic summaries). Higher overlap = better anchoring.

    Returns float 0.0-1.0.
    """
    if not conversation_thread or not response:
        return 0.5  # no thread yet → neutral (can't measure)

    resp_words = set(_significant_words(response))
    if not resp_words:
        return 0.5

    # Build context word set from thread + recent user turns
    context_words: set[str] = set()
    for entry in conversation_thread:
        context_words.update(_significant_words(entry))
    for turn in recent_user_turns[-3:]:
        context_words.update(_significant_words(turn))

    if not context_words:
        return 0.5

    overlap = resp_words & context_words
    # Proportion of response words that connect to established context
    return min(1.0, len(overlap) / max(1, min(len(resp_words), 10)))


def score_reference_accuracy(
    response: str,
    messages: list[dict],
    lcs_fn=None,
) -> float:
    """Score whether references to prior turns are factually consistent.

    Uses LCS word overlap between response clauses that contain referential
    language ("you said", "earlier", "we discussed") and actual prior content.

    Returns float 0.0-1.0. Returns 1.0 if no references detected (no claim made).
    """
    if not messages or not response:
        return 1.0

    # Detect referential phrases
    ref_patterns = re.compile(
        r"(you (said|mentioned|asked|told)|earlier|before|last time|"
        r"we (discussed|talked|were)|as i said|like i mentioned)",
        re.IGNORECASE,
    )

    if not ref_patterns.search(response):
        return 1.0  # no back-references → no accuracy claim to evaluate

    # Extract prior content for comparison
    prior_words: list[str] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str) and content:
            prior_words.extend(content.lower().split())

    if not prior_words:
        return 1.0

    # Use LCS to measure overlap between response and prior content
    resp_words = response.lower().split()
    if lcs_fn is not None:
        lcs_len = lcs_fn(resp_words, prior_words)
    else:
        from agents.hapax_daimonion.conversation_pipeline import _lcs_word_length

        lcs_len = _lcs_word_length(resp_words[:30], prior_words[:100])

    # Normalize: high LCS relative to response length = accurate references
    return min(1.0, lcs_len / max(1, len(resp_words) * 0.3))


def evaluate_turn(
    response: str,
    messages: list[dict],
    conversation_thread: list[str],
    user_utterance: str | None = None,
    langfuse_trace=None,
    directive_strategy: str | None = None,
) -> dict[str, float]:
    """Run all per-turn scores and push to Langfuse.

    Args:
        directive_strategy: Current grounding ledger strategy (e.g. "advance",
            "rephrase", "elaborate"). If provided, scores directive compliance.

    Returns dict of score_name → value for logging.
    """
    from agents._telemetry import hapax_score

    # Recent user turns from messages
    recent_user = [
        m["content"]
        for m in messages
        if m.get("role") == "user" and isinstance(m.get("content"), str)
    ][-5:]

    anchor = score_context_anchor(response, conversation_thread, recent_user)
    accuracy = score_reference_accuracy(response, messages)

    scores = {
        "context_anchor_success": round(anchor, 3),
        "reference_accuracy": round(accuracy, 3),
    }

    # Acceptance classification on the PREVIOUS user utterance (response to our last output)
    if user_utterance:
        label, acceptance_val = classify_acceptance(user_utterance)
        scores["acceptance_type"] = round(acceptance_val, 3)
        scores["acceptance_label"] = label  # type: ignore[assignment]

    # Turn-pair semantic coherence (embedding-based, replaces word overlap for Cycle 2)
    if user_utterance and response:
        coherence = score_turn_pair_coherence(user_utterance, response)
        if coherence is not None:
            scores["turn_pair_coherence"] = round(coherence, 3)

    # Behavioral covariates
    if user_utterance:
        scores["user_word_count"] = len(user_utterance.split())
    scores["assistant_word_count"] = len(response.split()) if response else 0

    # RLHF anti-pattern monitoring (Batch 4)
    if response:
        scores["response_monologic"] = round(_score_monologic(response), 3)

    # Directive compliance: did the model follow the grounding strategy?
    if response and directive_strategy:
        scores["directive_compliance"] = round(
            score_directive_compliance(response, directive_strategy), 3
        )

    # Push to Langfuse
    if langfuse_trace is not None:
        for name, val in scores.items():
            if isinstance(val, (int, float)):
                hapax_score(langfuse_trace, name, val)

    return scores


# ── Turn-Pair Semantic Coherence ─────────────────────────────────────────────


def score_turn_pair_coherence(user_text: str, assistant_text: str) -> float | None:
    """Compute embedding-based semantic coherence between user utterance and response.

    Uses nomic-embed (768-dim) cosine similarity. Captures semantic grounding
    that word overlap misses: paraphrasing, abstraction, synthesis all produce
    high coherence even with zero word overlap.

    Returns float 0.0-1.0, or None if embedding fails.
    """
    try:
        from agents._config import embed_safe

        user_vec = embed_safe(user_text, prefix="search_query")
        asst_vec = embed_safe(assistant_text, prefix="search_document")

        if user_vec is None or asst_vec is None:
            return None

        import numpy as np

        dot = np.dot(user_vec, asst_vec)
        norm_u = np.linalg.norm(user_vec)
        norm_a = np.linalg.norm(asst_vec)
        if norm_u == 0 or norm_a == 0:
            return 0.0
        sim = float(dot / (norm_u * norm_a))
        # Clamp to [0, 1] — negative cosine similarity means orthogonal/opposing
        return max(0.0, min(1.0, sim))
    except Exception:
        return None


# ── RLHF Anti-Pattern Monitoring ─────────────────────────────────────────────

# Dialogic markers: words/phrases that indicate collaborative, grounding-aware speech
_DIALOGIC_MARKERS = [
    "right?",
    "yeah?",
    "you know",
    "does that",
    "make sense",
    "what do you think",
    "want me to",
    "should I",
    "let me know",
    "earlier you",
    "you mentioned",
    "you said",
    "we discussed",
    "as you said",
    "going back to",
]


def _score_monologic(response: str) -> float:
    """Score whether a response is monologic (1.0) or dialogic (0.0).

    Heuristic: responses containing comprehension checks, back-references to
    operator's words, or collaborative offers score as dialogic. Purely
    declarative self-contained responses score as monologic.

    Used to detect the RLHF anti-pattern (Shaikh et al. 2024 NAACL):
    RLHF trains models toward monologic completeness rather than
    collaborative grounding.
    """
    lower = response.lower()
    dialogic_count = sum(1 for marker in _DIALOGIC_MARKERS if marker in lower)

    # Questions (ending with ?) are dialogic
    if response.rstrip().endswith("?"):
        dialogic_count += 1

    # More dialogic markers = lower monologic score
    if dialogic_count >= 2:
        return 0.0  # clearly dialogic
    if dialogic_count == 1:
        return 0.3  # somewhat dialogic
    return 1.0  # purely monologic


def score_directive_compliance(
    response: str,
    directive_strategy: str,
) -> float:
    """Score whether the response follows the grounding directive.

    Returns 1.0 if compliant, 0.0 if non-compliant.
    Heuristic matching — not perfect, but catches obvious violations.
    """
    lower = response.lower()

    if directive_strategy == "rephrase":
        # Should rephrase, not introduce new content
        # Heuristic: shorter responses that reference prior content are compliant
        return 1.0 if len(response.split()) <= 50 else 0.5

    if directive_strategy == "elaborate":
        # Should provide example or analogy
        example_markers = ["for example", "like", "such as", "imagine", "think of"]
        return 1.0 if any(m in lower for m in example_markers) else 0.3

    if directive_strategy == "present_reasoning":
        # Should explain why, not retract
        reasoning_markers = ["because", "reason", "the thing is", "actually", "my thinking"]
        retract_markers = ["you're right", "i was wrong", "i apologize", "sorry about"]
        if any(m in lower for m in retract_markers):
            return 0.0  # sycophantic retraction
        return 1.0 if any(m in lower for m in reasoning_markers) else 0.5

    if directive_strategy == "advance":
        return 1.0  # any response is compliant with "advance"

    if directive_strategy == "ungrounded_caution":
        # Should not reference the ungrounded content
        return 1.0  # hard to check mechanically, default compliant

    return 1.0  # neutral/unknown strategy


# ── Helpers ──────────────────────────────────────────────────────────────────


def _significant_words(text: str, min_len: int = 4) -> list[str]:
    """Extract significant words (length >= min_len, lowercased)."""
    return [w.lower() for w in text.split() if len(w) >= min_len and w.isalpha()]
