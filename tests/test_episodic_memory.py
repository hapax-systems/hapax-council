"""Tests for episodic memory (WS3 Level 2)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from shared.episodic_memory import (
    COLLECTION,
    Episode,
    EpisodeBuilder,
    EpisodeStore,
    _downsample,
    _flow_state,
    _mode,
)


def _snap(
    ts: float = 100.0,
    activity: str = "coding",
    flow_score: float = 0.5,
    audio: float = 0.01,
    hr: int = 70,
    consent: str = "no_guest",
    voice_turns: int = 0,
) -> dict:
    return {
        "timestamp": ts,
        "ts": ts,
        "production_activity": activity,
        "flow_score": flow_score,
        "audio_energy_rms": audio,
        "heart_rate_bpm": hr,
        "consent_phase": consent,
        "voice_session": {"turn_count": voice_turns},
    }


def _mock_qdrant() -> MagicMock:
    client = MagicMock()
    client.get_collections.return_value = SimpleNamespace(
        collections=[SimpleNamespace(name=COLLECTION)]
    )
    return client


def _mock_embed(text: str, prefix: str = "search_query") -> list[float]:
    h = hash(text) % 1000
    return [float(h % (i + 1)) / (i + 1) for i in range(768)]


# ── Helper Tests ─────────────────────────────────────────────────────────────


class TestHelpers:
    def test_flow_state(self):
        assert _flow_state(0.0) == "idle"
        assert _flow_state(0.3) == "warming"
        assert _flow_state(0.6) == "active"
        assert _flow_state(1.0) == "active"

    def test_mode_basic(self):
        assert _mode(["a", "b", "a", "c"]) == "a"

    def test_mode_empty(self):
        assert _mode([]) == ""
        assert _mode(["", "", ""]) == ""

    def test_downsample_exact(self):
        assert _downsample([1.0, 2.0, 3.0, 4.0, 5.0], 5) == [1.0, 2.0, 3.0, 4.0, 5.0]

    def test_downsample_fewer(self):
        result = _downsample([1.0, 2.0], 5)
        assert len(result) == 5
        assert result[0] == 1.0
        assert result[1] == 2.0

    def test_downsample_more(self):
        result = _downsample(list(range(20)), 5)
        assert len(result) == 5

    def test_downsample_empty(self):
        assert _downsample([], 5) == [0.0] * 5


# ── Episode Model Tests ─────────────────────────────────────────────────────


class TestEpisode:
    def test_summary_text_basic(self):
        ep = Episode(activity="coding", duration_s=300, flow_state="active")
        text = ep.summary_text
        assert "coding" in text
        assert "300s" in text
        assert "active" in text

    def test_summary_text_idle(self):
        ep = Episode(activity="", duration_s=60, flow_state="idle")
        assert "idle" in ep.summary_text

    def test_summary_text_with_voice(self):
        ep = Episode(activity="coding", duration_s=120, voice_turns=5)
        assert "5 voice turns" in ep.summary_text

    def test_summary_text_with_consent(self):
        ep = Episode(activity="coding", duration_s=60, consent_phase="guest_present")
        assert "consent" in ep.summary_text

    def test_summary_text_with_trend(self):
        ep = Episode(activity="coding", duration_s=60, flow_trend=0.01)
        assert "rising" in ep.summary_text


# ── Episode Builder Tests ────────────────────────────────────────────────────


class TestEpisodeBuilder:
    def test_first_snapshot_no_episode(self):
        builder = EpisodeBuilder()
        result = builder.observe(_snap(ts=100))
        assert result is None

    def test_same_state_accumulates(self):
        builder = EpisodeBuilder()
        builder.observe(_snap(ts=100, activity="coding", flow_score=0.5))
        builder.observe(_snap(ts=102.5, activity="coding", flow_score=0.5))
        result = builder.observe(_snap(ts=105, activity="coding", flow_score=0.5))
        assert result is None  # no boundary

    def test_activity_change_closes_episode(self):
        builder = EpisodeBuilder()
        builder.observe(_snap(ts=100, activity="coding"))
        builder.observe(_snap(ts=102.5, activity="coding"))
        result = builder.observe(_snap(ts=105, activity="browsing"))
        assert result is not None
        assert result.activity == "coding"
        assert result.snapshot_count == 2

    def test_flow_state_change_closes_episode(self):
        builder = EpisodeBuilder()
        builder.observe(_snap(ts=100, flow_score=0.1))  # idle
        builder.observe(_snap(ts=102.5, flow_score=0.1))
        result = builder.observe(_snap(ts=105, flow_score=0.7))  # active
        assert result is not None
        assert result.flow_state == "idle"

    def test_time_gap_closes_episode(self):
        builder = EpisodeBuilder()
        builder.observe(_snap(ts=100))
        builder.observe(_snap(ts=102.5))
        result = builder.observe(_snap(ts=200))  # 97.5s gap
        assert result is not None

    def test_consent_change_closes_episode(self):
        builder = EpisodeBuilder()
        builder.observe(_snap(ts=100, consent="no_guest"))
        builder.observe(_snap(ts=102.5, consent="no_guest"))
        result = builder.observe(_snap(ts=105, consent="guest_present"))
        assert result is not None
        assert result.consent_phase == "no_guest"

    def test_episode_has_correct_duration(self):
        builder = EpisodeBuilder()
        builder.observe(_snap(ts=100, activity="coding"))
        builder.observe(_snap(ts=110, activity="coding"))
        builder.observe(_snap(ts=120, activity="coding"))
        result = builder.observe(_snap(ts=130, activity="browsing"))
        assert result is not None
        assert result.duration_s == 20.0  # 120 - 100
        assert result.start_ts == 100.0
        assert result.end_ts == 120.0

    def test_episode_downsampled_signals(self):
        builder = EpisodeBuilder()
        for i in range(10):
            builder.observe(_snap(ts=100 + i * 2.5, activity="coding", flow_score=0.1 * i))
        result = builder.observe(_snap(ts=125, activity="browsing"))
        assert result is not None
        assert len(result.flow_scores) == 5
        assert len(result.audio_energy) == 5
        assert len(result.heart_rates) == 5

    def test_episode_flow_trend(self):
        builder = EpisodeBuilder()
        # Stay within "active" band (>=0.6) but with rising trend
        builder.observe(_snap(ts=100, activity="coding", flow_score=0.6))
        builder.observe(_snap(ts=110, activity="coding", flow_score=0.7))
        builder.observe(_snap(ts=120, activity="coding", flow_score=0.9))
        result = builder.observe(_snap(ts=130, activity="browsing"))
        assert result is not None
        assert result.flow_trend > 0  # rising

    def test_episode_voice_turns(self):
        builder = EpisodeBuilder()
        builder.observe(_snap(ts=100, voice_turns=0))
        builder.observe(_snap(ts=102.5, voice_turns=3))
        builder.observe(_snap(ts=105, voice_turns=5))
        result = builder.observe(_snap(ts=107.5, activity="browsing"))
        assert result is not None
        assert result.voice_turns == 5  # max seen

    def test_flush(self):
        builder = EpisodeBuilder()
        builder.observe(_snap(ts=100))
        builder.observe(_snap(ts=102.5))
        result = builder.flush()
        assert result is not None
        assert result.snapshot_count == 2

    def test_flush_insufficient_data(self):
        builder = EpisodeBuilder()
        builder.observe(_snap(ts=100))
        result = builder.flush()
        assert result is None  # need at least 2 snapshots

    def test_empty_activity_no_false_boundary(self):
        """Both empty activities should not trigger a boundary."""
        builder = EpisodeBuilder()
        builder.observe(_snap(ts=100, activity=""))
        result = builder.observe(_snap(ts=102.5, activity=""))
        assert result is None


# ── Episode Store Tests ──────────────────────────────────────────────────────


class TestEpisodeStore:
    def test_ensure_collection_creates_when_missing(self):
        client = MagicMock()
        client.get_collections.return_value = SimpleNamespace(collections=[])
        store = EpisodeStore(client=client)
        store.ensure_collection()
        client.create_collection.assert_called_once()

    def test_ensure_collection_skips_when_exists(self):
        client = _mock_qdrant()
        store = EpisodeStore(client=client)
        store.ensure_collection()
        client.create_collection.assert_not_called()

    @patch("shared.config.embed", side_effect=_mock_embed)
    def test_record_returns_id(self, mock_embed):
        client = _mock_qdrant()
        store = EpisodeStore(client=client)
        ep = Episode(activity="coding", duration_s=300, start_ts=1000)
        eid = store.record(ep)
        assert eid.startswith("ep-")
        client.upsert.assert_called_once()

    @patch("shared.config.embed", side_effect=_mock_embed)
    def test_search_returns_matches(self, mock_embed):
        client = _mock_qdrant()
        mock_point = SimpleNamespace(
            payload=Episode(activity="coding", duration_s=300).model_dump(),
            score=0.8,
        )
        client.query_points.return_value = SimpleNamespace(points=[mock_point])
        store = EpisodeStore(client=client)
        matches = store.search("coding session")
        assert len(matches) == 1
        assert matches[0].score == 0.8
        assert matches[0].episode.activity == "coding"

    @patch("shared.config.embed", side_effect=_mock_embed)
    def test_search_filters_low_score(self, mock_embed):
        client = _mock_qdrant()
        mock_point = SimpleNamespace(
            payload=Episode(activity="coding").model_dump(),
            score=0.1,
        )
        client.query_points.return_value = SimpleNamespace(points=[mock_point])
        store = EpisodeStore(client=client)
        matches = store.search("anything", min_score=0.3)
        assert len(matches) == 0

    @patch("shared.config.embed", side_effect=_mock_embed)
    def test_search_with_activity_filter(self, mock_embed):
        client = _mock_qdrant()
        client.query_points.return_value = SimpleNamespace(points=[])
        store = EpisodeStore(client=client)
        store.search("test", activity="coding")
        call_kwargs = client.query_points.call_args
        assert call_kwargs.kwargs.get("query_filter") is not None

    @patch("shared.config.embed", side_effect=_mock_embed)
    def test_search_for_activity(self, mock_embed):
        client = _mock_qdrant()
        client.query_points.return_value = SimpleNamespace(points=[])
        store = EpisodeStore(client=client)
        store.search_for_activity("coding", context="afternoon session")
        client.query_points.assert_called_once()

    def test_count(self):
        client = _mock_qdrant()
        client.get_collection.return_value = SimpleNamespace(points_count=15)
        store = EpisodeStore(client=client)
        assert store.count() == 15
