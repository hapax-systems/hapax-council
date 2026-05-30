"""R1(b): effect-drift selection must reject a content-frozen primary.

Regression guard for the live failure where ``_select_effect_drift_state``
served a primary whose file mtime was fresh (re-touched) but whose rendered
scalars were frozen (``frame_count``/``timestamp_unix_ms`` pinned), suppressing
the live fallback. Content freshness is judged by ``timestamp_unix_ms``, which
freezes with the content, not by the re-touched file mtime.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "darkplaces-state-export.py"


def _load_exporter() -> ModuleType:
    spec = importlib.util.spec_from_file_location("darkplaces_state_export", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _real_slotdrift(ts_ms: float) -> dict:
    return {
        "timestamp_unix_ms": ts_ms,
        "frame_count": 100,
        "source_presence": {
            "visible_source_count": 38,
            "minimum_effect_source_count": 4,
            "fail_closed": False,
        },
        "slotdrift_coverage": {"window_limit": 192},
    }


def _setup(tmp_path: Path, primary_payload: dict, now: float) -> tuple[Path, Path]:
    primary = tmp_path / "effect-drift-state.json"
    fallback = tmp_path / "effect-drift-fallback.json"
    primary.write_text(json.dumps(primary_payload), encoding="utf-8")
    fallback.write_text(json.dumps({"dominant_family": "tonal"}), encoding="utf-8")
    # Both files mtime-fresh: isolates the content-freshness check from mtime.
    os.utime(primary, (now, now))
    os.utime(fallback, (now, now))
    return primary, fallback


def test_content_frozen_primary_is_not_served_as_slotdrift(tmp_path: Path) -> None:
    exporter = _load_exporter()
    now = 1_000_000.0
    primary, fallback = _setup(tmp_path, _real_slotdrift(now * 1000.0 - 30_000.0), now)
    _state, source = exporter._select_effect_drift_state(primary, fallback, now=now)
    assert source != "slotdrift"
    assert source == "synthetic-fallback"


def test_content_fresh_primary_is_served_as_slotdrift(tmp_path: Path) -> None:
    exporter = _load_exporter()
    now = 1_000_000.0
    primary, fallback = _setup(tmp_path, _real_slotdrift(now * 1000.0 - 1_000.0), now)
    state, source = exporter._select_effect_drift_state(primary, fallback, now=now)
    assert source == "slotdrift"
    assert state["frame_count"] == 100


def test_primary_missing_content_timestamp_defers_to_mtime(tmp_path: Path) -> None:
    """A payload with no ``timestamp_unix_ms`` (legacy / non-live-producer)
    carries no content clock, so selection defers to mtime freshness rather
    than fail-closing -- preserving behaviour for sources without the stamp."""
    exporter = _load_exporter()
    now = 1_000_000.0
    payload = _real_slotdrift(0.0)
    del payload["timestamp_unix_ms"]
    primary, fallback = _setup(tmp_path, payload, now)
    _state, source = exporter._select_effect_drift_state(primary, fallback, now=now)
    assert source == "slotdrift"
