"""Static HTML renderer for the citable-nexus front-door site.

Each ``render_<page>_page`` function returns a fully-formed HTML
string with V5 attribution boilerplate + non-engagement clause in
the footer. The renderer is deliberately framework-free — no Astro,
no Eleventy, no Hugo dependency. Pure stdlib + filesystem reads from
``agents.publication_bus.surface_registry`` and
``shared.attribution_block``. The output is portable across any
static host (GitHub Pages, omg.lol weblog, Netlify, plain object
storage).

Phase 0 invariants the renderer enforces:

  - No operator legal name in any rendered page body. The V5 byline
    constants come from ``shared.attribution_block`` which has its
    own legal-name guard; all other body text is hand-authored here
    and must remain operator-referent-only ("Oudepode", "the
    operator", "OTO").
  - No "Subscribe" / "Contact" / "Get a Demo" CTAs. Verified by
    :class:`tests.agents.citable_nexus.test_renderer.TestNoCtaCopy`.
  - Non-engagement clause appears on every page footer (long form
    for ``/`` and ``/refuse``; short form elsewhere).
  - Open Graph + Bluesky meta tags on every page.
  - Self-contained HTML — no external CSS / JS dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from agents.citable_nexus.datacite_snapshot import (
    DataCiteSnapshot,
    Work,
    read_latest_snapshot,
)
from agents.citable_nexus.vault_content import (
    markdown_to_html,
    read_vault_document,
)
from agents.publication_bus.surface_registry import (
    SURFACE_REGISTRY,
    AutomationStatus,
    auto_surfaces,
    refused_surfaces,
)
from shared.attribution_block import (
    NON_ENGAGEMENT_CLAUSE_LONG,
    NON_ENGAGEMENT_CLAUSE_SHORT,
)

# ── Page registry ────────────────────────────────────────────────────


@dataclass(frozen=True)
class PageMeta:
    """Metadata for one rendered static page."""

    path: str
    title: str
    description: str
    body_html: str


PAGE_PATHS: Final[tuple[str, ...]] = (
    "/",
    "/cite",
    "/refuse",
    "/surfaces",
    "/manifesto",
    "/refusal-brief",
    "/deposits",
)
"""Phase 0 + Phase 1b + Phase 1c page set. Phase 2 adds
/citation-graph (Cytoscape.js)."""

CANONICAL_BASE_URL: Final[str] = "https://hapax.research"
"""Canonical base URL the rendered site assumes when emitting
``<link rel="canonical">``. Operator can override via the build CLI
when the actual deployment URL differs (e.g., omg.lol weblog
fallback)."""

V5_BYLINE: Final[str] = "Hapax / Oudepode / OTO"
"""V5 byline per the operator-referent policy. Uses the operator-
referent picker's canonical names; no legal name. The Refusal Brief's
authorship-indeterminacy stance binds this byline to the artifact set,
not to a single person."""

POLYSEMIC_DECODER_CHANNEL_7: Final[str] = (
    "Polysemic decoder channel 7: an aesthetic register, not a marketing surface."
)
"""Per Manifesto v0 §II + V5 attribution policy. The site adopts
this register because the Refusal Brief explicitly identifies the
absence of marketing copy as its load-bearing aesthetic claim."""


# ── HTML helpers ──────────────────────────────────────────────────────


def _esc(text: str) -> str:
    """Minimal HTML escaper (stdlib's html.escape would do but
    pulling it for a 4-char substitution is overkill)."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _meta_tags(title: str, description: str, page_path: str) -> str:
    """Open Graph + Bluesky + Twitter Card meta tags.

    Bluesky uses Open Graph; the explicit ``og:`` block covers all
    three platforms with one declaration."""
    canonical_url = f"{CANONICAL_BASE_URL}{page_path}"
    return f"""    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{_esc(title)}</title>
    <meta name="description" content="{_esc(description)}">
    <meta name="author" content="{_esc(V5_BYLINE)}">
    <link rel="canonical" href="{_esc(canonical_url)}">
    <meta property="og:title" content="{_esc(title)}">
    <meta property="og:description" content="{_esc(description)}">
    <meta property="og:url" content="{_esc(canonical_url)}">
    <meta property="og:type" content="website">
    <meta name="twitter:card" content="summary">
    <meta name="twitter:title" content="{_esc(title)}">
    <meta name="twitter:description" content="{_esc(description)}">"""


def _footer(long_form: bool = False) -> str:
    """V5 attribution + non-engagement clause footer."""
    clause = NON_ENGAGEMENT_CLAUSE_LONG if long_form else NON_ENGAGEMENT_CLAUSE_SHORT
    return f"""    <footer>
        <p class="byline">{_esc(V5_BYLINE)}</p>
        <p class="clause">{_esc(clause)}</p>
        <p class="register">{_esc(POLYSEMIC_DECODER_CHANNEL_7)}</p>
    </footer>"""


def _wrap(meta: PageMeta, *, footer_long_form: bool = False) -> str:
    """Wrap one PageMeta into a full HTML document."""
    return f"""<!doctype html>
<html lang="en">
<head>
{_meta_tags(meta.title, meta.description, meta.path)}
</head>
<body>
{meta.body_html}
{_footer(long_form=footer_long_form)}
</body>
</html>
"""


# ── Page renderers ────────────────────────────────────────────────────


def render_landing_page() -> PageMeta:
    """``/`` — landing with V5 byline + page index + non-engagement clause."""
    body = """    <header>
        <h1>Hapax research</h1>
        <p class="intent">A citable nexus for the operator's published artifacts.</p>
    </header>
    <main>
        <section class="page-index">
            <h2>Index</h2>
            <ul>
                <li><a href="/cite">/cite</a> — canonical citation block (BibTeX, RIS, plaintext)</li>
                <li><a href="/refuse">/refuse</a> — REFUSED surfaces catalog (the Tier-3 catalog)</li>
                <li><a href="/surfaces">/surfaces</a> — full publication-bus surface registry</li>
            </ul>
            <p class="phase-note">Phase 1+ pages — <code>/manifesto</code>, <code>/refusal-brief</code>, <code>/deposits</code>, <code>/citation-graph</code> — ship after the operator vault sync + DataCite snapshot ledger lands.</p>
        </section>
    </main>"""
    return PageMeta(
        path="/",
        title="Hapax research — citable nexus",
        description="A citable nexus for the operator's published artifacts. Manifesto, Refusal Brief, surface registry, citation graph.",
        body_html=body,
    )


def render_cite_page() -> PageMeta:
    """``/cite`` — canonical citation block in BibTeX, RIS, plaintext."""
    bibtex = (
        "@misc{hapax_research_2026,\n"
        "  author       = {Hapax and Oudepode},\n"
        "  title        = {Hapax: a single-operator research instrument},\n"
        "  year         = {2026},\n"
        "  url          = {https://hapax.research},\n"
        "  note         = {Authorship-indeterminacy stance per V5 attribution policy}\n"
        "}"
    )
    ris = (
        "TY  - GEN\n"
        "AU  - Hapax\n"
        "AU  - Oudepode\n"
        "TI  - Hapax: a single-operator research instrument\n"
        "PY  - 2026\n"
        "UR  - https://hapax.research\n"
        "ER  - "
    )
    plaintext = (
        "Hapax & Oudepode (2026). Hapax: a single-operator research "
        "instrument. https://hapax.research"
    )
    body = f"""    <header>
        <h1>Cite</h1>
        <p class="intent">Canonical citation block. Pick the format your citation manager expects.</p>
    </header>
    <main>
        <section>
            <h2>BibTeX</h2>
            <pre><code>{_esc(bibtex)}</code></pre>
        </section>
        <section>
            <h2>RIS</h2>
            <pre><code>{_esc(ris)}</code></pre>
        </section>
        <section>
            <h2>Plaintext</h2>
            <p>{_esc(plaintext)}</p>
        </section>
        <section class="cff-note">
            <h2>CITATION.cff</h2>
            <p>The canonical CITATION.cff lives in the
                <a href="https://github.com/ryanklee/hapax-council">hapax-council</a> repo
                root and is the authoritative source for the GitHub citation widget.</p>
        </section>
    </main>"""
    return PageMeta(
        path="/cite",
        title="Cite — Hapax research",
        description="Canonical citation block (BibTeX, RIS, plaintext). The CITATION.cff in the source repo is the authoritative form.",
        body_html=body,
    )


def render_refuse_page() -> PageMeta:
    """``/refuse`` — REFUSED surfaces catalog (Tier-3)."""
    refused = refused_surfaces()
    refused_items = "\n".join(
        f"            <li><code>{_esc(name)}</code>{_refusal_link_suffix(name)}</li>"
        for name in refused
    )
    body = f"""    <header>
        <h1>Refused surfaces</h1>
        <p class="intent">Surfaces the publication-bus has explicitly chosen not to engage with. The Refusal Brief documents the reasoning per surface; this page is the live index.</p>
    </header>
    <main>
        <section class="refused-catalog">
            <h2>Tier-3 REFUSED catalog ({len(refused)} surfaces)</h2>
            <ul>
{refused_items}
            </ul>
        </section>
        <section class="refusal-brief-pointer">
            <h2>Why these specifically</h2>
            <p>Per-surface rationale lives in the Refusal Brief deposit (Zenodo concept-DOI: forthcoming). The brief enumerates the load-bearing constitutional, technical, and ethical reasons the publication-bus declines each surface. Refusal-as-data: the catalog is itself the artifact.</p>
        </section>
    </main>"""
    return PageMeta(
        path="/refuse",
        title="Refused surfaces — Hapax research",
        description="The REFUSED-surface catalog. Refusal-as-data: the catalog is itself the artifact.",
        body_html=body,
    )


def _refusal_link_suffix(surface_name: str) -> str:
    """Render the refusal_link if the surface has one in its registry entry."""
    spec = SURFACE_REGISTRY.get(surface_name)
    if spec is None or not spec.refusal_link:
        return ""
    return f' &mdash; <a href="{_esc(spec.refusal_link)}">refusal rationale</a>'


def render_surfaces_page() -> PageMeta:
    """``/surfaces`` — full publication-bus surface registry rendered."""
    auto = auto_surfaces()
    refused = refused_surfaces()
    conditional = sorted(
        name
        for name, spec in SURFACE_REGISTRY.items()
        if spec.automation_status == AutomationStatus.CONDITIONAL_ENGAGE
    )

    auto_items = "\n".join(_render_surface_row(name) for name in auto)
    conditional_items = "\n".join(_render_surface_row(name) for name in conditional)
    refused_items = "\n".join(_render_surface_row(name) for name in refused)

    body = f"""    <header>
        <h1>Surfaces</h1>
        <p class="intent">The publication-bus surface registry rendered as a public dashboard. Three tiers: automated dispatch, conditional engagement (one-time operator action), refused.</p>
    </header>
    <main>
        <section class="surfaces-tier">
            <h2>FULL_AUTO ({len(auto)})</h2>
            <p class="tier-intent">Daemon-side dispatch with no operator-active maintenance after credential bootstrap.</p>
            <ul>
{auto_items}
            </ul>
        </section>
        <section class="surfaces-tier">
            <h2>CONDITIONAL_ENGAGE ({len(conditional)})</h2>
            <p class="tier-intent">One-time operator action required (account creation, session-cookie extraction, etc.). Daemon dispatch fully automated post-bootstrap.</p>
            <ul>
{conditional_items}
            </ul>
        </section>
        <section class="surfaces-tier">
            <h2>REFUSED ({len(refused)})</h2>
            <p class="tier-intent">Surfaces the publication-bus has explicitly chosen not to engage with. See <a href="/refuse">/refuse</a> for the catalog with refusal links.</p>
            <ul>
{refused_items}
            </ul>
        </section>
    </main>"""
    return PageMeta(
        path="/surfaces",
        title="Surfaces — Hapax research",
        description=f"Publication-bus surface registry: {len(auto)} FULL_AUTO, {len(conditional)} CONDITIONAL_ENGAGE, {len(refused)} REFUSED.",
        body_html=body,
    )


def _render_surface_row(surface_name: str) -> str:
    spec = SURFACE_REGISTRY.get(surface_name)
    api = f" &mdash; <em>{_esc(spec.api)}</em>" if spec and spec.api else ""
    note = (
        f'<br><span class="scope-note">{_esc(spec.scope_note)}</span>'
        if spec and spec.scope_note
        else ""
    )
    return f"                <li><code>{_esc(surface_name)}</code>{api}{note}</li>"


# ── Phase 1b: vault-content pages ────────────────────────────────────


def _render_vault_page(
    *,
    slug: str,
    path: str,
    title: str,
    description: str,
    placeholder_intro: str,
) -> PageMeta:
    """Render one vault-sourced page with safe-fallback for missing files.

    The renderer build environment (CI, ad-hoc) may not have the
    operator vault mounted. When the source file is absent,
    ``vault_content.read_vault_document`` returns
    ``available=False`` and we emit a Phase-1 placeholder rather
    than failing the build.
    """
    doc = read_vault_document(slug)
    if doc.available:
        rendered = markdown_to_html(doc.markdown)
        body = f"""    <header>
        <h1>{_esc(title)}</h1>
        <p class="intent">Sourced from the operator vault at build time.</p>
    </header>
    <main class="vault-content">
{rendered}
    </main>"""
    else:
        body = f"""    <header>
        <h1>{_esc(title)}</h1>
        <p class="intent">{_esc(placeholder_intro)}</p>
    </header>
    <main class="vault-placeholder">
        <p>The {slug} markdown source is not yet synced into the renderer's build scope. The operator vault path
            (<code>~/Documents/Personal/30-areas/hapax/{slug}.md</code>) is the canonical authoring surface;
            this page renders that content directly when the build host has read access to the vault.</p>
        <p>Set <code>HAPAX_VAULT_HAPAX_DIR</code> to override the source dir.</p>
    </main>"""
    return PageMeta(
        path=path,
        title=title,
        description=description,
        body_html=body,
    )


def render_manifesto_page() -> PageMeta:
    """``/manifesto`` — Manifesto v0 rendered from the operator vault."""
    return _render_vault_page(
        slug="manifesto",
        path="/manifesto",
        title="Manifesto — Hapax research",
        description="Manifesto v0 — the canonical articulation of Hapax's single-operator research-instrument posture.",
        placeholder_intro="Manifesto v0 is the canonical articulation of Hapax's single-operator research-instrument posture.",
    )


def render_refusal_brief_page() -> PageMeta:
    """``/refusal-brief`` — Refusal Brief rendered from the operator vault."""
    return _render_vault_page(
        slug="refusal-brief",
        path="/refusal-brief",
        title="Refusal Brief — Hapax research",
        description="Refusal Brief — per-surface rationale for the publication-bus's REFUSED catalog.",
        placeholder_intro="The Refusal Brief enumerates the load-bearing constitutional, technical, and ethical reasons the publication-bus declines each Tier-3 REFUSED surface.",
    )


# ── Phase 1c: deposits page from DataCite snapshot ───────────────────


def _render_work_row(work: Work) -> str:
    """Render one DataCite-tracked work as an HTML list entry."""
    related_count = len(work.related_identifiers)
    related_suffix = (
        f" &middot; {related_count} related identifier{'s' if related_count != 1 else ''}"
        if related_count
        else ""
    )
    citations_suffix = (
        f" &middot; {work.citation_count} citation{'s' if work.citation_count != 1 else ''}"
        if work.citation_count
        else ""
    )
    return (
        f'                <li><a href="{_esc(work.landing_page_url)}"><code>{_esc(work.doi)}</code></a>'
        f"{citations_suffix}{related_suffix}</li>"
    )


def render_deposits_page(snapshot: DataCiteSnapshot | None = None) -> PageMeta:
    """``/deposits`` — operator's DataCite-tracked authored works.

    Reads the freshest snapshot via :func:`read_latest_snapshot`
    when ``snapshot`` is None (the build-time path); tests inject
    a fixture instead. Safe-fallback when no snapshot is available.
    """
    snap = snapshot if snapshot is not None else read_latest_snapshot()

    if snap.available:
        works_html = "\n".join(_render_work_row(w) for w in snap.works) or (
            "                <li><em>The DataCite mirror tracks zero works for this ORCID iD "
            "as of the snapshot date. New deposits land here on the next nightly fire.</em></li>"
        )
        body = f"""    <header>
        <h1>Deposits</h1>
        <p class="intent">Operator's authored works as resolved by the DataCite GraphQL API. Snapshot date: <code>{_esc(snap.snapshot_date or "")}</code>; ORCID iD: <a href="{_esc(snap.orcid_url or "")}"><code>{_esc(snap.orcid_url or "")}</code></a>.</p>
    </header>
    <main>
        <section class="deposits-list">
            <h2>Tracked works ({len(snap.works)})</h2>
            <ul>
{works_html}
            </ul>
        </section>
        <section class="snapshot-provenance">
            <h2>Snapshot provenance</h2>
            <p>Source: <code>~/hapax-state/datacite-mirror/{_esc(snap.snapshot_date or "")}.json</code> (updated daily by <code>hapax-datacite-mirror.timer</code>). Schema follows the DataCite Commons GraphQL <code>orcidWorks</code> query; <code>citations.totalCount</code> is the inbound-citation count DataCite knows about, and <code>relatedIdentifiers</code> are operator-or-deposit-asserted relations to other DOIs / URIs.</p>
        </section>
    </main>"""
    else:
        body = """    <header>
        <h1>Deposits</h1>
        <p class="intent">Operator's authored works as resolved by the DataCite GraphQL API.</p>
    </header>
    <main class="snapshot-placeholder">
        <p>No DataCite snapshot found at <code>~/hapax-state/datacite-mirror/</code>. The mirror runs nightly via
            <code>hapax-datacite-mirror.timer</code>; the first snapshot lands after the operator configures
            <code>HAPAX_OPERATOR_ORCID</code> (see <code>scripts/configure-orcid.sh</code> from PR #2018).
            Set <code>HAPAX_DATACITE_MIRROR_DIR</code> to override the source dir for this build.</p>
    </main>"""
    return PageMeta(
        path="/deposits",
        title="Deposits — Hapax research",
        description=f"Operator's DataCite-tracked authored works ({len(snap.works) if snap.available else 0} works).",
        body_html=body,
    )


# ── Site-level renderer ───────────────────────────────────────────────


@dataclass(frozen=True)
class RenderedSite:
    """The full set of rendered pages keyed by path."""

    pages: dict[str, str]


def render_site() -> RenderedSite:
    """Render all Phase-0 + Phase-1 pages.

    Returns a :class:`RenderedSite` mapping URL path → fully-formed
    HTML document. Pages with the long-form non-engagement clause:
    ``/``, ``/refuse``, and ``/refusal-brief``. Other pages use the
    short form.
    """
    pages: dict[str, str] = {}
    pages["/"] = _wrap(render_landing_page(), footer_long_form=True)
    pages["/cite"] = _wrap(render_cite_page(), footer_long_form=False)
    pages["/refuse"] = _wrap(render_refuse_page(), footer_long_form=True)
    pages["/surfaces"] = _wrap(render_surfaces_page(), footer_long_form=False)
    pages["/manifesto"] = _wrap(render_manifesto_page(), footer_long_form=False)
    pages["/refusal-brief"] = _wrap(render_refusal_brief_page(), footer_long_form=True)
    pages["/deposits"] = _wrap(render_deposits_page(), footer_long_form=False)
    return RenderedSite(pages=pages)
