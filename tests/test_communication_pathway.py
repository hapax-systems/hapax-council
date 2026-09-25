"""Tests for shared.communication_pathway — canonical content digests and mechanical message checks.

Each test pins one unsafe case from the communication-pathway design (v3.1 §1.2, §3, §5): an equivalent message
must digest the same, a changed one must not, and each mechanical check must flag the defect class it exists for.
"""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime
from email.message import EmailMessage

import pytest

from shared import communication_pathway as cp


def _mail(
    body: str,
    *,
    subject: str = "DOC-1 comment from Example Lab",
    attach: bytes | None = None,
    charset: str = "utf-8",
    filename: str = "comment.txt",
    date: str = "Fri, 25 Sep 2026 00:00:00 +0000",
    msgid: str = "<a@example.org>",
) -> EmailMessage:
    m = EmailMessage()
    m["From"] = "Example Lab <lab@example.org>"
    m["To"] = "comments@example.gov"
    m["Subject"] = subject
    m["Date"] = date
    m["Message-ID"] = msgid
    m.set_content(body, charset=charset)
    if attach is not None:
        m.add_attachment(
            attach, maintype="text", subtype="plain", filename=filename, params={"charset": charset}
        )
    return m


def _digest(m: EmailMessage) -> str:
    return cp.canonical_digest(cp.email_manifest(m))


# U10: equivalent messages digest the same ----------------------------------------------------------


def test_u10_boundary_date_messageid_do_not_change_digest():
    a = _mail("hello\n", attach=b"x\n", date="Fri, 25 Sep 2026 00:47:17 +0000", msgid="<a@h>")
    b = _mail("hello\n", attach=b"x\n", date="Sat, 26 Sep 2026 01:00:00 +0000", msgid="<b@h>")
    assert a.as_bytes() != b.as_bytes()
    assert _digest(a) == _digest(b)


def test_u10_charset_case_and_alias():
    assert cp.normalize_charset("UTF-8") == cp.normalize_charset("utf8") == "utf-8"
    assert cp.normalize_charset("Latin1") == cp.normalize_charset("ISO8859-1") == "iso-8859-1"
    assert cp.normalize_charset("ASCII") == "us-ascii"


def test_u10_nfc_and_nfd_equal():
    nfc = unicodedata.normalize("NFC", "café\n")
    nfd = unicodedata.normalize("NFD", "café\n")
    assert nfc != nfd
    assert _digest(_mail(nfc)) == _digest(_mail(nfd))


def test_u10_crlf_and_lf_bodies_equal():
    assert _digest(_mail("a\r\nb\r\n")) == _digest(_mail("a\nb\n"))


def test_u10_flowed_rewrap_equal():
    one = "This is one long paragraph that wraps. \nIt keeps going here.\n"
    two = "This is one long \nparagraph that wraps. It keeps \ngoing here.\n"
    assert cp.flowed_text(one, delsp=False) == cp.flowed_text(two, delsp=False)


def test_u10_flowed_delsp_removes_the_soft_break_space():
    assert cp.flowed_text("ab \ncd\n", delsp=True) == "abcd\n"
    assert cp.flowed_text("ab \ncd\n", delsp=False) == "ab cd\n"


def test_u10_crlf_line_ends_normalised_before_flowed_reconstruction():
    # get_content() already yields LF for email parts, so this pins the module's own line-end normalisation.
    assert cp.flowed_text("ab \r\ncd\r\n", delsp=False) == cp.flowed_text("ab \ncd\n", delsp=False)
    assert cp.flowed_text("ab \r\ncd\r\n", delsp=False) == "ab cd\n"


def test_u10_filename_forms_equal():
    a = _mail("b\n", attach=b"x\n", filename="café.txt")
    b = _mail("b\n", attach=b"x\n", filename=unicodedata.normalize("NFD", "café.txt"))
    assert _digest(a) == _digest(b)


def test_u10_subject_whitespace_equal():
    assert _digest(_mail("b\n", subject="DOC-1   comment")) == _digest(
        _mail("b\n", subject="DOC-1 comment")
    )


def test_u10_neg_one_decoded_byte_changes_digest():
    assert _digest(_mail("hello\n")) != _digest(_mail("hellp\n"))


def test_u10_neg_recipient_changes_digest():
    a = _mail("hello\n")
    b = _mail("hello\n")
    b.replace_header("To", "someone-else@example.gov")
    assert _digest(a) != _digest(b)


def test_manifest_keeps_only_reader_visible_headers():
    man = cp.email_manifest(_mail("b\n"))
    assert man["channel"] == "email"
    assert set(man["headers"]) <= {"from", "to", "cc", "reply_to", "subject"}


def test_canonical_digest_rejects_floats():
    with pytest.raises(ValueError):
        cp.canonical_digest({"x": 1.5})


# U6: a body that duplicates an attachment -----------------------------------------------------------


def test_u6_body_duplicating_attachment_is_flagged():
    body = "the comment text\n"
    assert cp.duplicated_parts(cp.email_manifest(_mail(body, attach=body.encode()))) == [(0, 1)]


def test_u6_distinct_parts_not_flagged():
    assert (
        cp.duplicated_parts(cp.email_manifest(_mail("cover note\n", attach=b"the comment\n"))) == []
    )


# U7: line ends on the transport stream --------------------------------------------------------------


def test_u7_bare_lf_and_bare_cr_detected():
    assert cp.bare_line_ends(b"a\nb\r\n") == ["bare LF at byte 1"]
    assert cp.bare_line_ends(b"a\r\nb\r\n") == []
    assert cp.bare_line_ends(b"a\rb\r\n") == ["bare CR at byte 1"]


def test_u7_to_crlf_normalises_lf_only_and_is_idempotent():
    assert cp.to_crlf(b"a\nb\n") == b"a\r\nb\r\n"
    assert cp.to_crlf(b"a\r\nb\r\n") == b"a\r\nb\r\n"


# U8: a URL immediately followed by punctuation ------------------------------------------------------


def test_u8_url_with_trailing_colon_is_flagged():
    text = "the draft at https://doi.org/10.1234/example.draft: printed page numbers"
    assert cp.url_punctuation_flags(text) == ["https://doi.org/10.1234/example.draft:"]


def test_u8_url_followed_by_space_or_sentence_end_space_not_flagged():
    assert cp.url_punctuation_flags("see https://example.org/x for more") == []


# U9: Markdown constructs inside text/plain ----------------------------------------------------------


def test_u9_markdown_flags_the_three_found_constructs():
    text = "# Notes\n\n**bold** text\n| a | b |\n|---|---|\nplain line\n"
    assert {f[0] for f in cp.markdown_flags(text)} == {"atx_heading", "bold", "pipe_table"}


def test_u9_plain_numbered_and_bulleted_text_not_flagged():
    assert cp.markdown_flags("1. First point\n- a bullet is fine\n") == []


# P5(a): decoded line length -------------------------------------------------------------------------


def test_p5a_lines_over_78_are_reported_by_number():
    assert cp.long_lines("x" * 79 + "\n" + "y" * 78 + "\n") == [1]


# P5(f): subject -------------------------------------------------------------------------------------


def test_p5f_subject_patterns_and_controls():
    assert cp.subject_problems("DOC-1 comment", ["DOC-1"]) == []
    assert cp.subject_problems("comment", ["DOC-1"]) == ["missing mandatory pattern: DOC-1"]
    assert cp.subject_problems("DOC-1\r\nBcc: x", ["DOC-1"]) == ["control character in subject"]


# U4 and U18: validity window and replay against the component's own act log -------------------------


def test_u4_record_outside_its_window_is_refused():
    nb = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
    na = datetime(2026, 9, 25, 1, 0, tzinfo=UTC)
    assert cp.within_window(datetime(2026, 9, 25, 0, 30, tzinfo=UTC), nb, na) is True
    assert cp.within_window(datetime(2026, 9, 25, 1, 0, 1, tzinfo=UTC), nb, na) is False
    assert cp.within_window(datetime(2026, 9, 24, 23, 59, tzinfo=UTC), nb, na) is False


def test_u18_repeated_digest_and_nonce_in_act_log_is_refused():
    log = [{"canonical_digest": "d1", "nonce": "n1"}]
    assert cp.act_seen("d1", "n1", log) is True
    assert cp.act_seen("d1", "n2", log) is False
    assert cp.act_seen("d2", "n1", log) is False


# U19: norm-table completeness -----------------------------------------------------------------------


def test_u19_norm_table_missing_a_channel_statement_is_reported():
    statements = ["release", "foia", "no-proprietary", "ai-analysis", "no-training"]
    table = {
        "release": "import",
        "foia": "import",
        "ai-analysis": "import",
        "no-training": "import",
    }
    assert cp.norm_table_missing(statements, table) == ["no-proprietary"]
    table["no-proprietary"] = "import"
    assert cp.norm_table_missing(statements, table) == []
