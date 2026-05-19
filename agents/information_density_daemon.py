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
from collections import Counter
from pathlib import Path
from typing import Any

from shared.information_density import BOCPDModel, InformationDensityField, SourceDensity

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


# ── Narrative Source ─────────────────────────────────────────────────────────

NARRATIVE_STATE_SHM = Path("/dev/shm/hapax-director/narrative-state.json")
CHRONICLE_EVENTS_PATH = Path("/dev/shm/hapax-chronicle/events.jsonl")
AUDIENCE_SHM = Path("/dev/shm/hapax-perception/audience.json")
STT_RECENT_PATH = Path("/dev/shm/hapax-daimonion/stt-recent.txt")


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class NarrativeSource:
    """Computes narrative density from chronicle, transcript, and audience signals.

    Four sub-signals:
    - activity:  Shannon entropy over chronicle event types (variety of things happening)
    - surprise:  1 - mean(cosine_sim(transcript, anchors)) — high when ungrounded
    - novelty:   BOCPD change-point probability on transcript embedding magnitude
    - relevance: viewer_count / max(viewer_count, 1) normalized [0,1]
    """

    def __init__(self, anchor_vectors: list[list[float]]) -> None:
        self._anchor_vectors = anchor_vectors
        self._bocpd = BOCPDModel(hazard=1 / 100, max_run_lengths=100)
        self._show_start = time.time()

    def compute(self) -> SourceDensity:
        """Compute all four narrative density sub-signals."""
        activity = self._compute_activity()
        surprise = self._compute_surprise()
        novelty = self._compute_novelty()
        relevance = self._compute_relevance()

        sd = SourceDensity(
            source_id="narrative",
            activity=activity,
            surprise=surprise,
            novelty=novelty,
            relevance=relevance,
            confidence=1.0,
            timestamp=time.time(),
        )
        sd.compute_density()
        return sd

    def _compute_activity(self) -> float:
        """Shannon entropy over chronicle event types since show start."""
        try:
            events_path = CHRONICLE_EVENTS_PATH
            if not events_path.exists():
                return 0.0
            counter: Counter[str] = Counter()
            text = events_path.read_text(encoding="utf-8")
            for line in text.splitlines():
                if not line.strip():
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = evt.get("ts", 0.0)
                if ts < self._show_start:
                    continue
                event_type = evt.get("event_type", "unknown")
                counter[event_type] += 1

            total = sum(counter.values())
            if total == 0:
                return 0.0
            n_types = len(counter)
            if n_types <= 1:
                return 0.0
            entropy = 0.0
            max_entropy = math.log2(n_types) if n_types > 1 else 1.0
            for count in counter.values():
                p = count / total
                if p > 0:
                    entropy -= p * math.log2(p)
            return entropy / max_entropy if max_entropy > 0 else 0.0
        except OSError:
            return 0.0

    def _compute_surprise(self) -> float:
        """1 - mean(cosine_sim(transcript_embedding, anchors)). High = ungrounded."""
        if not self._anchor_vectors:
            return 0.5  # neutral when no anchors

        try:
            transcript = STT_RECENT_PATH.read_text(encoding="utf-8").strip()
        except (FileNotFoundError, OSError):
            return 0.5

        if not transcript:
            return 0.5

        from shared.config import embed_safe

        vec = embed_safe(transcript, prefix="search_query")
        if vec is None:
            return 0.5

        sims = [_cosine_similarity(vec, anchor) for anchor in self._anchor_vectors]
        mean_sim = sum(sims) / len(sims) if sims else 0.0
        return max(0.0, min(1.0, 1.0 - mean_sim))

    def _compute_novelty(self) -> float:
        """BOCPD change-point probability on transcript embedding stream.

        Uses the L2 norm of the latest transcript embedding as a scalar
        summary — sudden topic shifts produce large norm changes.
        """
        try:
            transcript = STT_RECENT_PATH.read_text(encoding="utf-8").strip()
        except (FileNotFoundError, OSError):
            return 0.0

        if not transcript:
            return 0.0

        from shared.config import embed_safe

        vec = embed_safe(transcript, prefix="search_query")
        if vec is None:
            return 0.0

        magnitude = math.sqrt(sum(x * x for x in vec))
        return self._bocpd.update(magnitude)

    def _compute_relevance(self) -> float:
        """Viewer count normalized to [0,1]. Read from audience SHM."""
        audience_data = _read_json(AUDIENCE_SHM)
        if audience_data is None:
            return 0.0
        viewer_count = _extract_float(audience_data, "viewer_count", "viewers", "count")
        return min(1.0, viewer_count / max(viewer_count, 1.0))


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
    anchor_vectors = [vec for _, vec in anchors]

    # Register narrative source — uses direct SourceDensity updates
    field.register_source("narrative", obs_min=0.0, obs_max=1.0)
    narrative = NarrativeSource(anchor_vectors)

    log.info(
        "information_density_daemon: started with %d sources + narrative, %d concept anchors",
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

            # Update narrative source with pre-computed density signals
            narrative_density = narrative.compute()
            field.update(
                "narrative",
                narrative_density.activity,
                relevance=narrative_density.relevance,
            )
            # Override the source model's computed values with our richer signals
            narrative_model = field._sources.get("narrative")
            if narrative_model is not None:
                narrative_model.last_density = narrative_density

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
