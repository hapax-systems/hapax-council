"""Interview compass — assemble direction document for nightly operator interviews.

Runs 30 minutes before interview time. Reads chronicle events, open CC-tasks,
system observations (stimmung trends), and profile gaps. Produces a compass
document at /dev/shm/hapax-interview/compass.json for the interview agent.

Usage:
    uv run python -m agents.interview_compass
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

COMPASS_PATH = Path("/dev/shm/hapax-interview/compass.json")
CHRONICLE_PATH = Path("/dev/shm/hapax-chronicle/events.jsonl")
STIMMUNG_PATH = Path("/dev/shm/hapax-stimmung/state.json")
CC_TASKS_DIR = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"


@dataclass
class CompassDocument:
    generated_at: float = field(default_factory=time.time)
    chronicle_highlights: list[dict] = field(default_factory=list)
    open_threads: list[dict] = field(default_factory=list)
    stimmung_snapshot: dict = field(default_factory=dict)
    profile_gaps: list[str] = field(default_factory=list)
    suggested_directions: list[str] = field(default_factory=list)


def read_today_chronicle(window_h: float = 24.0) -> list[dict]:
    """Read chronicle events from the last window_h hours."""
    if not CHRONICLE_PATH.exists():
        return []
    cutoff = time.time() - (window_h * 3600)
    events: list[dict] = []
    try:
        with CHRONICLE_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                ts = event.get("ts")
                if isinstance(ts, (int, float)) and ts >= cutoff:
                    events.append(event)
    except OSError:
        log.debug("Chronicle read failed", exc_info=True)
    return events


def _chronicle_highlights(events: list[dict], max_items: int = 10) -> list[dict]:
    """Extract high-salience events for interview context."""
    salient = [e for e in events if e.get("salience", 0) >= 0.7]
    salient.sort(key=lambda e: e.get("salience", 0), reverse=True)
    return [
        {
            "source": e.get("source", "unknown"),
            "narrative": e.get("narrative", e.get("text", ""))[:200],
            "salience": e.get("salience", 0),
            "ts": e.get("ts"),
        }
        for e in salient[:max_items]
    ]


def read_open_threads(max_items: int = 8) -> list[dict]:
    """Read in-progress and claimed CC-tasks as open threads."""
    if not CC_TASKS_DIR.is_dir():
        return []
    threads: list[dict] = []
    for f in CC_TASKS_DIR.glob("*.md"):
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        status = ""
        title = ""
        wsjf = 0.0
        for line in text.split("\n"):
            if line.startswith("status:"):
                status = line.split(":", 1)[1].strip()
            elif line.startswith("title:"):
                title = line.split(":", 1)[1].strip().strip('"')
            elif line.startswith("wsjf:"):
                try:
                    wsjf = float(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
        if status in ("in_progress", "claimed", "pr_open"):
            threads.append({"title": title, "status": status, "wsjf": wsjf})
    threads.sort(key=lambda t: t["wsjf"], reverse=True)
    return threads[:max_items]


def read_stimmung_snapshot() -> dict:
    """Read current stimmung state."""
    try:
        raw = json.loads(STIMMUNG_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {
            "overall_stance": raw.get("overall_stance", "unknown"),
            "energy": raw.get("energy"),
            "valence": raw.get("valence"),
            "arousal": raw.get("arousal"),
        }
    except (OSError, json.JSONDecodeError):
        return {}


def read_profile_gaps() -> list[str]:
    """Identify sparse/missing profile dimensions for interview direction."""
    try:
        from logos.interview import analyze_profile

        analysis = analyze_profile()
        gaps: list[str] = []
        for dim in analysis.missing_dimensions[:3]:
            gaps.append(f"Missing dimension: {dim}")
        for sparse in analysis.sparse_dimensions[:3]:
            gaps.append(f"Sparse: {sparse.get('dimension', '?')} ({sparse.get('count', 0)} facts)")
        return gaps
    except Exception:
        log.debug("Profile analysis failed", exc_info=True)
        return []


def _derive_directions(
    highlights: list[dict],
    threads: list[dict],
    stimmung: dict,
    gaps: list[str],
) -> list[str]:
    """Derive interview directions from assembled context (deterministic)."""
    directions: list[str] = []

    if highlights:
        top = highlights[0]
        directions.append(
            f"Chronicle: {top['source']} — {top['narrative'][:80]}"
        )

    if threads:
        top_thread = threads[0]
        directions.append(f"Active work: {top_thread['title']}")

    if gaps:
        directions.append(f"Profile gap: {gaps[0]}")

    stance = stimmung.get("overall_stance", "nominal")
    if stance not in ("nominal", "unknown"):
        directions.append(f"Stimmung: {stance} — explore what's driving this state")

    if not directions:
        directions.append("No specific direction — open exploratory interview")

    return directions


def generate_compass() -> CompassDocument:
    """Assemble the interview compass from all sources."""
    events = read_today_chronicle()
    highlights = _chronicle_highlights(events)
    threads = read_open_threads()
    stimmung = read_stimmung_snapshot()
    gaps = read_profile_gaps()
    directions = _derive_directions(highlights, threads, stimmung, gaps)

    return CompassDocument(
        chronicle_highlights=highlights,
        open_threads=threads,
        stimmung_snapshot=stimmung,
        profile_gaps=gaps,
        suggested_directions=directions,
    )


def write_compass(compass: CompassDocument) -> Path:
    """Write compass to SHM for interview agent consumption."""
    COMPASS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = COMPASS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(compass), indent=2, default=str))
    os.replace(tmp, COMPASS_PATH)
    log.info("Interview compass written: %d directions, %d highlights",
             len(compass.suggested_directions), len(compass.chronicle_highlights))
    return COMPASS_PATH


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    compass = generate_compass()
    path = write_compass(compass)
    print(f"Compass: {path}")
    print(f"  Directions: {len(compass.suggested_directions)}")
    print(f"  Chronicle highlights: {len(compass.chronicle_highlights)}")
    print(f"  Open threads: {len(compass.open_threads)}")
    print(f"  Profile gaps: {len(compass.profile_gaps)}")


if __name__ == "__main__":
    main()
