"""Focused tests for DURF YAML parsing cache behavior."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from agents.studio_compositor import durf_source as _durf_module


def test_yaml_mapping_cache_avoids_reparse_until_file_metadata_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "relay.yaml"
    path.write_text("status: claimed\n", encoding="utf-8")
    calls = 0

    def fake_safe_load(_text: str) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"status": f"parse-{calls}"}

    _durf_module._YAML_MAPPING_CACHE.clear()
    monkeypatch.setattr(_durf_module.yaml, "safe_load", fake_safe_load)

    try:
        assert _durf_module._read_yaml_mapping(path) == {"status": "parse-1"}
        assert _durf_module._read_yaml_mapping(path) == {"status": "parse-1"}
        assert calls == 1

        path.write_text("status: claimed\nextra: true\n", encoding="utf-8")

        assert _durf_module._read_yaml_mapping(path) == {"status": "parse-2"}
        assert calls == 2
    finally:
        _durf_module._YAML_MAPPING_CACHE.clear()
