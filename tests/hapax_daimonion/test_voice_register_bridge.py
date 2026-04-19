"""Phase 7 voice-register bridge tests (task #113).

Contract:
    * Missing file -> DEFAULT_REGISTER.
    * Stale file (>2s mtime) -> DEFAULT_REGISTER.
    * Fresh file with a valid register -> that register.
    * Malformed payload -> DEFAULT_REGISTER.
    * Package swap (external write) is picked up on next read once the
      in-process cache window lapses.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from agents.hapax_daimonion.cpal.register_bridge import (
    VoiceRegisterBridge,
    frame_text_for_register,
    textmode_prompt_prefix,
)
from shared.voice_register import DEFAULT_REGISTER, VoiceRegister


def _make_bridge(tmp_path: Path) -> tuple[VoiceRegisterBridge, Path]:
    f = tmp_path / "homage-voice-register.json"
    # Disable the 250ms cache so each call reads from disk; tests drive
    # the state file directly and expect reads to reflect disk state
    # synchronously. Production keeps the default cache.
    bridge = VoiceRegisterBridge(register_file=f, cache_ttl_s=0.0)
    return bridge, f


def _write_register(path: Path, register: VoiceRegister, *, package: str = "bitchx") -> None:
    payload = {"register": register.value, "package": package, "updated_at": 0.0}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


class TestMissingFile:
    def test_returns_default_when_file_missing(self, tmp_path: Path) -> None:
        bridge, _ = _make_bridge(tmp_path)
        assert bridge.current_register() == DEFAULT_REGISTER

    def test_default_is_conversing(self) -> None:
        # Pinned: spec §4.8 default is CONVERSING under non-broadcast mode.
        assert DEFAULT_REGISTER == VoiceRegister.CONVERSING


class TestFreshFile:
    def test_textmode_value_returned(self, tmp_path: Path) -> None:
        bridge, f = _make_bridge(tmp_path)
        _write_register(f, VoiceRegister.TEXTMODE)
        assert bridge.current_register() == VoiceRegister.TEXTMODE

    def test_announcing_value_returned(self, tmp_path: Path) -> None:
        bridge, f = _make_bridge(tmp_path)
        _write_register(f, VoiceRegister.ANNOUNCING)
        assert bridge.current_register() == VoiceRegister.ANNOUNCING

    def test_conversing_value_returned(self, tmp_path: Path) -> None:
        bridge, f = _make_bridge(tmp_path)
        _write_register(f, VoiceRegister.CONVERSING)
        assert bridge.current_register() == VoiceRegister.CONVERSING


class TestStaleFile:
    def test_stale_mtime_falls_back_to_default(self, tmp_path: Path) -> None:
        bridge, f = _make_bridge(tmp_path)
        _write_register(f, VoiceRegister.TEXTMODE)
        # Backdate mtime far beyond the 2s window.
        old = time.time() - 10.0
        os.utime(f, (old, old))
        assert bridge.current_register() == DEFAULT_REGISTER

    def test_custom_stale_window(self, tmp_path: Path) -> None:
        f = tmp_path / "reg.json"
        bridge = VoiceRegisterBridge(register_file=f, cache_ttl_s=0.0, stale_after_s=0.1)
        _write_register(f, VoiceRegister.TEXTMODE)
        old = time.time() - 1.0
        os.utime(f, (old, old))
        assert bridge.current_register() == DEFAULT_REGISTER


class TestMalformed:
    def test_non_json_payload_falls_back(self, tmp_path: Path) -> None:
        bridge, f = _make_bridge(tmp_path)
        f.write_text("not json at all", encoding="utf-8")
        assert bridge.current_register() == DEFAULT_REGISTER

    def test_missing_register_key_falls_back(self, tmp_path: Path) -> None:
        bridge, f = _make_bridge(tmp_path)
        f.write_text(json.dumps({"package": "bitchx"}), encoding="utf-8")
        assert bridge.current_register() == DEFAULT_REGISTER

    def test_unknown_register_value_falls_back(self, tmp_path: Path) -> None:
        bridge, f = _make_bridge(tmp_path)
        f.write_text(
            json.dumps({"register": "whispering", "package": "bitchx"}),
            encoding="utf-8",
        )
        assert bridge.current_register() == DEFAULT_REGISTER

    def test_non_string_register_value_falls_back(self, tmp_path: Path) -> None:
        bridge, f = _make_bridge(tmp_path)
        f.write_text(json.dumps({"register": 42}), encoding="utf-8")
        assert bridge.current_register() == DEFAULT_REGISTER


class TestPackageSwap:
    def test_swap_reflected_on_next_read(self, tmp_path: Path) -> None:
        bridge, f = _make_bridge(tmp_path)
        _write_register(f, VoiceRegister.TEXTMODE, package="bitchx")
        assert bridge.current_register() == VoiceRegister.TEXTMODE
        # Simulate operator switching to a hypothetical conversing-lineage
        # package; choreographer rewrites the file.
        _write_register(f, VoiceRegister.CONVERSING, package="hypercard")
        assert bridge.current_register() == VoiceRegister.CONVERSING


class TestCache:
    def test_cache_suppresses_repeat_reads(self, tmp_path: Path) -> None:
        f = tmp_path / "reg.json"
        # Use explicit injected ``now`` so we can prove caching without
        # relying on wall-clock timing.
        bridge = VoiceRegisterBridge(register_file=f, cache_ttl_s=1.0)
        _write_register(f, VoiceRegister.TEXTMODE)
        assert bridge.current_register(now=0.0) == VoiceRegister.TEXTMODE
        # Overwrite with a different register; cache should still return
        # the stale value because ``now`` is inside the TTL window.
        _write_register(f, VoiceRegister.ANNOUNCING)
        assert bridge.current_register(now=0.5) == VoiceRegister.TEXTMODE
        # Step past the TTL — new read reflects disk.
        assert bridge.current_register(now=2.0) == VoiceRegister.ANNOUNCING


class TestFraming:
    def test_textmode_prefix_is_nonempty(self) -> None:
        prefix = textmode_prompt_prefix()
        assert prefix
        assert "clipped" in prefix.lower() or "irc" in prefix.lower()

    def test_frame_textmode_prepends_prefix(self) -> None:
        framed = frame_text_for_register("hello", VoiceRegister.TEXTMODE)
        assert framed.startswith(textmode_prompt_prefix())
        assert framed.endswith("hello")

    def test_frame_non_textmode_passthrough(self) -> None:
        assert frame_text_for_register("hello", VoiceRegister.CONVERSING) == "hello"
        assert frame_text_for_register("hello", VoiceRegister.ANNOUNCING) == "hello"
