"""Tests for the Rode Wireless Pro detection + auto-routing adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.hapax_daimonion import rode_wireless_adapter as adapter_mod
from agents.hapax_daimonion.cpal import stt_source_resolver as resolver_mod

# --- Sample pw-cli output ---

_PW_CLI_WITH_RODE = """\
\tid 34, type PipeWire:Interface:Device/3
\t\tfactory.id = "14"
\t\tclient.id = "31"
\t\tdevice.description = "RODE Wireless Pro"
\t\tdevice.name = "alsa_card.usb-RODE_Wireless_Pro-00"
\tid 42, type PipeWire:Interface:Node/3
\t\tnode.name = "alsa_input.usb-RODE_Wireless_Pro-00.analog-stereo"
"""

_PW_CLI_WITHOUT_RODE = """\
\tid 34, type PipeWire:Interface:Device/3
\t\tdevice.description = "Blue Microphones Yeti"
\t\tdevice.name = "alsa_card.usb-Blue_Microphones_Yeti-00"
\tid 42, type PipeWire:Interface:Node/3
\t\tnode.name = "alsa_input.usb-Blue_Microphones_Yeti-00.analog-stereo"
"""


# --- Detection ---


class TestDetection:
    def test_detects_rode_in_pw_cli_output(self):
        assert adapter_mod.detect_rode_present(_PW_CLI_WITH_RODE) is True

    def test_detects_absence_when_no_rode_lines(self):
        assert adapter_mod.detect_rode_present(_PW_CLI_WITHOUT_RODE) is False

    def test_empty_output_means_absent(self):
        assert adapter_mod.detect_rode_present("") is False

    def test_match_is_case_insensitive(self):
        assert adapter_mod.detect_rode_present("node.name = rode-wireless-pro") is True

    def test_matches_wireless_pro_token(self):
        # Some firmware revs expose only "Wireless Pro" without the RODE prefix.
        assert adapter_mod.detect_rode_present("device.description = Wireless Pro") is True


# --- Tag file IO ---


class TestVoiceSourceIO:
    def test_write_then_read_roundtrip(self, tmp_path: Path):
        path = tmp_path / "voice-source.txt"
        adapter_mod.write_voice_source(adapter_mod.VOICE_SOURCE_RODE, path=path)
        assert path.read_text().strip() == "rode"

    def test_write_creates_parent_dir(self, tmp_path: Path):
        path = tmp_path / "sub" / "deeper" / "voice-source.txt"
        adapter_mod.write_voice_source(adapter_mod.VOICE_SOURCE_YETI, path=path)
        assert path.read_text().strip() == "yeti"

    def test_write_rejects_invalid_tag(self, tmp_path: Path):
        with pytest.raises(ValueError):
            adapter_mod.write_voice_source("bogus", path=tmp_path / "x.txt")

    def test_read_returns_none_when_file_missing(self, tmp_path: Path):
        assert adapter_mod.read_voice_source(tmp_path / "missing.txt") is None

    def test_read_returns_none_for_invalid_tag(self, tmp_path: Path):
        path = tmp_path / "voice-source.txt"
        path.write_text("garbage\n")
        assert adapter_mod.read_voice_source(path) is None


# --- Adapter state machine + metric ---


class _StubMetric:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def set_active(self, tag: str) -> None:
        self.calls.append(tag)


class TestAdapter:
    def test_writes_rode_when_device_present(self, tmp_path: Path):
        path = tmp_path / "voice-source.txt"
        metric = _StubMetric()
        ada = adapter_mod.RodeWirelessAdapter(
            voice_source_path=path,
            probe=lambda: _PW_CLI_WITH_RODE,
            metric=metric,
        )
        assert ada.tick() == "rode"
        assert path.read_text().strip() == "rode"
        assert metric.calls == ["rode"]

    def test_writes_yeti_on_fallback(self, tmp_path: Path):
        path = tmp_path / "voice-source.txt"
        metric = _StubMetric()
        ada = adapter_mod.RodeWirelessAdapter(
            voice_source_path=path,
            probe=lambda: _PW_CLI_WITHOUT_RODE,
            metric=metric,
        )
        assert ada.tick() == "yeti"
        assert path.read_text().strip() == "yeti"
        assert metric.calls == ["yeti"]

    def test_disappearance_triggers_fallback_transition(self, tmp_path: Path):
        path = tmp_path / "voice-source.txt"
        metric = _StubMetric()
        outputs = iter([_PW_CLI_WITH_RODE, _PW_CLI_WITHOUT_RODE])
        ada = adapter_mod.RodeWirelessAdapter(
            voice_source_path=path,
            probe=lambda: next(outputs),
            metric=metric,
        )
        assert ada.tick() == "rode"
        assert ada.tick() == "yeti"
        assert path.read_text().strip() == "yeti"
        assert metric.calls == ["rode", "yeti"]

    def test_idempotent_ticks_do_not_rewrite_metric(self, tmp_path: Path):
        path = tmp_path / "voice-source.txt"
        metric = _StubMetric()
        ada = adapter_mod.RodeWirelessAdapter(
            voice_source_path=path,
            probe=lambda: _PW_CLI_WITH_RODE,
            metric=metric,
        )
        ada.tick()
        ada.tick()
        ada.tick()
        # Only the first transition emits; identical ticks are no-ops.
        assert metric.calls == ["rode"]

    def test_pw_cli_missing_means_fallback(self, tmp_path: Path):
        # Empty probe output (e.g. pw-cli absent, timed out) => yeti.
        path = tmp_path / "voice-source.txt"
        ada = adapter_mod.RodeWirelessAdapter(
            voice_source_path=path,
            probe=lambda: "",
            metric=_StubMetric(),
        )
        assert ada.tick() == "yeti"


# --- STT source resolver ---


class TestSttSourceResolver:
    def test_reads_rode_tag(self, tmp_path: Path):
        path = tmp_path / "voice-source.txt"
        path.write_text("rode\n")
        r = resolver_mod.SttSourceResolver(path=path)
        assert r.current_tag() == "rode"
        # voice-p2-perception-registry: the rode point resolves to the live
        # mk5 capture node (the direct-USB RX node is absent from the graph).
        assert r.resolve() == "hapax-mic-rode-capture"

    def test_reads_yeti_tag(self, tmp_path: Path):
        path = tmp_path / "voice-source.txt"
        path.write_text("yeti\n")
        r = resolver_mod.SttSourceResolver(path=path)
        assert r.current_tag() == "yeti"
        assert r.resolve() == "echo_cancel_capture"

    def test_reads_contact_mic_tag(self, tmp_path: Path):
        path = tmp_path / "voice-source.txt"
        path.write_text("contact-mic\n")
        r = resolver_mod.SttSourceResolver(path=path)
        assert r.current_tag() == "contact-mic"
        assert r.resolve() == "contact_mic"

    def test_missing_file_falls_back_to_yeti(self, tmp_path: Path):
        r = resolver_mod.SttSourceResolver(path=tmp_path / "nope.txt")
        assert r.current_tag() == "yeti"
        assert r.resolve() == "echo_cancel_capture"

    def test_invalid_tag_falls_back_to_yeti(self, tmp_path: Path):
        path = tmp_path / "voice-source.txt"
        path.write_text("unknown-source\n")
        r = resolver_mod.SttSourceResolver(path=path)
        assert r.current_tag() == "yeti"

    def test_cache_prevents_re_read_within_ttl(self, tmp_path: Path):
        path = tmp_path / "voice-source.txt"
        path.write_text("rode\n")
        now = [100.0]
        r = resolver_mod.SttSourceResolver(path=path, cache_ttl_s=5.0, clock=lambda: now[0])
        assert r.current_tag() == "rode"
        # Swap the file under us — within TTL, cache must still return rode.
        path.write_text("yeti\n")
        now[0] = 103.0
        assert r.current_tag() == "rode"

    def test_cache_expires_after_ttl(self, tmp_path: Path):
        path = tmp_path / "voice-source.txt"
        path.write_text("rode\n")
        now = [100.0]
        r = resolver_mod.SttSourceResolver(path=path, cache_ttl_s=5.0, clock=lambda: now[0])
        assert r.current_tag() == "rode"
        path.write_text("yeti\n")
        now[0] = 106.0  # past the 5 s TTL
        assert r.current_tag() == "yeti"

    def test_invalidate_forces_re_read(self, tmp_path: Path):
        path = tmp_path / "voice-source.txt"
        path.write_text("rode\n")
        r = resolver_mod.SttSourceResolver(path=path, cache_ttl_s=60.0)
        assert r.current_tag() == "rode"
        path.write_text("yeti\n")
        r.invalidate()
        assert r.current_tag() == "yeti"


# --- Prometheus metric ---


class TestVoiceSourceMetric:
    def test_metric_set_active_without_crash(self):
        # Real prometheus_client is a hard dependency — constructing the
        # metric against the default registry must succeed. We don't assert
        # on the scraped value because collector re-registration across
        # tests is fiddly; the adapter-level tests already prove the
        # transitions land via the stub metric.
        metric = adapter_mod._VoiceSourceMetric()
        metric.set_active("rode")
        metric.set_active("yeti")
        metric.set_active("contact-mic")
