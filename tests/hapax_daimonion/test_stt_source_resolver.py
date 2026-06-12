"""stt_source_resolver — registry-backed tag→target map, legacy fallback."""

from __future__ import annotations

from pathlib import Path

from agents.hapax_daimonion.cpal import stt_source_resolver as mod
from agents.hapax_daimonion.cpal.stt_source_resolver import SttSourceResolver


class TestTagMap:
    def test_registry_backed_map_matches_contract(self) -> None:
        assert mod._tag_to_source_map() == {
            "rode": "hapax-mic-rode-capture",
            "yeti": "echo_cancel_capture",
            "contact-mic": "contact_mic",
        }

    def test_falls_back_to_legacy_map_without_registry(self, monkeypatch) -> None:
        monkeypatch.setattr(mod, "load_default_registry", lambda: None)
        assert mod._tag_to_source_map() == mod._LEGACY_TAG_TO_SOURCE


class TestResolver:
    def test_resolves_rode_tag_via_registry(self, tmp_path: Path) -> None:
        tag_file = tmp_path / "voice-source.txt"
        tag_file.write_text("rode")
        r = SttSourceResolver(path=tag_file)
        assert r.resolve() == "hapax-mic-rode-capture"

    def test_missing_tag_file_falls_back_to_yeti(self, tmp_path: Path) -> None:
        r = SttSourceResolver(path=tmp_path / "absent.txt")
        assert r.resolve() == "echo_cancel_capture"

    def test_invalid_tag_falls_back_to_yeti(self, tmp_path: Path) -> None:
        tag_file = tmp_path / "voice-source.txt"
        tag_file.write_text("not-a-tag")
        r = SttSourceResolver(path=tag_file)
        assert r.resolve() == "echo_cancel_capture"

    def test_cache_honors_ttl(self, tmp_path: Path) -> None:
        tag_file = tmp_path / "voice-source.txt"
        tag_file.write_text("rode")
        now = [0.0]
        r = SttSourceResolver(path=tag_file, cache_ttl_s=5.0, clock=lambda: now[0])
        assert r.current_tag() == "rode"
        tag_file.write_text("yeti")
        now[0] = 4.0
        assert r.current_tag() == "rode"  # cached
        now[0] = 6.0
        assert r.current_tag() == "yeti"  # expired
