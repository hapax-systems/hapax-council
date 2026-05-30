from __future__ import annotations

import json
import runpy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "screwm-drift-state-source.py"


def _load_script() -> dict:
    return runpy.run_path(str(SCRIPT), run_name="__test_screwm_drift_state__")


def test_screwm_drift_state_source_covers_all_effect_families() -> None:
    module = _load_script()

    effect_drift, visual_chain, plan = module["build_states"](now=1000.0)
    families = {item["effect_family"] for item in effect_drift["passes"]}
    active = [item for item in effect_drift["passes"] if item["non_neutral"]]
    inactive = [item for item in effect_drift["passes"] if not item["non_neutral"]]

    assert families == {"tonal", "atmospheric", "temporal", "texture", "edge", "compositing"}
    assert effect_drift["pass_count"] == 6
    assert effect_drift["non_neutral_pass_count"] == 4
    assert len(active) == 4
    assert len(inactive) == 2
    assert effect_drift["dominant_family"] in families
    assert effect_drift["support_family"] in families
    assert all(
        item["fourth_wall_policy"] == "forbid_foreground_overlay" for item in effect_drift["passes"]
    )
    assert {"fast", "slow"} <= {item["eviction_cadence"] for item in effect_drift["passes"]}
    assert all(item["slot_intensity"] > 0 and item["max_delta"] > 0 for item in active)
    assert all(item["slot_intensity"] == 0 and item["max_delta"] == 0 for item in inactive)
    assert visual_chain["params"]["drift.amplitude"] > 0
    assert visual_chain["levels"]["visual_chain.spectral_color"] > 0
    assert len(plan["passes"]) == len(effect_drift["passes"])
    assert (
        module["DEFAULT_PLAN"].as_posix() == "/dev/shm/hapax-visual/screwm-effect-drift-plan.json"
    )
    assert (
        module["DEFAULT_EFFECT_DRIFT"].as_posix()
        == "/dev/shm/hapax-visual/screwm-effect-drift-fallback-state.json"
    )
    assert plan["consumer"] == "darkplaces-state-export"


def test_screwm_drift_state_source_writes_atomic_state_files(tmp_path: Path) -> None:
    module = _load_script()
    effect_path = tmp_path / "effect-drift-state.json"
    chain_path = tmp_path / "visual-chain-state.json"
    plan_path = tmp_path / "plan.json"
    args = module["parse_args"](
        [
            "--effect-drift",
            str(effect_path),
            "--visual-chain",
            str(chain_path),
            "--plan",
            str(plan_path),
            "--once",
        ]
    )

    assert module["run"](args) == 0

    effect_drift = json.loads(effect_path.read_text(encoding="utf-8"))
    visual_chain = json.loads(chain_path.read_text(encoding="utf-8"))
    assert effect_drift["source_presence"] == "synthetic-fallback-live-state-only"
    assert effect_drift["fallback_state"] is True
    assert effect_drift["route_authority"] == "screwm_darkplaces_synthetic_fallback"
    assert visual_chain["params"]["post.vignette_strength"] > 0
