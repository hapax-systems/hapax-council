"""Information Density Daemon — reads perceptual sources, computes density field.

Runs as a systemd service. Reads from existing SHM files and perception
state, feeds the InformationDensityField, and writes the aggregate to
/dev/shm/hapax-density-field/state.json every tick.

Every source participates. Sources are auto-discovered from SHM paths.
New sources can be added by appending to SOURCE_REGISTRY.
"""

from __future__ import annotations

import json
import logging
import math
import time
import urllib.request
from pathlib import Path
from typing import Any

from shared.information_density import InformationDensityField

log = logging.getLogger(__name__)

CONCEPT_ANCHORS_SHM = Path("/dev/shm/hapax-density-field/concept-anchors.json")
OPERATOR_PROFILE_PATH = (
    Path(__file__).resolve().parent.parent / "profiles" / "operator-profile.json"
)
GOALS_API_URL = "http://localhost:8051/api/goals"

TICK_INTERVAL_S = 0.5


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _extract_float(data: dict[str, Any] | None, *keys: str, default: float = 0.0) -> float:
    if data is None:
        return default
    for key in keys:
        val = data.get(key)
        if isinstance(val, (int, float)) and math.isfinite(val):
            return float(val)
    return default


def compute_concept_anchors() -> list[tuple[str, list[float]]]:
    """Compute concept anchor embeddings at show start.

    Reads the operator profile identity and current vault goals, produces
    5-10 foundational concept strings, embeds each via nomic-embed, and
    returns (concept_name, embedding_vector) tuples. Persists to SHM at
    /dev/shm/hapax-density-field/concept-anchors.json.
    """
    from shared.config import embed_batch_safe

    # ── Gather identity context ──────────────────────────────────────────
    identity_facts: list[str] = []
    profile = _read_json(OPERATOR_PROFILE_PATH)
    if profile:
        # Extract identity dimension facts
        for dim in profile.get("dimensions", []):
            if dim.get("name") == "identity":
                for fact in dim.get("facts", []):
                    val = fact.get("value", "")
                    if val and "test" not in val.lower():
                        identity_facts.append(val)
        # Fall back to top-level summary/name
        if not identity_facts:
            if profile.get("name"):
                identity_facts.append(f"The operator is {profile['name']}")
            if profile.get("summary"):
                identity_facts.append(profile["summary"])

    # ── Gather goal context ──────────────────────────────────────────────
    goal_strings: list[str] = []
    try:
        with urllib.request.urlopen(GOALS_API_URL, timeout=5) as resp:
            goals_data = json.loads(resp.read().decode("utf-8"))
            if isinstance(goals_data, list):
                for g in goals_data[:5]:
                    title = g.get("title", g.get("name", ""))
                    if title:
                        goal_strings.append(title)
            elif isinstance(goals_data, dict):
                for g in goals_data.get("goals", goals_data.get("items", []))[:5]:
                    title = g.get("title", g.get("name", ""))
                    if title:
                        goal_strings.append(title)
    except Exception:
        log.debug("compute_concept_anchors: goals API unavailable", exc_info=True)

    # ── Build concept strings ────────────────────────────────────────────
    concepts: list[str] = [
        "what Hapax is — a single-operator externalized executive function system",
        "who the operator is — the person behind the livestream",
        "what this stream is about — live system development and research",
        "the current working mode and research direction",
        "grounding — connecting abstract work to lived experience",
    ]
    # Add operator identity facts as concepts
    for fact in identity_facts[:3]:
        concepts.append(f"operator identity: {fact}")
    # Add current goals as concepts
    for goal in goal_strings[:3]:
        concepts.append(f"current project goal: {goal}")
    # Cap at 10
    concepts = concepts[:10]

    # ── Embed ────────────────────────────────────────────────────────────
    embeddings = embed_batch_safe(concepts, prefix="search_document")
    if embeddings is None:
        log.warning("compute_concept_anchors: embedding failed, returning empty")
        return []

    anchors = list(zip(concepts, embeddings, strict=True))

    # ── Persist to SHM ───────────────────────────────────────────────────
    try:
        CONCEPT_ANCHORS_SHM.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": time.time(),
            "count": len(anchors),
            "anchors": [{"concept": name, "embedding_dim": len(vec)} for name, vec in anchors],
            # Store actual vectors for downstream consumers
            "vectors": {name: vec for name, vec in anchors},
        }
        tmp = CONCEPT_ANCHORS_SHM.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        tmp.replace(CONCEPT_ANCHORS_SHM)
        log.info(
            "compute_concept_anchors: wrote %d anchors to %s", len(anchors), CONCEPT_ANCHORS_SHM
        )
    except OSError:
        log.warning("compute_concept_anchors: SHM write failed", exc_info=True)

    return anchors


SOURCE_REGISTRY: list[dict[str, Any]] = [
    {
        "id": "audio.broadcast_rms",
        "shm": "/dev/shm/hapax-audio-self-perception/state.json",
        "keys": ["rms", "rms_dbfs"],
        "obs_min": -60.0,
        "obs_max": 0.0,
    },
    {
        "id": "audio.spectral_centroid",
        "shm": "/dev/shm/hapax-audio-self-perception/state.json",
        "keys": ["spectral_centroid"],
        "obs_min": 0.0,
        "obs_max": 8000.0,
    },
    {
        "id": "perception.presence",
        "shm": "/dev/shm/hapax-daimonion/perception-fused.json",
        "keys": ["presence_probability", "presence_score"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "perception.vad_confidence",
        "shm": "/dev/shm/hapax-daimonion/perception-fused.json",
        "keys": ["vad_confidence"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "stimmung.health",
        "shm": "/dev/shm/hapax-stimmung/state.json",
        "keys": ["health"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "stimmung.exploration_deficit",
        "shm": "/dev/shm/hapax-stimmung/state.json",
        "keys": ["exploration_deficit"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "stimmung.operator_stress",
        "shm": "/dev/shm/hapax-stimmung/state.json",
        "keys": ["operator_stress"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "compositor.mood_valence",
        "shm": "/dev/shm/hapax-compositor/mood-state.json",
        "keys": ["valence", "mood_valence"],
        "obs_min": -1.0,
        "obs_max": 1.0,
    },
    {
        "id": "compositor.pace",
        "shm": "/dev/shm/hapax-compositor/pace-state.json",
        "keys": ["pace", "pace_value"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "mixer.energy",
        "shm": "/dev/shm/hapax-perception/audio.json",
        "keys": ["mixer_energy", "energy"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "mixer.beat",
        "shm": "/dev/shm/hapax-perception/audio.json",
        "keys": ["mixer_beat", "beat"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "desk.activity",
        "shm": "/dev/shm/hapax-perception/audio.json",
        "keys": ["desk_energy", "contact_energy"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "ir.motion_delta",
        "shm": "/dev/shm/hapax-perception/fused.json",
        "keys": ["ir_motion_delta"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "biometric.heart_rate",
        "shm": "/dev/shm/hapax-sensors/watch.json",
        "keys": ["heart_rate_bpm", "hr_bpm"],
        "obs_min": 40.0,
        "obs_max": 180.0,
    },
    {
        "id": "system.gpu_utilization",
        "shm": "/dev/shm/hapax-stimmung/state.json",
        "keys": ["resource_pressure"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
]


def run_density_daemon() -> None:
    """Main loop — read sources, compute density, write SHM."""
    field = InformationDensityField()

    for src in SOURCE_REGISTRY:
        field.register_source(
            src["id"],
            obs_min=src.get("obs_min", -1.0),
            obs_max=src.get("obs_max", 1.0),
        )

    # Compute concept anchors once at show start
    anchors = compute_concept_anchors()
    log.info(
        "information_density_daemon: started with %d sources, %d concept anchors",
        len(SOURCE_REGISTRY),
        len(anchors),
    )

    while True:
        try:
            for src in SOURCE_REGISTRY:
                shm_path = Path(src["shm"])
                data = _read_json(shm_path)
                value = _extract_float(data, *src["keys"])
                field.update(src["id"], value)

            field.write_shm()

            agg = field.aggregate_density()
            top = field.top_sources(3)
            if top and top[0].density > 0.5:
                log.debug(
                    "density tick: agg=%.3f top=%s(%.3f)",
                    agg,
                    top[0].source_id,
                    top[0].density,
                )
        except Exception:
            log.debug("density tick failed", exc_info=True)

        time.sleep(TICK_INTERVAL_S)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    run_density_daemon()
