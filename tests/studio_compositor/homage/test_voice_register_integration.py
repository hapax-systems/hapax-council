"""Phase 7 end-to-end: choreographer -> SHM -> CPAL bridge (task #113).

Covers the package-swap -> register-file contract. Full CPAL runtime is
out of scope for this test — we assert the on-disk payload matches
``package.voice_register_default`` and that the bridge consumes it
correctly.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from agents.hapax_daimonion.cpal.register_bridge import VoiceRegisterBridge
from agents.studio_compositor.homage import BITCHX_CONSENT_SAFE_PACKAGE, BITCHX_PACKAGE
from agents.studio_compositor.homage.choreographer import Choreographer
from shared.voice_register import VoiceRegister


@pytest.fixture
def choreographer(tmp_path: Path) -> tuple[Choreographer, Path]:
    """Build a Choreographer with every SHM path redirected under ``tmp_path``.

    Also enables HOMAGE (via an explicit truthy env) so Phase-7 broadcast
    runs through reconcile() rather than short-circuiting.
    """
    register_file = tmp_path / "homage-voice-register.json"
    chor = Choreographer(
        pending_file=tmp_path / "homage-pending.json",
        uniforms_file=tmp_path / "uniforms.json",
        substrate_package_file=tmp_path / "homage-substrate-package.json",
        consent_safe_flag_file=tmp_path / "consent-safe-none.json",
        voice_register_file=register_file,
        rng=random.Random(0),
    )
    return chor, register_file


class TestPackageSwapWritesRegister:
    def test_bitchx_package_emits_textmode(self, choreographer, monkeypatch) -> None:
        chor, register_file = choreographer
        monkeypatch.setenv("HAPAX_HOMAGE_ACTIVE", "1")

        chor.reconcile(BITCHX_PACKAGE, now=0.0)

        assert register_file.exists()
        payload = json.loads(register_file.read_text(encoding="utf-8"))
        assert payload["register"] == "textmode"
        assert payload["register"] == VoiceRegister.TEXTMODE.value
        assert payload["package"] == "bitchx"

    def test_payload_matches_package_voice_register_default(
        self, choreographer, monkeypatch
    ) -> None:
        """Integration invariant: on-wire register == package default."""
        chor, register_file = choreographer
        monkeypatch.setenv("HAPAX_HOMAGE_ACTIVE", "1")

        chor.reconcile(BITCHX_PACKAGE, now=0.0)

        payload = json.loads(register_file.read_text(encoding="utf-8"))
        assert payload["register"] == BITCHX_PACKAGE.voice_register_default.value

    def test_consent_safe_variant_keeps_textmode(self, tmp_path, monkeypatch) -> None:
        """The consent-safe swap must NOT drop out of TEXTMODE.

        Per task brief: "BitchX consent-safe -> TEXTMODE (keeps register
        stable even when palette goes grey)". This locks in that contract.
        """
        monkeypatch.setenv("HAPAX_HOMAGE_ACTIVE", "1")
        register_file = tmp_path / "homage-voice-register.json"
        flag_file = tmp_path / "consent-safe-active.json"
        flag_file.write_text(json.dumps({"consent_safe": True}), encoding="utf-8")
        chor = Choreographer(
            pending_file=tmp_path / "homage-pending.json",
            uniforms_file=tmp_path / "uniforms.json",
            substrate_package_file=tmp_path / "homage-substrate-package.json",
            consent_safe_flag_file=flag_file,
            voice_register_file=register_file,
            rng=random.Random(0),
        )

        chor.reconcile(BITCHX_PACKAGE, now=0.0)

        payload = json.loads(register_file.read_text(encoding="utf-8"))
        # Substrate broadcast swapped to the consent-safe variant, and
        # both BitchX variants declare TEXTMODE — register survives the
        # consent flip.
        assert payload["register"] == "textmode"
        assert payload["package"] == "bitchx_consent_safe"
        assert BITCHX_CONSENT_SAFE_PACKAGE.voice_register_default == VoiceRegister.TEXTMODE

    def test_flag_off_suppresses_register_publish(self, choreographer, monkeypatch) -> None:
        """Rollback posture: HAPAX_HOMAGE_ACTIVE=0 skips Phase-7 publish."""
        chor, register_file = choreographer
        monkeypatch.setenv("HAPAX_HOMAGE_ACTIVE", "0")

        chor.reconcile(BITCHX_PACKAGE, now=0.0)

        assert not register_file.exists()


class TestBridgeConsumesChoreographerOutput:
    """End-to-end: choreographer writes, bridge reads, CPAL gets the register."""

    def test_bridge_reads_freshly_written_register(self, choreographer, monkeypatch) -> None:
        chor, register_file = choreographer
        monkeypatch.setenv("HAPAX_HOMAGE_ACTIVE", "1")

        chor.reconcile(BITCHX_PACKAGE, now=0.0)

        # Use a zero-TTL bridge so the test doesn't race the cache window.
        bridge = VoiceRegisterBridge(register_file=register_file, cache_ttl_s=0.0)
        assert bridge.current_register() == VoiceRegister.TEXTMODE
