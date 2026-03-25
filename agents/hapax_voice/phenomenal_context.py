"""Phenomenal context renderer — faithful rendering of temporal bands + self-band.

Not a compressor. The upstream structures (temporal bands, apperception cascade,
stimmung) already self-compress based on environmental state. This renderer
presents what survived at the available fidelity, preserving directional force.

Design principles (from multi-disciplinary research):
1. Render what's there — upstream already decided what matters
2. Orient, don't inform — the LLM should BE in a situation, not read ABOUT one
3. Progressive fidelity — truncation at any point leaves coherent orientation
4. Preserve coupling — don't decompose situations into independent facts
5. Stimmung first when non-nominal — global prior shapes everything
6. Never fabricate — absence is signal
7. One output, tiers consume what fits

The output is ordered by perceptual priority:
  1. Stimmung (non-nominal only) — global attunement
  2. Situation coupling — operator + system + environment in one breath
  3. Temporal impression + horizon — present and near-future
  4. Surprise/deviation — prediction errors (the interesting part)
  5. Temporal depth — retention, protention details
  6. Self-state — apperception when non-trivial

LOCAL naturally gets lines 1-3. FAST gets through 4-5. STRONG/CAPABLE get all.

References: Husserl (time-consciousness), Heidegger (ready-to-hand),
Merleau-Ponty (structural coupling), Dreyfus (absorbed coping),
Gibson (affordances), Friston (precision-weighting).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

_TEMPORAL_PATH = Path("/dev/shm/hapax-temporal/bands.json")
_APPERCEPTION_PATH = Path("/dev/shm/hapax-apperception/self-band.json")
_STIMMUNG_PATH = Path("/dev/shm/hapax-stimmung/state.json")

# Staleness thresholds (seconds)
_TEMPORAL_STALE_S = 30.0
_APPERCEPTION_STALE_S = 30.0
_STIMMUNG_STALE_S = 300.0


def _read_json(path: Path) -> dict | None:
    """Read a JSON file, returning None on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def render(tier: str = "CAPABLE") -> str:
    """Render phenomenal context for voice LLM injection.

    Returns a progressive-fidelity block of natural language that
    orients the LLM in the current experiential situation. The tier
    controls how much of the progressive output is returned.

    The upstream structures self-compress: calm environments produce
    sparse output, eventful ones produce rich output. This function
    renders faithfully — it does not add compression logic.
    """
    # Snapshot all sources once for cross-layer consistency
    stimmung_data = _read_json(_STIMMUNG_PATH)
    _raw_temporal = _read_json(_TEMPORAL_PATH)
    apperception_data = _read_json(_APPERCEPTION_PATH)

    # Parse temporal once: staleness check + XML parse
    temporal_data = _parse_temporal_snapshot(_raw_temporal)

    lines: list[str] = []

    # ── Layer 1: Stimmung (non-nominal only) ─────────────────────
    if s := _render_stimmung(stimmung_data):
        lines.append(s)

    # ── Layer 2: Situation coupling ──────────────────────────────
    if s := _render_situation(temporal_data):
        lines.append(s)

    # ── Layer 3: Temporal impression + horizon ───────────────────
    if s := _render_impression(temporal_data):
        lines.append(s)

    # LOCAL tier: return layers 1-3 (minimum viable orientation)
    if tier == "LOCAL":
        return "\n".join(lines) if lines else ""

    # ── Layer 4: Surprise / deviation ────────────────────────────
    if s := _render_surprise(temporal_data):
        lines.append(s)

    # ── Layer 5: Temporal depth (retention + protention) ─────────
    if s := _render_temporal_depth(temporal_data):
        lines.append(s)

    # FAST tier: return layers 1-5
    if tier == "FAST":
        return "\n".join(lines) if lines else ""

    # ── Layer 6: Self-state (apperception) ───────────────────────
    if s := _render_self_state(apperception_data):
        lines.append(s)

    # STRONG / CAPABLE: full progressive output
    return "\n".join(lines) if lines else ""


# ── Layer renderers ──────────────────────────────────────────────────────────


def _render_stimmung(data: dict | None) -> str:
    """Layer 1: System attunement. Empty when nominal (the common case)."""
    if data is None:
        return ""
    try:
        if (time.time() - data.get("timestamp", 0)) > _STIMMUNG_STALE_S:
            return ""
        stance = data.get("overall_stance", "nominal")
        if stance == "nominal":
            return ""
        if stance == "cautious":
            return "System cautious — conserve where possible."
        if stance == "degraded":
            return "System degraded — keep responses brief, avoid heavy processing."
        if stance == "critical":
            return "System critical — minimal responses only, essential information."
        return ""
    except Exception:
        return ""


def _render_situation(temporal: dict | None) -> str:
    """Layer 2: Coupled situation — operator + environment in one breath."""
    if temporal is None:
        return ""

    impression = temporal.get("impression", {})
    parts: list[str] = []

    # Time context
    hour = time.localtime().tm_hour
    if 5 <= hour < 12:
        period = "morning"
    elif 12 <= hour < 18:
        period = "afternoon"
    elif 18 <= hour < 23:
        period = "evening"
    else:
        period = "late night"

    # Activity + flow coupled
    activity = impression.get("activity", "")
    flow = impression.get("flow_state", "idle")
    presence = impression.get("presence", "")

    if presence == "away":
        parts.append(f"{period.capitalize()}, operator away")
    elif activity and activity != "idle":
        if flow == "active":
            parts.append(f"{period.capitalize()}, deep {activity}")
        elif flow == "warming":
            parts.append(f"{period.capitalize()}, settling into {activity}")
        else:
            parts.append(f"{period.capitalize()}, {activity}")
    else:
        parts.append(f"{period.capitalize()}, idle")

    return ", ".join(parts) + "." if parts else ""


def _render_impression(temporal: dict | None) -> str:
    """Layer 3: Present moment + nearest horizon.

    Couples impression with the highest-confidence protention to give
    a sense of direction, not just position.
    """
    if temporal is None:
        return ""

    impression = temporal.get("impression", {})
    protention = temporal.get("protention", [])

    parts: list[str] = []

    # Flow score as direction indicator
    flow_score = impression.get("flow_score", 0.0)
    if isinstance(flow_score, (int, float)) and flow_score > 0:
        parts.append(f"flow {flow_score:.0%}")

    # Heart rate if notable
    hr = impression.get("heart_rate", 0)
    if isinstance(hr, int) and hr > 0:
        parts.append(f"{hr}bpm")

    # Music
    genre = impression.get("music_genre", "")
    if genre:
        parts.append(genre)

    # Presence probability (precise)
    pp = impression.get("presence_probability")
    if pp is not None and isinstance(pp, (int, float)):
        if pp < 0.3:
            parts.append("away")
        elif pp < 0.7:
            parts.append("uncertain presence")

    # Nearest protention (direction, not position)
    if protention:
        best = max(protention, key=lambda p: p.get("confidence", 0))
        conf = best.get("confidence", 0)
        state = best.get("predicted_state", "")
        if conf >= 0.5 and state:
            readable = state.replace("_", " ")
            parts.append(f"→ {readable}")

    if not parts:
        return ""
    return " ".join(parts) + "."


def _render_surprise(temporal: dict | None) -> str:
    """Layer 4: Prediction errors. The most phenomenologically interesting signal.

    Only present when something was predicted and turned out wrong. Its mere
    presence in the rendering reorients the LLM.
    """
    if temporal is None:
        return ""

    surprises = temporal.get("surprises", [])
    if not surprises:
        return ""

    # Filter to meaningful surprises
    notable = [s for s in surprises if s.get("surprise", 0) > 0.3]
    if not notable:
        return ""

    parts: list[str] = []
    for s in notable[:2]:  # max 2 surprise notes
        observed = s.get("observed", "")
        expected = s.get("expected", "")
        field = s.get("field", "")
        if observed and expected:
            parts.append(f"unexpected {field}: {observed} (predicted {expected})")
        elif observed:
            parts.append(f"unexpected: {observed}")

    if not parts:
        return ""
    return "Surprise: " + "; ".join(parts) + "."


def _render_temporal_depth(temporal: dict | None) -> str:
    """Layer 5: Retention (fading past) + protention details.

    This adds temporal thickness — where things were and where they're going.
    Only for FAST+ tiers that can absorb it.
    """
    if temporal is None:
        return ""

    parts: list[str] = []

    # Retention entries (fading past)
    retention = temporal.get("retention", [])
    if retention:
        ret_parts: list[str] = []
        for r in retention:
            age = r.get("age_s", 0)
            summary = r.get("summary", "")
            presence = r.get("presence", "")
            if summary:
                note = f"{age:.0f}s ago: {summary}"
                if presence and presence != "present":
                    note += f" ({presence})"
                ret_parts.append(note)
        if ret_parts:
            parts.append("Was: " + " → ".join(ret_parts))

    # Protention details (beyond the single horizon in layer 3)
    protention = temporal.get("protention", [])
    if len(protention) > 1:
        preds = []
        for p in protention[:3]:
            state = p.get("predicted_state", "").replace("_", " ")
            conf = p.get("confidence", 0)
            if state and conf >= 0.3:
                preds.append(f"{state} ({conf:.0%})")
        if preds:
            parts.append("Next: " + ", ".join(preds))

    return " ".join(parts) if parts else ""


def _render_self_state(data: dict | None) -> str:
    """Layer 6: Apperceptive self-awareness.

    Renders what the system knows about its own processing reliability.
    The LLM uses this to calibrate its assertiveness — hedge where
    uncertain, speak directly where confident.

    Format follows ACT cognitive defusion: "I notice..." not "I am...".
    """
    if data is None:
        return ""
    try:
        if (time.time() - data.get("timestamp", 0)) > _APPERCEPTION_STALE_S:
            return ""
    except Exception:
        return ""

    model = data.get("self_model", {})
    dimensions = model.get("dimensions", {})
    coherence = model.get("coherence", 0.7)
    reflections = model.get("recent_reflections", [])
    pending = data.get("pending_actions", [])

    parts: list[str] = []

    # Coherence as behavioral instruction
    if coherence < 0.4:
        parts.append("Self-coherence low — hedge all observations, avoid confident claims.")
    elif coherence < 0.6:
        parts.append("Self-coherence settling — hedge where uncertain.")

    # Low-confidence dimensions: tell the LLM WHERE to hedge
    low_conf = [name for name, d in dimensions.items() if d.get("confidence", 0.5) < 0.35]
    if low_conf:
        domains = ", ".join(d.replace("_", " ") for d in low_conf[:3])
        parts.append(f"Uncertain about: {domains}.")

    # Active tension (most recent reflection)
    if reflections:
        parts.append(reflections[-1])

    # Pending action (if relevant)
    if pending:
        parts.append(pending[0])

    if not parts:
        return ""
    return " ".join(parts)


# ── Data readers ──────────────────────────────────────────────────────────────


def _clear_cache() -> None:
    """No-op. Previously cleared module-level cache globals (now removed).

    Retained for backward compatibility with existing tests.
    """


def _parse_temporal_snapshot(raw: dict | None) -> dict | None:
    """Apply staleness check and XML parse to a raw temporal dict.

    Returns None if raw is None, stale, or missing XML.
    """
    if raw is None:
        return None
    if (time.time() - raw.get("timestamp", 0)) > _TEMPORAL_STALE_S:
        return None
    xml = raw.get("xml", "")
    if not xml:
        return None
    return _parse_temporal_xml(xml, raw)


def _parse_temporal_xml(xml: str, raw: dict) -> dict:
    """Parse temporal bands XML into structured dict for rendering.

    Extracts retention, impression, protention, surprises into dicts
    so the renderers don't need to do XML parsing.
    """
    import re

    result: dict = {"retention": [], "impression": {}, "protention": [], "surprises": []}

    # Impression fields: <tag>value</tag> or <tag surprise="0.5" expected="foo">value</tag>
    impression_match = re.search(r"<impression>(.*?)</impression>", xml, re.DOTALL)
    if impression_match:
        imp_xml = impression_match.group(1)
        # Match tags with optional attributes in any order
        for m in re.finditer(r"<(\w+)([^>]*)>([^<]*)</\1>", imp_xml):
            tag, attrs, value = m.groups()
            result["impression"][tag] = value.strip()
            # Check for surprise attribute
            surprise_m = re.search(r'surprise="([^"]*)"', attrs)
            expected_m = re.search(r'expected="([^"]*)"', attrs)
            if surprise_m:
                surprise_val = float(surprise_m.group(1))
                if surprise_val > 0.3:
                    result["surprises"].append(
                        {
                            "field": tag,
                            "observed": value.strip(),
                            "expected": expected_m.group(1) if expected_m else "",
                            "surprise": surprise_val,
                        }
                    )

    # Retention: <memory age_s="5" flow="active" activity="coding" presence="present">summary</memory>
    for m in re.finditer(r"<memory([^>]*)>([^<]*)</memory>", xml):
        attrs, summary = m.groups()
        age_m = re.search(r'age_s="([^"]*)"', attrs)
        flow_m = re.search(r'flow="([^"]*)"', attrs)
        activity_m = re.search(r'activity="([^"]*)"', attrs)
        presence_m = re.search(r'presence="([^"]*)"', attrs)
        result["retention"].append(
            {
                "age_s": float(age_m.group(1)) if age_m else 0.0,
                "flow_state": flow_m.group(1) if flow_m else "",
                "activity": activity_m.group(1) if activity_m else "",
                "presence": presence_m.group(1) if presence_m else "",
                "summary": summary.strip(),
            }
        )

    # Protention: <prediction state="entering_deep_work" confidence="0.72">basis</prediction>
    for m in re.finditer(
        r'<prediction\s+state="([^"]*)"\s+confidence="([^"]*)">([^<]*)</prediction>',
        xml,
    ):
        state, confidence, basis = m.groups()
        result["protention"].append(
            {
                "predicted_state": state,
                "confidence": float(confidence),
                "basis": basis.strip(),
            }
        )

    # Add raw surprise data if not already captured from impression annotations
    max_surprise = raw.get("max_surprise", 0.0)
    if max_surprise > 0.3 and not result["surprises"]:
        # Surprises may be in separate tags
        for m in re.finditer(r'<surprise[^>]*observed="([^"]*)"', xml):
            result["surprises"].append(
                {
                    "field": "observation",
                    "observed": m.group(1),
                    "expected": "",
                    "surprise": max_surprise,
                }
            )

    return result
