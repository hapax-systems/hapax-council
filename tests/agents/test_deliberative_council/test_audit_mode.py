from __future__ import annotations

from pathlib import Path

import pytest

from agents.deliberative_council.models import ConvergenceStatus
from agents.deliberative_council.modes.audit import (
    AuditClaim,
    AuditFileReport,
    AuditSweepReport,
    discover_artifacts,
    extract_claims,
    run_audit_sweep,
)
from agents.deliberative_council.modes.disconfirmation import (
    DisconfirmationReceipt,
    DisconfirmationRecommendation,
    DisconfirmationVerdict,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _stub_receipt(claim: AuditClaim, verdict: DisconfirmationVerdict) -> DisconfirmationReceipt:
    if verdict == DisconfirmationVerdict.SURVIVED:
        return DisconfirmationReceipt(
            claim=claim.text,
            source_refs=(claim.source_path,),
            verdict=verdict,
            recommendation=DisconfirmationRecommendation.ACCEPT,
            attacks_attempted=("axis: probe",),
            attacks_survived=("axis: held",),
            convergence_status=ConvergenceStatus.CONVERGED,
        )
    if verdict == DisconfirmationVerdict.REFUTED:
        return DisconfirmationReceipt(
            claim=claim.text,
            source_refs=(claim.source_path,),
            verdict=verdict,
            recommendation=DisconfirmationRecommendation.RETRACT,
            evidence_against=("counter-evidence",),
            counter_arguments=("adversarial challenge",),
            convergence_status=ConvergenceStatus.CONVERGED,
        )
    if verdict == DisconfirmationVerdict.CONTESTED:
        return DisconfirmationReceipt(
            claim=claim.text,
            source_refs=(claim.source_path,),
            verdict=verdict,
            recommendation=DisconfirmationRecommendation.NARROW,
            convergence_status=ConvergenceStatus.CONTESTED,
        )
    return DisconfirmationReceipt(
        claim=claim.text,
        source_refs=(claim.source_path,),
        verdict=DisconfirmationVerdict.INSUFFICIENT_EVIDENCE,
        recommendation=DisconfirmationRecommendation.REVISE,
        convergence_status=ConvergenceStatus.HUNG,
    )


class TestSweepDiscoversResearchArtifacts:
    def test_discovers_all_markdown_recursively(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.md", "# a")
        _write(tmp_path / "sub" / "b.md", "# b")
        _write(tmp_path / "sub" / "deeper" / "c.md", "# c")
        _write(tmp_path / "ignore.txt", "ignored")

        artifacts = discover_artifacts(tmp_path)

        assert len(artifacts) == 3
        assert all(p.suffix == ".md" for p in artifacts)
        assert artifacts == sorted(artifacts)

    def test_ignores_non_markdown(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.md", "# a")
        _write(tmp_path / "b.py", "# b")
        _write(tmp_path / "c.rst", "# c")

        artifacts = discover_artifacts(tmp_path)

        assert len(artifacts) == 1
        assert artifacts[0].name == "a.md"

    def test_single_file_scope(self, tmp_path: Path) -> None:
        f = _write(tmp_path / "one.md", "# one")
        assert discover_artifacts(f) == [f]

    def test_single_non_md_file_scope_returns_empty(self, tmp_path: Path) -> None:
        f = _write(tmp_path / "one.txt", "one")
        assert discover_artifacts(f) == []

    def test_missing_scope_returns_empty(self, tmp_path: Path) -> None:
        assert discover_artifacts(tmp_path / "does-not-exist") == []

    @pytest.mark.asyncio
    async def test_sweep_visits_every_artifact(self, tmp_path: Path) -> None:
        _write(tmp_path / "no_claims.md", "Nothing interesting here.")
        _write(tmp_path / "one_claim.md", "This shows that A implies B.")
        _write(tmp_path / "sub" / "two_claims.md", "X proves Y. Z demonstrates W.")

        async def maker(c: AuditClaim) -> DisconfirmationReceipt:
            return _stub_receipt(c, DisconfirmationVerdict.SURVIVED)

        report = await run_audit_sweep(tmp_path, receipt_maker=maker)

        assert report.files_scanned == 3
        assert report.files_with_claims == 2
        assert report.total_claims == 3
        assert {fr.source_path for fr in report.file_reports} == {
            str(tmp_path / "no_claims.md"),
            str(tmp_path / "one_claim.md"),
            str(tmp_path / "sub" / "two_claims.md"),
        }


class TestSweepExtractsClaimsFromMarkdown:
    def test_extracts_each_canonical_claim_verb(self, tmp_path: Path) -> None:
        f = _write(
            tmp_path / "claims.md",
            "Result A demonstrates X.\n"
            "Result B establishes Y.\n"
            "Result C proves Z.\n"
            "Result D shows Q.\n"
            "Result E confirms R.\n"
            "Result F validates S.\n",
        )
        claims = extract_claims(f)
        verbs = {c.verb for c in claims}
        assert verbs == {
            "demonstrates",
            "establishes",
            "proves",
            "shows",
            "confirms",
            "validates",
        }
        assert all(c.line_number >= 1 for c in claims)
        assert all(c.source_path == str(f) for c in claims)

    def test_extracts_case_insensitive(self, tmp_path: Path) -> None:
        f = _write(tmp_path / "case.md", "It DEMONSTRATES the point.")
        claims = extract_claims(f)
        assert len(claims) == 1
        assert claims[0].verb == "demonstrates"

    def test_skips_fenced_code_blocks(self, tmp_path: Path) -> None:
        f = _write(
            tmp_path / "fenced.md",
            "Prose says A shows B.\n\n```python\nprint('shows is in code')\n```\n",
        )
        claims = extract_claims(f)
        assert len(claims) == 1
        assert "code" not in claims[0].text

    def test_skips_frontmatter(self, tmp_path: Path) -> None:
        f = _write(
            tmp_path / "fm.md",
            "---\ntitle: 'X demonstrates Y'\n---\n\nThe body proves something.\n",
        )
        claims = extract_claims(f)
        assert len(claims) == 1
        assert claims[0].verb == "proves"

    def test_skips_inline_code(self, tmp_path: Path) -> None:
        f = _write(
            tmp_path / "inline.md",
            "The call `model.shows(x)` is internal. The result demonstrates utility.",
        )
        claims = extract_claims(f)
        verbs = [c.verb for c in claims]
        assert verbs == ["demonstrates"]

    def test_partial_word_matches_do_not_count(self, tmp_path: Path) -> None:
        f = _write(
            tmp_path / "partial.md",
            "The showcase was great. Approved.\n",
        )
        assert extract_claims(f) == []

    def test_strips_list_marker_prefix(self, tmp_path: Path) -> None:
        f = _write(
            tmp_path / "lists.md",
            "- The bench proves throughput is bounded.\n"
            "* The trace shows the hot path.\n"
            "1. The plot demonstrates scaling.\n",
        )
        claims = extract_claims(f)
        verbs = {c.verb for c in claims}
        assert verbs == {"proves", "shows", "demonstrates"}

    def test_returns_empty_when_no_verbs_present(self, tmp_path: Path) -> None:
        f = _write(tmp_path / "boring.md", "This file has no epistemic claims.")
        assert extract_claims(f) == []

    def test_unreadable_file_returns_empty(self, tmp_path: Path) -> None:
        bogus = tmp_path / "missing.md"
        assert extract_claims(bogus) == []


class TestSweepReportStructure:
    @pytest.mark.asyncio
    async def test_report_aggregates_verdict_totals(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "survived.md",
            "A demonstrates B. C shows D.",
        )
        _write(tmp_path / "refuted.md", "X proves Y.")
        _write(tmp_path / "contested.md", "M establishes N.")
        _write(tmp_path / "insufficient.md", "P confirms Q.")

        mapping = {
            str(tmp_path / "survived.md"): DisconfirmationVerdict.SURVIVED,
            str(tmp_path / "refuted.md"): DisconfirmationVerdict.REFUTED,
            str(tmp_path / "contested.md"): DisconfirmationVerdict.CONTESTED,
            str(tmp_path / "insufficient.md"): DisconfirmationVerdict.INSUFFICIENT_EVIDENCE,
        }

        async def maker(c: AuditClaim) -> DisconfirmationReceipt:
            return _stub_receipt(c, mapping[c.source_path])

        report = await run_audit_sweep(tmp_path, receipt_maker=maker)

        assert isinstance(report, AuditSweepReport)
        assert report.scope == str(tmp_path)
        assert report.files_scanned == 4
        assert report.files_with_claims == 4
        assert report.total_claims == 5
        # survived.md produced 2 claims, all survived
        assert report.survived == 2
        assert report.refuted == 1
        assert report.contested == 1
        assert report.insufficient == 1
        # totals reconcile
        assert (
            report.survived + report.contested + report.refuted + report.insufficient
            == report.total_claims
        )

    @pytest.mark.asyncio
    async def test_report_serializes_to_json(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.md", "One demonstrates two.")

        async def maker(c: AuditClaim) -> DisconfirmationReceipt:
            return _stub_receipt(c, DisconfirmationVerdict.SURVIVED)

        report = await run_audit_sweep(tmp_path, receipt_maker=maker)

        data = report.model_dump(mode="json")
        assert {
            "scope",
            "files_scanned",
            "files_with_claims",
            "total_claims",
            "survived",
            "contested",
            "refuted",
            "insufficient",
            "file_reports",
            "generated_at",
        }.issubset(data.keys())
        assert data["file_reports"][0]["claims_found"] == 1

    @pytest.mark.asyncio
    async def test_report_records_per_file_receipts(self, tmp_path: Path) -> None:
        _write(tmp_path / "rich.md", "A shows B. C proves D.")
        _write(tmp_path / "empty.md", "No claims here.")

        async def maker(c: AuditClaim) -> DisconfirmationReceipt:
            return _stub_receipt(c, DisconfirmationVerdict.CONTESTED)

        report = await run_audit_sweep(tmp_path, receipt_maker=maker)

        rich = next(fr for fr in report.file_reports if fr.source_path.endswith("rich.md"))
        empty = next(fr for fr in report.file_reports if fr.source_path.endswith("empty.md"))
        assert isinstance(rich, AuditFileReport)
        assert rich.claims_found == 2
        assert len(rich.receipts) == 2
        assert empty.claims_found == 0
        assert empty.receipts == ()

    @pytest.mark.asyncio
    async def test_receipt_maker_exception_is_recorded_as_error(self, tmp_path: Path) -> None:
        _write(tmp_path / "boom.md", "A demonstrates B.")

        async def maker(c: AuditClaim) -> DisconfirmationReceipt:
            raise RuntimeError("provider blew up")

        report = await run_audit_sweep(tmp_path, receipt_maker=maker)

        assert report.total_claims == 1
        assert report.survived == 0
        assert report.refuted == 0
        assert report.contested == 0
        assert report.insufficient == 0
        boom = next(fr for fr in report.file_reports if fr.source_path.endswith("boom.md"))
        assert boom.claims_found == 1
        assert boom.receipts == ()
        assert len(boom.errors) == 1
        assert "RuntimeError" in boom.errors[0]

    @pytest.mark.asyncio
    async def test_claim_limit_per_file_caps_audit_volume(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "many.md",
            "A shows B. C demonstrates D. E proves F. G establishes H.",
        )

        async def maker(c: AuditClaim) -> DisconfirmationReceipt:
            return _stub_receipt(c, DisconfirmationVerdict.SURVIVED)

        report = await run_audit_sweep(tmp_path, receipt_maker=maker, claim_limit_per_file=2)
        assert report.total_claims == 2
        assert report.survived == 2
