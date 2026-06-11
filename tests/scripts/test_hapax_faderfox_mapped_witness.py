from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-faderfox-mapped-witness"


def _run(tmp_path: Path, journal: str) -> dict:
    fixture = tmp_path / "journal.txt"
    fixture.write_text(journal, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--journal-file", str(fixture)],
        check=True,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return json.loads(proc.stdout)


def test_reports_mapped_fader_journal_witness(tmp_path: Path) -> None:
    report = _run(
        tmp_path,
        """
2026-06-05 01:00:00 INFO faderfox_bridge: fader music -> hapax-music-loudnorm vol=0.504
2026-06-05 01:00:01 INFO faderfox_bridge: fader music -> hapax-music-loudnorm vol=0.512
""",
    )

    assert report["ok"] is True
    assert report["mapped_fader_witness"] is True
    assert report["mapped_fader_events"] == 2
    assert report["unmapped_events"] == 0
    assert report["profile_drift"] is False


def test_reports_profile_drift_for_unmapped_sweep(tmp_path: Path) -> None:
    report = _run(
        tmp_path,
        """
2026-06-05 13:34:34 INFO faderfox_bridge: unmapped CC ch=1 cc=6 val=69 (add to controls YAML)
2026-06-05 13:34:34 INFO faderfox_bridge: unmapped CC ch=1 cc=6 val=68 (add to controls YAML)
2026-06-05 13:34:34 INFO faderfox_bridge: unmapped CC ch=1 cc=6 val=67 (add to controls YAML)
2026-06-05 13:34:34 INFO faderfox_bridge: unmapped CC ch=1 cc=6 val=66 (add to controls YAML)
""",
    )

    assert report["ok"] is True
    assert report["mapped_fader_witness"] is False
    assert report["unmapped_events"] == 4
    assert report["profile_drift"] is True
    assert report["unmapped_sweeps"][0]["channel"] == 1
    assert report["unmapped_sweeps"][0]["cc"] == 6
    assert report["unmapped_sweeps"][0]["configured_kind"] is None


def test_reports_no_event_window_without_drift(tmp_path: Path) -> None:
    report = _run(tmp_path, "service started\n")

    assert report["ok"] is True
    assert report["mapped_fader_witness"] is False
    assert report["mapped_fader_events"] == 0
    assert report["unmapped_events"] == 0
    assert report["profile_drift"] is False


def test_classifies_raw_learn_line_against_configured_map(tmp_path: Path) -> None:
    report = _run(
        tmp_path,
        "INFO faderfox_bridge: MIDI control_change channel=0 control=95 value=64 time=0\n",
    )

    assert report["ok"] is True
    assert report["mapped_fader_witness"] is True
    assert report["mapped_fader_events"] == 1
    assert report["raw_midi_events"] == 1
    assert report["profile_drift"] is False
