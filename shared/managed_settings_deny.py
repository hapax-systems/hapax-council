"""Managed-settings deny list: deny-only, add-only.

Claude Code managed settings (``/etc/claude-code/managed-settings.d/``) cannot be overridden by
user, project or session settings, and a denied tool is removed from the session entirely. The
deny list is kept in this repository, which the restricted sessions can themselves edit. So the
code that installs it is deliberately narrow:

- it accepts **only** ``{"permissions": {"deny": [...]}}`` with MCP tool or server names; allow
  rules, ask rules, permission modes and any other key are refused;
- it only **adds** to what is installed: an entry missing from the repository file is kept and
  reported as a removal request, never removed. Removing a deny entry widens what sessions can
  do, so it is a deliberate root act outside this code.

A refused candidate writes nothing, so failure narrows. This module is pure; the installer that
runs as root calls ``plan`` and writes ``write_text`` when it is not ``None``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

_ENTRY = re.compile(r"^mcp__[A-Za-z0-9_.-]+(?:__[A-Za-z0-9_.-]+)?$")


@dataclass(frozen=True)
class Plan:
    write_text: str | None
    errors: list[str] = field(default_factory=list)
    removal_requests: list[str] = field(default_factory=list)


def validate(data: Any) -> list[str]:
    """Errors for anything other than a deny list of MCP tool or server names."""
    if not isinstance(data, Mapping) or set(data) != {"permissions"}:
        return ["top level must be exactly {'permissions': ...}"]
    permissions = data["permissions"]
    if not isinstance(permissions, Mapping) or set(permissions) != {"deny"}:
        return ["permissions must contain exactly one key, 'deny' (no allow, ask or mode keys)"]
    deny = permissions["deny"]
    if not isinstance(deny, list):
        return ["permissions.deny must be a list"]
    return [
        f"not an MCP tool or server name: {entry!r}"
        for entry in deny
        if not isinstance(entry, str) or not _ENTRY.match(entry)
    ]


def merge_monotonic(installed: Iterable[str], candidate: Iterable[str]) -> list[str]:
    """The sorted union: every installed entry is kept, new candidate entries are added."""
    return sorted(set(installed) | set(candidate))


def render(deny: Iterable[str]) -> str:
    """Deterministic file content for a deny list."""
    return json.dumps({"permissions": {"deny": sorted(set(deny))}}, indent=2) + "\n"


def _parse(text: str, label: str) -> tuple[list[str] | None, list[str]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, [f"{label}: not valid JSON ({exc.msg})"]
    errors = validate(data)
    if errors:
        return None, [f"{label}: {e}" for e in errors]
    return list(data["permissions"]["deny"]), []


def plan(installed_text: str | None, candidate_text: str) -> Plan:
    """What the installer should write, given the installed file (if any) and the repository's."""
    candidate, errors = _parse(candidate_text, "candidate")
    if candidate is None:
        return Plan(None, errors)
    if installed_text is None:
        return Plan(render(candidate))
    installed, errors = _parse(installed_text, "installed")
    if installed is None:
        return Plan(None, errors)
    merged = merge_monotonic(installed, candidate)
    removals = sorted(set(installed) - set(candidate))
    new_text = render(merged)
    return Plan(None if new_text == render(installed) else new_text, [], removals)
