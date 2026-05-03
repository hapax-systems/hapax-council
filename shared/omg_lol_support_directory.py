"""omg.lol support-directory composer — typed weblog body for the receive-only rails.

The seven receive-only payment rails shipped this week
(GitHub Sponsors, Liberapay, Open Collective, Stripe Payment Link,
Ko-fi, Patreon, BuyMeACoffee) all live in ``shared/*_receive_only_rail.py``
and validate inbound webhooks. None of them declares a public-facing
surface that an audience can reach to *initiate* a contribution.

This module composes a single typed support directory — an aggregate
listing of the seven rails' canonical public receive URLs, rendered
to deterministic markdown that is suitable for posting via
:class:`agents.publication_bus.omg_weblog_publisher.OmgLolWeblogPublisher`.

Constitutional invariants enforced at construction (each fails closed
via :class:`SupportDirectoryError` raised inside a Pydantic
``model_validator`` — Pydantic wraps custom ``ValueError`` subclasses
inside :class:`pydantic.ValidationError`, so callers should
``pytest.raises(Exception, match=...)``):

1. Each entry's ``public_url`` is HTTPS-only, carries no query string
   or fragment, and resolves to a netloc explicitly registered for
   that ``RailId`` in :data:`_RAIL_DOMAIN_ALLOWLIST`. Naked-domain
   links (path empty or ``"/"``) are rejected — every rail has a
   per-handle path.
2. The directory carries no duplicate ``rail_id``; one entry per
   rail per directory.
3. The directory is non-empty.

The composer is **pure** — no outbound calls, no filesystem writes,
no network. Actual publication is the caller's responsibility (the
existing :class:`OmgLolWeblogPublisher` enforces the AllowlistGate,
legal-name-leak guard, and canonical Counter at ``_emit()`` time).

The module ships a deterministic renderer
(:func:`render_directory_markdown`) that lex-sorts entries by
``rail_id`` so two builds with identical inputs produce byte-identical
output — which is what makes the rendered body safe to commit to
git, hash for change-detection, or diff for review.

cc-task: ``omg-lol-support-directory-publisher``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SupportDirectoryError(ValueError):
    """Fail-closed error raised on any rejected directory shape.

    Subclasses :class:`ValueError` so existing
    ``except ValueError`` handlers inherit the fail-closed default
    without code changes. Pydantic wraps this inside
    :class:`pydantic.ValidationError` when raised from a
    ``model_validator``; portable test form is
    ``pytest.raises(Exception, match=...)``.
    """


class RailId(StrEnum):
    """The seven receive-only rails currently shipped on origin/main.

    Order is the StrEnum declaration order; the canonical render
    sort key is the ``.value`` (lex). Adding a new rail requires:

    1. Land the receive-only rail module under ``shared/``.
    2. Add the ``RailId`` member here.
    3. Add the per-rail netloc set to :data:`_RAIL_DOMAIN_ALLOWLIST`.

    All three are compile-time-visible — there is no runtime
    "register a rail" path.
    """

    GITHUB_SPONSORS = "github_sponsors"
    LIBERAPAY = "liberapay"
    OPEN_COLLECTIVE = "open_collective"
    STRIPE_PAYMENT_LINK = "stripe_payment_link"
    KO_FI = "ko_fi"
    PATREON = "patreon"
    BUY_ME_A_COFFEE = "buy_me_a_coffee"


_RAIL_DOMAIN_ALLOWLIST: dict[RailId, frozenset[str]] = {
    RailId.GITHUB_SPONSORS: frozenset({"github.com"}),
    RailId.LIBERAPAY: frozenset({"liberapay.com"}),
    RailId.OPEN_COLLECTIVE: frozenset({"opencollective.com"}),
    RailId.STRIPE_PAYMENT_LINK: frozenset({"buy.stripe.com"}),
    RailId.KO_FI: frozenset({"ko-fi.com"}),
    RailId.PATREON: frozenset({"patreon.com", "www.patreon.com"}),
    RailId.BUY_ME_A_COFFEE: frozenset({"buymeacoffee.com", "www.buymeacoffee.com"}),
}


class _DirectoryModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SupportDirectoryEntry(_DirectoryModel):
    """One rail entry in the support directory.

    Aggregate-only — carries the rail id, the canonical public URL,
    a short display name, and an optional note. No payer state, no
    per-supporter recognition, no tier amounts.
    """

    rail_id: RailId
    public_url: str = Field(min_length=10, max_length=256)
    display_name: str = Field(min_length=1, max_length=64)
    note: str = Field(default="", max_length=140)

    @model_validator(mode="after")
    def _validate_entry(self) -> Self:
        parsed = urlparse(self.public_url)
        if parsed.scheme != "https":
            raise SupportDirectoryError(f"public_url scheme must be https, got {parsed.scheme!r}")
        if parsed.query or parsed.fragment:
            raise SupportDirectoryError("public_url must carry no query string or fragment")
        if not parsed.netloc:
            raise SupportDirectoryError("public_url must carry a netloc")
        allowed = _RAIL_DOMAIN_ALLOWLIST[self.rail_id]
        if parsed.netloc not in allowed:
            raise SupportDirectoryError(
                f"public_url netloc {parsed.netloc!r} not in allowlist "
                f"for rail {self.rail_id.value!r}"
            )
        if not parsed.path or parsed.path == "/":
            raise SupportDirectoryError(
                "public_url must carry a per-handle path (naked domain rejected)"
            )
        return self


class SupportDirectory(_DirectoryModel):
    """Typed support directory — non-empty, no duplicate rail_id.

    The directory is an aggregate-only view; the rendered markdown
    body produced by :func:`render_directory_markdown` is the
    artifact that gets passed to a publication-bus publisher.
    """

    title: str = Field(min_length=1, max_length=64)
    preamble: str = Field(default="", max_length=512)
    entries: tuple[SupportDirectoryEntry, ...]

    @model_validator(mode="after")
    def _validate_directory(self) -> Self:
        if not self.entries:
            raise SupportDirectoryError("entries must be non-empty")
        seen: set[RailId] = set()
        for entry in self.entries:
            if entry.rail_id in seen:
                raise SupportDirectoryError(f"duplicate rail_id {entry.rail_id.value!r}")
            seen.add(entry.rail_id)
        return self


def render_directory_markdown(directory: SupportDirectory) -> str:
    """Render ``directory`` to deterministic markdown.

    Entries are lex-sorted by ``rail_id.value`` so two builds with
    identical inputs produce byte-identical output. Caller is
    responsible for routing the result through a publication-bus
    publisher; this function performs no I/O and no leak-scan
    (the publisher's :func:`assert_no_leak` runs at ``_emit()``
    time).
    """
    sorted_entries = sorted(directory.entries, key=lambda e: e.rail_id.value)
    lines: list[str] = [f"# {directory.title}", ""]
    if directory.preamble:
        lines.extend([directory.preamble.rstrip(), ""])
    for entry in sorted_entries:
        line = f"- **{entry.display_name}** — <{entry.public_url}>"
        if entry.note:
            line += f" — {entry.note.rstrip()}"
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "RailId",
    "SupportDirectory",
    "SupportDirectoryEntry",
    "SupportDirectoryError",
    "render_directory_markdown",
]
