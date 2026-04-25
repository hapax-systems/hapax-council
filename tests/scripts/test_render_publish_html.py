"""Tests for ``emit_html_via_pandoc`` + ``--emit-md``/``--emit-html``
CLI options on ``scripts/render_constitutional_brief.py``.

Closes the V5 publish pipeline operator-side: takes the publish-ready
markdown form (#1445) and produces pandoc HTML for downstream
consumers (omg.lol weblog publisher, philarchive submission, static
site builds). Pandoc PDF render remains a documented operator-side
follow-on once the LaTeX backend is installed; HTML works
pandoc-native without LaTeX.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from textwrap import dedent

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def synthetic_brief(tmp_path: Path) -> Path:
    p = tmp_path / "synthetic-brief.md"
    p.write_text(
        dedent(
            """\
            ---
            title: "Synthetic Test Brief"
            authors:
              byline_variant: V2
              unsettled_variant: V3
              surface_deviation_matrix_key: philarchive
            non_engagement_clause_form: LONG
            ---

            # Synthetic Test Brief

            Body content here.
            """
        )
    )
    return p


@pytest.fixture
def have_pandoc() -> bool:
    return shutil.which("pandoc") is not None


class TestEmitHtmlViaPandoc:
    """The ``emit_html_via_pandoc`` function pipes publish-ready md
    through pandoc to produce a self-contained HTML document.
    """

    def test_emit_html_produces_html5_doctype(self, have_pandoc: bool) -> None:
        if not have_pandoc:
            pytest.skip("pandoc not installed")
        from scripts.render_constitutional_brief import emit_html_via_pandoc

        publish_md = "# Test Title\n\n**Byline**\n\nBody content.\n"
        html = emit_html_via_pandoc(publish_md, title="Test Title")

        assert "<!DOCTYPE html>" in html
        assert "<html" in html

    def test_emit_html_carries_title(self, have_pandoc: bool) -> None:
        if not have_pandoc:
            pytest.skip("pandoc not installed")
        from scripts.render_constitutional_brief import emit_html_via_pandoc

        publish_md = "# Body Title\n\nBody.\n"
        html = emit_html_via_pandoc(publish_md, title="My Custom Title")

        assert "<title>My Custom Title</title>" in html

    def test_emit_html_carries_body(self, have_pandoc: bool) -> None:
        if not have_pandoc:
            pytest.skip("pandoc not installed")
        from scripts.render_constitutional_brief import emit_html_via_pandoc

        publish_md = "# Test\n\n**Author Line**\n\nBody paragraph.\n"
        html = emit_html_via_pandoc(publish_md, title="Test")

        assert "Body paragraph." in html
        # Bold renders as <strong>
        assert "<strong>Author Line</strong>" in html

    def test_pandoc_missing_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When pandoc is not on PATH, FileNotFoundError surfaces."""
        from scripts.render_constitutional_brief import emit_html_via_pandoc

        # Force PATH to empty so pandoc cannot be found.
        monkeypatch.setenv("PATH", "/nonexistent")
        with pytest.raises((FileNotFoundError, subprocess.CalledProcessError)):
            emit_html_via_pandoc("# X\n", title="X")


class TestCliEmitMd:
    """``--emit-md PATH`` writes publish-ready markdown to disk."""

    def test_emit_md_writes_file(
        self, monkeypatch: pytest.MonkeyPatch, synthetic_brief: Path, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
        out_path = tmp_path / "out" / "synthetic.publish.md"
        from scripts.render_constitutional_brief import main

        rc = main(["render", str(synthetic_brief), "--emit-md", str(out_path)])

        assert rc == 0
        assert out_path.exists()
        content = out_path.read_text()
        # Title heading from frontmatter
        assert "# Synthetic Test Brief" in content
        # Byline and body interpolated
        assert "Test Operator" in content
        assert "Body content here" in content

    def test_emit_md_creates_parent_dirs(
        self, monkeypatch: pytest.MonkeyPatch, synthetic_brief: Path, tmp_path: Path
    ) -> None:
        """``--emit-md`` mkdir -p's the parent directory so callers
        don't need to pre-create the published-artifacts subtree."""
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
        out_path = tmp_path / "deeply" / "nested" / "out" / "x.md"
        from scripts.render_constitutional_brief import main

        rc = main(["render", str(synthetic_brief), "--emit-md", str(out_path)])

        assert rc == 0
        assert out_path.exists()


class TestCliEmitHtml:
    """``--emit-html PATH`` writes pandoc HTML to disk (when pandoc available)."""

    def test_emit_html_writes_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        synthetic_brief: Path,
        tmp_path: Path,
        have_pandoc: bool,
    ) -> None:
        if not have_pandoc:
            pytest.skip("pandoc not installed")
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
        out_path = tmp_path / "out" / "synthetic.html"
        from scripts.render_constitutional_brief import main

        rc = main(["render", str(synthetic_brief), "--emit-html", str(out_path)])

        assert rc == 0
        assert out_path.exists()
        content = out_path.read_text()
        assert "<!DOCTYPE html>" in content
        assert "Test Operator" in content
        assert "Body content here" in content
        assert "<title>Synthetic Test Brief</title>" in content

    def test_emit_html_when_pandoc_missing_returns_3(
        self,
        monkeypatch: pytest.MonkeyPatch,
        synthetic_brief: Path,
        tmp_path: Path,
    ) -> None:
        """When pandoc is missing, exit code 3 distinguishes the
        infrastructure failure from a source-error (rc=2)."""
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
        monkeypatch.setenv("PATH", "/nonexistent")
        out_path = tmp_path / "out" / "synthetic.html"
        from scripts.render_constitutional_brief import main

        rc = main(["render", str(synthetic_brief), "--emit-html", str(out_path)])

        assert rc == 3
        assert not out_path.exists()


class TestCliBothModes:
    """``--emit-md`` and ``--emit-html`` can be combined; both fire."""

    def test_both_emit_modes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        synthetic_brief: Path,
        tmp_path: Path,
        have_pandoc: bool,
    ) -> None:
        if not have_pandoc:
            pytest.skip("pandoc not installed")
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
        md_out = tmp_path / "out" / "synthetic.publish.md"
        html_out = tmp_path / "out" / "synthetic.html"
        from scripts.render_constitutional_brief import main

        rc = main(
            [
                "render",
                str(synthetic_brief),
                "--emit-md",
                str(md_out),
                "--emit-html",
                str(html_out),
            ]
        )

        assert rc == 0
        assert md_out.exists()
        assert html_out.exists()
