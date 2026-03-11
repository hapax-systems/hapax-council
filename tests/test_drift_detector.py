"""Tests for drift_detector — schemas, formatters, fix logic.

All I/O is mocked. No real LLM calls, filesystem reads, or subprocess calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.drift_detector import (
    REGISTRY_CATEGORIES,
    DocFix,
    DriftItem,
    DriftReport,
    FixReport,
    _build_fix_context,
    detect_drift,
    format_fixes,
    format_human,
    generate_fixes,
    load_docs,
)

# ── Schema tests ─────────────────────────────────────────────────────────────


class TestDriftItem:
    def test_required_fields(self):
        item = DriftItem(
            severity="high",
            category="stale_reference",
            doc_file="~/CLAUDE.md",
            doc_claim="LibreChat on port 3080",
            reality="Open WebUI on port 3080",
            suggestion="Replace LibreChat with Open WebUI",
        )
        assert item.severity == "high"
        assert item.category == "stale_reference"
        assert item.doc_file == "~/CLAUDE.md"

    def test_all_severity_levels(self):
        for sev in ("high", "medium", "low"):
            item = DriftItem(
                severity=sev,
                category="test",
                doc_file="x",
                doc_claim="a",
                reality="b",
                suggestion="c",
            )
            assert item.severity == sev

    def test_json_round_trip(self):
        item = DriftItem(
            severity="medium",
            category="wrong_port",
            doc_file="~/docs.md",
            doc_claim="port 3000",
            reality="port 3080",
            suggestion="Update port",
        )
        data = item.model_dump()
        restored = DriftItem(**data)
        assert restored == item


class TestDriftReport:
    def test_empty_report(self):
        report = DriftReport(
            drift_items=[],
            docs_analyzed=[],
            summary="No drift.",
        )
        assert len(report.drift_items) == 0
        assert report.summary == "No drift."

    def test_defaults(self):
        report = DriftReport(summary="test")
        assert report.drift_items == []
        assert report.docs_analyzed == []

    def test_with_items(self):
        items = [
            DriftItem(
                severity="high",
                category="missing_service",
                doc_file="~/CLAUDE.md",
                doc_claim="MongoDB listed",
                reality="MongoDB not running",
                suggestion="Remove from docs",
            ),
            DriftItem(
                severity="low",
                category="config_mismatch",
                doc_file="~/CLAUDE.md",
                doc_claim="curl healthcheck",
                reality="python3 healthcheck",
                suggestion="Update",
            ),
        ]
        report = DriftReport(
            drift_items=items,
            docs_analyzed=["~/CLAUDE.md"],
            summary="2 items found",
        )
        assert len(report.drift_items) == 2
        assert report.docs_analyzed == ["~/CLAUDE.md"]

    def test_json_round_trip(self):
        report = DriftReport(
            drift_items=[
                DriftItem(
                    severity="high",
                    category="stale_reference",
                    doc_file="a.md",
                    doc_claim="old",
                    reality="new",
                    suggestion="fix",
                ),
            ],
            docs_analyzed=["a.md"],
            summary="1 item",
        )
        json_str = report.model_dump_json()
        restored = DriftReport.model_validate_json(json_str)
        assert restored == report


class TestDocFix:
    def test_required_fields(self):
        fix = DocFix(
            doc_file="~/CLAUDE.md",
            section_title="Service Topology",
            original="| LibreChat | librechat |",
            corrected="| Open WebUI | open-webui |",
            explanation="LibreChat was replaced by Open WebUI",
        )
        assert fix.doc_file == "~/CLAUDE.md"
        assert "LibreChat" in fix.original
        assert "Open WebUI" in fix.corrected


class TestFixReport:
    def test_empty(self):
        report = FixReport(fixes=[], summary="No fixes")
        assert len(report.fixes) == 0

    def test_defaults(self):
        report = FixReport(summary="test")
        assert report.fixes == []

    def test_with_fixes(self):
        report = FixReport(
            fixes=[
                DocFix(
                    doc_file="a.md",
                    section_title="s",
                    original="old",
                    corrected="new",
                    explanation="e",
                ),
            ],
            summary="1 fix",
        )
        assert len(report.fixes) == 1


# ── format_human tests ───────────────────────────────────────────────────────


class TestFormatHuman:
    def test_empty_report(self):
        report = DriftReport(
            drift_items=[],
            docs_analyzed=["~/CLAUDE.md"],
            summary="All clean.",
        )
        output = format_human(report)
        assert "No drift detected" in output
        assert "All clean." in output
        assert "~/CLAUDE.md" in output

    def test_severity_ordering(self):
        """High-severity items should appear before medium and low."""
        items = [
            DriftItem(
                severity="low",
                category="c",
                doc_file="a",
                doc_claim="x",
                reality="y",
                suggestion="z",
            ),
            DriftItem(
                severity="high",
                category="c",
                doc_file="a",
                doc_claim="x",
                reality="y",
                suggestion="z",
            ),
            DriftItem(
                severity="medium",
                category="c",
                doc_file="a",
                doc_claim="x",
                reality="y",
                suggestion="z",
            ),
        ]
        report = DriftReport(drift_items=items, docs_analyzed=["a"], summary="s")
        output = format_human(report)
        lines = output.splitlines()
        # Find severity icon positions
        icon_lines = [l for l in lines if l.startswith("[")]
        assert icon_lines[0].startswith("[!!]")  # high first
        assert icon_lines[1].startswith("[! ]")  # medium second
        assert icon_lines[2].startswith("[ .]")  # low third

    def test_severity_counts(self):
        items = [
            DriftItem(
                severity="high",
                category="c",
                doc_file="a",
                doc_claim="x",
                reality="y",
                suggestion="z",
            ),
            DriftItem(
                severity="high",
                category="c",
                doc_file="a",
                doc_claim="x",
                reality="y",
                suggestion="z",
            ),
            DriftItem(
                severity="medium",
                category="c",
                doc_file="a",
                doc_claim="x",
                reality="y",
                suggestion="z",
            ),
        ]
        report = DriftReport(drift_items=items, docs_analyzed=["a"], summary="s")
        output = format_human(report)
        assert "3 items" in output
        assert "2 high" in output
        assert "1 medium" in output
        assert "0 low" in output

    def test_item_details_rendered(self):
        items = [
            DriftItem(
                severity="high",
                category="missing_service",
                doc_file="~/CLAUDE.md",
                doc_claim="MongoDB listed",
                reality="MongoDB not running",
                suggestion="Remove it",
            ),
        ]
        report = DriftReport(drift_items=items, docs_analyzed=["~/CLAUDE.md"], summary="drift")
        output = format_human(report)
        assert "missing_service" in output
        assert "Doc says:" in output
        assert "MongoDB listed" in output
        assert "Reality:" in output
        assert "MongoDB not running" in output
        assert "Fix:" in output
        assert "Remove it" in output

    def test_unknown_severity_icon(self):
        items = [
            DriftItem(
                severity="critical",
                category="c",
                doc_file="a",
                doc_claim="x",
                reality="y",
                suggestion="z",
            ),
        ]
        report = DriftReport(drift_items=items, docs_analyzed=["a"], summary="s")
        output = format_human(report)
        assert "[??]" in output


# ── format_fixes tests ───────────────────────────────────────────────────────


class TestFormatFixes:
    def test_no_fixes(self):
        report = FixReport(fixes=[], summary="Nothing to fix")
        output = format_fixes(report)
        assert output == "No fixes to apply."

    def test_with_fixes(self):
        report = FixReport(
            fixes=[
                DocFix(
                    doc_file="~/CLAUDE.md",
                    section_title="Services",
                    original="| LibreChat | 3080 |",
                    corrected="| Open WebUI | 3080 |",
                    explanation="LibreChat replaced",
                ),
            ],
            summary="1 fix across 1 file",
        )
        output = format_fixes(report)
        assert "Proposed Fixes (1 changes)" in output
        assert "--- ~/CLAUDE.md" in output
        assert "Section: Services" in output
        assert "Reason: LibreChat replaced" in output
        assert "- | LibreChat | 3080 |" in output
        assert "+ | Open WebUI | 3080 |" in output
        assert "To apply:" in output

    def test_multiline_fix(self):
        report = FixReport(
            fixes=[
                DocFix(
                    doc_file="a.md",
                    section_title="s",
                    original="line1\nline2",
                    corrected="new1\nnew2\nnew3",
                    explanation="expanded",
                ),
            ],
            summary="1 fix",
        )
        output = format_fixes(report)
        assert "- line1" in output
        assert "- line2" in output
        assert "+ new1" in output
        assert "+ new2" in output
        assert "+ new3" in output


# ── generate_fixes tests ────────────────────────────────────────────────────


class TestGenerateFixes:
    @pytest.mark.asyncio
    async def test_no_actionable_items(self):
        """Low-severity only → no fixes generated, no LLM call."""
        report = DriftReport(
            drift_items=[
                DriftItem(
                    severity="low",
                    category="c",
                    doc_file="a.md",
                    doc_claim="x",
                    reality="y",
                    suggestion="z",
                ),
            ],
            docs_analyzed=["a.md"],
            summary="low only",
        )
        result = await generate_fixes(report, {"a.md": "content"})
        assert result.fixes == []
        assert "No high/medium" in result.summary

    @pytest.mark.asyncio
    async def test_empty_drift_items(self):
        report = DriftReport(drift_items=[], docs_analyzed=[], summary="clean")
        result = await generate_fixes(report, {})
        assert result.fixes == []

    @pytest.mark.asyncio
    async def test_skips_missing_doc_content(self):
        """If doc content is not in the docs dict, skip that file."""
        report = DriftReport(
            drift_items=[
                DriftItem(
                    severity="high",
                    category="c",
                    doc_file="missing.md",
                    doc_claim="x",
                    reality="y",
                    suggestion="z",
                ),
            ],
            docs_analyzed=["missing.md"],
            summary="missing file",
        )
        # docs dict doesn't contain "missing.md"
        result = await generate_fixes(report, {})
        assert result.fixes == []

    @pytest.mark.asyncio
    async def test_groups_by_file(self):
        """Items for the same file should be grouped into one LLM call."""
        mock_fix = FixReport(
            fixes=[
                DocFix(
                    doc_file="a.md", section_title="s", original="o", corrected="c", explanation="e"
                )
            ],
            summary="1 fix",
        )
        mock_result = MagicMock()
        mock_result.output = mock_fix

        report = DriftReport(
            drift_items=[
                DriftItem(
                    severity="high",
                    category="c1",
                    doc_file="a.md",
                    doc_claim="x1",
                    reality="y1",
                    suggestion="z1",
                ),
                DriftItem(
                    severity="medium",
                    category="c2",
                    doc_file="a.md",
                    doc_claim="x2",
                    reality="y2",
                    suggestion="z2",
                ),
                DriftItem(
                    severity="high",
                    category="c3",
                    doc_file="b.md",
                    doc_claim="x3",
                    reality="y3",
                    suggestion="z3",
                ),
            ],
            docs_analyzed=["a.md", "b.md"],
            summary="mixed",
        )
        docs = {"a.md": "content A", "b.md": "content B"}

        with patch("agents.drift_detector.fix_agent") as mock_agent:
            mock_agent.run = AsyncMock(return_value=mock_result)
            result = await generate_fixes(report, docs)

        # Should be called twice — once per unique doc file
        assert mock_agent.run.call_count == 2
        assert "2 files" in result.summary

    @pytest.mark.asyncio
    async def test_filters_low_severity(self):
        """Only high and medium items get fixes."""
        mock_fix = FixReport(fixes=[], summary="empty")
        mock_result = MagicMock()
        mock_result.output = mock_fix

        report = DriftReport(
            drift_items=[
                DriftItem(
                    severity="high",
                    category="c",
                    doc_file="a.md",
                    doc_claim="x",
                    reality="y",
                    suggestion="z",
                ),
                DriftItem(
                    severity="low",
                    category="c",
                    doc_file="a.md",
                    doc_claim="x",
                    reality="y",
                    suggestion="z",
                ),
            ],
            docs_analyzed=["a.md"],
            summary="mixed",
        )

        with patch("agents.drift_detector.fix_agent") as mock_agent:
            mock_agent.run = AsyncMock(return_value=mock_result)
            await generate_fixes(report, {"a.md": "content"})

        # Only one call — the low-severity item was filtered
        assert mock_agent.run.call_count == 1
        # Verify the prompt only includes the high-severity item
        call_prompt = mock_agent.run.call_args[0][0]
        assert "[high]" in call_prompt
        assert "[low]" not in call_prompt


# ── fix agent configuration tests ───────────────────────────────────────────


class TestFixAgentConfiguration:
    def test_fix_agent_has_context_tools(self):
        """Fix agent should have operator context tools registered."""
        from agents.drift_detector import fix_agent

        # pydantic-ai agents store tools — verify context tools are present
        tool_names = set(fix_agent._function_toolset.tools.keys())
        assert "lookup_constraints" in tool_names
        assert "lookup_patterns" in tool_names

    def test_fix_agent_system_prompt_mentions_context_tools(self):
        """System prompt should guide the fix agent on when to use tools."""
        from agents.drift_detector import FIX_SYSTEM_PROMPT

        assert "lookup_constraints" in FIX_SYSTEM_PROMPT
        assert "lookup_patterns" in FIX_SYSTEM_PROMPT
        assert "CONTEXT TOOLS" in FIX_SYSTEM_PROMPT


# ── fix context tests ───────────────────────────────────────────────────────


class TestBuildFixContext:
    def test_no_context_for_non_registry_items(self):
        """Non-registry categories produce no context block."""
        items = [
            DriftItem(
                severity="high",
                category="stale_reference",
                doc_file="a.md",
                doc_claim="x",
                reality="y",
                suggestion="z",
            )
        ]
        result = _build_fix_context("a.md", items)
        assert result == ""

    def test_returns_context_for_registry_categories(self):
        """Registry categories trigger context generation with archetype details."""
        from shared.document_registry import Archetype, DocumentRegistry, RepoDeclaration

        items = [
            DriftItem(
                severity="medium",
                category="missing-section",
                doc_file="test-repo/CLAUDE.md",
                doc_claim="x",
                reality="y",
                suggestion="z",
            )
        ]
        registry = DocumentRegistry(
            version=1,
            archetypes={
                "project-context": Archetype(
                    description="Per-repo working context",
                    required_sections=["## Project Memory", "## Conventions"],
                    composite=True,
                )
            },
            repos={
                "test-repo": RepoDeclaration(
                    path="~/projects/test-repo",
                    required_docs=[{"path": "CLAUDE.md", "archetype": "project-context"}],
                )
            },
        )

        result = _build_fix_context("test-repo/CLAUDE.md", items, registry=registry)
        assert "project-context" in result
        assert "Per-repo working context" in result
        assert "## Project Memory" in result
        assert "composite" in result.lower()
        assert "test-repo" in result

    def test_single_purpose_archetype(self):
        """Non-composite archetypes are described as single-purpose."""
        from shared.document_registry import Archetype, DocumentRegistry, RepoDeclaration

        items = [
            DriftItem(
                severity="medium",
                category="missing-section",
                doc_file="repo/spec.md",
                doc_claim="x",
                reality="y",
                suggestion="z",
            )
        ]
        registry = DocumentRegistry(
            version=1,
            archetypes={
                "specification": Archetype(
                    description="Architectural design",
                    required_sections=["## Architecture"],
                    composite=False,
                )
            },
            repos={
                "repo": RepoDeclaration(
                    path="~/projects/repo",
                    required_docs=[{"path": "spec.md", "archetype": "specification"}],
                )
            },
        )

        result = _build_fix_context("repo/spec.md", items, registry=registry)
        assert "single-purpose" in result

    def test_coverage_gap_includes_rule_context(self):
        """Coverage-gap items get coverage rule details in context."""
        from shared.document_registry import CoverageRule, DocumentRegistry

        items = [
            DriftItem(
                severity="medium",
                category="coverage-gap",
                doc_file="~/projects/hapax-system/rules/system-context.md",
                doc_claim="agents in system-context",
                reality="agent 'foo' not found",
                suggestion="Add 'foo' to system-context.md",
            )
        ]
        registry = DocumentRegistry(
            version=1,
            coverage_rules=[
                CoverageRule(
                    ci_type="agent",
                    reference_doc="~/projects/hapax-system/rules/system-context.md",
                    reference_section="## Management Agents",
                    match_by="name",
                    severity="medium",
                    description="Every agent module must have a row in system-context.md",
                )
            ],
        )

        result = _build_fix_context(
            "~/projects/hapax-system/rules/system-context.md", items, registry=registry
        )
        assert "Coverage context" in result
        assert "Management Agents" in result
        assert "Every agent module" in result

    def test_no_coverage_context_for_non_coverage_items(self):
        """Non-coverage-gap registry items don't get coverage rule details."""
        from shared.document_registry import CoverageRule, DocumentRegistry

        items = [
            DriftItem(
                severity="medium",
                category="missing-section",
                doc_file="a.md",
                doc_claim="x",
                reality="y",
                suggestion="z",
            )
        ]
        registry = DocumentRegistry(
            version=1,
            coverage_rules=[
                CoverageRule(
                    ci_type="agent",
                    reference_doc="a.md",
                    reference_section="## Agents",
                    match_by="name",
                    severity="medium",
                    description="test",
                )
            ],
        )

        result = _build_fix_context("a.md", items, registry=registry)
        assert "Coverage context" not in result

    def test_registry_categories_constant(self):
        """Verify REGISTRY_CATEGORIES contains expected categories."""
        expected = {
            "missing-required-doc",
            "missing-section",
            "coverage-gap",
            "repo-awareness-gap",
            "spec-reference-gap",
            "boundary-mismatch",
        }
        assert expected == REGISTRY_CATEGORIES

    @pytest.mark.asyncio
    async def test_generate_fixes_injects_registry_context(self):
        """generate_fixes includes registry context in prompt for registry items."""
        mock_fix = FixReport(fixes=[], summary="empty")
        mock_result = MagicMock()
        mock_result.output = mock_fix

        report = DriftReport(
            drift_items=[
                DriftItem(
                    severity="medium",
                    category="missing-section",
                    doc_file="a.md",
                    doc_claim="x",
                    reality="y",
                    suggestion="z",
                ),
            ],
            docs_analyzed=["a.md"],
            summary="registry drift",
        )

        with (
            patch("agents.drift_detector.fix_agent") as mock_agent,
            patch(
                "agents.drift_detector._build_fix_context",
                return_value="## Document context\n- Archetype: project-context",
            ),
        ):
            mock_agent.run = AsyncMock(return_value=mock_result)
            await generate_fixes(report, {"a.md": "content"})

        call_prompt = mock_agent.run.call_args[0][0]
        assert "Document context" in call_prompt
        assert "project-context" in call_prompt


# ── detect_drift tests ──────────────────────────────────────────────────────


class TestDetectDrift:
    @pytest.mark.asyncio
    async def test_no_docs_returns_empty(self):
        """If no documentation files found, returns empty report."""
        with patch("agents.drift_detector.load_docs", return_value={}):
            report = await detect_drift(manifest=MagicMock())
        assert report.drift_items == []
        assert "No documentation" in report.summary

    @pytest.mark.asyncio
    async def test_passes_manifest_and_docs_to_agent(self):
        mock_manifest = MagicMock()
        mock_manifest.model_dump_json.return_value = '{"test": true}'

        mock_report = DriftReport(drift_items=[], docs_analyzed=[], summary="clean")
        mock_result = MagicMock()
        mock_result.output = mock_report

        docs = {"~/CLAUDE.md": "# Some documentation content"}
        with (
            patch("agents.drift_detector.load_docs", return_value=docs),
            patch("agents.drift_detector.drift_agent") as mock_agent,
        ):
            mock_agent.run = AsyncMock(return_value=mock_result)
            report = await detect_drift(manifest=mock_manifest)

        # Agent was called with prompt containing manifest + docs
        call_prompt = mock_agent.run.call_args[0][0]
        assert '{"test": true}' in call_prompt
        assert "Some documentation content" in call_prompt
        # docs_analyzed gets populated from the loaded docs
        assert report.docs_analyzed == ["~/CLAUDE.md"]

    @pytest.mark.asyncio
    async def test_truncates_long_docs(self):
        mock_manifest = MagicMock()
        mock_manifest.model_dump_json.return_value = "{}"

        mock_result = MagicMock()
        mock_result.output = DriftReport(drift_items=[], docs_analyzed=[], summary="ok")

        long_doc = "x" * 10000
        with (
            patch("agents.drift_detector.load_docs", return_value={"big.md": long_doc}),
            patch("agents.drift_detector.drift_agent") as mock_agent,
        ):
            mock_agent.run = AsyncMock(return_value=mock_result)
            await detect_drift(manifest=mock_manifest)

        call_prompt = mock_agent.run.call_args[0][0]
        assert "[... truncated ...]" in call_prompt

    @pytest.mark.asyncio
    async def test_generates_manifest_if_none(self):
        """If no manifest passed, it calls generate_manifest()."""
        mock_manifest = MagicMock()
        mock_manifest.model_dump_json.return_value = "{}"

        mock_result = MagicMock()
        mock_result.output = DriftReport(drift_items=[], docs_analyzed=[], summary="ok")

        with (
            patch("agents.drift_detector.load_docs", return_value={"a.md": "test"}),
            patch("agents.drift_detector.drift_agent") as mock_agent,
            patch(
                "agents.drift_detector.generate_manifest",
                new_callable=AsyncMock,
                return_value=mock_manifest,
            ),
        ):
            mock_agent.run = AsyncMock(return_value=mock_result)
            await detect_drift(manifest=None)

        # Agent was called (manifest was generated)
        assert mock_agent.run.called


# ── load_docs tests ──────────────────────────────────────────────────────────


class TestLoadDocs:
    def test_returns_dict(self):
        """load_docs returns a dict (may be empty if files not found)."""
        result = load_docs()
        assert isinstance(result, dict)
        # Values should be strings
        for path, content in result.items():
            assert isinstance(path, str)
            assert isinstance(content, str)

    def test_paths_shortened(self):
        """Paths in the result should use ~ instead of full home path."""
        result = load_docs()
        for path in result:
            assert not path.startswith("/home/"), f"Path should be shortened: {path}"


class TestAxiomDriftIntegration:
    def test_drift_item_axiom_category(self):
        item = DriftItem(
            severity="high",
            category="axiom-violation",
            doc_file="axioms/registry.yaml",
            doc_claim="single_user axiom: no multi-user auth",
            reality="OAuth2 with user management found",
            suggestion="Remove multi-user auth or justify as single-user protection",
        )
        assert item.category == "axiom-violation"
        assert item.severity == "high"
