"""Regression pin: pw-cat playback subprocess must declare media.role=Assistant.

WirePlumber's role-based ducker (config/wireplumber/50-hapax-voice-duck.conf,
linking.role-based.duck-level=0.3) lowers bed-music streams while a
``media.role=Assistant`` stream is active. node.stream.default-media-role
is "Multimedia", so untagged TTS output looks like just-another-music-stream
and the duck never fires.

Live regression observed 2026-04-21 by delta:
``~/.cache/hapax/relay/delta-ducking-gap-20260421-05h00.md``. All audio
sources competed at equal level on broadcast because the ducker had no
Assistant signal to react to.

This pin asserts both pw-cat call sites in
``agents/hapax_daimonion/pw_audio_output.py`` carry the
``--media-role Assistant`` flag.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.hapax_daimonion.pw_audio_output import PwAudioOutput, play_pcm


class TestMediaRoleOnPersistentSubprocess:
    """``PwAudioOutput._ensure_process`` builds the pw-cat command for the
    long-lived TTS subprocess. The ``--media-role Assistant`` pair must
    appear in argv so WirePlumber tags the resulting stream."""

    def test_media_role_assistant_in_default_target_argv(self) -> None:
        out = PwAudioOutput(sample_rate=24000, channels=1, target=None)
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc
            out._ensure_process(target=None, media_role="Assistant")

        cmd = mock_popen.call_args[0][0]
        assert "pw-cat" in cmd
        assert "--media-role" in cmd
        idx = cmd.index("--media-role")
        assert cmd[idx + 1] == "Assistant"

    def test_media_role_assistant_in_per_call_target_argv(self) -> None:
        out = PwAudioOutput(sample_rate=24000, channels=1)
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc
            out._ensure_process(target="hapax-voice-fx-capture", media_role="Assistant")

        cmd = mock_popen.call_args[0][0]
        assert "--media-role" in cmd
        idx = cmd.index("--media-role")
        assert cmd[idx + 1] == "Assistant"
        # Sanity: --target still set
        target_idx = cmd.index("--target")
        assert cmd[target_idx + 1] == "hapax-voice-fx-capture"

    def test_media_role_broadcast_routed_via_per_call_override(self) -> None:
        """cc-task voice-broadcast-role-split — write(media_role="Broadcast")
        spawns a separate subprocess with ``--media-role Broadcast`` so the
        wireplumber loopback for ``loopback.sink.role.broadcast`` picks it
        up, leaving the constructor-default Assistant subprocess untouched."""
        out = PwAudioOutput(sample_rate=24000, channels=1, target=None)
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_proc.stdin = MagicMock()
            mock_popen.return_value = mock_proc

            out.write(b"\x00" * 100, target="hapax-voice-fx-capture", media_role="Broadcast")

        cmd = mock_popen.call_args[0][0]
        idx = cmd.index("--media-role")
        assert cmd[idx + 1] == "Broadcast"
        target_idx = cmd.index("--target")
        assert cmd[target_idx + 1] == "hapax-voice-fx-capture"

    def test_per_role_subprocesses_cached_independently(self) -> None:
        """Two writes with different media_role values spawn TWO pw-cat
        subprocesses, cached separately by the (target, role) key."""
        out = PwAudioOutput(sample_rate=24000, channels=1, target="t1")
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_proc.stdin = MagicMock()
            mock_popen.return_value = mock_proc

            out.write(b"\x00" * 100, media_role="Assistant")
            out.write(b"\x00" * 100, media_role="Broadcast")
            out.write(b"\x00" * 100, media_role="Assistant")  # cache hit

        # 2 unique (t1, Assistant) and (t1, Broadcast) → 2 spawns, third is cached.
        assert mock_popen.call_count == 2


class TestMediaRoleOnOneShotPlayback:
    """``play_pcm`` is a one-shot subprocess.run for chimes / samples /
    executor commands. Same role tag required so chimes also duck bed
    music when they fire."""

    def test_media_role_assistant_in_one_shot_argv(self) -> None:
        with patch("subprocess.run") as mock_run:
            play_pcm(b"\x00" * 100)

        cmd = mock_run.call_args[0][0]
        assert "pw-cat" in cmd
        assert "--media-role" in cmd
        idx = cmd.index("--media-role")
        assert cmd[idx + 1] == "Assistant"
