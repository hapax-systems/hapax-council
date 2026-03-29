"""Tests for activity mode detection."""

from agents.hapax_daimonion.activity_mode import classify_activity_mode
from agents.hapax_daimonion.screen_models import GearObservation, WorkspaceAnalysis


def test_coding_mode():
    analysis = WorkspaceAnalysis(
        app="foot",
        context="editing code",
        summary="IDE open.",
        operator_present=True,
        operator_activity="typing",
        operator_attention="screen",
        gear_state=[],
    )
    assert classify_activity_mode(analysis, audio_music=False) == "coding"


def test_production_mode():
    analysis = WorkspaceAnalysis(
        app="foot",
        context="terminal",
        summary="Terminal.",
        operator_present=True,
        operator_activity="using_hardware",
        operator_attention="hardware",
        gear_state=[
            GearObservation(device="MPC", powered=True, display_content="", notes=""),
        ],
    )
    assert classify_activity_mode(analysis, audio_music=True) == "production"


def test_away_mode():
    analysis = WorkspaceAnalysis(
        app="foot",
        context="idle",
        summary="Screen idle.",
        operator_present=False,
        operator_activity="away",
        operator_attention="away",
        gear_state=[],
    )
    assert classify_activity_mode(analysis, audio_music=False) == "away"


def test_meeting_mode():
    analysis = WorkspaceAnalysis(
        app="firefox",
        context="video call",
        summary="Video call in browser.",
        operator_present=True,
        operator_activity="typing",
        operator_attention="screen",
        gear_state=[],
    )
    assert classify_activity_mode(analysis, audio_music=False, audio_speech=True) == "meeting"


def test_research_mode():
    analysis = WorkspaceAnalysis(
        app="firefox",
        context="reading docs",
        summary="Documentation page.",
        operator_present=True,
        operator_activity="reading",
        operator_attention="screen",
        gear_state=[],
    )
    assert classify_activity_mode(analysis, audio_music=False) == "research"
