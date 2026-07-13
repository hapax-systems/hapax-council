#!/usr/bin/env python3
"""Phase-advance: after closing Phase N, create Phase N+1 if the request has more phases.

Called by cc-close after a successful done-status close. Reads the parent
request for phase structure, creates the next phase's task if one exists
and no task already covers it.

Exit 0 always — advisory, never blocks cc-close.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

TASKS_DIR = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks"
REQUESTS_DIR = Path.home() / "Documents/Personal/20-projects/hapax-requests/active"
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from shared.sdlc_filesystem_transaction import (  # noqa: E402
    FilesystemTransactionError,
    create_task_note_transactionally,
)

OWNERSHIP_CACHE = Path(
    os.environ.get("HAPAX_CC_OWNERSHIP_CACHE_DIR", str(Path.home() / ".cache/hapax"))
).expanduser()


def _extract_phase(task_id: str, title: str) -> int | None:
    for text in (task_id, title):
        m = re.search(r"[Pp]hase[- _]?(\d+)", text)
        if m:
            return int(m.group(1))
    return None


def _find_parent_request(note_path: Path) -> Path | None:
    text = note_path.read_text(errors="replace")[:1000]
    for line in text.splitlines():
        if line.strip().startswith("parent_request:"):
            val = line.split(":", 1)[1].strip().strip('"').strip("'")
            if val and val != "null":
                for d in [REQUESTS_DIR, REQUESTS_DIR.parent / "closed"]:
                    candidate = d / val
                    if candidate.exists():
                        return candidate
                    for f in d.iterdir():
                        if val in f.name:
                            return f
    return None


def _request_has_phase(request_path: Path, phase_num: int) -> bool:
    text = request_path.read_text(errors="replace")
    return bool(re.search(rf"###?\s*Phase\s*{phase_num}\b", text, re.IGNORECASE))


def _phase_task_exists(phase_num: int, parent_request: str) -> bool:
    for d in [TASKS_DIR / "active", TASKS_DIR / "closed"]:
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if f.suffix != ".md":
                continue
            name = f.name.lower()
            if (
                f"phase{phase_num}" in name
                or f"phase-{phase_num}" in name
                or f"phase_{phase_num}" in name
            ):
                text = f.read_text(errors="replace")[:500]
                if parent_request in text:
                    return True
    return False


def main() -> None:
    if len(sys.argv) < 3:
        return

    closed_note = Path(sys.argv[1])
    task_id = sys.argv[2]

    if not closed_note.exists():
        return

    text = closed_note.read_text(errors="replace")[:1000]
    fields: dict[str, str] = {}
    if text.startswith("---"):
        end = text.find("\n---", 4)
        if end > 0:
            for line in text[4:end].splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    fields[k.strip()] = v.strip().strip('"').strip("'")

    title = fields.get("title", "")
    current_phase = _extract_phase(task_id, title)
    if current_phase is None:
        return

    request_path = _find_parent_request(closed_note)
    if request_path is None:
        return

    next_phase = current_phase + 1
    if not _request_has_phase(request_path, next_phase):
        return

    parent_req = fields.get("parent_request", "")
    if _phase_task_exists(next_phase, parent_req):
        print(f"cc-phase-advance: Phase {next_phase} task already exists, skipping")
        return

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    wsjf = float(fields.get("wsjf", "5.0") or "5.0") * 0.85
    slug = re.sub(r"phase[- _]?\d+", f"phase{next_phase}", task_id, flags=re.IGNORECASE)
    if slug == task_id:
        slug = f"{task_id}-phase{next_phase}"

    new_title = re.sub(
        r"[Pp]hase\s*\d+",
        f"Phase {next_phase}",
        title,
    )
    if new_title == title:
        new_title = f"Phase {next_phase}: {title}"

    content = f"""---
type: cc-task
task_id: {slug}
title: "{new_title}"
status: offered
assigned_to: unassigned
priority: {fields.get("priority", "p2")}
wsjf: {wsjf:.1f}
kind: {fields.get("kind", "build")}
parent_request: {parent_req}
authority_case: {fields.get("authority_case", "")}
parent_spec: {fields.get("parent_spec", "null")}
created_at: {now}
updated_at: {now}
tags:
  - cc-task
  - auto-phase-advance
---

# {new_title}

Auto-created by cc-phase-advance after Phase {current_phase} closed.

## Acceptance Criteria

- [ ] Phase {next_phase} deliverables complete
- [ ] Tests pass
- [ ] PR merged
"""

    out_path = TASKS_DIR / "active" / f"{slug}.md"
    if out_path.exists():
        print(f"cc-phase-advance: {slug} already exists")
        return

    closed_path = TASKS_DIR / "closed" / out_path.name
    closed_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        create_task_note_transactionally(
            out_path,
            content=content.encode("utf-8"),
            mode=0o644,
            cache_dir=OWNERSHIP_CACHE,
            vault_root=TASKS_DIR,
            absent_guard_paths=(closed_path,),
        )
    except (OSError, FilesystemTransactionError) as exc:
        print(f"cc-phase-advance: create lost identity race for {slug}: {exc}")
        return
    print(f"cc-phase-advance: created Phase {next_phase} task: {slug} (WSJF {wsjf:.1f})")


if __name__ == "__main__":
    main()
