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
    assert lines["shader-plan-pass-count.txt"] == "0.0000"
    assert lines["visual-chain-param-pressure.txt"] == "0.0000"


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
    assert float(lines["effect-drift-active-ratio.txt"]) == 1.0
    assert float(lines["effect-drift-edge.txt"]) > 0
    assert float(lines["visual-chain-drift.txt"]) > 0


def test_row_selection_accepts_ordinals_and_labels() -> None:
    module = _load_script()

    selected = module["selected_rows"]("2,threshold-zeta")

    assert [row.label for row in selected] == ["prism-beta", "threshold-zeta"]
