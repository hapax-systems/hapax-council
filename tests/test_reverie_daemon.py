# tests/test_reverie_daemon.py
"""Tests for the standalone Reverie daemon entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_daemon_tick_consumes_impingements(tmp_path: Path):
    """Daemon reads impingements from JSONL and dispatches to mixer."""
    imp_file = tmp_path / "impingements.jsonl"
    imp_data = {
        "id": "test-001",
        "timestamp": 1000.0,
        "source": "dmn.evaluative",
        "type": "salience_integration",
        "strength": 0.7,
        "content": {"metric": "tension", "dimensions": {"intensity": 0.5}},
    }
    imp_file.write_text(json.dumps(imp_data) + "\n")

    mock_mixer = MagicMock()
    mock_mixer.tick = AsyncMock()
    mock_mixer.dispatch_impingement = MagicMock()

    from agents.reverie.__main__ import ReverieDaemon

    daemon = ReverieDaemon(
        impingement_path=imp_file,
        mixer=mock_mixer,
        skip_bootstrap=True,
    )

    await daemon.tick()

    mock_mixer.dispatch_impingement.assert_called_once()
    mock_mixer.tick.assert_awaited_once()


@pytest.mark.asyncio
async def test_daemon_tick_tolerates_missing_impingement_file(tmp_path: Path):
    """Daemon handles missing impingement file gracefully."""
    mock_mixer = MagicMock()
    mock_mixer.tick = AsyncMock()

    from agents.reverie.__main__ import ReverieDaemon

    daemon = ReverieDaemon(
        impingement_path=tmp_path / "nonexistent.jsonl",
        mixer=mock_mixer,
        skip_bootstrap=True,
    )

    await daemon.tick()  # Should not raise

    mock_mixer.tick.assert_awaited_once()
    mock_mixer.dispatch_impingement.assert_not_called()
