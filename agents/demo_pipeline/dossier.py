"""Interactive dossier collection for named audience members.

Gathers background on a specific person through a CLI interview,
persists to demo-audiences.yaml, and optionally indexes relationship
facts to Qdrant profile-facts.
"""
from __future__ import annotations

import logging
import os
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

import yaml

from agents.demo_models import AUDIENCES_PATH, AudienceDossier, load_audiences, load_personas

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded question set — maps to KNOWLEDGE_DIMENSIONS from sufficiency.py
# ---------------------------------------------------------------------------

DOSSIER_QUESTIONS: list[dict] = [
    {
        "dimension": "prior_knowledge",
        "question": "What does {name} already know about this system? (e.g., 'nothing', 'heard me talk about it', 'seen a previous demo', 'uses it daily')",
        "key": "prior_knowledge_level",
    },
    {
        "dimension": "goals_pain_points",
        "question": "What does {name} care about most? What would make them think 'this was worth seeing'?",
        "key": "goals",
    },
    {
        "dimension": "attitudes_resistance",
        "question": "Any skepticism or concerns? (e.g., 'thinks I spend too much time on it', 'worried about AI', 'none') [press Enter to skip]",
        "key": "attitudes",
    },
    {
        "dimension": "decision_role",
        "question": "What's their relationship to you and this work? (e.g., 'spouse, no technical role', 'manager evaluating approach', 'peer who might adopt similar tools')",
        "key": "relationship_role",
    },
    {
        "dimension": "situational_constraints",
        "question": "Any context about when/where this demo happens? (e.g., 'casual at home', 'formal presentation', '5 minutes at lunch') [press Enter to skip]",
        "key": "situational_context",
    },
]


# ---------------------------------------------------------------------------
# Interactive collection
# ---------------------------------------------------------------------------


def gather_dossier_interactive(
    audience_key: str,
    archetype: str,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
    personas: dict | None = None,
) -> tuple[AudienceDossier, dict[str, str]]:
    """Interactive CLI session to collect audience dossier.

    Uses input_fn/print_fn injection for testability.
    Returns (AudienceDossier, responses) so caller can pass responses
    to record_relationship_facts().
    """
    print_fn(f"\nGathering dossier for '{audience_key}'\n")

    # Always ask for name first
    name = input_fn("What should we call this person? (e.g., their first name): ").strip()
    if not name:
        name = audience_key

    # Ask each question, build context in single pass
    responses: dict[str, str] = {}
    context_parts: list[str] = []
    for q in DOSSIER_QUESTIONS:
        prompt = q["question"].format(name=name) + ": "
        answer = input_fn(prompt).strip()
        if answer:
            responses[q["key"]] = answer
            context_parts.append(f"{q['dimension']}: {answer}")
    context = "\n".join(context_parts)

    # Build calibration from archetype defaults
    if personas is None:
        personas = load_personas()
    calibration: dict = {}
    if archetype in personas:
        persona = personas[archetype]
        calibration = {
            "emphasize": list(persona.show),
            "skip": list(persona.skip),
        }

    dossier = AudienceDossier(
        key=audience_key,
        archetype=archetype,
        name=name,
        context=context,
        calibration=calibration,
    )
    return dossier, responses


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save_dossier(
    dossier: AudienceDossier,
    path: Path | None = None,
) -> Path:
    """Save dossier to demo-audiences.yaml using atomic write.

    Uses tempfile + os.replace pattern (from lessons.py).
    Merges with existing audiences if file exists.
    """
    target = path or AUDIENCES_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    # Load existing audiences
    existing = load_audiences(target)

    # Add/update this dossier
    existing[dossier.key.lower()] = dossier

    # Serialize to YAML-friendly dict
    audiences_data: dict = {}
    for key, d in existing.items():
        audiences_data[d.key] = {
            "archetype": d.archetype,
            "name": d.name,
            "context": d.context,
            "calibration": d.calibration,
        }

    content = yaml.dump(
        {"audiences": audiences_data},
        default_flow_style=False,
        sort_keys=True,
    )

    # Atomic write: tempfile + os.replace
    fd = tempfile.NamedTemporaryFile(
        mode="w",
        dir=str(target.parent),
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    )
    try:
        fd.write(content)
        fd.flush()
        os.fsync(fd.fileno())
        fd.close()
        os.replace(fd.name, str(target))
    except BaseException:
        fd.close()
        try:
            os.unlink(fd.name)
        except OSError:
            pass
        raise

    return target


# ---------------------------------------------------------------------------
# Relationship fact indexing (best-effort)
# ---------------------------------------------------------------------------


def record_relationship_facts(
    dossier: AudienceDossier,
    responses: dict[str, str],
) -> int:
    """Persist relationship facts to Qdrant profile-facts collection.

    Uses embed_batch from shared.config with UUID5 keying for deterministic IDs.
    Returns number of facts indexed.
    Catches exceptions internally (best-effort).
    """
    try:
        from qdrant_client.models import PointStruct

        from shared.config import embed_batch, get_qdrant

        collection = "profile-facts"

        # Build facts from dossier context + responses
        texts: list[str] = []
        metadata_list: list[dict] = []

        # Index each non-empty response as a relationship fact
        for key, value in responses.items():
            if not value:
                continue
            text = f"relationships/{dossier.key}: {key} = {value}"
            texts.append(text)
            metadata_list.append({
                "dimension": "relationships",
                "key": f"{dossier.key}/{key}",
                "value": value,
                "confidence": 0.9,
                "source": "dossier-interview",
                "text": text,
                "audience_key": dossier.key,
                "audience_name": dossier.name,
            })

        # Also index the assembled context as a summary fact
        if dossier.context:
            text = f"relationships/{dossier.key}: context = {dossier.context}"
            texts.append(text)
            metadata_list.append({
                "dimension": "relationships",
                "key": f"{dossier.key}/context",
                "value": dossier.context,
                "confidence": 0.9,
                "source": "dossier-interview",
                "text": text,
                "audience_key": dossier.key,
                "audience_name": dossier.name,
            })

        if not texts:
            return 0

        vectors = embed_batch(texts, prefix="search_document")

        points: list[PointStruct] = []
        for vec, meta in zip(vectors, metadata_list):
            point_id = str(uuid.uuid5(
                uuid.NAMESPACE_DNS,
                f"profile-fact-relationships-{meta['key']}",
            ))
            points.append(PointStruct(id=point_id, vector=vec, payload=meta))

        client = get_qdrant()
        client.upsert(collection, points)

        log.info("Indexed %d relationship facts for '%s'", len(points), dossier.key)
        return len(points)

    except Exception:
        log.warning("Failed to index relationship facts (best-effort)", exc_info=True)
        return 0
