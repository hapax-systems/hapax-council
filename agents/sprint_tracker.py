"""Sprint tracker agent — vault-native R&D schedule management.

Reads completion signals from /dev/shm/hapax-sprint/completed.jsonl,
updates Obsidian vault measure notes (frontmatter), evaluates decision gates,
computes sprint state, and emits nudges/notifications.

Timer: systemd user timer, every 5 minutes.
Run: uv run python -m agents.sprint_tracker
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

# ── Paths ───────────────────────────────────────────────────────────────

VAULT_DIR = Path.home() / "Documents" / "Personal"
SPRINT_DIR = VAULT_DIR / "20-projects" / "hapax-research" / "sprint"
MEASURES_DIR = SPRINT_DIR / "measures"
GATES_DIR = SPRINT_DIR / "gates"
SPRINTS_DIR = SPRINT_DIR / "sprints"

SHM_DIR = Path("/dev/shm/hapax-sprint")
COMPLETED_FILE = SHM_DIR / "completed.jsonl"
STATE_FILE = SHM_DIR / "state.json"
NUDGE_FILE = SHM_DIR / "nudge.json"

SCHEDULE_START = datetime(2026, 3, 30, tzinfo=UTC)

# ── Frontmatter I/O ────────────────────────────────────────────────────


def _parse_note(path: Path) -> tuple[dict, str]:
    """Parse YAML frontmatter + body from a vault note."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}, ""
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    yaml_text = text[3:end].strip()
    if not yaml_text:
        return {}, text[end + 3 :].lstrip("\n")
    try:
        data = yaml.safe_load(yaml_text)
        if not isinstance(data, dict):
            return {}, text
        return data, text[end + 3 :].lstrip("\n")
    except yaml.YAMLError:
        return {}, text


def _write_frontmatter(path: Path, fm: dict, body: str) -> None:
    """Atomically rewrite a vault note with updated frontmatter."""
    # Preserve key ordering for readability
    yaml_str = yaml.dump(fm, default_flow_style=False, sort_keys=False, allow_unicode=True)
    content = f"---\n{yaml_str}---\n{body}"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.rename(path)


# ── Completion signal I/O ───────────────────────────────────────────────


def _consume_completions() -> list[dict]:
    """Read and truncate the completion signal file."""
    if not COMPLETED_FILE.exists():
        return []
    try:
        lines = COMPLETED_FILE.read_text(encoding="utf-8").strip().splitlines()
        signals = []
        for line in lines:
            try:
                signals.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        # Truncate after reading
        COMPLETED_FILE.write_text("", encoding="utf-8")
        return signals
    except OSError:
        return []


# ── Vault scanning ──────────────────────────────────────────────────────


def _load_measures() -> dict[str, tuple[dict, str, Path]]:
    """Load all measure notes. Returns {id: (frontmatter, body, path)}."""
    measures = {}
    if not MEASURES_DIR.exists():
        return measures
    for p in sorted(MEASURES_DIR.glob("*.md")):
        fm, body = _parse_note(p)
        mid = fm.get("id")
        if mid:
            measures[str(mid)] = (fm, body, p)
    return measures


def _load_gates() -> dict[str, tuple[dict, str, Path]]:
    """Load all gate notes. Returns {id: (frontmatter, body, path)}."""
    gates = {}
    if not GATES_DIR.exists():
        return gates
    for p in sorted(GATES_DIR.glob("*.md")):
        fm, body = _parse_note(p)
        gid = fm.get("id")
        if gid:
            gates[str(gid)] = (fm, body, p)
    return gates


# ── Gate evaluation ─────────────────────────────────────────────────────


def _evaluate_gate_condition(
    condition: str, result_summary: str | None
) -> tuple[bool, float | None]:
    """Evaluate a gate condition against a measure's result_summary.

    Returns (passed, measured_value). Handles simple numeric comparisons
    like 'contradiction_rate < 0.15' or 'r >= 0.1'.
    """
    if not result_summary:
        return False, None

    # Extract numeric value from result summary
    # Expected format: "contradiction_rate: 0.08" or "r = 0.35" or just "0.08"

    numbers = re.findall(r"[-+]?\d*\.?\d+", result_summary)
    if not numbers:
        return False, None

    measured = float(numbers[0])

    # Parse condition: "metric_name < threshold" or "metric_name >= threshold"
    cond_match = re.search(r"([<>]=?)\s*([-+]?\d*\.?\d+)", condition)
    if not cond_match:
        return False, measured

    op, threshold_str = cond_match.group(1), cond_match.group(2)
    threshold = float(threshold_str)

    ops = {
        "<": measured < threshold,
        "<=": measured <= threshold,
        ">": measured > threshold,
        ">=": measured >= threshold,
    }
    return ops.get(op, False), measured


# ── Sprint state computation ────────────────────────────────────────────


def _current_day() -> int:
    """Compute current schedule day (1-indexed) from start date.

    Returns 0 if the sprint hasn't started yet.
    """
    now = datetime.now(tz=UTC)
    delta = now - SCHEDULE_START
    if delta.total_seconds() < 0:
        return 0
    return delta.days + 1


def _compute_state(measures: dict, gates: dict) -> dict:
    """Compute sprint state summary for /dev/shm and session context."""
    by_status = {"pending": 0, "in_progress": 0, "completed": 0, "blocked": 0, "skipped": 0}
    by_sprint: dict[int, dict] = {}
    total_effort = 0.0
    completed_effort = 0.0

    for _mid, (fm, _, _) in measures.items():
        status = fm.get("status", "pending")
        by_status[status] = by_status.get(status, 0) + 1

        sprint = fm.get("sprint", 0)
        if sprint not in by_sprint:
            by_sprint[sprint] = {
                "pending": 0,
                "in_progress": 0,
                "completed": 0,
                "blocked": 0,
                "skipped": 0,
            }
        by_sprint[sprint][status] = by_sprint[sprint].get(status, 0) + 1

        effort = fm.get("effort_hours", 0) or 0
        total_effort += effort
        if status == "completed":
            completed_effort += effort

    # Find current sprint (first sprint with uncompleted work)
    current_sprint = 0
    for s in sorted(by_sprint.keys()):
        counts = by_sprint[s]
        if counts.get("pending", 0) > 0 or counts.get("in_progress", 0) > 0:
            current_sprint = s
            break

    # Find next block (earliest pending measure by day + block)
    next_block = None
    for _mid, (fm, _, _) in sorted(
        measures.items(), key=lambda x: (x[1][0].get("day", 99), x[1][0].get("block", "9999"))
    ):
        if fm.get("status") == "pending":
            next_block = {
                "measure": fm.get("id"),
                "title": fm.get("title"),
                "scheduled": fm.get("block"),
                "day": fm.get("day"),
                "sprint": fm.get("sprint"),
            }
            break

    # Gate summary
    gates_passed = sum(1 for _, (fm, _, _) in gates.items() if fm.get("status") == "passed")
    gates_failed = sum(1 for _, (fm, _, _) in gates.items() if fm.get("status") == "failed")
    gates_pending = sum(1 for _, (fm, _, _) in gates.items() if fm.get("status") == "pending")

    blocking_gate = None
    for gid, (fm, _, _) in gates.items():
        if fm.get("status") == "failed" and not fm.get("acknowledged", False):
            blocking_gate = gid
            break

    return {
        "current_sprint": current_sprint,
        "current_day": _current_day(),
        "measures_completed": by_status.get("completed", 0),
        "measures_total": len(measures),
        "measures_in_progress": by_status.get("in_progress", 0),
        "measures_blocked": by_status.get("blocked", 0),
        "measures_skipped": by_status.get("skipped", 0),
        "measures_pending": by_status.get("pending", 0),
        "effort_completed": round(completed_effort, 1),
        "effort_total": round(total_effort, 1),
        "gates_passed": gates_passed,
        "gates_failed": gates_failed,
        "gates_pending": gates_pending,
        "next_block": next_block,
        "blocking_gate": blocking_gate,
        "by_sprint": {str(k): v for k, v in by_sprint.items()},
        "timestamp": time.time(),
    }


# ── Posterior tracker ───────────────────────────────────────────────────


def _update_posterior_tracker(measures: dict) -> None:
    """Write the running posterior tracker to the vault."""
    # Aggregate posterior gains by model
    models: dict[str, dict] = {}
    for _mid, (fm, _, _) in measures.items():
        model = fm.get("model", "Unknown")
        model_id = fm.get("model_id", 0)
        if model not in models:
            models[model] = {
                "model_id": model_id,
                "gained": 0.0,
                "possible": 0.0,
                "measures": 0,
                "completed": 0,
            }
        gain = fm.get("posterior_gain", 0) or 0
        models[model]["possible"] += gain
        models[model]["measures"] += 1
        if fm.get("status") == "completed":
            models[model]["gained"] += gain
            models[model]["completed"] += 1

    # Pre-schedule baselines
    baselines = {
        "Phenomenological Mapping": 0.58,
        "DMN Continuous Substrate": 0.53,
        "Stimmung": 0.64,
        "Salience / Biased Competition": 0.61,
        "Bayesian Tool Selection": 0.54,
        "Reverie / Bachelard": 0.33,
    }

    lines = ["# Posterior Tracker\n"]
    lines.append(f"**Updated:** {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}\n")
    lines.append("| Model | Baseline | Gained | Current Est. | Possible | Measures |")
    lines.append("|-------|----------|--------|-------------|----------|----------|")

    for model in sorted(models.keys(), key=lambda m: models[m]["model_id"]):
        info = models[model]
        baseline = baselines.get(model, 0.0)
        current = min(baseline + info["gained"], 1.0)
        target = min(baseline + info["possible"], 1.0)
        lines.append(
            f"| {model} | {baseline:.2f} | +{info['gained']:.2f} | "
            f"**{current:.2f}** | {target:.2f} | {info['completed']}/{info['measures']} |"
        )

    tracker_path = SPRINT_DIR / "_posterior-tracker.md"
    tracker_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Sprint summary ──────────────────────────────────────────────────────


def _update_sprint_summary(state: dict, measures: dict) -> None:
    """Write sprint summary notes."""
    SPRINTS_DIR.mkdir(parents=True, exist_ok=True)
    current = state["current_sprint"]
    sprint_measures = {
        mid: fm for mid, (fm, _, _) in measures.items() if fm.get("sprint") == current
    }

    lines = [f"# Sprint {current}\n"]
    lines.append(
        f"**Day:** {state['current_day']} | **Updated:** {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}\n"
    )

    # Status summary
    counts = state.get("by_sprint", {}).get(str(current), {})
    lines.append("## Progress\n")
    lines.append(f"- Completed: {counts.get('completed', 0)}")
    lines.append(f"- In Progress: {counts.get('in_progress', 0)}")
    lines.append(f"- Pending: {counts.get('pending', 0)}")
    lines.append(f"- Blocked: {counts.get('blocked', 0)}")
    lines.append(f"- Skipped: {counts.get('skipped', 0)}")
    lines.append("")

    # Measure list
    lines.append("## Measures\n")
    lines.append("| ID | Title | Status | Completed |")
    lines.append("|----|-------|--------|-----------|")
    for mid in sorted(
        sprint_measures.keys(),
        key=lambda m: (sprint_measures[m].get("day", 99), sprint_measures[m].get("block", "")),
    ):
        fm = sprint_measures[mid]
        completed_at = fm.get("completed_at", "") or ""
        if completed_at:
            completed_at = completed_at[:16]
        lines.append(
            f"| {fm.get('id')} | {fm.get('title')} | {fm.get('status')} | {completed_at} |"
        )

    path = SPRINTS_DIR / f"sprint-{current}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Nudge + notification ────────────────────────────────────────────────


def _emit_gate_nudge(gate_fm: dict) -> None:
    """Write a blocking nudge for a failed gate."""
    nudge = {
        "source_id": f"sprint:{gate_fm['id']}",
        "type": "gate_failure",
        "gate_id": gate_fm["id"],
        "title": f"Gate {gate_fm['id']} FAILED: {gate_fm.get('title', '')}",
        "detail": f"Condition: {gate_fm.get('condition', '')} | Result: {gate_fm.get('result_value', 'N/A')}",
        "downstream_blocked": gate_fm.get("downstream_measures", []),
        "acknowledged": False,
        "timestamp": time.time(),
    }
    SHM_DIR.mkdir(parents=True, exist_ok=True)
    NUDGE_FILE.write_text(json.dumps(nudge, indent=2), encoding="utf-8")

    # Desktop/ntfy notification
    try:
        from agents._notify import send_notification

        send_notification(
            title=f"Sprint Gate {gate_fm['id']} FAILED",
            message=(
                f"{gate_fm.get('title', '')}\n"
                f"Condition: {gate_fm.get('condition', '')}\n"
                f"Measured: {gate_fm.get('result_value', 'N/A')}\n"
                f"Blocked measures: {', '.join(gate_fm.get('downstream_measures', []))}\n"
                f"Acknowledge via nudge_act(source_id='sprint:{gate_fm['id']}')"
            ),
            priority="high",
            tags=["warning"],
        )
    except Exception:
        log.warning("Failed to send gate notification", exc_info=True)


def _clear_nudge_if_acknowledged() -> bool:
    """Check if operator acknowledged a gate nudge. Returns True if cleared.

    Validates the JSON root is a mapping before calling
    ``nudge.get(\"acknowledged\")``. The ``(json.JSONDecodeError, OSError)``
    catch did not cover AttributeError on non-dict roots — a writer
    producing valid JSON whose root is null, a list, a string, or a
    number previously crashed the sprint-tracker tick. Same shape as
    the other recent SHM-read fixes.
    """
    if not NUDGE_FILE.exists():
        return False
    try:
        nudge = json.loads(NUDGE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(nudge, dict):
        return False
    if nudge.get("acknowledged"):
        NUDGE_FILE.unlink(missing_ok=True)
        return True
    return False


# ── Main tick ───────────────────────────────────────────────────────────


def tick() -> bool:
    """Run one sprint tracker cycle. Returns True if any state changed."""
    changed = False

    # Ensure directories exist
    SHM_DIR.mkdir(parents=True, exist_ok=True)

    # Check if vault structure exists
    if not MEASURES_DIR.exists():
        log.info("No measures directory at %s — skipping tick", MEASURES_DIR)
        return False

    # Load state
    measures = _load_measures()
    gates = _load_gates()
    if not measures:
        log.info("No measures found — skipping tick")
        return False

    # Check gate acknowledgments
    if _clear_nudge_if_acknowledged():
        # Find the gate that was acknowledged and mark it
        for gid, (fm, body, path) in gates.items():
            if fm.get("status") == "failed" and not fm.get("acknowledged", False):
                fm["acknowledged"] = True
                _write_frontmatter(path, fm, body)
                log.info("Gate %s acknowledged", gid)
                changed = True
                break

    # Process completion signals
    signals = _consume_completions()
    for signal in signals:
        mid = str(signal.get("measure_id", ""))
        if mid not in measures:
            log.warning("Completion signal for unknown measure: %s", mid)
            continue

        fm, body, path = measures[mid]
        if fm.get("status") in ("completed", "skipped"):
            continue

        fm["status"] = "completed"
        fm["completed_at"] = signal.get("timestamp") or datetime.now(tz=UTC).isoformat()
        if signal.get("result_summary"):
            fm["result_summary"] = signal["result_summary"]
        _write_frontmatter(path, fm, body)
        log.info("Measure %s completed", mid)
        changed = True

        # Unblock downstream measures
        for blocked_id in fm.get("blocks", []):
            blocked_id = str(blocked_id)
            if blocked_id in measures:
                bfm, bbody, bpath = measures[blocked_id]
                if bfm.get("status") == "blocked":
                    # Check if ALL dependencies are completed
                    deps = [str(d) for d in bfm.get("depends_on", [])]
                    all_done = all(
                        measures.get(str(d), ({}, "", Path()))[0].get("status") == "completed"
                        for d in deps
                    )
                    if all_done:
                        bfm["status"] = "pending"
                        _write_frontmatter(bpath, bfm, bbody)
                        log.info("Measure %s unblocked", blocked_id)
                        changed = True

    # Evaluate gates
    for gid, (gfm, gbody, gpath) in gates.items():
        if gfm.get("status") != "pending":
            continue

        trigger_id = str(gfm.get("trigger_measure", ""))
        if trigger_id not in measures:
            continue

        trigger_fm = measures[trigger_id][0]
        if trigger_fm.get("status") != "completed":
            continue

        # Gate's trigger measure is complete — evaluate
        condition = gfm.get("condition", "")
        result_summary = trigger_fm.get("result_summary")
        passed, measured_value = _evaluate_gate_condition(condition, result_summary)

        gfm["evaluated_at"] = datetime.now(tz=UTC).isoformat()
        gfm["result_value"] = measured_value

        if passed:
            gfm["status"] = "passed"
            _write_frontmatter(gpath, gfm, gbody)
            log.info("Gate %s PASSED (measured: %s)", gid, measured_value)
        else:
            gfm["status"] = "failed"
            _write_frontmatter(gpath, gfm, gbody)
            log.info("Gate %s FAILED (measured: %s)", gid, measured_value)

            # Block downstream measures
            for dm_id in gfm.get("downstream_measures", []):
                dm_id = str(dm_id)
                if dm_id in measures:
                    dfm, dbody, dpath = measures[dm_id]
                    if dfm.get("status") in ("pending", "in_progress"):
                        dfm["status"] = "skipped"
                        _write_frontmatter(dpath, dfm, dbody)
                        log.info("Measure %s skipped (gate %s failed)", dm_id, gid)

            # Emit blocking nudge
            _emit_gate_nudge(gfm)

        changed = True

    # Reload after changes
    if changed:
        measures = _load_measures()
        gates = _load_gates()

    # Compute and write state
    state = _compute_state(measures, gates)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.rename(STATE_FILE)

    # Update vault summaries
    _update_posterior_tracker(measures)
    _update_sprint_summary(state, measures)

    # Write sensor state for DMN
    try:
        from agents._sensor_protocol import write_sensor_state

        write_sensor_state(
            "sprint",
            {
                "current_sprint": state["current_sprint"],
                "current_day": state["current_day"],
                "completed": state["measures_completed"],
                "total": state["measures_total"],
                "blocking_gate": state["blocking_gate"],
                "timestamp": state["timestamp"],
            },
        )
    except Exception:
        pass

    if changed:
        log.info(
            "Sprint %d Day %d: %d/%d completed, %d blocked, %d skipped",
            state["current_sprint"],
            state["current_day"],
            state["measures_completed"],
            state["measures_total"],
            state["measures_blocked"],
            state["measures_skipped"],
        )

    return changed


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    tick()
