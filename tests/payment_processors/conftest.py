"""Shared payment-processor test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

import shared.durable_jsonl_sink as sink_mod


@pytest.fixture
def _durable_chronicle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provision the Stage0 durable chronicle sink for receive-rail tests."""

    durable_root = tmp_path / "stage0-durable-sink"
    durable_root.mkdir()
    monkeypatch.setenv("HAPAX_DURABLE_SINK_ROOT", str(durable_root))
    monkeypatch.setattr(sink_mod, "_mount_fstype_for_path", lambda _path: "btrfs")
    monkeypatch.setattr(
        "shared.chronicle.CHRONICLE_FILE",
        tmp_path / "chronicle" / "events.jsonl",
    )
    return durable_root
