"""Static HTML renderer for the citable-nexus front-door site.

Each ``render_<page>_page`` function returns a fully-formed HTML
string with V5 attribution boilerplate + non-engagement clause in
the footer. The renderer is deliberately framework-free — no Astro,
no Eleventy, no Hugo dependency. Pure stdlib + filesystem reads from
``agents.publication_bus.surface_registry`` and
``shared.attribution_block``. The output is portable across any
static host (GitHub Pages, omg.lol weblog, Netlify, plain object
storage).

Invariants the renderer enforces:

  - No operator legal name in any rendered page body. The V5 byline
    constants come from ``shared.attribution_block`` which has its
    own legal-name guard; all other body text is hand-authored here
    and must remain operator-referent-only ("Oudepode", "the
    operator", "OTO").
  - No "Subscribe" / "Contact" / "Get a Demo" CTAs. Verified by
    :class:`tests.agents.citable_nexus.test_renderer.TestNoCtaCopy`.
  - Site-specific distribution limits appear on every page footer via
    the shared attribution block's per-artifact override.
  - Open Graph + Bluesky meta tags on every page.
  - Self-contained HTML — no external CSS / JS dependencies.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from agents.authoring.byline import Byline, BylineVariant, SurfaceRegister
from agents.citable_nexus.citation_graph import compose_graph
from agents.citable_nexus.datacite_snapshot import (
    DataCiteSnapshot,
    Work,
    read_latest_snapshot,
)
from agents.citable_nexus.vault_content import (
    markdown_to_html,
    read_cleared_inputs,
    read_vault_document,
)
from agents.publication_bus.surface_registry import (
    SURFACE_REGISTRY,
    AutomationStatus,
    auto_surfaces,
    refused_surfaces,
)
from shared.attribution_block import (
    UnsettledContributionVariant,
    render_attribution_block,
)

# ── Page registry ────────────────────────────────────────────────────


@dataclass(frozen=True)
class PageMeta:
    """Metadata for one rendered static page."""

    path: str
    title: str
    description: str
    body_html: str


PAGE_PATHS: Final[tuple[str, ...]] = ("/", "/cite", "/404.html")
"""Always included pages. Optional document routes require cleared inputs."""

HOME_SOURCE = Path(__file__).resolve().parents[2] / "docs/citable-nexus/home.md"


def normalize_canonical_url(value: str) -> str:
    """Accept an explicit HTTP(S) origin, optionally with a static-site path prefix."""
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or re.search(r"[\s<>\\{}\"']", value)
        or any(part in (".", "..") for part in parsed.path.split("/"))
    ):
        raise ValueError(
            "--canonical-url must be an absolute HTTP(S) URL without credentials, query or fragment"
        )
    # Also reject malformed port numbers before any output is written.
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError(f"--canonical-url: {exc}") from exc
    return value


V5_BYLINE: Final[str] = "Hapax / Oudepode / OTO"
"""V5 byline per the operator-referent policy. Uses the operator-
referent picker's canonical names; no legal name. The Refusal Brief's
authorship-indeterminacy stance binds this byline to the artifact set,
not to a single person."""

SITE_DISTRIBUTION_LIMITS: Final[str] = (
    "This site publishes static research pages. No comments, subscriptions or "
    "automated outreach originate here. Human-authored participation elsewhere remains possible."
)
"""Per-artifact limits; this does not change shared estate distribution policy."""


# ── HTML helpers ──────────────────────────────────────────────────────


def _esc(text: str) -> str:
    """Minimal HTML escaper (stdlib's html.escape would do but
    pulling it for a 4-char substitution is overkill)."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _meta_tags(title: str, description: str, page_path: str, canonical_base: str) -> str:
    """Open Graph + Bluesky + Twitter Card meta tags.

    Bluesky uses Open Graph; the explicit ``og:`` block covers all
    three platforms with one declaration."""
    canonical_url = f"{canonical_base}{page_path}"
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


def _footer() -> str:
    """Identify the work and contributions, with this site's distribution limits."""
    attribution = render_attribution_block(
        Byline(operator_legal_name="", operator_referent="Oudepode"),
        byline_variant=BylineVariant.V4,
        unsettled_variant=UnsettledContributionVariant.V4,
        register=SurfaceRegister.AESTHETIC,
        non_engagement_clause_override=SITE_DISTRIBUTION_LIMITS,
    )
    return f"""    <footer>
        <p class="byline">{_esc(attribution.byline_text)}</p>
        <p>AI agents contribute to research, implementation and writing;
        individual publications explain contributions and review status.</p>
        <p class="clause">{_esc(attribution.non_engagement_clause or "")}</p>
    </footer>"""


def _wrap(meta: PageMeta, canonical_url: str, *, has_feed: bool = False) -> str:
    """Wrap one PageMeta into a full HTML document."""
    body = re.sub(
        r'href="(/(?!/)[^" ]*)"', lambda m: f'href="{_esc(canonical_url)}{m[1]}"', meta.body_html
    )
    feed_link = (
        f'<link rel="alternate" type="application/rss+xml" title="Hapax documents" href="{_esc(canonical_url)}/rss.xml">'
        if has_feed
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
{_meta_tags(meta.title, meta.description, meta.path, canonical_url)}
{feed_link}
<style>
:root {{ color-scheme: light dark; --bg: light-dark(hsl(0 0% 98%), hsl(0 0% 10%)); --panel: light-dark(hsl(0 0% 94%), hsl(0 0% 14%)); --ink: light-dark(hsl(0 0% 13%), hsl(0 0% 92%)); --muted: light-dark(hsl(0 0% 35%), hsl(0 0% 72%)); --link: light-dark(hsl(205 80% 32%), hsl(200 75% 74%)); --status: light-dark(hsl(155 65% 25%), hsl(155 48% 69%)); --rule: light-dark(hsl(0 0% 72%), hsl(0 0% 38%)); }}
* {{ box-sizing: border-box; letter-spacing: 0; }}
body {{ margin: auto; max-width: 66rem; padding: 3rem; background: var(--bg); color: var(--ink); font: 1.0625rem/1.7 system-ui, sans-serif; overflow-wrap: anywhere; }}
h1, h2, h3, h4 {{ line-height: 1.2; text-wrap: balance; }}
h1 {{ font-size: 3rem; margin-block: 2.5rem 1.5rem; }}
.home > h1 {{ font-family: ui-monospace, monospace; }}
.home > h1 + p {{ font-size: 1.375rem; line-height: 1.5; max-width: 48ch; }}
h2 {{ font-size: 1.45rem; margin-block: 3rem 1.25rem; border-block-start: 1px solid var(--rule); padding-block-start: 1rem; }}
p, ul {{ max-width: 68ch; }}
a {{ color: var(--link); text-underline-offset: .2em; }}
a:hover {{ text-decoration-thickness: .15em; }}
a:focus-visible {{ outline: 2px solid currentColor; outline-offset: 4px; }}
nav {{ border-block: 1px solid var(--rule); padding-block: .65rem; font-size: .95rem; }}
nav a {{ display: inline-block; margin-inline-end: 1rem; }}
footer {{ border-block-start: 1px solid var(--rule); margin-block-start: 3.5rem; padding-block: 1.25rem; color: var(--muted); font-size: .9rem; }}
.byline {{ color: var(--ink); font-weight: 650; }}
pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: var(--panel); padding: 1rem; font-size: .875rem; line-height: 1.6; }}
code {{ font-family: ui-monospace, monospace; }}
.parser-fixture {{ margin: 1.75rem 0; border: 1px solid var(--rule); }}
figcaption {{ padding: 1rem 1.25rem; color: var(--muted); font-size: .95rem; max-width: 76ch; }}
figcaption strong {{ display: block; color: var(--ink); margin-block-end: .35rem; }}
.fixture-row {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(13rem, .5fr); border-block-start: 1px solid var(--rule); }}
.fixture-row pre {{ margin: 0; }}
.fixture-row dl {{ margin: 0; padding: 1rem 1.25rem; }}
.fixture-row dt {{ color: var(--muted); font-size: .85rem; }}
.fixture-row dd {{ margin: .35rem 0 0; color: var(--status); font-weight: 650; }}
.fixture-result {{ border-block-start: 1px solid var(--rule); padding: .75rem 1.25rem; margin: 0; max-width: none; font-size: .95rem; }}
@media (max-width: 40rem) {{
    body {{ padding: 1rem; }}
    .fixture-row {{ grid-template-columns: minmax(0, 1fr); }}
}}
</style>
</head>
<body>
<nav aria-label="Site"><a href="{_esc(canonical_url)}/">Home</a><a href="{_esc(canonical_url)}/cite">Cite</a></nav>
{body}
{_footer()}
</body>
</html>
"""


# ── Page renderers ────────────────────────────────────────────────────


def _parser_fixture_figure() -> str:
    """Abbreviated verbatim fields from the synthetic test linked in home.md.

    Source: tests/dev_story/test_parser.py:240-270 at
    9f4cd45184381a9befaa9208d6b0e6403de6484a, including its asserted roles.
    Omit identifiers/timestamps; the remaining content is copied, not invented.
    """
    examples = (
        (
            {"type": "user", "message": {"role": "user", "content": "a real operator turn"}},
            "user",
        ),
        (
            {
                "type": "user",
                "isCompactSummary": True,
                "message": {"role": "user", "content": "agent-authored summary prose"},
            },
            "compaction_summary",
        ),
    )
    rows = "\n".join(
        '<div class="fixture-row">'
        f'<pre aria-label="Synthetic envelope {number}"><code>{_esc(json.dumps(envelope, indent=2))}</code></pre>'
        "<dl><dt>Observed parser role</dt>"
        f"<dd><code>{_esc(role)}</code></dd></dl></div>"
        for number, (envelope, role) in enumerate(examples, 1)
    )
    return f"""<figure class="parser-fixture" aria-labelledby="parser-fixture-caption">
<figcaption id="parser-fixture-caption"><strong>Two envelopes, one retained user turn</strong>
Synthetic fixture, abbreviated to the relevant fields. It demonstrates the distinction
between a user turn and a compaction summary, not speaker authentication or summary accuracy.</figcaption>
{rows}
<p class="fixture-result">Parser result: 2 envelopes · 1 retained user turn.</p>
</figure>"""


def render_landing_page() -> PageMeta:
    """Render the committed, reader-facing home copy."""
    markdown = HOME_SOURCE.read_text(encoding="utf-8")
    description = " ".join(markdown.split("\n\n")[1].splitlines())
    # This committed home-only marker inserts trusted figure markup. The general
    # Markdown renderer continues to escape raw HTML in cleared documents.
    before, after = markdown.split("<!-- parser-fixture -->")
    body = markdown_to_html(before) + _parser_fixture_figure() + markdown_to_html(after)
    return PageMeta(
        path="/",
        title="Hapax — research and engineering",
        description=description,
        body_html=f'<main class="home">{body}</main>',
    )


def render_cite_page(canonical_url: str) -> PageMeta:
    """``/cite`` — canonical citation block in BibTeX, RIS, plaintext."""
    canonical_url = normalize_canonical_url(canonical_url)
    bibtex = (
        "@misc{hapax_research_2026,\n"
        "  author       = {Hapax and Oudepode},\n"
        "  title        = {Hapax: a single-operator research instrument},\n"
        "  year         = {2026},\n"
        f"  url          = {{{canonical_url}}},\n"
        "  note         = {Authorship-indeterminacy stance per V5 attribution policy}\n"
        "}"
    )
    ris = (
        "TY  - GEN\n"
        "AU  - Hapax\n"
        "AU  - Oudepode\n"
        "TI  - Hapax: a single-operator research instrument\n"
        "PY  - 2026\n"
        f"UR  - {canonical_url}\n"
        "ER  - "
    )
    plaintext = (
        f"Hapax & Oudepode (2026). Hapax: a single-operator research instrument. {canonical_url}"
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
                <a href="https://github.com/hapax-systems/hapax-council">hapax-council</a> repo
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
        <p class="intent">Surfaces the publication-bus has explicitly chosen not to engage with. The Refusal Brief documents the reasoning per surface; this page records the source registry at build time.</p>
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


# ── Cleared vault-content pages ────────────────────────────────────


def _render_vault_page(
    *,
    slug: str,
    path: str,
    title: str,
    description: str,
    placeholder_intro: str,
    cleared_inputs: frozenset[Path],
) -> PageMeta:
    """Render a cleared source or state plainly that no copy is included."""
    doc = read_vault_document(slug, cleared_inputs=cleared_inputs)
    if doc.available:
        rendered = markdown_to_html(doc.markdown)
        rendered = re.sub(r"<(\/?)(h[1-4])>", lambda m: f"<{m[1]}h{int(m[2][1]) + 1}>", rendered)
        body = f"""    <header>
        <h1>{_esc(title)}</h1>
        <p class="intent">Included from an explicitly cleared source.</p>
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
        <p>No reviewed copy is included in this build.</p>
    </main>"""
    return PageMeta(
        path=path,
        title=title,
        description=description,
        body_html=body,
    )


def render_manifesto_page(*, cleared_inputs: frozenset[Path] = frozenset()) -> PageMeta:
    """``/manifesto`` — Manifesto v0 rendered from the operator vault."""
    return _render_vault_page(
        slug="manifesto",
        cleared_inputs=cleared_inputs,
        path="/manifesto",
        title="Manifesto — Hapax research",
        description="Manifesto v0 — the canonical articulation of Hapax's single-operator research-instrument posture.",
        placeholder_intro="Manifesto v0 is the canonical articulation of Hapax's single-operator research-instrument posture.",
    )


def render_refusal_brief_page(*, cleared_inputs: frozenset[Path] = frozenset()) -> PageMeta:
    """``/refusal-brief`` — Refusal Brief rendered from the operator vault."""
    return _render_vault_page(
        slug="refusal-brief",
        cleared_inputs=cleared_inputs,
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
        <p>No reviewed deposit snapshot is included in this build.</p>
    </main>"""
    return PageMeta(
        path="/deposits",
        title="Deposits — Hapax research",
        description=f"Operator's DataCite-tracked authored works ({len(snap.works) if snap.available else 0} works).",
        body_html=body,
    )


# ── Phase 2: citation graph from DataCite snapshot ───────────────────


def render_citation_graph_page(
    snapshot: DataCiteSnapshot | None = None,
) -> PageMeta:
    """``/citation-graph`` — DataCite-derived backlink network.

    Composes a Cytoscape.js elements list from the freshest DataCite
    snapshot (or an injected fixture for tests). The page embeds the
    JSON inline for machine extraction and a readable identifier/relation
    list. No graph library or network request is needed.
    """
    snap = snapshot if snapshot is not None else read_latest_snapshot()
    graph = compose_graph(snap)
    elements = graph.to_cytoscape_elements()
    elements_json = json.dumps(elements, sort_keys=True)

    if snap.available:
        intro = (
            f"DataCite-derived backlink network. Snapshot date: "
            f"<code>{_esc(snap.snapshot_date or '')}</code>; "
            f"{len(graph.nodes)} nodes, {len(graph.edges)} edges."
        )
        rows = "\n".join(
            f"<li>{_esc(edge.source)} — {_esc(edge.relation_type)} — {_esc(edge.target)}</li>"
            for edge in graph.edges
        )
        nodes = "\n".join(f"<li>{_esc(node.id)}</li>" for node in graph.nodes)
        # Escape raw-text script delimiters even in explicitly supplied data.
        elements_json = elements_json.replace("<", "\\u003c")
        body_main = f"""    <main>
        <section><h2>Identifiers</h2><ul>{nodes}</ul></section>
        <section><h2>Recorded relations</h2><ul>{rows}</ul></section>
        <section><h2>Graph data</h2><p>Embedded JSON uses the Cytoscape elements format.</p>
        <pre>{_esc(elements_json)}</pre></section>
    </main>
    <script type="application/json" id="graph-data">{elements_json}</script>"""
    else:
        intro = "DataCite-derived backlink network."
        body_main = """    <main class="snapshot-placeholder">
        <p>No reviewed citation graph is included in this build.</p>
    </main>"""

    body = f"""    <header>
        <h1>Citation graph</h1>
        <p class="intent">{intro}</p>
    </header>
{body_main}"""
    return PageMeta(
        path="/citation-graph",
        title="Citation graph — Hapax research",
        description=f"DataCite-derived backlink network ({len(graph.nodes)} nodes, {len(graph.edges)} edges).",
        body_html=body,
    )


# ── Site-level renderer ───────────────────────────────────────────────


@dataclass(frozen=True)
class RenderedSite:
    """The full set of rendered pages keyed by path."""

    pages: dict[str, str]
    feed: str | None = None


def render_site(canonical_url: str, *, cleared_inputs: Path | None = None) -> RenderedSite:
    """Render committed chrome/home and only explicitly cleared optional documents."""
    canonical_url = normalize_canonical_url(canonical_url)
    cleared = read_cleared_inputs(cleared_inputs)
    entries = [
        read_vault_document(slug, cleared_inputs=cleared) for slug in ("manifesto", "refusal-brief")
    ]
    entries = [doc for doc in entries if doc.available and doc.markdown.strip()]
    metadata = [
        render_landing_page(),
        render_cite_page(canonical_url),
        PageMeta(
            path="/404.html",
            title="Page not found — Hapax",
            description="The requested page was not found.",
            body_html='<main><h1>Page not found</h1><p>The requested page is not included here. <a href="/">Return home</a>.</p></main>',
        ),
    ]
    if any(doc.slug == "manifesto" for doc in entries):
        metadata.append(render_manifesto_page(cleared_inputs=cleared))
    if any(doc.slug == "refusal-brief" for doc in entries):
        metadata.append(render_refusal_brief_page(cleared_inputs=cleared))
    pages = {
        meta.path: _wrap(
            meta,
            canonical_url,
            has_feed=bool(entries),
        )
        for meta in metadata
    }
    feed = None
    if entries:
        rss = ET.Element("rss", version="2.0")
        channel = ET.SubElement(rss, "channel")
        for tag, value in (
            ("title", "Hapax documents"),
            ("link", canonical_url + "/"),
            ("description", "Documents included in this build."),
        ):
            ET.SubElement(channel, tag).text = value
        for doc in entries:
            item = ET.SubElement(channel, "item")
            ET.SubElement(item, "title").text = doc.slug.replace("-", " ").title()
            ET.SubElement(item, "link").text = canonical_url + "/" + doc.slug
            ET.SubElement(item, "guid", isPermaLink="true").text = canonical_url + "/" + doc.slug
        feed = ET.tostring(rss, encoding="unicode", xml_declaration=True)
    return RenderedSite(pages=pages, feed=feed)
