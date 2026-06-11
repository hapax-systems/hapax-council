"""Regression pin: role.broadcast routing must exist for WirePlumber policy.

Per cc-task ``voice-broadcast-role-split``: daimonion's
``destination_channel.resolve_role()`` returns ``"Broadcast"`` for
livestream-classified utterances. The WirePlumber policy file carries the
role policy anchors while generated PipeWire role fragments carry the concrete
``input.loopback.sink.role.*`` loopback nodes.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WIREPLUMBER_CONFIG = REPO_ROOT / "config" / "wireplumber" / "50-hapax-voice-duck.conf"
GENERATED_ROLE_DIR = REPO_ROOT / "config" / "pipewire" / "generated" / "pipewire"


def _strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


class TestWireplumberRoleBroadcastLoopback:
    def test_config_file_exists(self) -> None:
        assert WIREPLUMBER_CONFIG.exists(), (
            f"Expected wireplumber config at {WIREPLUMBER_CONFIG} — has it moved?"
        )

    def test_broadcast_loopback_block_present(self) -> None:
        """``loopback.sink.role.broadcast`` policy anchor must be defined."""
        content = WIREPLUMBER_CONFIG.read_text(encoding="utf-8")
        assert 'node.name = "loopback.sink.role.broadcast"' in content, (
            "loopback.sink.role.broadcast policy not found in wireplumber config — "
            "voice-broadcast-role-split fix incomplete"
        )

    def test_concrete_broadcast_role_fragment_exists(self) -> None:
        """Generated PipeWire fragment owns the concrete role loopback node."""
        role_conf = (GENERATED_ROLE_DIR / "role-broadcast.conf").read_text(encoding="utf-8")
        assert 'node.name = "input.loopback.sink.role.broadcast"' in role_conf
        assert 'node.name = "input.loopback.sink.role.broadcast-output"' in role_conf
        assert 'device.intended-roles = [ "Broadcast" ]' in role_conf
        assert 'target.object = "hapax-voice-fx-capture"' in role_conf

    def test_wireplumber_file_does_not_duplicate_pipewire_loopbacks(self) -> None:
        """The WirePlumber policy file must not define duplicate loopback modules."""
        content = _strip_comments(WIREPLUMBER_CONFIG.read_text(encoding="utf-8"))
        assert "libpipewire-module-loopback" not in content
        assert "input.loopback.sink.role." not in content

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
        """Generated broadcast loopback declares intended role Broadcast."""
        role_conf = (GENERATED_ROLE_DIR / "role-broadcast.conf").read_text(encoding="utf-8")
        assert 'device.intended-roles = [ "Broadcast" ]' in role_conf, (
            "Broadcast role fragment's intended-roles list does not match daimonion's "
            'BROADCAST_MEDIA_ROLE = "Broadcast"'
        )

    def test_assistant_loopback_targets_hapax_private(self) -> None:
        """Phase-3 pin: role.assistant must route to hapax-private, NOT broadcast.

        Once the broadcast loopback exists (asserted above), Assistant
        becomes the private-only path. Any revert of this target back
        to ``hapax-voice-fx-capture`` re-introduces the leak that the
        2026-04-26 morning fix targeted: every Assistant-role utterance
        (sidechat replies, debug, exploration cognition) lands on
        broadcast. Triage the daimonion classifier instead.
        """
        content = WIREPLUMBER_CONFIG.read_text(encoding="utf-8")
        assistant_start = content.find('node.name = "loopback.sink.role.assistant"')
        assert assistant_start != -1
        assistant_end = content.find("provides = loopback.sink.role.assistant", assistant_start)
        assistant_block = content[assistant_start:assistant_end]
        # The block must declare hapax-private and must NOT declare the
        # broadcast chain target. Comments inside the block are allowed
        # to mention either name; the assertion targets the live
        # ``policy.role-based.preferred-target = "..."`` directive.
        target_line = next(
            (
                line
                for line in assistant_block.splitlines()
                if "policy.role-based.preferred-target" in line
                and not line.lstrip().startswith("#")
            ),
            None,
        )
        assert target_line is not None, (
            "role.assistant block missing policy.role-based.preferred-target line"
        )
        assert '"hapax-private"' in target_line, (
            f"role.assistant must target hapax-private, found: {target_line.strip()}"
        )
