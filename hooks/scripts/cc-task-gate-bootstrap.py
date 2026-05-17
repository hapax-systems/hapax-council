#!/usr/bin/env python3
"""Validate unclaimed cc-task gate intake bootstrap writes.

This helper is intentionally narrow. It lets a session create the governance
object that makes ordinary work claimable, but only as a new request or offered
cc-task note in the Obsidian governance vault.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NOT_CANDIDATE = 10
BLOCKED = 12

NULLISH = {"", "null", "none", "~", "[]"}


def _strip_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1].strip()
    return value


def _parse_inline_list(value: str) -> list[str]:
    value = value.strip()
    if value == "[]":
        return []
    if not (value.startswith("[") and value.endswith("]")):
        scalar = _strip_scalar(value)
        return [scalar] if scalar else []
    inner = value[1:-1].strip()
    if not inner:
        return []
    return [_strip_scalar(item) for item in inner.split(",") if _strip_scalar(item)]


def _split_frontmatter(content: str) -> tuple[dict[str, Any], set[str], str, list[str]]:
    errors: list[str] = []
    if not content.startswith("---\n"):
        return {}, set(), "", ["note must start with YAML frontmatter"]
    end = content.find("\n---", 4)
    if end < 0:
        return {}, set(), "", ["note frontmatter must close with ---"]

    frontmatter = content[4:end]
    body = content[end + 4 :]
    fields: dict[str, Any] = {}
    present: set[str] = set()
    lines = frontmatter.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        idx += 1
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        present.add(key)
        if value:
            if value.startswith("[") and value.endswith("]"):
                fields[key] = _parse_inline_list(value)
            else:
                fields[key] = _strip_scalar(value)
            continue

        items: list[str] = []
        while idx < len(lines):
            child = lines[idx].strip()
            if not child:
                idx += 1
                continue
            if child.startswith("- "):
                item = _strip_scalar(child[2:])
                if item:
                    items.append(item)
                idx += 1
                continue
            break
        fields[key] = items

    return fields, present, body, errors


def _as_scalar(fields: dict[str, Any], key: str) -> str:
    value = fields.get(key, "")
    if isinstance(value, list):
        return ""
    return str(value).strip()


def _as_list(fields: dict[str, Any], key: str) -> list[str]:
    value = fields.get(key, [])
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text or text.lower() in NULLISH:
        return []
    return _parse_inline_list(text)


def _is_nullish(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, list):
        return len(value) == 0
    return str(value).strip().lower() in NULLISH


def _require_scalar(fields: dict[str, Any], key: str, errors: list[str]) -> None:
    if _is_nullish(fields.get(key)):
        errors.append(f"missing non-empty `{key}`")


def _require_present(fields_present: set[str], key: str, errors: list[str]) -> None:
    if key not in fields_present:
        errors.append(f"missing `{key}`")


def _validate_request(path: Path, fields: dict[str, Any], present: set[str]) -> list[str]:
    errors: list[str] = []
    if _as_scalar(fields, "type") != "hapax-request":
        errors.append("request note must declare `type: hapax-request`")
    for key in (
        "request_id",
        "title",
        "status",
        "requester",
        "created_at",
        "updated_at",
        "authority_requested",
        "risk_guess",
        "requires_research",
    ):
        _require_scalar(fields, key, errors)
    for key in ("surfaces", "principle_flags", "tags"):
        _require_present(present, key, errors)
        if not _as_list(fields, key):
            errors.append(f"`{key}` must contain at least one item")

    request_id = _as_scalar(fields, "request_id")
    if request_id and not request_id.startswith("REQ-"):
        errors.append("`request_id` must start with REQ-")
    if request_id and not path.name.startswith(request_id):
        errors.append("request filename must start with `request_id`")

    status = _as_scalar(fields, "status")
    if status not in {"captured", "accepted_for_planning"}:
        errors.append("request `status` must be captured or accepted_for_planning")
    if status == "accepted_for_planning":
        _require_scalar(fields, "planning_case", errors)

    return errors


def _validate_task(path: Path, fields: dict[str, Any], present: set[str], body: str) -> list[str]:
    errors: list[str] = []
    if _as_scalar(fields, "type") != "cc-task":
        errors.append("cc-task note must declare `type: cc-task`")
    for key in (
        "task_id",
        "title",
        "priority",
        "wsjf",
        "status",
        "assigned_to",
        "parent_spec",
        "authority_case",
        "quality_floor",
        "mutation_surface",
        "authority_level",
        "route_metadata_schema",
    ):
        _require_scalar(fields, key, errors)
    for key in ("depends_on", "blocks", "tags", "mutation_scope_refs"):
        _require_present(present, key, errors)
    for key in ("tags", "mutation_scope_refs"):
        if not _as_list(fields, key):
            errors.append(f"`{key}` must contain at least one item")
    for key in ("branch", "pr", "claimed_at", "completed_at"):
        _require_present(present, key, errors)

    task_id = _as_scalar(fields, "task_id")
    if task_id and not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", task_id):
        errors.append("`task_id` contains unsupported characters")
    if task_id and not (path.stem == task_id or path.stem.startswith(f"{task_id}-")):
        errors.append("cc-task filename must match `task_id` or start with `task_id-`")

    if _as_scalar(fields, "status") != "offered":
        errors.append("new cc-task bootstrap notes must use `status: offered`")
    if _as_scalar(fields, "assigned_to") != "unassigned":
        errors.append("new cc-task bootstrap notes must use `assigned_to: unassigned`")

    authority_case = _as_scalar(fields, "authority_case")
    if authority_case and not re.match(r"^CASE-[A-Z0-9-]+$", authority_case):
        errors.append("`authority_case` must be a CASE-* identifier")

    for key in ("branch", "pr", "claimed_at", "completed_at"):
        if key in present and not _is_nullish(fields.get(key)):
            errors.append(f"`{key}` must be null for a new offered task")

    try:
        if float(_as_scalar(fields, "wsjf")) < 0:
            errors.append("`wsjf` must be non-negative")
    except ValueError:
        errors.append("`wsjf` must be numeric")

    route_schema = _as_scalar(fields, "route_metadata_schema")
    if route_schema and route_schema != "1":
        errors.append("`route_metadata_schema` must be 1")

    if "## Session log" not in body:
        errors.append("cc-task body must include `## Session log`")

    return errors


def _role_for_ledger() -> str:
    for key in ("HAPAX_AGENT_ROLE", "CODEX_ROLE", "CLAUDE_ROLE", "HAPAX_AGENT_NAME"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return "unknown"


def _write_ledger(kind: str, path: Path, identifier: str) -> None:
    ledger = Path(
        os.environ.get(
            "HAPAX_CC_TASK_GATE_BOOTSTRAP_LEDGER",
            str(Path.home() / ".cache" / "hapax" / "cc-task-gate-bootstrap-ledger.jsonl"),
        )
    ).expanduser()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "role": _role_for_ledger(),
        "tool": "Write",
        "kind": kind,
        "id": identifier,
        "path": str(path),
        "reason": "unclaimed_governance_intake_bootstrap",
    }
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _block(message: str, details: list[str] | None = None) -> int:
    print(
        f"cc-task-gate: BLOCKED — invalid unclaimed governance bootstrap: {message}",
        file=sys.stderr,
    )
    for detail in details or []:
        print(f"  - {detail}", file=sys.stderr)
    return BLOCKED


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return NOT_CANDIDATE

    if payload.get("tool_name") != "Write":
        return NOT_CANDIDATE
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return NOT_CANDIDATE
    raw_path = str(
        tool_input.get("file_path")
        or tool_input.get("path")
        or tool_input.get("notebook_path")
        or ""
    ).strip()
    if not raw_path:
        return NOT_CANDIDATE
    content = tool_input.get("content")

    home = Path.home()
    request_root = (
        home / "Documents" / "Personal" / "20-projects" / "hapax-requests" / "active"
    ).resolve(strict=False)
    task_root = (
        home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    ).resolve(strict=False)
    target = Path(raw_path).expanduser().resolve(strict=False)

    kind: str | None = None
    try:
        if (
            target.suffix == ".md"
            and target.is_relative_to(request_root)
            and target != request_root
        ):
            kind = "request"
        elif target.suffix == ".md" and target.is_relative_to(task_root) and target != task_root:
            kind = "cc-task"
    except ValueError:
        return NOT_CANDIDATE

    if kind is None:
        return NOT_CANDIDATE
    if target.exists():
        return _block("target note already exists", [str(target)])
    if not isinstance(content, str) or not content.strip():
        return _block("Write content is missing or empty", [str(target)])

    fields, present, body, errors = _split_frontmatter(content)
    if not errors:
        if kind == "request":
            errors.extend(_validate_request(target, fields, present))
            identifier = _as_scalar(fields, "request_id") or target.stem
        else:
            errors.extend(_validate_task(target, fields, present, body))
            identifier = _as_scalar(fields, "task_id") or target.stem

    if errors:
        return _block(str(target), errors)

    try:
        _write_ledger(kind, target, identifier)
    except OSError as exc:
        return _block("could not write bootstrap ledger", [str(exc)])

    print(f"cc-task-gate: intake bootstrap allowed — {kind} {identifier} logged", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
