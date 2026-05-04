"""Author-anonymization invariants for the live-chat reader."""

from __future__ import annotations

from agents.youtube_chat_reader.anonymize import AuthorAnonymizer


def test_token_is_stable_within_one_anonymizer() -> None:
    anon = AuthorAnonymizer()
    a = anon.token("UCabcdef")
    b = anon.token("UCabcdef")
    assert a == b
    assert len(a) == 12


def test_token_differs_for_distinct_authors() -> None:
    anon = AuthorAnonymizer()
    assert anon.token("UCabcdef") != anon.token("UCxyzqrs")


def test_keys_unlinked_across_anonymizers() -> None:
    a = AuthorAnonymizer()
    b = AuthorAnonymizer()
    # Same author id, different process-key — token must change so
    # cross-session correlation is impossible without consent.
    assert a.token("UCabcdef") != b.token("UCabcdef")


def test_empty_author_collapses_to_anon() -> None:
    anon = AuthorAnonymizer()
    assert anon.token(None) == "anon"
    assert anon.token("") == "anon"


def test_token_is_hex_only() -> None:
    anon = AuthorAnonymizer()
    token = anon.token("UCabcdef")
    assert all(ch in "0123456789abcdef" for ch in token)


def test_no_plaintext_id_in_token() -> None:
    """The author_id must not appear as a substring of the token.

    Cheap structural check that we are hashing rather than truncating.
    """
    anon = AuthorAnonymizer()
    raw = "UCabcdef"
    token = anon.token(raw)
    assert raw not in token
    assert raw.lower() not in token
