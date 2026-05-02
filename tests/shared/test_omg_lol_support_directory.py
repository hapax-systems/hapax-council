"""Tests for the omg.lol support-directory composer.

cc-task: omg-lol-support-directory-publisher.
"""

from __future__ import annotations

import pytest

from shared.governance.omg_referent import OperatorNameLeak, safe_render
from shared.omg_lol_support_directory import (
    RailId,
    SupportDirectory,
    SupportDirectoryEntry,
    SupportDirectoryError,
    render_directory_markdown,
)

_FAKE_LEGAL_NAME = "Test Person Placeholder"

_CANONICAL_URLS: dict[RailId, str] = {
    RailId.GITHUB_SPONSORS: "https://github.com/sponsors/hapax",
    RailId.LIBERAPAY: "https://liberapay.com/Hapax/",
    RailId.OPEN_COLLECTIVE: "https://opencollective.com/hapax",
    RailId.STRIPE_PAYMENT_LINK: "https://buy.stripe.com/test_abcd1234",
    RailId.KO_FI: "https://ko-fi.com/hapax",
    RailId.PATREON: "https://patreon.com/hapax",
    RailId.BUY_ME_A_COFFEE: "https://buymeacoffee.com/hapax",
}


def _entry(rail_id: RailId, **overrides: object) -> SupportDirectoryEntry:
    fields: dict[str, object] = {
        "rail_id": rail_id,
        "public_url": _CANONICAL_URLS[rail_id],
        "display_name": rail_id.value.replace("_", " ").title(),
        "note": "",
    }
    fields.update(overrides)
    return SupportDirectoryEntry(**fields)  # type: ignore[arg-type]


def _all_entries() -> tuple[SupportDirectoryEntry, ...]:
    return tuple(_entry(rail) for rail in RailId)


def test_entry_constructs_for_each_rail() -> None:
    for rail in RailId:
        e = _entry(rail)
        assert e.rail_id is rail
        assert e.public_url == _CANONICAL_URLS[rail]


def test_entry_is_frozen_and_forbids_extras() -> None:
    e = _entry(RailId.LIBERAPAY)
    with pytest.raises(Exception):
        e.display_name = "mutated"  # type: ignore[misc]
    with pytest.raises(Exception, match=r"forbid|extra"):
        SupportDirectoryEntry(
            rail_id=RailId.LIBERAPAY,
            public_url=_CANONICAL_URLS[RailId.LIBERAPAY],
            display_name="Liberapay",
            note="",
            payer_email="leak@example.com",  # type: ignore[call-arg]
        )


def test_entry_rejects_non_https_scheme() -> None:
    with pytest.raises(Exception, match=r"scheme must be https"):
        _entry(RailId.GITHUB_SPONSORS, public_url="http://github.com/sponsors/hapax")


def test_entry_rejects_query_string() -> None:
    with pytest.raises(Exception, match=r"no query string or fragment"):
        _entry(
            RailId.LIBERAPAY,
            public_url="https://liberapay.com/Hapax/?ref=marketing",
        )


def test_entry_rejects_fragment() -> None:
    with pytest.raises(Exception, match=r"no query string or fragment"):
        _entry(RailId.KO_FI, public_url="https://ko-fi.com/hapax#tip")


def test_entry_rejects_disallowed_netloc() -> None:
    with pytest.raises(Exception, match=r"netloc.*not in allowlist"):
        _entry(
            RailId.GITHUB_SPONSORS,
            public_url="https://example.com/sponsors/hapax",
        )


def test_entry_rejects_naked_domain() -> None:
    with pytest.raises(Exception, match=r"per-handle path"):
        _entry(RailId.LIBERAPAY, public_url="https://liberapay.com")


def test_entry_rejects_root_path_only() -> None:
    with pytest.raises(Exception, match=r"per-handle path"):
        _entry(RailId.LIBERAPAY, public_url="https://liberapay.com/")


def test_entry_accepts_alternate_netloc_in_allowlist() -> None:
    e = _entry(RailId.PATREON, public_url="https://www.patreon.com/hapax")
    assert e.public_url == "https://www.patreon.com/hapax"


def test_directory_constructs_with_seven_rails() -> None:
    d = SupportDirectory(title="Support Hapax", entries=_all_entries())
    assert len(d.entries) == len(RailId)


def test_directory_rejects_empty_entries() -> None:
    with pytest.raises(Exception, match=r"non-empty"):
        SupportDirectory(title="Support Hapax", entries=())


def test_directory_rejects_duplicate_rail_id() -> None:
    e1 = _entry(RailId.LIBERAPAY)
    e2 = _entry(RailId.LIBERAPAY, display_name="Liberapay-2")
    with pytest.raises(Exception, match=r"duplicate rail_id"):
        SupportDirectory(title="Support Hapax", entries=(e1, e2))


def test_directory_is_frozen() -> None:
    d = SupportDirectory(title="Support Hapax", entries=_all_entries())
    with pytest.raises(Exception):
        d.title = "Mutated"  # type: ignore[misc]


def test_render_is_deterministic() -> None:
    """Same inputs render to byte-identical output, regardless of input order."""
    forward = SupportDirectory(title="Support Hapax", entries=_all_entries())
    reversed_entries = tuple(reversed(_all_entries()))
    reverse = SupportDirectory(title="Support Hapax", entries=reversed_entries)
    assert render_directory_markdown(forward) == render_directory_markdown(reverse)


def test_render_sorts_entries_lex_by_rail_id() -> None:
    d = SupportDirectory(title="Support Hapax", entries=_all_entries())
    body = render_directory_markdown(d)
    expected_order = sorted(rail.value for rail in RailId)
    rendered_order = [line for line in body.splitlines() if line.startswith("- **")]
    for i, rail_value in enumerate(expected_order):
        display = rail_value.replace("_", " ").title()
        assert rendered_order[i].startswith(f"- **{display}**")


def test_render_includes_title_and_preamble() -> None:
    d = SupportDirectory(
        title="Support Hapax",
        preamble="Pick any rail; receive-only and aggregate.",
        entries=(_entry(RailId.LIBERAPAY),),
    )
    body = render_directory_markdown(d)
    assert body.startswith("# Support Hapax\n")
    assert "Pick any rail" in body


def test_render_includes_note_when_present() -> None:
    e = _entry(RailId.LIBERAPAY, note="0% platform fee")
    body = render_directory_markdown(SupportDirectory(title="t", entries=(e,)))
    assert "0% platform fee" in body


def test_render_omits_empty_preamble_separator() -> None:
    d = SupportDirectory(title="t", entries=(_entry(RailId.LIBERAPAY),))
    body = render_directory_markdown(d)
    assert "\n\n\n" not in body


def test_render_passes_legal_name_guard_with_a_seeded_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Smoke pin: the rendered body must contain no operator legal name.

    Seeds the env-var legal-name pattern with a non-operator
    placeholder string and runs the canonical safe_render leak-scan
    over the rendered body. The composer carries no operator-name
    token, so the scan must pass.
    """
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", _FAKE_LEGAL_NAME)
    d = SupportDirectory(title="Support Hapax", entries=_all_entries())
    body = render_directory_markdown(d)
    assert safe_render(body, segment_id=None) == body


def test_render_blocks_legal_name_in_preamble(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If an operator-name pattern leaked into the preamble, the guard fires."""
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", _FAKE_LEGAL_NAME)
    d = SupportDirectory(
        title="Support",
        preamble=f"By {_FAKE_LEGAL_NAME}.",
        entries=(_entry(RailId.LIBERAPAY),),
    )
    body = render_directory_markdown(d)
    with pytest.raises(OperatorNameLeak):
        safe_render(body, segment_id=None)


def test_rail_domain_allowlist_is_complete() -> None:
    """Every RailId has a domain allowlist entry — no module-level missing key."""
    from shared.omg_lol_support_directory import _RAIL_DOMAIN_ALLOWLIST

    for rail in RailId:
        assert rail in _RAIL_DOMAIN_ALLOWLIST
        assert _RAIL_DOMAIN_ALLOWLIST[rail], f"empty allowlist for {rail.value}"


def test_module_carries_no_outbound_calls() -> None:
    """Composer is pure; source must not import network / file clients."""
    import inspect

    import shared.omg_lol_support_directory as mod

    src = inspect.getsource(mod)
    forbidden = ("requests.", "httpx.", "urllib.request", "aiohttp", "open(")
    for token in forbidden:
        assert token not in src, f"unexpected I/O reference: {token!r}"


def test_support_directory_error_is_value_error() -> None:
    """SupportDirectoryError must subclass ValueError so existing handlers catch it."""
    assert issubclass(SupportDirectoryError, ValueError)
