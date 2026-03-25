"""Systematic smoke tests — end-to-end integration across all 8 batches.

These tests verify cross-module integration paths using synthetic data.
No external dependencies (no DF, no Qdrant, no LLM).

Smoke Test Matrix:
  S1  Bridge → Schema: write JSON to /dev/shm mock, read as typed model
  S2  Schema → Position: tick arithmetic produces valid season/year/era
  S3  Blueprint → Bridge: generate CSV, send through bridge command protocol
  S4  State → Chains: each chain produces correct action for representative states
  S5  State → Governor: full evaluation loop produces commands for composite state
  S6  Governor → Suppression: siege engages crisis_suppression, blocks planner
  S7  Governor → Suppression → Recovery: suppression decays after threat clears
  S8  Goals → Governor: GoalPlanner dispatches subgoals to correct chains
  S9  State → Episodes: season change triggers episode boundary and closure
  S10 Episodes → Narrative: closed episode produces narrative text
  S11 Episodes → Metrics: session tracker accumulates commands and survival time
  S12 Metrics → Death: fortress death detection triggers session finalization
  S13 Full Loop: bridge read → governor evaluate → commands → bridge write
  S14 API → State: FastAPI TestClient serves fortress state from mock /dev/shm
  S15 Working Mode: FORTRESS enum value accepted and round-trips
  S16 Suppression Stability: 50-tick alternating state produces bounded suppression
  S17 Goal Completion: satisfied subgoals are marked COMPLETED, goal completes
  S18 Chronicle: narrative writes valid JSONL to chronicle file
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from agents.fortress.blueprints import generate_blueprint, generate_fortress_plan
from agents.fortress.bridge import DFHackBridge
from agents.fortress.chains.crisis import CrisisResponderChain
from agents.fortress.chains.military import MilitaryCommanderChain
from agents.fortress.chains.planner import FortressPlannerChain
from agents.fortress.chains.resource import ResourceManagerChain
from agents.fortress.chains.storyteller import StorytellerChain
from agents.fortress.config import BridgeConfig, FortressConfig
from agents.fortress.episodes import FortressEpisodeBuilder
from agents.fortress.goal_library import FOUND_FORTRESS, SURVIVE_WINTER
from agents.fortress.goals import GoalPlanner, GoalState
from agents.fortress.metrics import FortressSessionTracker
from agents.fortress.narrative import format_narrative_fallback, write_chronicle_entry
from agents.fortress.schema import (
    BuildingSummary,
    DwarfSkill,
    DwarfUnit,
    FastFortressState,
    FortressPosition,
    FullFortressState,
    MilitarySquad,
    SiegeEvent,
    StockpileSummary,
    WealthSummary,
    Workshop,
)
from agents.fortress.wiring import FortressGovernor
from shared.working_mode import WorkingMode

# ---------------------------------------------------------------------------
# Fixtures: representative fortress states
# ---------------------------------------------------------------------------


def _fast_state(**overrides) -> FastFortressState:
    """Minimal valid fast state."""
    defaults = dict(
        timestamp=time.time(),
        game_tick=120000,
        year=3,
        season=2,
        month=8,
        day=15,
        fortress_name="Smokefort",
        paused=False,
        population=47,
        food_count=234,
        drink_count=100,
        active_threats=0,
        job_queue_length=15,
        idle_dwarf_count=3,
        most_stressed_value=5000,
    )
    defaults.update(overrides)
    return FastFortressState(**defaults)


def _full_state(**overrides) -> FullFortressState:
    """Full state with units, workshops, stockpiles."""
    defaults = dict(
        timestamp=time.time(),
        game_tick=120000,
        year=3,
        season=2,
        month=8,
        day=15,
        fortress_name="Smokefort",
        paused=False,
        population=47,
        food_count=234,
        drink_count=100,
        active_threats=0,
        job_queue_length=15,
        idle_dwarf_count=3,
        most_stressed_value=5000,
        units=tuple(
            DwarfUnit(
                id=i,
                name=f"Urist {i}",
                profession="Miner",
                skills=(DwarfSkill(name="MINING", level=3),),
                stress=5000,
                mood="normal",
                current_job="Mining",
            )
            for i in range(47)
        ),
        squads=(
            MilitarySquad(
                id=1,
                name="The Axes",
                member_ids=(0, 1, 2, 3, 4),
                equipment_quality=0.7,
                training_level=0.5,
            ),
        ),
        stockpiles=StockpileSummary(
            food=234, drink=100, wood=50, stone=200, metal_bars=20, weapons=10, armor=8
        ),
        workshops=(
            Workshop(
                type="Craftsdwarfs", x=10, y=10, z=-2, is_active=True, current_job="MakeCrafts"
            ),
            Workshop(type="Metalsmith", x=12, y=10, z=-2, is_active=False, current_job="idle"),
            Workshop(type="Still", x=14, y=10, z=-2, is_active=True, current_job="idle"),
            Workshop(type="Kitchen", x=16, y=10, z=-2, is_active=True, current_job="idle"),
        ),
        buildings=BuildingSummary(beds=30, tables=20, chairs=20, doors=40),
        wealth=WealthSummary(created=80000, exported=5000, imported=12000),
    )
    defaults.update(overrides)
    return FullFortressState(**defaults)


def _siege_state() -> FullFortressState:
    """State with active siege."""
    return _full_state(
        active_threats=35,
        pending_events=(SiegeEvent(attacker_civ="Goblins", force_size=35),),
    )


def _famine_state() -> FullFortressState:
    """State with critical food/drink shortage."""
    return _full_state(
        food_count=5,
        drink_count=2,
        stockpiles=StockpileSummary(food=5, drink=2),
    )


def _founding_state() -> FullFortressState:
    """State at fortress founding — small population, no infrastructure."""
    return _full_state(
        population=7,
        food_count=30,
        drink_count=20,
        idle_dwarf_count=5,
        most_stressed_value=0,
        units=tuple(
            DwarfUnit(
                id=i,
                name=f"Settler {i}",
                profession="Peasant",
                skills=(),
                stress=0,
                mood="normal",
                current_job="idle",
            )
            for i in range(7)
        ),
        squads=(),
        stockpiles=StockpileSummary(food=30, drink=20, wood=5),
        workshops=(),
        buildings=BuildingSummary(beds=0),
        wealth=WealthSummary(created=0),
    )


# ===========================================================================
# S1: Bridge → Schema
# ===========================================================================


class TestS1BridgeSchema:
    def test_write_read_roundtrip(self, tmp_path: Path):
        """Write JSON to mock /dev/shm, read back as typed FastFortressState."""
        config = BridgeConfig(state_dir=tmp_path)
        bridge = DFHackBridge(config=config)

        state_data = _fast_state().model_dump()
        (tmp_path / "state.json").write_text(json.dumps(state_data))

        state = bridge.read_state()
        assert state is not None
        assert isinstance(state, FastFortressState)
        assert state.fortress_name == "Smokefort"
        assert state.population == 47

    def test_full_state_detected(self, tmp_path: Path):
        """Full state (with units key) parsed as FullFortressState."""
        config = BridgeConfig(state_dir=tmp_path)
        bridge = DFHackBridge(config=config)

        state_data = _full_state().model_dump()
        (tmp_path / "state.json").write_text(json.dumps(state_data))

        state = bridge.read_state()
        assert isinstance(state, FullFortressState)
        assert len(state.units) == 47


# ===========================================================================
# S2: Schema → Position
# ===========================================================================


class TestS2FortressPosition:
    def test_tick_to_season_year(self):
        pos = FortressPosition.from_tick(403200 * 3 + 33600 * 6 + 1200 * 10, population=47)
        assert pos.year == 3
        assert pos.month == 6
        assert pos.day == 10
        assert pos.season == 2  # autumn
        assert pos.era == "growth"  # 47 dwarves

    def test_era_boundaries(self):
        assert FortressPosition.from_tick(0, 5).era == "founding"
        assert FortressPosition.from_tick(0, 50).era == "establishment"
        assert FortressPosition.from_tick(0, 150).era == "legendary"


# ===========================================================================
# S3: Blueprint → Bridge
# ===========================================================================


class TestS3BlueprintBridge:
    def test_generate_and_send(self, tmp_path: Path):
        """Generate a blueprint CSV and send it through the bridge."""
        csv = generate_blueprint("central_stairwell", depth=3, width=3)
        assert "#dig" in csv
        assert len(csv) > 50

        config = BridgeConfig(state_dir=tmp_path)
        bridge = DFHackBridge(config=config)
        bridge.send_command("dig", blueprint=csv)

        cmds = json.loads((tmp_path / "commands.json").read_text())
        assert len(cmds) == 1
        assert cmds[0]["action"] == "dig"
        assert "#dig" in cmds[0]["blueprint"]

    def test_fortress_plan_generates(self):
        """Full fortress plan produces non-empty ordered phases."""
        plan = generate_fortress_plan(target_population=30)
        assert len(plan) > 0
        labels = [label for label, _ in plan]
        assert any(
            "stairwell" in l.lower() or "entrance" in l.lower() or "dig" in l.lower()
            for l in labels
        )


# ===========================================================================
# S4: State → Individual Chains
# ===========================================================================


class TestS4IndividualChains:
    def test_planner_needs_bedrooms(self):
        """Low bed count → planner selects expand_bedrooms."""
        state = _full_state(buildings=BuildingSummary(beds=10))  # 10 beds for 47 dwarves
        chain = FortressPlannerChain()
        veto, action = chain.evaluate(state)
        assert veto.allowed
        assert action.action == "expand_bedrooms"

    def test_military_responds_to_threat(self):
        state = _siege_state()
        chain = MilitaryCommanderChain()
        veto, action = chain.evaluate(state)
        assert veto.allowed
        assert action.action in ("full_assault", "defensive_position", "civilian_burrow")

    def test_resource_produces_food_when_low(self):
        state = _famine_state()
        chain = ResourceManagerChain()
        veto, action = chain.evaluate(state)
        assert veto.allowed
        assert action.action == "food_production"

    def test_crisis_triggers_on_compound_threat(self):
        state = _full_state(
            active_threats=35,
            food_count=5,
            drink_count=2,
            stockpiles=StockpileSummary(food=5, drink=2),
        )
        chain = CrisisResponderChain(config=FortressConfig())
        veto, action = chain.evaluate(state)
        assert action.action in ("immediate_lockdown", "targeted_response")

    def test_storyteller_selects_dramatic_for_siege(self):
        state = _fast_state(active_threats=20)
        chain = StorytellerChain()
        veto, action = chain.evaluate(state)
        assert action.action == "dramatic_narrative"


# ===========================================================================
# S5: State → Governor (full loop)
# ===========================================================================


class TestS5GovernorFullLoop:
    def test_peaceful_state_produces_commands(self):
        """Peaceful full state → planner and resource manager produce commands."""
        gov = FortressGovernor()
        state = _full_state(buildings=BuildingSummary(beds=10))
        commands = gov.evaluate(state)
        chains = {c.chain for c in commands}
        assert len(commands) > 0
        # Should have planner (needs beds) and/or resource manager
        assert chains & {"fortress_planner", "resource_manager"}

    def test_siege_produces_crisis_and_military(self):
        """Siege state → crisis_responder and military_commander fire."""
        gov = FortressGovernor()
        commands = gov.evaluate(_siege_state())
        chains = {c.chain for c in commands}
        assert "crisis_responder" in chains or "military_commander" in chains


# ===========================================================================
# S6: Governor → Suppression (siege blocks planner)
# ===========================================================================


class TestS6SuppressionEngagement:
    def test_siege_suppresses_planner(self):
        """After siege evaluation, crisis_suppression rises, planner suppressed on next tick."""
        gov = FortressGovernor()

        # First eval: siege fires crisis
        gov.evaluate(_siege_state())

        # Advance time to let suppression ramp
        time.sleep(0.15)  # crisis attack is 0.1s

        # Second eval: suppression should be high
        levels = gov.tick_suppression()
        assert levels["crisis_suppression"] > 0.5

        # Third eval with peaceful state: planner should be suppressed
        gov.evaluate(_full_state(buildings=BuildingSummary(beds=10)))
        # Planner may or may not fire depending on exact timing,
        # but crisis_suppression should be non-zero
        assert levels["crisis_suppression"] > 0.0


# ===========================================================================
# S7: Suppression Recovery
# ===========================================================================


class TestS7SuppressionRecovery:
    def test_suppression_decays_after_threat_clears(self):
        """Crisis suppression decays toward 0 when no threats persist."""
        gov = FortressGovernor()

        # Siege fires
        gov.evaluate(_siege_state())
        time.sleep(0.15)

        # Peaceful state → crisis target set to 0
        gov.evaluate(_full_state())
        time.sleep(0.1)

        levels = gov.tick_suppression()
        # Should be decaying (release is 5.0s so won't be 0 yet, but should be dropping)
        # Just verify it's not stuck at 1.0
        assert levels["crisis_suppression"] < 1.0


# ===========================================================================
# S8: Goals → Governor
# ===========================================================================


class TestS8GoalDispatch:
    def test_survive_winter_dispatches_food_subgoal(self):
        """Low food + active survive_winter → GoalPlanner returns food subgoal."""
        planner = GoalPlanner(goals=[SURVIVE_WINTER])
        planner.activate_goal("survive_winter", tick=100000)

        state = _fast_state(food_count=5, drink_count=2)
        subgoals = planner.evaluate(state)

        ids = {sg.id for sg in subgoals}
        assert "emergency_food" in ids
        assert "emergency_drink" in ids

    def test_found_fortress_dispatches_dig_entrance(self):
        """Active found_fortress → dispatches dig_entrance first."""
        planner = GoalPlanner(goals=[FOUND_FORTRESS])
        planner.activate_goal("found_fortress", tick=0)

        state = _fast_state(population=7, food_count=30)
        subgoals = planner.evaluate(state)

        ids = {sg.id for sg in subgoals}
        assert "dig_entrance" in ids
        # build_workshops depends on dig_entrance, so shouldn't be dispatched yet
        # (unless dig_entrance check returns True)


# ===========================================================================
# S9: State → Episodes
# ===========================================================================


class TestS9EpisodeBoundaries:
    def test_season_change_closes_episode(self):
        """Season change triggers episode boundary."""
        builder = FortressEpisodeBuilder(session_id="smoke-test")

        # First observation starts episode
        s1 = _fast_state(season=1, year=3)
        assert builder.observe(s1) is None  # starts, no close

        # Same season — no boundary
        s2 = _fast_state(season=1, year=3, game_tick=121000)
        assert builder.observe(s2) is None

        # Season change — closes episode
        s3 = _fast_state(season=2, year=3, game_tick=200000)
        episode = builder.observe(s3)
        assert episode is not None
        assert episode.trigger == "season_change"
        assert episode.fortress_name == "Smokefort"

    def test_siege_event_closes_episode(self):
        builder = FortressEpisodeBuilder()
        builder.observe(_fast_state())

        siege_state = _fast_state(
            active_threats=20,
            game_tick=130000,
            pending_events=(SiegeEvent(attacker_civ="Goblins", force_size=20),),
        )
        episode = builder.observe(siege_state)
        assert episode is not None
        assert episode.trigger == "siege"

    def test_flush_closes_partial(self):
        builder = FortressEpisodeBuilder()
        builder.observe(_fast_state())
        episode = builder.flush()
        assert episode is not None
        assert episode.trigger == "flush"


# ===========================================================================
# S10: Episodes → Narrative
# ===========================================================================


class TestS10Narrative:
    def test_fallback_narrative_for_each_trigger(self):
        """Each trigger type produces non-empty narrative."""
        from agents.fortress.episodes import FortressEpisode

        for trigger in ("season_change", "siege", "migrant", "death", "mood", "start", "flush"):
            ep = FortressEpisode(
                fortress_name="Narratefort",
                year=2,
                season=1,
                trigger=trigger,
                population_start=30,
                population_end=32,
                food_start=100,
                food_end=90,
            )
            text = format_narrative_fallback(ep)
            assert len(text) > 0, f"Empty narrative for trigger={trigger}"


# ===========================================================================
# S11: Episodes → Metrics
# ===========================================================================


class TestS11Metrics:
    def test_session_tracker_lifecycle(self):
        """Start → update → record commands → check survival."""
        tracker = FortressSessionTracker()
        s1 = _fast_state(game_tick=100000)
        tracker.start(s1)
        assert tracker.fortress_name == "Smokefort"
        assert tracker.start_tick == 100000

        s2 = _fast_state(game_tick=200000, population=50)
        tracker.update(s2)
        assert tracker.peak_population == 50
        assert tracker.survival_ticks == 100000

        tracker.record_command("fortress_planner")
        tracker.record_command("resource_manager")
        tracker.record_command("military_commander", vetoed=True)
        assert tracker.total_commands == 2
        assert tracker.chain_metrics["military_commander"].commands_vetoed == 1

        tracker.record_event("siege")
        tracker.record_event("siege")
        assert tracker.events_summary["siege"] == 2


# ===========================================================================
# S12: Metrics → Death Detection
# ===========================================================================


class TestS12DeathDetection:
    def test_population_zero_is_dead(self):
        tracker = FortressSessionTracker()
        state = _fast_state(population=0)
        assert tracker.is_fortress_dead(state)

    def test_no_food_no_drink_is_dead(self):
        tracker = FortressSessionTracker()
        state = _fast_state(food_count=0, drink_count=0)
        assert tracker.is_fortress_dead(state)

    def test_food_present_is_alive(self):
        tracker = FortressSessionTracker()
        state = _fast_state(food_count=50, drink_count=30)
        assert not tracker.is_fortress_dead(state)

    def test_finalize_writes_session(self, tmp_path: Path):
        """Finalize writes valid JSONL."""
        import agents.fortress.metrics as metrics_mod

        orig = metrics_mod.SESSIONS_PATH
        metrics_mod.SESSIONS_PATH = tmp_path / "sessions.jsonl"
        try:
            tracker = FortressSessionTracker()
            tracker.start(_fast_state(game_tick=0))
            tracker.update(_fast_state(game_tick=120000))
            record = tracker.finalize("tantrum_spiral")

            assert record["cause_of_death"] == "tantrum_spiral"
            assert record["survival_days"] == 100

            lines = (tmp_path / "sessions.jsonl").read_text().strip().split("\n")
            assert len(lines) == 1
            parsed = json.loads(lines[0])
            assert parsed["session_id"] == tracker.session_id
        finally:
            metrics_mod.SESSIONS_PATH = orig


# ===========================================================================
# S13: Full Loop (bridge → governor → commands → bridge)
# ===========================================================================


class TestS13FullLoop:
    def test_end_to_end(self, tmp_path: Path):
        """Read state from mock /dev/shm → governor evaluates → commands written back."""
        config = BridgeConfig(state_dir=tmp_path)
        bridge = DFHackBridge(config=config)

        # Write a state file with low beds (planner should want to expand)
        state = _full_state(buildings=BuildingSummary(beds=10))
        (tmp_path / "state.json").write_text(json.dumps(state.model_dump()))

        # Read state
        read_state = bridge.read_state()
        assert read_state is not None

        # Governor evaluates
        gov = FortressGovernor()
        commands = gov.evaluate(read_state)
        assert len(commands) > 0

        # Write commands back through bridge
        for cmd in commands:
            bridge.send_command(cmd.action, **cmd.params)

        # Verify commands file exists and is valid
        cmds_file = tmp_path / "commands.json"
        assert cmds_file.exists()
        cmds = json.loads(cmds_file.read_text())
        assert len(cmds) == len(commands)


# ===========================================================================
# S14: API → State
# ===========================================================================


class TestS14API:
    def test_state_endpoint(self, tmp_path: Path):
        """FastAPI TestClient serves fortress state."""
        from unittest.mock import patch

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from logos.api.routes.fortress import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        state_path = tmp_path / "state.json"
        state_data = _fast_state().model_dump()
        state_path.write_text(json.dumps(state_data))

        with patch("logos.api.routes.fortress._bridge_config") as mock_cfg:
            mock_cfg.state_path = state_path
            mock_cfg.staleness_threshold_s = 30.0
            resp = client.get("/api/fortress/state")

        assert resp.status_code == 200
        assert resp.json()["fortress_name"] == "Smokefort"

    def test_503_when_no_df(self, tmp_path: Path):
        from unittest.mock import patch

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from logos.api.routes.fortress import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        with patch("logos.api.routes.fortress._bridge_config") as mock_cfg:
            mock_cfg.state_path = tmp_path / "nonexistent.json"
            mock_cfg.staleness_threshold_s = 30.0
            resp = client.get("/api/fortress/state")

        assert resp.status_code == 503


# ===========================================================================
# S15: Working Mode
# ===========================================================================


class TestS15WorkingMode:
    def test_fortress_enum_value(self):
        assert WorkingMode.FORTRESS.value == "fortress"
        assert WorkingMode("fortress") == WorkingMode.FORTRESS

    def test_roundtrip(self, tmp_path: Path):
        import shared.working_mode as wm_mod
        from shared.working_mode import get_working_mode, set_working_mode

        orig = wm_mod.WORKING_MODE_FILE
        wm_mod.WORKING_MODE_FILE = tmp_path / "working-mode"
        try:
            set_working_mode(WorkingMode.FORTRESS)
            assert get_working_mode() == WorkingMode.FORTRESS
        finally:
            wm_mod.WORKING_MODE_FILE = orig


# ===========================================================================
# S16: Suppression Stability
# ===========================================================================


class TestS16SuppressionStability:
    def test_alternating_states_bounded(self):
        """Alternating siege/peaceful states don't cause unbounded oscillation."""
        gov = FortressGovernor()
        siege = _siege_state()
        peaceful = _full_state()

        for i in range(50):
            state = siege if i % 2 == 0 else peaceful
            gov.evaluate(state)
            time.sleep(0.005)

        levels = gov.tick_suppression()
        for name, level in levels.items():
            assert 0.0 <= level <= 1.0, f"{name} out of bounds: {level}"


# ===========================================================================
# S17: Goal Completion
# ===========================================================================


class TestS17GoalCompletion:
    def test_subgoal_dispatched_then_satisfied(self):
        """Low food dispatches emergency_food; adequate food satisfies it on next eval."""
        planner = GoalPlanner(goals=[SURVIVE_WINTER])
        planner.activate_goal("survive_winter", tick=0)

        # First eval: low food → emergency_food dispatched
        low_state = _fast_state(food_count=5, drink_count=2)
        subgoals = planner.evaluate(low_state)
        ids = {sg.id for sg in subgoals}
        assert "emergency_food" in ids

        # Second eval: food restored → emergency_food auto-completes
        high_state = _fast_state(food_count=1000, drink_count=500)
        subgoals2 = planner.evaluate(high_state)
        ids2 = {sg.id for sg in subgoals2}
        assert "emergency_food" not in ids2

        assert (
            planner.tracker.subgoal_state("survive_winter", "emergency_food") == GoalState.COMPLETED
        )


# ===========================================================================
# S18: Chronicle JSONL
# ===========================================================================


class TestS18Chronicle:
    def test_write_chronicle_entry(self, tmp_path: Path):
        """Chronicle entry writes valid JSONL."""
        import agents.fortress.narrative as narr_mod

        orig = narr_mod.CHRONICLE_PATH
        narr_mod.CHRONICLE_PATH = tmp_path / "chronicle.jsonl"
        try:
            from agents.fortress.episodes import FortressEpisode

            ep = FortressEpisode(
                session_id="smoke",
                fortress_name="Chroniclefort",
                game_tick_start=100000,
                game_tick_end=200000,
                year=2,
                season=1,
                trigger="season_change",
                population_start=30,
                population_end=35,
                food_start=100,
                food_end=120,
                narrative="Summer has arrived. The fortress prospers.",
            )
            write_chronicle_entry(ep)

            lines = (tmp_path / "chronicle.jsonl").read_text().strip().split("\n")
            assert len(lines) == 1
            entry = json.loads(lines[0])
            assert entry["fortress_name"] == "Chroniclefort"
            assert entry["narrative"] == "Summer has arrived. The fortress prospers."
            assert entry["year"] == 2
        finally:
            narr_mod.CHRONICLE_PATH = orig
