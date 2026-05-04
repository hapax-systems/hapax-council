"""Chat affordances must be registered in shared/affordance_registry.py."""

from __future__ import annotations

from shared.affordance_registry import AFFORDANCE_DOMAINS, ALL_AFFORDANCES


def test_chat_domain_registered() -> None:
    assert "chat" in AFFORDANCE_DOMAINS


def test_required_chat_affordances_present() -> None:
    """Per cc-task youtube-chat-ingestion-impingement §3."""
    names = {r.name for r in ALL_AFFORDANCES}
    assert "chat.acknowledge_message" in names
    assert "chat.answer_question" in names
    assert "chat.tier_suggestion_add" in names
    assert "chat.mood_shift" in names
    # Operator-relevant additions:
    assert "chat.hero_swap" in names


def test_chat_affordances_have_descriptions_long_enough_for_embedding() -> None:
    """Descriptions must carry enough Gibson-verb signal for cosine match.

    The AffordancePipeline embeds the description verbatim — a 5-word
    blurb yields generic vectors that match nothing.
    """
    for record in AFFORDANCE_DOMAINS["chat"]:
        word_count = len(record.description.split())
        assert word_count >= 12, f"{record.name} description is too short: {word_count} words"
