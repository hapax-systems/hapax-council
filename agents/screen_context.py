"""Screen context sync — capture active window context for behavioral profiling.

Samples the active Hyprland window and writes hourly summaries to
rag-sources/screen-context/. Enriches each sample with concurrent
flow state, activity mode, and stimmung stance from perception state.

Feeds the work_patterns, tool_usage, and energy_and_attention profile
dimensions. Fills the screen_context producer gap in dimensions.py.

Run: uv run python -m agents.screen_context
Timer: every 5 minutes via systemd (accumulates, writes hourly summaries)
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

RAG_DIR = Path.home() / "documents" / "rag-sources" / "screen-context"
CACHE_DIR = Path.home() / ".cache" / "screen-context"
STATE_FILE = CACHE_DIR / "state.json"
FACTS_FILE = CACHE_DIR / "screen-context-profile-facts.jsonl"
PERCEPTION_STATE = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"
STIMMUNG_STATE = Path("/dev/shm/hapax-stimmung/state.json")


def _hyprctl_activewindow() -> dict | None:
    """Get active window info from Hyprland."""
    try:
        result = subprocess.run(
            ["hyprctl", "activewindow", "-j"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        log.warning("hyprctl failed: %s", e)
    return None


def _read_perception() -> dict:
    """Read current perception state."""
    try:
        data = json.loads(PERCEPTION_STATE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _read_stimmung() -> str:
    """Read current stimmung stance."""
    try:
        data = json.loads(STIMMUNG_STATE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return "unknown"
    if not isinstance(data, dict):
        return "unknown"
    return data.get("overall_stance", "unknown")


def _default_state() -> dict:
    return {"samples": [], "last_hour_written": ""}


def _load_state() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return _default_state()
    if not isinstance(data, dict):
        return _default_state()
    return data


def _save_state(state: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _classify_app(app_class: str) -> str:
    """Classify app into a category."""
    app = app_class.lower()
    if app in ("foot", "kitty", "alacritty", "wezterm"):
        return "terminal"
    if app in ("code", "code-oss", "vscodium"):
        return "editor"
    if app in ("firefox", "chromium", "google-chrome", "brave-browser"):
        return "browser"
    if app in ("discord", "slack", "telegram-desktop", "signal-desktop"):
        return "chat"
    if app in ("obs", "obs-studio"):
        return "streaming"
    if app in ("gimp", "inkscape", "krita"):
        return "graphics"
    if app in ("bitwig-studio", "reaper", "ardour"):
        return "daw"
    return "other"


def sync() -> bool:
    """Sample current window and accumulate. Write hourly summary when hour rolls."""
    window = _hyprctl_activewindow()
    if window is None:
        return False

    perc = _read_perception()
    state = _load_state()
    now = datetime.now(UTC)
    current_hour = now.strftime("%Y-%m-%d-%H")

    app_class = window.get("class", "unknown")
    title = window.get("title", "")
    workspace_id = window.get("workspace", {}).get("id", 0)

    sample = {
        "timestamp": now.isoformat(),
        "app_class": app_class,
        "app_category": _classify_app(app_class),
        "title": title[:120],  # truncate long titles
        "workspace_id": workspace_id,
        "flow_state": perc.get("flow_state", "unknown"),
        "activity_mode": perc.get("activity_mode", "unknown"),
        "stimmung_stance": _read_stimmung(),
        "operator_present": perc.get("operator_present", True),
    }

    state.setdefault("samples", []).append(sample)

    # Write hourly summary when the hour rolls over
    last_hour = state.get("last_hour_written", "")
    if last_hour and last_hour != current_hour:
        hour_samples = [
            s for s in state["samples"] if s["timestamp"][:13].replace("T", "-") == last_hour
        ]
        if hour_samples:
            _write_hourly_doc(last_hour, hour_samples)
            # Remove written samples
            state["samples"] = [
                s for s in state["samples"] if s["timestamp"][:13].replace("T", "-") != last_hour
            ]

    state["last_hour_written"] = current_hour
    _save_state(state)

    # Write profile facts periodically
    _write_profile_facts(state["samples"])

    return True


def _write_hourly_doc(hour_str: str, samples: list[dict]) -> None:
    """Write an hourly screen context summary."""
    RAG_DIR.mkdir(parents=True, exist_ok=True)
    path = RAG_DIR / f"context-{hour_str}.md"

    # Compute app time distribution
    app_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    flow_counts: dict[str, int] = {}
    activity_counts: dict[str, int] = {}

    for s in samples:
        app_counts[s["app_class"]] = app_counts.get(s["app_class"], 0) + 1
        category_counts[s["app_category"]] = category_counts.get(s["app_category"], 0) + 1
        flow_counts[s["flow_state"]] = flow_counts.get(s["flow_state"], 0) + 1
        activity_counts[s["activity_mode"]] = activity_counts.get(s["activity_mode"], 0) + 1

    total = len(samples)
    date_part = hour_str[:10]
    hour_part = hour_str[-2:]

    # Dominant app and state
    dominant_app = max(app_counts, key=app_counts.get) if app_counts else "unknown"
    dominant_flow = max(flow_counts, key=flow_counts.get) if flow_counts else "unknown"

    frontmatter = {
        "source_service": "screen_context",
        "content_type": "screen_context_hourly",
        "timestamp": samples[-1]["timestamp"],
        "modality_tags": ["behavioral", "temporal"],
        "date": date_part,
        "hour": int(hour_part),
        "sample_count": total,
        "dominant_app": dominant_app,
        "dominant_flow_state": dominant_flow,
    }

    lines = [
        f"---\n{yaml.dump(frontmatter, default_flow_style=False).strip()}\n---",
        f"# Screen Context — {date_part} {hour_part}:00\n",
        f"**Samples:** {total}",
        f"**Dominant app:** {dominant_app}",
        f"**Dominant flow state:** {dominant_flow}\n",
    ]

    lines.append("## App Usage\n")
    for app, count in sorted(app_counts.items(), key=lambda x: -x[1]):
        pct = (count / total) * 100
        lines.append(
            f"- **{app}** ({category_counts.get(_classify_app(app), '?')}): {pct:.0f}% ({count} samples)"
        )

    lines.append("\n## Flow State Distribution\n")
    for fs, count in sorted(flow_counts.items(), key=lambda x: -x[1]):
        pct = (count / total) * 100
        lines.append(f"- **{fs}:** {pct:.0f}%")

    lines.append("\n## Activity Mode Distribution\n")
    for am, count in sorted(activity_counts.items(), key=lambda x: -x[1]):
        pct = (count / total) * 100
        lines.append(f"- **{am}:** {pct:.0f}%")

    # Window title samples (unique, for context)
    unique_titles = list(dict.fromkeys(s["title"] for s in samples if s["title"]))[:10]
    if unique_titles:
        lines.append("\n## Window Titles (sample)\n")
        for t in unique_titles:
            lines.append(f"- {t}")

    path.write_text("\n".join(lines) + "\n")
    log.info("Wrote screen context: %s (%d samples)", path.name, total)


def _write_profile_facts(samples: list[dict]) -> None:
    """Write profile facts from accumulated samples."""
    if not samples:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Top apps by frequency
    app_counts: dict[str, int] = {}
    for s in samples:
        app_counts[s["app_class"]] = app_counts.get(s["app_class"], 0) + 1
    top_apps = sorted(app_counts.items(), key=lambda x: -x[1])[:10]

    facts = [
        {
            "dimension": "tool_usage",
            "key": "screen_context_top_apps",
            "value": ", ".join(f"{app} ({count})" for app, count in top_apps),
            "confidence": 0.8,
            "source": "screen_context",
        },
        {
            "dimension": "work_patterns",
            "key": "screen_context_sample_count",
            "value": f"{len(samples)} screen context samples across {len(app_counts)} apps",
            "confidence": 0.9,
            "source": "screen_context",
        },
    ]

    with open(FACTS_FILE, "w") as f:
        for fact in facts:
            f.write(json.dumps(fact) + "\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if sync():
        print("Screen context synced.")
    else:
        print("Screen context sync failed (no Hyprland window).")
