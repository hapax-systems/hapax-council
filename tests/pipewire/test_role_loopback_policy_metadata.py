"""Regression pins for generated role-loopback PipeWire fragments.

WirePlumber's role-volume Lua hook iterates every
``input.loopback.sink.role.*`` sink and compares
``policy.role-based.priority`` as a number. Generated PipeWire role
fragments must carry the concrete role metadata because
``50-hapax-voice-duck.conf`` is only the minimal WirePlumber policy surface.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATED = REPO_ROOT / "config" / "pipewire" / "generated" / "pipewire"

EXPECTED = {
    "role-assistant.conf": {
        'device.intended-roles = [ "Assistant" ]',
        "policy.role-based.priority = 40",
        'policy.role-based.preferred-target = "hapax-private"',
    },
    "role-broadcast.conf": {
        'device.intended-roles = [ "Broadcast" ]',
        "policy.role-based.priority = 40",
        'policy.role-based.preferred-target = "hapax-voice-fx-capture"',
    },
    "role-multimedia.conf": {
        'device.intended-roles = [ "Music", "Movie", "Game", "Multimedia" ]',
        "policy.role-based.priority = 10",
        'policy.role-based.preferred-target = "hapax-pc-loudnorm"',
    },
    "role-notification.conf": {
        'device.intended-roles = [ "Notification" ]',
        "policy.role-based.priority = 20",
        'policy.role-based.preferred-target = "hapax-notification-private"',
    },
}


def test_generated_role_loopbacks_have_wireplumber_priority_metadata() -> None:
    for filename, expected_lines in EXPECTED.items():
        text = (GENERATED / filename).read_text(encoding="utf-8")
        assert 'node.name = "input.loopback.sink.role.' in text
        for line in expected_lines:
            assert line in text, f"{filename} missing {line}"
