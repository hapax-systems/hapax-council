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
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests
import urllib3

from shared.vault_ownership import frontmatter_preserved

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

# Awareness daemon outputs consumed by the section renderers below.
# These paths match the canonical writers in
# ``agents/operator_awareness/`` and ``agents/refusal_brief/``;
# missing files degrade gracefully (renderers emit a stale-state
# placeholder rather than crashing the daily-note tick).
AWARENESS_STATE_PATH = Path("/dev/shm/hapax-awareness/state.json")
REFUSALS_LOG_PATH = Path("/dev/shm/hapax-refusals/log.jsonl")

# Refused section: tail window. Spec is "last 24h"; renderer drops
# events whose timestamp falls outside that window so the section
# rotates content automatically as events age out.
REFUSED_TAIL_WINDOW_S = 24 * 60 * 60

# Awareness state TTL — when the state file timestamp is older than
# this, the section renders a dimmed placeholder. Matches the
# AwarenessState.ttl_seconds default (90s) so consumer + producer
# share the staleness contract.
AWARENESS_STALE_AFTER_S = 90.0

# Prometheus per-section append counter. Optional dependency: when
# prometheus_client isn't installed (minimal test envs), falls back
# to a no-op so the daily-note tick still completes.
hapax_awareness_vault_appends_total = None
try:
    from prometheus_client import Counter as _VaultCounter

    hapax_awareness_vault_appends_total = _VaultCounter(
        "hapax_awareness_vault_appends_total",
        "Daily-note awareness/refused section append outcomes.",
        ["result", "section"],
    )
except Exception:
    pass


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

    # Read current content — localhost Obsidian REST API uses self-signed cert.
    # Connection failures (Obsidian desktop not running) are expected and
    # non-fatal — return False + info-log so the systemd unit exits clean
    # rather than triggering notify-failure on every 15-min tick when the
    # operator happens to have Obsidian closed.
    try:
        resp = requests.get(
            f"{OBSIDIAN_API}/vault/{path}",
            headers={"Authorization": f"Bearer {api_key}", "Accept": "text/markdown"},
            verify=False,  # noqa: S501  # nosec B501 - localhost self-signed
            timeout=5,
        )
    except requests.exceptions.ConnectionError:
        log.info(
            "Obsidian API unreachable at %s — skipping this tick "
            "(open Obsidian to resume context writes)",
            OBSIDIAN_API,
        )
        return False
    except requests.exceptions.Timeout:
        log.info("Obsidian API timed out — skipping this tick")
        return False

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

    # OQ-9: the daily note is operator-owned. A daemon body-section write must
    # never alter the operator's frontmatter — refuse the write if it would.
    if not frontmatter_preserved(content, new_content):
        log.error("Refusing daily-note append: would mutate operator frontmatter")
        return False

    # Write back via PUT — localhost Obsidian REST API uses self-signed cert.
    try:
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
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        log.info("Obsidian API unavailable during PUT: %s — skipping", type(e).__name__)
        return False

    if resp.status_code in (200, 204):
        log.info("Appended context to daily note")
        return True
    else:
        log.warning("PUT failed: %s %s", resp.status_code, resp.text[:200])
        return False


# ── Awareness / Refused section rendering ─────────────────────────


def _read_awareness_state(
    *,
    path: Path = AWARENESS_STATE_PATH,
    now: datetime | None = None,
    stale_after_s: float = AWARENESS_STALE_AFTER_S,
) -> tuple[dict | None, str | None]:
    """Return ``(state_dict, stale_reason)``.

    ``state_dict`` is None when the file is missing or unparseable;
    ``stale_reason`` carries a short message ("missing"/"stale"/"unreadable")
    used by the renderer to dim the section. Both None when state is
    fresh — renderer happy path.
    """
    if not path.exists():
        return None, "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "unreadable"
    if not isinstance(data, dict):
        return None, "unreadable"
    ts_raw = data.get("timestamp")
    if isinstance(ts_raw, str):
        try:
            ts = datetime.fromisoformat(ts_raw)
        except ValueError:
            return None, "unreadable"
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        wall = now or datetime.now(UTC)
        age_s = (wall - ts).total_seconds()
        if age_s > stale_after_s:
            return None, f"stale (last update {int(age_s)}s ago)"
    return data, None


def _block(state: dict, key: str) -> dict:
    """Return ``state[key]`` as a dict (defaulting to empty)."""
    val = state.get(key)
    return val if isinstance(val, dict) else {}


def render_awareness_section(
    state: dict | None,
    *,
    stale_reason: str | None = None,
    now: datetime | None = None,
) -> str:
    """Render the ``## Awareness`` section markdown.

    Compact, prose-table per category. NEVER aggregates refusals
    (those live in their own section). When ``stale_reason`` is set
    OR ``state`` is None, renders a single dimmed placeholder line
    rather than fabricating zero-valued blocks.
    """
    wall = (now or datetime.now(UTC)).strftime("%H:%M UTC")
    header = f"## Awareness\n\n_15m tick · last sync {wall}_\n\n"
    if state is None or stale_reason is not None:
        msg = stale_reason or "no state"
        return f"{header}- _state {msg}_\n"

    stream = _block(state, "stream")
    health = _block(state, "health_system")
    music = _block(state, "music_soundcloud")
    publishing = _block(state, "publishing_pipeline")
    research = _block(state, "research_dispatches")
    programmes = _block(state, "content_programmes")
    marketing = _block(state, "marketing_outreach")
    fleet = _block(state, "hardware_fleet")
    sprint = _block(state, "time_sprint")
    daimonion = _block(state, "daimonion_voice")
    governance = _block(state, "governance")

    lines = [
        f"- Stream: {'live' if stream.get('live') else 'offline'} · "
        f"{int(stream.get('chronicle_events_5min', 0))} events/5min",
        f"- Health: {health.get('overall_status', 'unknown')} · "
        f"failed={int(health.get('failed_units', 0))} · "
        f"disk {float(health.get('disk_pct_used', 0)):.0f}% · "
        f"GPU {float(health.get('gpu_vram_pct_used', 0)):.0f}%",
        f"- Daimonion: stance={daimonion.get('stance', 'unknown')} · "
        f"{'voice-on' if daimonion.get('voice_session_active') else 'voice-off'}",
        f"- Music: source={music.get('source') or 'none'} · "
        f"{'playing' if music.get('is_playing') else 'silent'}",
        f"- Publishing: inbox={int(publishing.get('inbox_count', 0))} · "
        f"in-flight={int(publishing.get('in_flight_count', 0))}",
        f"- Research: in-flight={int(research.get('in_flight_count', 0))}",
        f"- Programmes: active={programmes.get('active_programme') or 'none'}",
        f"- Marketing: pending={int(marketing.get('pending_count', 0))}",
        f"- Fleet: pi {int(fleet.get('pi_count_online', 0))}/"
        f"{int(fleet.get('pi_count_total', 0))} online",
        f"- Sprint: day={int(sprint.get('sprint_day', 0))} · "
        f"completed={int(sprint.get('completed_measures', 0))} · "
        f"blocked={int(sprint.get('blocked_measures', 0))}",
        f"- Governance: contracts={int(governance.get('active_consent_contracts', 0))}",
    ]
    return header + "\n".join(lines) + "\n"


def _read_refused_events(
    *,
    path: Path = REFUSALS_LOG_PATH,
    now: datetime | None = None,
    window_s: float = REFUSED_TAIL_WINDOW_S,
) -> list[dict]:
    """Tail valid refusal events from the log within the rolling window.

    Returns events as raw dicts (NEVER aggregated, NEVER summarized
    — constitutional load-bearing per the spec). Missing file or
    malformed lines yield an empty list rather than raising.
    """
    if not path.exists():
        return []
    cutoff = (now or datetime.now(UTC)) - timedelta(seconds=window_s)
    events: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                text = raw.strip()
                if not text:
                    continue
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                ts_raw = data.get("timestamp")
                if not isinstance(ts_raw, str):
                    continue
                try:
                    ts = datetime.fromisoformat(ts_raw)
                except ValueError:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts >= cutoff:
                    events.append(data)
    except OSError:
        return []
    return events


def render_refused_section(events: list[dict]) -> str:
    """Render the ``## Refused`` section markdown.

    Raw enumerated list — one row per refusal, no aggregation, no
    "30 refusals today" summary, no categorisation. Constitutional
    load-bearing per ``feedback_full_automation_or_no_engagement``
    and the awareness-vault-daily-note-extension spec: aggregating
    refusals would erase the per-event provenance the operator can
    inspect.
    """
    header = "## Refused\n\n_first-class refusal log · raw entries, no aggregation_\n\n"
    if not events:
        return f"{header}- _no refusals in the last 24h_\n"
    rows: list[str] = []
    for ev in events:
        ts_raw = ev.get("timestamp", "")
        # Trim to minute precision for daily-note compactness; the
        # full-fidelity timestamp lives in the JSONL log.
        try:
            ts = datetime.fromisoformat(str(ts_raw))
            ts_disp = ts.strftime("%H:%M")
        except ValueError:
            ts_disp = str(ts_raw)[:5]
        axiom = ev.get("axiom", "?")
        surface = ev.get("surface", "?")
        reason = (ev.get("reason") or "").strip()
        # Single-line reason; the writer's 160-char cap already
        # bounds the source field, so this is just a defence against
        # accidental newlines in legacy log entries.
        reason = reason.replace("\n", " ").replace("\r", " ")
        rows.append(f"- {ts_disp} · axiom={axiom} · surface={surface} · reason={reason}")
    return header + "\n".join(rows) + "\n"


def _replace_section_in_daily(
    section_heading: str,
    rendered: str,
    *,
    today: str | None = None,
) -> bool:
    """Idempotently replace ``section_heading`` block in today's daily note.

    Replace-not-append semantics: if the section already exists,
    it's rewritten in-place; if not, it's appended to the end of
    the file. Either way, two consecutive ticks produce the same
    file content (modulo refreshed values), so retries are safe.

    Section boundary is the next ``## `` heading or end-of-file.
    """
    api_key = _load_api_key()
    if not api_key:
        log.error("No API key — cannot replace %s section", section_heading)
        return False

    today = today or datetime.now().strftime("%Y-%m-%d")
    path = f"40-calendar/daily/{today}.md"

    try:
        resp = requests.get(
            f"{OBSIDIAN_API}/vault/{path}",
            headers={"Authorization": f"Bearer {api_key}", "Accept": "text/markdown"},
            verify=False,  # noqa: S501  # nosec B501 - localhost self-signed
            timeout=5,
        )
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        log.info("Obsidian API unavailable for %s: %s", section_heading, type(e).__name__)
        return False

    if resp.status_code == 404:
        log.info("Daily note doesn't exist yet — skipping %s", section_heading)
        return False
    if resp.status_code != 200:
        log.warning("Failed to read daily note: %s", resp.status_code)
        return False

    new_content = _splice_section(resp.text, section_heading, rendered)

    # OQ-9: operator-owned daily note — a body-section replace must never touch
    # operator frontmatter. Refuse the write if it would.
    if not frontmatter_preserved(resp.text, new_content):
        log.error("Refusing %s write: would mutate operator frontmatter", section_heading)
        return False

    try:
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
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        log.info("PUT failed for %s: %s", section_heading, type(e).__name__)
        return False

    if resp.status_code in (200, 204):
        return True
    log.warning("PUT %s failed: %s", section_heading, resp.status_code)
    return False


def _splice_section(content: str, heading: str, rendered: str) -> str:
    """Return ``content`` with ``heading`` block replaced by ``rendered``.

    Pure function (the network call lives in
    :func:`_replace_section_in_daily`). Splits on lines, finds the
    heading line, replaces from there until the next ``## `` heading
    or end-of-file. If ``heading`` is absent, appends at end with a
    blank-line separator.
    """
    lines = content.split("\n")
    start_idx: int | None = None
    for i, line in enumerate(lines):
        if line.strip() == heading.strip():
            start_idx = i
            break

    rendered_block = rendered.rstrip("\n")
    if start_idx is None:
        # Append at end with a blank-line separator. Avoid a stray
        # extra blank line when the file already ends with one.
        sep = "" if content.endswith("\n\n") else ("\n" if content.endswith("\n") else "\n\n")
        return content + sep + rendered_block + "\n"

    # Find the end of the section: the next ``## `` line, exclusive.
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].startswith("## "):
            end_idx = j
            break

    head = "\n".join(lines[:start_idx])
    tail = "\n".join(lines[end_idx:])
    parts: list[str] = []
    if head:
        parts.append(head)
    parts.append(rendered_block)
    if tail:
        parts.append(tail)
    return "\n".join(parts)


def _record_section_outcome(*, section: str, ok: bool) -> None:
    """Bump the per-section append counter (no-op if Prom unavailable)."""
    if hapax_awareness_vault_appends_total is None:
        return
    try:
        hapax_awareness_vault_appends_total.labels(
            result="ok" if ok else "error",
            section=section,
        ).inc()
    except Exception:
        pass


def write_awareness_section() -> bool:
    """Read awareness state and write the ``## Awareness`` section.

    Returns True iff the PUT succeeded; False on any degraded path
    (Obsidian unreachable, missing daily note, missing state file).
    All failure paths are non-fatal — the daily-note tick continues.
    """
    state, stale = _read_awareness_state()
    rendered = render_awareness_section(state, stale_reason=stale)
    ok = _replace_section_in_daily("## Awareness", rendered)
    _record_section_outcome(section="awareness", ok=ok)
    return ok


def write_refused_section() -> bool:
    """Tail the refusal log and write the ``## Refused`` section.

    Returns True iff the PUT succeeded. Always renders raw events;
    even an empty event list produces a deterministic placeholder
    line (rather than omitting the section) so the operator can see
    "no refusals" as a positive signal.
    """
    events = _read_refused_events()
    rendered = render_refused_section(events)
    ok = _replace_section_in_daily("## Refused", rendered)
    _record_section_outcome(section="refused", ok=ok)
    return ok


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    entry = _build_entry()
    log.info("Context entry:\n%s", entry)

    if _append_to_daily(entry):
        log.info("Done — context written to daily note")
    else:
        log.warning("Failed to write context")

    # Awareness + Refused sections (best-effort, independent of the
    # ## Log append above — neither section's failure rolls back the
    # other).
    write_awareness_section()
    write_refused_section()


if __name__ == "__main__":
    main()
