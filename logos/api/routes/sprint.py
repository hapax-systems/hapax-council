"""Sprint state and measure/gate endpoints for the Hapax Obsidian plugin v2."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sprint", tags=["sprint"])

# Paths
_SHM_STATE = Path("/dev/shm/hapax-sprint/state.json")
_SHM_COMPLETED = Path("/dev/shm/hapax-sprint/completed.jsonl")
_SHM_NUDGE = Path("/dev/shm/hapax-sprint/nudge.json")

_VAULT_MEASURES_DIR = (
    Path.home()
    / "Documents"
    / "Personal"
    / "20-projects"
    / "hapax-research"
    / "sprint"
    / "measures"
)
_VAULT_GATES_DIR = (
    Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-research" / "sprint" / "gates"
)

# Per-model baselines (prior probability of coherence)
_MODEL_BASELINES: dict[str, float] = {
    "Phenomenological Mapping": 0.58,
    "DMN Continuous Substrate": 0.53,
    "Stimmung": 0.64,
    "Salience / Biased Competition": 0.61,
    "Bayesian Tool Selection": 0.54,
    "Reverie / Bachelard": 0.33,
}


class TransitionStatus(StrEnum):
    in_progress = "in_progress"
    completed = "completed"


class TransitionRequest(BaseModel):
    status: TransitionStatus
    result_summary: str | None = None


class TransitionResponse(BaseModel):
    ok: bool
    measure_id: str
    new_status: str


class AcknowledgeResponse(BaseModel):
    ok: bool
    gate_id: str


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_frontmatter(text: str) -> dict:
    """Extract and parse YAML frontmatter between --- markers."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end: int | None = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return {}
    fm_text = "\n".join(lines[1:end])
    try:
        result = yaml.safe_load(fm_text)
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def _read_vault_dir(directory: Path) -> list[dict]:
    """Read all .md files from a vault directory, returning parsed frontmatter dicts."""
    if not directory.is_dir():
        return []
    results = []
    for md_file in sorted(directory.glob("*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
            fm = _parse_frontmatter(text)
            if fm:
                results.append(fm)
        except Exception:
            log.warning("Failed to read vault file: %s", md_file)
    return results


def _compute_model_posteriors(measures: list[dict]) -> dict[str, dict]:
    """Compute per-model posterior data from vault measure notes."""
    model_data: dict[str, dict] = {}

    for model_name, baseline in _MODEL_BASELINES.items():
        model_measures = [
            m for m in measures if m.get("model") == model_name or m.get("model_name") == model_name
        ]
        completed = sum(1 for m in model_measures if m.get("status") == "completed")
        total = len(model_measures)

        # Simple Bayesian update: posterior = weighted average of baseline and completion rate
        if total > 0:
            completion_rate = completed / total
            posterior = baseline * 0.5 + completion_rate * 0.5
        else:
            posterior = baseline

        model_data[model_name] = {
            "baseline": baseline,
            "posterior": round(posterior, 4),
            "measures_total": total,
            "measures_completed": completed,
        }

    return model_data


def _zeroed_sprint_state() -> dict:
    return {
        "sprint_id": None,
        "active": False,
        "start_date": None,
        "end_date": None,
        "measures": [],
        "gates": [],
        "models": {},
    }


@router.get("")
async def get_sprint_state() -> dict:
    """Return current sprint state from /dev/shm, enriched with model posteriors."""
    state = _read_json(_SHM_STATE)
    if state is None:
        state = _zeroed_sprint_state()

    # Enrich with per-model posterior data from vault measures
    measures = _read_vault_dir(_VAULT_MEASURES_DIR)
    state["models"] = _compute_model_posteriors(measures)

    return state


@router.get("/measures")
async def get_measures() -> dict:
    """Return all sprint measures from vault frontmatter."""
    measures = _read_vault_dir(_VAULT_MEASURES_DIR)
    return {"measures": measures}


@router.get("/measures/{measure_id}")
async def get_measure(measure_id: str) -> dict:
    """Return a single sprint measure by ID."""
    measures = _read_vault_dir(_VAULT_MEASURES_DIR)
    for m in measures:
        if str(m.get("id", "")) == measure_id or str(m.get("measure_id", "")) == measure_id:
            return m
    raise HTTPException(status_code=404, detail=f"Measure '{measure_id}' not found")


@router.get("/gates")
async def get_gates() -> dict:
    """Return all sprint gates from vault frontmatter."""
    gates = _read_vault_dir(_VAULT_GATES_DIR)
    return {"gates": gates}


@router.get("/gates/{gate_id}")
async def get_gate(gate_id: str) -> dict:
    """Return a single sprint gate by ID."""
    gates = _read_vault_dir(_VAULT_GATES_DIR)
    for g in gates:
        if str(g.get("id", "")) == gate_id or str(g.get("gate_id", "")) == gate_id:
            return g
    raise HTTPException(status_code=404, detail=f"Gate '{gate_id}' not found")


@router.post("/measures/{measure_id}/transition")
async def transition_measure(measure_id: str, body: TransitionRequest) -> TransitionResponse:
    """Write a completion signal to the sprint completed.jsonl file."""
    _SHM_COMPLETED.parent.mkdir(parents=True, exist_ok=True)

    signal = {
        "measure_id": measure_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "trigger": "obsidian-plugin",
        "status": body.status,
        "result_summary": body.result_summary or "",
    }

    try:
        with _SHM_COMPLETED.open("a", encoding="utf-8") as f:
            f.write(json.dumps(signal) + "\n")
    except OSError as exc:
        log.error("Failed to write sprint completion signal: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to write completion signal") from exc

    return TransitionResponse(ok=True, measure_id=measure_id, new_status=body.status)


@router.post("/gates/{gate_id}/acknowledge")
async def acknowledge_gate(gate_id: str) -> AcknowledgeResponse:
    """Acknowledge a gate nudge by setting acknowledged=true in nudge.json."""
    nudge = _read_json(_SHM_NUDGE)
    if nudge is None:
        raise HTTPException(
            status_code=404, detail=f"No active nudge file found for gate '{gate_id}'"
        )

    nudge["acknowledged"] = True

    # Atomic write: tmp + rename
    tmp = _SHM_NUDGE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(nudge), encoding="utf-8")
        tmp.rename(_SHM_NUDGE)
    except OSError as exc:
        log.error("Failed to write nudge acknowledgement: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to write acknowledgement") from exc

    return AcknowledgeResponse(ok=True, gate_id=gate_id)
