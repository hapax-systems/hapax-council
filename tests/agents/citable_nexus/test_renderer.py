"""Tests for ``agents.citable_nexus.renderer``."""

from __future__ import annotations

import re

from agents.citable_nexus.renderer import (
    PAGE_PATHS,
    V5_BYLINE,
    PageMeta,
    render_cite_page,
    render_landing_page,
    render_refuse_page,
    render_site,
    render_surfaces_page,
)
from agents.publication_bus.surface_registry import (
    SURFACE_REGISTRY,
    AutomationStatus,
    refused_surfaces,
)
from shared.attribution_block import (
    NON_ENGAGEMENT_CLAUSE_LONG,
    NON_ENGAGEMENT_CLAUSE_SHORT,
)

# ── PAGE_PATHS contract ───────────────────────────────────────────────


class TestPagePaths:
    def test_phase_0_plus_1_set(self):
        assert PAGE_PATHS == (
            "/",
            "/cite",
            "/refuse",
            "/surfaces",
            "/manifesto",
            "/refusal-brief",
            "/deposits",
        )

    def test_no_phase_2_paths_yet(self):
        for not_yet in ("/citation-graph",):
            assert not_yet not in PAGE_PATHS


# ── Per-page renderers ───────────────────────────────────────────────


class TestLandingPage:
    def test_returns_page_meta(self):
        page = render_landing_page()
        assert isinstance(page, PageMeta)
        assert page.path == "/"

    def test_title_present(self):
        page = render_landing_page()
        assert "Hapax research" in page.title

    def test_body_lists_other_pages(self):
        body = render_landing_page().body_html
        assert "/cite" in body
        assert "/refuse" in body
        assert "/surfaces" in body

    def test_body_mentions_phase_1_pages_as_deferred(self):
        body = render_landing_page().body_html
        assert "manifesto" in body.lower()


class TestCitePage:
    def test_path(self):
        page = render_cite_page()
        assert page.path == "/cite"

    def test_bibtex_block(self):
        body = render_cite_page().body_html
        assert "@misc" in body
        assert "hapax_research_2026" in body

    def test_ris_block(self):
        body = render_cite_page().body_html
        assert "TY  - GEN" in body

    def test_plaintext_citation(self):
        body = render_cite_page().body_html
        # `&` is HTML-escaped to `&amp;` in the body; both the
        # plaintext "Hapax" + "Oudepode" and the year must be present.
        assert "Hapax" in body
        assert "Oudepode" in body
        assert "2026" in body
        assert "https://hapax.research" in body

    def test_cff_pointer(self):
        body = render_cite_page().body_html
        assert "CITATION.cff" in body
        assert "hapax-council" in body


class TestRefusePage:
    def test_path(self):
        page = render_refuse_page()
        assert page.path == "/refuse"

    def test_lists_each_refused_surface(self):
        body = render_refuse_page().body_html
        for refused in refused_surfaces():
            assert refused in body

    def test_count_matches_registry(self):
        body = render_refuse_page().body_html
        match = re.search(r"\((\d+) surfaces\)", body)
        assert match is not None
        assert int(match.group(1)) == len(refused_surfaces())


class TestSurfacesPage:
    def test_path(self):
        page = render_surfaces_page()
        assert page.path == "/surfaces"

    def test_three_tiers_present(self):
        body = render_surfaces_page().body_html
        assert "FULL_AUTO" in body
        assert "CONDITIONAL_ENGAGE" in body
        assert "REFUSED" in body

    def test_lists_every_surface_in_registry(self):
        body = render_surfaces_page().body_html
        for surface_name in SURFACE_REGISTRY:
            assert surface_name in body, f"{surface_name} missing from /surfaces"

    def test_tier_counts_match_registry(self):
        body = render_surfaces_page().body_html
        auto_count = sum(
            1
            for spec in SURFACE_REGISTRY.values()
            if spec.automation_status == AutomationStatus.FULL_AUTO
        )
        conditional_count = sum(
            1
            for spec in SURFACE_REGISTRY.values()
            if spec.automation_status == AutomationStatus.CONDITIONAL_ENGAGE
        )
        refused_count = sum(
            1
            for spec in SURFACE_REGISTRY.values()
            if spec.automation_status == AutomationStatus.REFUSED
        )
        assert f"FULL_AUTO ({auto_count})" in body
        assert f"CONDITIONAL_ENGAGE ({conditional_count})" in body
        assert f"REFUSED ({refused_count})" in body


# ── Site-level renderer ───────────────────────────────────────────────


class TestRenderSite:
    def test_returns_all_phase_0_paths(self):
        site = render_site()
        assert set(site.pages) == set(PAGE_PATHS)

    def test_every_page_is_html_doctype(self):
        site = render_site()
        for path, html in site.pages.items():
            assert html.startswith("<!doctype html>"), f"{path} missing doctype"

    def test_every_page_has_v5_byline(self):
        site = render_site()
        for path, html in site.pages.items():
            assert V5_BYLINE in html, f"{path} missing V5 byline"

    def test_every_page_has_non_engagement_clause(self):
        site = render_site()
        for path, html in site.pages.items():
            has_long = NON_ENGAGEMENT_CLAUSE_LONG in html
            has_short = NON_ENGAGEMENT_CLAUSE_SHORT in html
            assert has_long or has_short, f"{path} missing non-engagement clause"

    def test_every_page_has_canonical_link(self):
        site = render_site()
        for path, html in site.pages.items():
            assert 'rel="canonical"' in html, f"{path} missing canonical link"

    def test_every_page_has_open_graph_meta(self):
        site = render_site()
        for path, html in site.pages.items():
            assert 'property="og:title"' in html, f"{path} missing og:title"
            assert 'property="og:description"' in html, f"{path} missing og:description"
            assert 'property="og:url"' in html, f"{path} missing og:url"


# ── Constitutional invariants ─────────────────────────────────────────


class TestNoCtaCopy:
    """Per cc-task: no Subscribe / Contact / Demo CTAs anywhere."""

    FORBIDDEN_PHRASES = (
        "Subscribe",
        "subscribe to our",
        "Contact Us",
        "Contact us",
        "Get a Demo",
        "Get Started",
        "Sign Up",
        "Sign up",
        "Buy Now",
    )

    def test_no_cta_copy_anywhere(self):
        site = render_site()
        for path, html in site.pages.items():
            for phrase in self.FORBIDDEN_PHRASES:
                assert phrase not in html, (
                    f"{path} contains forbidden CTA copy: {phrase!r}; "
                    "the citable-nexus is a research-instrument index, not a "
                    "marketing landing page (per cc-task scope §Out of scope)"
                )


class TestPolysemicRegister:
    def test_register_attribution_present_on_landing(self):
        # The polysemic-decoder-channel-7 string is in the footer, not the
        # body. Check it on the full rendered page (body + footer) instead.
        from agents.citable_nexus.renderer import _wrap

        full = _wrap(render_landing_page(), footer_long_form=True)
        assert "Polysemic decoder channel 7" in full
