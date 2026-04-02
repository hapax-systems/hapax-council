"""Tests for tool affordance descriptions and recruitment gate."""

from unittest.mock import MagicMock

from agents.hapax_daimonion.tool_affordances import TOOL_AFFORDANCES
from agents.hapax_daimonion.tool_recruitment import ToolRecruitmentGate
from shared.affordance import SelectionCandidate

BANNED_WORDS = ["function", "api", "endpoint", "json", "schema", "qdrant", "shm"]


# --- Task 1: Affordance description tests ---


def test_all_tools_have_affordance_descriptions():
    assert len(TOOL_AFFORDANCES) >= 20


def test_descriptions_are_semantic_not_implementation():
    for name, desc in TOOL_AFFORDANCES:
        desc_lower = desc.lower()
        for banned in BANNED_WORDS:
            assert banned not in desc_lower, f"{name}: mentions '{banned}'"
        word_count = len(desc.split())
        assert 8 <= word_count <= 40, f"{name}: {word_count} words"


def test_no_duplicate_tool_names():
    names = [name for name, _ in TOOL_AFFORDANCES]
    assert len(names) == len(set(names)), "Duplicate tool names in affordances"


def test_descriptions_use_gibson_verbs():
    """At least half the descriptions should start with a Gibson-style verb."""
    gibson_verbs = {
        "observe",
        "retrieve",
        "search",
        "assess",
        "detect",
        "send",
        "generate",
        "direct",
        "configure",
        "shift",
        "navigate",
        "stage",
        "confirm",
        "dismiss",
        "reposition",
        "adjust",
        "trigger",
        "secure",
        "deliver",
        "control",
        "compose",
    }
    verb_count = sum(1 for _, desc in TOOL_AFFORDANCES if desc.split()[0].lower() in gibson_verbs)
    assert verb_count >= len(TOOL_AFFORDANCES) // 2, (
        f"Only {verb_count}/{len(TOOL_AFFORDANCES)} descriptions start with Gibson verbs"
    )


# --- Task 2: Recruitment gate tests ---


def test_utterance_to_impingement():
    gate = ToolRecruitmentGate.__new__(ToolRecruitmentGate)
    gate._pipeline = None
    imp = gate._utterance_to_impingement("what's the weather like today?")
    assert imp.source == "operator.utterance"
    assert "weather" in imp.content.get("narrative", "")
    assert imp.strength == 1.0


def test_recruit_returns_tool_names():
    gate = ToolRecruitmentGate.__new__(ToolRecruitmentGate)
    mock_pipeline = MagicMock()
    mock_pipeline.select.return_value = [
        SelectionCandidate(capability_name="get_weather", combined=0.7),
        SelectionCandidate(capability_name="get_current_time", combined=0.3),
    ]
    gate._pipeline = mock_pipeline
    gate._tool_names = {"get_weather", "get_current_time", "search_documents"}
    recruited = gate.recruit("what's the weather?")
    assert "get_weather" in recruited
    assert "get_current_time" in recruited


def test_recruit_filters_non_tool_candidates():
    """Pipeline may return capabilities that aren't tools — gate filters them."""
    gate = ToolRecruitmentGate.__new__(ToolRecruitmentGate)
    mock_pipeline = MagicMock()
    mock_pipeline.select.return_value = [
        SelectionCandidate(capability_name="get_weather", combined=0.7),
        SelectionCandidate(capability_name="not_a_real_tool", combined=0.5),
    ]
    gate._pipeline = mock_pipeline
    gate._tool_names = {"get_weather", "get_current_time"}
    recruited = gate.recruit("weather check")
    assert "get_weather" in recruited
    assert "not_a_real_tool" not in recruited


def test_record_outcome_calls_pipeline():
    gate = ToolRecruitmentGate.__new__(ToolRecruitmentGate)
    gate._pipeline = MagicMock()
    gate.record_outcome("get_weather", success=True)
    gate._pipeline.record_outcome.assert_called_once_with("get_weather", success=True)


def test_register_tools_counts_successes():
    mock_pipeline = MagicMock()
    mock_pipeline.index_capability.side_effect = [True, False, True]
    count = ToolRecruitmentGate.register_tools(
        mock_pipeline,
        [("tool_a", "desc a"), ("tool_b", "desc b"), ("tool_c", "desc c")],
    )
    assert count == 2
    assert mock_pipeline.index_capability.call_count == 3
