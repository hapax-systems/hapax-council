from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "audit-ward-visibility.py"


def test_audit_ward_visibility_json_filters_active_wards_and_fails_thresholds(
    tmp_path: Path,
) -> None:
    layout = _write_layout(tmp_path)
    snapshot = _write_snapshot(tmp_path)
    active_wards = tmp_path / "current-layout-state.json"
    active_wards.write_text(
        json.dumps({"active_ward_ids": ["visible", "absent"], "schema_version": 1}),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            str(SCRIPT),
            "--snapshot",
            str(snapshot),
            "--layout",
            str(layout),
            "--active-wards-file",
            str(active_wards),
            "--canvas-w",
            "100",
            "--canvas-h",
            "100",
            "--json",
            "--min-visible-wards",
            "2",
            "--min-visible-fraction",
            "0.75",
        ],
        text=True,
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["active_ward_ids"] == ["absent", "visible"]
    assert [ward["ward"] for ward in payload["wards"]] == ["visible", "absent"]
    assert payload["visible_wards"] == 1
    assert "visible_ward_count_below_min:1<2" in payload["reasons"]
    assert "visible_ward_fraction_below_min:0.500<0.750" in payload["reasons"]


def test_audit_ward_visibility_json_passes_when_active_thresholds_are_met(
    tmp_path: Path,
) -> None:
    layout = _write_layout(tmp_path)
    snapshot = _write_snapshot(tmp_path)
    active_wards = tmp_path / "current-layout-state.json"
    active_wards.write_text(
        json.dumps({"active_ward_ids": ["visible"], "schema_version": 1}),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            str(SCRIPT),
            "--snapshot",
            str(snapshot),
            "--layout",
            str(layout),
            "--active-wards-file",
            str(active_wards),
            "--canvas-w",
            "100",
            "--canvas-h",
            "100",
            "--json",
            "--min-visible-wards",
            "1",
            "--min-visible-fraction",
            "1.0",
        ],
        text=True,
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["reasons"] == []
    assert [ward["ward"] for ward in payload["wards"]] == ["visible"]


def test_audit_ward_visibility_prefers_rendered_assignment_readback(
    tmp_path: Path,
) -> None:
    layout = _write_layout(tmp_path)
    snapshot = _write_snapshot(tmp_path)
    active_wards = tmp_path / "current-layout-state.json"
    active_wards.write_text(
        json.dumps(
            {
                "active_ward_ids": ["runtime-panel"],
                "assignments": [
                    {
                        "ward": "runtime-panel",
                        "surface": "runtime-panel-surface",
                        "x": 0,
                        "y": 0,
                        "w": 50,
                        "h": 50,
                        "opacity": 1.0,
                        "non_destructive": True,
                    }
                ],
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            str(SCRIPT),
            "--snapshot",
            str(snapshot),
            "--layout",
            str(layout),
            "--active-wards-file",
            str(active_wards),
            "--canvas-w",
            "100",
            "--canvas-h",
            "100",
            "--json",
            "--min-visible-wards",
            "1",
        ],
        text=True,
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["assignment_source"] == "current-layout-state"
    assert [ward["ward"] for ward in payload["wards"]] == ["runtime-panel"]
    assert "active_ward_missing:runtime-panel" not in payload["reasons"]


def _write_layout(tmp_path: Path) -> Path:
    layout = {
        "surfaces": [
            {
                "id": "visible-surface",
                "geometry": {"kind": "rect", "x": 0, "y": 0, "w": 50, "h": 50},
            },
            {
                "id": "absent-surface",
                "geometry": {"kind": "rect", "x": 50, "y": 0, "w": 50, "h": 50},
            },
            {
                "id": "inactive-surface",
                "geometry": {"kind": "rect", "x": 0, "y": 50, "w": 50, "h": 50},
            },
        ],
        "assignments": [
            {"source": "visible", "surface": "visible-surface", "opacity": 1.0},
            {"source": "absent", "surface": "absent-surface", "opacity": 1.0},
            {"source": "inactive", "surface": "inactive-surface", "opacity": 1.0},
        ],
    }
    path = tmp_path / "layout.json"
    path.write_text(json.dumps(layout), encoding="utf-8")
    return path


def _write_snapshot(tmp_path: Path) -> Path:
    image = Image.new("RGB", (100, 100), (0, 0, 0))
    pixels = image.load()
    for y in range(50):
        for x in range(50):
            pixels[x, y] = (230, 210, 160) if (x + y) % 2 else (40, 90, 160)
    path = tmp_path / "snapshot.jpg"
    image.save(path)
    return path
