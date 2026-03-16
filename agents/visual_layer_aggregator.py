"""Visual layer signal aggregator — polls cockpit API and perception state.

Standalone async process. Reads signals from the cockpit API and perception
state file, runs the DisplayStateMachine, and writes VisualLayerState
atomically to /dev/shm for the studio compositor to render.

Two cadences:
  Fast (15s): health, GPU, infrastructure
  Slow (60s): nudges, briefing, drift, goals, copilot

Entry point: uv run python -m agents.visual_layer_aggregator
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import httpx

from agents.visual_layer_state import (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    DisplayStateMachine,
    SignalCategory,
    SignalEntry,
    VisualLayerState,
)

log = logging.getLogger("visual_layer_aggregator")

# ── Paths ────────────────────────────────────────────────────────────────────

PERCEPTION_STATE_PATH = Path.home() / ".cache" / "hapax-voice" / "perception-state.json"
OUTPUT_DIR = Path("/dev/shm/hapax-compositor")
OUTPUT_FILE = OUTPUT_DIR / "visual-layer-state.json"

# ── Cadences ─────────────────────────────────────────────────────────────────

FAST_INTERVAL_S = 15.0
SLOW_INTERVAL_S = 60.0

# ── API ──────────────────────────────────────────────────────────────────────

COCKPIT_BASE = os.environ.get("COCKPIT_BASE_URL", "http://127.0.0.1:8051/api")


# ── Signal Mapping ───────────────────────────────────────────────────────────


def map_health(data: dict) -> list[SignalEntry]:
    """Map /api/health response to signals."""
    signals = []
    status = data.get("overall_status", "healthy")
    if status == "healthy":
        return signals

    failed = data.get("failed_checks", [])
    failed_count = data.get("failed", 0)

    if status == "failed" or failed_count >= 3:
        severity = SEVERITY_CRITICAL
    elif status == "degraded":
        severity = SEVERITY_HIGH
    else:
        severity = SEVERITY_MEDIUM

    title = f"System {status}"
    detail = ", ".join(failed[:3]) if failed else f"{failed_count} checks failing"
    signals.append(
        SignalEntry(
            category=SignalCategory.HEALTH_INFRA,
            severity=severity,
            title=title,
            detail=detail,
            source_id="health-overall",
        )
    )
    return signals


def map_gpu(data: dict) -> list[SignalEntry]:
    """Map /api/gpu response to signals."""
    signals = []
    usage_pct = data.get("usage_pct", 0)
    temp = data.get("temperature_c", 0)

    if usage_pct > 90:
        signals.append(
            SignalEntry(
                category=SignalCategory.HEALTH_INFRA,
                severity=SEVERITY_HIGH,
                title=f"VRAM {usage_pct:.0f}%",
                detail=f"{data.get('free_mb', 0)}MB free",
                source_id="gpu-vram",
            )
        )
    elif usage_pct > 80:
        signals.append(
            SignalEntry(
                category=SignalCategory.HEALTH_INFRA,
                severity=SEVERITY_MEDIUM,
                title=f"VRAM {usage_pct:.0f}%",
                source_id="gpu-vram",
            )
        )

    if temp > 85:
        signals.append(
            SignalEntry(
                category=SignalCategory.HEALTH_INFRA,
                severity=SEVERITY_HIGH,
                title=f"GPU {temp}°C",
                source_id="gpu-temp",
            )
        )

    return signals


def map_nudges(data: list[dict]) -> list[SignalEntry]:
    """Map /api/nudges response to signals. Top 3 by priority."""
    signals = []
    for nudge in data[:3]:
        label = nudge.get("priority_label", "low")
        score = nudge.get("priority_score", 0)

        if label == "critical":
            severity = SEVERITY_CRITICAL
        elif label == "high":
            severity = SEVERITY_HIGH
        elif label == "medium":
            severity = SEVERITY_MEDIUM
        else:
            severity = SEVERITY_LOW

        signals.append(
            SignalEntry(
                category=SignalCategory.WORK_TASKS,
                severity=severity,
                title=nudge.get("title", "Nudge"),
                detail=nudge.get("suggested_action", ""),
                source_id=nudge.get("source_id", f"nudge-{score}"),
            )
        )
    return signals


def map_briefing(data: dict) -> list[SignalEntry]:
    """Map /api/briefing response to signals."""
    signals = []
    headline = data.get("headline", "")
    if not headline:
        return signals

    action_items = data.get("action_items", [])
    high_items = [a for a in action_items if a.get("priority") == "high"]

    severity = SEVERITY_MEDIUM if high_items else SEVERITY_LOW
    detail = f"{len(action_items)} items" if action_items else ""

    signals.append(
        SignalEntry(
            category=SignalCategory.CONTEXT_TIME,
            severity=severity,
            title=headline[:60],
            detail=detail,
            source_id="briefing-headline",
        )
    )
    return signals


def map_drift(data: dict) -> list[SignalEntry]:
    """Map /api/drift response to signals."""
    signals = []
    items = data.get("items", [])
    high_items = [i for i in items if i.get("severity") == "high"]

    if high_items:
        signals.append(
            SignalEntry(
                category=SignalCategory.GOVERNANCE,
                severity=SEVERITY_MEDIUM,
                title=f"{len(high_items)} high-drift items",
                detail=high_items[0].get("description", "")[:60] if high_items else "",
                source_id="drift-high",
            )
        )
    return signals


def map_goals(data: dict) -> list[SignalEntry]:
    """Map /api/goals response to signals."""
    signals = []
    stale = data.get("primary_stale", [])
    if stale:
        signals.append(
            SignalEntry(
                category=SignalCategory.WORK_TASKS,
                severity=SEVERITY_LOW,
                title=f"{len(stale)} stale goal{'s' if len(stale) > 1 else ''}",
                detail=stale[0] if stale else "",
                source_id="goals-stale",
            )
        )
    return signals


def map_copilot(data: dict) -> list[SignalEntry]:
    """Map /api/copilot response to signals."""
    signals = []
    message = data.get("message", "")
    if message and len(message) > 10:
        signals.append(
            SignalEntry(
                category=SignalCategory.CONTEXT_TIME,
                severity=SEVERITY_LOW,
                title=message[:60],
                source_id="copilot-msg",
            )
        )
    return signals


def map_perception(data: dict) -> tuple[list[SignalEntry], float, float, bool]:
    """Map perception-state.json to signals + flow/audio/production metadata."""
    signals = []

    flow_score = data.get("flow_score", 0.0)
    audio_energy = data.get("audio_energy_rms", 0.0)
    production = data.get("production_activity", "idle")
    production_active = production not in ("idle", "")

    # Consent phase as governance signal
    consent = data.get("consent_phase", "no_guest")
    if consent not in ("no_guest", ""):
        signals.append(
            SignalEntry(
                category=SignalCategory.GOVERNANCE,
                severity=SEVERITY_MEDIUM if consent == "pending_consent" else SEVERITY_LOW,
                title=f"Consent: {consent.replace('_', ' ')}",
                source_id="consent-phase",
            )
        )

    # Music genre as ambient sensor
    genre = data.get("music_genre", "")
    if genre:
        signals.append(
            SignalEntry(
                category=SignalCategory.AMBIENT_SENSOR,
                severity=0.0,
                title=genre,
                source_id="music-genre",
            )
        )

    return signals, flow_score, audio_energy, production_active


# ── Aggregator ───────────────────────────────────────────────────────────────


class VisualLayerAggregator:
    """Polls cockpit API and perception state, runs state machine, writes output."""

    def __init__(self) -> None:
        self._sm = DisplayStateMachine()
        self._client = httpx.AsyncClient(base_url=COCKPIT_BASE, timeout=5.0)
        self._fast_signals: list[SignalEntry] = []
        self._slow_signals: list[SignalEntry] = []
        self._perception_signals: list[SignalEntry] = []
        self._flow_score: float = 0.0
        self._audio_energy: float = 0.0
        self._production_active: bool = False

    async def _fetch_json(self, path: str) -> dict | list | None:
        """Fetch a cockpit API endpoint. Returns None on any error."""
        try:
            resp = await self._client.get(path)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            log.debug("Failed to fetch %s", path, exc_info=True)
        return None

    async def poll_fast(self) -> None:
        """Poll fast-cadence endpoints (health, GPU)."""
        signals: list[SignalEntry] = []

        health = await self._fetch_json("/health")
        if isinstance(health, dict):
            signals.extend(map_health(health))

        gpu = await self._fetch_json("/gpu")
        if isinstance(gpu, dict):
            signals.extend(map_gpu(gpu))

        self._fast_signals = signals

    async def poll_slow(self) -> None:
        """Poll slow-cadence endpoints (nudges, briefing, drift, goals, copilot)."""
        signals: list[SignalEntry] = []

        nudges = await self._fetch_json("/nudges")
        if isinstance(nudges, list):
            signals.extend(map_nudges(nudges))

        briefing = await self._fetch_json("/briefing")
        if isinstance(briefing, dict):
            signals.extend(map_briefing(briefing))

        drift = await self._fetch_json("/drift")
        if isinstance(drift, dict):
            signals.extend(map_drift(drift))

        goals = await self._fetch_json("/goals")
        if isinstance(goals, dict):
            signals.extend(map_goals(goals))

        copilot = await self._fetch_json("/copilot")
        if isinstance(copilot, dict):
            signals.extend(map_copilot(copilot))

        self._slow_signals = signals

    def poll_perception(self) -> None:
        """Read perception-state.json (local file, no HTTP)."""
        try:
            data = json.loads(PERCEPTION_STATE_PATH.read_text())
            signals, flow, audio, prod = map_perception(data)
            self._perception_signals = signals
            self._flow_score = flow
            self._audio_energy = audio
            self._production_active = prod
        except (FileNotFoundError, json.JSONDecodeError):
            pass  # perception daemon may not be running

    def compute_and_write(self) -> VisualLayerState:
        """Run state machine and write output atomically."""
        all_signals = self._fast_signals + self._slow_signals + self._perception_signals

        state = self._sm.tick(
            signals=all_signals,
            flow_score=self._flow_score,
            audio_energy=self._audio_energy,
            production_active=self._production_active,
        )

        # Atomic write
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            tmp = OUTPUT_FILE.with_suffix(".tmp")
            tmp.write_text(state.model_dump_json(), encoding="utf-8")
            tmp.rename(OUTPUT_FILE)
        except OSError:
            log.debug("Failed to write visual layer state", exc_info=True)

        return state

    async def run(self) -> None:
        """Main loop: dual-cadence polling."""
        log.info("Visual layer aggregator starting")
        last_slow = 0.0

        while True:
            now = time.monotonic()

            # Always: read perception state (local file, fast)
            self.poll_perception()

            # Fast cadence: health, GPU
            await self.poll_fast()

            # Slow cadence: nudges, briefing, drift, goals
            if now - last_slow >= SLOW_INTERVAL_S:
                await self.poll_slow()
                last_slow = now

            # Compute and write
            state = self.compute_and_write()
            log.debug(
                "State: %s, signals: %d, flow: %.2f",
                state.display_state,
                sum(len(v) for v in state.signals.values()),
                self._flow_score,
            )

            await asyncio.sleep(FAST_INTERVAL_S)

    async def close(self) -> None:
        await self._client.aclose()


# ── Entry Point ──────────────────────────────────────────────────────────────


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    agg = VisualLayerAggregator()
    try:
        await agg.run()
    finally:
        await agg.close()


if __name__ == "__main__":
    asyncio.run(main())
