"""Tests for ``agents.citable_nexus.renderer``."""

from __future__ import annotations

import hashlib
import json
import re
import runpy
import tempfile
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

import pytest

from agents.citable_nexus.renderer import (
    HOME_SOURCE,
    PAGE_PATHS,
    SITE_DISTRIBUTION_LIMITS,
    V5_BYLINE,
    PageMeta,
    normalize_canonical_url,
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

CANONICAL = "https://example.invalid/research"
REPO_ROOT = Path(__file__).resolve().parents[3]

# ── PAGE_PATHS contract ───────────────────────────────────────────────


class TestPagePaths:
    def test_full_path_set(self):
        assert PAGE_PATHS == ("/", "/cite", "/404.html")


# ── Per-page renderers ───────────────────────────────────────────────


class TestLandingPage:
    def test_returns_page_meta(self):
        page = render_landing_page()
        assert isinstance(page, PageMeta)
        assert page.path == "/"

    def test_title_present(self):
        page = render_landing_page()
        assert "Hapax" in page.title

    def test_home_copy_is_committed_and_rendered(self):
        from agents.citable_nexus.vault_content import markdown_to_html

        copy = HOME_SOURCE.read_text(encoding="utf-8")
        assert (
            hashlib.sha256(copy.encode()).hexdigest()
            == "f5e06f09b779c7030fd47f86b357d7fca174e1313cce3c10824df837d810561b"  # pragma: allowlist secret (synthetic digest pin)
        )
        rendered = render_landing_page().body_html
        before, after = copy.split("<!-- parser-fixture -->")
        assert markdown_to_html(before) in rendered
        assert markdown_to_html(after) in rendered
        assert "<!-- parser-fixture -->" not in rendered
        assert (
            "Research and engineering on human-agent work, authority, evidence and consent." in copy
        )
        assert "A summary is not a person's instruction." in copy
        assert "individual publications explain contributions\nand review status." in copy
        assert copy.count("Research and engineering") == 1
        assert copy.count("One person") == 1
        assert "Payment must not purchase a" in copy
        headings = re.findall(r"^## (.+)$", copy, re.M)
        assert headings == [
            "Start With Something You Can Check",
            "The Questions Behind The Work",
            "Code And Research",
            "Commitments",
            "About The Work",
        ]
        for forbidden in (
            "Standards Entry",
            "GitHub Organization Lede",
            "Delivery Note",
            "Integration And Evidence Notes",
            "publish.obsidian.md",
            "Contact",
            "Phase",
        ):
            assert forbidden not in copy
        links = re.findall(r"\]\(([^)]+)\)", copy)
        assert links == [
            "https://github.com/hapax-systems/hapax-council/blob/9f4cd45184381a9befaa9208d6b0e6403de6484a/agents/dev_story/parser.py#L276",
            "https://github.com/hapax-systems/hapax-council/blob/9f4cd45184381a9befaa9208d6b0e6403de6484a/tests/dev_story/test_parser.py#L240",
            "https://github.com/hapax-systems",
            "https://hapax.weblog.lol/",
            "https://hapax.weblog.lol/rss.xml",
        ]

    def test_no_phase_or_readability_promises(self):
        for html in render_site(CANONICAL).pages.values():
            for stale in (
                "Phase 0",
                "Phase 1",
                "phase-note",
                "ship after",
                "read access",
                "not yet synced",
                "configure-orcid.sh",
                "HAPAX_VAULT_HAPAX_DIR",
            ):
                assert stale not in html


class TestCitePage:
    def test_path(self):
        page = render_cite_page(CANONICAL)
        assert page.path == "/cite"

    def test_bibtex_block(self):
        body = render_cite_page(CANONICAL).body_html
        assert "@misc" in body
        assert "hapax_research_2026" in body

    def test_ris_block(self):
        body = render_cite_page(CANONICAL).body_html
        assert "TY  - GEN" in body

    def test_plaintext_citation(self):
        body = render_cite_page(CANONICAL).body_html
        # `&` is HTML-escaped to `&amp;` in the body; both the
        # plaintext "Hapax" + "Oudepode" and the year must be present.
        assert "Hapax" in body
        assert "Oudepode" in body
        assert "2026" in body
        tokens = {token.strip(".,)") for token in body.split()}
        assert CANONICAL in tokens

    def test_cff_pointer(self):
        body = render_cite_page(CANONICAL).body_html
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
    def test_returns_only_current_entry_paths(self):
        site = render_site(CANONICAL)
        assert set(site.pages) == set(PAGE_PATHS)

    def test_every_page_is_html_doctype(self):
        site = render_site(CANONICAL)
        for path, html in site.pages.items():
            assert html.startswith("<!doctype html>"), f"{path} missing doctype"

    def test_every_page_has_v5_byline(self):
        site = render_site(CANONICAL)
        for path, html in site.pages.items():
            assert V5_BYLINE in html, f"{path} missing V5 byline"

    def test_every_page_has_non_engagement_clause(self):
        site = render_site(CANONICAL)
        for path, html in site.pages.items():
            assert SITE_DISTRIBUTION_LIMITS in html, path
            assert NON_ENGAGEMENT_CLAUSE_LONG not in html, path
            assert NON_ENGAGEMENT_CLAUSE_SHORT not in html, path
            assert "Polysemic decoder channel 7" not in html, path
            assert "AI agents contribute to research, implementation and writing" in html, path

    def test_every_page_has_canonical_link(self):
        site = render_site(CANONICAL)
        for path, html in site.pages.items():
            assert 'rel="canonical"' in html, f"{path} missing canonical link"

    def test_every_page_has_open_graph_meta(self):
        site = render_site(CANONICAL)
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
        site = render_site(CANONICAL)
        for path, html in site.pages.items():
            for phrase in self.FORBIDDEN_PHRASES:
                assert phrase not in html, (
                    f"{path} contains forbidden CTA copy: {phrase!r}; "
                    "the citable-nexus is a research-instrument index, not a "
                    "marketing landing page (per cc-task scope §Out of scope)"
                )


def test_footer_uses_per_artifact_distribution_override(monkeypatch):
    from unittest.mock import Mock

    from agents.citable_nexus import renderer

    render = Mock(wraps=renderer.render_attribution_block)
    monkeypatch.setattr(renderer, "render_attribution_block", render)
    site = render_site(CANONICAL)
    assert render.call_count == len(site.pages)
    for call in render.call_args_list:
        assert call.kwargs["non_engagement_clause_override"] == SITE_DISTRIBUTION_LIMITS
    assert "No comments, subscriptions or automated outreach originate here." in site.pages["/"]
    assert "Human-authored participation elsewhere remains possible." in site.pages["/"]


def test_home_figure_matches_source_fixture_and_observed_parser_roles(tmp_path, monkeypatch):
    # Execute the existing synthetic fixture in a temporary directory, recording
    # the actual parser inputs and output. No real transcript is read.
    fixture = runpy.run_path(str(REPO_ROOT / "tests/dev_story/test_parser.py"))
    case = fixture["test_compaction_summary_is_not_counted_as_an_operator_turn"]
    parse = fixture["parse_session"]
    observed = {}

    def record_parse(path, project_path):
        observed["envelopes"] = [json.loads(line) for line in path.read_text().splitlines()]
        result = parse(path, project_path)
        observed["roles"] = [message.role for message in result.messages]
        return result

    monkeypatch.setitem(case.__globals__, "parse_session", record_parse)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    case()
    body = render_landing_page().body_html
    figure = re.search(r"<figure\b.*?</figure>", body, re.S)[0]
    envelopes = [
        json.loads(unescape(block))
        for block in re.findall(r"<pre[^>]*><code>(.*?)</code></pre>", figure, re.S)
    ]
    assert envelopes == [
        {
            key: value
            for key, value in envelope.items()
            if key in ("type", "message", "isCompactSummary")
        }
        for envelope in observed["envelopes"]
    ]
    assert (
        re.findall(r"<dd><code>(.*?)</code></dd>", figure)
        == observed["roles"]
        == [
            "user",
            "compaction_summary",
        ]
    )
    assert '"uuid"' not in unescape(figure) and '"timestamp"' not in unescape(figure)
    assert "Parser result: 2 envelopes · 1 retained user turn." in figure
    assert "Synthetic fixture, abbreviated to the relevant fields." in figure
    assert "not speaker authentication or summary accuracy." in figure
    assert "9f4cd45184381a9befaa9208d6b0e6403de6484a/tests/dev_story/test_parser.py#L240" in body


class Structure(HTMLParser):
    """Strict checks for the renderer's HTML subset; HTMLParser alone is permissive."""

    VOID = {"meta", "link", "br", "hr", "img", "input", "source", "wbr"}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.tags = []
        self.ids = set()
        self.feed(html)
        self.close()
        assert not self.stack, self.stack

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        assert len(attributes) == len(attrs), "duplicate attributes"
        if "id" in attributes:
            assert attributes["id"] not in self.ids
            self.ids.add(attributes["id"])
        if tag == "li":
            assert self.stack[-1] in ("ul", "ol")
        if tag in ("p", "main", "section", "h1", "h2", "ul", "pre"):
            assert "p" not in self.stack, "block nested in paragraph"
        self.tags.append((tag, attributes))
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack and self.stack[-1] == tag, (tag, self.stack)
        self.stack.pop()


def test_all_pages_have_valid_semantic_self_contained_html():
    from agents.citable_nexus.datacite_snapshot import DataCiteSnapshot, Work
    from agents.citable_nexus.renderer import _wrap, render_citation_graph_page

    pages = render_site(CANONICAL).pages
    # Exercise the formerly network-dependent populated graph as well as empty pages.
    graph = render_citation_graph_page(
        DataCiteSnapshot(
            snapshot_date="2026-01-01",
            orcid_url=None,
            works=[
                Work(
                    doi="10.1234/example",
                    landing_page_url="https://example.invalid/work",
                    citation_count=0,
                    related_identifiers=[],
                )
            ],
        )
    )
    pages["populated-graph"] = _wrap(graph, CANONICAL)
    for path, html in pages.items():
        parsed = Structure(html)
        tags = [tag for tag, _ in parsed.tags]
        assert tags.count("html") == tags.count("head") == tags.count("body") == 1, path
        assert tags.count("main") == tags.count("h1") == 1, path
        assert any(
            tag == "meta"
            and attrs.get("name") == "viewport"
            and attrs.get("content") == "width=device-width, initial-scale=1"
            for tag, attrs in parsed.tags
        ), path
        previous = 0
        for tag, attrs in parsed.tags:
            if re.fullmatch(r"h[1-6]", tag):
                level = int(tag[1])
                assert level <= previous + 1, path
                previous = level
            assert tag not in ("img", "iframe", "object", "embed", "audio", "video"), path
            if tag == "script":
                assert attrs.get("type") == "application/json" and "src" not in attrs, path
            if tag == "link":
                assert attrs.get("rel") in ("canonical", "alternate"), path
        assert not re.search(r"@import|url\s*\(", html, re.I), path


def test_canonical_propagates_to_citations_chrome_and_cname(tmp_path):
    from scripts.build_citable_nexus import main

    output = tmp_path / "site"
    assert main(["--out", str(output), "--canonical-url", CANONICAL + "/"]) == 0
    assert (output / "CNAME").read_text() == "example.invalid\n"
    for path, html in render_site(CANONICAL).pages.items():
        parsed = Structure(html)
        canonicals = [
            attrs["href"]
            for tag, attrs in parsed.tags
            if tag == "link" and attrs.get("rel") == "canonical"
        ]
        assert canonicals == [CANONICAL + path], path
        for tag, attrs in parsed.tags:
            if tag == "a" and urlsplit(attrs["href"]).hostname not in (
                "github.com",
                "hapax.weblog.lol",
            ):
                assert attrs["href"].startswith(CANONICAL + "/"), (path, attrs["href"])
        assert not re.search(r'href="/(?!/)', html), path
        assert f'href="{CANONICAL}/"' in html
    cite = unescape((output / "cite/index.html").read_text())
    assert "url          = {" + CANONICAL + "}" in cite
    assert "UR  - " + CANONICAL in cite
    assert "instrument. " + CANONICAL in cite
    assert (
        "https://hapax.research" not in (REPO_ROOT / "agents/citable_nexus/renderer.py").read_text()
    )
    error = (output / "404.html").read_text()
    assert "<h1>Page not found</h1>" in error
    assert "The requested page is not included here." in error
    assert '<nav aria-label="Site">' in error and "<footer>" in error
    assert not (output / "404.html/index.html").exists()


def test_build_refuses_missing_canonical_input_before_writing(tmp_path, monkeypatch, capsys):
    from scripts.build_citable_nexus import main

    monkeypatch.delenv("HAPAX_CITABLE_NEXUS_CANONICAL_URL", raising=False)
    for output_format in ("html-tree", "json"):
        with pytest.raises(SystemExit) as exc:
            main(["--out", str(tmp_path / "absent"), "--format", output_format])
        assert exc.value.code == 2
        assert "--canonical-url is required" in capsys.readouterr().err
    assert not (tmp_path / "absent").exists()


def test_cli_environment_and_option_precedence(tmp_path, monkeypatch):
    from scripts.build_citable_nexus import main

    monkeypatch.setenv("HAPAX_CITABLE_NEXUS_CANONICAL_URL", "https://environment.invalid")
    output = tmp_path / "site.json"
    assert main(["--out", str(output), "--format", "json"]) == 0
    assert json.loads(output.read_text())["cname"] == "environment.invalid"
    assert main(["--out", str(output), "--format", "json", "--canonical-url", CANONICAL]) == 0
    payload = json.loads(output.read_text())
    assert payload["cname"] == "example.invalid"
    assert CANONICAL + "/cite" in payload["pages"]["/cite"]
    assert "feed" not in payload


@pytest.mark.parametrize(
    "value",
    [
        "",
        "example.invalid",
        "ftp://example.invalid",
        "https://user@example.invalid",
        "https://example.invalid/?q=x",
        "https://example.invalid/#x",
        "https://example.invalid/../escape",
        "https://example.invalid:bad",
    ],
)
def test_invalid_canonical_is_refused(value):
    with pytest.raises(ValueError, match="--canonical-url"):
        normalize_canonical_url(value)


def test_feed_exists_only_for_nonempty_cleared_entries(tmp_path, monkeypatch):
    from scripts.build_citable_nexus import main

    monkeypatch.setenv("HAPAX_VAULT_HAPAX_DIR", str(tmp_path))
    doc = tmp_path / "manifesto.md"
    doc.write_text("# Cleared example\n\nPublic fixture.")
    allowlist = tmp_path / "cleared.txt"
    allowlist.write_text("manifesto.md\n")
    output = tmp_path / "site"
    args = ["--out", str(output), "--canonical-url", CANONICAL]
    assert main(args) == 0
    assert not (output / "rss.xml").exists()
    assert 'rel="alternate"' not in (output / "index.html").read_text()
    assert main(args + ["--cleared-inputs", str(allowlist)]) == 0
    rss = ET.fromstring((output / "rss.xml").read_text())
    assert [item.findtext("link") for item in rss.findall("channel/item")] == [
        CANONICAL + "/manifesto"
    ]
    for html in output.rglob("*.html"):
        assert f'href="{CANONICAL}/rss.xml"' in html.read_text()
        Structure(html.read_text())
    json_out = tmp_path / "site.json"
    assert (
        main(
            [
                "--out",
                str(json_out),
                "--canonical-url",
                CANONICAL,
                "--format",
                "json",
                "--cleared-inputs",
                str(allowlist),
            ]
        )
        == 0
    )
    assert ET.fromstring(json.loads(json_out.read_text())["feed"]).find("channel/item") is not None
    assert main(args) == 0
    assert not (output / "rss.xml").exists(), "remove previously emitted feed on rebuild"
    assert not (output / "manifesto/index.html").exists(), "remove formerly cleared document"
    doc.write_text("")
    assert main(args + ["--cleared-inputs", str(allowlist)]) == 0
    assert not (output / "rss.xml").exists()


def test_workflow_and_cname_are_input_driven_text():
    template = (REPO_ROOT / "docs/citable-nexus/github-actions-deploy.yml.template").read_text()
    assert (
        "HAPAX_CITABLE_NEXUS_CANONICAL_URL: ${{ vars.HAPAX_CITABLE_NEXUS_CANONICAL_URL }}"
        in template
    )
    assert "--exclude 'CNAME'" not in template
    assert '"Pages: /, /cite, /refuse, /surfaces"' not in template
    assert "Phase 0" not in template
    assert (REPO_ROOT / "docs/citable-nexus/CNAME.template").read_text() == "{canonical_host}\n"


def test_registry_dispositions_and_existing_schema():
    import runpy

    import yaml

    path = REPO_ROOT / "docs/repo-pres/public-surface-registry.yaml"
    registry = yaml.safe_load(path.read_text())
    assert registry["schema_version"] == 1
    surfaces = {row["surface_id"]: row for row in registry["surfaces"]}
    expected = {
        "omg.landing": ("corrected", "agents/omg_web_builder/static/index.html"),
        "obsidian.publish.home": ("withdrawn", "docs/runbooks/obsidian-publish-sync.md"),
        "citable_nexus.entry": ("corrected", "agents/citable_nexus/renderer.py"),
        "weblog.chrome": (
            "unchanged-with-reason",
            "agents/publication_bus/omg_weblog_publisher.py",
        ),
        "weblog.rss_fanout": ("unchanged-with-reason", "agents/self_federate/rss_validator.py"),
        "github.organization.profile": (
            "unchanged-with-reason",
            "hapax-constitution/sdlc/render/org_profile_readme.py",
        ),
    }
    for name, (disposition, source) in expected.items():
        row = surfaces[name]
        assert row["disposition"] == disposition, name
        assert row["owner"] and row["disposition_reason"], name
        assert source in row["source_refs"], name
    gate = runpy.run_path(str(REPO_ROOT / "scripts/check-public-surface-claims.py"))
    assert gate["public_surface_registry_findings"](registry, registry_path=path) == []
