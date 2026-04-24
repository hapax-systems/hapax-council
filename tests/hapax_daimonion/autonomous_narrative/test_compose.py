"""Unit tests for autonomous_narrative.compose."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.hapax_daimonion.autonomous_narrative import compose


@dataclass
class _FakeRole:
    value: str


@dataclass
class _FakeProgramme:
    role: Any = None
    narrative_beat: str = ""
    programme_id: str = "prog-x"


@dataclass
class _FakeContext:
    programme: Any = None
    stimmung_tone: str = "ambient"
    director_activity: str = "observe"
    chronicle_events: tuple = field(default_factory=tuple)


def _events(*items: dict) -> tuple[dict, ...]:
    return tuple(items)


# ── empty chronicle → silence ─────────────────────────────────────────────


def test_empty_chronicle_returns_none() -> None:
    """Spec: ground in ≥1 specific observed event. No events → silence."""
    ctx = _FakeContext(chronicle_events=())
    assert compose.compose_narrative(ctx, llm_call=lambda **_: "should not see this") is None


# ── prompt construction ───────────────────────────────────────────────────


def test_prompt_includes_seed_state() -> None:
    seen = []

    def stub(*, prompt: str, seed: str) -> str:
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
    out = compose.compose_narrative(ctx, llm_call=stub)
    assert out is not None
    assert "Signal density" in out
    assert seen
    seed = seen[0]["seed"]
    assert "showcase" in seed
    assert "opening_arc" in seed
    assert "focused" in seed
    assert "create" in seed
    assert "side B started" in seed


def test_prompt_carries_voice_constraints() -> None:
    seen = []

    def stub(*, prompt: str, seed: str) -> str:
        seen.append(prompt)
        return "Hapax recorded a vinyl-side change at AUX5."

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    compose.compose_narrative(ctx, llm_call=stub)
    prompt = seen[0]
    assert "Scientific register" in prompt
    assert "Hapax is a system, not a character" in prompt
    assert "1 to 3 sentences" in prompt
    assert "[silence]" in prompt
    assert "the AI" in prompt  # diegetic-consistency clause


# ── register enforcement ──────────────────────────────────────────────────


def test_personification_output_drops_to_silence() -> None:
    def stub(*, prompt: str, seed: str) -> str:
        return "Hapax feels the rhythm shifting."

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    assert compose.compose_narrative(ctx, llm_call=stub) is None


def test_commercial_tell_drops_to_silence() -> None:
    def stub(*, prompt: str, seed: str) -> str:
        return "Subscribe for more research-instrument footage."

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    assert compose.compose_narrative(ctx, llm_call=stub) is None


def test_creator_opener_drops_to_silence() -> None:
    def stub(*, prompt: str, seed: str) -> str:
        return "Welcome back to the broadcast — vinyl side B is rolling."

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    assert compose.compose_narrative(ctx, llm_call=stub) is None


def test_neutral_prose_passes_register() -> None:
    def stub(*, prompt: str, seed: str) -> str:
        return "Vinyl side change on AUX5; signal density rising over the last 90 seconds."

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    out = compose.compose_narrative(ctx, llm_call=stub)
    assert out is not None
    assert "Vinyl side change" in out


# ── LLM failure handling ──────────────────────────────────────────────────


def test_llm_returns_none_yields_silence() -> None:
    def stub(*, prompt: str, seed: str):
        return None

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    assert compose.compose_narrative(ctx, llm_call=stub) is None


def test_llm_raises_yields_silence() -> None:
    def stub(*, prompt: str, seed: str):
        raise RuntimeError("network gone")

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    assert compose.compose_narrative(ctx, llm_call=stub) is None


def test_llm_returns_empty_string_yields_silence() -> None:
    def stub(*, prompt: str, seed: str) -> str:
        return ""

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    assert compose.compose_narrative(ctx, llm_call=stub) is None


def test_chronicle_truncated_to_recent_events() -> None:
    """Composer caps chronicle bullets at 8 most-recent for prompt size control."""
    seen = []

    def stub(*, prompt: str, seed: str) -> str:
        seen.append(seed)
        return "Vinyl side B started; signal density up."

    events = tuple(
        {
            "ts": float(i),
            "source": "audio",
            "intent_family": f"event.{i}",
            "content": {"narrative": f"narrative-{i}"},
        }
        for i in range(20)
    )
    ctx = _FakeContext(chronicle_events=events)
    compose.compose_narrative(ctx, llm_call=stub)
    seed = seen[0]
    # Should include the LAST 8 events (highest ts), so narrative-19 must
    # be present and narrative-0 must NOT be present.
    assert "narrative-19" in seed
    assert "narrative-0" not in seed
