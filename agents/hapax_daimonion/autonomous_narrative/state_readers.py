"""Read state from ``/dev/shm/`` + the in-process daimonion for SS1 composition.

Per the design draft: chronicle, stimmung, director activity, programme
are the inputs. Chronicle reads MUST filter out self-authored narrative
events (``source="self_authored_narrative"``) and conversation-pipeline
events (``source="conversation_pipeline"``) so the composer doesn't
feed its own past output back into the next composition (feedback-loop
novelty degradation).

Reads are best-effort: missing files return safe defaults so the loop
never crashes on a transient SHM read miss.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_CHRONICLE_PATH = Path("/dev/shm/hapax-dmn/impingements.jsonl")
_STIMMUNG_PATH = Path("/dev/shm/hapax-stimmung/state.json")
_RESEARCH_MARKER_PATH = Path("/dev/shm/hapax-compositor/research-marker.json")
_DIRECTOR_INTENT_PATH = Path("/dev/shm/hapax-compositor/director_intent.jsonl")
_TRIAD_LEDGER_PATH = Path.home() / "hapax-state" / "outcomes" / "narration-triads.jsonl"
_TRIAD_STATE_PATH = Path("/dev/shm/hapax-daimonion/narration-triad-state.json")
_VOICE_OUTPUT_WITNESS_PATH = Path("/dev/shm/hapax-daimonion/voice-output-witness.json")

# SS2 cycle 1: vault-context grounding. Operator's recent daily notes +
# active goals flow into the prompt as "current focus" context, NOT as
# directives about what to talk about — the gating + grounding rules in
# compose.py still own emission selection. Spec: ytb-SS2 §4.
_VAULT_BASE = Path.home() / "Documents" / "Personal"
_VAULT_DAILY_DIR = _VAULT_BASE / "40-calendar" / "daily"

# Cycle-1 hyperparameters per spec §4.2 — kept module-level so cycle 2+
# changes are diffable.
_VAULT_MAX_DAILY_NOTES: int = 5
_VAULT_MAX_DAILY_BODY_BYTES: int = 1500  # per daily note, before truncation
_VAULT_MAX_TOTAL_BYTES: int = 3000  # cap on combined daily-notes excerpts
_VAULT_MAX_GOALS: int = 10
# Goal statuses considered "active" for the purpose of grounding —
# anything else is a closed concern that shouldn't shape what Hapax
# narrates about.
_VAULT_ACTIVE_GOAL_STATUSES: frozenset[str] = frozenset(
    {"active", "in_progress", "claimed", "scoped", "planned", "blocked"}
)

# Chronicle sources whose events MUST be filtered when composing — these
# are events the autonomous narrative path itself produces (or directly
# consumes), and feeding them back would create a self-referential
# novelty-degrading loop.
_SELF_AUTHORED_SOURCES: frozenset[str] = frozenset(
    {
        "autonomous_narrative",  # the impingement source we emit
        "self_authored_narrative",  # the chronicle event source we write back
        "conversation_pipeline",  # operator-facing TTS responses
    }
)

# Minimum salience for a chronicle event to be eligible for narration.
# Per spec: 0.4. Keeps the LLM grounded in actually-significant events.
_MIN_SALIENCE: float = 0.4

# Window of chronicle events to consider when composing. Per design
# draft: 5-10 min sliding window.
_CHRONICLE_WINDOW_S: float = 600.0


@dataclass(frozen=True)
class VaultContext:
    """Operator's recent vault state for SS2 cycle 1 grounding.

    Daily-note excerpts are mtime-ordered, oldest first (so the LLM
    sees temporal progression). Each excerpt is the body of the note
    truncated at ``_VAULT_MAX_DAILY_BODY_BYTES``; the combined size is
    capped at ``_VAULT_MAX_TOTAL_BYTES`` by dropping the oldest first
    if needed. Active goals are (title, priority, status) triples,
    priority-sorted (P0 first).
    """

    daily_note_excerpts: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    """``(date_label, body_excerpt)`` pairs, oldest first."""

    active_goals: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)
    """``(title, priority, status)`` triples, priority-sorted."""

    def is_empty(self) -> bool:
        return not self.daily_note_excerpts and not self.active_goals


@dataclass(frozen=True)
class NarrativeContext:
    """Snapshot of state used to compose one narrative emission."""

    programme: Any  # Programme | None — typed as Any to keep import-light
    stimmung_tone: str
    director_activity: str
    chronicle_events: tuple[dict, ...] = field(default_factory=tuple)
    vault_context: VaultContext = field(default_factory=lambda: VaultContext())
    triad_continuity: dict[str, Any] = field(default_factory=dict)


def assemble_context(daemon: Any, *, now: float | None = None) -> NarrativeContext:
    """Snapshot all inputs for one composition.

    The daemon argument is the live ``VoiceDaemon``; we pull
    ``programme_manager`` from it and read SHM directly for the rest.
    """
    chronicle_events = tuple(read_chronicle_window(now=now, window_s=_CHRONICLE_WINDOW_S))
    return NarrativeContext(
        programme=read_active_programme(daemon),
        stimmung_tone=read_stimmung_tone(),
        director_activity=read_director_activity(),
        chronicle_events=chronicle_events,
        vault_context=read_recent_vault_context(),
        triad_continuity=read_triad_continuity(chronicle_events=chronicle_events, now=now),
    )


def read_active_programme(daemon: Any) -> Any | None:
    """Pull the active Programme from the daemon's programme_manager (in-memory)."""
    pm = getattr(daemon, "programme_manager", None)
    if pm is None:
        return None
    try:
        store = pm.store
        return store.active_programme()
    except Exception as exc:
        log.debug("active programme read failed: %s", exc)
        return None


def read_stimmung_tone() -> str:
    """Read tone/stance from stimmung state, default ``"ambient"``.

    Validates the JSON root is a mapping before calling ``.get``; the
    ``except (OSError, ValueError)`` clause does not catch AttributeError,
    so a writer producing valid JSON whose root is null, a list, a
    string, or a number previously raised AttributeError out of the
    autonomous-narrative emit path. Same shape as the other recent
    SHM-read fixes (#2627, #2631, #2632, #2633, #2636 merged).
    """
    try:
        data = json.loads(_STIMMUNG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.debug("stimmung read failed: %s", exc)
        return "ambient"
    if not isinstance(data, dict):
        return "ambient"
    for key in ("tone", "stance", "overall_stance"):
        v = data.get(key)
        if isinstance(v, str):
            return v
    return "ambient"


def read_director_activity() -> str:
    """Best-effort read of the compositor's last-known activity label.

    Validates JSON roots are mappings before calling ``.get`` on them
    (same rationale as :func:`read_stimmung_tone`). Two readers here
    — the research marker and the director-intent JSONL tail — both
    needed the gate.
    """
    try:
        data = json.loads(_RESEARCH_MARKER_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if isinstance(data, dict):
        v = data.get("activity")
        if isinstance(v, str):
            return v
    try:
        with _DIRECTOR_INTENT_PATH.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
        if lines:
            last = json.loads(lines[-1])
            if isinstance(last, dict):
                v = last.get("activity") or last.get("intent")
                if isinstance(v, str):
                    return v
    except (OSError, ValueError) as exc:
        log.debug("director intent read failed: %s", exc)
    return "observe"


def read_triad_continuity(
    path: Path | None = None,
    *,
    ledger_path: Path | None = None,
    chronicle_events: tuple[dict, ...] = (),
    now: float | None = None,
) -> dict[str, Any]:
    """Read the current narration-triad continuity cache."""
    state_path = path or _TRIAD_STATE_PATH
    if path is None or ledger_path is not None:
        _refresh_triad_continuity(
            state_path=state_path,
            ledger_path=ledger_path,
            chronicle_events=chronicle_events,
            now=now,
        )
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.debug("triad continuity read failed: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def _refresh_triad_continuity(
    *,
    state_path: Path,
    ledger_path: Path | None,
    chronicle_events: tuple[dict, ...],
    now: float | None,
) -> None:
    try:
        from shared.narration_triad import (
            NarrationTriadLedger,
            triad_resolution_refs_from_events,
        )

        observed_refs, semantic_refs = triad_resolution_refs_from_events(chronicle_events)
        observed_refs.update(_voice_output_witness_refs())
        ledger = NarrationTriadLedger(
            ledger_path=ledger_path or _TRIAD_LEDGER_PATH,
            state_path=state_path,
        )
        ledger.resolve_open_triads(
            now=now,
            observed_witness_refs=observed_refs,
            semantic_closure_refs=semantic_refs,
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("triad continuity refresh failed: %s", exc)


def _voice_output_witness_refs(path: Path | None = None) -> set[str]:
    witness_path = path or _VOICE_OUTPUT_WITNESS_PATH
    try:
        data = json.loads(witness_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    refs = {"wcs:audio.broadcast_voice:voice-output-witness"}
    status = data.get("status") if isinstance(data, dict) else None
    if status == "playback_completed":
        refs.add("voice-output-witness:playback_completed")
    return refs


def read_chronicle_window(
    *,
    now: float | None = None,
    window_s: float = _CHRONICLE_WINDOW_S,
    min_salience: float = _MIN_SALIENCE,
    self_authored_sources: frozenset[str] = _SELF_AUTHORED_SOURCES,
    path: Path | None = None,
) -> list[dict]:
    """Tail recent chronicle events in the rolling window.

    Filters:
      * ``ts >= now - window_s``
      * salience >= ``min_salience`` (when present)
      * source NOT in ``self_authored_sources`` (avoid feedback loop)

    ``path`` defaults to the module-level ``_CHRONICLE_PATH`` resolved at
    call time (not at function-def time), so tests can ``monkeypatch``
    the module global to redirect reads.
    """
    if path is None:
        path = _CHRONICLE_PATH
    if not path.exists():
        return []
    cutoff = (now if now is not None else time.time()) - window_s
    out: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                ts = event.get("ts") or event.get("timestamp")
                if not isinstance(ts, (int, float)) or ts < cutoff:
                    continue
                source = event.get("source", "")
                if source in self_authored_sources:
                    continue
                salience = event.get("salience")
                if salience is None:
                    payload = event.get("content") or event.get("payload") or {}
                    if isinstance(payload, dict):
                        salience = payload.get("salience")
                if isinstance(salience, (int, float)) and salience < min_salience:
                    continue
                out.append(event)
    except OSError as exc:
        log.debug("chronicle window read failed: %s", exc)
    return out


# ── SS2 cycle 1: vault-context grounding ──────────────────────────────


def _strip_frontmatter(text: str) -> str:
    """Drop the leading ``---``-fenced YAML block, return body text.

    Intentionally minimal — full ``shared.frontmatter`` parsing is more
    expensive than necessary for the body-extraction pass, and the
    autonomous_narrative path is import-cost-conscious.
    """
    if not text.startswith("---"):
        return text
    rest = text[3:]
    if rest.startswith("\n"):
        rest = rest[1:]
    end = rest.find("\n---")
    if end < 0:
        return text  # malformed frontmatter; return original
    body = rest[end + len("\n---") :]
    return body.lstrip("\n")


def _read_daily_notes(
    *,
    daily_dir: Path,
    max_notes: int,
    max_body_bytes: int,
    max_total_bytes: int,
) -> tuple[tuple[str, str], ...]:
    """Last ``max_notes`` daily notes by mtime, oldest-first, bytes-capped."""
    if not daily_dir.is_dir():
        return ()
    try:
        candidates = [p for p in daily_dir.iterdir() if p.is_file() and p.suffix == ".md"]
    except OSError as exc:
        log.debug("vault daily dir read failed: %s", exc)
        return ()
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    selected = list(reversed(candidates[:max_notes]))  # oldest first

    excerpts: list[tuple[str, str]] = []
    total = 0
    for path in selected:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        body = _strip_frontmatter(raw).strip()
        if not body:
            continue
        if len(body) > max_body_bytes:
            body = body[:max_body_bytes].rstrip() + "…"
        excerpts.append((path.stem, body))
        total += len(body)
    # Drop oldest until under cap. Preserves the most recent context
    # under bytes pressure.
    while total > max_total_bytes and excerpts:
        dropped_label, dropped_body = excerpts.pop(0)
        total -= len(dropped_body)
        log.debug("vault excerpt dropped under cap: %s", dropped_label)
    return tuple(excerpts)


_PRIORITY_ORDER = {"P0": 0, "p0": 0, "P1": 1, "p1": 1, "P2": 2, "p2": 2, "P3": 3, "p3": 3}


def _read_active_goals(
    *,
    vault_base: Path,
    max_goals: int,
    active_statuses: frozenset[str],
) -> tuple[tuple[str, str, str], ...]:
    """Active ``type: goal`` notes, priority-sorted (P0 first)."""
    if not vault_base.is_dir():
        return ()
    try:
        from shared.frontmatter import parse_frontmatter  # noqa: PLC0415
    except ImportError:
        return ()

    found: list[tuple[str, str, str, int]] = []
    try:
        candidates = list(vault_base.rglob("*.md"))
    except OSError as exc:
        log.debug("vault goals scan failed: %s", exc)
        return ()
    for path in candidates:
        try:
            fm, _body = parse_frontmatter(path)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(fm, dict) or fm.get("type") != "goal":
            continue
        status = str(fm.get("status", "planned")).strip()
        if status not in active_statuses:
            continue
        title = str(fm.get("title", path.stem)).strip()
        priority = str(fm.get("priority", "P2")).strip()
        sort_key = _PRIORITY_ORDER.get(priority, 99)
        found.append((title, priority, status, sort_key))

    found.sort(key=lambda t: (t[3], t[0]))
    return tuple((t[0], t[1], t[2]) for t in found[:max_goals])


def read_recent_vault_context(
    *,
    vault_base: Path | None = None,
    daily_dir: Path | None = None,
    max_daily_notes: int = _VAULT_MAX_DAILY_NOTES,
    max_daily_body_bytes: int = _VAULT_MAX_DAILY_BODY_BYTES,
    max_total_bytes: int = _VAULT_MAX_TOTAL_BYTES,
    max_goals: int = _VAULT_MAX_GOALS,
    active_goal_statuses: frozenset[str] = _VAULT_ACTIVE_GOAL_STATUSES,
) -> VaultContext:
    """SS2 cycle 1 grounding source — operator's recent focus state.

    Pulls the last ``max_daily_notes`` daily notes (mtime-ordered,
    oldest first) and active ``type: goal`` notes from the vault,
    capped at ``max_total_bytes`` of combined excerpt size.

    Failure mode: if the vault directory is missing (e.g., daimonion
    running on a machine without the vault mounted), returns an empty
    ``VaultContext`` rather than raising. Empty contexts are correctly
    handled downstream (compose.py omits the vault block from the
    seed when empty).

    All bounds are arguments so cycle-2+ refinements are
    parameterizable without code changes — only the spec's H1 vs H2
    selection drives whether the bounds shift.
    """
    base = vault_base or _VAULT_BASE
    notes_dir = daily_dir or _VAULT_DAILY_DIR
    daily_excerpts = _read_daily_notes(
        daily_dir=notes_dir,
        max_notes=max_daily_notes,
        max_body_bytes=max_daily_body_bytes,
        max_total_bytes=max_total_bytes,
    )
    goals = _read_active_goals(
        vault_base=base,
        max_goals=max_goals,
        active_statuses=active_goal_statuses,
    )
    return VaultContext(daily_note_excerpts=daily_excerpts, active_goals=goals)
