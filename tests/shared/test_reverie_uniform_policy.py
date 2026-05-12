from __future__ import annotations

from shared.reverie_uniform_policy import (
    clamp_reverie_live_uniforms,
    reverie_uniform_bound_violations,
)


def test_reverie_live_uniform_policy_bounds_generated_substrate() -> None:
    values = {
        "noise.amplitude": 0.85,
        "content.salience": 0.6,
        "content.intensity": 0.6,
        "post.vignette_strength": 0.4,
        "post.sediment_strength": 0.08,
        "post.master_opacity": 0.2,
        "fb.trace_strength": 0.8,
    }

    bounded = clamp_reverie_live_uniforms(values)

    assert bounded["noise.amplitude"] == 0.25
    assert bounded["content.salience"] == 0.35
    assert bounded["content.intensity"] == 0.35
    assert bounded["post.vignette_strength"] == 0.25
    assert bounded["post.sediment_strength"] == 0.05
    assert bounded["post.master_opacity"] == 0.85
    assert bounded["fb.trace_strength"] == 0.25


def test_reverie_live_uniform_policy_reports_violations() -> None:
    violations = reverie_uniform_bound_violations(
        {
            "noise.amplitude": 0.85,
            "color.saturation": 0.4,
        }
    )

    assert violations == {"noise.amplitude": {"value": 0.85, "bounded": 0.25}}
