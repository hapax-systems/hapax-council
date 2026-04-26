"""Tests for ``agents.marketing.bridgy_audit``."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agents.marketing.bridgy_audit import (
    BRIDGY_PLATFORMS,
    BridgyCoverageReport,
    PlatformOutcome,
    coverage_pct,
    render_coverage_report,
    write_coverage_report,
)


class TestBridgyPlatforms:
    def test_canonical_platforms_listed(self) -> None:
        # Per cc-task §intent: Bridgy POSSE fans out to four canonical
        # surfaces; the audit must recognize all four.
        assert "mastodon" in BRIDGY_PLATFORMS
        assert "bluesky" in BRIDGY_PLATFORMS
        assert "github" in BRIDGY_PLATFORMS
        assert "webmention-incoming" in BRIDGY_PLATFORMS


class TestPlatformOutcome:
    def test_dataclass_carries_counts(self) -> None:
        outcome = PlatformOutcome(
            platform="mastodon",
            ok=8,
            refused=2,
            error=1,
        )
        assert outcome.platform == "mastodon"
        assert outcome.ok == 8
        assert outcome.refused == 2
        assert outcome.error == 1


class TestCoveragePct:
    def test_zero_outcomes_returns_zero(self) -> None:
        outcome = PlatformOutcome(platform="mastodon", ok=0, refused=0, error=0)
        assert coverage_pct(outcome) == 0.0

    def test_all_ok_returns_one(self) -> None:
        outcome = PlatformOutcome(platform="bluesky", ok=10, refused=0, error=0)
        assert coverage_pct(outcome) == 1.0

    def test_partial_returns_fraction(self) -> None:
        # 8 ok + 2 refused + 0 error = 10 attempts; 8 ok = 0.8
        outcome = PlatformOutcome(platform="mastodon", ok=8, refused=2, error=0)
        assert abs(coverage_pct(outcome) - 0.8) < 1e-9


class TestRenderCoverageReport:
    def test_report_includes_iso_date(self) -> None:
        report = BridgyCoverageReport(
            generated_at=datetime(2026, 4, 26, 7, 30, tzinfo=UTC),
            window_days=30,
            outcomes=[],
        )
        rendered = render_coverage_report(report)
        assert "2026-04-26" in rendered

    def test_report_includes_window_days(self) -> None:
        report = BridgyCoverageReport(
            generated_at=datetime(2026, 4, 26, tzinfo=UTC),
            window_days=30,
            outcomes=[],
        )
        rendered = render_coverage_report(report)
        assert "30" in rendered

    def test_report_includes_per_platform_pct(self) -> None:
        report = BridgyCoverageReport(
            generated_at=datetime(2026, 4, 26, tzinfo=UTC),
            window_days=30,
            outcomes=[
                PlatformOutcome(platform="mastodon", ok=9, refused=0, error=1),
                PlatformOutcome(platform="bluesky", ok=10, refused=0, error=0),
            ],
        )
        rendered = render_coverage_report(report)
        assert "mastodon" in rendered
        assert "bluesky" in rendered
        # 9/10 = 90%
        assert "90" in rendered
        # 10/10 = 100%
        assert "100" in rendered

    def test_report_flags_zero_coverage_as_refusal_candidate(self) -> None:
        report = BridgyCoverageReport(
            generated_at=datetime(2026, 4, 26, tzinfo=UTC),
            window_days=30,
            outcomes=[
                PlatformOutcome(platform="github", ok=0, refused=0, error=0),
            ],
        )
        rendered = render_coverage_report(report)
        # Zero-attempt platforms surface as refusal candidates per cc-task
        # acceptance criteria: "Refusal-brief annex entries for unreached surfaces"
        assert "github" in rendered
        # The renderer surfaces the gap explicitly
        assert "no attempts" in rendered.lower() or "refusal" in rendered.lower()


class TestWriteCoverageReport:
    def test_writes_to_iso_dated_file(self, tmp_path: Path) -> None:
        report = BridgyCoverageReport(
            generated_at=datetime(2026, 4, 26, tzinfo=UTC),
            window_days=30,
            outcomes=[
                PlatformOutcome(platform="mastodon", ok=5, refused=0, error=0),
            ],
        )
        target = write_coverage_report(report, marketing_dir=tmp_path)
        assert target.exists()
        assert "2026-04-26" in target.name
        assert target.read_text(encoding="utf-8").strip() != ""

    def test_creates_parent_dir(self, tmp_path: Path) -> None:
        deep = tmp_path / "sub1" / "sub2"
        report = BridgyCoverageReport(
            generated_at=datetime(2026, 4, 26, tzinfo=UTC),
            window_days=30,
            outcomes=[],
        )
        target = write_coverage_report(report, marketing_dir=deep)
        assert target.exists()
        assert target.parent == deep
