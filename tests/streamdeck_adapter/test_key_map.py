"""Tests for agents.streamdeck_adapter.key_map (Phase 8 item 6)."""

from __future__ import annotations

from pathlib import Path

import pytest


class TestParseKeyMap:
    def test_valid_shape(self):
        from agents.streamdeck_adapter.key_map import parse_key_map

        km = parse_key_map(
            {
                "bindings": [
                    {"key": 0, "command": "studio.camera_profile.set", "args": {"profile": "hero"}},
                    {"key": 1, "command": "studio.stream_mode.toggle", "label": "Toggle"},
                ]
            }
        )
        assert len(km.bindings) == 2
        assert km.bindings[0].key == 0
        assert km.bindings[0].command == "studio.camera_profile.set"
        assert km.bindings[0].args == {"profile": "hero"}
        assert km.bindings[1].label == "Toggle"
        assert km.bindings[1].args == {}

    def test_for_key_lookup(self):
        from agents.streamdeck_adapter.key_map import parse_key_map

        km = parse_key_map(
            {
                "bindings": [
                    {"key": 3, "command": "research.condition.open"},
                ]
            }
        )
        assert km.for_key(3) is not None
        assert km.for_key(3).command == "research.condition.open"
        assert km.for_key(4) is None

    def test_rejects_non_mapping_root(self):
        from agents.streamdeck_adapter.key_map import KeyMapError, parse_key_map

        with pytest.raises(KeyMapError, match="root must be a mapping"):
            parse_key_map(["not", "a", "dict"])

    def test_rejects_missing_bindings_list(self):
        from agents.streamdeck_adapter.key_map import KeyMapError, parse_key_map

        with pytest.raises(KeyMapError, match="'bindings' must be a list"):
            parse_key_map({"bindings": {"not": "a list"}})

    def test_rejects_negative_key(self):
        from agents.streamdeck_adapter.key_map import KeyMapError, parse_key_map

        with pytest.raises(KeyMapError, match="non-negative"):
            parse_key_map({"bindings": [{"key": -1, "command": "x"}]})

    def test_rejects_duplicate_keys(self):
        from agents.streamdeck_adapter.key_map import KeyMapError, parse_key_map

        with pytest.raises(KeyMapError, match="duplicate key"):
            parse_key_map(
                {
                    "bindings": [
                        {"key": 0, "command": "a"},
                        {"key": 0, "command": "b"},
                    ]
                }
            )

    def test_rejects_empty_command(self):
        from agents.streamdeck_adapter.key_map import KeyMapError, parse_key_map

        with pytest.raises(KeyMapError, match="command"):
            parse_key_map({"bindings": [{"key": 0, "command": ""}]})

    def test_rejects_non_dict_args(self):
        from agents.streamdeck_adapter.key_map import KeyMapError, parse_key_map

        with pytest.raises(KeyMapError, match="args must be a mapping"):
            parse_key_map({"bindings": [{"key": 0, "command": "x", "args": ["not", "a", "dict"]}]})


class TestLoadKeyMap:
    def test_load_from_file(self, tmp_path: Path):
        from agents.streamdeck_adapter.key_map import load_key_map

        p = tmp_path / "sd.yaml"
        p.write_text(
            """
bindings:
  - key: 0
    command: studio.camera_profile.set
    args: {profile: hero_operator}
    label: Operator
""",
            encoding="utf-8",
        )
        km = load_key_map(p)
        assert len(km.bindings) == 1
        assert km.bindings[0].label == "Operator"

    def test_missing_file_raises(self, tmp_path: Path):
        from agents.streamdeck_adapter.key_map import KeyMapError, load_key_map

        with pytest.raises(KeyMapError, match="not found"):
            load_key_map(tmp_path / "nope.yaml")

    def test_malformed_yaml_raises(self, tmp_path: Path):
        from agents.streamdeck_adapter.key_map import KeyMapError, load_key_map

        p = tmp_path / "bad.yaml"
        p.write_text("bindings: [unclosed", encoding="utf-8")
        with pytest.raises(KeyMapError, match="YAML parse error"):
            load_key_map(p)

    def test_repo_default_config_loads(self):
        """Regression pin: the shipped config/streamdeck.yaml must parse."""
        from agents.streamdeck_adapter.key_map import load_key_map

        default = Path(__file__).resolve().parents[2] / "config" / "streamdeck.yaml"
        if not default.exists():
            pytest.skip("config/streamdeck.yaml not present at repo root in this checkout")
        km = load_key_map(default)
        assert len(km.bindings) >= 1
        # No duplicates, all commands non-empty
        seen: set[int] = set()
        for b in km.bindings:
            assert b.key not in seen
            seen.add(b.key)
            assert b.command
