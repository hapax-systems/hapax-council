from __future__ import annotations

import runpy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "screwm-effect-drift-matrix-witness.py"


def _load_script() -> dict:
    return runpy.run_path(str(SCRIPT), run_name="__test_screwm_matrix__")


def test_matrix_pairs_every_darkplaces_preset_with_existing_slotdrift_bank() -> None:
    module = _load_script()
    rows = module["MATRIX_ROWS"]
    banks = module["_load_permutation_sets"]()

    assert [row.ordinal for row in rows] == list(range(7))
    assert [row.preset for row in rows] == list(range(7))
    paired = [row.bank_label for row in rows if row.ordinal > 0]
    assert paired == [
        "alpha-line-tonal-trail",
        "beta-rutt-key-recursion",
        "gamma-mask-detail-temporal",
        "delta-map-slit-geometry",
        "epsilon-palette-particle-fluid",
        "zeta-breath-reaction-wave",
    ]
    assert set(paired) <= set(banks)
    assert all(row.expected_cues for row in rows)


def test_quiet_live_baseline_zeros_prior_effect_state() -> None:
    module = _load_script()
    lines = module["build_row_lines"](
        module["MATRIX_ROWS"][0],
        exporter=module["_load_exporter"](),
        bank_effects=module["_load_permutation_sets"](),
        state_dir=Path("/tmp/unused-screwm-matrix-state"),
    )

    assert lines["effect-review-preset.txt"] == "0"
    assert lines["local-effect-count.txt"] == "0.0000"
    assert lines["effect-drift-active-ratio.txt"] == "0.0000"
    assert lines["effect-drift-compositing.txt"] == "0.0000"
    for new_scalar in (
        "active-slot-ratio",
        "active-effect-ratio",
        "fast-ratio",
        "slow-ratio",
        "kind-variance",
    ):
        assert lines[f"effect-drift-{new_scalar}.txt"] == "0.0000"
    assert lines["effect-drift-source.txt"] != "slotdrift"
    assert lines["effect-drift-real-source.txt"] == "0.0000"
    for family in ("tonal", "atmospheric", "temporal", "texture", "edge", "compositing"):
        assert lines[f"effect-drift-mode-{family}.txt"] == "0.0000"
    assert lines["shader-plan-pass-count.txt"] == "0.0000"
    assert lines["visual-chain-param-pressure.txt"] == "0.0000"
    assert lines["camera-manual.txt"] == "1.0000"
    assert lines["camera-origin-x.txt"] == "0.0000"
    assert lines["camera-yaw.txt"] == "90.0000"


def test_matrix_row_writes_uservec_preset_and_effect_drift_scalars(tmp_path: Path) -> None:
    module = _load_script()
    row = module["MATRIX_ROWS"][4]

    lines = module["build_row_lines"](
        row,
        exporter=module["_load_exporter"](),
        bank_effects=module["_load_permutation_sets"](),
        state_dir=tmp_path,
    )

    assert lines["effect-review-preset.txt"] == "4"
    assert lines["local-effect-route.txt"] == "ENTITY_LOCAL_SOURCE_PLANE"
    assert lines["shader-plan-route.txt"] == "IN_SCROOM_SHADER_PASS_PLAN"
    assert lines["effect-drift-route.txt"] == "IN_SCROOM_EFFECT_DRIFT_STATE"
    assert float(lines["shader-plan-pass-count.txt"]) > 0
    assert float(lines["shader-plan-motion.txt"]) > 0
    assert 0.3 <= float(lines["effect-drift-active-ratio.txt"]) <= 1.0
    assert (
        max(
            float(lines[f"effect-drift-{family}.txt"])
            for family in ("tonal", "atmospheric", "temporal", "texture", "edge", "compositing")
        )
        > 0
    )
    assert float(lines["visual-chain-drift.txt"]) > 0
    # New SlotDrift vocabulary must round-trip as a real slotdrift state, not the
    # synthetic live fallback that every row used before this witness was tightened.
    assert lines["effect-drift-source.txt"] == "slotdrift"
    assert lines["effect-drift-real-source.txt"] == "1.0000"
    assert float(lines["effect-drift-active-slot-ratio.txt"]) > 0
    assert float(lines["effect-drift-active-effect-ratio.txt"]) > 0
    assert float(lines["effect-drift-kind-variance.txt"]) > 0
    assert (
        float(lines["effect-drift-fast-ratio.txt"]) + float(lines["effect-drift-slow-ratio.txt"])
    ) > 0


def test_row_selection_accepts_ordinals_and_labels() -> None:
    module = _load_script()

    selected = module["selected_rows"]("2,threshold-zeta")

    assert [row.label for row in selected] == ["prism-beta", "threshold-zeta"]


def test_matrix_restore_clears_camera_and_review_preset(tmp_path: Path) -> None:
    module = _load_script()
    game_data = tmp_path / "game-data"
    output_dir = tmp_path / "out"
    args = type(
        "Args",
        (),
        {
            "rows": "0",
            "output_dir": output_dir,
            "game_data": game_data,
            "video_device": tmp_path / "video52",
            "direct_display": ":82",
            "capture_timeout_s": 0.1,
            "settle_s": 0.01,
            "capture": False,
            "restore_camera": True,
        },
    )()

    assert module["run_matrix"](args) == 0
    assert (game_data / "camera-manual.txt").read_text(encoding="utf-8") == "0.0000\n"
    assert (game_data / "effect-review-preset.txt").read_text(encoding="utf-8") == "0\n"


def test_new_slotdrift_scalars_vary_across_rows(tmp_path: Path) -> None:
    module = _load_script()
    exporter = module["_load_exporter"]()
    banks = module["_load_permutation_sets"]()

    def _row_lines(ordinal: int) -> dict:
        return module["build_row_lines"](
            module["MATRIX_ROWS"][ordinal],
            exporter=exporter,
            bank_effects=banks,
            state_dir=tmp_path / f"row{ordinal}",
        )

    low = _row_lines(1)
    mid = _row_lines(3)
    high = _row_lines(6)

    # Driven by per-row slot intensity + active slot count, not a fixed fallback:
    # the scalars must change with the row ordinal.
    assert float(high["effect-drift-active-ratio.txt"]) > float(
        low["effect-drift-active-ratio.txt"]
    )
    assert float(mid["effect-drift-active-slot-ratio.txt"]) > float(
        low["effect-drift-active-slot-ratio.txt"]
    )
    assert all(lines["effect-drift-source.txt"] == "slotdrift" for lines in (low, mid, high))
