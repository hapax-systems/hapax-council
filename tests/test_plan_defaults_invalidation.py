"""Test that plan defaults cache invalidates when plan.json changes."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from agents.reverie._uniforms import _load_plan_defaults


def test_cache_invalidates_on_mtime_change():
    with tempfile.TemporaryDirectory() as td:
        plan_path = Path(td) / "plan.json"
        plan_v1 = {
            "passes": [
                {"node_id": "noise", "uniforms": {"amplitude": 0.7}, "param_order": ["amplitude"]}
            ]
        }
        plan_path.write_text(json.dumps(plan_v1))

        with patch("agents.reverie._uniforms.PLAN_FILE", plan_path):
            # Force cache clear
            import agents.reverie._uniforms as mod

            mod._plan_defaults_cache = None
            mod._plan_defaults_mtime = 0.0

            defaults1 = _load_plan_defaults()
            assert defaults1["noise.amplitude"] == 0.7

            # Write new plan with different value
            plan_v2 = {
                "passes": [
                    {
                        "node_id": "noise",
                        "uniforms": {"amplitude": 0.9},
                        "param_order": ["amplitude"],
                    },
                    {
                        "node_id": "sat_echo",
                        "uniforms": {"delay": 0.5},
                        "param_order": ["delay"],
                    },
                ]
            }
            plan_path.write_text(json.dumps(plan_v2))

            defaults2 = _load_plan_defaults()
            assert defaults2["noise.amplitude"] == 0.9
            assert defaults2["sat_echo.delay"] == 0.5
