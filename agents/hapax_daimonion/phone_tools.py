"""Phone voice command tools — registered with the conversation pipeline.

Provides tool definitions for LLM function calling:
  - find_phone: ring the phone
  - lock_phone: lock the phone
  - send_to_phone: send text/URL to phone clipboard
  - send_sms: send a text message
  - phone_notifications: summarize recent notifications
  - media_control: play/pause/skip phone media
"""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)

_DEVICE_ID = "aecd697f91434f7797836db631b36e3b"


def _cli(*args: str) -> str:
    try:
        result = subprocess.run(
            ["kdeconnect-cli", "--device", _DEVICE_ID, *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            return f"Failed: {detail}"
        return result.stdout.strip() or "Done"
    except Exception as e:
        return f"Failed: {e}"


def find_phone() -> str:
    """Ring the operator's phone to locate it."""
    return _cli("--ring")


def lock_phone() -> str:
    """Lock the operator's phone."""
    return _cli("--lock")


def send_to_phone(text: str) -> str:
    """Send text or URL to the operator's phone."""
    return _cli("--share-text", text)


def send_sms(recipient: str, message: str) -> str:
    """Send an SMS message."""
    return _cli("--send-sms", message, "--destination", recipient)


def phone_notifications() -> str:
    """List recent phone notifications."""
    return _cli("--list-notifications")


def media_control(action: str) -> str:
    """Control phone media playback (play, pause, next, previous, stop)."""
    valid = {"play", "pause", "next", "previous", "stop"}
    if action.lower() not in valid:
        return f"Unknown action: {action}. Use: {', '.join(valid)}"
    # MPRIS actions via KDE Connect DBus
    try:
        result = subprocess.run(
            [
                "busctl",
                "--user",
                "call",
                "org.kde.kdeconnect",
                f"/modules/kdeconnect/devices/{_DEVICE_ID}/mprisremote",
                "org.kde.kdeconnect.device.mprisremote",
                "sendAction",
                "s",
                action.capitalize(),
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return f"Media {action}" if result.returncode == 0 else f"Failed: {result.stderr}"
    except Exception as e:
        return f"Failed: {e}"


# Tool definitions for OpenAI-style function calling
PHONE_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "find_phone",
            "description": "Ring the operator's phone to help locate it. Use when they say 'where's my phone' or 'find my phone'.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lock_phone",
            "description": "Lock the operator's phone. Use when they say 'lock my phone'.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_to_phone",
            "description": "Send text or a URL to the operator's phone clipboard/share. Use when they say 'send this to my phone' or 'share that with my phone'.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Text or URL to send"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_sms",
            "description": "Send an SMS text message. Use when the operator says 'text someone' or 'send a message to'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {"type": "string", "description": "Phone number or contact name"},
                    "message": {"type": "string", "description": "Message to send"},
                },
                "required": ["recipient", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "media_control",
            "description": "Control phone media playback. Use when operator says 'pause', 'play', 'skip', 'next song'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["play", "pause", "next", "previous", "stop"],
                    }
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "phone_notifications",
            "description": (
                "List recent notifications from the operator's phone. Use when "
                "they say 'what notifications do I have' or 'check my phone'."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

# Handler mapping for tool execution
PHONE_TOOL_HANDLERS = {
    "find_phone": lambda **_: find_phone(),
    "lock_phone": lambda **_: lock_phone(),
    "send_to_phone": lambda **kw: send_to_phone(kw["text"]),
    "send_sms": lambda **kw: send_sms(kw["recipient"], kw["message"]),
    "media_control": lambda **kw: media_control(kw["action"]),
    "phone_notifications": lambda **_: phone_notifications(),
}
