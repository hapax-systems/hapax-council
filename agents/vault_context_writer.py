"""Vault context writer — persists working context to the daily note.

Appends a timestamped entry under ## Log in today's daily note via the
Obsidian Local REST API. Sources: git branch, recent commits, active sprint
measure, stimmung stance, session duration.

Deterministic (tier 3, no LLM calls). Runs on a 15-minute systemd timer.

Usage:
    uv run python -m agents.vault_context_writer
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import requests
import urllib3

# Suppress self-signed cert warnings for local REST API
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger(__name__)

# --- Configuration ---

OBSIDIAN_API = "https://localhost:27124"
API_KEY_PATH = (
    Path.home()
    / "Documents"
    / "Personal"
    / ".obsidian"
    / "plugins"
    / "obsidian-local-rest-api"
    / "data.json"
)
PROJECTS_DIR = Path.home() / "projects"
STIMMUNG_STATE = Path("/dev/shm/hapax-stimmung/state.json")
SPRINT_STATE = Path("/dev/shm/hapax-sprint/state.json")
COUNCIL_DIR = PROJECTS_DIR / "hapax-council"


def _load_api_key() -> str | None:
    try:
        data = json.loads(API_KEY_PATH.read_text(encoding="utf-8"))
        return data.get("apiKey")
    except Exception:
        log.warning("Failed to read Obsidian REST API key")
        return None


def _git_context() -> dict[str, str]:
    """Get current branch and last 3 commit subjects."""
    result: dict[str, str] = {}
    try:
        branch = subprocess.run(
            ["git", "-C", str(COUNCIL_DIR), "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if branch.returncode == 0:
            result["branch"] = branch.stdout.strip()

        log_out = subprocess.run(
            ["git", "-C", str(COUNCIL_DIR), "log", "--oneline", "-3", "--format=%s"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if log_out.returncode == 0:
            result["recent_commits"] = log_out.stdout.strip()
    except Exception:
        pass
    return result


def _stimmung_context() -> str:
    """Read stimmung stance."""
    try:
        data = json.loads(STIMMUNG_STATE.read_text(encoding="utf-8"))
        return data.get("stance", "unknown")
    except Exception:
        return "unknown"


def _sprint_context() -> dict[str, str]:
    """Read active sprint measure and blocking gate."""
    result: dict[str, str] = {}
    try:
        data = json.loads(SPRINT_STATE.read_text(encoding="utf-8"))
        nb = data.get("next_block")
        if isinstance(nb, dict) and nb.get("measure"):
            result["next_measure"] = f"{nb['measure']} {nb.get('title', '')}"
        gate = data.get("blocking_gate")
        if gate:
            result["blocking_gate"] = gate
        result["progress"] = f"{data.get('measures_completed', 0)}/{data.get('measures_total', 0)}"
    except Exception:
        pass
    return result


def _build_entry() -> str:
    """Build a single log entry from all context sources."""
    now = datetime.now(UTC).strftime("%H:%M")
    parts = [f"- **{now}**"]

    git = _git_context()
    if git.get("branch"):
        parts.append(f"  branch: `{git['branch']}`")
    if git.get("recent_commits"):
        for line in git["recent_commits"].splitlines()[:3]:
            parts.append(f"  - {line}")

    sprint = _sprint_context()
    if sprint.get("next_measure"):
        parts.append(f"  sprint: {sprint['next_measure']} ({sprint.get('progress', '?')})")
    if sprint.get("blocking_gate"):
        parts.append(f"  **blocked**: gate {sprint['blocking_gate']}")

    stance = _stimmung_context()
    if stance != "unknown":
        parts.append(f"  stimmung: {stance}")

    return "\n".join(parts)


def _append_to_daily(entry: str) -> bool:
    """Append entry under ## Log in today's daily note."""
    api_key = _load_api_key()
    if not api_key:
        log.error("No API key — cannot write to vault")
        return False

    today = datetime.now().strftime("%Y-%m-%d")
    path = f"40-calendar/daily/{today}.md"

    # Read current content — localhost Obsidian REST API uses self-signed cert
    resp = requests.get(
        f"{OBSIDIAN_API}/vault/{path}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "text/markdown"},
        verify=False,  # noqa: S501  # nosec B501 - localhost self-signed
        timeout=5,
    )

    if resp.status_code == 404:
        log.info("Daily note doesn't exist yet — skipping")
        return False
    if resp.status_code != 200:
        log.warning("Failed to read daily note: %s", resp.status_code)
        return False

    content = resp.text

    # Insert entry after "## Log" line (before the next section or end)
    lines = content.split("\n")
    insert_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "## Log":
            insert_idx = i + 1
            # Skip the placeholder dash if it's the only content
            if insert_idx < len(lines) and lines[insert_idx].strip() == "-":
                lines[insert_idx] = ""  # Remove placeholder
            break

    if insert_idx is None:
        log.warning("No ## Log section in daily note")
        return False

    lines.insert(insert_idx, entry)
    new_content = "\n".join(lines)

    # Write back via PUT — localhost Obsidian REST API uses self-signed cert
    resp = requests.put(
        f"{OBSIDIAN_API}/vault/{path}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "text/markdown",
        },
        data=new_content.encode("utf-8"),
        verify=False,  # noqa: S501  # nosec B501 - localhost self-signed
        timeout=5,
    )

    if resp.status_code in (200, 204):
        log.info("Appended context to daily note")
        return True
    else:
        log.warning("PUT failed: %s %s", resp.status_code, resp.text[:200])
        return False


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    entry = _build_entry()
    log.info("Context entry:\n%s", entry)

    if _append_to_daily(entry):
        log.info("Done — context written to daily note")
    else:
        log.warning("Failed to write context")


if __name__ == "__main__":
    main()
