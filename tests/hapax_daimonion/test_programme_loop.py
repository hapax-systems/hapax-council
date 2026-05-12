"""Tests for hapax_daimonion.programme_loop — B3 wire-up gap closer."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agents.hapax_daimonion.programme_loop import (
    PROGRAMME_TICK_INTERVAL_S,
    programme_manager_loop,
)


class _FakeDaemon:
    def __init__(self) -> None:
        self._running = True


def _make_decision(trigger_value: str = "none"):
    """Build a BoundaryDecision-shaped object the loop will read."""
    decision = MagicMock()
    decision.trigger.value = trigger_value
    # Default to None for the no-boundary case; tests overwrite to mocks
    # when they want the loop to surface the from/to programme IDs.
    decision.from_programme = None
    decision.to_programme = None
    return decision


def _decision_with_programmes(*, trigger: str, from_id: str | None, to_id: str | None):
    """Decision shape with from/to programme mocks."""
    decision = MagicMock()
    decision.trigger.value = trigger
    decision.from_programme = MagicMock(programme_id=from_id) if from_id else None
    decision.to_programme = MagicMock(programme_id=to_id) if to_id else None
    return decision


# ── Build path ────────────────────────────────────────────────────────


def test_constants_exist() -> None:
    assert PROGRAMME_TICK_INTERVAL_S == 1.0


# ── Loop behavior ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_loop_ticks_manager_until_daemon_stops() -> None:
    """Loop calls manager.tick() at least once before daemon._running flips."""
    daemon = _FakeDaemon()
    fake_manager = MagicMock()
    fake_manager.tick.return_value = _make_decision("none")

    with patch("agents.hapax_daimonion.programme_loop._build_manager", return_value=fake_manager):
        loop_task = asyncio.create_task(programme_manager_loop(daemon))
        # Give the loop one tick window
        await asyncio.sleep(PROGRAMME_TICK_INTERVAL_S + 0.3)
        daemon._running = False
        await asyncio.wait_for(loop_task, timeout=PROGRAMME_TICK_INTERVAL_S + 1.0)

    assert fake_manager.tick.call_count >= 1


@pytest.mark.asyncio
async def test_loop_logs_transition_when_trigger_fires(caplog) -> None:
    """A non-NONE trigger logs an INFO line so operator sees the boundary."""
    import logging as _logging

    daemon = _FakeDaemon()
    fake_manager = MagicMock()
    fake_manager.tick.return_value = _decision_with_programmes(
        trigger="planned", from_id="p_warmup", to_id="p_main"
    )

    with (
        patch("agents.hapax_daimonion.programme_loop._build_manager", return_value=fake_manager),
        caplog.at_level(_logging.INFO, logger="agents.hapax_daimonion.programme_loop"),
    ):
        loop_task = asyncio.create_task(programme_manager_loop(daemon))
        await asyncio.sleep(PROGRAMME_TICK_INTERVAL_S + 0.3)
        daemon._running = False
        await asyncio.wait_for(loop_task, timeout=PROGRAMME_TICK_INTERVAL_S + 1.0)

    transitions = [r for r in caplog.records if "programme transition" in r.message]
    assert transitions, "expected a programme transition log line"


@pytest.mark.asyncio
async def test_loop_swallows_tick_exceptions() -> None:
    """A buggy tick() must not crash the loop — log + continue."""
    daemon = _FakeDaemon()
    fake_manager = MagicMock()
    fake_manager.tick.side_effect = RuntimeError("plan corrupted")

    with patch("agents.hapax_daimonion.programme_loop._build_manager", return_value=fake_manager):
        loop_task = asyncio.create_task(programme_manager_loop(daemon))
        await asyncio.sleep(PROGRAMME_TICK_INTERVAL_S + 0.3)
        daemon._running = False
        await asyncio.wait_for(loop_task, timeout=PROGRAMME_TICK_INTERVAL_S + 1.0)

    # The loop kept ticking despite tick() raising every time
    assert fake_manager.tick.call_count >= 1


@pytest.mark.asyncio
async def test_loop_retries_after_construction_failure(caplog) -> None:
    """A persistent construction failure should warn (throttled) but not spin
    at 100% CPU — the loop sleeps the same interval between retries."""
    import logging as _logging

    daemon = _FakeDaemon()
    construct_calls = {"n": 0}

    def boom():
        construct_calls["n"] += 1
        raise ImportError("module missing")

    with (
        patch("agents.hapax_daimonion.programme_loop._build_manager", side_effect=boom),
        caplog.at_level(_logging.WARNING, logger="agents.hapax_daimonion.programme_loop"),
    ):
        loop_task = asyncio.create_task(programme_manager_loop(daemon))
        await asyncio.sleep(PROGRAMME_TICK_INTERVAL_S + 0.3)
        daemon._running = False
        await asyncio.wait_for(loop_task, timeout=PROGRAMME_TICK_INTERVAL_S + 1.0)

    # Construction was attempted once per tick — at least 1 attempt
    assert construct_calls["n"] >= 1
    warnings = [r for r in caplog.records if "construction failed" in r.message]
    # Throttled to at most one warning in this short window
    assert 1 <= len(warnings) <= 2


@pytest.mark.asyncio
async def test_loop_exits_when_daemon_running_false_at_start() -> None:
    """Daemon already shutting down → loop exits without ticking."""
    daemon = _FakeDaemon()
    daemon._running = False
    fake_manager = MagicMock()
    fake_manager.tick.return_value = _make_decision("none")

    with patch("agents.hapax_daimonion.programme_loop._build_manager", return_value=fake_manager):
        await asyncio.wait_for(programme_manager_loop(daemon), timeout=2.0)

    assert fake_manager.tick.call_count == 0


# ── Auto-plan trigger ──────────────────────────────────────────────────


import time


def test_auto_plan_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.hapax_daimonion.programme_loop import (
        PROGRAMME_AUTO_PLAN_ENV,
        is_auto_plan_enabled,
    )

    monkeypatch.delenv(PROGRAMME_AUTO_PLAN_ENV, raising=False)
    assert is_auto_plan_enabled() is False


def test_auto_plan_enabled_truthy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.hapax_daimonion.programme_loop import (
        PROGRAMME_AUTO_PLAN_ENV,
        is_auto_plan_enabled,
    )

    for v in ("1", "true", "yes", "on", "TRUE", "On"):
        monkeypatch.setenv(PROGRAMME_AUTO_PLAN_ENV, v)
        assert is_auto_plan_enabled() is True


def test_auto_plan_disabled_falsy(monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.hapax_daimonion.programme_loop import (
        PROGRAMME_AUTO_PLAN_ENV,
        is_auto_plan_enabled,
    )

    for v in ("0", "false", "no", "off", "", "maybe"):
        monkeypatch.setenv(PROGRAMME_AUTO_PLAN_ENV, v)
        assert is_auto_plan_enabled() is False


def test_maybe_author_plan_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.hapax_daimonion.programme_loop import (
        PROGRAMME_AUTO_PLAN_ENV,
        _maybe_author_plan,
    )

    monkeypatch.delenv(PROGRAMME_AUTO_PLAN_ENV, raising=False)
    manager = MagicMock()
    planner, ts = _maybe_author_plan(manager, None, 0.0)
    assert planner is None
    assert ts == 0.0
    manager.store.add.assert_not_called()


def test_maybe_author_plan_runs_while_active_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """An ACTIVE programme does NOT block planning — segments pre-assemble
    while the current one runs so content flows continuously."""
    from agents.hapax_daimonion.programme_loop import (
        PROGRAMME_AUTO_PLAN_ENV,
        _maybe_author_plan,
    )
    from shared.programme import ProgrammeStatus

    monkeypatch.setenv(PROGRAMME_AUTO_PLAN_ENV, "1")
    manager = MagicMock()
    active = MagicMock()
    active.status = ProgrammeStatus.ACTIVE
    manager.store.all.return_value = [active]

    fake_plan = MagicMock()
    p1 = MagicMock(programme_id="p_next")
    fake_plan.programmes = [p1]
    fake_planner = MagicMock()
    fake_planner.plan.return_value = fake_plan

    planner, ts = _maybe_author_plan(manager, fake_planner, 0.0)
    assert ts > 0.0  # attempt was made
    fake_planner.plan.assert_called_once()


def test_maybe_author_plan_noop_when_pending_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """PENDING programmes block planning — no double-queueing."""
    from agents.hapax_daimonion.programme_loop import (
        PROGRAMME_AUTO_PLAN_ENV,
        _maybe_author_plan,
    )
    from shared.programme import ProgrammeStatus

    monkeypatch.setenv(PROGRAMME_AUTO_PLAN_ENV, "1")
    manager = MagicMock()
    pending = MagicMock()
    pending.status = ProgrammeStatus.PENDING
    manager.store.all.return_value = [pending]

    planner, ts = _maybe_author_plan(manager, None, 0.0)
    assert ts == 0.0  # no attempt timestamp recorded
    manager.store.add.assert_not_called()


def test_maybe_author_plan_within_cooldown_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.hapax_daimonion.programme_loop import (
        PROGRAMME_AUTO_PLAN_ENV,
        _maybe_author_plan,
    )

    monkeypatch.setenv(PROGRAMME_AUTO_PLAN_ENV, "1")
    manager = MagicMock()
    manager.store.all.return_value = []
    fake_planner = MagicMock()

    # First attempt was 1 second ago; cooldown is 300s by default.
    last_ts = time.monotonic() - 1.0
    planner, ts = _maybe_author_plan(manager, fake_planner, last_ts)

    assert planner is fake_planner
    assert ts == last_ts  # unchanged — cooldown blocked the attempt
    fake_planner.plan.assert_not_called()


def test_maybe_author_plan_writes_and_activates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty store + flag on + cooldown elapsed → planner authors, store writes,
    first programme activates."""
    from agents.hapax_daimonion.programme_loop import (
        PROGRAMME_AUTO_PLAN_ENV,
        _maybe_author_plan,
    )

    monkeypatch.setenv(PROGRAMME_AUTO_PLAN_ENV, "1")
    manager = MagicMock()
    manager.store.all.return_value = []
    fake_plan = MagicMock()
    p1 = MagicMock(programme_id="p1")
    p2 = MagicMock(programme_id="p2")
    fake_plan.programmes = [p1, p2]
    fake_planner = MagicMock()
    fake_planner.plan.return_value = fake_plan

    planner, ts = _maybe_author_plan(manager, fake_planner, 0.0)

    assert ts > 0.0  # cooldown timestamp recorded
    fake_planner.plan.assert_called_once()
    assert manager.store.add.call_count == 2
    manager.store.activate.assert_called_once_with("p1")


def test_maybe_author_plan_handles_planner_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """planner.plan() returning None → cooldown set, no store writes."""
    from agents.hapax_daimonion.programme_loop import (
        PROGRAMME_AUTO_PLAN_ENV,
        _maybe_author_plan,
    )

    monkeypatch.setenv(PROGRAMME_AUTO_PLAN_ENV, "1")
    manager = MagicMock()
    manager.store.all.return_value = []
    fake_planner = MagicMock()
    fake_planner.plan.return_value = None

    planner, ts = _maybe_author_plan(manager, fake_planner, 0.0)

    assert ts > 0.0  # cooldown recorded so we don't retry immediately
    manager.store.add.assert_not_called()
    manager.store.activate.assert_not_called()


def test_maybe_author_plan_handles_planner_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """planner.plan() raising → cooldown set, no store writes, no propagation."""
    from agents.hapax_daimonion.programme_loop import (
        PROGRAMME_AUTO_PLAN_ENV,
        _maybe_author_plan,
    )

    monkeypatch.setenv(PROGRAMME_AUTO_PLAN_ENV, "1")
    manager = MagicMock()
    manager.store.all.return_value = []
    fake_planner = MagicMock()
    fake_planner.plan.side_effect = TimeoutError("LLM gateway down")

    planner, ts = _maybe_author_plan(manager, fake_planner, 0.0)

    assert ts > 0.0
    manager.store.add.assert_not_called()


def test_execute_segment_cue_quarantines_responsible_layout_contract() -> None:
    from agents.hapax_daimonion.programme_loop import _execute_segment_cue_if_allowed

    active = SimpleNamespace(
        programme_id="prog-responsible",
        content=SimpleNamespace(
            hosting_context="hapax_responsible_live",
            beat_layout_intents=[{"beat_id": "hook", "needs": ["evidence_visible"]}],
            segment_cues=["camera.hero tight"],
        ),
    )
    execute_cue = MagicMock()

    assert _execute_segment_cue_if_allowed(active, 0, execute_cue) is False
    execute_cue.assert_not_called()


def test_execute_segment_cue_allows_legacy_non_responsible_content() -> None:
    from agents.hapax_daimonion.programme_loop import _execute_segment_cue_if_allowed

    active = SimpleNamespace(
        programme_id="prog-legacy",
        content=SimpleNamespace(
            hosting_context="non_responsible_static",
            beat_layout_intents=[],
            segment_cues=["legacy safe cue"],
        ),
    )
    execute_cue = MagicMock()

    assert _execute_segment_cue_if_allowed(active, 0, execute_cue) is True
    execute_cue.assert_called_once_with("legacy safe cue")


def test_active_segment_payload_uses_plural_layout_intents_and_authority_ref() -> None:
    from agents.hapax_daimonion.programme_loop import _active_segment_payload

    artifact_ref = {
        "ref": "prepared_artifact:" + "a" * 64,
        "artifact_sha256": "a" * 64,
        "prep_session_id": "prep-1",
        "model_id": "command-r-08-2024-exl3-5.0bpw",
        "authority": "prior_only",
        "projected_authority": "declares_layout_needs_only",
    }
    active = SimpleNamespace(
        programme_id="prog-responsible",
        actual_started_at=123.0,
        planned_duration_s=3600.0,
        topic="topic",
        content=SimpleNamespace(
            narrative_beat="topic",
            declared_topic="declared topic",
            source_uri="https://example.com/source",
            subject="Source Subject",
            segment_beats=["hook: open", "body: show evidence"],
            prepared_artifact_ref=artifact_ref,
            artifact_path_diagnostic="/tmp/prog-responsible.json",
            hosting_context="hapax_responsible_live",
            authority="prior_only",
            source_refs=["vault:source"],
            asset_attributions=[
                {
                    "source_ref": "vault:source",
                    "asset_kind": "vault_note",
                    "title": "Source Note",
                }
            ],
            beat_layout_intents=[
                {
                    "beat_id": "body",
                    "parent_beat_index": 1,
                    "needs": ["evidence_visible"],
                    "expected_effects": ["evidence_on_screen"],
                    "evidence_refs": ["prepared_artifact:" + "a" * 64, "vault:source"],
                    "source_affordances": ["asset:source-card"],
                }
            ],
            layout_decision_contract={"receipt_required": True, "may_command_layout": False},
            runtime_layout_validation={"receipt_required": True},
        ),
    )

    payload = _active_segment_payload(active, "rant", 1)

    assert "current_beat_layout_intents" in payload
    assert "current_beat_layout_intent" not in payload
    assert payload["current_beat_layout_intents"][0]["beat_id"] == "body"
    assert payload["current_beat_layout_intents"][0]["needs"] == ["evidence_visible"]
    assert payload["prepared_artifact_ref"] == artifact_ref
    assert payload["artifact_path_diagnostic"] == "/tmp/prog-responsible.json"
    assert payload["topic"] == "declared topic"
    assert payload["source_uri"] == "https://example.com/source"
    assert payload["subject"] == "Source Subject"
    assert payload["source_refs"] == ["vault:source", "https://example.com/source"]
    assert payload["asset_attributions"][0]["title"] == "Source Note"
    assert payload["ward_profile"] == "argument_crescendo"
    assert payload["ward_accent_role"] == "accent_red"
    assert "layout_decision_contract" not in payload
    assert "runtime_layout_validation" not in payload
    assert "fallback_active" not in payload


def test_prepped_payload_projects_prepared_script_to_live_priors() -> None:
    from agents.hapax_daimonion.programme_loop import (
        _prepped_beat_cards,
        _prepped_live_priors,
    )

    artifact_ref = {"ref": "prepared_artifact:" + "b" * 64}
    payload = {
        "artifact_sha256": "b" * 64,
        "prepared_artifact_ref": artifact_ref,
        "segment_beats": ["rank Alpha with a visible tier decision"],
        "prepared_script": [
            "Place Alpha in S-tier because the ranking makes the evidence legible."
        ],
        "beat_action_intents": [
            {
                "beat_index": 0,
                "intents": [
                    {
                        "kind": "tier_chart",
                        "expected_effect": "tier_chart.place:Alpha:S",
                    }
                ],
            }
        ],
        "beat_layout_intents": [
            {
                "beat_id": "beat-1",
                "beat_index": 0,
                "needs": ["tier_visual"],
                "evidence_refs": ["beat_action_intents[0].intents[0]"],
            }
        ],
    }

    cards = _prepped_beat_cards(payload)
    priors = _prepped_live_priors(payload)

    assert cards[0]["prepared_artifact_ref"] == artifact_ref["ref"]
    assert cards[0]["action_intent_kinds"] == ["tier_chart"]
    assert cards[0]["layout_needs"] == ["tier_visual"]
    assert cards[0]["prior_summary"].startswith("Place Alpha")
    assert priors[0]["prepared_artifact_ref"] == artifact_ref["ref"]
    assert priors[0]["text"].startswith("Place Alpha")


def test_active_segment_payload_includes_live_prior_proposals() -> None:
    from agents.hapax_daimonion.programme_loop import _active_segment_payload
    from shared.programme import ProgrammeContent

    content = ProgrammeContent(
        delivery_mode="live_prior",
        segment_beats=["hook"],
        beat_action_intents=[
            {
                "beat_index": 0,
                "intents": [{"kind": "tier_chart", "expected_effect": "tier_chart.place:X:S"}],
            }
        ],
        beat_cards=[
            {
                "beat_index": 0,
                "title": "hook",
                "prior_summary": "Prepared prior, not script authority.",
                "action_intent_kinds": ["tier_chart"],
                "layout_needs": ["tier_visual"],
            }
        ],
        live_priors=[
            {
                "prior_id": "prepared-script-beat-1",
                "beat_index": 0,
                "text": "Prepared prior excerpt.",
            }
        ],
    )
    active = SimpleNamespace(
        programme_id="prog-live",
        actual_started_at=123.0,
        planned_duration_s=600.0,
        topic="topic",
        content=content,
    )

    payload = _active_segment_payload(active, "tier_list", 0)

    assert payload["delivery_mode"] == "live_prior"
    assert payload["current_beat_action_intents"][0]["beat_index"] == 0
    assert payload["current_beat_cards"][0]["prior_summary"].startswith("Prepared prior")
    assert payload["current_beat_live_priors"][0]["text"] == "Prepared prior excerpt."


def test_active_segment_payload_includes_format_metadata_for_each_segmented_role() -> None:
    from agents.hapax_daimonion.programme_loop import _active_segment_payload
    from shared.programme import SEGMENTED_CONTENT_FORMAT_SPECS, ProgrammeContent

    for role_value, spec in SEGMENTED_CONTENT_FORMAT_SPECS.items():
        content = ProgrammeContent(
            narrative_beat=f"{role_value} on source",
            segment_beats=["hook"],
            source_refs=["vault:source"],
            role_contract={
                "source_packet_refs": ["vault:source"],
                "role_live_bit_mechanic": "source evidence changes the segment object",
            },
        )
        active = SimpleNamespace(
            programme_id=f"prog-{role_value}",
            actual_started_at=123.0,
            planned_duration_s=600.0,
            topic="topic",
            content=content,
        )

        payload = _active_segment_payload(active, role_value, 0)

        assert payload["ward_profile"] == spec.ward_profile
        assert payload["ward_accent_role"] == spec.ward_accent_role
        assert payload["asset_requirements"] == list(spec.asset_requirements)


def test_active_segment_payload_includes_beat_state_metadata() -> None:
    from agents.hapax_daimonion.programme_loop import _active_segment_payload

    active = SimpleNamespace(
        programme_id="prog-beat-test",
        actual_started_at=100.0,
        planned_duration_s=1800.0,
        topic="Beat state test",
        content=SimpleNamespace(
            narrative_beat="Testing beat state",
            declared_topic="Beat state",
            source_uri=None,
            subject=None,
            segment_beats=["hook: open", "body: main content", "close: wrap up"],
            prepared_artifact_ref=None,
            artifact_path_diagnostic=None,
            hosting_context=None,
            authority=None,
            source_refs=[],
            asset_attributions=[],
            beat_layout_intents=[],
            layout_decision_contract=None,
            runtime_layout_validation=None,
        ),
    )

    payload = _active_segment_payload(active, "rant", 1)

    assert payload["current_beat_text"] == "body: main content"
    assert payload["total_beats"] == 3
    assert payload["beat_progress"] == round(2 / 3, 3)
    assert isinstance(payload["beat_elapsed_s"], float)
    assert payload["beat_elapsed_s"] > 0
    assert "updated_at" in payload
    assert payload["updated_at"] > 0


def test_active_segment_payload_beat_state_empty_beats() -> None:
    from agents.hapax_daimonion.programme_loop import _active_segment_payload

    active = SimpleNamespace(
        programme_id="prog-empty",
        actual_started_at=None,
        planned_duration_s=3600.0,
        content=SimpleNamespace(
            narrative_beat="No beats",
            declared_topic=None,
            source_uri=None,
            subject=None,
            segment_beats=[],
            prepared_artifact_ref=None,
            artifact_path_diagnostic=None,
            hosting_context=None,
            authority=None,
            source_refs=[],
            asset_attributions=[],
            beat_layout_intents=[],
            layout_decision_contract=None,
            runtime_layout_validation=None,
        ),
    )

    payload = _active_segment_payload(active, "rant", 0)

    assert payload["current_beat_text"] == ""
    assert payload["total_beats"] == 0
    assert payload["beat_progress"] == 0.0


def test_programme_loop_checks_beat_transition_once_per_tick() -> None:
    from pathlib import Path

    source = Path("agents/hapax_daimonion/programme_loop.py").read_text(encoding="utf-8")

    assert source.count("check_beat_transition(active)") == 1
