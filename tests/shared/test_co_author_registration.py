"""Explicit participant registration must preserve the existing default byline."""

from shared import co_author_model as authors


def test_codex_is_registered_without_invented_metadata():
    participant = authors.get("codex")
    assert participant is authors.CODEX
    assert authors.get("CODEX") is participant
    assert participant.name == "Codex"
    assert participant.role == "substrate"
    assert participant.cff_type == "entity"
    assert participant.to_cff_dict() == {"name": "Codex", "alias": "codex"}


def test_codex_can_be_named_explicitly():
    assert authors.compose_byline(["codex"]) == "Codex"
    assert authors.to_cff_authors_block(["codex"]) == [{"name": "Codex", "alias": "codex"}]


def test_registration_preserves_default_participants_and_byline():
    expected = (authors.HAPAX, authors.CLAUDE_CODE, authors.get("operator"))
    assert expected == authors.ALL_CO_AUTHORS
    assert authors.CODEX not in authors.ALL_CO_AUTHORS
    assert authors.compose_byline() == ", ".join(author.name for author in expected)
    assert authors.to_cff_authors_block() == [author.to_cff_dict() for author in expected]
