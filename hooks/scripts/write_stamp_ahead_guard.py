#!/usr/bin/env python3
"""write_stamp_ahead_guard -- PreToolUse (Write) refusal for stamps ahead of the clock.

Row `write-stamp-ahead-of-clock-hook-20261004`; the glm-steward dispatch terms
(2026-10-04T23:24:46Z) bind this implementation:

* Refuse when a stamp is more than ``AHEAD_THRESHOLD_SECONDS`` (15) ahead of
  the clock at the moment of the call.
* Two stamp surfaces: the target's basename prefix, in both vault precisions
  ``YYYYMMDDTHHMMZ`` and ``YYYYMMDDTHHMMSSZ`` (strict prefix, UTC/Z), and the
  written content's leading-frontmatter ``created_at``.
* When both parse, the **max** of the two governs.
* Past stamps always pass; this check never refuses on age.
* Fail **open** on anything unparseable, but log the near-miss prefix for
  review so a silent pass is distinguishable from a clean one.
* Refusal is refuse-and-print only: the message carries the current ``date -u``
  and the hook never rewrites or corrects a stamp.
* Write-only and vault-scoped. The Personal-vault root comes from the same knob
  and default as ``hooks/scripts/cc-task-root.sh`` (``PERSONAL_VAULT_PATH``,
  else ``$HOME/Documents/Personal``) -- pinned by a parity test so the two
  cannot drift into a split SSOT.

Wired as a council PreToolUse gate for Write. A filename/``created_at``
disagreement is refused on the max, so an ahead stamp cannot hide behind a
past one.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

AHEAD_THRESHOLD_SECONDS = 15

_SECOND_STAMP_RE = re.compile(r"\d{8}T\d{6}Z")
_MINUTE_STAMP_RE = re.compile(r"\d{8}T\d{4}Z")
_ISO_STAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_FILENAME_NEAR_RE = re.compile(r"(\d{8}T\d{2,6})")
_ISO_NEAR_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
_CREATED_AT_LINE_RE = re.compile(r"^created_at[ \t]*:[ \t]*(.+?)[ \t]*$")

_STAMP_FORMATS = (
    (_SECOND_STAMP_RE, "%Y%m%dT%H%M%SZ"),
    (_MINUTE_STAMP_RE, "%Y%m%dT%H%MZ"),
    (_ISO_STAMP_RE, "%Y-%m-%dT%H:%M:%SZ"),
)

_NEAR_MISS_LOG = (".cache", "hapax", "write-stamp-ahead-near-miss.jsonl")


@dataclass(frozen=True)
class Verdict:
    """The decision for one write, and the stamp that produced it."""

    refuse: bool
    ahead_seconds: int | None = None
    stamp_epoch: int | None = None
    source: str | None = None
    stamp_text: str | None = None


def stamp_epoch(stamp: str) -> int | None:
    """Epoch seconds for one UTC/Z stamp, or None when it is not a known form."""
    if not isinstance(stamp, str):
        return None
    for pattern, fmt in _STAMP_FORMATS:
        if pattern.fullmatch(stamp):
            try:
                parsed = datetime.strptime(stamp, fmt).replace(tzinfo=UTC)
            except ValueError:
                return None
            return int(parsed.timestamp())
    return None


def parse_filename_stamp(basename: str) -> str | None:
    """The stamp that strictly prefixes ``basename``, seconds form first."""
    if not isinstance(basename, str):
        return None
    for pattern in (_SECOND_STAMP_RE, _MINUTE_STAMP_RE):
        match = pattern.match(basename)
        if match is not None:
            return match.group(0)
    return None


def filename_near_miss(basename: str) -> str | None:
    """A stamp-shaped but unparseable basename prefix, for the near-miss log."""
    if parse_filename_stamp(basename) is not None:
        return None
    match = _FILENAME_NEAR_RE.match(basename)
    return match.group(1) if match is not None else None


def _frontmatter_lines(content: str) -> list[str]:
    """The lines of the leading ``---`` frontmatter block, or [] if there is none."""
    if not isinstance(content, str):
        return []
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return lines[1:index]
    return []


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def frontmatter_created_at_raw(content: str) -> str | None:
    """The unvalidated ``created_at`` value from the leading frontmatter block."""
    for line in _frontmatter_lines(content):
        # A top-level key only: a nested `created_at:` under route_metadata is
        # indented and must not be read as the record's own stamp.
        match = _CREATED_AT_LINE_RE.match(line)
        if match is not None:
            return _unquote(match.group(1))
    return None


def frontmatter_created_at(content: str) -> str | None:
    """The frontmatter ``created_at`` when it is a UTC/Z stamp, else None."""
    raw = frontmatter_created_at_raw(content)
    if raw is None or stamp_epoch(raw) is None:
        return None
    return raw


def created_at_near_miss(content: str) -> str | None:
    """A stamp-shaped but unparseable ``created_at``, for the near-miss log."""
    raw = frontmatter_created_at_raw(content)
    if raw is None or stamp_epoch(raw) is not None:
        return None
    return raw if _ISO_NEAR_RE.match(raw) is not None else None


def evaluate(now_epoch: int, filename_stamp: str | None, created_at: str | None) -> Verdict:
    """Refuse when the max of the parseable stamps is more than 15 s ahead."""
    candidates: list[tuple[int, str, str]] = []
    if filename_stamp is not None:
        epoch = stamp_epoch(filename_stamp)
        if epoch is not None:
            candidates.append((epoch, "filename", filename_stamp))
    if created_at is not None:
        epoch = stamp_epoch(created_at)
        if epoch is not None:
            candidates.append((epoch, "created_at", created_at))
    if not candidates:
        return Verdict(refuse=False)
    stamp_epoch_value, source, stamp_text = max(candidates, key=lambda item: item[0])
    ahead = stamp_epoch_value - now_epoch
    return Verdict(
        refuse=ahead > AHEAD_THRESHOLD_SECONDS,
        ahead_seconds=ahead,
        stamp_epoch=stamp_epoch_value,
        source=source,
        stamp_text=stamp_text,
    )


def resolve_vault_root(env: Mapping[str, str]) -> Path | None:
    """The Personal-vault root: ``PERSONAL_VAULT_PATH`` else ``$HOME/Documents/Personal``.

    Mirrors the ``personal`` branch of ``hooks/scripts/cc-task-root.sh``: whitespace
    trimmed, ``~/`` expanded against this env's HOME, ``~user`` refused, and a
    relative value refused (a relative root is a different vault per process).
    """
    raw = (env.get("PERSONAL_VAULT_PATH") or "").strip()
    if not raw:
        home = (env.get("HOME") or "").strip()
        if not home:
            return None
        raw = os.path.join(home, "Documents", "Personal")
    elif raw == "~" or raw.startswith("~/"):
        home = (env.get("HOME") or "").strip()
        if not home:
            return None
        raw = home if raw == "~" else os.path.join(home, raw[2:])
    elif raw.startswith("~"):
        return None
    if not os.path.isabs(raw):
        return None
    return Path(raw)


def is_under(path: Path, root: Path) -> bool:
    """True when ``path`` resolves to ``root`` or below it."""
    try:
        resolved = path.expanduser().resolve(strict=False)
        anchor = root.expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return False
    return resolved == anchor or anchor in resolved.parents


def _log_near_miss(env: Mapping[str, str], basename: str, kind: str, prefix: str | None) -> None:
    """Append one near-miss line. Never fatal -- a log failure must not block a write."""
    if not prefix:
        return
    home = (env.get("HOME") or "").strip()
    if not home:
        return
    entry = {
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kind": kind,
        "prefix": prefix,
        "basename": basename,
    }
    try:
        log_path = Path(home).joinpath(*_NEAR_MISS_LOG)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError:
        return


def _date_u(now_epoch: int) -> str:
    """The value `date -u` prints for this instant, and its ISO/Z twin."""
    moment = datetime.fromtimestamp(now_epoch, tz=UTC)
    classic = f"{moment:%a %b} {moment.day:2d} {moment:%H:%M:%S} UTC {moment:%Y}"
    return f"{moment:%Y-%m-%dT%H:%M:%S}Z ({classic})"


def refusal_message(path: Path, verdict: Verdict, now_epoch: int) -> str:
    stamp_iso = datetime.fromtimestamp(verdict.stamp_epoch or 0, tz=UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return "\n".join(
        (
            "write-stamp-ahead-guard: REFUSED - a stamp is ahead of the clock.",
            f"  file:            {path}",
            f"  source:          {verdict.source} ({verdict.stamp_text} = {stamp_iso})",
            f"  ahead of clock:  {verdict.ahead_seconds} s (threshold {AHEAD_THRESHOLD_SECONDS} s)",
            f"  current date -u: {_date_u(now_epoch)}",
            "  next action: re-read the clock with `date -u` immediately before writing and",
            "               write the value you measured. This hook refuses only; it never",
            "               rewrites or corrects a stamp.",
        )
    )


def main(stdin_text: str | None = None, env: Mapping[str, str] | None = None) -> int:
    """Exit 2 (and print the clock) on an ahead stamp; 0 otherwise. Fail open."""
    environ: Mapping[str, str] = os.environ if env is None else env
    raw = sys.stdin.read() if stdin_text is None else stdin_text
    try:
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            return 0
        if str(payload.get("tool_name") or "") != "Write":
            return 0
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            return 0
        raw_path = tool_input.get("file_path") or tool_input.get("path") or ""
        if not isinstance(raw_path, str) or not raw_path:
            return 0
        root = resolve_vault_root(environ)
        if root is None:
            return 0
        path = Path(raw_path).expanduser()
        if not is_under(path, root):
            return 0
        content = tool_input.get("content")
        if not isinstance(content, str):
            fallback = tool_input.get("new_string")
            content = fallback if isinstance(fallback, str) else ""
        filename_stamp = parse_filename_stamp(path.name)
        created_at = frontmatter_created_at(content)
        if filename_stamp is None:
            _log_near_miss(environ, path.name, "filename", filename_near_miss(path.name))
        if created_at is None:
            _log_near_miss(environ, path.name, "created_at", created_at_near_miss(content))
        now_epoch = int(time.time())
        verdict = evaluate(now_epoch, filename_stamp, created_at)
        if verdict.refuse:
            print(refusal_message(path, verdict, now_epoch), file=sys.stderr)
            return 2
        return 0
    except Exception:  # noqa: BLE001 - a crashing clock check must never block a write.
        print("write-stamp-ahead-guard: internal error; failing open.", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
