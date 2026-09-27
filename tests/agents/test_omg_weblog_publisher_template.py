"""Pins the tracked omg.lol weblog template and its reciprocal identity link.

Companion assets (same PR):

* ``agents/omg_weblog_publisher/static/weblog-template.html`` — the tracked export.
* ``agents/omg_weblog_publisher/static/weblog-template.provenance.json`` — its
  provenance record, including the digests these tests cross-check.

What is pinned, and what is NOT:

* **Pinned:** the *weblog -> profile* direction. Every ``rel=me`` tag in the tracked
  template resolves to the profile, the tracked bytes equal the recorded export (size and
  sha256, cross-checked against the provenance record), and the extractor that decides
  what counts as a ``rel=me`` tag is pinned against quote-style, case and attribute-order
  variants so the target check cannot fail open.
* **Not pinned here:** the *profile -> weblog* direction. That link is produced by
  ``agents/omg_web_builder/static/index.html`` and is outside this PR. "Reciprocal" is a
  property of the pair, not of this file.

Why the negative tests exist: an extractor that silently misses a tag cannot protect the
"exactly the profile" assertion — a foreign ``rel=me`` written in single quotes, unquoted,
or with a differently-cased token would be invisible to it. HTML ``rel`` tokens are ASCII
case-insensitive.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re

import pytest

PROFILE = "https://hapax.omg.lol/"
ASSET_BYTES = 6766
ASSET_SHA256 = (
    "73c1f4b8476cf57edb8901f90da80e874fecb460b17b2a992a196d405ac988bf"  # pragma: allowlist secret
)

STATIC_DIR = (
    pathlib.Path(__file__).resolve().parents[2] / "agents" / "omg_weblog_publisher" / "static"
)
TEMPLATE_PATH = STATIC_DIR / "weblog-template.html"
PROVENANCE_PATH = STATIC_DIR / "weblog-template.provenance.json"

_TAG_RE = re.compile(r"<(a|link)\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>", re.IGNORECASE)
_ATTR_RE = re.compile(
    r"""([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'`=<>]+))"""
)


def _template() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def _tag_attrs(tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in _ATTR_RE.finditer(tag):
        value = match.group(2)
        if value is None:
            value = match.group(3)
        if value is None:
            value = match.group(4)
        attrs[match.group(1).lower()] = value or ""
    return attrs


def _relme_tags(fragment: str) -> list[tuple[str, str]]:
    """(tag name, href) for every tag whose rel token list contains ``me``.

    Quote-style agnostic; the token comparison is ASCII-case-insensitive, as HTML defines
    ``rel`` tokens to be.
    """
    found: list[tuple[str, str]] = []
    for match in _TAG_RE.finditer(fragment):
        attrs = _tag_attrs(match.group(0))
        rel_tokens = {token.lower() for token in attrs.get("rel", "").split()}
        if "me" in rel_tokens and "href" in attrs:
            found.append((match.group(1).lower(), attrs["href"]))
    return found


def _split_head(template: str) -> tuple[str, str]:
    """(head, rest) split on the first ``</head>``, ASCII-case-insensitive, index-safe."""
    match = re.search(r"</head\s*>", template, re.IGNORECASE)
    assert match, "weblog template has no </head>"
    return template[: match.start()], template[match.end() :]


def test_tracked_asset_matches_the_recorded_export() -> None:
    raw = TEMPLATE_PATH.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert len(raw) == ASSET_BYTES
    assert digest == ASSET_SHA256
    record = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    assert record["asset_bytes"] == len(raw)
    assert record["asset_sha256"] == digest


def test_head_declares_machine_readable_reciprocal_identity() -> None:
    head, _ = _split_head(_template())
    assert [t for t in _relme_tags(head) if t[0] == "link"] == [("link", PROFILE)]


def test_profile_anchor_carries_visible_reciprocal_identity() -> None:
    _, body = _split_head(_template())
    assert [t for t in _relme_tags(body) if t[0] == "a"] == [("a", PROFILE)]


def test_reciprocal_identity_targets_are_exactly_the_profile() -> None:
    assert [href for _, href in _relme_tags(_template())] == [PROFILE, PROFILE]


@pytest.mark.parametrize(
    "evil_tag",
    [
        "<a rel='me' href='https://evil.example/'>",
        "<a rel=me href=https://evil.example/>",
        '<a rel="Me" href="https://evil.example/">',
        "<a rel='ME' href=https://evil.example/Me>",
        '<a rel="me external" href="https://evil.example/">',
    ],
)
def test_extractor_sees_a_foreign_relme_however_it_is_written(evil_tag: str) -> None:
    """If the extractor cannot see these, the 'exactly the profile' pin fails open."""
    assert _relme_tags(evil_tag) == [
        ("a", "https://evil.example/" + ("Me" if "Me>" in evil_tag else ""))
    ]


def test_extractor_survives_an_angle_bracket_inside_an_attribute_value() -> None:
    tag = '<a title="a > b" rel="me" href="https://evil.example/">'
    assert _relme_tags(tag) == [("a", "https://evil.example/")]


def test_extractor_ignores_tags_without_a_me_token() -> None:
    assert _relme_tags('<a rel="noopener noreferrer" href="https://evil.example/">') == []
    assert _relme_tags('<link rel="alternate" type="application/rss+xml" href="/rss.xml">') == []
