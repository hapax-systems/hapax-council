"""Fortress governor daemon — runtime entrypoint.

Connects the DFHack bridge to the governance loop, wiring episodes,
metrics, goals, creativity, and state exposure for the Logos API.

Usage: uv run python -m agents.fortress
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import time
from pathlib import Path
from typing import Any

from agents.fortress.bridge import DFHackBridge
from agents.fortress.chunks import ChunkCompressor
from agents.fortress.config import FortressConfig
from agents.fortress.creativity_metrics import CreativityMetrics
from agents.fortress.deliberation import run_deliberation
from agents.fortress.episodes import FortressEpisodeBuilder
from agents.fortress.events import EventRouter
from agents.fortress.goal_library import DEFAULT_GOALS
from agents.fortress.goals import GoalPlanner
from agents.fortress.metrics import FortressSessionTracker
from agents.fortress.narrative import format_narrative_fallback, write_chronicle_entry
from agents.fortress.schema import FastFortressState, FortressPosition
from agents.fortress.spatial_memory import SpatialMemoryStore
from agents.fortress.tactical import TacticalContext, encode_tactical
from agents.fortress.trends import TrendEngine
from agents.fortress.wiring import FortressGovernor

log = logging.getLogger(__name__)

STATE_DIR = Path("/dev/shm/hapax-fortress")
GOVERNANCE_FILE = STATE_DIR / "governance.json"
GOALS_FILE = STATE_DIR / "goals.json"
METRICS_FILE = STATE_DIR / "metrics.json"

GOVERNANCE_INTERVAL = 2.0  # seconds
MAINTENANCE_INTERVAL = 30.0
IDLE_POLL_INTERVAL = 5.0


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically via tmp+rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    tmp.rename(path)


class FortressDaemon:
    """Runtime orchestrator connecting bridge, governor, and lifecycle components."""

    def __init__(self, config: FortressConfig | None = None) -> None:
        self._config = config or FortressConfig()
        self._bridge = DFHackBridge(config=self._config.bridge)
        self._governor = FortressGovernor(config=self._config)
        self._episode_builder = FortressEpisodeBuilder()
        self._tracker = FortressSessionTracker()
        self._goal_planner = GoalPlanner(goals=list(DEFAULT_GOALS))
        self._creativity_metrics = CreativityMetrics()
        self._tactical_ctx = TacticalContext()
        self._chunk_compressor = ChunkCompressor()
        self._event_router = EventRouter(planner=self._goal_planner)
        self._trend_engine = TrendEngine()
        self._memory_store = SpatialMemoryStore()
        self._prev_state: FastFortressState | None = None
        self._running = True
        self._cmd_cooldowns: dict[str, float] = {}
        self._recent_decisions: list[str] = []  # last N commands for deliberation context
        self._started = False
        self._last_game_day = -1

        # Impingement cascade integration
        from agents.fortress.capability import FORTRESS_DESCRIPTION, FortressGovernanceCapability

        self._fortress_capability = FortressGovernanceCapability()
        self._dmn_impingement_cursor = 0

        # Affordance pipeline: index fortress capability and register interrupt tokens
        from shared.affordance import CapabilityRecord
        from shared.affordance_pipeline import AffordancePipeline

        self._affordance_pipeline = AffordancePipeline()
        self._affordance_pipeline.index_capability(
            CapabilityRecord(
                name="fortress_governance",
                description=FORTRESS_DESCRIPTION,
                daemon="fortress",
            )
        )
        self._affordance_pipeline.register_interrupt(
            "population_critical", "fortress_governance", "fortress"
        )

    async def run(self) -> None:
        """Run governance + maintenance loops concurrently."""
        log.info("Fortress daemon starting")
        await asyncio.gather(
            self._governance_loop(),
            self._impingement_consumer_loop(),
            self._deliberation_loop(),
            self._maintenance_loop(),
        )

    async def _governance_loop(self) -> None:
        """Main loop: read state -> evaluate -> dispatch -> episodes -> metrics."""
        last_tick = -1
        cycle_count = 0

        while self._running:
            state = self._bridge.read_state()
            if state is None:
                if cycle_count % 10 == 0:
                    log.debug("No state available (DF not running or bridge stopped)")
                # If we haven't started yet, try unpausing (game may be paused,
                # causing state to go stale because bridge only exports on ticks)
                if not self._started and self._bridge._config.state_path.exists():
                    log.info("State stale but file exists — sending unpause")
                    self._bridge.send_command("pause", state=False)
                await asyncio.sleep(IDLE_POLL_INTERVAL)
                cycle_count += 1
                continue

            # First state: initialize session + unpause game
            if not self._started:
                self._start_session(state)
                self._bridge.send_command("pause", state=False)
                log.info("Game unpaused")

            # Skip if game tick unchanged (paused or same state)
            if state.game_tick == last_tick:
                await asyncio.sleep(GOVERNANCE_INTERVAL)
                cycle_count += 1
                continue
            last_tick = state.game_tick

            # Process events through router
            events = self._bridge.extract_events(state)
            interrupts = self._event_router.process_events(
                tuple(events), state, now=state.game_tick
            )

            # Push state to trend engine
            self._trend_engine.push(state)

            # Log INTERRUPT events
            if interrupts:
                for ie in interrupts:
                    log.warning("INTERRUPT: %s", ie.event.type)

            # Governor evaluation
            commands = self._governor.evaluate(state)
            cycle_count += 1

            # Dedup with 30s cooldown: same command can re-fire after window expires
            dedup_window = 30.0
            now_dedup = time.monotonic()
            new_commands = []
            for cmd in commands:
                key = f"{cmd.chain}:{cmd.action}:{cmd.params}"
                last_time = self._cmd_cooldowns.get(key, 0.0)
                if (now_dedup - last_time) >= dedup_window:
                    new_commands.append(cmd)
                    self._cmd_cooldowns[key] = now_dedup
            commands = new_commands

            # Expire resolved events
            self._event_router.expire_events(state)

            # Log every 30s or when NEW commands are produced
            now_mono = time.monotonic()
            if commands or (now_mono - getattr(self, "_last_log_time", 0)) > 30:
                self._last_log_time = now_mono
                log.info(
                    "Tick %d | Pop %d | Food %d | Drink %d | Threats %d | Cmds %d | Total %d",
                    state.game_tick,
                    state.population,
                    state.food_count,
                    state.drink_count,
                    state.active_threats,
                    len(commands),
                    self._tracker.total_commands,
                )

            # Dispatch commands through bridge — tactical encoding
            for cmd in commands:
                tactical_actions = encode_tactical(cmd, state, self._tactical_ctx)
                if tactical_actions:
                    for ta in tactical_actions:
                        action = ta.pop("action")
                        self._bridge.send_command(action, **ta)
                else:
                    # Passthrough: send symbolic command
                    self._bridge.send_command(cmd.action, **cmd.params)
                self._tracker.record_command(cmd.chain)
                self._recent_decisions.append(f"{cmd.chain}: {cmd.action}")
                if len(self._recent_decisions) > 50:
                    self._recent_decisions = self._recent_decisions[-30:]
                self._creativity_metrics.record_action(
                    cmd.chain, has_semantic_ref=(cmd.chain == "creativity")
                )
                log.info("  -> [%s] %s %s", cmd.chain, cmd.action, cmd.params)

            # Log storyteller narrative
            if self._governor._last_story_action is not None:
                log.info("Storyteller: %s", self._governor._last_story_action.action)
                self._governor._last_story_action = None

            # Impingement cascade: handled by _impingement_consumer_loop (reads JSONL)

            # Episode lifecycle
            episode = self._episode_builder.observe(state)
            if episode is not None:
                episode.narrative = format_narrative_fallback(episode)
                write_chronicle_entry(episode)
                self._creativity_metrics.record_episode()
                log.info("Episode closed: %s (%s)", episode.trigger, episode.fortress_name)

            # Track events (use already-extracted events)
            for event in events:
                self._tracker.record_event(event.type)

            # Update metrics
            self._tracker.update(state)
            self._creativity_metrics.update_ticks(state.game_tick)

            # Check death
            if self._tracker.is_fortress_dead(state):
                cause = "depopulation" if state.population == 0 else "starvation"
                self._tracker.finalize(cause)
                log.warning("Fortress died: %s", cause)
                self._running = False
                break

            # Expose state for API
            self._write_governor_state(state)

            await asyncio.sleep(GOVERNANCE_INTERVAL)

    async def _impingement_consumer_loop(self) -> None:
        """Poll DMN impingements and route through affordance pipeline."""
        from shared.impingement import Impingement

        imp_path = Path("/dev/shm/hapax-dmn/impingements.jsonl")

        while self._running:
            try:
                if imp_path.exists():
                    text = imp_path.read_text(encoding="utf-8")
                    lines = text.strip().split("\n") if text.strip() else []

                    new_lines = lines[self._dmn_impingement_cursor :]
                    if new_lines:
                        self._dmn_impingement_cursor = len(lines)

                        for line in new_lines:
                            if not line.strip():
                                continue
                            try:
                                imp = Impingement.model_validate_json(line)
                                candidates = self._affordance_pipeline.select(imp)
                                for c in candidates:
                                    if c.capability_name == "fortress_governance":
                                        self._fortress_capability.activate(imp, c.combined)
                                if candidates:
                                    self._affordance_pipeline.add_inhibition(imp, duration_s=60.0)
                            except Exception:
                                pass
            except Exception:
                log.debug("Impingement consumer error (non-fatal)", exc_info=True)

            await asyncio.sleep(1.0)

    async def _deliberation_loop(self) -> None:
        """Per-game-day LLM deliberation."""
        last_day = -1
        while self._running:
            state = self._bridge.read_state()
            if state is None:
                await asyncio.sleep(5.0)
                continue

            # Fire once per game-day
            if state.day == last_day:
                await asyncio.sleep(2.0)
                continue
            last_day = state.day

            # Skip until session has started (let fast loop stabilize)
            if not self._started:
                await asyncio.sleep(2.0)
                continue

            log.info("Deliberation cycle starting (Day %d, Year %d)", state.day, state.year)

            # Build tool dispatch table
            from agents.fortress.attention import AttentionBudget
            from agents.fortress.observation import (
                check_announcements,
                check_military,
                check_nobles,
                check_stockpile,
                check_work_orders,
                describe_patch_tool,
                examine_dwarf,
                get_situation_chunks,
                observe_region,
                recall_memory,
                scan_threats,
                survey_floor,
            )

            budget = AttentionBudget()
            budget.reset(state.population, state.day)

            dispatch = {
                "check_stockpile": lambda category="food": check_stockpile(
                    state, self._memory_store, budget, category
                ),
                "check_military": lambda: check_military(state, self._memory_store, budget),
                "check_nobles": lambda: check_nobles(state, self._memory_store, budget),
                "check_work_orders": lambda: check_work_orders(state, self._memory_store, budget),
                "scan_threats": lambda: scan_threats(state, self._memory_store, budget),
                "check_announcements": lambda since_tick=0: check_announcements(
                    state, self._memory_store, budget, since_tick
                ),
                "examine_dwarf": lambda unit_id=0: examine_dwarf(
                    state, self._memory_store, budget, unit_id
                ),
                "recall_memory": lambda patch_id="": recall_memory(
                    self._memory_store, patch_id, state.game_tick
                ),
                "get_situation": lambda: get_situation_chunks(
                    self._chunk_compressor, state, self._prev_state
                ),
                "observe_region": lambda patch_id="": observe_region(
                    state, self._memory_store, budget, patch_id
                ),
                "describe_patch": lambda patch_id="": describe_patch_tool(
                    state, self._memory_store, budget, patch_id
                ),
                "survey_floor": lambda z_level=0: survey_floor(
                    state, self._memory_store, budget, z_level
                ),
            }

            # Build recent_events from active events + trend anomalies/projections
            recent_events: list[str] = []
            for ae in self._event_router.active_events:
                recent_events.append(f"[{ae.classification.urgency.value}] {ae.event.type}")
            for anomaly in self._trend_engine.anomalies():
                recent_events.append(f"[TREND] {anomaly}")
            for proj in self._trend_engine.projections():
                recent_events.append(f"[PROJECTION] {proj}")

            # Read DMN buffer for situational enrichment
            dmn_buffer = ""
            try:
                from pathlib import Path

                dmn_path = Path("/dev/shm/hapax-dmn/buffer.txt")
                if dmn_path.exists():
                    dmn_buffer = dmn_path.read_text(encoding="utf-8").strip()
            except OSError:
                pass

            # Consume pending impingements from cascade (fed by _impingement_consumer_loop)
            if self._fortress_capability.has_pending_impingement():
                imp = self._fortress_capability.consume_impingement()
                if imp:
                    recent_events.append(
                        f"[IMPINGEMENT] {imp.content.get('metric', imp.source)} "
                        f"(strength={imp.strength:.2f})"
                    )
                    log.info("Cascade impingement consumed: %s", imp.content)

            try:
                actions = await run_deliberation(
                    state=state,
                    compressor=self._chunk_compressor,
                    prev_state=self._prev_state,
                    config=self._config.deliberation,
                    tool_dispatch=dispatch,
                    recent_events=recent_events,
                    recent_decisions=self._recent_decisions[-20:],
                    dmn_buffer=dmn_buffer,
                )

                for action in actions:
                    act = action.get("action", "")
                    params = {k: v for k, v in action.items() if k != "action"}
                    self._bridge.send_command(act, **params)
                    log.info("  Deliberation action: %s %s", act, params)

            except Exception as exc:
                log.error("Deliberation failed: %s", exc)

            self._prev_state = state

    async def _maintenance_loop(self) -> None:
        """Slow loop: goal timeouts, spatial memory maintenance, cooldown pruning."""
        while self._running:
            await asyncio.sleep(MAINTENANCE_INTERVAL)
            # Prune old cooldown entries (older than 5 minutes)
            now = time.monotonic()
            self._cmd_cooldowns = {k: v for k, v in self._cmd_cooldowns.items() if (now - v) < 300}
            # Spatial memory maintenance
            state = self._bridge.read_state()
            tick = state.game_tick if state else 0
            self._memory_store.consolidate(tick)
            self._memory_store.prune(tick)

    def _start_session(self, state: FastFortressState) -> None:
        """Initialize session components on first state read."""
        self._tracker.start(state)
        self._episode_builder = FortressEpisodeBuilder(session_id=self._tracker.session_id)
        self._started = True

        # Activate founding goal for new fortresses (small population)
        if state.population <= 10:
            self._goal_planner.activate_goal("found_fortress", tick=state.game_tick)
        else:
            self._goal_planner.activate_goal("survive_winter", tick=state.game_tick)

        log.info(
            "Session started: %s (pop=%d, tick=%d)",
            state.fortress_name,
            state.population,
            state.game_tick,
        )

    def _write_governor_state(self, state: FastFortressState) -> None:
        """Write live state to /dev/shm for API consumption."""
        # Governance state
        levels = self._governor.tick_suppression()
        governance = {
            "chains": {
                "fortress_planner": {"active": True, "last_action": None},
                "military_commander": {"active": True, "last_action": None},
                "resource_manager": {"active": True, "last_action": None},
                "crisis_responder": {"active": True, "last_action": None},
                "storyteller": {"active": True, "last_action": None},
                "advisor": {"active": False, "last_action": None},
                "creativity": {"active": True, "last_action": None},
            },
            "suppression": levels,
        }
        _atomic_write(GOVERNANCE_FILE, governance)

        # Goals state
        goals_data: list[dict[str, Any]] = []
        for goal in DEFAULT_GOALS:
            goal_state = self._goal_planner.tracker.goal_state(goal.id)
            subgoals = []
            for sg in goal.subgoals:
                sg_state = self._goal_planner.tracker.subgoal_state(goal.id, sg.id)
                subgoals.append(
                    {
                        "id": sg.id,
                        "description": sg.description,
                        "chain": sg.chain,
                        "state": sg_state.value,
                    }
                )
            goals_data.append(
                {
                    "id": goal.id,
                    "description": goal.description,
                    "priority": goal.priority,
                    "state": goal_state.value,
                    "subgoals": subgoals,
                }
            )
        _atomic_write(GOALS_FILE, {"goals": goals_data})

        # Metrics state
        pos = FortressPosition.from_tick(state.game_tick, state.population)
        metrics_data = {
            "session_id": self._tracker.session_id,
            "fortress_name": self._tracker.fortress_name,
            "survival_days": self._tracker.survival_days,
            "survival_years": round(self._tracker.survival_years, 2),
            "total_commands": self._tracker.total_commands,
            "peak_population": self._tracker.peak_population,
            "era": pos.era,
            "chain_metrics": {
                k: {"issued": v.commands_issued, "vetoed": v.commands_vetoed}
                for k, v in self._tracker.chain_metrics.items()
            },
            "creativity": self._creativity_metrics.to_dict(),
        }
        _atomic_write(METRICS_FILE, metrics_data)

    def stop(self) -> None:
        self._running = False
        # Flush partial episode
        episode = self._episode_builder.flush()
        if episode is not None:
            episode.narrative = format_narrative_fallback(episode)
            write_chronicle_entry(episode)
        # Finalize session if started
        if self._started:
            self._tracker.finalize("shutdown")
        log.info("Fortress daemon stopped")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    daemon = FortressDaemon()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, daemon.stop)

    try:
        await daemon.run()
    finally:
        daemon.stop()


if __name__ == "__main__":
    asyncio.run(main())
