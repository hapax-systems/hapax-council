"""Unit tests for autonomous_narrative.compose.

Updated to match the 2026-04-27 "no fences" compose rewrite: the
composer no longer drops entire utterances on register violations;
it _sanitizes_ trouble sentences and emits surviving prose. The
empty-chronicle short-circuit was also removed (LLM can compose
from programme/stimmung/activity alone).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest

from agents.hapax_daimonion.autonomous_narrative import compose


@pytest.fixture(autouse=True)
def _bypass_grounding_triage():
    """Bypass the grounding triage in compose tests.

    Compose tests test composition and sanitization logic; the grounding
    triage has its own dedicated test suite. Without this, the triage
    reads real SHM impingement data and produces machine-dependent results.
    """
    with patch(
        "agents.hapax_daimonion.autonomous_narrative.grounding_triage.triage",
        return_value=("emit", 1.0),
    ):
        yield


@dataclass
class _FakeRole:
    value: str


@dataclass
class _FakeProgramme:
    role: Any = None
    narrative_beat: str = ""
    programme_id: str = "prog-x"
    content: Any = None


@dataclass
class _FakeContext:
    programme: Any = None
    stimmung_tone: str = "ambient"
    director_activity: str = "observe"
    chronicle_events: tuple = field(default_factory=tuple)
    triad_continuity: dict[str, Any] = field(default_factory=dict)


def _events(*items: dict) -> tuple[dict, ...]:
    return tuple(items)


# ── empty chronicle behavior ──────────────────────────────────────────────


def test_empty_chronicle_composes_from_other_state() -> None:
    """Post-2026-04-27: empty chronicle no longer short-circuits.

    The LLM can compose from programme/stimmung/activity alone.
    """

    def stub(*, prompt: str, seed: str, **kwargs) -> str:
        return "The AUX5 stimmung envelope holds at 0.72Hz across the 90s observation window."

    ctx = _FakeContext(chronicle_events=())
    out = compose.compose_narrative(ctx, llm_call=stub)
    assert out is not None


# ── prompt construction ───────────────────────────────────────────────────


def test_prompt_includes_seed_state() -> None:
    seen = []

    def stub(*, prompt: str, seed: str, **kwargs) -> str:
        seen.append({"prompt": prompt, "seed": seed})
        return "Signal density rising on AUX5; vinyl side change just landed."

    ctx = _FakeContext(
        programme=_FakeProgramme(role=_FakeRole(value="showcase"), narrative_beat="opening_arc"),
        stimmung_tone="focused",
        director_activity="create",
        chronicle_events=_events(
            {
                "ts": 100.0,
                "source": "audio.vinyl",
                "intent_family": "vinyl.side_change",
                "content": {"narrative": "side B started"},
            }
        ),
    )
    compose.compose_narrative(ctx, llm_call=stub)
    # The output may be sanitized (vinyl terms removed), but the stub ran
    assert seen
    seed = seen[0]["seed"]
    assert "showcase" in seed
    assert "opening_arc" in seed
    assert "focused" in seed
    assert "create" in seed
    assert "side B started" in seed


def test_seed_includes_live_priors_without_treating_them_as_script_authority() -> None:
    from shared.programme import ProgrammeContent

    seen = []

    def stub(*, prompt: str, seed: str, **kwargs) -> str:
        seen.append(seed)
        return "The Alpha ranking uses the visible tier change as its evidence."

    content = ProgrammeContent(
        narrative_beat="rank Alpha",
        delivery_mode="live_prior",
        segment_beats=["rank Alpha with evidence"],
        beat_cards=[
            {
                "beat_index": 0,
                "title": "rank Alpha",
                "prior_summary": "Alpha belongs in S-tier because the evidence is visible.",
                "action_intent_kinds": ["tier_chart"],
                "layout_needs": ["tier_visual"],
            }
        ],
        live_priors=[
            {
                "prior_id": "prepared-script-beat-1",
                "beat_index": 0,
                "text": "Use Alpha as prepared context, then compose the moment live.",
            }
        ],
    )
    ctx = _FakeContext(
        programme=_FakeProgramme(
            role=_FakeRole(value="showcase"),
            narrative_beat="rank Alpha",
            content=content,
        )
    )

    compose.compose_narrative(ctx, llm_call=stub)

    seed = seen[0]
    assert "Prepared live priors" in seed
    assert "compose live, do not read as a script" in seed
    assert "Alpha belongs in S-tier" in seed
    assert "tier_visual" in seed


def test_prompt_includes_open_triad_continuity() -> None:
    seen = []

    def stub(*, prompt: str, seed: str, **kwargs) -> str:
        seen.append(seed)
        return "Signal continuity remains open pending witness."

    ctx = _FakeContext(
        triad_continuity={
            "open_triads": [
                {
                    "triad_id": "triad-1",
                    "status": "open",
                    "obligations": [
                        {
                            "kind": "monitor",
                            "status": "open",
                            "text": "Resolve monitor obligation",
                        }
                    ],
                }
            ],
            "recently_resolved_triads": [],
            "metrics": {"orphan_rate": 1.0},
        }
    )
    compose.compose_narrative(ctx, llm_call=stub)

    assert "Narration continuity ledger" in seen[0]
    assert "Resolve monitor obligation" in seen[0]


def test_prompt_carries_voice_constraints() -> None:
    seen = []

    def stub(*, prompt: str, seed: str, **kwargs) -> str:
        seen.append(prompt)
        return "The AUX5 signal density shifted 0.3dB over the last 90s observation window."

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    compose.compose_narrative(ctx, llm_call=stub)
    prompt = seen[0]
    assert "HELP my grounding" in prompt
    assert "Hapax" in prompt
    assert "1-3 sentences" in prompt
    assert "the AI" in prompt  # diegetic-consistency clause


def test_prompt_includes_operator_referent_guard() -> None:
    seen = []

    def stub(*, prompt: str, seed: str, **kwargs) -> str:
        seen.append(prompt)
        return "The Operator remains outside the frame."

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    compose.compose_narrative(ctx, operator_referent="The Operator", llm_call=stub)
    prompt = seen[0]
    assert "use exactly 'The Operator'" in prompt
    assert "Do not use the legal name" in prompt


# ── register enforcement ──────────────────────────────────────────────────


def test_personification_sentences_drop_to_silence() -> None:
    def stub(*, prompt: str, seed: str, **kwargs) -> str:
        return "Hapax feels the rhythm shifting."

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    out = compose.compose_narrative(ctx, llm_call=stub)
    assert out is None


def test_mixed_operator_referents_drop_to_silence() -> None:
    def stub(*, prompt: str, seed: str, **kwargs) -> str:
        return "The Operator adjusts focus while OTO remains off camera."

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    assert compose.compose_narrative(ctx, operator_referent="The Operator", llm_call=stub) is None


def test_legal_name_env_drops_to_silence(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Fixture Real Person")

    def stub(*, prompt: str, seed: str, **kwargs) -> str:
        return "Fixture Real Person adjusts the workstation lighting."

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    assert compose.compose_narrative(ctx, operator_referent="The Operator", llm_call=stub) is None


def test_commercial_tell_drops_to_silence() -> None:
    def stub(*, prompt: str, seed: str, **kwargs) -> str:
        return "Subscribe for more research-instrument footage."

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    assert compose.compose_narrative(ctx, llm_call=stub) is None


def test_creator_opener_drops_to_silence() -> None:
    def stub(*, prompt: str, seed: str, **kwargs) -> str:
        return "Welcome back to the broadcast — vinyl side B is rolling."

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    assert compose.compose_narrative(ctx, llm_call=stub) is None


def test_neutral_prose_passes_register() -> None:
    def stub(*, prompt: str, seed: str, **kwargs) -> str:
        return "AUX5 signal density rising at 0.4dB per 90s window."

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    out = compose.compose_narrative(ctx, llm_call=stub)
    assert out is not None
    assert "AUX5 signal density" in out


def test_mixed_trouble_and_clean_keeps_clean() -> None:
    """Sanitizer should keep clean sentences when mixed with trouble ones."""

    def stub(*, prompt: str, seed: str, **kwargs) -> str:
        return "AUX5 signal density rising. Subscribe for more footage. The CPAL evaluator holds steady."

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    out = compose.compose_narrative(ctx, llm_call=stub)
    assert out is not None
    assert "AUX5 signal density" in out
    assert "CPAL evaluator" in out
    assert "Subscribe" not in out


# ── LLM failure handling ──────────────────────────────────────────────────


def test_llm_returns_none_yields_silence() -> None:
    def stub(*, prompt: str, seed: str, **kwargs):
        return None

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    assert compose.compose_narrative(ctx, llm_call=stub) is None


def test_llm_raises_yields_silence() -> None:
    def stub(*, prompt: str, seed: str, **kwargs):
        raise RuntimeError("network gone")

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    assert compose.compose_narrative(ctx, llm_call=stub) is None


def test_llm_returns_empty_string_yields_silence() -> None:
    def stub(*, prompt: str, seed: str, **kwargs) -> str:
        return ""

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    assert compose.compose_narrative(ctx, llm_call=stub) is None


def test_chronicle_caps_at_8_unique_events() -> None:
    """Composer caps chronicle bullets at 8 unique events.

    Post-2026-04-27: events are deduplicated by (source, narrative-prefix).
    _summarize_events sorts by ts ascending and takes the first 8 unique,
    so with 20 events we get events 0-7.
    """
    seen = []

    def stub(*, prompt: str, seed: str, **kwargs) -> str:
        seen.append(seed)
        return "The AUX5 signal density increased by 0.2dB."

    events = tuple(
        {
            "ts": float(i),
            "source": f"sensor.{i}",
            "intent_family": f"event.{i}",
            "content": {"narrative": f"narrative-{i}"},
        }
        for i in range(20)
    )
    ctx = _FakeContext(chronicle_events=events)
    compose.compose_narrative(ctx, llm_call=stub)
    seed = seen[0]
    # First 8 events are included (sorted ascending, cap at 8)
    assert "narrative-0" in seed
    assert "narrative-7" in seed
    # 9th and beyond are excluded
    assert "narrative-8" not in seed
    assert "narrative-19" not in seed
