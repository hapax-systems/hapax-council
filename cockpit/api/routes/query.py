"""Query endpoints — natural language system introspection with SSE streaming."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from sse_starlette.sse import EventSourceResponse

from cockpit.query_dispatch import classify_query, get_agent_list, run_query

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/query", tags=["query"])


class QueryRunRequest(BaseModel):
    query: str

    @field_validator("query")
    @classmethod
    def query_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Query must not be empty")
        return v.strip()


class QueryRefineRequest(BaseModel):
    query: str
    prior_result: str
    agent_type: str

    @field_validator("query")
    @classmethod
    def query_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Query must not be empty")
        return v.strip()


@router.get("/agents")
async def list_query_agents():
    """List available query agent types."""
    agents = get_agent_list()
    return [
        {
            "agent_type": a.agent_type,
            "name": a.name,
            "description": a.description,
        }
        for a in agents
    ]


@router.post("/run")
async def run_query_endpoint(req: QueryRunRequest):
    """Run a natural language query with auto-classification.

    Returns an SSE stream with events: status, text_delta, done, error.
    """

    async def event_generator():
        try:
            agent_type = classify_query(req.query)
            yield {
                "event": "status",
                "data": json.dumps({"phase": "querying", "agent": agent_type}),
            }

            result = await run_query(agent_type, req.query)

            yield {
                "event": "text_delta",
                "data": json.dumps({"content": result.markdown}),
            }
            yield {
                "event": "done",
                "data": json.dumps({
                    "agent_used": result.agent_type,
                    "tokens_in": result.tokens_in,
                    "tokens_out": result.tokens_out,
                    "elapsed_ms": result.elapsed_ms,
                }),
            }
        except Exception as e:
            log.exception("Query failed")
            yield {
                "event": "error",
                "data": json.dumps({"message": str(e)}),
            }

    return EventSourceResponse(event_generator())


@router.post("/refine")
async def refine_query_endpoint(req: QueryRefineRequest):
    """Refine a prior query result with follow-up context."""
    if req.agent_type not in {a.agent_type for a in get_agent_list()}:
        raise HTTPException(status_code=400, detail=f"Unknown agent type: {req.agent_type}")

    async def event_generator():
        try:
            yield {
                "event": "status",
                "data": json.dumps({"phase": "querying", "agent": req.agent_type}),
            }

            result = await run_query(
                req.agent_type,
                req.query,
                prior_context=req.prior_result,
            )

            yield {
                "event": "text_delta",
                "data": json.dumps({"content": result.markdown}),
            }
            yield {
                "event": "done",
                "data": json.dumps({
                    "agent_used": result.agent_type,
                    "tokens_in": result.tokens_in,
                    "tokens_out": result.tokens_out,
                    "elapsed_ms": result.elapsed_ms,
                }),
            }
        except Exception as e:
            log.exception("Refine query failed")
            yield {
                "event": "error",
                "data": json.dumps({"message": str(e)}),
            }

    return EventSourceResponse(event_generator())
