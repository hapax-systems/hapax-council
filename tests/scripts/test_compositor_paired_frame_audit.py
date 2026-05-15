from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "compositor-paired-frame-audit.sh"


@pytest.mark.skipif(shutil.which("magick") is None, reason="ImageMagick not installed")
def test_compositor_paired_frame_audit_writes_diff_and_region_metrics(tmp_path: Path) -> None:
    pre = tmp_path / "pre.jpg"
    final = tmp_path / "final.jpg"
    state = tmp_path / "effect-state.json"
    output_root = tmp_path / "audit"

    subprocess.run(
        ["magick", "-size", "1280x720", "xc:black", str(pre)],
        check=True,
    )
    subprocess.run(
        [
            "magick",
            "-size",
            "1280x720",
            "xc:black",
            "-fill",
            "white",
            "-draw",
            "rectangle 100,100 300,300",
            str(final),
        ],
        check=True,
    )
    state.write_text('{"non_neutral_pass_count": 1}\n', encoding="utf-8")

    result = subprocess.run(
        [
            str(SCRIPT),
            "pytest",
            "--duration",
            "1.0",
            "--interval-ms",
            "500",
            "--pre-source",
            str(pre),
            "--final-source",
            str(final),
            "--state-source",
            str(state),
            "--output-root",
            str(output_root),
        ],
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    captures = list((output_root / "pytest").glob("*"))
    assert len(captures) == 1
    capture_dir = captures[0]
    assert (capture_dir / "pre_fx-01.jpg").is_file()
    assert (capture_dir / "final-01.jpg").is_file()
    assert (capture_dir / "diff-01.jpg").is_file()
    assert (capture_dir / "pre_fx-02.jpg").is_file()
    assert (capture_dir / "final-02.jpg").is_file()
    assert (capture_dir / "diff-02.jpg").is_file()
    assert (capture_dir / "transition_diff-02.jpg").is_file()
    assert (capture_dir / "effect_state-01.json").is_file()
    assert (capture_dir / "capture_times.tsv").is_file()
    assert (capture_dir / "README.md").is_file()

    capture_rows = (capture_dir / "capture_times.tsv").read_text(
        encoding="utf-8"
    ).splitlines()
    assert capture_rows[0] == "sample\tcaptured_at_utc"
    assert [row.split("\t")[0] for row in capture_rows[1:]] == ["01", "02"]

    rows = (capture_dir / "metrics.tsv").read_text(encoding="utf-8").splitlines()
    assert rows[0] == "sample\tscope\tdiff_mean\tdiff_max\tdiff_sd\tpre_mean\tfinal_mean"
    assert all(len(row.split("\t")) == 7 for row in rows)
    assert {row.split("\t")[1] for row in rows[1:]} == {
        "global",
        "left_top",
        "right_top",
        "left_bottom",
        "right_bottom",
        "center",
    }

    transition_rows = (capture_dir / "transition_metrics.tsv").read_text(
        encoding="utf-8"
    ).splitlines()
    assert (
        transition_rows[0]
        == "sample\tscope\tfinal_delta_mean\tfinal_delta_max\tfinal_delta_sd\tprev_final_mean\tfinal_mean"
    )
    assert all(len(row.split("\t")) == 7 for row in transition_rows)
    assert {row.split("\t")[0] for row in transition_rows[1:]} == {"02"}
    assert {row.split("\t")[1] for row in transition_rows[1:]} == {
        "global",
        "left_top",
        "right_top",
        "left_bottom",
        "right_bottom",
        "center",
    }
