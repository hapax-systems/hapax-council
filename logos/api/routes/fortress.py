"""Logos API routes for fortress governance data.

Serves fortress state, governance chain status, goals, events,
metrics, and session history for the Logos frontend.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from agents.fortress.config import BridgeConfig
from shared.config import PROFILES_DIR

router = APIRouter(prefix="/api/fortress", tags=["fortress"])
log = logging.getLogger(__name__)

_bridge_config = BridgeConfig()
GOVERNOR_STATE_DIR = Path("/dev/shm/hapax-fortress")


def _read_json_or(path: Path, fallback: dict) -> dict:
    """Read a JSON file, returning fallback on error."""
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return fallback


def _read_state_file() -> dict | None:
    """Read raw state JSON from bridge, or None if unavailable."""
    path = _bridge_config.state_path
    if not path.exists():
        return None
    try:
        import time

        age = time.time() - path.stat().st_mtime
        if age > _bridge_config.staleness_threshold_s:
            return None
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Failed to read fortress state: %s", exc)
        return None


@router.get("/state")
async def get_fortress_state():
    """Current fortress state from DFHack bridge."""
    data = _read_state_file()
    if data is None:
        raise HTTPException(status_code=503, detail="Fortress not active")
    return data


@router.get("/events")
async def get_fortress_events(limit: int = 50):
    """Recent fortress events from state."""
    data = _read_state_file()
    if data is None:
        raise HTTPException(status_code=503, detail="Fortress not active")
    events = data.get("pending_events", [])
    return {"events": events[-limit:]}


@router.get("/governance")
async def get_fortress_governance():
    """Governance chain activity and suppression field levels."""
    path = GOVERNOR_STATE_DIR / "governance.json"
    if not path.exists():
        # Return placeholder when governor not running
        return {
            "chains": {
                name: {"active": False, "last_action": None}
                for name in (
                    "fortress_planner",
                    "military_commander",
                    "resource_manager",
                    "crisis_responder",
                    "storyteller",
                    "advisor",
                    "creativity",
                )
            },
            "suppression": {
                "crisis_suppression": 0.0,
                "military_alert": 0.0,
                "resource_pressure": 0.0,
                "planner_activity": 0.0,
                "creativity_suppression": 0.0,
            },
        }
    return _read_json_or(path, {"chains": {}, "suppression": {}})


@router.get("/goals")
async def get_fortress_goals():
    """Active compound goals and subgoal states."""
    path = GOVERNOR_STATE_DIR / "goals.json"
    if not path.exists():
        return {"goals": []}
    return _read_json_or(path, {"goals": []})


@router.get("/metrics")
async def get_fortress_metrics():
    """Current session metrics (live)."""
    path = GOVERNOR_STATE_DIR / "metrics.json"
    if not path.exists():
        return {
            "session_id": None,
            "survival_days": 0,
            "total_commands": 0,
            "chain_metrics": {},
        }
    return _read_json_or(
        path, {"session_id": None, "survival_days": 0, "total_commands": 0, "chain_metrics": {}}
    )


@router.get("/sessions")
async def get_fortress_sessions(limit: int = 20):
    """Historical session list with survival times."""
    sessions_path = PROFILES_DIR / "fortress-sessions.jsonl"
    if not sessions_path.exists():
        return {"sessions": []}
    entries = []
    for line in sessions_path.read_text().strip().split("\n"):
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return {"sessions": entries[-limit:]}


@router.get("/sessions/{session_id}")
async def get_fortress_session(session_id: str):
    """Detailed session record."""
    sessions_path = PROFILES_DIR / "fortress-sessions.jsonl"
    if not sessions_path.exists():
        raise HTTPException(status_code=404, detail="No sessions recorded")
    for line in sessions_path.read_text().strip().split("\n"):
        if line:
            try:
                entry = json.loads(line)
                if entry.get("session_id") == session_id:
                    return entry
            except json.JSONDecodeError:
                continue
    raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@router.get("/chronicle")
async def get_fortress_chronicle(limit: int = 50):
    """Narrative chronicle entries."""
    chronicle_path = PROFILES_DIR / "fortress-chronicle.jsonl"
    if not chronicle_path.exists():
        return {"entries": []}
    entries = []
    for line in chronicle_path.read_text().strip().split("\n"):
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return {"entries": entries[-limit:]}
