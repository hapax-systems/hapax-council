"""Code-narration producer — detect + emit impingements.

Pure functions + a CLI entry point. Called via systemd user timer every ~30s.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from pathlib import Path

from shared.impingement import Impingement, ImpingementType
from shared.sensor_protocol import IMPINGEMENTS_FILE

log = logging.getLogger("code_narration")

# Editor window class/title patterns — match what Hyprland reports in
# `hyprctl activewindow`. Populated from operator's actual editor usage:
# nvim / neovide / VSCode / Cursor / kitty+editor-in-terminal.
EDITOR_WINDOW_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"neovide", re.I),
    re.compile(r"\bnvim\b", re.I),
    # VSCode window class is often just "Code" (case-preserved); accept that
    # plus explicit forms. The boundary stops false-positives on "qrcode"
    # and similar substrings.
    re.compile(r"\b(vscode|vs\s*code|code-oss|code)\b", re.I),
    re.compile(r"cursor", re.I),
    re.compile(r"zed", re.I),
)

# Project directories to watch. Non-project code changes (dotfiles, /etc)
# are not appropriate material for code-narration.
PROJECT_ROOTS: tuple[Path, ...] = (
    Path.home() / "projects" / "hapax-council",
    Path.home() / "projects" / "hapax-officium",
    Path.home() / "projects" / "hapax-constitution",
    Path.home() / "projects" / "hapax-mcp",
    Path.home() / "projects" / "hapax-watch",
    Path.home() / "projects" / "hapax-phone",
)

# Throttle state lives on disk so producer reinvocations respect history.
_THROTTLE_STATE_FILE = Path.home() / ".cache" / "hapax" / "code-narration-state.json"

# Minimum seconds between narrations scoped to the same project directory.
# Prevents narrator spam during continuous editing within a single repo.
_THROTTLE_PROJECT_S = 120.0

# Maximum seconds since file mtime to consider "recently modified" — a file
# touched 5 minutes ago isn't the current focus even if the editor is open.
_RECENT_FILE_WINDOW_S = 90.0

# Impingement strength — ambient, not urgent. Low enough that boredom
# baseline + stimmung routing don't treat code-narration as an interrupt.
_IMPINGEMENT_STRENGTH = 0.25


def _run(cmd: list[str], cwd: Path | None = None, timeout: float = 3.0) -> str | None:
    """Run a subprocess safely. Return stdout stripped, or None on any failure."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def active_window_is_editor() -> bool:
    """True iff the currently-focused window matches an editor pattern.

    Reads from ``hyprctl activewindow -j`` (Hyprland compositor). Fails
    closed to False (conservative: don't narrate if we can't tell).
    """
    raw = _run(["hyprctl", "activewindow", "-j"])
    if not raw:
        return False
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False
    fields = " ".join(
        str(data.get(k, "")) for k in ("class", "initialClass", "title", "initialTitle")
    )
    return any(p.search(fields) for p in EDITOR_WINDOW_PATTERNS)


def recent_project_changes() -> list[tuple[Path, list[str]]]:
    """Return per-project list of recently-modified files.

    For each known project root that exists, read ``git status --porcelain``
    and filter to files whose mtime is within ``_RECENT_FILE_WINDOW_S``.
    Ignores deletions + untracked files — the narrator wants modified-
    in-place work, not git housekeeping.

    Returns ``[(project_root, [modified_file, ...]), ...]`` for projects
    with any recent activity. Projects with no recent changes are omitted.
    """
    now = time.time()
    results: list[tuple[Path, list[str]]] = []
    for root in PROJECT_ROOTS:
        if not (root / ".git").exists():
            continue
        porcelain = _run(["git", "status", "--porcelain"], cwd=root)
        if not porcelain:
            continue
        recent_files: list[str] = []
        for line in porcelain.splitlines():
            if len(line) < 4:
                continue
            status_code, path = line[:2].strip(), line[3:].strip()
            if status_code in ("D", "DD") or status_code.startswith("??"):
                continue
            # Handle rename format: "oldname -> newname"
            path = path.split(" -> ")[-1].strip('"')
            full = root / path
            try:
                mtime = full.stat().st_mtime
            except OSError:
                continue
            if now - mtime <= _RECENT_FILE_WINDOW_S:
                recent_files.append(path)
        if recent_files:
            results.append((root, recent_files))
    return results


def _load_throttle_state() -> dict[str, float]:
    """Load the per-project last-narrated-at map. Fresh dict on any error."""
    try:
        return {k: float(v) for k, v in json.loads(_THROTTLE_STATE_FILE.read_text()).items()}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def _save_throttle_state(state: dict[str, float]) -> None:
    """Atomic write of the throttle state."""
    try:
        _THROTTLE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _THROTTLE_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        tmp.rename(_THROTTLE_STATE_FILE)
    except OSError:
        log.debug("Failed to persist throttle state", exc_info=True)


def _change_summary(project_root: Path, files: list[str], max_files: int = 3) -> str:
    """Terse summary of what's being edited in this project.

    Currently template-based: lists up to N files. Full LLM-driven
    summaries are a Phase 9 follow-up.
    """
    if len(files) == 1:
        return f"editing {files[0]}"
    head = ", ".join(files[:max_files])
    if len(files) > max_files:
        return f"editing {head} and {len(files) - max_files} other files"
    return f"editing {head}"


def build_narrative(project_root: Path, files: list[str]) -> str:
    """Compose the code-narration narrative string for consumption."""
    project_name = project_root.name
    summary = _change_summary(project_root, files)
    return f"Working in {project_name}: {summary}."


def _emit_impingement(narrative: str, project_root: Path, files: list[str]) -> None:
    """Append a code_narration impingement to the shared JSONL transport."""
    imp = Impingement(
        timestamp=time.time(),
        source="code_narration",
        type=ImpingementType.PATTERN_MATCH,
        strength=_IMPINGEMENT_STRENGTH,
        content={
            "narrative": narrative,
            "metric": "code_narration",
            "project": project_root.name,
            "project_root": str(project_root),
            "files": files,
        },
        context={"role": "executive-function-assistant"},
        interrupt_token="code_narration",
    )
    try:
        IMPINGEMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with IMPINGEMENTS_FILE.open("a", encoding="utf-8") as f:
            f.write(imp.model_dump_json() + "\n")
    except OSError:
        log.warning("Failed to write code_narration impingement", exc_info=True)


def run_once() -> int:
    """One check cycle — detect + emit + update throttle. Returns emit count.

    Intended to be called by a systemd user timer every ~30s. Pure at the
    level of its inputs (hyprctl + filesystem + disk-persisted throttle
    state) so repeat invocation is safe.
    """
    if not active_window_is_editor():
        log.debug("Editor not focused; skipping narration check")
        return 0
    changes = recent_project_changes()
    if not changes:
        log.debug("No recent project changes; skipping narration")
        return 0
    state = _load_throttle_state()
    now = time.time()
    emitted = 0
    for project_root, files in changes:
        key = str(project_root)
        last = state.get(key, 0.0)
        if now - last < _THROTTLE_PROJECT_S:
            continue
        narrative = build_narrative(project_root, files)
        _emit_impingement(narrative, project_root, files)
        state[key] = now
        emitted += 1
        log.info("Emitted code_narration impingement: %s", narrative)
    if emitted > 0:
        _save_throttle_state(state)
    return emitted


def main() -> None:
    """CLI entry point for systemd user timer."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    count = run_once()
    log.debug("code_narration cycle complete (emitted=%d)", count)


if __name__ == "__main__":
    main()
