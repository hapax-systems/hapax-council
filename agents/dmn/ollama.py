"""DMN Ollama inference helpers and system prompts."""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger("dmn.pulse")

OLLAMA_URL = "http://localhost:11434/api/generate"
DMN_MODEL = "qwen3.5:4b"

SENSORY_SYSTEM = (
    "You are a continuous situation monitor. Report WHAT is happening in one sentence. "
    "Never explain WHY. Never evaluate quality. Never use abstract language. "
    "Format: one concrete sentence describing the current state."
)
EVALUATIVE_SYSTEM = (
    "You are a value trajectory assessor. Given the current state and what changed, "
    "report whether the situation is IMPROVING, DEGRADING, or STABLE. "
    "If degrading, state the specific concern in concrete terms (what is wrong, not why). "
    'Format: "Trajectory: [improving|degrading|stable]. Concern: [specific issue or none]" '
    "Never evaluate your own performance. Never use abstract language."
)
CONSOLIDATION_SYSTEM = (
    "Compress the following observations into one paragraph. "
    "Preserve: specific numbers, state changes, trends, anomalies. "
    "Discard: redundant stable readings, repeated values. "
    "Never interpret or evaluate. Just compress the facts."
)


async def _ollama_generate(prompt: str, system: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                OLLAMA_URL,
                json={
                    "model": DMN_MODEL,
                    "prompt": prompt,
                    "system": system,
                    "stream": False,
                    "options": {"num_predict": 100, "temperature": 0.3},
                },
            )
            if resp.status_code == 200:
                return resp.json().get("response", "").strip()
            log.warning("Ollama returned %d", resp.status_code)
            return ""
    except Exception as exc:
        log.debug("Ollama call failed: %s", exc)
        return ""


def _format_sensor_prompt(snapshot: dict, deltas: list[str]) -> str:
    parts = []
    p = snapshot.get("perception", {})
    parts.append(f"Activity: {p.get('activity', '?')}. Flow: {p.get('flow_score', 0):.1f}.")
    s = snapshot.get("stimmung", {})
    parts.append(f"Stimmung: {s.get('stance', '?')}. Stress: {s.get('operator_stress', 0):.2f}.")
    f = snapshot.get("fortress")
    if f:
        parts.append(
            f"Fortress {f.get('fortress_name', '?')}: pop={f.get('population')}, "
            f"food={f.get('food')}, drink={f.get('drink')}, "
            f"threats={f.get('threats')}, idle={f.get('idle')}."
        )
    w = snapshot.get("watch", {})
    if w.get("heart_rate", 0) > 0:
        parts.append(f"Heart rate: {w['heart_rate']} bpm.")
    if deltas:
        parts.append("Changes: " + "; ".join(deltas) + ".")
    return " ".join(parts)
