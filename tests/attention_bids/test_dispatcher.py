"""Tests for LRR Phase 8 item 10 — attention-bid delivery dispatcher."""

from __future__ import annotations

import json
from pathlib import Path


def _bid(**overrides):
    from agents.attention_bids.bidder import AttentionBid

    return AttentionBid(
        source=overrides.get("source", "briefing"),
        salience=overrides.get("salience", 0.6),
        summary=overrides.get("summary", "Sprint gate about to close"),
        objective_id=overrides.get("objective_id"),
    )


class TestStimmungSuppresses:
    def test_critical_stance_suppresses(self):
        from agents.attention_bids.dispatcher import _stimmung_suppresses

        assert _stimmung_suppresses({"stance": "critical"}).startswith("stimmung_stance=")

    def test_degraded_stance_suppresses(self):
        from agents.attention_bids.dispatcher import _stimmung_suppresses

        assert _stimmung_suppresses({"stance": "degraded"}).startswith("stimmung_stance=")

    def test_high_stress_suppresses(self):
        from agents.attention_bids.dispatcher import _stimmung_suppresses

        assert _stimmung_suppresses({"operator_stress": {"value": 0.9}}).startswith("stress_value=")

    def test_normal_stimmung_does_not_suppress(self):
        from agents.attention_bids.dispatcher import _stimmung_suppresses

        assert (
            _stimmung_suppresses({"stance": "nominal", "operator_stress": {"value": 0.2}}) is None
        )

    def test_empty_stimmung_does_not_suppress(self):
        from agents.attention_bids.dispatcher import _stimmung_suppresses

        assert _stimmung_suppresses({}) is None


class TestLoadChannelConfig:
    def test_missing_file_returns_defaults(self, tmp_path: Path):
        from agents.attention_bids.dispatcher import DEFAULT_CHANNELS, load_channel_config

        cfg = load_channel_config(tmp_path / "nope.yaml")
        assert cfg.enabled_channels == DEFAULT_CHANNELS

    def test_loads_valid_config(self, tmp_path: Path):
        from agents.attention_bids.dispatcher import load_channel_config

        p = tmp_path / "attention-bids.yaml"
        p.write_text(
            "enabled_channels:\n  - ntfy\n  - visual_flash\nhysteresis_minutes: 5\n",
            encoding="utf-8",
        )
        cfg = load_channel_config(p)
        assert cfg.enabled_channels == ("ntfy", "visual_flash")
        assert cfg.hysteresis_minutes == 5

    def test_drops_unknown_channels(self, tmp_path: Path):
        from agents.attention_bids.dispatcher import load_channel_config

        p = tmp_path / "attention-bids.yaml"
        p.write_text(
            "enabled_channels:\n  - ntfy\n  - mystery_channel\n",
            encoding="utf-8",
        )
        cfg = load_channel_config(p)
        assert cfg.enabled_channels == ("ntfy",)

    def test_empty_channels_falls_back_to_default(self, tmp_path: Path):
        from agents.attention_bids.dispatcher import DEFAULT_CHANNELS, load_channel_config

        p = tmp_path / "attention-bids.yaml"
        p.write_text("enabled_channels: []\n", encoding="utf-8")
        cfg = load_channel_config(p)
        assert cfg.enabled_channels == DEFAULT_CHANNELS

    def test_malformed_hysteresis_falls_back(self, tmp_path: Path):
        from agents.attention_bids.dispatcher import HYSTERESIS_MINUTES_DEFAULT, load_channel_config

        p = tmp_path / "attention-bids.yaml"
        p.write_text(
            "enabled_channels: [ntfy]\nhysteresis_minutes: not-a-number\n", encoding="utf-8"
        )
        cfg = load_channel_config(p)
        assert cfg.hysteresis_minutes == HYSTERESIS_MINUTES_DEFAULT


class TestDispatchBid:
    def _config(self, channels=("ntfy",), hysteresis_minutes=15):
        from agents.attention_bids.dispatcher import ChannelConfig

        return ChannelConfig(enabled_channels=channels, hysteresis_minutes=hysteresis_minutes)

    def test_suppressed_by_stimmung(self, tmp_path: Path):
        from agents.attention_bids.dispatcher import dispatch_bid

        calls: list[tuple[str, str]] = []
        result = dispatch_bid(
            _bid(),
            stimmung={"stance": "critical"},
            now_epoch=100.0,
            last_delivered_at={},
            config=self._config(),
            trigger_dir=tmp_path,
            log_path=tmp_path / "log.jsonl",
            notifier=lambda t, b: calls.append((t, b)),
        )
        assert result.delivered == ()
        assert result.suppressed is not None
        assert calls == []
        log_line = (tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()[0]
        entry = json.loads(log_line)
        assert entry["suppressed"].startswith("stimmung_stance=")

    def test_ntfy_channel_calls_notifier(self, tmp_path: Path):
        from agents.attention_bids.dispatcher import dispatch_bid

        calls: list[tuple[str, str]] = []
        state: dict[str, float] = {}
        result = dispatch_bid(
            _bid(summary="Run the claim-5 eval"),
            stimmung={"stance": "nominal"},
            now_epoch=100.0,
            last_delivered_at=state,
            config=self._config(),
            trigger_dir=tmp_path,
            log_path=tmp_path / "log.jsonl",
            notifier=lambda t, b: calls.append((t, b)),
        )
        assert result.delivered == ("ntfy",)
        assert state["ntfy"] == 100.0
        assert calls == [("Hapax bid: briefing", "Run the claim-5 eval")]

    def test_visual_flash_writes_trigger_file(self, tmp_path: Path):
        from agents.attention_bids.dispatcher import dispatch_bid

        result = dispatch_bid(
            _bid(),
            stimmung={"stance": "nominal"},
            now_epoch=200.0,
            last_delivered_at={},
            config=self._config(channels=("visual_flash",)),
            trigger_dir=tmp_path,
            log_path=tmp_path / "log.jsonl",
            notifier=lambda t, b: None,
        )
        assert result.delivered == ("visual_flash",)
        active = json.loads((tmp_path / "active.json").read_text(encoding="utf-8"))
        assert active["source"] == "briefing"
        assert active["ts"] == 200.0

    def test_tts_and_led_each_have_own_file(self, tmp_path: Path):
        from agents.attention_bids.dispatcher import dispatch_bid

        result = dispatch_bid(
            _bid(),
            stimmung={"stance": "nominal"},
            now_epoch=200.0,
            last_delivered_at={},
            config=self._config(channels=("tts", "stream_deck_led")),
            trigger_dir=tmp_path,
            log_path=tmp_path / "log.jsonl",
            notifier=lambda t, b: None,
        )
        assert set(result.delivered) == {"tts", "stream_deck_led"}
        assert (tmp_path / "tts.json").exists()
        assert (tmp_path / "led.json").exists()
        assert not (tmp_path / "active.json").exists()

    def test_hysteresis_throttles_repeat(self, tmp_path: Path):
        from agents.attention_bids.dispatcher import dispatch_bid

        state: dict[str, float] = {}
        # First call — delivers
        first = dispatch_bid(
            _bid(),
            stimmung={"stance": "nominal"},
            now_epoch=1000.0,
            last_delivered_at=state,
            config=self._config(channels=("ntfy",), hysteresis_minutes=15),
            trigger_dir=tmp_path,
            log_path=tmp_path / "log.jsonl",
            notifier=lambda t, b: None,
        )
        assert first.delivered == ("ntfy",)
        # Second call inside 15-min window — throttled
        second = dispatch_bid(
            _bid(),
            stimmung={"stance": "nominal"},
            now_epoch=1000.0 + 60 * 5,  # 5 minutes later
            last_delivered_at=state,
            config=self._config(channels=("ntfy",), hysteresis_minutes=15),
            trigger_dir=tmp_path,
            log_path=tmp_path / "log.jsonl",
            notifier=lambda t, b: None,
        )
        assert second.delivered == ()
        assert second.throttled == ("ntfy",)

    def test_hysteresis_releases_after_window(self, tmp_path: Path):
        from agents.attention_bids.dispatcher import dispatch_bid

        state: dict[str, float] = {"ntfy": 1000.0}
        result = dispatch_bid(
            _bid(),
            stimmung={"stance": "nominal"},
            now_epoch=1000.0 + 60 * 20,  # 20 minutes later, after 15-min hysteresis
            last_delivered_at=state,
            config=self._config(channels=("ntfy",), hysteresis_minutes=15),
            trigger_dir=tmp_path,
            log_path=tmp_path / "log.jsonl",
            notifier=lambda t, b: None,
        )
        assert result.delivered == ("ntfy",)

    def test_per_channel_hysteresis_independent(self, tmp_path: Path):
        from agents.attention_bids.dispatcher import dispatch_bid

        state: dict[str, float] = {"ntfy": 1000.0}
        result = dispatch_bid(
            _bid(),
            stimmung={"stance": "nominal"},
            now_epoch=1000.0 + 60 * 5,  # 5 minutes, less than 15-min window
            last_delivered_at=state,
            config=self._config(channels=("ntfy", "visual_flash"), hysteresis_minutes=15),
            trigger_dir=tmp_path,
            log_path=tmp_path / "log.jsonl",
            notifier=lambda t, b: None,
        )
        # ntfy throttled (recent), visual_flash delivered (first time)
        assert result.delivered == ("visual_flash",)
        assert result.throttled == ("ntfy",)

    def test_log_has_delivered_and_throttled(self, tmp_path: Path):
        from agents.attention_bids.dispatcher import dispatch_bid

        state: dict[str, float] = {"ntfy": 1000.0}
        dispatch_bid(
            _bid(),
            stimmung={"stance": "nominal"},
            now_epoch=1000.0 + 60 * 1,
            last_delivered_at=state,
            config=self._config(channels=("ntfy", "visual_flash"), hysteresis_minutes=15),
            trigger_dir=tmp_path,
            log_path=tmp_path / "log.jsonl",
            notifier=lambda t, b: None,
        )
        entry = json.loads((tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()[0])
        assert entry["delivered"] == ["visual_flash"]
        assert entry["throttled"] == ["ntfy"]
        assert entry["source"] == "briefing"


class TestShippedConfig:
    def test_default_yaml_parses(self):
        """Regression pin: the shipped config/attention-bids.yaml stays valid."""
        from agents.attention_bids.dispatcher import load_channel_config

        repo_cfg = Path(__file__).resolve().parents[2] / "config" / "attention-bids.yaml"
        if not repo_cfg.exists():
            import pytest

            pytest.skip("shipped config not present in this checkout")
        cfg = load_channel_config(repo_cfg)
        assert cfg.enabled_channels == ("ntfy",)
        assert cfg.hysteresis_minutes == 15
