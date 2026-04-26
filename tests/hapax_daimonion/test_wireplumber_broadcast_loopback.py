"""Regression pin: wireplumber policy must require role.broadcast loopback.

Per cc-task ``voice-broadcast-role-split``: daimonion's
``destination_channel.resolve_role()`` returns ``"Broadcast"`` for
livestream-classified utterances. Without the corresponding
``loopback.sink.role.broadcast`` block in
``config/wireplumber/50-hapax-voice-duck.conf``'s
``policy.linking.role-based.loopbacks`` requires list, the loopback
defined further down in the file may not load at boot — and
``--media-role Broadcast`` streams would be silently unrouted.

This pin asserts the requires line carries all four expected
loopback role names.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WIREPLUMBER_CONFIG = REPO_ROOT / "config" / "wireplumber" / "50-hapax-voice-duck.conf"


class TestWireplumberRoleBroadcastLoopback:
    def test_config_file_exists(self) -> None:
        assert WIREPLUMBER_CONFIG.exists(), (
            f"Expected wireplumber config at {WIREPLUMBER_CONFIG} — has it moved?"
        )

    def test_broadcast_loopback_block_present(self) -> None:
        """``loopback.sink.role.broadcast`` block must be defined."""
        content = WIREPLUMBER_CONFIG.read_text(encoding="utf-8")
        assert 'node.name = "loopback.sink.role.broadcast"' in content, (
            "loopback.sink.role.broadcast block not found in wireplumber config — "
            "voice-broadcast-role-split fix incomplete"
        )

    def test_broadcast_loopback_in_policy_requires(self) -> None:
        """Policy ``requires`` list must include role.broadcast loopback.

        Without this, wireplumber may not auto-load the broadcast loopback
        at boot, leaving ``--media-role Broadcast`` streams unrouted.
        """
        content = WIREPLUMBER_CONFIG.read_text(encoding="utf-8")
        assert "loopback.sink.role.broadcast" in content, (
            "loopback.sink.role.broadcast not referenced anywhere"
        )
        # Scope search to the policy block (after the policy.linking
        # anchor), not the earlier rules block which has its own
        # requires = [ ... ] array for unrelated factories.
        # Use `provides = policy.linking.role-based.loopbacks` as the
        # anchor (unique to the virtual-policy block; the earlier
        # wireplumber.profiles entry uses `=` not `provides =`).
        policy_anchor = content.find("provides = policy.linking.role-based.loopbacks")
        assert policy_anchor != -1, (
            "policy.linking.role-based.loopbacks virtual-policy anchor missing — config restructured?"
        )
        require_block_start = content.find("requires = [", policy_anchor)
        require_block_end = content.find("]", require_block_start)
        assert require_block_start != -1, "policy requires array not found after anchor"
        require_block = content[require_block_start:require_block_end]
        assert "loopback.sink.role.broadcast" in require_block, (
            "loopback.sink.role.broadcast missing from policy requires array — "
            "broadcast loopback may not load at boot"
        )

    def test_broadcast_loopback_targets_voice_fx_capture(self) -> None:
        """Broadcast loopback must route to hapax-voice-fx-capture (livestream chain)."""
        content = WIREPLUMBER_CONFIG.read_text(encoding="utf-8")
        # Find the broadcast block's preferred-target by locating the
        # block start and reading forward to find the preferred-target line.
        broadcast_start = content.find('node.name = "loopback.sink.role.broadcast"')
        assert broadcast_start != -1
        broadcast_end = content.find("provides = loopback.sink.role.broadcast", broadcast_start)
        broadcast_block = content[broadcast_start:broadcast_end]
        assert "hapax-voice-fx-capture" in broadcast_block, (
            "Broadcast loopback does not route to hapax-voice-fx-capture — "
            "livestream TTS would not reach broadcast chain"
        )

    def test_broadcast_intended_role_name(self) -> None:
        """Broadcast loopback declares device.intended-roles = [ \"Broadcast\" ]."""
        content = WIREPLUMBER_CONFIG.read_text(encoding="utf-8")
        broadcast_start = content.find('node.name = "loopback.sink.role.broadcast"')
        broadcast_end = content.find("provides = loopback.sink.role.broadcast", broadcast_start)
        broadcast_block = content[broadcast_start:broadcast_end]
        assert 'device.intended-roles = [ "Broadcast" ]' in broadcast_block, (
            "Broadcast loopback's intended-roles list does not match daimonion's "
            'BROADCAST_MEDIA_ROLE = "Broadcast"'
        )
