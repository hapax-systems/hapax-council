"""Tests for the GEAL grounding-source classifier (spec §6.3)."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "source_id,expected",
    [
        # Operator-perception class → top apex.
        ("insightface.enrolled.jason", "top"),
        ("insightface:operator", "top"),
        ("pi-noir.desk.hand", "top"),
        ("pi-noir.overhead.drums", "top"),
        ("room-change.wake", "top"),
        ("operator.gaze.shift", "top"),
        # RAG / memory / vault-note class → bottom-left apex.
        ("rag.document.paper-42", "bl"),
        ("vault.note.reading", "bl"),
        ("memory.episodic.2026-04-22", "bl"),
        ("qdrant.profile-facts.5", "bl"),
        # Chat / world / music-match / SoundCloud class → bottom-right apex.
        ("chat.keyword.drums", "br"),
        ("chat.viewer.applause", "br"),
        ("world.event.storm", "br"),
        ("music.match.lofi-42", "br"),
        ("soundcloud.track.featured", "br"),
        # Imagination-converge → all three.
        ("imagination.converge.42", "all"),
        ("imagination.cross-source.corroborated", "all"),
    ],
)
def test_classify_source_canonical_prefixes(source_id: str, expected: str) -> None:
    from shared.geal_grounding_classifier import classify_source

    assert classify_source(source_id) == expected


def test_unknown_defaults_to_bl_memory_bucket() -> None:
    """Spec §6.3 table: a source without a recognised prefix falls into
    the RAG / memory bucket (bottom-left) — treat it as something
    Hapax recalled rather than perceived.
    """
    from shared.geal_grounding_classifier import classify_source

    assert classify_source("wholly_unknown.foo.bar") == "bl"
    assert classify_source("") == "bl"


def test_case_insensitive_dispatch() -> None:
    from shared.geal_grounding_classifier import classify_source

    assert classify_source("INSIGHTFACE.enrolled.jason") == "top"
    assert classify_source("Rag.document.paper") == "bl"
    assert classify_source("Chat.keyword.x") == "br"
