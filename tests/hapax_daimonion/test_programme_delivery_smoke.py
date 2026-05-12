from __future__ import annotations

import json
from pathlib import Path

from agents.hapax_daimonion.programme_delivery_smoke import run_smoke


def test_programme_delivery_smoke_completes_full_cycle(tmp_path: Path) -> None:
    result = run_smoke(output_dir=tmp_path, programme_id="programme-delivery-smoke-test")

    assert result.receipt["ok"] is True
    assert result.receipt["prep_manifest_ok"] is True
    assert result.receipt["programme_loaded"] is True
    assert result.receipt["beat_transition_count"] == 3
    assert result.receipt["director_command_count"] == 3
    assert result.receipt["tts_delivered_count"] == 3
    assert len(result.receipt["accepted_layouts"]) == 3
    assert len(result.receipt["screenshot_paths"]) == 3
    assert all(Path(path).exists() for path in result.receipt["screenshot_paths"])

    saved = json.loads(result.receipt_path.read_text(encoding="utf-8"))
    assert saved["ok"] is True
