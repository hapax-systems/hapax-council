#!/usr/bin/env python3
"""cc-execution-attestation-check — SHADOW execution-observer caller (CEI SLICE 4 caller).

At cc-task close this observes the claiming session's transcript via the SHIPPED
``shared/execution_observer.py::observe_claude_transcript`` — which until now had ZERO
production callers — and ledgers the ``ObservedExecution`` plus every
``model_refusal_fallback`` event (a served-model mismatch, carrying ``request_id``).

That ledger write IS the receipt-attribution fix for the served-model accounting defect:
work served by a model routing never selected (e.g. a provider decline-triggered
fallback) is now attributed and JOINable on ``request_id`` at close, instead of lost.

SHADOW-only + fail-OPEN:
- OFF by default; runs only when ``HAPAX_EXECUTION_ATTESTATION=shadow``.
- NEVER blocks, slows, or crashes a closure (advisory ledger write; every error is swallowed).
- The provider decline (``trigger=refusal``) is legitimate and final. This RECORDS, never
  circumvents, quarantines, or enforce-flips. ``SERVED_MISMATCH`` stays SUSPENDED.

Modeled on ``scripts/cc-task-closure-check.py::shadow_observe``. See the supersession-aware
reconstruction: ``~/Documents/Personal/30-areas/hapax/wave3d-session-reconstruction-2026-07-09.md``.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.execution_observer import (  # noqa: E402
    UNSUPPORTED_EXECUTION_OBSERVER,
    observe_claude_transcript,
)

#: Env flag enabling the SHADOW gate (default off — observe-first doctrine).
GATE_ENV = "HAPAX_EXECUTION_ATTESTATION"
#: Optional route_id (e.g. ``claude/headless/full``) to resolve sanctioned models + verdict.
ROUTE_ENV = "HAPAX_EXECUTION_ATTESTATION_ROUTE"

LEDGER_DIR = Path.home() / ".cache" / "hapax" / "execution-attestation" / "receipts"
CLAIM_GLOB = Path.home() / ".cache" / "hapax" / "cc-active-task-*"
TRANSCRIPT_GLOB = Path.home() / ".claude" / "projects" / "*" / "*.jsonl"


def _task_id_from_note(note_path: Path) -> str:
    """Best-effort task_id from the cc-task note's frontmatter (fallback to stem)."""
    try:
        text = note_path.read_text(encoding="utf-8")
    except OSError:
        return note_path.stem
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("task_id:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return note_path.stem


_CLAIM_FILE_PREFIX = "cc-active-task-"
#: Session-keyed claim files are ``cc-active-task-<role>-<session_uuid>``. The role may
#: itself contain hyphens, so anchor on the trailing UUID (robust to hyphenated roles).
_SESSION_UUID_RE = re.compile(
    r"^cc-active-task-(.+)-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)


def _claiming_session_id(task_id: str) -> str | None:
    """The session_id that claimed ``task_id``, read from the cc-task claim files.

    Both the legacy (``cc-active-task-<role>``) and session-keyed
    (``cc-active-task-<role>-<session_uuid>``) claim files hold the task_id as their
    content. The session_id lives in the session-keyed file's trailing UUID.
    """
    cache = Path.home() / ".cache" / "hapax"
    for candidate in cache.glob("cc-active-task-*"):
        try:
            if candidate.read_text(encoding="utf-8").strip() != task_id:
                continue
        except OSError:
            continue
        match = _SESSION_UUID_RE.match(candidate.name)
        if match:
            return match.group(2)
    return None


def _scope_worktrees(note_path: Path) -> list[Path]:
    """The task's mutation-scope worktree paths (``mutation_scope_refs``), ``~`` expanded."""
    try:
        text = note_path.read_text(encoding="utf-8")
    except OSError:
        return []
    refs: list[Path] = []
    in_refs = False
    for line in text.splitlines():
        if line.strip() == "mutation_scope_refs:":
            in_refs = True
            continue
        if in_refs:
            if line.startswith(" ") or line.startswith("\t"):
                stripped = line.strip().lstrip("-").strip().strip("\"'")
                if stripped:
                    refs.append(Path(stripped).expanduser())
            else:
                break
    return refs


def _encode_project_dir(worktree: Path) -> str:
    """Claude Code encodes the cwd into the project dir name as ``<path with / -> ->``.

    e.g. ``/home/hapax/projects/hapax-council`` -> ``-home-hapax-projects-hapax-council``.
    """
    return str(worktree).replace("/", "-")


def _resolve_transcript(session_id: str | None, note_path: Path) -> Path | None:
    """Find the claiming session's Claude Code transcript.

    Two strategies (first hit wins, most-recent on ties):
    1. By ``session_id`` across every project (handles lanes whose HAPAX_SESSION_ID is the
       Claude session uuid).
    2. By the task's worktree project dir — for normal lane execution the Claude session runs
       *in* the worktree, so its transcript lives under
       ``~/.claude/projects/<encoded-worktree>/``; the most-recent there is the claiming
       session's. (The claim session_id and the Claude session uuid are different id spaces, so
       id-only resolution is unreliable; the worktree path is the robust signal.)
    """
    projects = Path.home() / ".claude" / "projects"
    candidates: list[Path] = []
    if session_id:
        for project_dir in projects.glob("*"):
            transcript = project_dir / f"{session_id}.jsonl"
            if transcript.is_file():
                candidates.append(transcript)
    for worktree in _scope_worktrees(note_path):
        project_dir = projects / _encode_project_dir(worktree)
        if project_dir.is_dir():
            candidates.extend(project_dir.glob("*.jsonl"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _ledger(task_id: str, payload: dict) -> Path:
    """Write the attestation receipt for ``task_id`` (idempotent overwrite per close)."""
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    path = LEDGER_DIR / f"{task_id}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def observe_close(note_path: Path) -> dict:
    """Observe the claiming session's transcript + ledger the result. Pure: never raises."""
    task_id = _task_id_from_note(note_path)
    session_id = _claiming_session_id(task_id)
    transcript = _resolve_transcript(session_id, note_path)

    payload: dict = {
        "task_id": task_id,
        "session_id": session_id,
        "transcript": str(transcript) if transcript else None,
        "observed_models": [],
        "turn_count": 0,
        "fallback_events": [],
        "verdict": None,
        "malformed_lines": 0,
        "note": "SHADOW execution-attestation receipt (advisory; never blocks close).",
    }

    if transcript is None:
        payload["note"] = "no claiming-session transcript found; nothing to observe."
        return payload

    observed = observe_claude_transcript(transcript)
    payload["observed_models"] = sorted(observed.models)
    payload["turn_count"] = observed.turn_count
    payload["malformed_lines"] = observed.malformed_lines
    payload["fallback_events"] = [
        {
            "from_model": ev.from_model,
            "to_model": ev.to_model,
            "trigger": ev.trigger,
            "request_id": ev.request_id,
        }
        for ev in observed.fallback_events
    ]

    # Optional verdict when a route_id is supplied (sanctioned ⊇ observed). Fail-OPEN:
    # an unknown route or missing registry records observed-only, never blocks.
    route_id = os.environ.get(ROUTE_ENV, "").strip() or None
    if route_id:
        try:
            from shared.execution_attestation import attest_transcript  # noqa: PLC0415

            verdict = attest_transcript(transcript, frozenset(), carrier="claude")
            # Empty sanctioned set → verdict surfaces UNSUPPORTED/DRIFT honestly; callers
            # resolve the real sanctioned set via sanctioned_models_for_route when wiring
            # the gate to a known route. Recorded, not enforced.
            payload["verdict"] = {
                "status": verdict.status,
                "admissible": verdict.admissible,
                "unsanctioned_models": sorted(verdict.unsanctioned_models),
            }
        except Exception as exc:  # noqa: BLE001 — advisory: never raise
            payload["verdict"] = {"error": f"{type(exc).__name__}: {exc}"}
    else:
        payload["verdict"] = {"status": UNSUPPORTED_EXECUTION_OBSERVER, "admissible": False}

    return payload


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: cc-execution-attestation-check.py <path-to-cc-task.md>", file=sys.stderr)
        return 64
    # SHADOW-only: off unless explicitly enabled. Byte-identical to no-op without the env.
    if os.environ.get(GATE_ENV, "").strip().lower() != "shadow":
        return 0
    note_path = Path(argv[1])
    try:
        payload = observe_close(note_path)
        _ledger(payload["task_id"], payload)
    except Exception as exc:  # noqa: BLE001 — advisory: a failure must never affect closure
        print(f"cc-execution-attestation-check: advisory observe failed ({exc})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
