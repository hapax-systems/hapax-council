#!/usr/bin/env python3
"""Validate and route unclaimed governance-intake bootstrap writes.

This helper is intentionally narrow. Direct editor writes are denied after
validation; the reported remediation performs creation under the stable
ownership transaction.

Keep this dependency-light: hooks run under the system Python before repo
PYTHONPATH or the project venv is guaranteed, so importing shared.frontmatter
would make a safety gate depend on optional runtime packaging.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from task_frontmatter_stdlib import (
    DuplicateKeyError,
    FrontmatterSubsetError,
    parse_frontmatter_document,
    scalar_text,
    string_list,
)

NOT_CANDIDATE = 10
BLOCKED = 12

NULLISH = {"", "null", "none", "~", "[]"}


def _split_frontmatter(content: str) -> tuple[dict[str, Any], set[str], str, list[str]]:
    try:
        parsed = parse_frontmatter_document(content)
    except (DuplicateKeyError, FrontmatterSubsetError, UnicodeDecodeError) as exc:
        return {}, set(), "", [f"strict YAML validation failed: {exc}"]
    return parsed.fields, set(parsed.fields), parsed.body, []


def _as_scalar(fields: dict[str, Any], key: str) -> str:
    return scalar_text(fields.get(key)).strip()


def _as_list(fields: dict[str, Any], key: str) -> list[str]:
    return string_list(fields.get(key))


def _is_nullish(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, list):
        return len(value) == 0
    return str(value).strip().lower() in NULLISH


def _require_scalar(fields: dict[str, Any], key: str, errors: list[str]) -> None:
    if _is_nullish(fields.get(key)) or not _as_scalar(fields, key):
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
    if request_id and path.stem != request_id:
        errors.append("request filename must be exactly `<request_id>.md`")

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
    if task_id and path.stem != task_id:
        errors.append("cc-task filename must be exactly `<task_id>.md`")

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


def validate_bootstrap_candidate(
    target: Path,
    content: str,
    kind: str,
) -> tuple[str, list[str]]:
    """Return the canonical identifier and every validation error."""

    fields, present, body, errors = _split_frontmatter(content)
    if errors:
        return target.stem, errors
    if kind == "request":
        errors.extend(_validate_request(target, fields, present))
        identifier = _as_scalar(fields, "request_id") or target.stem
    elif kind == "cc-task":
        errors.extend(_validate_task(target, fields, present, body))
        identifier = _as_scalar(fields, "task_id") or target.stem
    else:
        return target.stem, [f"unsupported bootstrap kind: {kind}"]
    return identifier, errors


def _role_for_ledger() -> str:
    for key in ("HAPAX_AGENT_ROLE", "CODEX_ROLE", "CLAUDE_ROLE", "HAPAX_AGENT_NAME"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return "unknown"


def write_bootstrap_ledger(kind: str, path: Path, identifier: str) -> None:
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

    identifier, errors = validate_bootstrap_candidate(target, content, kind)

    if errors:
        return _block(str(target), errors)

    return _block(
        "direct Write cannot serialize a governance identity",
        [
            f"validated {kind} identity: {identifier}",
            "write a JSON payload under /tmp/hapax-* and run "
            "`scripts/cc-governance-intake-create --payload <path>`",
        ],
    )


if __name__ == "__main__":
    raise SystemExit(main())
