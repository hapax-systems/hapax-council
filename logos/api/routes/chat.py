"""Chat endpoints — session management + SSE streaming chat."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from logos.chat_agent import ChatSession, format_conversation_export

log = logging.getLogger("logos.api.chat")

router = APIRouter(prefix="/api/chat", tags=["chat"])

PROJECT_DIR = Path(__file__).parent.parent.parent.parent

# In-process session store (single-user system)
_sessions: dict[str, ChatSession] = {}
_active_generation: dict[str, asyncio.Event] = {}  # session_id -> cancel event


def _get_session(session_id: str) -> ChatSession:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return session


# ── Session lifecycle ────────────────────────────────────────────────────


class CreateSessionRequest(BaseModel):
    model: str = "balanced"


class CreateSessionResponse(BaseModel):
    session_id: str
    model: str


@router.post("/sessions")
async def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    """Create a new chat session."""
    session_id = str(uuid.uuid4())[:8]

    # Try to restore from persisted state
    persist_path = ChatSession.session_path()
    if persist_path.exists():
        try:
            session = ChatSession.load(persist_path, PROJECT_DIR)
            session.set_model(req.model)
        except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError):
            session = ChatSession(project_dir=PROJECT_DIR, model_alias=req.model)
    else:
        session = ChatSession(project_dir=PROJECT_DIR, model_alias=req.model)

    _sessions[session_id] = session
    return CreateSessionResponse(session_id=session_id, model=session.model_alias)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get session info."""
    session = _get_session(session_id)
    return {
        "session_id": session_id,
        "model": session.model_alias,
        "message_count": session.message_count,
        "total_tokens": session.total_tokens,
        "mode": session.mode,
        "generating": session.generating,
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Destroy a chat session."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    del _sessions[session_id]
    # Cancel any active generation
    if session_id in _active_generation:
        _active_generation[session_id].set()
        del _active_generation[session_id]
    return {"status": "deleted"}


# ── Model switching ──────────────────────────────────────────────────────


class ModelRequest(BaseModel):
    model: str


@router.post("/sessions/{session_id}/model")
async def switch_model(session_id: str, req: ModelRequest):
    """Switch the session's model."""
    session = _get_session(session_id)
    session.set_model(req.model)
    return {"status": "ok", "model": session.model_alias}


# ── Available models ─────────────────────────────────────────────────────


@router.get("/models")
async def get_models():
    """List available model aliases."""
    try:
        from shared.config import MODELS

        return {"models": list(MODELS.keys())}
    except (ImportError, AttributeError):
        return {"models": ["balanced", "fast", "reasoning", "coding", "local-fast"]}


# ── Message history ──────────────────────────────────────────────────────


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str):
    """Get formatted message history for the session."""
    session = _get_session(session_id)
    export = format_conversation_export(session.message_history, session.model_alias)
    return {"content": export, "message_count": session.message_count}


# ── Send message (SSE streaming) ─────────────────────────────────────────


class SendRequest(BaseModel):
    message: str


@router.post("/sessions/{session_id}/send")
async def send_message(session_id: str, req: SendRequest):
    """Send a message and stream the response via SSE.

    SSE events:
        text_delta  → {"content": "partial text"}
        tool_call   → {"name": "tool_name", "args": "arg_string", "call_id": "..."}
        done        → {"full_text": "...", "turn_tokens": N, "total_tokens": N}
        error       → {"message": "...", "recoverable": true/false}
    """
    session = _get_session(session_id)

    if session.generating:
        raise HTTPException(status_code=409, detail="Session is already generating")

    cancel_event = asyncio.Event()
    _active_generation[session_id] = cancel_event

    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def _generate():
        try:
            full_text = await session.send_message(
                req.message,
                on_text_delta=lambda text: queue.put_nowait(
                    {
                        "event": "text_delta",
                        "data": {"content": text},
                    }
                ),
                on_tool_call=lambda name, args: queue.put_nowait(
                    {
                        "event": "tool_call",
                        "data": {
                            "name": name,
                            "args": args,
                            "call_id": f"{name}-{uuid.uuid4().hex[:6]}",
                        },
                    }
                ),
            )
            await queue.put(
                {
                    "event": "done",
                    "data": {
                        "full_text": full_text,
                        "turn_tokens": session.last_turn_tokens,
                        "total_tokens": session.total_tokens,
                    },
                }
            )
        except asyncio.CancelledError:
            await queue.put(
                {
                    "event": "done",
                    "data": {
                        "full_text": "",
                        "turn_tokens": 0,
                        "total_tokens": session.total_tokens,
                        "cancelled": True,
                    },
                }
            )
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            log.exception("Chat generation error: %s", e)
            is_rate_limit = "rate_limit" in str(e).lower()
            await queue.put(
                {
                    "event": "error",
                    "data": {
                        "message": "Rate limit exceeded, please retry"
                        if is_rate_limit
                        else "Internal error during chat generation",
                        "recoverable": is_rate_limit,
                    },
                }
            )
        finally:
            _active_generation.pop(session_id, None)
            await queue.put(None)  # Sentinel
            # Auto-save after each turn
            try:
                session.save(ChatSession.session_path())
            except OSError:
                pass

    task = asyncio.create_task(_generate())

    # Monitor cancel event
    async def _cancel_monitor():
        await cancel_event.wait()
        task.cancel()

    cancel_task = asyncio.create_task(_cancel_monitor())

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield {
                    "event": event["event"],
                    "data": json.dumps(event["data"]),
                }
        finally:
            cancel_task.cancel()
            task.cancel()

    return EventSourceResponse(event_generator())


# ── Stop generation ──────────────────────────────────────────────────────


@router.post("/sessions/{session_id}/stop")
async def stop_generation(session_id: str):
    """Cancel an active generation."""
    cancel = _active_generation.get(session_id)
    if cancel:
        cancel.set()
        return {"status": "cancelled"}
    return {"status": "not_generating"}


# ── Export ────────────────────────────────────────────────────────────────


@router.post("/sessions/{session_id}/export")
async def export_session(session_id: str):
    """Export conversation as markdown."""
    session = _get_session(session_id)
    content = format_conversation_export(session.message_history, session.model_alias)
    return {"content": content, "model": session.model_alias}


# ── Interview mode ────────────────────────────────────────────────────


@router.post("/sessions/{session_id}/interview")
async def start_interview(session_id: str):
    """Start an interview session. Returns SSE stream."""
    session = _get_session(session_id)

    if session.mode == "interview":
        raise HTTPException(status_code=409, detail="Already in interview mode")
    if session.generating:
        raise HTTPException(status_code=409, detail="Session is generating")

    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def _run():
        try:
            full_text = await session.start_interview(
                on_text_delta=lambda text: queue.put_nowait(
                    {
                        "event": "text_delta",
                        "data": {"content": text},
                    }
                ),
                on_tool_call=lambda name, args: queue.put_nowait(
                    {
                        "event": "tool_call",
                        "data": {"name": name, "args": args, "call_id": f"{name}-interview"},
                    }
                ),
                on_plan_ready=lambda: queue.put_nowait(
                    {
                        "event": "plan_ready",
                        "data": {
                            "topic_count": len(session.interview_state.plan.topics)
                            if session.interview_state
                            else 0,
                            "focus": session.interview_state.plan.topics[0].topic
                            if session.interview_state and session.interview_state.plan.topics
                            else "",
                        },
                    }
                ),
            )
            await queue.put(
                {
                    "event": "done",
                    "data": {
                        "full_text": full_text,
                        "turn_tokens": session.last_turn_tokens,
                        "total_tokens": session.total_tokens,
                    },
                }
            )
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            log.exception("Interview start error: %s", e)
            await queue.put(
                {
                    "event": "error",
                    "data": {"message": "Internal error starting interview", "recoverable": False},
                }
            )
        finally:
            await queue.put(None)
            try:
                session.save(ChatSession.session_path())
            except OSError:
                pass

    task = asyncio.create_task(_run())

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield {"event": event["event"], "data": json.dumps(event["data"])}
        finally:
            task.cancel()

    return EventSourceResponse(event_generator())


@router.post("/sessions/{session_id}/interview/end")
async def end_interview(session_id: str):
    """End the interview and flush accumulated facts."""
    session = _get_session(session_id)
    if session.mode != "interview":
        raise HTTPException(status_code=400, detail="Not in interview mode")

    summary = await session.end_interview()
    try:
        session.save(ChatSession.session_path())
    except OSError:
        pass
    return {"status": "ok", "summary": summary}


@router.post("/sessions/{session_id}/interview/skip")
async def skip_interview_topic(session_id: str):
    """Skip the current interview topic."""
    session = _get_session(session_id)
    if session.mode != "interview":
        raise HTTPException(status_code=400, detail="Not in interview mode")

    message = session.skip_interview_topic()
    return {"status": "ok", "message": message}


@router.get("/sessions/{session_id}/interview/status")
async def interview_status(session_id: str):
    """Get interview progress."""
    session = _get_session(session_id)
    if session.mode != "interview":
        return {"active": False}

    status_text = session.interview_status()
    state = session.interview_state
    return {
        "active": True,
        "status": status_text,
        "topics_explored": len(state.topics_explored) if state else 0,
        "total_topics": len(state.plan.topics) if state and state.plan else 0,
        "facts_count": len(state.facts) if state else 0,
        "insights_count": len(state.insights) if state else 0,
    }
