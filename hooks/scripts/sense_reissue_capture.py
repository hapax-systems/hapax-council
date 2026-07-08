#!/usr/bin/env python3
"""sense_reissue_capture — UserPromptSubmit hook core (gestalt-substrate Move 1).

The operator re-issues orienting research ("make sure you have all directional signals/plans
in view", "research your purview") as a SENSE-DISCHARGE of an unverifiable coverage gap. Those
directives evaporate today: said once in one lane's chat, captured nowhere role/program-scoped,
so they must be re-issued. This hook captures re-issue-shaped operator prompts as durable
``signal.reissue`` coordination events — the capture-at-utterance fix for the re-issue root cause
and the input series for the future sense-discharge canary.

Design SSOT: 30-areas/hapax/gestalt-substrate-design-2026-06-27.md.

Contract:
- Pure classifier (:func:`classify_reissue`) over a re-issue lexicon — narrow enough that ordinary
  task prompts do NOT match (false positives would train the operator to ignore the surface).
- On a match, emit via the SANCTIONED daemon CLI ``python -m shared.coord_event_log append
  --fail-open`` (the non-daemon path: the CLI commits to the canonical log or spools for daemon
  ingestion). The lane guard is not bypassed — direct ``CoordWriter.lane()`` writes stay refused;
  the CLI is the intended escape.
- HONEST receipt: "captured" only when the CLI reports ``appended``; "captured (queued)" when it
  reports ``spooled`` — never claim a write that did not happen.
- Fail-open + non-blocking: any malformed input or emit failure exits 0 with no error, so the
  operator's prompt is never blocked.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

# repo root = hooks/scripts/<this> -> parents[2]; coord CLI runs with this on the path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAX_VERBATIM = 600

# (compiled pattern, trigger_class). Deliberately narrow: each requires a coverage/purview-specific
# term, so "research the bug" / "make sure the tests pass" do NOT match. Ordered; first match wins.
_LEXICON: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(research|review|check|ingest|gather)\b[^.]{0,40}?\b"
            r"(purview|directional signal|standing (signal|guidance|direction)|"
            r"plans? and commitments?|signal/plan)\b",
            re.IGNORECASE,
        ),
        "purview",
    ),
    (
        re.compile(
            r"\b(make sure|ensure|verify|confirm|double.?check)\b[^.]{0,50}?\b"
            r"(have (all|everything)|in view|all (your |the )?"
            r"(directional |standing |recent )?(signals?|plans?|commitments?|context|docs|"
            r"leads|planning|discoveries))\b",
            re.IGNORECASE,
        ),
        "coverage",
    ),
    (
        re.compile(
            r"\b(follow (all )?(the )?leads|have everything|"
            r"make sure (you have |i have )?everything)\b",
            re.IGNORECASE,
        ),
        "completeness",
    ),
    (
        re.compile(
            r"\b(missing|not (being )?accounted for|don'?t have|overlook(ed|ing)?|"
            r"large tranche|missed)\b[^.]{0,40}?\b"
            r"(work|plan|planning|tranche|signal|context|design|thinking|docs?)\b",
            re.IGNORECASE,
        ),
        "suspected-gap",
    ),
    (
        re.compile(
            r"\b(went lossy|go lossy|lossy after|losing context|context loss)\b", re.IGNORECASE
        ),
        "lossy",
    ),
)


def _normalize(text: str) -> str:
    """Lowercase + whitespace-collapse for stable matching and hashing."""
    return re.sub(r"\s+", " ", text.strip().lower())


def classify_reissue(text: str) -> tuple[bool, str | None]:
    """Return ``(is_reissue, trigger_class)`` for an operator prompt.

    A re-issue is a prompt whose shape is "make sure you have / research your coverage" — the
    operator discharging a sense of an unaccounted-for gap. Narrow by construction to avoid
    flagging ordinary task prompts.
    """
    if not text or not text.strip():
        return (False, None)
    for pattern, trigger_class in _LEXICON:
        if pattern.search(text):
            return (True, trigger_class)
    return (False, None)


def _bucket(now: datetime) -> str:
    """Coarse (per-day) idempotency bucket: identical re-issue text the same day dedups; a genuine
    later re-issue of the same phrasing is a new event."""
    return now.astimezone(UTC).strftime("%Y-%m-%d")


def reissue_event_id(
    session_id: str, prompt: str, *, role: str, program: str | None, now: datetime
) -> str:
    """Deterministic, idempotent-on-retry event id for a captured re-issue.

    Scoped by role + program (not just session+day+prompt) so the SAME prompt captured under a
    different lane/program is a distinct event, not collapsed as a duplicate by the coord log.
    """
    digest = hashlib.sha256(
        f"{role}\x1f{program or ''}\x1f{session_id}\x1f{_bucket(now)}\x1f{_normalize(prompt)}".encode()
    ).hexdigest()
    return f"sigreissue-{digest[:32]}"


def build_emit_command(
    *,
    role: str,
    session_id: str,
    program: str | None,
    event_id: str,
    trigger_class: str,
    verbatim: str,
    python_exe: str = sys.executable,
) -> list[str]:
    """Construct the sanctioned coord-CLI argv for one ``signal.reissue`` append (fail-open)."""
    payload = json.dumps(
        {
            "trigger_class": trigger_class,
            "verbatim": verbatim[:_MAX_VERBATIM],
            "lane": role,
            "captured_by": "sense-reissue-capture",
        },
        separators=(",", ":"),
    )
    cmd = [
        python_exe,
        "-m",
        "shared.coord_event_log",
        "append",
        "--event-type",
        "signal.reissue",
        "--actor",
        role or "roleless",
        "--subject",
        session_id,
        "--event-id",
        event_id,
        "--origin",
        "sense-reissue-capture",
        "--payload",
        payload,
        "--fail-open",
    ]
    if program:
        cmd += ["--parent-spec", program]
    return cmd


def run_emit(cmd: Sequence[str]) -> dict[str, object]:
    """Run the coord-CLI append; return the parsed receipt, or ``{}`` on any failure (fail-open)."""
    try:
        proc = subprocess.run(  # noqa: S603 - argv is built internally, no shell
            list(cmd),
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        # fail-open: subprocess spawn/timeout/OS error -> empty receipt (the hook never blocks).
        return {}
    if proc.returncode != 0:
        return {}
    try:
        parsed = json.loads(proc.stdout)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _default_cache_dir() -> Path:
    """The cc-active-task MARKER dir — matches cc-claim/cc-task-gate EXACTLY: ``$HOME/.cache/hapax``.
    NOT XDG-aware: cc-claim writes the markers there unconditionally, so honoring XDG_CACHE_HOME would
    read a different directory and miss the active claim (-> no program scope)."""
    return Path.home() / ".cache" / "hapax"


def _default_tasks_dir() -> Path:
    """The cc-task SSOT ``active/`` dir, derived from the canonical
    ``shared.coord_projection.DEFAULT_VAULT_TASKS`` (the vault root cc-claim uses) imported BY
    REFERENCE so it tracks any future change and cannot drift — fail-open to the literal. No bespoke
    env var: the single source of truth is the shared constant. Resolved lazily so the import is paid
    only when a re-issue actually fires, never per prompt.
    """
    try:
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        from shared.coord_projection import DEFAULT_VAULT_TASKS

        return DEFAULT_VAULT_TASKS / "active"
    except Exception:
        # shared not importable in this context -> last-resort literal (the single-user SSOT path).
        return Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"


def _train_from_note(tasks_dir: Path, task_id: str) -> str | None:
    """Read the ``train:`` from a claimed task note. Mirrors cc-claim's note resolution: a
    descriptor-named ``<task_id>-*.md`` is preferred, then the exact ``<task_id>.md``."""
    try:
        notes = sorted(tasks_dir.glob(f"{task_id}-*.md"))
    except Exception:
        notes = []  # glob failed (e.g. dir absent) -> fall through to the exact <task_id>.md below
    notes.append(tasks_dir / f"{task_id}.md")
    for note in notes:
        try:
            lines = note.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue  # unreadable/absent note -> try the next candidate
        for line in lines:
            if line.startswith("train:"):
                train = line.split(":", 1)[1].strip()
                if train:
                    return train
    return None


def resolve_program(
    role: str,
    *,
    session_id: str | None = None,
    cache_dir: Path | None = None,
    tasks_dir: Path | None = None,
) -> str | None:
    """Best-effort program/train scope for the lane = the active cc-task's ``train`` field.

    Mirrors cc-claim's pointer convention: PREFER the session-keyed claim
    ``cc-active-task-<role>-<session_id>`` (the gate's preferred pointer), then the legacy
    ``cc-active-task-<role>`` (which cc-claim always also writes). No cross-session glob — another
    session's claim must never supply this lane's scope. The marker holds the task id; the note is
    resolved as ``<task_id>-*.md`` then ``<task_id>.md``. Any failure returns None (the event is still
    captured, just role-scoped). Never raises.
    """
    if not role:
        return None
    cache = cache_dir or _default_cache_dir()
    tasks = tasks_dir or _default_tasks_dir()
    candidates: list[Path] = []
    if session_id:
        candidates.append(cache / f"cc-active-task-{role}-{session_id}")
    candidates.append(
        cache / f"cc-active-task-{role}"
    )  # legacy fallback (always written by cc-claim)
    for marker in candidates:
        try:
            lines = marker.read_text(encoding="utf-8").strip().splitlines()
        except Exception:
            continue  # unreadable/absent marker -> try the next candidate
        task_id = lines[0].strip() if lines else ""
        if not task_id:
            continue
        train = _train_from_note(tasks, task_id)
        if train:
            return train
    return None


def format_receipt(
    receipt: dict[str, object], *, trigger_class: str, program: str | None = None
) -> str:
    """One honest line for the operator (injected as context). Distinguishes committed vs spooled,
    and only claims program-scoping when a program was actually attached."""
    scope = "role/program-scoped" if program else "role-scoped"
    if receipt.get("appended"):
        return (
            f"⟂ sense captured: signal.reissue [{trigger_class}] committed — durable + {scope}; "
            f"it propagates to the gestalt fold (no need to re-research)."
        )
    if receipt.get("spooled"):
        return (
            f"⟂ sense captured (queued for ingestion): signal.reissue [{trigger_class}] spooled — "
            f"it becomes durable and propagates once the daemon ingests the spool."
        )
    return ""


def main(
    argv: list[str] | None = None, *, stdin: object = None, now: datetime | None = None
) -> int:
    """Read the UserPromptSubmit payload, capture a re-issue if present, print an honest receipt.

    Always returns 0 (fail-open, never blocks the prompt). ``argv`` is ``[role, program?]`` supplied
    by the .sh wrapper (role resolved via agent-role.sh); ``program`` is best-effort and optional.
    """
    args = sys.argv[1:] if argv is None else argv
    role = args[0] if len(args) >= 1 else ""
    program = args[1] if len(args) >= 2 and args[1] else None
    stream = sys.stdin if stdin is None else stdin
    try:
        raw = stream.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0  # fail-open: malformed/unreadable stdin -> never block the prompt
    if not isinstance(payload, dict):
        return 0
    prompt = str(payload.get("prompt") or "")
    session_id = str(payload.get("session_id") or "unknown")

    is_reissue, trigger_class = classify_reissue(prompt)
    if not is_reissue or trigger_class is None:
        return 0

    if program is None:
        program = resolve_program(role, session_id=session_id)
    stamp = now or datetime.now(UTC)
    cmd = build_emit_command(
        role=role,
        session_id=session_id,
        program=program,
        event_id=reissue_event_id(session_id, prompt, role=role, program=program, now=stamp),
        trigger_class=trigger_class,
        verbatim=prompt,
    )
    line = format_receipt(run_emit(cmd), trigger_class=trigger_class, program=program)
    if line:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
