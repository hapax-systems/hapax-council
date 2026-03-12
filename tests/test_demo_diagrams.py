"""Tests for D2 diagram generation and sanitization."""

from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("PIL", reason="Pillow not installed")

from agents.demo_pipeline.diagrams import (  # noqa: E402
    _convert_inline_chain,
    _expand_semicolons,
    _extract_nodes_and_edges,
    _fallback_diagram,
    _simplify_d2,
    _strip_style_blocks,
    is_d2_available,
    render_d2,
    sanitize_d2_source,
)


class TestDiagrams:
    def test_is_d2_available_returns_bool(self):
        result = is_d2_available()
        assert isinstance(result, bool)

    def test_render_d2_fallback_no_d2(self, tmp_path):
        """When D2 not installed, generates fallback Pillow image."""
        output = tmp_path / "diagram.png"
        with patch("agents.demo_pipeline.diagrams.is_d2_available", return_value=False):
            result = render_d2("A -> B -> C", output)
        assert result.exists()
        assert result.stat().st_size > 0

    @pytest.mark.skipif(not is_d2_available(), reason="D2 not installed")
    def test_render_d2_with_d2(self, tmp_path):
        output = tmp_path / "diagram.png"
        result = render_d2("A -> B", output)
        assert result.exists()

    def test_gruvbox_theme_in_source(self, tmp_path):
        """Verify theme is prepended (check via mock subprocess)."""
        output = tmp_path / "diagram.png"
        with (
            patch("agents.demo_pipeline.diagrams.is_d2_available", return_value=True),
            patch("subprocess.run") as mock_run,
            patch("tempfile.NamedTemporaryFile") as mock_tmp,
        ):
            # Make mock work
            mock_file = mock_tmp.return_value.__enter__.return_value
            mock_file.name = str(tmp_path / "test.d2")
            mock_run.return_value.returncode = 0
            # Create output file so the function succeeds
            output.touch()

            render_d2("A -> B", output)

            # Check what was written to the temp file
            written = mock_file.write.call_args[0][0]
            assert "theme-id: 200" in written
            assert "#282828" in written


class TestConvertInlineChain:
    def test_converts_single_line_chain(self):
        src = "Title: A [cloud] -> B [diamond] -> C [rectangle]"
        result = _convert_inline_chain(src)
        assert "direction: right" in result
        assert '"A"' in result
        assert '"B"' in result
        assert "shape: cloud" in result
        assert "shape: diamond" in result
        assert "->" in result

    def test_handles_chain_without_title(self):
        src = "Health Monitor [circle] -> Problem Detection [diamond] -> Auto Fix [step]"
        result = _convert_inline_chain(src)
        assert "shape: circle" in result
        assert "shape: diamond" in result
        assert "shape: step" in result

    def test_replaces_invalid_shapes_with_rectangle(self):
        src = "A [server] -> B [gear] -> C [cloud]"
        result = _convert_inline_chain(src)
        # server and gear are invalid, should become rectangle
        assert "shape: cloud" in result
        lines = result.split("\n")
        rect_count = sum(1 for l in lines if "shape: rectangle" in l)
        assert rect_count == 2

    def test_passthrough_when_multiline(self):
        src = "A: {\n  shape: rectangle\n}\nB: {\n  shape: cloud\n}\nA -> B"
        result = _convert_inline_chain(src)
        assert result == src  # Should not modify multi-line D2

    def test_passthrough_when_no_brackets(self):
        src = "direction: right\nA -> B -> C"
        result = _convert_inline_chain(src)
        assert result == src

    def test_real_llm_output(self):
        """Test with actual LLM-generated D2 that was causing failures."""
        src = (
            "ADHD Executive Function Support: ADHD Challenges [cloud] -> "
            "Task Initiation Difficulty [diamond] -> Working Memory Limits [diamond] -> "
            "System Solutions [rectangle] -> Automatic Daily Briefings [document]"
        )
        result = _convert_inline_chain(src)
        assert "direction: right" in result
        assert "shape: cloud" in result
        assert "shape: diamond" in result
        assert "shape: document" in result
        # Should have proper node -> node edges
        assert "->" in result


class TestSanitizeD2Source:
    def test_strips_invalid_shapes(self):
        src = "MyNode: {\n  shape: server\n}"
        result = sanitize_d2_source(src)
        assert "shape: server" not in result

    def test_keeps_valid_shapes(self):
        src = "MyNode: {\n  shape: cylinder\n}"
        result = sanitize_d2_source(src)
        assert "shape: cylinder" in result

    def test_strips_inline_styles(self):
        src = "style.fill: red\nstyle.stroke: blue\nMyNode"
        result = sanitize_d2_source(src)
        assert "style.fill" not in result
        assert "MyNode" in result

    def test_quotes_labels_with_parens(self):
        src = "api: API Gateway (REST)"
        result = sanitize_d2_source(src)
        assert '"API Gateway (REST)"' in result

    def test_quotes_labels_with_colons(self):
        src = "monitor: Health Monitor: 77 checks"
        result = sanitize_d2_source(src)
        assert '"Health Monitor: 77 checks"' in result

    def test_leaves_already_quoted_labels(self):
        src = 'api: "API Gateway"'
        result = sanitize_d2_source(src)
        assert 'api: "API Gateway"' in result

    def test_leaves_braced_values(self):
        src = "api: {\n  shape: rectangle\n}"
        result = sanitize_d2_source(src)
        assert "api: {" in result

    def test_doesnt_quote_block_opening(self):
        """Node definitions with trailing { should not have the { quoted."""
        src = "profile_store: Profile Store {\n  shape: cylinder\n}"
        result = sanitize_d2_source(src)
        assert "Profile Store {" in result
        assert '"Profile Store {"' not in result

    def test_doesnt_quote_keywords(self):
        src = "direction: right"
        result = sanitize_d2_source(src)
        assert "direction: right" in result

    def test_strips_markdown_fences(self):
        src = "```d2\nA -> B\n```"
        result = sanitize_d2_source(src)
        assert "```" not in result
        assert "A -> B" in result

    def test_strips_plain_markdown_fences(self):
        src = "```\nA -> B\n```"
        result = sanitize_d2_source(src)
        assert "```" not in result

    def test_preserves_edges(self):
        src = "A -> B\nB -> C"
        result = sanitize_d2_source(src)
        assert "A -> B" in result
        assert "B -> C" in result

    def test_strips_near_object_reference(self):
        """near: OtherNode (dynamic ref) should be stripped for ELK layout."""
        src = "MyNode: {\n  shape: text\n  near: OtherNode\n}"
        result = sanitize_d2_source(src)
        assert "near:" not in result

    def test_keeps_near_constant_value(self):
        """near: top-center (constant) is valid in ELK."""
        src = "MyLabel: {\n  shape: text\n  near: top-center\n}"
        result = sanitize_d2_source(src)
        assert "near: top-center" in result

    def test_strips_stroke_dash(self):
        src = "style.stroke-dash: 5\nMyNode"
        result = sanitize_d2_source(src)
        assert "style.stroke-dash" not in result

    def test_strips_incomplete_connection_missing_dest(self):
        """Lines like 'X ->' with no destination should be stripped."""
        src = "A -> B\nC ->\nD -> E"
        result = sanitize_d2_source(src)
        assert "A -> B" in result
        assert "D -> E" in result
        assert "C ->" not in result

    def test_strips_incomplete_connection_missing_src(self):
        """Lines like '-> Y' with no source should be stripped."""
        src = "A -> B\n-> C\nD -> E"
        result = sanitize_d2_source(src)
        assert "A -> B" in result
        assert "D -> E" in result
        lines = [l.strip() for l in result.split("\n") if l.strip()]
        assert not any(l.startswith("->") for l in lines)


class TestExpandSemicolons:
    def test_expands_inline_properties(self):
        src = "litellm: LiteLLM Gateway {shape: hexagon; style: {fill: #E8F8F5}}"
        result = _expand_semicolons(src)
        assert "shape: hexagon" in result
        # Style block should be expanded
        assert ";" not in result

    def test_passthrough_no_semicolons(self):
        src = "A: {\n  shape: rectangle\n}"
        result = _expand_semicolons(src)
        assert result == src


class TestStripStyleBlocks:
    def test_strips_multiline_style_block(self):
        src = "MyNode: {\n  shape: rectangle\n  style: {\n    fill: red\n    stroke: blue\n  }\n}"
        result = _strip_style_blocks(src)
        assert "shape: rectangle" in result
        assert "fill" not in result
        assert "stroke" not in result

    def test_strips_inline_style_block(self):
        src = 'MyNode: {\n  shape: circle\n  style: {fill: "#abc"}\n}'
        result = _strip_style_blocks(src)
        assert "shape: circle" in result
        assert "fill" not in result

    def test_strips_style_dot_properties(self):
        src = "style.fill: red\nstyle.stroke: blue\nstyle.border-radius: 8\nMyNode"
        result = _strip_style_blocks(src)
        assert "MyNode" in result
        assert "style." not in result

    def test_preserves_non_style_content(self):
        src = "A: {\n  shape: rectangle\n}\nA -> B"
        result = _strip_style_blocks(src)
        assert "shape: rectangle" in result
        assert "A -> B" in result


class TestBracketShapeSyntax:
    def test_converts_bracket_shape_with_label(self):
        """LLMs generate 'id [shape: X]: Label' which is invalid D2."""
        src = "profile_extraction [shape: rectangle]: Profile Extractor"
        result = sanitize_d2_source(src)
        assert '"Profile Extractor"' in result
        assert "shape: rectangle" in result
        assert "[shape:" not in result

    def test_converts_bracket_shape_only(self):
        src = "tier1 [shape: hexagon]"
        result = sanitize_d2_source(src)
        assert "shape: hexagon" in result
        assert "[shape:" not in result

    def test_replaces_invalid_shape_in_brackets(self):
        src = "mynode [shape: server]: My Server"
        result = sanitize_d2_source(src)
        assert "shape: rectangle" in result
        assert "shape: server" not in result

    def test_preserves_edges_after_bracket_conversion(self):
        src = "a [shape: rectangle]: Node A\nb [shape: cloud]: Node B\na -> b"
        result = sanitize_d2_source(src)
        assert "-> b" in result  # Edge preserved (source may be renamed)
        assert "shape: rectangle" in result
        assert "shape: cloud" in result
        assert "[shape:" not in result


class TestSanitizeDotNotation:
    def test_strips_dot_property_in_edges(self):
        """Dot-notation like Node.property -> Target causes D2 substitution errors."""
        src = "Router -> Target\nRouter.balanced -> Claude Sonnet: complex reasoning"
        result = sanitize_d2_source(src)
        assert "Router -> Target" in result
        assert "Router -> Claude Sonnet" in result
        assert ".balanced" not in result

    def test_preserves_normal_edges(self):
        src = "A -> B\nB -> C"
        result = sanitize_d2_source(src)
        assert "A -> B" in result
        assert "B -> C" in result


class TestSanitizeStyleStripping:
    """Integration tests for style stripping in full sanitizer."""

    def test_strips_inline_semicolon_styles(self):
        """LLM-generated D2 with inline semicolons and styles."""
        src = "litellm: LiteLLM Gateway:4000 {shape: hexagon; style: {fill: #E8F8F5}}"
        result = sanitize_d2_source(src)
        assert "shape: hexagon" in result
        assert "fill" not in result
        assert "#E8F8F5" not in result

    def test_strips_complex_style_blocks(self):
        """Complex nested style blocks from real LLM output."""
        src = (
            "internet: Internet {shape: cloud; style: {fill: #FEE2E2; stroke: red; stroke-width: 2}}\n"
            "internet -> server"
        )
        result = sanitize_d2_source(src)
        assert "shape: cloud" in result
        assert "internet -> server" in result
        assert "fill" not in result
        assert "stroke" not in result

    def test_full_llm_diagram_sanitizes(self):
        """Real LLM output that was causing 'missing value after colon'."""
        src = (
            "direction: right\n"
            "litellm: LiteLLM Gateway:4000 {shape: hexagon; style: {fill: #DBEAFE}}\n"
            "langfuse: Langfuse:3000 {shape: rectangle; style: {fill: #FDF2F8}}\n"
            "qdrant: Qdrant:6333 {shape: cylinder; style: {fill: #F0FDF4}}\n"
            "litellm -> langfuse\n"
            "litellm -> qdrant"
        )
        result = sanitize_d2_source(src)
        assert "direction: right" in result
        assert "shape: hexagon" in result
        assert "shape: cylinder" in result
        assert "litellm -> langfuse" in result
        # Port numbers in labels should be quoted
        assert '"LiteLLM Gateway:4000"' in result
        assert "fill" not in result

    def test_strips_freetext_routing_tables(self):
        """LLM-generated routing table text inside braces."""
        src = (
            "routing: Model Routing Logic {\n"
            "  'fast' → Claude Haiku\n"
            "  'balanced' → Claude Sonnet\n"
            "}"
        )
        result = sanitize_d2_source(src)
        # Free-text lines should be stripped
        assert "→" not in result


class TestSimplifyD2:
    def test_extracts_edges(self):
        result = _simplify_d2("A -> B\nB -> C")
        # Node IDs are lowercased for D2 compatibility
        assert "a -> b" in result
        assert "b -> c" in result

    def test_extracts_inline_labels(self):
        result = _simplify_d2('api: "API Gateway"\ndb: "Database"')
        assert "API Gateway" in result
        assert "Database" in result

    def test_preserves_direction(self):
        result = _simplify_d2("direction: right\nA -> B")
        assert "direction: right" in result

    def test_skips_comments(self):
        result = _simplify_d2("# comment\nA -> B")
        assert "comment" not in result
        assert "a -> b" in result

    def test_multi_word_edges(self):
        """Multi-word node names in edges should be handled."""
        result = _simplify_d2(
            "Corporate Data -> Axiom Governance\nAxiom Governance -> Decision Support"
        )
        assert "corporate_data -> axiom_governance" in result
        assert "axiom_governance -> decision_support" in result
        # Nodes should be extracted with original labels
        assert '"Corporate Data"' in result
        assert '"Axiom Governance"' in result


class TestExtractNodesAndEdges:
    def test_extracts_structure(self):
        src = "A: {\n  shape: rectangle\n}\nB: {\n  shape: cylinder\n}\nA -> B"
        nodes, edges = _extract_nodes_and_edges(src)
        assert len(nodes) >= 2
        assert len(edges) == 1

    def test_empty_source(self):
        nodes, edges = _extract_nodes_and_edges("")
        assert nodes == []
        assert edges == []


class TestFallbackDiagram:
    def test_generates_png(self, tmp_path: Path):
        out = tmp_path / "diagram.png"
        result = _fallback_diagram("A -> B -> C", out, (800, 600))
        assert result.exists()
        assert result.suffix == ".png"

    def test_empty_source_fallback(self, tmp_path: Path):
        out = tmp_path / "empty.png"
        result = _fallback_diagram("", out, (800, 600))
        assert result.exists()

    def test_many_nodes(self, tmp_path: Path):
        src = "\n".join(f"Node{i}: {{\n  shape: rectangle\n}}" for i in range(10))
        out = tmp_path / "many.png"
        result = _fallback_diagram(src, out, (1920, 1080))
        assert result.exists()
