"""Reverie prediction monitor + live operational metrics.

Prediction summaries from /dev/shm/hapax-reverie/predictions.json (5-min timer).
Live operational metrics from uniforms, perception state, and chronicle (real-time).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Response

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/predictions", tags=["predictions"])

PREDICTIONS_SHM = Path("/dev/shm/hapax-reverie/predictions.json")
UNIFORMS_FILE = Path("/dev/shm/hapax-imagination/uniforms.json")
PERCEPTION_STATE = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"
CHRONICLE_DIR = Path("/dev/shm/hapax-chronicle")


def _read_predictions() -> dict:
    try:
        return json.loads(PREDICTIONS_SHM.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


@router.get("")
async def get_predictions() -> dict:
    """Return latest prediction monitor sample as JSON."""
    return _read_predictions()


@router.get("/metrics")
async def predictions_metrics() -> Response:
    """Expose prediction metrics in Prometheus text format."""
    data = _read_predictions()
    if not data:
        return Response("# no prediction data available\n", media_type="text/plain")

    lines: list[str] = []
    lines.append("# HELP reverie_prediction_actual Current actual value of each prediction metric")
    lines.append("# TYPE reverie_prediction_actual gauge")
    lines.append(
        "# HELP reverie_prediction_healthy Whether prediction is within expected range (1=yes)"
    )
    lines.append("# TYPE reverie_prediction_healthy gauge")
    lines.append("# HELP reverie_hours_since_deploy Hours elapsed since PR #570 deployment")
    lines.append("# TYPE reverie_hours_since_deploy gauge")
    lines.append("# HELP reverie_alert_count Number of active prediction alerts")
    lines.append("# TYPE reverie_alert_count gauge")

    hours = data.get("hours_since_deploy", 0)
    lines.append(f"reverie_hours_since_deploy {hours}")
    lines.append(f"reverie_alert_count {data.get('alert_count', 0)}")

    for p in data.get("predictions", []):
        name = p.get("name", "unknown")
        actual = p.get("actual", 0)
        healthy = 1 if p.get("healthy", False) else 0
        lines.append(f'reverie_prediction_actual{{prediction="{name}"}} {actual}')
        lines.append(f'reverie_prediction_healthy{{prediction="{name}"}} {healthy}')

    # --- Live operational metrics (real-time, not from timer) ---

    # Shader uniforms: per-parameter deviation from vocabulary defaults
    _VOCAB_DEFAULTS = {
        "color.brightness": 1.0,
        "color.saturation": 1.0,
        "color.hue_rotate": 0.0,
        "noise.amplitude": 0.7,
        "noise.frequency_x": 1.5,
        "fb.hue_shift": 0.0,
        "post.vignette_strength": 0.35,
    }
    lines.append("# HELP reverie_uniform_value Current shader uniform value")
    lines.append("# TYPE reverie_uniform_value gauge")
    lines.append("# HELP reverie_uniform_deviation Deviation from vocabulary default")
    lines.append("# TYPE reverie_uniform_deviation gauge")
    try:
        uniforms = json.loads(UNIFORMS_FILE.read_text())
        for param, default in _VOCAB_DEFAULTS.items():
            val = uniforms.get(param)
            if val is not None and isinstance(val, (int, float)):
                lines.append(f'reverie_uniform_value{{param="{param}"}} {val}')
                lines.append(
                    f'reverie_uniform_deviation{{param="{param}"}} {abs(val - default):.6f}'
                )
    except Exception:
        pass

    # Presence signals: individual signal states
    lines.append(
        "# HELP reverie_presence_signal Individual presence signal value (1=active, 0=inactive)"
    )
    lines.append("# TYPE reverie_presence_signal gauge")
    lines.append("# HELP reverie_presence_posterior Bayesian presence posterior")
    lines.append("# TYPE reverie_presence_posterior gauge")
    _PRESENCE_SIGNALS = [
        "presence_probability",
        "presence_state",
        "desk_activity",
        "desk_energy",
        "ir_hand_activity",
        "ir_motion_delta",
        "ir_person_detected",
        "ir_person_count",
    ]
    try:
        perception = json.loads(PERCEPTION_STATE.read_text())
        pp = perception.get("presence_probability", 0)
        lines.append(f"reverie_presence_posterior {pp}")
        # Desk energy (continuous 0-1)
        de = perception.get("desk_energy", 0)
        lines.append(f'reverie_presence_signal{{signal="desk_energy"}} {de}')
        # IR motion (continuous)
        motion = perception.get("ir_motion_delta", 0)
        lines.append(f'reverie_presence_signal{{signal="ir_motion_delta"}} {motion}')
        # Binary signals
        for sig in ["ir_hand_activity", "desk_activity"]:
            val = perception.get(sig, "idle")
            active = 1 if isinstance(val, str) and val not in ("idle", "none", "unknown", "") else 0
            lines.append(f'reverie_presence_signal{{signal="{sig}"}} {active}')
        ir_persons = perception.get("ir_person_count", 0)
        lines.append(f'reverie_presence_signal{{signal="ir_person_count"}} {ir_persons}')
    except Exception:
        pass

    # Chronicle technique confidence: last 60s of activations
    lines.append("# HELP reverie_technique_confidence Last recruitment confidence per technique")
    lines.append("# TYPE reverie_technique_confidence gauge")
    lines.append("# HELP reverie_technique_rate Activations per minute per technique")
    lines.append("# TYPE reverie_technique_rate gauge")
    try:
        events_file = CHRONICLE_DIR / "events.jsonl"
        if events_file.exists():
            now = time.time()
            cutoff = now - 60.0
            technique_last: dict[str, float] = {}
            technique_count: dict[str, int] = {}
            with open(events_file) as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if e.get("source") != "visual" or e.get("event_type") != "technique.activated":
                        continue
                    ts = e.get("ts", 0)
                    if ts < cutoff:
                        continue
                    name = e.get("payload", {}).get("technique_name", "")
                    conf = e.get("payload", {}).get("confidence", 0)
                    if name:
                        technique_last[name] = conf
                        technique_count[name] = technique_count.get(name, 0) + 1
            for name, conf in technique_last.items():
                lines.append(f'reverie_technique_confidence{{technique="{name}"}} {conf}')
            elapsed = min(60.0, now - cutoff)
            for name, count in technique_count.items():
                rate = count / elapsed * 60 if elapsed > 0 else 0
                lines.append(f'reverie_technique_rate{{technique="{name}"}} {rate:.2f}')
    except Exception:
        pass

    # --- ALL shader uniforms (replacing 7-param subset) ---
    lines.append("# HELP hapax_uniform_value Current shader uniform value")
    lines.append("# TYPE hapax_uniform_value gauge")
    lines.append("# HELP hapax_uniform_deviation Deviation from plan default")
    lines.append("# TYPE hapax_uniform_deviation gauge")
    try:
        uniforms = json.loads(UNIFORMS_FILE.read_text())
        # Load plan defaults for deviation calculation
        plan_defaults: dict[str, float] = {}
        plan_path = Path("/dev/shm/hapax-imagination/pipeline/plan.json")
        try:
            plan = json.loads(plan_path.read_text())
            for p in plan.get("passes", []):
                nid = p.get("node_id", "")
                for k, v in p.get("uniforms", {}).items():
                    if isinstance(v, (int, float)):
                        plan_defaults[f"{nid}.{k}"] = float(v)
        except Exception:
            pass
        for param, val in sorted(uniforms.items()):
            if isinstance(val, (int, float)):
                lines.append(f'hapax_uniform_value{{param="{param}"}} {val}')
                default = plan_defaults.get(param, 0.0)
                lines.append(f'hapax_uniform_deviation{{param="{param}"}} {abs(val - default):.6f}')
    except Exception:
        pass

    # --- Stimmung dimensions ---
    lines.append("# HELP hapax_stimmung_value Stimmung dimension value (0=healthy, 1=stressed)")
    lines.append("# TYPE hapax_stimmung_value gauge")
    lines.append("# HELP hapax_stimmung_freshness_s Seconds since dimension was last updated")
    lines.append("# TYPE hapax_stimmung_freshness_s gauge")
    lines.append(
        "# HELP hapax_stimmung_stance"
        " Overall stance (0=nominal, 0.1=seeking, 0.25=cautious, 0.5=degraded, 1=critical)"
    )
    lines.append("# TYPE hapax_stimmung_stance gauge")
    try:
        stimmung_path = Path("/dev/shm/hapax-stimmung/state.json")
        stimmung = json.loads(stimmung_path.read_text())
        stance_map = {
            "nominal": 0.0,
            "seeking": 0.1,
            "cautious": 0.25,
            "degraded": 0.5,
            "critical": 1.0,
        }
        stance = stimmung.get("overall_stance", "nominal")
        lines.append(f"hapax_stimmung_stance {stance_map.get(stance, 0.0)}")
        for key, val in stimmung.items():
            if isinstance(val, dict) and "value" in val:
                v = val.get("value", 0)
                fresh = val.get("freshness_s", 999)
                lines.append(f'hapax_stimmung_value{{dimension="{key}"}} {v}')
                lines.append(f'hapax_stimmung_freshness_s{{dimension="{key}"}} {fresh}')
    except Exception:
        pass

    # --- SCM Mesh Health (14 components) ---
    lines.append("# HELP hapax_mesh_error PCT control loop error per component")
    lines.append("# TYPE hapax_mesh_error gauge")
    lines.append("# HELP hapax_mesh_perception PCT perception value per component")
    lines.append("# TYPE hapax_mesh_perception gauge")
    try:
        shm = Path("/dev/shm")
        for health_file in sorted(shm.glob("hapax-*/health.json")):
            comp = health_file.parent.name.removeprefix("hapax-")
            try:
                h = json.loads(health_file.read_text())
                err = h.get("error", 0)
                perc = h.get("perception", 0)
                lines.append(f'hapax_mesh_error{{component="{comp}"}} {err}')
                lines.append(f'hapax_mesh_perception{{component="{comp}"}} {perc}')
            except Exception:
                pass
    except Exception:
        pass

    # --- Exploration signals (14 components) ---
    lines.append("# HELP hapax_exploration_boredom Boredom index per component (0-1)")
    lines.append("# TYPE hapax_exploration_boredom gauge")
    lines.append("# HELP hapax_exploration_curiosity Curiosity index per component (0-1)")
    lines.append("# TYPE hapax_exploration_curiosity gauge")
    lines.append("# HELP hapax_exploration_error Chronic error per component (0-1)")
    lines.append("# TYPE hapax_exploration_error gauge")
    lines.append("# HELP hapax_exploration_stagnation_s Stagnation duration per component")
    lines.append("# TYPE hapax_exploration_stagnation_s gauge")
    lines.append("# HELP hapax_exploration_coherence Local coherence per component (0-1)")
    lines.append("# TYPE hapax_exploration_coherence gauge")
    try:
        explore_dir = Path("/dev/shm/hapax-exploration")
        if explore_dir.exists():
            for ef in sorted(explore_dir.glob("*.json")):
                comp = ef.stem
                try:
                    ed = json.loads(ef.read_text())
                    lines.append(
                        f'hapax_exploration_boredom{{component="{comp}"}}'
                        f" {ed.get('boredom_index', 0)}"
                    )
                    lines.append(
                        f'hapax_exploration_curiosity{{component="{comp}"}}'
                        f" {ed.get('curiosity_index', 0)}"
                    )
                    lines.append(
                        f'hapax_exploration_error{{component="{comp}"}}'
                        f" {ed.get('chronic_error', 0)}"
                    )
                    lines.append(
                        f'hapax_exploration_stagnation_s{{component="{comp}"}}'
                        f" {ed.get('stagnation_duration', 0)}"
                    )
                    lines.append(
                        f'hapax_exploration_coherence{{component="{comp}"}}'
                        f" {ed.get('local_coherence', 0)}"
                    )
                except Exception:
                    pass
    except Exception:
        pass

    # --- Imagination current fragment ---
    lines.append("# HELP hapax_imagination_dimension Current imagination dimension value (0-1)")
    lines.append("# TYPE hapax_imagination_dimension gauge")
    lines.append("# HELP hapax_imagination_salience Current fragment salience (0-1)")
    lines.append("# TYPE hapax_imagination_salience gauge")
    lines.append(
        "# HELP hapax_imagination_continuation Whether fragment continues previous thought (0/1)"
    )
    lines.append("# TYPE hapax_imagination_continuation gauge")
    try:
        imag_path = Path("/dev/shm/hapax-imagination/current.json")
        imag = json.loads(imag_path.read_text())
        lines.append(f"hapax_imagination_salience {imag.get('salience', 0)}")
        lines.append(f"hapax_imagination_continuation {1 if imag.get('continuation') else 0}")
        for dim, val in sorted(imag.get("dimensions", {}).items()):
            if isinstance(val, (int, float)):
                lines.append(f'hapax_imagination_dimension{{dim="{dim}"}} {val}')
    except Exception:
        pass

    # --- DMN status ---
    lines.append("# HELP hapax_dmn_buffer_entries DMN observation buffer depth")
    lines.append("# TYPE hapax_dmn_buffer_entries gauge")
    lines.append("# HELP hapax_dmn_tick Total DMN ticks since start")
    lines.append("# TYPE hapax_dmn_tick counter")
    lines.append("# HELP hapax_dmn_uptime_s DMN uptime in seconds")
    lines.append("# TYPE hapax_dmn_uptime_s gauge")
    try:
        dmn_path = Path("/dev/shm/hapax-dmn/status.json")
        dmn = json.loads(dmn_path.read_text())
        lines.append(f"hapax_dmn_buffer_entries {dmn.get('buffer_entries', 0)}")
        lines.append(f"hapax_dmn_tick {dmn.get('tick', 0)}")
        lines.append(f"hapax_dmn_uptime_s {dmn.get('uptime_s', 0):.1f}")
    except Exception:
        pass
    # Visual salience
    try:
        vs_path = Path("/dev/shm/hapax-dmn/visual-salience.json")
        vs = json.loads(vs_path.read_text())
        lines.append("# HELP hapax_dmn_satellites_active Number of recruited satellite nodes")
        lines.append("# TYPE hapax_dmn_satellites_active gauge")
        lines.append(f"hapax_dmn_satellites_active {vs.get('satellites_active', 0)}")
    except Exception:
        pass

    # --- CPAL conversation state ---
    lines.append("# HELP hapax_cpal_gain CPAL loop gain (0-1)")
    lines.append("# TYPE hapax_cpal_gain gauge")
    lines.append("# HELP hapax_cpal_error CPAL error decomposition")
    lines.append("# TYPE hapax_cpal_error gauge")
    try:
        cpal_path = Path("/dev/shm/hapax-conversation/state.json")
        cpal = json.loads(cpal_path.read_text())
        lines.append(f"hapax_cpal_gain {cpal.get('gain', 0)}")
        for domain in ["comprehension", "affective", "temporal", "magnitude"]:
            val = cpal.get(domain, 0)
            lines.append(f'hapax_cpal_error{{domain="{domain}"}} {val}')
    except Exception:
        pass

    # --- Thompson sampling state (top 30 by use_count) ---
    lines.append("# HELP hapax_thompson_mean Thompson sampling mean per capability")
    lines.append("# TYPE hapax_thompson_mean gauge")
    lines.append("# HELP hapax_capability_uses Total activations per capability")
    lines.append("# TYPE hapax_capability_uses gauge")
    try:
        act_path = Path.home() / ".cache" / "hapax" / "affordance-activation-state.json"
        act_data = json.loads(act_path.read_text())
        acts = act_data.get("activations", {})
        by_use = sorted(acts.items(), key=lambda x: x[1].get("use_count", 0), reverse=True)
        for name, state in by_use[:30]:
            alpha = state.get("ts_alpha", 2.0)
            beta = state.get("ts_beta", 1.0)
            total = alpha + beta
            mean = alpha / total if total > 0 else 0.5
            lines.append(f'hapax_thompson_mean{{capability="{name}"}} {mean:.4f}')
            lines.append(
                f'hapax_capability_uses{{capability="{name}"}} {state.get("use_count", 0)}'
            )
        # Total associations
        assoc_count = len(act_data.get("associations", {}))
        lines.append("# HELP hapax_hebbian_associations Total learned context associations")
        lines.append("# TYPE hapax_hebbian_associations gauge")
        lines.append(f"hapax_hebbian_associations {assoc_count}")
    except Exception:
        pass

    # --- Active content sources ---
    lines.append(
        "# HELP hapax_content_sources_active Number of active content sources on visual surface"
    )
    lines.append("# TYPE hapax_content_sources_active gauge")
    try:
        sources_dir = Path("/dev/shm/hapax-imagination/sources")
        count = 0
        if sources_dir.exists():
            for sd in sources_dir.iterdir():
                if sd.is_dir() and (sd / "manifest.json").exists():
                    count += 1
        lines.append(f"hapax_content_sources_active {count}")
    except Exception:
        pass

    # --- Feature flags ---
    lines.append("# HELP hapax_feature_flag Feature flag status (1=enabled)")
    lines.append("# TYPE hapax_feature_flag gauge")
    world_flag = Path.home() / ".cache" / "hapax" / "world-routing-enabled"
    lines.append(f'hapax_feature_flag{{flag="world_routing"}} {1 if world_flag.exists() else 0}')

    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
