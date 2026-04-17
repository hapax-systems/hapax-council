"""Stream Deck key-map loader.

The key map is an operator-editable YAML file that names, per physical
Stream Deck key, the command-registry command to dispatch on press.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class KeyBinding:
    """A single Stream Deck key → command mapping."""

    key: int  # 0-indexed from top-left
    command: str  # dotted command-registry name, e.g. "studio.camera_profile.set"
    args: dict[str, Any] = field(default_factory=dict)
    label: str = ""  # optional display label


@dataclass(frozen=True)
class KeyMap:
    """Full key-map for one Stream Deck device."""

    bindings: tuple[KeyBinding, ...]

    def for_key(self, key_index: int) -> KeyBinding | None:
        for b in self.bindings:
            if b.key == key_index:
                return b
        return None


class KeyMapError(ValueError):
    """Raised when a key-map YAML file cannot be interpreted."""


def load_key_map(path: Path) -> KeyMap:
    """Load and validate ``config/streamdeck.yaml`` (or equivalent).

    Raises KeyMapError for any malformed-shape problem so the caller
    can degrade gracefully (log and idle) instead of crash-looping.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise KeyMapError(f"key-map file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise KeyMapError(f"key-map YAML parse error: {exc}") from exc

    return parse_key_map(raw)


def parse_key_map(raw: Any) -> KeyMap:
    """Validate a pre-parsed YAML dict and build a ``KeyMap``."""
    if not isinstance(raw, dict):
        raise KeyMapError("key-map root must be a mapping with a 'bindings' key")

    bindings_raw = raw.get("bindings")
    if not isinstance(bindings_raw, list):
        raise KeyMapError("key-map 'bindings' must be a list")

    seen_keys: set[int] = set()
    bindings: list[KeyBinding] = []
    for idx, entry in enumerate(bindings_raw):
        if not isinstance(entry, dict):
            raise KeyMapError(f"bindings[{idx}] must be a mapping")

        key = entry.get("key")
        command = entry.get("command")
        args = entry.get("args", {})
        label = entry.get("label", "")

        if not isinstance(key, int) or key < 0:
            raise KeyMapError(f"bindings[{idx}].key must be a non-negative int")
        if key in seen_keys:
            raise KeyMapError(f"duplicate key index {key} in key-map")
        if not isinstance(command, str) or not command:
            raise KeyMapError(f"bindings[{idx}].command must be a non-empty string")
        if not isinstance(args, dict):
            raise KeyMapError(f"bindings[{idx}].args must be a mapping (got {type(args).__name__})")
        if not isinstance(label, str):
            raise KeyMapError(f"bindings[{idx}].label must be a string")

        seen_keys.add(key)
        bindings.append(KeyBinding(key=key, command=command, args=dict(args), label=label))

    return KeyMap(bindings=tuple(bindings))
