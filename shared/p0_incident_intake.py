"""P0 technical-alert intake for governed SDLC consumption.

Desktop notifications are a delivery surface, not a durable work queue. This
module turns high-severity technical/system alerts into one deterministic
cc-task per incident fingerprint, then keeps subsequent alerts attached to that
same task and an incident JSONL ledger.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from shared.jsonl_append import append_jsonl

DEFAULT_STATE_PATH = Path.home() / ".cache" / "hapax" / "p0-incident-intake" / "state.json"
DEFAULT_LEDGER_PATH = Path.home() / ".cache" / "hapax" / "p0-incident-intake" / "events.jsonl"
DEFAULT_TASK_ROOT = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
DEFAULT_PARENT_REQUEST = "REQ-20260611-failure-ledger-longitudinal.md"
DEFAULT_PARENT_SPEC = (
    "/home/hapax/Documents/Personal/30-areas/hapax/failure-ledger-sdlc-feedback-2026-06-11.md"
)
DEFAULT_AUTHORITY_CASE = "CASE-SYSTEM-INTEGRITY-20260611"
DEFAULT_VAULT_NAME = "Personal"
LATEST_ALERT_BLOCK_RE = re.compile(r"(?s)## Latest Alert\n\n.*?\n## Evidence\n")

log = logging.getLogger(__name__)


TECHNICAL_TITLE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("Service Failed:", "systemd_service_failed"),
    ("Stack Failed", "health_stack_failed"),
    ("Health Monitor Failed", "health_monitor_failed"),
    ("Health:", "health_monitor_alert"),
    ("Backup Health FAIL", "backup_health_failed"),
    ("Disk CRITICAL", "disk_critical"),
    ("VRAM Emergency", "vram_emergency"),
    ("SDLC invariant violation", "sdlc_invariant_violation"),
    ("SDLC: dispatch refusal circuit breaker", "sdlc_dispatch_refusal"),
    ("SDLC: dispatch starvation detected", "sdlc_dispatch_starvation"),
    ("SDLC: task stuck, blocked", "sdlc_task_stalled"),
    ("[VIOLATION]", "cc_hygiene_violation"),
    ("Infra Registry Drift", "infra_registry_drift"),
    ("Hapax lane-supervisor:", "lane_supervisor_alert"),
    ("LUFS panic-cap", "audio_lufs_breach"),
    ("Audio: LUFS Breach", "audio_lufs_breach"),
    ("Audio: Crest spike", "audio_crest_spike"),
    ("Audio: Topology Drift", "audio_topology_drift"),
    ("Voice witness watchdog:", "voice_witness_watchdog"),
    ("Drift Detector Failed", "drift_detector_failed"),
    ("Disk Space", "disk_space_critical"),
    ("Recovery escalation", "recovery_escalation"),
    ("Recovery governor fail-open", "recovery_governor_failopen"),
)


@dataclass(frozen=True)
class IncidentClassification:
    kind: str
    fingerprint: str
    technical: bool
    reason: str


@dataclass(frozen=True)
class IntakeResult:
    technical: bool
    created: bool = False
    updated: bool = False
    task_id: str | None = None
    task_path: Path | None = None
    fingerprint: str | None = None
    replace_id: int | None = None
    click_url: str | None = None
    reason: str = ""
    recurrence: bool = False
    recurrence_of_task_id: str | None = None
    recurrence_of_task_path: Path | None = None


@dataclass(frozen=True)
class _TaskMatch:
    path: Path
    closed: bool


def classify_notification(
    title: str,
    message: str,
    *,
    priority: str = "default",
    tags: list[str] | None = None,
    technical: bool | None = None,
) -> IncidentClassification:
    """Classify whether a notification should become SDLC incident intake."""

    title_s = title.strip()
    message_s = message.strip()
    priority_s = priority.strip().lower()
    tags_s = {str(tag).strip().lower() for tag in tags or [] if str(tag).strip()}

    if technical is False:
        return IncidentClassification("nontechnical", "", False, "technical_false")

    kind = _technical_kind(title_s)
    if kind == "sdlc_task_stalled":
        # Self-amplification break: a stalled/blocked AUTO-MINTED incident task
        # (p0-incident-*) must NOT mint another P0 — it would re-enter forever as a
        # fresh sdlc_task_stalled incident. These tasks are not lane-workable.
        _stalled_id = re.search(r"\b(?:Task\s+)?([a-z0-9][a-z0-9_.-]{8,})\b", message_s)
        if _stalled_id and _stalled_id.group(1).startswith("p0-incident-"):
            return IncidentClassification(
                "nontechnical", "", False, "stalled_incident_task_no_remint"
            )
    if technical is True and not kind:
        kind = "technical_alert"

    if not kind:
        return IncidentClassification("nontechnical", "", False, "no_technical_pattern")

    if priority_s not in {"high", "urgent"} and not (tags_s & {"skull", "rotating_light"}):
        return IncidentClassification(kind, "", False, "below_p0_priority")

    return IncidentClassification(kind, _fingerprint_for(kind, title_s, message_s), True, "matched")


def record_notification(
    title: str,
    message: str,
    *,
    priority: str = "default",
    tags: list[str] | None = None,
    technical: bool | None = None,
    task_root: Path = DEFAULT_TASK_ROOT,
    state_path: Path = DEFAULT_STATE_PATH,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    now: datetime | None = None,
) -> IntakeResult:
    """Create or update the governed SDLC intake item for a technical alert."""

    now = now or datetime.now(UTC)
    classification = classify_notification(
        title,
        message,
        priority=priority,
        tags=tags,
        technical=technical,
    )
    if not classification.technical:
        return IntakeResult(technical=False, reason=classification.reason)

    with _state_file_lock(state_path):
        return _record_notification_locked(
            title,
            message,
            priority=priority,
            tags=tags,
            task_root=task_root,
            state_path=state_path,
            ledger_path=ledger_path,
            now=now,
            classification=classification,
        )


def _record_notification_locked(
    title: str,
    message: str,
    *,
    priority: str,
    tags: list[str] | None,
    task_root: Path,
    state_path: Path,
    ledger_path: Path,
    now: datetime,
    classification: IncidentClassification,
) -> IntakeResult:
    state = _load_state(state_path)
    incidents = state.setdefault("incidents", {})
    existing = incidents.get(classification.fingerprint, {})
    base_task_id = str(existing.get("base_task_id") or _task_id_for(classification.fingerprint))
    task_id = str(existing.get("task_id") or base_task_id)
    task_match = _find_task(task_root, task_id)
    task_path = task_match.path if task_match is not None else None
    first_seen = str(existing.get("first_seen") or _iso(now))
    count = int(existing.get("count", 0)) + 1
    recurrence_count = int(existing.get("recurrence_count", 0) or 0)
    task_record = {
        "fingerprint": classification.fingerprint,
        "kind": classification.kind,
        "base_task_id": base_task_id,
        "task_id": task_id,
        "first_seen": first_seen,
        "last_seen": _iso(now),
        "count": count,
        "recurrence_count": recurrence_count,
        "priority": "p0",
        "last_title": title.strip(),
        "last_message": _clip(message.strip(), 1200),
        "tags": list(tags or []),
    }

    created = False
    updated = False
    recurrence = False
    recurrence_of_task_id = None
    recurrence_of_task_path = None
    if task_match is not None and task_match.closed:
        recurrence = True
        recurrence_count += 1
        recurrence_of_task_id = task_id
        recurrence_of_task_path = task_match.path
        task_id = _available_recurrence_task_id(task_root, base_task_id, recurrence_count)
        task_path = task_root / "active" / f"{task_id}-{_slugify(title, 48)}.md"
        task_record.update(
            {
                "task_id": task_id,
                "recurrence_count": recurrence_count,
                "recurrence_of_task_id": recurrence_of_task_id,
                "recurrence_of_task_path": str(recurrence_of_task_path),
            }
        )
        _write_new_task(
            task_path,
            task_record,
            title=title,
            message=message,
            now=now,
            ledger_path=ledger_path,
            state_path=state_path,
        )
        created = True
    elif task_path is None:
        task_path = task_root / "active" / f"{task_id}-{_slugify(title, 48)}.md"
        _write_new_task(
            task_path,
            task_record,
            title=title,
            message=message,
            now=now,
            ledger_path=ledger_path,
            state_path=state_path,
        )
        created = True
    else:
        _update_existing_task(task_path, task_record, title=title, message=message, now=now)
        updated = True

    task_record["task_path"] = str(task_path)
    # Persist coalescing state FIRST: a ledger IO failure must NOT abort the state
    # write, else the next identical alert re-mints -> re-flood. Fail-open on the ledger.
    incidents[classification.fingerprint] = task_record
    state["updated_at"] = _iso(now)
    _store_state(state_path, state)
    _rotate_ledger(ledger_path)
    appended = append_jsonl(
        ledger_path,
        {
            "ts": _iso(now),
            "kind": "p0_incident_notification",
            "incident_kind": classification.kind,
            "fingerprint": classification.fingerprint,
            "task_id": task_id,
            "task_path": str(task_path),
            "count": count,
            "title": title.strip(),
            "message": _clip(message.strip(), 1200),
            "tags": list(tags or []),
            "priority": priority,
            "recurrence": recurrence,
            "recurrence_count": recurrence_count,
            "recurrence_of_task_id": recurrence_of_task_id,
            "recurrence_of_task_path": str(recurrence_of_task_path)
            if recurrence_of_task_path is not None
            else None,
        },
        sort_keys=True,
        raising=False,
    )
    if not appended:
        log.warning(
            "p0 incident ledger append failed (coalescing state persisted; continuing): %s",
            ledger_path,
        )

    return IntakeResult(
        technical=True,
        created=created,
        updated=updated,
        task_id=task_id,
        task_path=task_path,
        fingerprint=classification.fingerprint,
        replace_id=replace_id_for_fingerprint(classification.fingerprint),
        click_url=obsidian_task_uri(task_path),
        reason=classification.reason,
        recurrence=recurrence,
        recurrence_of_task_id=recurrence_of_task_id,
        recurrence_of_task_path=recurrence_of_task_path,
    )


def replace_id_for_fingerprint(fingerprint: str) -> int:
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 2_147_483_647


def obsidian_task_uri(task_path: Path, *, vault_name: str = DEFAULT_VAULT_NAME) -> str:
    try:
        rel = task_path.with_suffix("").relative_to(Path.home() / "Documents" / "Personal")
    except ValueError:
        rel = task_path.with_suffix("")
    return f"obsidian://open?vault={quote(vault_name)}&file={quote(str(rel))}"


def _technical_kind(title: str) -> str:
    for prefix, kind in TECHNICAL_TITLE_PATTERNS:
        if title.startswith(prefix):
            return kind
    return ""


def _fingerprint_for(kind: str, title: str, message: str) -> str:
    if kind == "systemd_service_failed":
        unit = title.split(":", 1)[1].strip() if ":" in title else title
        return f"{kind}:{unit}"
    if kind == "cc_hygiene_violation":
        check = title.replace("[VIOLATION]", "", 1).strip() or "unknown"
        pr = re.search(r"\bPR\s+#?(\d+)\b", message)
        suffix = pr.group(1) if pr else _slugify(message, 40)
        return f"{kind}:{check}:{suffix}"
    if kind == "sdlc_invariant_violation":
        inv = re.search(r"\bINV-\d+\b", message)
        return f"{kind}:{inv.group(0) if inv else 'unknown'}"
    if kind in {"sdlc_dispatch_refusal", "sdlc_dispatch_starvation", "sdlc_task_stalled"}:
        task = re.search(r"\b(?:Task\s+)?([a-z0-9][a-z0-9_.-]{8,})\b", message)
        return f"{kind}:{task.group(1) if task else _slugify(message, 80)}"
    if kind == "infra_registry_drift":
        return kind
    if kind == "lane_supervisor_alert":
        lane = re.search(r"Hapax lane-supervisor:\s+([a-z0-9_-]+)\b", title, re.IGNORECASE)
        subject = lane.group(1).lower() if lane else _slugify(title, 40)
        if "lifetime ceiling" in title:
            return f"{kind}:launcher_lifetime:{subject}"
        if "respawn failing" in title:
            return f"{kind}:respawn_failing:{subject}"
        if "has no worktree" in title:
            return f"{kind}:missing_worktree:{subject}"
        return f"{kind}:{subject}"
    return f"{kind}:{_slugify(title, 80)}"


def _task_id_for(fingerprint: str) -> str:
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:8]
    slug = _slugify(fingerprint, 52)
    return f"p0-incident-{slug}-{digest}"


def _slugify(text: str, max_len: int = 80) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:max_len] or "alert").rstrip("-")


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


@contextmanager
def _state_file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _tmp_path_for(path: Path) -> Path:
    return path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")


def _load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "incidents": {}}
    return data if isinstance(data, dict) else {"version": 1, "incidents": {}}


def _rotate_ledger(path: Path, *, max_bytes: int = 8_000_000) -> None:
    """Rotate the P0 incident ledger past max_bytes (keep one prior generation as .1).
    Best-effort; a rotation failure must never block intake."""
    try:
        if path.exists() and path.stat().st_size >= max_bytes:
            path.replace(path.with_name(path.name + ".1"))
    except OSError:
        log.warning("p0 incident ledger rotation failed (continuing): %s", path)


def _store_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path_for(path)
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _find_task(task_root: Path, task_id: str) -> _TaskMatch | None:
    for subdir in ("active", "closed"):
        root = task_root / subdir
        for path in sorted(root.glob(f"{task_id}*.md")):
            return _TaskMatch(path=path, closed=subdir == "closed")
    return None


def _available_recurrence_task_id(task_root: Path, base_task_id: str, recurrence_count: int) -> str:
    candidate_count = recurrence_count
    while True:
        candidate = f"{base_task_id}-r{candidate_count}"
        if _find_task(task_root, candidate) is None:
            return candidate
        candidate_count += 1


def _write_new_task(
    path: Path,
    record: dict[str, Any],
    *,
    title: str,
    message: str,
    now: datetime,
    ledger_path: Path,
    state_path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = _render_task(
        record,
        title=title,
        message=message,
        now=now,
        ledger_path=ledger_path,
        state_path=state_path,
    )
    tmp = _tmp_path_for(path)
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _update_existing_task(
    path: Path, record: dict[str, Any], *, title: str, message: str, now: datetime
) -> None:
    text = path.read_text(encoding="utf-8")
    text = _set_frontmatter_scalar(text, "updated_at", _iso(now))
    text = _set_frontmatter_scalar(text, "last_incident_at", _iso(now))
    text = _set_frontmatter_scalar(text, "incident_count", str(record["count"]))
    text = _set_frontmatter_scalar(text, "last_incident_fingerprint", record["fingerprint"])
    latest_block = _render_latest_alert(record, title=title, message=message)
    text = _replace_latest_alert(text, latest_block)
    log_line = (
        f"- {_iso(now)} p0-incident-intake updated from `{_clip(title, 96)}` "
        f"(count={record['count']})."
    )
    if "## Session Log\n" in text:
        text = text.replace("## Session Log\n", f"## Session Log\n{log_line}\n", 1)
    else:
        text = text.rstrip() + f"\n\n## Session Log\n{log_line}\n"
    tmp = _tmp_path_for(path)
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _set_frontmatter_scalar(text: str, key: str, value: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 4)
    if end < 0:
        return text
    front = text[: end + 1]
    body = text[end + 1 :]
    line = f"{key}: {value}"
    if re.search(rf"(?m)^{re.escape(key)}\s*:", front):
        front = re.sub(rf"(?m)^{re.escape(key)}\s*:.*$", line, front)
    else:
        front = front.rstrip("\n") + f"\n{line}\n"
    return front + body


def _quote_yaml(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _render_task(
    record: dict[str, Any],
    *,
    title: str,
    message: str,
    now: datetime,
    ledger_path: Path,
    state_path: Path,
) -> str:
    now_s = _iso(now)
    task_id = record["task_id"]
    task_title = f"P0 incident: {_clip(title, 90)}"
    latest_alert = _render_latest_alert(record, title=title, message=message)
    prior_context = _render_prior_incident_context(record)
    recurrence_of_task_id = record.get("recurrence_of_task_id")
    recurrence_of_task_path = record.get("recurrence_of_task_path")
    return f"""---
type: cc-task
task_id: {task_id}
title: {_quote_yaml(task_title)}
status: offered
assigned_to: unassigned
priority: p0
wsjf: 32
effort_class: small
mutation_surface: source
quality_floor: frontier_review_required
authority_level: support_non_authoritative
route_metadata_schema: 1
route_metadata:
  route_metadata_schema: 1
  quality_floor: frontier_review_required
  authority_level: support_non_authoritative
  mutation_surface: source
  risk_flags:
    governance_sensitive: true
    privacy_or_secret_sensitive: false
    public_claim_sensitive: false
  context_shape:
    codebase_locality: cross_module
    vault_context_required: true
  verification_surface:
    deterministic_tests: [pytest]
    static_checks: [ruff]
    runtime_observation: true
  route_constraints:
    preferred_platforms: [codex]
    allowed_platforms: [codex, claude]
    prohibited_platforms: []
  review_requirement:
    support_artifact_allowed: true
    independent_review_required: true
    authoritative_acceptor_profile: frontier_full
kind: recovery_triage
risk_tier: T1
depends_on: []
blocks: []
branch: null
pr: null
created_at: {now_s}
claimed_at: null
completed_at: null
updated_at: {now_s}
parent_request: {DEFAULT_PARENT_REQUEST}
parent_spec: {DEFAULT_PARENT_SPEC}
authority_case: {DEFAULT_AUTHORITY_CASE}
exit_predicate: "Root cause identified, remediation applied or explicitly refused, source/runtime fix verified, and the alert no longer recurs through the P0 incident-intake ledger."
tags: [cc-task, p0, incident-intake, technical-alert, auto-minted]
stage: S6_IMPLEMENTATION
implementation_authorized: true
implementation_authorized_by: "P0 technical alert intake auto-mint under operator directive 2026-06-12"
source_mutation_authorized: true
docs_mutation_authorized: true
runtime_mutation_authorized: true
mutation_scope_refs:
  - shared/
  - scripts/
  - systemd/units/
  - tests/
incident_fingerprint: {record["fingerprint"]}
incident_kind: {record["kind"]}
incident_count: {record["count"]}
incident_recurrence_count: {record.get("recurrence_count", 0)}
base_incident_task_id: {record.get("base_task_id") or task_id}
recurrence_of_task_id: {recurrence_of_task_id or "null"}
recurrence_of_task_path: {_quote_yaml(str(recurrence_of_task_path)) if recurrence_of_task_path else "null"}
first_incident_at: {record["first_seen"]}
last_incident_at: {record["last_seen"]}
last_incident_fingerprint: {record["fingerprint"]}
---

# {task_title}

{latest_alert}
{prior_context}

## Evidence

- Incident ledger: `{ledger_path}`
- Intake state: `{state_path}`
- Original notification source: `shared.p0_incident_intake`

## Required Work

- [ ] Reproduce or inspect the failing predicate/source alert.
- [ ] Identify root cause and classify whether remediation is source, runtime, credential, or operator-only.
- [ ] Apply the smallest safe remediation under this task's declared mutation surface.
- [ ] Re-run the specific predicate that emitted the alert.
- [ ] Verify no duplicate notification storm remains.

## Acceptance criteria

- [ ] Root cause, remediation or explicit refusal, and recurrence-prevention notes are written in `## Post-mortem`.
- [ ] The specific alert predicate has been rechecked and its output is cited in `## Post-mortem`.
- [ ] The P0 incident ledger/state were reviewed after remediation, including prior recurrence context when present.
- [ ] Any follow-up work that remains is linked as a cc-task or explicitly refused with reason.

## Post-mortem

- Root cause:
- Remediation or refusal:
- Verification evidence:
- Recurrence prevention:
- Follow-up tasks:

## Session Log

- {now_s} p0-incident-intake minted this task from technical notification `{_clip(title, 96)}`.
"""


def _render_latest_alert(record: dict[str, Any], *, title: str, message: str) -> str:
    latest = _clip(message, 1800)
    return f"""## Latest Alert

- Title: `{title}`
- Priority: `p0`
- Kind: `{record["kind"]}`
- Fingerprint: `{record["fingerprint"]}`
- Count: {record["count"]}
- First seen: `{record["first_seen"]}`
- Last seen: `{record["last_seen"]}`

```text
{latest}
```
"""


def _replace_latest_alert(text: str, latest_block: str) -> str:
    replacement = f"{latest_block.rstrip()}\n\n## Evidence\n"
    updated, count = LATEST_ALERT_BLOCK_RE.subn(lambda _: replacement, text, count=1)
    if count:
        return updated
    if "## Evidence\n" in text:
        return text.replace("## Evidence\n", replacement, 1)
    return f"{text.rstrip()}\n\n{latest_block.rstrip()}\n"


def _render_prior_incident_context(record: dict[str, Any]) -> str:
    prior_path_s = str(record.get("recurrence_of_task_path") or "").strip()
    prior_task_id = str(record.get("recurrence_of_task_id") or "").strip()
    if not prior_path_s:
        return ""
    prior_path = Path(prior_path_s)
    try:
        prior_text = prior_path.read_text(encoding="utf-8")
    except OSError:
        prior_text = ""
    status = _frontmatter_value(prior_text, "status") or "unknown"
    completed_at = _frontmatter_value(prior_text, "completed_at") or "unknown"
    prior_count = _frontmatter_value(prior_text, "incident_count") or "unknown"
    pr = _frontmatter_value(prior_text, "pr") or "unknown"
    excerpt = _prior_resolution_excerpt(prior_text)
    recurrence_count = record.get("recurrence_count", 1)
    lines = [
        "## Prior Incident Context",
        "",
        f"This alert recurred after prior task `{prior_task_id}` reached `{status}`.",
        "",
        f"- Recurrence number: {recurrence_count}",
        f"- Prior task: `{prior_task_id}`",
        f"- Prior note: `{prior_path}`",
        f"- Prior completed_at: `{completed_at}`",
        f"- Prior PR: `{pr}`",
        f"- Prior incident count: `{prior_count}`",
    ]
    if excerpt:
        lines.extend(
            [
                "",
                "Prior resolution/post-mortem excerpt:",
                "",
                "```text",
                excerpt,
                "```",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Prior resolution/post-mortem excerpt: missing. Treat that as part of this recurrence.",
            ]
        )
    return "\n".join(lines) + "\n\n"


def _frontmatter_value(text: str, key: str) -> str | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    front = text[4:end]
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s*:\s*(.*?)\s*$", front)
    if not match:
        return None
    value = match.group(1).strip().strip('"').strip("'")
    return value if value and value.lower() not in {"null", "none", "~"} else None


def _prior_resolution_excerpt(text: str) -> str:
    for heading in ("Resolution", "Post-mortem"):
        section = _markdown_section(text, heading)
        if section and not _section_is_placeholder(section):
            return _clip(_strip_code_fence_confusion(section), 1200)
    section = _markdown_section(text, "Session Log")
    return _clip(_strip_code_fence_confusion(section), 700) if section else ""


def _markdown_section(text: str, heading: str) -> str:
    match = re.search(rf"(?im)^##[ \t]+{re.escape(heading)}(?:[ \t]+.*)?$", text)
    if match is None:
        return ""
    start = match.end()
    next_heading = re.search(r"(?m)^##\s+", text[start:])
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end].strip()


def _strip_code_fence_confusion(text: str) -> str:
    return text.replace("```", "'''").strip()


def _section_is_placeholder(text: str) -> bool:
    substantive = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line in {"```", "'''"}:
            continue
        if re.fullmatch(
            r"-\s+(Root cause|Remediation or refusal|Verification evidence|Recurrence prevention|Follow-up tasks):",
            line,
        ):
            continue
        substantive.append(line)
    return not substantive
