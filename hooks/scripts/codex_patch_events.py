#!/usr/bin/env python3
"""Convert a Codex patch hook payload into Claude-style edit events."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from typing import Any


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        preferred = ("patch", "input", "diff", "content", "command", "cmd")
        for key in preferred:
            if key in value:
                yield from _strings(value[key])
        for key, nested in value.items():
            if key not in preferred:
                yield from _strings(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _extract_patch(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input", payload)
    candidates = list(_strings(tool_input))
    for text in candidates:
        if "*** Begin Patch" in text or "diff --git" in text:
            return text
    return candidates[0] if candidates else ""


def _strip_diff_path(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("a/") or raw.startswith("b/"):
        return raw[2:]
    return raw


def _parse_patch(patch: str) -> list[tuple[str, str, str]]:
    events: list[tuple[str, str, str]] = []
    current_path = ""
    operation = "update"
    additions: list[str] = []

    def flush() -> None:
        nonlocal current_path, additions, operation
        if not current_path:
            return
        content = "\n".join(additions)
        if additions and not content.endswith("\n"):
            content += "\n"
        events.append((operation, current_path, content))
        current_path = ""
        operation = "update"
        additions = []

    for line in patch.splitlines():
        if line.startswith("*** Add File: "):
            flush()
            current_path = line.removeprefix("*** Add File: ").strip()
            operation = "add"
            continue
        if line.startswith("*** Update File: "):
            flush()
            current_path = line.removeprefix("*** Update File: ").strip()
            operation = "update"
            continue
        if line.startswith("*** Delete File: "):
            flush()
            path = line.removeprefix("*** Delete File: ").strip()
            if path:
                events.append(("delete", path, ""))
            continue
        if line.startswith("*** Move to: "):
            current_path = line.removeprefix("*** Move to: ").strip()
            operation = "update"
            continue
        if line.startswith("+++ "):
            path = _strip_diff_path(line.removeprefix("+++ ").strip())
            if path != "/dev/null":
                flush()
                current_path = path
                operation = "update"
            continue
        if current_path and line.startswith("+") and not line.startswith("+++"):
            additions.append(line[1:])

    flush()
    return events


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {"tool_input": {"patch": raw}}

    patch = _extract_patch(payload)
    for operation, path, content in _parse_patch(patch):
        tool_name = "Write" if operation == "add" else "Edit"
        event = {
            "hook_event_name": payload.get("hook_event_name", "PreToolUse"),
            "session_id": payload.get("session_id", ""),
            "cwd": payload.get("cwd", ""),
            "tool_name": tool_name,
            "tool_input": {
                "file_path": path,
                "path": path,
                "content": content,
                "new_string": content,
                "operation": operation,
            },
        }
        print(json.dumps(event, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
