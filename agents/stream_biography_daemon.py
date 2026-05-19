"""Stream biography daemon — grounding queries against chronicle to build narrative self-model.

Runs after each segment completion and on show start. Queries Command-R
to discover what the stream has established (concepts, introductions,
narrative events) by examining its own chronicle and transcript history.

Evidence-of-absence is first-class: "no introduction found" IS the
grounded evidence that the operator has not been introduced.

CASE-NARRATIVE-ARC-AWARENESS-20260519 Layer 1.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
from pathlib import Path

from shared.stream_biography import (
    GroundedConcept,
    GroundedIntroduction,
    NarrativeEvent,
    StreamBiography,
    load_persisted,
    persist,
    read_shm,
    write_shm,
)

log = logging.getLogger(__name__)

_CHRONICLE_API = "http://localhost:8051/api/chronicle"
_PROGRAMME_STORE = Path.home() / "hapax-state" / "programmes.jsonl"


def _fetch_chronicle(limit: int = 50) -> list[dict]:
    try:
        result = subprocess.run(
            ["curl", "-sf", f"{_CHRONICLE_API}?limit={limit}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass
    return []


def _count_completed_segments() -> int:
    if not _PROGRAMME_STORE.exists():
        return 0
    count = 0
    for line in _PROGRAMME_STORE.read_text().strip().splitlines():
        try:
            prog = json.loads(line)
            if prog.get("status") == "completed":
                count += 1
        except json.JSONDecodeError:
            continue
    return count


async def _query_grounding(chronicle_events: list[dict]) -> dict:
    """Query Command-R to discover what the stream has established."""
    from shared.config import LITELLM_BASE, LITELLM_KEY

    if not chronicle_events:
        return {"concepts": [], "introductions": [], "events": []}

    event_summaries = []
    for ev in chronicle_events[:30]:
        cat = ev.get("category", "unknown")
        summary = ev.get("summary", ev.get("description", ""))
        event_summaries.append(f"[{cat}] {summary}")

    prompt = (
        "You are examining a livestream's chronicle to discover what has been established.\n\n"
        "Chronicle events (most recent first):\n" + "\n".join(event_summaries) + "\n\n"
        "Based ONLY on this evidence, answer in JSON:\n"
        '{"concepts": [{"concept": "...", "confidence": 0.0-1.0, "evidence": "which event"}], '
        '"introductions": [{"subject": "...", "evidence": "which event"}], '
        '"narrative_stage": "inchoate|opening|developing|established"}\n\n'
        "If a concept has NOT been explained, do NOT list it. Absence = evidence of absence.\n"
        "If the operator has NOT been introduced, do NOT fabricate an introduction.\n"
        "Report ONLY what the chronicle evidence supports."
    )

    try:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{LITELLM_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {LITELLM_KEY}"},
                json={
                    "model": "local-fast",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 1000,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(content[start:end])
    except Exception:
        log.warning("grounding query failed", exc_info=True)

    return {"concepts": [], "introductions": [], "events": []}


async def update_biography(bio: StreamBiography | None = None) -> StreamBiography:
    if bio is None:
        bio = read_shm()

    chronicle = _fetch_chronicle(limit=50)
    bio.total_segments_completed = _count_completed_segments()

    if bio.show_started_at > 0:
        bio.total_stream_hours = (time.time() - bio.show_started_at) / 3600.0

    grounding = await _query_grounding(chronicle)

    now = time.time()
    for concept_data in grounding.get("concepts", []):
        concept_name = concept_data.get("concept", "")
        if not concept_name:
            continue
        evidence = concept_data.get("evidence", "")
        confidence = float(concept_data.get("confidence", 0.5))
        existing_conf = bio.concept_grounded(concept_name)
        bio.record_concept(
            GroundedConcept(
                concept=concept_name,
                evidence_refs=[evidence] if evidence else [],
                grounding_confidence=max(existing_conf, confidence),
                first_established_at=now if existing_conf == 0.0 else 0.0,
                last_reinforced_at=now,
            )
        )

    for intro_data in grounding.get("introductions", []):
        subject = intro_data.get("subject", "")
        if subject and not bio.has_introduction(subject):
            bio.record_introduction(
                GroundedIntroduction(
                    subject=subject,
                    evidence_refs=[intro_data.get("evidence", "")],
                    introduced_at=now,
                )
            )

    stage = grounding.get("narrative_stage", "inchoate")
    bio.record_event(
        NarrativeEvent(event_type="stage_assessment", description=stage, timestamp=now)
    )

    write_shm(bio)
    persist(bio)
    log.info(
        "biography updated: %d concepts, %d introductions, stage=%s",
        len(bio.established_concepts),
        len(bio.introductions),
        stage,
    )
    return bio


async def run_daemon(poll_interval_s: float = 60.0) -> None:
    bio = load_persisted() or StreamBiography()
    if bio.show_started_at == 0.0:
        bio.show_started_at = time.time()
    write_shm(bio)

    log.info("stream biography daemon started")
    while True:
        try:
            bio = await update_biography(bio)
        except Exception:
            log.warning("biography update failed", exc_info=True)
        await asyncio.sleep(poll_interval_s)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(run_daemon())
