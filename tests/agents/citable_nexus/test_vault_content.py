"""Tests for ``agents.citable_nexus.vault_content``."""

from __future__ import annotations

import pytest

from agents.citable_nexus.vault_content import (
    VAULT_HAPAX_DIR_ENV,
    markdown_to_html,
    read_cleared_inputs,
    read_vault_document,
)

# ── Vault read fallback ───────────────────────────────────────────────


class TestReadVaultDocument:
    def test_returns_unavailable_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv(VAULT_HAPAX_DIR_ENV, str(tmp_path))
        doc = read_vault_document("nonexistent")
        assert doc.available is False
        assert doc.markdown == ""
        assert doc.slug == "nonexistent"

    def test_returns_content_when_present(self, tmp_path, monkeypatch):
        monkeypatch.setenv(VAULT_HAPAX_DIR_ENV, str(tmp_path))
        target = tmp_path / "manifesto.md"
        target.write_text("# Manifesto\n\nFirst paragraph.\n", encoding="utf-8")
        doc = read_vault_document("manifesto", cleared_inputs=frozenset({target}))
        assert doc.available is True
        assert "Manifesto" in doc.markdown
        assert doc.slug == "manifesto"

    def test_empty_env_falls_back_to_default(self, tmp_path, monkeypatch):
        # Empty string env should defer to the default vault dir
        # (which may or may not exist on the test host; either way
        # the function returns a VaultDocument without raising).
        monkeypatch.setenv(VAULT_HAPAX_DIR_ENV, "")
        doc = read_vault_document("definitely-not-a-real-vault-slug-zzz9999")
        assert doc.available is False
        assert doc.markdown == ""

    def test_unset_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.delenv(VAULT_HAPAX_DIR_ENV, raising=False)
        doc = read_vault_document("definitely-not-a-real-vault-slug-zzz9999")
        assert doc.available is False
        assert doc.markdown == ""

    def test_directory_path_returns_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setenv(VAULT_HAPAX_DIR_ENV, str(tmp_path))
        # Create a directory at the slug path (not a regular file).
        (tmp_path / "manifesto.md").mkdir()
        doc = read_vault_document("manifesto")
        # Path.read_text raises IsADirectoryError → caught as OSError
        # → treated as unavailable.
        assert doc.available is False


# ── Markdown converter ────────────────────────────────────────────────


class TestMarkdownToHtml:
    def test_h1_heading(self):
        html = markdown_to_html("# Title")
        assert "<h1>Title</h1>" in html

    def test_h4_heading(self):
        html = markdown_to_html("#### Subsubsection")
        assert "<h4>Subsubsection</h4>" in html

    def test_paragraph(self):
        html = markdown_to_html("This is a paragraph.")
        assert "<p>This is a paragraph.</p>" in html

    def test_paragraphs_separated_by_blank_lines(self):
        html = markdown_to_html("First paragraph.\n\nSecond paragraph.")
        assert "<p>First paragraph.</p>" in html
        assert "<p>Second paragraph.</p>" in html

    def test_bullet_list(self):
        md = "- one\n- two\n- three"
        html = markdown_to_html(md)
        assert "<ul>" in html
        assert "<li>one</li>" in html
        assert "<li>two</li>" in html
        assert "<li>three</li>" in html
        assert "</ul>" in html

    def test_inline_code(self):
        html = markdown_to_html("Use `pass show` to read the secret.")
        assert "<code>pass show</code>" in html

    def test_inline_link(self):
        html = markdown_to_html("Visit [the spec](https://example.invalid/cite).")
        assert '<a href="https://example.invalid/cite">the spec</a>' in html

    def test_code_fence(self):
        md = "```\nimport sys\nsys.exit(0)\n```"
        html = markdown_to_html(md)
        assert "<pre><code>" in html
        assert "import sys" in html

    def test_html_escape_in_plain_text(self):
        html = markdown_to_html("Use <script> tags carefully.")
        assert "&lt;script&gt;" in html
        assert "<script>" not in html or "</script>" in html  # no raw script

    def test_html_escape_in_inline_code(self):
        html = markdown_to_html("`<dangerous>`")
        assert "<code>&lt;dangerous&gt;</code>" in html

    def test_empty_input_returns_empty_string(self):
        assert markdown_to_html("") == ""

    def test_heading_then_paragraph(self):
        md = "# Title\n\nA paragraph following."
        html = markdown_to_html(md)
        assert "<h1>Title</h1>" in html
        assert "<p>A paragraph following.</p>" in html


# ── Renderer integration with vault content ──────────────────────────


class TestRendererVaultIntegration:
    def test_manifesto_page_uses_vault_when_available(self, tmp_path, monkeypatch):
        monkeypatch.setenv(VAULT_HAPAX_DIR_ENV, str(tmp_path))
        (tmp_path / "manifesto.md").write_text(
            "# Manifesto v0\n\nA single-operator instrument.\n",
            encoding="utf-8",
        )

        from agents.citable_nexus.renderer import render_manifesto_page

        page = render_manifesto_page(cleared_inputs=frozenset({tmp_path / "manifesto.md"}))
        assert "<h2>Manifesto v0</h2>" in page.body_html
        assert "A single-operator instrument." in page.body_html

    def test_manifesto_page_placeholder_when_absent(self, tmp_path, monkeypatch):
        monkeypatch.setenv(VAULT_HAPAX_DIR_ENV, str(tmp_path))
        # Don't create manifesto.md; expect placeholder.

        from agents.citable_nexus.renderer import render_manifesto_page

        page = render_manifesto_page()
        assert "vault-placeholder" in page.body_html
        assert "No reviewed copy is included" in page.body_html

    def test_refusal_brief_page_uses_vault_when_available(self, tmp_path, monkeypatch):
        monkeypatch.setenv(VAULT_HAPAX_DIR_ENV, str(tmp_path))
        (tmp_path / "refusal-brief.md").write_text(
            "# Refusal Brief\n\n- declined: bandcamp\n- declined: discord\n",
            encoding="utf-8",
        )

        from agents.citable_nexus.renderer import render_refusal_brief_page

        page = render_refusal_brief_page(cleared_inputs=frozenset({tmp_path / "refusal-brief.md"}))
        assert "<h2>Refusal Brief</h2>" in page.body_html
        assert "<li>declined: bandcamp</li>" in page.body_html

    def test_render_site_omits_uncleared_documents(self, tmp_path, monkeypatch):
        monkeypatch.setenv(VAULT_HAPAX_DIR_ENV, str(tmp_path))

        from agents.citable_nexus.renderer import render_site

        site = render_site("https://example.invalid")
        assert "/manifesto" not in site.pages
        assert "/refusal-brief" not in site.pages
        assert "/deposits" not in site.pages
        assert "/citation-graph" not in site.pages


def test_readable_but_unlisted_never_rendered(tmp_path, monkeypatch):
    from agents.citable_nexus.renderer import render_site
    from scripts.build_citable_nexus import main

    monkeypatch.setenv(VAULT_HAPAX_DIR_ENV, str(tmp_path))
    (tmp_path / "manifesto.md").write_text("PRIVATE readable fixture")
    (tmp_path / "refusal-brief.md").write_text("PUBLIC cleared fixture")
    allowlist = tmp_path / "cleared.txt"
    allowlist.write_text("refusal-brief.md\n")
    assert not read_vault_document("manifesto").available
    site = render_site("https://example.invalid", cleared_inputs=allowlist)
    assert all("PRIVATE readable fixture" not in html for html in site.pages.values())
    assert "PUBLIC cleared fixture" in site.pages["/refusal-brief"]
    output = tmp_path / "site"
    assert (
        main(
            [
                "--out",
                str(output),
                "--canonical-url",
                "https://example.invalid",
                "--cleared-inputs",
                str(allowlist),
            ]
        )
        == 0
    )
    assert all(
        "PRIVATE readable fixture" not in path.read_text() for path in output.rglob("*.html")
    )
    # Empty and absent allowlists both clear nothing.
    allowlist.write_text("")
    assert read_cleared_inputs(allowlist) == read_cleared_inputs() == frozenset()


def test_listed_missing_input_refuses_by_name_before_output(tmp_path, caplog):
    from scripts.build_citable_nexus import main

    missing = tmp_path / "missing.md"
    allowlist = tmp_path / "cleared.txt"
    allowlist.write_text(str(missing) + "\n")
    with pytest.raises(ValueError, match="Cleared input refused:.*missing.md"):
        read_cleared_inputs(allowlist)
    assert (
        main(
            [
                "--out",
                str(tmp_path / "site"),
                "--canonical-url",
                "https://example.invalid",
                "--cleared-inputs",
                str(allowlist),
            ]
        )
        == 2
    )
    assert str(missing) in caplog.text
    assert not (tmp_path / "site").exists()


def test_allowlist_relative_absolute_and_failed_cleared_read(tmp_path, monkeypatch):
    monkeypatch.setenv(VAULT_HAPAX_DIR_ENV, str(tmp_path))
    target = tmp_path / "manifesto.md"
    target.write_text("# Fixture")
    allowlist = tmp_path / "cleared.txt"
    allowlist.write_text("manifesto.md\n" + str(target) + "\n\n")
    cleared = read_cleared_inputs(allowlist)
    assert cleared == frozenset({target})
    target.unlink()
    with pytest.raises(ValueError, match="Cleared input refused:.*manifesto.md"):
        read_vault_document("manifesto", cleared_inputs=cleared)
    with pytest.raises(ValueError, match="--cleared-inputs"):
        read_cleared_inputs(tmp_path / "absent-list")


def test_strong_emphasis_and_literal_code():
    assert (
        markdown_to_html("**A summary is not a person's instruction.**")
        == "<p><strong>A summary is not a person's instruction.</strong></p>"
    )
    assert markdown_to_html("`**literal**`") == "<p><code>**literal**</code></p>"
    assert markdown_to_html("[link](javascript:alert)") == "<p>link</p>"
