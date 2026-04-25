"""Monetization whitelist — operator-curated narrow-Ring-2 allowlist.

YAML-backed allowlist of capability names + rendered-payload patterns
that the operator has explicitly judged safe. Loaded on
``MonetizationRiskGate`` startup and reloaded on SIGHUP.

**Invariant** (tested in ``tests/monetization_review/test_whitelist.py``):
the whitelist NARROWS Ring 2 only — it can override a Ring-2-derived
block, but it CANNOT override a Ring-1 ``risk == "high"`` catalog
declaration. Ring 1 high stays unconditional.

YAML schema::

    exact:
      - "verbatim phrase the operator approved"
    regex:
      - pattern: "^safe \\\\d+$"
        note: "operator approved 2026-04-25"
    capabilities:
      - knowledge.web_search   # capability-name allowlist (Ring 2 only)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import yaml

log = logging.getLogger(__name__)

DEFAULT_WHITELIST_PATH: Final[Path] = Path.home() / "hapax-state" / "monetization-whitelist.yaml"

EMPTY_WHITELIST_TEMPLATE: Final[str] = """\
# Monetization whitelist — narrows Ring 2 only.
# NEVER bypasses Ring 1 high-risk catalog declarations.
# See agents/monetization_review/whitelist.py for schema.

exact: []
regex: []
capabilities: []
"""


@dataclass(frozen=True)
class WhitelistEntry:
    """One operator-approved pattern with origin metadata."""

    kind: str  # "exact" | "regex" | "capability"
    value: str
    note: str = ""


@dataclass
class Whitelist:
    """In-memory representation of the YAML allowlist.

    Stateless from the gate's perspective — the gate calls
    ``matches_payload`` / ``matches_capability`` per assess and gets
    bool back. SIGHUP-driven reload constructs a new instance via
    ``Whitelist.load`` and atomically swaps the gate's reference.
    """

    exact: tuple[str, ...] = ()
    regex: tuple[tuple[re.Pattern[str], str], ...] = ()
    capabilities: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def empty(cls) -> Whitelist:
        return cls()

    @classmethod
    def load(cls, path: Path | None = None) -> Whitelist:
        """Load + parse the YAML file. Missing file → empty whitelist.

        Malformed YAML or invalid regex → empty whitelist + WARNING log,
        never raises. The gate's correctness cannot depend on parser
        success — a corrupted whitelist must not block traffic.
        """
        target = path if path is not None else DEFAULT_WHITELIST_PATH
        if not target.exists():
            return cls.empty()
        try:
            raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            log.warning("monetization-whitelist: YAML parse failed at %s", target, exc_info=True)
            return cls.empty()
        if not isinstance(raw, dict):
            log.warning("monetization-whitelist: top-level not a mapping at %s", target)
            return cls.empty()

        exact = tuple(_as_str_list(raw.get("exact")))
        regex = tuple(_compile_regex_entries(raw.get("regex")))
        capabilities = frozenset(_as_str_list(raw.get("capabilities")))
        return cls(exact=exact, regex=regex, capabilities=capabilities)

    def matches_payload(self, payload: Any) -> tuple[bool, str]:
        """True iff a rendered-payload string matches an exact / regex rule.

        Returns (matched, reason). Non-string payloads convert via
        ``str(...)`` so dict / pydantic-model payloads still match on
        their string repr (good enough for operator review; the operator
        can refine the pattern if the repr is wrong).
        """
        text = payload if isinstance(payload, str) else str(payload)
        if text in self.exact:
            return True, f"exact-match whitelist entry ({text!r})"
        for pattern, note in self.regex:
            if pattern.search(text):
                detail = f" ({note})" if note else ""
                return True, f"regex whitelist entry {pattern.pattern!r}{detail}"
        return False, ""

    def matches_capability(self, capability_name: str) -> tuple[bool, str]:
        """True iff the bare capability name is on the operator's allowlist.

        Capability-level allowlist is the broadest stroke: every render
        of that capability passes the Ring 2 narrow regardless of
        rendered text. Use sparingly.
        """
        if capability_name in self.capabilities:
            return True, f"capability whitelist ({capability_name})"
        return False, ""

    def append_exact(self, text: str, *, path: Path | None = None) -> None:
        """Persist an exact-string entry to the YAML file.

        Appends to the existing list (not in-place mutation of self —
        the gate sees the new entry on next SIGHUP). Creates the file
        + parent directory if missing.
        """
        _append_entry(path or DEFAULT_WHITELIST_PATH, "exact", text)

    def append_regex(self, pattern: str, note: str = "", *, path: Path | None = None) -> None:
        """Persist a regex entry. Validates the pattern compiles."""
        re.compile(pattern)  # raises re.error if invalid; caller's responsibility
        _append_entry(
            path or DEFAULT_WHITELIST_PATH,
            "regex",
            {"pattern": pattern, "note": note} if note else {"pattern": pattern},
        )

    def append_capability(self, capability_name: str, *, path: Path | None = None) -> None:
        """Persist a capability-name allowlist entry."""
        _append_entry(path or DEFAULT_WHITELIST_PATH, "capabilities", capability_name)


def _as_str_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if isinstance(x, str | int | float)]


def _compile_regex_entries(raw: Any) -> list[tuple[re.Pattern[str], str]]:
    out: list[tuple[re.Pattern[str], str]] = []
    if not isinstance(raw, list):
        return out
    for entry in raw:
        if isinstance(entry, str):
            try:
                out.append((re.compile(entry), ""))
            except re.error as e:
                log.warning("monetization-whitelist: invalid regex %r — %s", entry, e)
            continue
        if not isinstance(entry, dict):
            continue
        pattern = entry.get("pattern")
        if not isinstance(pattern, str):
            continue
        note = entry.get("note", "")
        try:
            out.append((re.compile(pattern), str(note) if note else ""))
        except re.error as e:
            log.warning("monetization-whitelist: invalid regex %r — %s", pattern, e)
    return out


def _append_entry(path: Path, key: str, value: Any) -> None:
    """Atomically append ``value`` under ``key`` in the YAML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            existing = {}
    else:
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    bucket = existing.get(key)
    if not isinstance(bucket, list):
        bucket = []
    bucket.append(value)
    existing[key] = bucket
    for required in ("exact", "regex", "capabilities"):
        existing.setdefault(required, [])
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(existing, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


__all__ = [
    "DEFAULT_WHITELIST_PATH",
    "EMPTY_WHITELIST_TEMPLATE",
    "Whitelist",
    "WhitelistEntry",
]
