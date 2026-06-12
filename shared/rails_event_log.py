"""The unified SDLC event log — the rails map's substrate (rails-map spec §2).

One append-only event log; every yard pixel is a fold over it. Watchers diff
a persisted shadow of each feed against its current state and append
transition events with full provenance. Idempotent and restartable: the
shadow IS the cursor, and event_ids are content-derived (a replayed diff
produces the same ids, which consumers dedupe on).

Distinct from shared/coord_event_log.py (the Phase-4a coordination LEDGER —
lane/dispatch actor events, SQLite-canonical): that ledger is one FEED of
this log per the spec's feed table; this log is the cross-feed FOLD the map
renders. No writer here touches the coord ledger.

Event schema (spec §2, verbatim fields):
    {event_id, item_id, kind, stage_from, stage_to, actor, lane, gate,
     verdict, reason, ts, source_file, source_offset}

Feeds folded by this first tier (the already-exported surfaces):
    * task frontmatter (stage/status transitions)  -> kind=stage / kind=status
    * *.review-dossier.yaml                        -> kind=review
    * *.acceptance.yaml                            -> kind=receipt
    * coord-activation .deployed-sha               -> kind=deploy
Later tiers (claims/sessions/MQ/PRs) ride the same shadow-diff mechanism.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from shared.sdlc_lifecycle import frontmatter_from_text

EVENT_LOG = Path.home() / ".cache/hapax/coord/sdlc-events.jsonl"
SHADOW = Path.home() / ".cache/hapax/coord/sdlc-events.shadow.json"
VAULT = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks/active"
DEPLOY_SHA_FILE = Path.home() / ".cache/hapax/coord-activation/worktree/.deployed-sha"

_TASK_FIELDS = ("stage", "status", "assigned_to", "pr")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _event_id(payload: dict[str, Any]) -> str:
    # seq distinguishes genuinely repeated transitions (a flip-flop returning
    # to the same edge) while staying replay-stable: seq derives from the
    # persisted shadow, so a re-fold after a crash-before-shadow-write
    # rederives the same ids and consumers dedupe them (review finding,
    # PR #4100 fix round).
    basis = json.dumps(
        {
            k: payload.get(k)
            for k in ("item_id", "kind", "stage_from", "stage_to", "verdict", "reason", "seq")
        },
        sort_keys=True,
    )
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def _emit(events: list[dict[str, Any]], **fields: Any) -> None:
    evt = {
        "event_id": None,
        "item_id": None,
        "kind": None,
        "stage_from": None,
        "stage_to": None,
        "actor": None,
        "lane": None,
        "gate": None,
        "verdict": None,
        "reason": None,
        "seq": None,
        "ts": _now_iso(),
        "source_file": None,
        "source_offset": None,
    }
    evt.update(fields)
    evt["event_id"] = _event_id(evt)
    events.append(evt)


def _task_facts() -> dict[str, dict[str, str]]:
    facts: dict[str, dict[str, str]] = {}
    for note in VAULT.glob("*.md"):
        try:
            text = note.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # frontmatter ONLY — a `status:` line in the note body must never
        # shadow the real task state (review finding, PR #4100 fix round)
        fm = frontmatter_from_text(text)
        fields = {k: str(fm[k]).strip() for k in _TASK_FIELDS if fm.get(k) not in (None, "")}
        if fields:
            facts[note.stem] = {**fields, "_source": str(note)}
    return facts


def _dossier_facts() -> dict[str, dict[str, Any]]:
    facts: dict[str, dict[str, Any]] = {}
    for p in VAULT.glob("*.review-dossier.yaml"):
        try:
            d = yaml.safe_load(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:  # noqa: BLE001 — a broken dossier is its own event
            facts[p.name] = {"verdict": "unparseable", "_source": str(p)}
            continue
        if isinstance(d, dict):
            facts[p.name] = {
                "verdict": d.get("review_team_verdict"),
                "head_sha": str(d.get("head_sha") or "")[:12],
                "task_id": d.get("task_id") or p.name.split(".review-dossier")[0],
                "_source": str(p),
            }
        else:
            # yaml that parses to a non-mapping is just as broken as a raise
            facts[p.name] = {"verdict": "unparseable", "_source": str(p)}
    return facts


def _acceptance_facts() -> dict[str, dict[str, Any]]:
    facts: dict[str, dict[str, Any]] = {}
    for p in VAULT.glob("*.acceptance.yaml"):
        try:
            d = yaml.safe_load(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            facts[p.name] = {"verdict": "unparseable", "_source": str(p)}
            continue
        if isinstance(d, dict):
            facts[p.name] = {
                "verdict": d.get("verdict"),
                "acceptor": str(d.get("acceptor") or "")[:80],
                "task_id": p.name.split(".acceptance")[0],
                "_source": str(p),
            }
    return facts


def _deploy_fact() -> dict[str, str]:
    if DEPLOY_SHA_FILE.exists():
        try:
            return {"sha": DEPLOY_SHA_FILE.read_text().strip()}
        except OSError:
            pass
    return {"sha": "unknown"}


def fold_once() -> int:
    """Diff every feed against the shadow; append transition events. Returns
    the number of events emitted."""
    shadow: dict[str, Any] = {}
    if SHADOW.exists():
        try:
            shadow = json.loads(SHADOW.read_text())
        except (OSError, json.JSONDecodeError):
            shadow = {}

    events: list[dict[str, Any]] = []

    # per-stream transition counters, persisted in the shadow: replay-stable
    # (a re-fold before the shadow write rederives identical seqs -> identical
    # event_ids), while a GENUINE repeat of the same edge gets a fresh seq and
    # so a distinct event_id (review finding, PR #4100 fix round)
    seq_map: dict[str, int] = dict(shadow.get("seq", {}))

    def _next_seq(item_id: str, kind: str) -> int:
        key = f"{item_id}|{kind}"
        seq_map[key] = seq_map.get(key, 0) + 1
        return seq_map[key]

    tasks = _task_facts()
    prev_tasks = shadow.get("tasks", {})
    for tid, cur in tasks.items():
        prev = prev_tasks.get(tid, {})
        for field, kind in (("stage", "stage"), ("status", "status")):
            if cur.get(field) and cur.get(field) != prev.get(field):
                _emit(
                    events,
                    item_id=tid,
                    kind=kind,
                    stage_from=prev.get(field),
                    stage_to=cur.get(field),
                    lane=cur.get("assigned_to"),
                    seq=_next_seq(tid, kind),
                    source_file=cur.get("_source"),
                )

    dossiers = _dossier_facts()
    prev_dossiers = shadow.get("dossiers", {})
    for name, cur in dossiers.items():
        prev = prev_dossiers.get(name, {})
        if (cur.get("verdict"), cur.get("head_sha")) != (
            prev.get("verdict"),
            prev.get("head_sha"),
        ):
            _emit(
                events,
                item_id=cur.get("task_id", name),
                kind="review",
                gate="review-team",
                verdict=cur.get("verdict"),
                reason=cur.get("head_sha"),
                seq=_next_seq(cur.get("task_id", name), "review"),
                source_file=cur.get("_source"),
            )

    acceptances = _acceptance_facts()
    prev_acc = shadow.get("acceptances", {})
    for name, cur in acceptances.items():
        prev = prev_acc.get(name, {})
        if cur.get("verdict") != prev.get("verdict"):
            _emit(
                events,
                item_id=cur.get("task_id", name),
                kind="receipt",
                gate="acceptance",
                verdict=cur.get("verdict"),
                actor=cur.get("acceptor"),
                seq=_next_seq(cur.get("task_id", name), "receipt"),
                source_file=cur.get("_source"),
            )

    deploy = _deploy_fact()
    if deploy.get("sha") != shadow.get("deploy", {}).get("sha"):
        _emit(
            events,
            item_id="hapax-coord",
            kind="deploy",
            stage_from=(shadow.get("deploy", {}).get("sha") or "unknown")[:9],
            stage_to=deploy["sha"][:9],
            seq=_next_seq("hapax-coord", "deploy"),
            source_file=str(DEPLOY_SHA_FILE),
        )

    if events:
        EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)
        # jsonl-rotation: exempt(registry candidate — consumer shrink-audit pending, see audit-w0 follow-up)
        with EVENT_LOG.open("a", encoding="utf-8") as f:
            for evt in events:
                f.write(json.dumps(evt, sort_keys=True) + "\n")

    new_shadow = {
        "tasks": tasks,
        "dossiers": dossiers,
        "acceptances": acceptances,
        "deploy": deploy,
        "seq": seq_map,
        "folded_at": _now_iso(),
    }
    tmp = SHADOW.with_suffix(".tmp")
    tmp.write_text(json.dumps(new_shadow))
    os.replace(tmp, SHADOW)
    return len(events)
