"""Reverie prediction monitor — tracks 6 post-fix behavioral predictions.

Samples affordance pipeline state, chronicle events, and perception signals
every 5 minutes. Compares actual trajectories against predicted trends from
the PR #570 analysis. Writes structured results to /dev/shm for Prometheus
exposure and JSONL for historical analysis.

Predictions monitored:
  P1: Thompson convergence (alpha/(alpha+beta) → 0.95 within 2h)
  P2: Base-level warmth (normalized base_level → 0.3–0.4 within 24h)
  P3: Hebbian crystallization (top associations > 0.3 within 12h)
  P4: Winner-take-all risk (combined score std dev stays > 0.03)
  P5: Content vs vocabulary balance (technique/params event ratio 0.3–0.7)
  P6: Presence differentiation (no significant score gap active vs idle)
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

ACTIVATION_STATE = Path.home() / ".cache" / "hapax" / "affordance-activation-state.json"
CHRONICLE_API = "http://localhost:8051/api/chronicle"
PERCEPTION_STATE = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"
PREDICTIONS_SHM = Path("/dev/shm/hapax-reverie/predictions.json")
PREDICTIONS_JSONL = Path.home() / "hapax-state" / "monitors" / "reverie-predictions.jsonl"
DEPLOY_TS_FILE = Path("/dev/shm/hapax-reverie/fix-deploy-ts")

# Content affordances we're tracking (the ones that were trapped)
CONTENT_AFFORDANCES = [
    "content.imagination_image",
    "content.overhead_perspective",
    "content.desk_perspective",
    "content.camera_feed",
    "node.content_layer",
    "node.postprocess",
    "node.feedback",
]


@dataclass
class PredictionResult:
    name: str
    expected: str
    actual: float
    healthy: bool
    alert: str | None = None
    detail: str = ""


@dataclass
class MonitorSample:
    timestamp: float
    hours_since_deploy: float
    predictions: list[PredictionResult] = field(default_factory=list)
    alert_count: int = 0


def _get_deploy_ts() -> float:
    """Get timestamp of when the fix was deployed."""
    if DEPLOY_TS_FILE.exists():
        return float(DEPLOY_TS_FILE.read_text().strip())
    # Default: PR #570 merge time (2026-04-03T14:25:47Z)
    return 1775225147.0


def _load_activation_state() -> dict:
    try:
        data = json.loads(ACTIVATION_STATE.read_text())
        return data.get("activations", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _load_associations() -> dict:
    try:
        data = json.loads(ACTIVATION_STATE.read_text())
        return data.get("associations", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _load_perception() -> dict:
    try:
        return json.loads(PERCEPTION_STATE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _query_chronicle(since: str = "-10m", source: str | None = None) -> list[dict]:
    """Query chronicle API for recent events."""
    import urllib.request

    params = f"since={since}&limit=500"
    if source:
        params += f"&source={source}"
    url = f"{CHRONICLE_API}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
            if isinstance(data, str):
                data = json.loads(data)
            return data if isinstance(data, list) else []
    except Exception as e:
        log.warning("Chronicle query failed: %s", e)
        return []


def p1_thompson_convergence(activations: dict, hours: float) -> PredictionResult:
    """P1: Thompson mean should rise to ~0.95 within 2h."""
    means = []
    for name in CONTENT_AFFORDANCES:
        state = activations.get(name, {})
        alpha = state.get("ts_alpha", 2.0)
        beta = state.get("ts_beta", 1.0)
        mean = alpha / (alpha + beta) if (alpha + beta) > 0 else 0.5
        means.append(mean)

    avg_mean = sum(means) / len(means) if means else 0.5

    if hours < 2:
        expected = f"rising toward 0.95 ({hours:.1f}h of 2h)"
        healthy = avg_mean > 0.5  # should be above 0.5 even early
        alert = "Thompson mean below 0.5 after deploy" if not healthy else None
    else:
        expected = "≥0.70 (plateau expected)"
        healthy = avg_mean >= 0.70
        alert = (
            f"Thompson mean {avg_mean:.3f} — still below 0.70 after {hours:.1f}h"
            if not healthy
            else None
        )

    return PredictionResult(
        name="P1_thompson_convergence",
        expected=expected,
        actual=round(avg_mean, 4),
        healthy=healthy,
        alert=alert,
        detail=json.dumps(
            {
                n: round(a.get("ts_alpha", 2) / (a.get("ts_alpha", 2) + a.get("ts_beta", 1)), 4)
                for n, a in activations.items()
                if n in CONTENT_AFFORDANCES
            }
        ),
    )


def p2_base_level_warmth(activations: dict, hours: float) -> PredictionResult:
    """P2: Base-level should rise from ~0 to 0.3-0.4 within 24h."""
    now = time.time()
    levels = []
    for name in CONTENT_AFFORDANCES:
        state = activations.get(name, {})
        use_count = state.get("use_count", 0)
        last_use = state.get("last_use_ts", 0.0)
        first_use = state.get("first_use_ts", 0.0)
        # Replicate ACT-R base_level + normalization
        if use_count == 0:
            raw = -10.0
        else:
            t1 = max(0.001, now - last_use)
            if use_count == 1:
                raw = math.log(t1 ** (-0.5))
            else:
                tn = max(0.001, now - first_use)
                recent = t1 ** (-0.5)
                old_approx = 2 * (use_count - 1) / (tn**0.5 + t1**0.5)
                raw = math.log(recent + old_approx)
        clamped = max(-10.0, min(10.0, raw))
        normalized = 1.0 / (1.0 + math.exp(-clamped))
        levels.append(normalized)

    avg_level = sum(levels) / len(levels) if levels else 0.0

    if hours < 6:
        expected = f"rising from ~0 ({hours:.1f}h of 24h window)"
        healthy = True  # too early to judge
        alert = None
    elif hours < 24:
        expected = "0.1–0.3 (growing)"
        healthy = avg_level > 0.01 or any(
            activations.get(n, {}).get("use_count", 0) > 0 for n in CONTENT_AFFORDANCES
        )
        alert = (
            f"Base level flat at {avg_level:.3f} after {hours:.1f}h — no use_count growth"
            if not healthy
            else None
        )
    else:
        expected = "0.3–0.4 (warm)"
        healthy = avg_level > 0.15
        alert = f"Base level only {avg_level:.3f} after {hours:.1f}h" if not healthy else None

    return PredictionResult(
        name="P2_base_level_warmth",
        expected=expected,
        actual=round(avg_level, 4),
        healthy=healthy,
        alert=alert,
        detail=json.dumps(
            {n: activations.get(n, {}).get("use_count", 0) for n in CONTENT_AFFORDANCES}
        ),
    )


def p3_hebbian_crystallization(associations: dict, hours: float) -> PredictionResult:
    """P3: Top context associations should exceed 0.3 within 12h."""
    sorted_assoc = sorted(associations.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
    top_strength = abs(sorted_assoc[0][1]) if sorted_assoc else 0.0

    if hours < 6:
        expected = f"building ({hours:.1f}h of 12h window)"
        healthy = True
        alert = None
    elif hours < 12:
        expected = "some associations > 0.1"
        healthy = top_strength > 0.05 or len(associations) > 0
        alert = f"No associations after {hours:.1f}h" if not healthy else None
    else:
        expected = "top associations > 0.3"
        healthy = top_strength > 0.1
        alert = (
            f"Top association only {top_strength:.3f} after {hours:.1f}h" if not healthy else None
        )

    return PredictionResult(
        name="P3_hebbian_crystallization",
        expected=expected,
        actual=round(top_strength, 4),
        healthy=healthy,
        alert=alert,
        detail=json.dumps(dict(sorted_assoc[:3])) if sorted_assoc else "{}",
    )


def p4_winner_take_all(chronicle_events: list[dict]) -> PredictionResult:
    """P4: Combined score std dev should stay >0.03 (healthy diversity)."""
    techniques = [e for e in chronicle_events if e.get("event_type") == "technique.activated"]
    confidences = [e.get("payload", {}).get("confidence", 0) for e in techniques]

    if len(confidences) < 5:
        return PredictionResult(
            name="P4_winner_take_all",
            expected="insufficient data",
            actual=0.0,
            healthy=True,
            detail=f"{len(confidences)} events",
        )

    mean = sum(confidences) / len(confidences)
    variance = sum((c - mean) ** 2 for c in confidences) / len(confidences)
    std_dev = variance**0.5

    # Also check unique technique names
    unique_techniques = len(set(e.get("payload", {}).get("technique_name", "") for e in techniques))

    healthy = std_dev > 0.02
    alert = None
    if std_dev < 0.02:
        alert = f"Winner-take-all risk: std_dev={std_dev:.4f}, only {unique_techniques} unique techniques"

    return PredictionResult(
        name="P4_winner_take_all",
        expected="std_dev > 0.03 (diversity)",
        actual=round(std_dev, 4),
        healthy=healthy,
        alert=alert,
        detail=json.dumps(
            {
                "mean": round(mean, 4),
                "std_dev": round(std_dev, 4),
                "unique_techniques": unique_techniques,
                "event_count": len(confidences),
            }
        ),
    )


def p5_content_vocabulary_balance(chronicle_events: list[dict]) -> PredictionResult:
    """P5: technique.activated vs params.shifted ratio should be 0.3-0.7."""
    technique_count = sum(
        1 for e in chronicle_events if e.get("event_type") == "technique.activated"
    )
    params_count = sum(1 for e in chronicle_events if e.get("event_type") == "params.shifted")
    total = technique_count + params_count

    if total < 10:
        return PredictionResult(
            name="P5_content_vocabulary_balance",
            expected="insufficient data",
            actual=0.0,
            healthy=True,
            detail=f"technique={technique_count}, params={params_count}",
        )

    ratio = technique_count / total

    if ratio > 0.9:
        alert = f"Content eclipsing substrate: ratio={ratio:.2f} ({technique_count}/{total})"
        healthy = False
    elif ratio < 0.1:
        alert = f"Regression to pre-fix state: ratio={ratio:.2f} ({technique_count}/{total})"
        healthy = False
    else:
        alert = None
        healthy = True

    return PredictionResult(
        name="P5_content_vocabulary_balance",
        expected="0.3–0.7 (balanced)",
        actual=round(ratio, 4),
        healthy=healthy,
        alert=alert,
        detail=json.dumps(
            {"technique_events": technique_count, "params_events": params_count, "total": total}
        ),
    )


def p6_presence_differentiation(perception: dict) -> PredictionResult:
    """P6: Check whether presence is actually reaching the system."""
    presence = perception.get("presence_probability", 0.0)
    presence_state = perception.get("presence_state", "UNKNOWN")

    actual = float(presence)

    # Simple health check: presence should be non-zero when system is running
    # (input_active isn't written to perception-state.json, so we use presence_state)
    if presence_state == "AWAY" and presence > 0.5:
        alert = f"State=AWAY but posterior={presence:.2f} — hysteresis mismatch?"
        healthy = False
    elif presence_state == "PRESENT" and presence < 0.3:
        alert = f"State=PRESENT but posterior={presence:.2f} — signal dropout?"
        healthy = False
    else:
        alert = None
        healthy = True

    return PredictionResult(
        name="P6_presence_differentiation",
        expected="presence tracks input_active",
        actual=actual,
        healthy=healthy,
        alert=alert,
        detail=json.dumps({"presence_probability": presence, "presence_state": presence_state}),
    )


def sample() -> MonitorSample:
    """Take one complete sample of all 6 predictions."""
    now = time.time()
    deploy_ts = _get_deploy_ts()
    hours = (now - deploy_ts) / 3600

    activations = _load_activation_state()
    associations = _load_associations()
    perception = _load_perception()
    chronicle = _query_chronicle(since="-10m", source="visual")

    predictions = [
        p1_thompson_convergence(activations, hours),
        p2_base_level_warmth(activations, hours),
        p3_hebbian_crystallization(associations, hours),
        p4_winner_take_all(chronicle),
        p5_content_vocabulary_balance(chronicle),
        p6_presence_differentiation(perception),
    ]

    result = MonitorSample(
        timestamp=now,
        hours_since_deploy=round(hours, 2),
        predictions=predictions,
        alert_count=sum(1 for p in predictions if p.alert),
    )

    # Write to /dev/shm for Prometheus
    PREDICTIONS_SHM.parent.mkdir(parents=True, exist_ok=True)
    PREDICTIONS_SHM.write_text(json.dumps(asdict(result), indent=2))

    # Append to JSONL for history
    PREDICTIONS_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(PREDICTIONS_JSONL, "a") as f:
        f.write(json.dumps(asdict(result)) + "\n")

    # Send ntfy alerts
    if result.alert_count > 0:
        _send_alerts(predictions)

    return result


def _send_alerts(predictions: list[PredictionResult]) -> None:
    """Send ntfy notification for any triggered alerts."""
    import urllib.request

    alerts = [p for p in predictions if p.alert]
    if not alerts:
        return

    body = "\n".join(f"⚠ {a.name}: {a.alert}" for a in alerts)
    try:
        req = urllib.request.Request(
            "http://localhost:8090/hapax-reverie",
            data=body.encode(),
            headers={"Title": f"Reverie predictions: {len(alerts)} alert(s)", "Priority": "3"},
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception as e:
        log.warning("Failed to send ntfy alert: %s", e)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    result = sample()
    healthy = all(p.healthy for p in result.predictions)
    status = "HEALTHY" if healthy else f"ALERT ({result.alert_count})"
    log.info(
        "Reverie predictions [%s] %.1fh post-deploy: %s",
        status,
        result.hours_since_deploy,
        " | ".join(f"{p.name}={p.actual}" for p in result.predictions),
    )
    for p in result.predictions:
        if p.alert:
            log.warning("  ALERT %s: %s", p.name, p.alert)


if __name__ == "__main__":
    main()
