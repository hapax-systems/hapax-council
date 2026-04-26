"""Tests for ``agents.sc_attestation_publisher`` — Phase 1 scope."""

from __future__ import annotations

from agents.sc_attestation_publisher import (
    DEFAULT_ATTESTATION_DIR,
    SCATTESTATION_DEFAULT_OEMBED,
    PerTrackMetrics,
    RawCohortMetrics,
    cohort_variance,
    compute_like_play_ratio,
    render_attestation_table,
)


class TestPerTrackMetrics:
    def test_dataclass_carries_play_like_repost(self) -> None:
        m = PerTrackMetrics(
            track_url="https://soundcloud.com/oudepode/track-1",
            title="Track 1",
            plays=100,
            likes=4,
            reposts=1,
        )
        assert m.plays == 100
        assert m.likes == 4
        assert m.reposts == 1


class TestRawCohortMetrics:
    def test_dataclass_carries_release_window(self) -> None:
        m = RawCohortMetrics(
            release_window="2026-04",
            tracks=[
                PerTrackMetrics(
                    track_url="https://soundcloud.com/oudepode/track-1",
                    title="Track 1",
                    plays=100,
                    likes=4,
                    reposts=1,
                )
            ],
        )
        assert m.release_window == "2026-04"
        assert len(m.tracks) == 1


class TestCohortVariance:
    def test_zero_when_single_track(self) -> None:
        # std/mean = 0/X = 0.0 by convention when only one data point
        m = RawCohortMetrics(
            release_window="2026-04",
            tracks=[PerTrackMetrics(track_url="x", title="X", plays=100, likes=4, reposts=0)],
        )
        assert cohort_variance(m) == 0.0

    def test_zero_when_uniform_plays(self) -> None:
        m = RawCohortMetrics(
            release_window="2026-04",
            tracks=[
                PerTrackMetrics(track_url=f"u{n}", title=f"U{n}", plays=100, likes=4, reposts=0)
                for n in range(5)
            ],
        )
        assert cohort_variance(m) == 0.0

    def test_high_variance_for_disparate_plays(self) -> None:
        # Per drop-1: 13–151 plays/track at 2h post-public window
        # produces std/mean substantially > 0
        m = RawCohortMetrics(
            release_window="2026-04",
            tracks=[
                PerTrackMetrics(track_url="a", title="A", plays=13, likes=0, reposts=0),
                PerTrackMetrics(track_url="b", title="B", plays=151, likes=1, reposts=0),
                PerTrackMetrics(track_url="c", title="C", plays=82, likes=0, reposts=0),
            ],
        )
        variance = cohort_variance(m)
        # std/mean for [13, 151, 82] is ~0.75; assert > 0.4 (clearly non-uniform)
        assert variance > 0.4

    def test_returns_zero_for_zero_mean(self) -> None:
        m = RawCohortMetrics(
            release_window="2026-04",
            tracks=[
                PerTrackMetrics(track_url=f"z{n}", title=f"Z{n}", plays=0, likes=0, reposts=0)
                for n in range(3)
            ],
        )
        assert cohort_variance(m) == 0.0


class TestLikePlayRatio:
    def test_zero_plays_returns_zero(self) -> None:
        track = PerTrackMetrics(track_url="x", title="X", plays=0, likes=0, reposts=0)
        assert compute_like_play_ratio(track) == 0.0

    def test_organic_baseline(self) -> None:
        # Organic baseline 2-8% per drop-1
        track = PerTrackMetrics(track_url="x", title="X", plays=100, likes=5, reposts=0)
        ratio = compute_like_play_ratio(track)
        assert 0.04 < ratio < 0.06  # 5%

    def test_bot_inflated_below_threshold(self) -> None:
        # Drop-1: oudepode 0.4% like:play is bot-injection-shaped
        track = PerTrackMetrics(track_url="x", title="X", plays=1000, likes=4, reposts=0)
        ratio = compute_like_play_ratio(track)
        assert ratio < 0.01


class TestRenderAttestationTable:
    def test_table_contains_track_title_and_plays(self) -> None:
        m = RawCohortMetrics(
            release_window="2026-04",
            tracks=[
                PerTrackMetrics(
                    track_url="https://soundcloud.com/oudepode/zorn-cycles",
                    title="Zorn Cycles",
                    plays=82,
                    likes=2,
                    reposts=1,
                )
            ],
        )
        table = render_attestation_table(m)
        assert "Zorn Cycles" in table
        assert "82" in table
        assert "2" in table  # likes

    def test_table_includes_like_play_ratio_column(self) -> None:
        m = RawCohortMetrics(
            release_window="2026-04",
            tracks=[PerTrackMetrics(track_url="x", title="X", plays=100, likes=5, reposts=0)],
        )
        table = render_attestation_table(m)
        # Like:play ratio column header
        assert "Like" in table or "like" in table

    def test_table_includes_cohort_variance_footer(self) -> None:
        m = RawCohortMetrics(
            release_window="2026-04",
            tracks=[
                PerTrackMetrics(track_url="a", title="A", plays=13, likes=0, reposts=0),
                PerTrackMetrics(track_url="b", title="B", plays=151, likes=1, reposts=0),
            ],
        )
        table = render_attestation_table(m)
        assert "Cohort variance" in table or "variance" in table.lower()


class TestDefaults:
    def test_default_attestation_dir(self) -> None:
        assert "sc-attestation" in str(DEFAULT_ATTESTATION_DIR)

    def test_default_oembed_endpoint(self) -> None:
        assert SCATTESTATION_DEFAULT_OEMBED.startswith("https://soundcloud.com/oembed")
