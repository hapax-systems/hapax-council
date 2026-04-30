#!/usr/bin/env python3
"""Lossless revive/reconcile guard for protected Codex lanes.

This command is intentionally conservative: it records the state needed
for a protected-lane revive, archives stale claim markers instead of
deleting them, and only changes a protected task when the caller has
explicitly confirmed the protected lane is not actively being worked.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

DEFAULT_VAULT_ROOT = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "hapax"
DEFAULT_RELAY_DIR = DEFAULT_CACHE_DIR / "relay"
DEFAULT_DASHBOARD = DEFAULT_VAULT_ROOT / "_dashboard" / "codex-session-health.md"

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---(?=\n|$)", re.DOTALL)
FINAL_AGENT_STATUSES = {"closed", "completed", "done", "failed", "returned"}
STALE_ARCHIVE_PREFIX = "cc-active-task"


@dataclass(frozen=True)
class TaskNote:
    path: Path
    frontmatter: dict[str, Any]
    body: str

    @property
    def task_id(self) -> str | None:
        value = self.frontmatter.get("task_id")
        return str(value) if value else None

    @property
    def status(self) -> str | None:
        value = self.frontmatter.get("status")
        return str(value) if value else None

    @property
    def assigned_to(self) -> str | None:
        value = self.frontmatter.get("assigned_to")
        return str(value) if value else None


@dataclass(frozen=True)
class ReconcileConfig:
    session: str
    vault_root: Path
    cache_dir: Path
    relay_dir: Path
    dashboard_path: Path
    worktree_path: Path | None
    now: datetime
    protected_active: str
    tmux_visible: str
    ack_token: str | None
    dashboard_command: str | None
    audit_path: Path | None
    dry_run: bool


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _archive_timestamp(value: datetime) -> str:
    return _utc_iso(value).replace("-", "").replace(":", "")


def _parse_now(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO timestamp: {raw}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    tmp.replace(path)


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str] | None:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None
    try:
        frontmatter = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(frontmatter, dict):
        return None
    return frontmatter, text[match.end() :]


def _read_task(path: Path) -> TaskNote | None:
    try:
        parsed = _split_frontmatter(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    if parsed is None:
        return None
    frontmatter, body = parsed
    return TaskNote(path=path, frontmatter=frontmatter, body=body)


def _serialize_task(note: TaskNote) -> str:
    frontmatter = yaml.safe_dump(note.frontmatter, sort_keys=False)
    return f"---\n{frontmatter}---{note.body}"


def _write_task(note: TaskNote) -> None:
    tmp = note.path.with_suffix(note.path.suffix + ".tmp")
    tmp.write_text(_serialize_task(note), encoding="utf-8")
    tmp.replace(note.path)


def _find_task_note(vault_root: Path, task_id: str | None) -> TaskNote | None:
    if not task_id:
        return None
    active = vault_root / "active"
    exact = active / f"{task_id}.md"
    candidates = [exact] if exact.exists() else []
    candidates.extend(sorted(active.glob(f"{task_id}-*.md")))
    for candidate in candidates:
        note = _read_task(candidate)
        if note is not None:
            return note
    return None


def _extract_relay_claim(payload: dict[str, Any]) -> str | None:
    claim = payload.get("current_claim")
    if isinstance(claim, str) and claim.strip():
        return claim.strip()
    if isinstance(claim, dict):
        task_id = claim.get("task_id")
        if task_id:
            return str(task_id)
    for key in ("active_claim", "claimed_task", "claim"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict) and value.get("task_id"):
            return str(value["task_id"])
    return None


def _claim_marker_path(cache_dir: Path, session: str) -> Path:
    return cache_dir / f"cc-active-task-{session}"


def _read_claim_marker(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        first = path.read_text(encoding="utf-8").splitlines()[0].strip()
    except (IndexError, OSError):
        return None
    return first or None


def _tmux_visibility(session: str, override: str) -> str:
    if override != "unknown":
        return override
    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", f"hapax-codex-{session}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return "true" if result.returncode == 0 else "false"


def _git_value(args: list[str], *, cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _worktree_state(worktree_path: Path | None) -> dict[str, Any]:
    if worktree_path is None:
        return {"path": None, "exists": False, "branch": None, "head": None, "dirty_count": None}
    path = worktree_path.expanduser()
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "branch": None,
            "head": None,
            "dirty_count": None,
        }
    branch = _git_value(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    head = _git_value(["rev-parse", "HEAD"], cwd=path)
    status = _git_value(["status", "--porcelain"], cwd=path)
    dirty_count = None if status is None else len([line for line in status.splitlines() if line])
    return {
        "path": str(path),
        "exists": True,
        "branch": branch,
        "head": head,
        "dirty_count": dirty_count,
    }


def _dashboard_row(path: Path, session: str) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "row": None}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"path": str(path), "exists": True, "row": None, "read_error": True}
    prefix = f"| {session} |"
    for line in lines:
        if line.startswith(prefix):
            return {"path": str(path), "exists": True, "row": line}
    return {"path": str(path), "exists": True, "row": None}


def _collect_paths(value: Any, *, base: Path | None = None) -> list[Path]:
    paths: list[Path] = []
    if isinstance(value, str) and value.strip():
        raw = os.path.expandvars(value.strip())
        path = Path(raw).expanduser()
        if not path.is_absolute() and base is not None:
            path = base / path
        paths.append(path)
    elif isinstance(value, dict):
        for key in ("path", "file", "artifact", "output", "target"):
            if key in value:
                paths.extend(_collect_paths(value[key], base=base))
        for key, child in value.items():
            if key not in {"path", "file", "artifact", "output", "target"}:
                paths.extend(_collect_paths(child, base=base))
    elif isinstance(value, list | tuple):
        for child in value:
            paths.extend(_collect_paths(child, base=base))
    return paths


def _find_durable_output_values(value: Any) -> list[Any]:
    values: list[Any] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if "durable" in normalized and ("output" in normalized or "artifact" in normalized):
                values.append(child)
            else:
                values.extend(_find_durable_output_values(child))
    elif isinstance(value, list | tuple):
        for child in value:
            values.extend(_find_durable_output_values(child))
    return values


def _path_non_empty(path: Path) -> bool:
    if path.is_file():
        return path.stat().st_size > 0
    if path.is_dir():
        return any(path.iterdir())
    return False


def _durable_outputs(payload: dict[str, Any], *, base: Path | None) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in _find_durable_output_values(payload):
        for path in _collect_paths(value, base=base):
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            exists = path.exists()
            non_empty = exists and _path_non_empty(path)
            outputs.append({"path": key, "exists": exists, "non_empty": non_empty})
    return outputs


def _normalize_agent_status(raw: Any) -> str:
    value = str(raw or "unknown").strip().lower()
    if value in {"complete", "completed", "done", "returned", "success"}:
        return "returned"
    if value in {"closed", "cancelled", "canceled"}:
        return "closed"
    if value in {"fail", "failed", "error"}:
        return "failed"
    if value in {"open", "running", "in_progress", "queued", "active"}:
        return "open"
    return "unknown"


def _collect_agent_records(value: Any) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    if isinstance(value, str):
        records.append({"id": value, "status": "unknown"})
    elif isinstance(value, dict):
        identifier = value.get("id") or value.get("agent_id") or value.get("name") or "unknown"
        records.append(
            {
                "id": str(identifier),
                "status": _normalize_agent_status(value.get("status") or value.get("state")),
            }
        )
    elif isinstance(value, list | tuple):
        for child in value:
            records.extend(_collect_agent_records(child))
    return records


def _research_agents(payload: dict[str, Any]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    if not payload:
        return records
    stack: list[Any] = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).lower().replace("-", "_")
                if "research_agent" in normalized or normalized in {
                    "spawned_agents",
                    "subagents",
                    "agents",
                }:
                    records.extend(_collect_agent_records(child))
                else:
                    stack.append(child)
        elif isinstance(value, list | tuple):
            stack.extend(value)
    unique: dict[str, dict[str, str]] = {}
    for record in records:
        unique[f"{record['id']}:{record['status']}"] = record
    return list(unique.values())


def _coordination_note(now: datetime, session: str, archive_path: Path, task_id: str) -> str:
    return (
        f"- {_utc_iso(now)} {session} revive-reconcile guard archived stale claim marker "
        f"for `{task_id}` to `{archive_path}` before restoring the task to offered."
    )


def _append_session_log(note: TaskNote, line: str) -> TaskNote:
    body = note.body
    if "## Session log\n" in body:
        body = body.replace("## Session log\n", f"## Session log\n{line}\n", 1)
    else:
        separator = "" if body.endswith("\n") else "\n"
        body = f"{body}{separator}\n## Session log\n{line}\n"
    return TaskNote(path=note.path, frontmatter=note.frontmatter, body=body)


def _restore_task_to_offered(note: TaskNote, now: datetime) -> TaskNote:
    frontmatter = dict(note.frontmatter)
    frontmatter["status"] = "offered"
    frontmatter["assigned_to"] = "unassigned"
    frontmatter["claimed_at"] = None
    frontmatter["updated_at"] = _utc_iso(now)
    return TaskNote(path=note.path, frontmatter=frontmatter, body=note.body)


def _unique_archive_path(cache_dir: Path, session: str, now: datetime) -> Path:
    archive_dir = cache_dir / "stale-claims"
    stem = f"{STALE_ARCHIVE_PREFIX}-{session}.stale-{_archive_timestamp(now)}"
    candidate = archive_dir / stem
    index = 1
    while candidate.exists():
        candidate = archive_dir / f"{stem}.{index}"
        index += 1
    return candidate


def _archive_claim_marker(source: Path, archive_path: Path, *, dry_run: bool) -> str:
    if dry_run:
        return str(archive_path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(archive_path))
    return str(archive_path)


def _run_dashboard_command(command: str | None) -> dict[str, Any]:
    if not command:
        return {"requested": False, "ran": False, "returncode": None}
    try:
        result = subprocess.run(
            shlex.split(command),
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"requested": True, "ran": False, "returncode": None, "error": str(exc)}
    return {
        "requested": True,
        "ran": True,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def _relay_checkpoint(
    *,
    config: ReconcileConfig,
    resolution: str,
    archive_path: str | None,
    next_safe_action: str,
    warnings: list[str],
    observations: dict[str, Any],
    durable_outputs: list[dict[str, Any]],
    research_agents: list[dict[str, str]],
    dashboard: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "recorded_at": _utc_iso(config.now),
        "ack_token": config.ack_token,
        "session": config.session,
        "resolution": resolution,
        "archive_path": archive_path,
        "audit_path": str(config.audit_path) if config.audit_path else None,
        "next_safe_action": next_safe_action,
        "warnings": warnings,
        "observations": observations,
        "durable_outputs": durable_outputs,
        "research_agents": research_agents,
        "dashboard": dashboard,
        "dry_run": config.dry_run,
    }


def _write_relay_checkpoint(
    config: ReconcileConfig,
    relay_payload: dict[str, Any],
    checkpoint: dict[str, Any],
) -> None:
    if config.dry_run:
        return
    payload = dict(relay_payload)
    payload.setdefault("session", config.session)
    payload["updated"] = _utc_iso(config.now)
    payload["revive_checkpoint"] = checkpoint
    _write_yaml(config.relay_dir / f"{config.session}.yaml", payload)


def _write_audit(config: ReconcileConfig, result: dict[str, Any]) -> None:
    if config.dry_run or config.audit_path is None:
        return
    config.audit_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.audit_path.with_suffix(config.audit_path.suffix + ".tmp")
    tmp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(config.audit_path)


def reconcile(config: ReconcileConfig) -> dict[str, Any]:
    relay_path = config.relay_dir / f"{config.session}.yaml"
    relay_payload = _read_yaml(relay_path)
    relay_claim = _extract_relay_claim(relay_payload)
    claim_path = _claim_marker_path(config.cache_dir, config.session)
    claim_marker_existed_before = claim_path.exists()
    marker_claim = _read_claim_marker(claim_path)
    task_note = _find_task_note(config.vault_root, marker_claim or relay_claim)
    worktree = _worktree_state(config.worktree_path)
    tmux_visible = _tmux_visibility(config.session, config.tmux_visible)
    before_dashboard = _dashboard_row(config.dashboard_path, config.session)
    outputs = _durable_outputs(relay_payload, base=config.worktree_path)
    research = _research_agents(relay_payload)

    warnings: list[str] = []
    degraded_reasons: list[str] = []
    archive_path: str | None = None
    resolution = "no_action"
    next_safe_action = "no cleanup required"

    missing_outputs = [item for item in outputs if not item["exists"] or not item["non_empty"]]
    if missing_outputs:
        degraded_reasons.append("durable_output_missing_or_empty")
        warnings.append("durable_output_missing_or_empty")

    live_agents = [item for item in research if item["status"] not in FINAL_AGENT_STATUSES]
    if live_agents:
        warnings.append("research_agent_open_or_unknown")

    if marker_claim and relay_claim == marker_claim:
        resolution = "relay_claim_matches_marker"
    elif marker_claim and relay_claim and relay_claim != marker_claim:
        resolution = "conflict_no_cleanup"
        warnings.append("claim_marker_conflicts_with_relay_current_claim")
        next_safe_action = "operator must reconcile conflicting claim sources"
    elif marker_claim and not relay_claim:
        if task_note is None:
            resolution = "marker_without_task_no_cleanup"
            warnings.append("claim_marker_task_note_missing")
            next_safe_action = (
                "recover or inspect the referenced task note before changing claim state"
            )
        elif task_note.assigned_to not in {config.session, None, "unassigned"}:
            resolution = "conflict_no_cleanup"
            warnings.append("task_claimed_by_other_lane")
            next_safe_action = "do not clean up; coordinate with the owning live lane"
        elif task_note.status != "claimed":
            resolution = "not_stale_claim_state_no_cleanup"
            warnings.append(f"task_status_{task_note.status or 'unknown'}_not_claimed")
            next_safe_action = "inspect task status before changing claim state"
        elif config.protected_active != "false":
            resolution = "inactive_confirmation_required"
            warnings.append("protected_lane_activity_not_confirmed_false")
            next_safe_action = (
                "confirm protected lane is inactive or rerun with --protected-active false"
            )
        else:
            archive = _unique_archive_path(config.cache_dir, config.session, config.now)
            note_line = _coordination_note(config.now, config.session, archive, marker_claim)
            if not config.dry_run:
                noted = _append_session_log(task_note, note_line)
                _write_task(noted)
                reread = _read_task(task_note.path) or noted
                restored = _restore_task_to_offered(reread, config.now)
                _write_task(restored)
            archive_path = _archive_claim_marker(claim_path, archive, dry_run=config.dry_run)
            resolution = "stale_claim_archived_task_restored"
            next_safe_action = "regenerate dashboard and offer the task for a fresh claim"
    elif not marker_claim and relay_claim:
        resolution = "relay_claim_without_marker"
        warnings.append("relay_current_claim_without_marker")
        next_safe_action = "inspect claim marker loss before mutating task state"

    dashboard_run = (
        _run_dashboard_command(config.dashboard_command)
        if resolution == "stale_claim_archived_task_restored"
        else {"requested": False, "ran": False, "returncode": None}
    )
    after_dashboard = _dashboard_row(config.dashboard_path, config.session)
    dashboard = {
        "before": before_dashboard,
        "regeneration": dashboard_run,
        "after": after_dashboard,
    }
    observations = {
        "relay_path": str(relay_path),
        "relay_exists": relay_path.exists(),
        "relay_current_claim": relay_claim,
        "claim_marker_path": str(claim_path),
        "claim_marker_existed_before": claim_marker_existed_before,
        "claim_marker_exists_after": claim_path.exists(),
        "claim_marker_task": marker_claim,
        "task_path": str(task_note.path) if task_note else None,
        "task_status": task_note.status if task_note else None,
        "task_assigned_to": task_note.assigned_to if task_note else None,
        "tmux_visible": tmux_visible,
        "protected_active": config.protected_active,
        "worktree": worktree,
    }
    checkpoint = _relay_checkpoint(
        config=config,
        resolution=resolution,
        archive_path=archive_path,
        next_safe_action=next_safe_action,
        warnings=warnings,
        observations=observations,
        durable_outputs=outputs,
        research_agents=research,
        dashboard=dashboard,
    )
    _write_relay_checkpoint(config, relay_payload, checkpoint)

    state = "degraded" if degraded_reasons else "ok"
    if resolution in {"conflict_no_cleanup", "inactive_confirmation_required"}:
        state = "blocked"
    result = {
        "state": state,
        "resolution": resolution,
        "warnings": warnings,
        "degraded_reasons": degraded_reasons,
        "archive_path": archive_path,
        "audit_path": str(config.audit_path) if config.audit_path else None,
        "next_safe_action": next_safe_action,
        "observations": observations,
        "durable_outputs": outputs,
        "research_agents": research,
        "dashboard": dashboard,
    }
    _write_audit(config, result)
    return result


def _default_worktree(session: str) -> Path:
    return Path.home() / "projects" / f"hapax-council--{session}"


def _default_audit_path(cache_dir: Path, session: str, now: datetime) -> Path:
    return cache_dir / "revive-checkpoints" / f"{session}-{_archive_timestamp(now)}.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, help="Codex lane, for example cx-violet")
    parser.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--relay-dir", type=Path, default=DEFAULT_RELAY_DIR)
    parser.add_argument("--dashboard", type=Path, default=DEFAULT_DASHBOARD)
    parser.add_argument("--worktree-path", type=Path)
    parser.add_argument("--now", help="override current UTC timestamp for fixtures")
    parser.add_argument(
        "--protected-active",
        choices=("true", "false", "unknown"),
        default="unknown",
        help="explicit operator/lane activity observation; false is required for stale cleanup",
    )
    parser.add_argument(
        "--tmux-visible",
        choices=("true", "false", "unknown"),
        default="unknown",
        help="override tmux visibility observation for fixtures",
    )
    parser.add_argument("--ack-token", help="ACK token to record in relay revive_checkpoint")
    parser.add_argument(
        "--dashboard-command",
        help="command to run after a stale marker archive, e.g. scripts/hapax-codex-health --write-obsidian",
    )
    parser.add_argument(
        "--audit-path",
        type=Path,
        help="write compact reconcile audit JSON here; defaults under cache revive-checkpoints",
    )
    parser.add_argument("--dry-run", action="store_true", help="observe and report without writing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    worktree = (
        args.worktree_path if args.worktree_path is not None else _default_worktree(args.session)
    )
    now = _parse_now(args.now)
    cache_dir = args.cache_dir.expanduser()
    audit_path = (
        args.audit_path.expanduser()
        if args.audit_path
        else _default_audit_path(cache_dir, args.session, now)
    )
    config = ReconcileConfig(
        session=args.session,
        vault_root=args.vault_root.expanduser(),
        cache_dir=cache_dir,
        relay_dir=args.relay_dir.expanduser(),
        dashboard_path=args.dashboard.expanduser(),
        worktree_path=worktree.expanduser() if worktree is not None else None,
        now=now,
        protected_active=args.protected_active,
        tmux_visible=args.tmux_visible,
        ack_token=args.ack_token,
        dashboard_command=args.dashboard_command,
        audit_path=audit_path,
        dry_run=args.dry_run,
    )
    result = reconcile(config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result["state"] == "blocked" else 1 if result["state"] == "degraded" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
