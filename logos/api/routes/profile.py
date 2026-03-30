"""Profile endpoints — read/correct operator profile facts."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger("logos.api.profile")

router = APIRouter(prefix="/api/profile", tags=["profile"])

from logos.api.routes._config import LOGOS_STATE_DIR

PENDING_FACTS_PATH = LOGOS_STATE_DIR / "pending-facts.jsonl"


@router.get("/{dimension}")
async def get_dimension(dimension: str):
    """Get facts for a specific profile dimension."""
    import asyncio

    def _read():
        from agents.profiler import PROFILE_DIMENSIONS, load_existing_profile

        profile = load_existing_profile()
        if not profile:
            return None

        if not dimension:
            # Summary
            dims = []
            for dim in profile.dimensions:
                dims.append(
                    {"name": dim.name, "fact_count": len(dim.facts), "summary": dim.summary or ""}
                )
            missing = [
                d for d in PROFILE_DIMENSIONS if d not in {dim.name for dim in profile.dimensions}
            ]
            return {
                "dimensions": dims,
                "missing": missing,
                "total_facts": sum(d["fact_count"] for d in dims),
            }

        for dim in profile.dimensions:
            if dim.name == dimension:
                facts = []
                for f in dim.facts:
                    facts.append(
                        {
                            "key": f.key,
                            "value": f.value,
                            "confidence": f.confidence,
                            "source": f.source,
                        }
                    )
                return {"name": dim.name, "summary": dim.summary or "", "facts": facts}

        return None

    result = await asyncio.to_thread(_read)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"Dimension '{dimension}' not found or no profile"
        )
    return result


@router.get("")
async def get_profile_summary():
    """Get profile summary with all dimensions."""
    import asyncio

    def _read():
        from agents.profiler import PROFILE_DIMENSIONS, load_existing_profile

        profile = load_existing_profile()
        if not profile:
            return {"dimensions": [], "missing": list(PROFILE_DIMENSIONS), "total_facts": 0}
        dims = []
        for dim in profile.dimensions:
            dims.append(
                {"name": dim.name, "fact_count": len(dim.facts), "summary": dim.summary or ""}
            )
        missing = [
            d for d in PROFILE_DIMENSIONS if d not in {dim.name for dim in profile.dimensions}
        ]
        return {
            "dimensions": dims,
            "missing": missing,
            "total_facts": sum(d["fact_count"] for d in dims),
            "version": profile.version,
            "updated_at": profile.updated_at,
        }

    return await asyncio.to_thread(_read)


class CorrectionRequest(BaseModel):
    dimension: str
    key: str
    value: str


@router.post("/correct")
async def correct_fact(req: CorrectionRequest):
    """Apply a correction to a profile fact."""
    import asyncio

    def _apply():
        from agents.profiler import apply_corrections

        if req.value.upper() == "DELETE":
            corrections = [{"dimension": req.dimension, "key": req.key, "value": None}]
        else:
            corrections = [{"dimension": req.dimension, "key": req.key, "value": req.value}]
        return apply_corrections(corrections)

    result = await asyncio.to_thread(_apply)
    return {"status": "ok", "result": result}


class DeleteFactRequest(BaseModel):
    dimension: str
    key: str


@router.post("/delete")
async def delete_fact(req: DeleteFactRequest):
    """Delete a fact from the profile."""
    import asyncio

    def _delete():
        from agents.profiler import apply_corrections

        return apply_corrections([{"dimension": req.dimension, "key": req.key, "value": None}])

    result = await asyncio.to_thread(_delete)
    return {"status": "ok", "result": result}


@router.get("/facts/pending")
async def get_pending_facts():
    """Get pending observations not yet flushed to profile."""
    if not PENDING_FACTS_PATH.exists():
        return {"facts": [], "count": 0}

    facts = []
    try:
        for line in PENDING_FACTS_PATH.read_text().strip().splitlines():
            try:
                facts.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass

    return {"facts": facts, "count": len(facts)}


@router.post("/facts/flush")
async def flush_pending_facts():
    """Flush pending facts to the profiler."""
    import asyncio

    if not PENDING_FACTS_PATH.exists():
        return {"status": "ok", "flushed": 0}

    def _flush():
        from agents.profiler import flush_interview_facts
        from logos.interview import RecordedFact

        facts = []
        for line in PENDING_FACTS_PATH.read_text().strip().splitlines():
            try:
                data = json.loads(line)
                facts.append(
                    RecordedFact(
                        dimension=data["dimension"],
                        key=data["key"],
                        value=data["value"],
                        confidence=data.get("confidence", 0.6),
                        evidence=data.get("evidence", ""),
                    )
                )
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        if not facts:
            return 0

        flush_interview_facts(facts=facts, insights=[], source="conversation:logos")
        # Clear the pending file
        PENDING_FACTS_PATH.write_text("")
        return len(facts)

    count = await asyncio.to_thread(_flush)
    return {"status": "ok", "flushed": count}
