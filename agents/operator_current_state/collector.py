"""Collect private operator current-state from governed local sources."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from agents.operator_current_state.state import (
    Conflict,
    Counts,
    OperatorCurrentState,
    OperatorCurrentStateItem,
    PrivacyFilter,
    Readiness,
    ReadinessBlocker,
    SourceStatus,
    parse_timestamp,
    utc_now,
)


@dataclass(frozen=True)
class OperatorCurrentStatePaths:
    planning_feed: Path = Path.home() / ".cache" / "hapax" / "planning-feed-state.json"
    requests_dir: Path = (
        Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-requests" / "active"
    )
    cc_tasks_dir: Path = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    claims_dir: Path = Path.home() / ".cache" / "hapax"
    relay_dir: Path = Path.home() / ".cache" / "hapax" / "relay"
    awareness_state: Path = Path("/dev/shm/hapax-awareness/state.json")
    operator_now_seed: Path = (
        Path.home()
        / "Documents"
        / "Personal"
        / "20-projects"
        / "hapax-requests"
        / "_dashboard"
        / "operator-now.md"
    )
    cc_operator_blocking: Path = (
        Path.home()
        / "Documents"
        / "Personal"
        / "20-projects"
        / "hapax-cc-tasks"
        / "_dashboard"
        / "cc-operator-blocking.md"
    )
    hn_receipts_dir: Path = Path("/tmp")

    @property
    def active_tasks_dir(self) -> Path:
        return self.cc_tasks_dir / "active"

    @property
    def closed_tasks_dir(self) -> Path:
        return self.cc_tasks_dir / "closed"


def collect_operator_current_state(
    paths: OperatorCurrentStatePaths | None = None,
    *,
    now: datetime | None = None,
    public_projection_authorized: bool = False,
) -> OperatorCurrentState:
    paths = paths or OperatorCurrentStatePaths()
    now = now or utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    source_status: dict[str, SourceStatus] = {}
    blockers: list[ReadinessBlocker] = []
    items: list[OperatorCurrentStateItem] = []

    planning_feed = _load_planning_feed(paths.planning_feed)
    source_status["planning_feed"] = _file_status(
        paths.planning_feed,
        now,
        required=True,
        authority="derived",
        max_age=timedelta(minutes=5),
        generated_at=parse_timestamp(planning_feed.get("generated_at"))
        if isinstance(planning_feed, dict)
        else None,
    )

    requests = _load_frontmatter_dir(paths.requests_dir)
    source_status["active_requests"] = _dir_status(
        paths.requests_dir, now, required=True, authority="authoritative", error=requests.error
    )

    active_tasks = _load_frontmatter_dir(paths.active_tasks_dir)
    source_status["active_tasks"] = _dir_status(
        paths.active_tasks_dir,
        now,
        required=True,
        authority="authoritative",
        error=active_tasks.error,
    )

    closed_tasks = _load_frontmatter_dir(paths.closed_tasks_dir)
    source_status["closed_tasks"] = _dir_status(
        paths.closed_tasks_dir,
        now,
        required=True,
        authority="authoritative",
        error=closed_tasks.error,
    )

    claims = _claim_files(paths.claims_dir)
    source_status["active_claims"] = _dir_status(
        paths.claims_dir, now, required=True, authority="derived", max_age=timedelta(minutes=30)
    )

    relay_notes = _recent_relay_notes(paths.relay_dir, now)
    source_status["relay_recent"] = _dir_status(
        paths.relay_dir, now, required=True, authority="advisory", max_age=timedelta(hours=24)
    )

    source_status["operator_now_seed"] = _file_status(
        paths.operator_now_seed,
        now,
        required=False,
        authority="historical",
        max_age=None,
    )
    source_status["cc_operator_blocking"] = _file_status(
        paths.cc_operator_blocking,
        now,
        required=False,
        authority="historical",
        max_age=None,
    )

    awareness = _load_json(paths.awareness_state)
    awareness_generated = (
        parse_timestamp(awareness.get("timestamp")) if isinstance(awareness, dict) else None
    )
    awareness_ttl = (
        _safe_int(awareness.get("ttl_seconds"), default=90) if isinstance(awareness, dict) else 90
    )
    source_status["awareness_state"] = _file_status(
        paths.awareness_state,
        now,
        required=False,
        authority="derived",
        max_age=timedelta(seconds=awareness_ttl),
        generated_at=awareness_generated,
    )

    source_status["hn_readiness_receipts"] = _hn_receipt_status(paths.hn_receipts_dir, now)

    for source_id, status in source_status.items():
        if status.required and status.predicate_value != "fresh":
            blockers.append(
                ReadinessBlocker(
                    source=source_id,
                    reason=status.error or f"source is {status.predicate_value}",
                    predicate_family="freshness",
                    predicate_value=status.predicate_value,
                )
            )

    items.extend(_items_from_tasks(active_tasks.records, now, public_projection_authorized))
    items.extend(_items_from_planning_feed(planning_feed, active_tasks.records, now))
    items.extend(_items_from_relay(relay_notes, active_tasks.records, now))
    items.extend(_items_from_claims(claims, active_tasks.records, now))
    items.extend(_items_from_historical(paths.cc_operator_blocking, now))
    items.extend(_items_from_awareness(source_status["awareness_state"], now))

    item_conflict = any(item.conflicts for item in items)
    if item_conflict:
        blockers.append(
            ReadinessBlocker(
                source="items",
                reason="item conflict",
                predicate_family="methodology",
                predicate_value="conflict",
            )
        )

    readiness_value = "ready" if not blockers else "unknown"
    if readiness_value == "ready" and not any(item.class_ in {"do", "decide"} for item in items):
        items.append(
            _item(
                "know",
                "no-verified-action",
                "No verified operator action",
                "All required sources were fresh and no active do/decide item was found.",
                now,
                source_ref=str(paths.planning_feed),
                predicate_family="readiness",
                predicate_value="ready",
                confidence="high",
                status="active",
            )
        )

    counts = Counts(
        know=sum(1 for item in items if item.class_ == "know"),
        do=sum(1 for item in items if item.class_ == "do"),
        decide=sum(1 for item in items if item.class_ == "decide"),
        expect=sum(1 for item in items if item.class_ == "expect"),
        watch=sum(1 for item in items if item.class_ == "watch"),
    )

    return OperatorCurrentState(
        generated_at=now,
        readiness=Readiness(value=readiness_value, blockers=blockers),
        source_status=source_status,
        items=items,
        counts=counts,
        privacy_filter=PrivacyFilter(public_projection_authorized=public_projection_authorized),
    )


@dataclass(frozen=True)
class FrontmatterLoad:
    records: list[tuple[Path, dict[str, Any], str]]
    error: str | None = None


def _load_frontmatter_dir(path: Path) -> FrontmatterLoad:
    if not path.exists():
        return FrontmatterLoad([], "missing")
    if not path.is_dir():
        return FrontmatterLoad([], "not_directory")
    records: list[tuple[Path, dict[str, Any], str]] = []
    try:
        for note in sorted(path.glob("*.md")):
            text = note.read_text(encoding="utf-8")
            records.append((note, _frontmatter(text), text))
    except OSError as exc:
        return FrontmatterLoad(records, str(exc))
    return FrontmatterLoad(records)


def _frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    loaded = yaml.safe_load(parts[1]) or {}
    return loaded if isinstance(loaded, dict) else {}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _load_planning_feed(path: Path) -> dict[str, Any]:
    return _load_json(path)


def _file_status(
    path: Path,
    now: datetime,
    *,
    required: bool,
    authority: str,
    max_age: timedelta | None,
    generated_at: datetime | None = None,
) -> SourceStatus:
    if not path.exists():
        return _source_status(path, now, required, authority, "missing", max_age, error="missing")
    evaluated_at = generated_at or datetime.fromtimestamp(path.stat().st_mtime, UTC)
    if max_age is None:
        return _source_status(
            path, now, required, authority, "fresh", None, evaluated_at=evaluated_at
        )
    stale_after = evaluated_at + max_age
    value = "fresh" if stale_after > now else "stale"
    return _source_status(path, now, required, authority, value, max_age, evaluated_at=evaluated_at)


def _dir_status(
    path: Path,
    now: datetime,
    *,
    required: bool,
    authority: str,
    max_age: timedelta | None = None,
    error: str | None = None,
) -> SourceStatus:
    if error:
        return _source_status(path, now, required, authority, "unknown", max_age, error=error)
    if not path.exists():
        return _source_status(path, now, required, authority, "missing", max_age, error="missing")
    if not path.is_dir():
        return _source_status(
            path, now, required, authority, "unknown", max_age, error="not_directory"
        )
    return _source_status(path, now, required, authority, "fresh", max_age)


def _source_status(
    path: Path,
    now: datetime,
    required: bool,
    authority: str,
    value: str,
    max_age: timedelta | None,
    *,
    evaluated_at: datetime | None = None,
    error: str | None = None,
) -> SourceStatus:
    evaluated_at = evaluated_at or now
    stale_after = evaluated_at + (max_age or timedelta(days=36500))
    return SourceStatus(
        path=str(path),
        required=required,
        authority=authority,  # type: ignore[arg-type]
        predicate_value=value,  # type: ignore[arg-type]
        evaluated_at=evaluated_at,
        stale_after=stale_after,
        error=error,
    )


def _items_from_tasks(
    records: list[tuple[Path, dict[str, Any], str]],
    now: datetime,
    public_projection_authorized: bool,
) -> list[OperatorCurrentStateItem]:
    items: list[OperatorCurrentStateItem] = []
    for path, fm, _text in records:
        tags = _as_list(fm.get("tags"))
        operator_required = _truthy(fm.get("operator_required"))
        has_operator_tag = any(
            tag in {"operator-action", "operator-physical", "operator-decision"} for tag in tags
        )
        privacy = str(fm.get("privacy_class") or "private_operator")
        if privacy == "public_safe" and not public_projection_authorized:
            items.append(
                _item(
                    "watch",
                    f"privacy-denial:{path.name}",
                    f"Public-safe denied for {fm.get('task_id', path.stem)}",
                    "A source attempted public_safe without a public projection ISAP.",
                    now,
                    source_ref=str(path),
                    predicate_family="authorization",
                    predicate_value="denied",
                    confidence="high",
                    status="blocked",
                    conflicts=[
                        Conflict(
                            source_ref=str(path),
                            predicate_value="public_safe",
                            note="public projection not authorized",
                        )
                    ],
                )
            )
        if not operator_required and not has_operator_tag:
            continue
        cls = "decide" if "operator-decision" in tags else "do"
        items.append(
            _item(
                cls,
                f"task:{fm.get('task_id', path.stem)}",
                str(fm.get("title") or fm.get("task_id") or path.stem),
                str(fm.get("blocked_reason") or ""),
                now,
                source_ref=str(path),
                predicate_family="methodology",
                predicate_value=str(fm.get("status") or "unknown"),
                confidence="high",
                status="active",
                operator_required=True,
                urgency="today",
            )
        )
    return items


def _items_from_planning_feed(
    feed: dict[str, Any],
    active_tasks: list[tuple[Path, dict[str, Any], str]],
    now: datetime,
) -> list[OperatorCurrentStateItem]:
    if not feed:
        return []
    items: list[OperatorCurrentStateItem] = []
    for attention in feed.get("attention_required") or []:
        if not isinstance(attention, dict):
            continue
        req_id = str(attention.get("request_id") or "unknown")
        items.append(
            _item(
                "watch",
                f"planning:{req_id}",
                f"Planning attention: {req_id}",
                str(attention.get("action") or attention.get("action_needed") or ""),
                now,
                source_ref="planning-feed:attention_required",
                predicate_family="methodology",
                predicate_value=str(attention.get("coverage") or "unknown"),
                confidence="medium",
                status="active",
            )
        )
    task_request_refs = {_request_basename(fm.get("parent_request")) for _, fm, _ in active_tasks}
    for req in feed.get("requests") or []:
        if not isinstance(req, dict):
            continue
        req_id = str(req.get("request_id") or "")
        if req.get("coverage") == "untracked" and req_id in task_request_refs:
            items.append(
                _item(
                    "watch",
                    f"coverage-mismatch:{req_id}",
                    f"Coverage mismatch for {req_id}",
                    "Planning feed marks request untracked while an active task references it.",
                    now,
                    source_ref="planning-feed:requests",
                    predicate_family="methodology",
                    predicate_value="conflict",
                    confidence="high",
                    status="active",
                    conflicts=[
                        Conflict(
                            source_ref="active_tasks",
                            predicate_value="task_exists",
                            note="active task references request",
                        )
                    ],
                )
            )
    return items


def _items_from_relay(
    relay_notes: list[tuple[Path, str]],
    active_tasks: list[tuple[Path, dict[str, Any], str]],
    now: datetime,
) -> list[OperatorCurrentStateItem]:
    items: list[OperatorCurrentStateItem] = []
    task_operator_required = {
        str(fm.get("task_id") or path.stem): _task_requires_operator(fm)
        for path, fm, _ in active_tasks
    }
    for path, text in relay_notes:
        lower = text.lower()
        if "operator action" not in lower and "operator_required" not in lower:
            continue
        task_match = re.search(r"(?im)^\s*task_id\s*:\s*([A-Za-z0-9_.:-]+)\s*$", text)
        relay_operator_required = "operator_required" in lower or "operator action" in lower
        if task_match:
            task_id = task_match.group(1)
            task_requires_operator = task_operator_required.get(task_id)
            if task_requires_operator is False and relay_operator_required:
                items.append(
                    _item(
                        "watch",
                        f"relay-task-conflict:{path.name}:{task_id}",
                        "Relay/task operator obligation conflict",
                        "Relay text claims operator action for a task whose authoritative task note does not.",
                        now,
                        source_ref=str(path),
                        predicate_family="methodology",
                        predicate_value="conflict",
                        confidence="high",
                        status="blocked",
                        conflicts=[
                            Conflict(
                                source_ref=f"active_tasks:{task_id}",
                                predicate_value="operator_required_false",
                                note="relay note claims operator action",
                            )
                        ],
                    )
                )
            continue
        has_governed_ref = any(token in text for token in ("CASE-", "REQ-"))
        if has_governed_ref:
            continue
        items.append(
            _item(
                "watch",
                f"relay-advisory:{path.name}",
                "Ungoverned relay operator action mention",
                "Relay text mentions operator action without a task, case, or request reference.",
                now,
                source_ref=str(path),
                predicate_family="methodology",
                predicate_value="advisory",
                confidence="medium",
                status="active",
            )
        )
    return items


def _task_requires_operator(fm: dict[str, Any]) -> bool:
    tags = _as_list(fm.get("tags"))
    return _truthy(fm.get("operator_required")) or any(
        tag in {"operator-action", "operator-physical", "operator-decision"} for tag in tags
    )


def _items_from_claims(
    claims: list[tuple[Path, str]],
    active_tasks: list[tuple[Path, dict[str, Any], str]],
    now: datetime,
) -> list[OperatorCurrentStateItem]:
    task_ids = {str(fm.get("task_id") or path.stem) for path, fm, _ in active_tasks}
    items: list[OperatorCurrentStateItem] = []
    for path, task_id in claims:
        if task_id and task_id not in task_ids:
            items.append(
                _item(
                    "watch",
                    f"claim-missing-task:{task_id}",
                    f"Active claim references missing task {task_id}",
                    "Claim file exists but no active task file with that task_id was found.",
                    now,
                    source_ref=str(path),
                    predicate_family="dependency",
                    predicate_value="not_found",
                    confidence="medium",
                    status="active",
                )
            )
    return items


def _items_from_historical(path: Path, now: datetime) -> list[OperatorCurrentStateItem]:
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8").lower()
    except OSError:
        return []
    if "action" not in text and "due" not in text:
        return []
    return [
        _item(
            "watch",
            "historical-operator-blocking-excluded",
            "Historical operator dashboard excluded",
            "cc-operator-blocking is historical input and cannot create current do/decide items.",
            now,
            source_ref=str(path),
            predicate_family="freshness",
            predicate_value="historical",
            confidence="high",
            status="stale",
        )
    ]


def _items_from_awareness(status: SourceStatus, now: datetime) -> list[OperatorCurrentStateItem]:
    if status.predicate_value == "fresh":
        return []
    return [
        _item(
            "watch",
            "awareness-state-not-fresh",
            "Awareness state not fresh",
            f"Runtime awareness source is {status.predicate_value}; this is telemetry, not an operator obligation.",
            now,
            source_ref=status.path,
            predicate_family="freshness",
            predicate_value=status.predicate_value,
            confidence="medium",
            status="stale" if status.predicate_value == "stale" else "unknown",
        )
    ]


def _claim_files(path: Path) -> list[tuple[Path, str]]:
    if not path.exists() or not path.is_dir():
        return []
    claims: list[tuple[Path, str]] = []
    for claim in sorted(path.glob("cc-active-task-*")):
        try:
            claims.append((claim, claim.read_text(encoding="utf-8").strip()))
        except OSError:
            continue
    return claims


def _recent_relay_notes(path: Path, now: datetime) -> list[tuple[Path, str]]:
    if not path.exists() or not path.is_dir():
        return []
    notes: list[tuple[Path, str]] = []
    cutoff = now - timedelta(hours=24)
    for note in sorted(path.glob("*.md")):
        try:
            if datetime.fromtimestamp(note.stat().st_mtime, UTC) < cutoff:
                continue
            notes.append((note, note.read_text(encoding="utf-8")))
        except OSError:
            continue
    return notes


def _hn_receipt_status(path: Path, now: datetime) -> SourceStatus:
    if not path.exists() or not path.is_dir():
        return _source_status(path, now, False, "derived", "missing", timedelta(minutes=60))
    receipts = sorted(
        path.glob("hapax-hn-systems-readiness-*.json"), key=lambda p: p.stat().st_mtime
    )
    if not receipts:
        return _source_status(path, now, False, "derived", "missing", timedelta(minutes=60))
    latest = receipts[-1]
    generated = datetime.fromtimestamp(latest.stat().st_mtime, UTC)
    value = "fresh" if generated + timedelta(minutes=60) > now else "stale"
    return _source_status(
        latest, now, False, "derived", value, timedelta(minutes=60), evaluated_at=generated
    )


def _item(
    cls: str,
    key: str,
    summary: str,
    details: str,
    now: datetime,
    *,
    source_ref: str,
    predicate_family: str,
    predicate_value: str,
    confidence: str,
    status: str,
    operator_required: bool = False,
    urgency: str = "routine",
    conflicts: list[Conflict] | None = None,
) -> OperatorCurrentStateItem:
    item_id = "ocs:{}:{}".format(
        cls, hashlib.sha256(key.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    )
    return OperatorCurrentStateItem(
        **{
            "id": item_id,
            "class": cls,
            "summary": summary,
            "details": details,
            "owner": "operator" if operator_required else "system",
            "operator_required": operator_required,
            "urgency": urgency,
            "due_at": None,
            "next_check_at": None,
            "stale_after": now + timedelta(minutes=15),
            "source_ref": source_ref,
            "evidence_ref": source_ref,
            "predicate_family": predicate_family,
            "predicate_value": predicate_value,
            "confidence": confidence,
            "escalation_policy": "dashboard",
            "privacy_class": "private_operator",
            "status": status,
            "conflicts": conflicts or [],
        }
    )


def _as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _safe_int(value: object, *, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _request_basename(value: object) -> str:
    if not value:
        return ""
    text = str(value)
    return Path(text).stem.split("-operator-current-state-cockpit")[0] if "/" in text else text
