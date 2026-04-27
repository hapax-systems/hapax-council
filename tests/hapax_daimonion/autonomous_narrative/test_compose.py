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


# ── empty chronicle behavior ──────────────────────────────────────────────


def test_empty_chronicle_composes_from_other_state() -> None:
    """Post-2026-04-27: empty chronicle no longer short-circuits.

    The LLM can compose from programme/stimmung/activity alone.
    """

    def stub(*, prompt: str, seed: str) -> str:
        return "Ambient stimmung levels steady across the observation window."

    ctx = _FakeContext(chronicle_events=())
    out = compose.compose_narrative(ctx, llm_call=stub)
    assert out is not None


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
    compose.compose_narrative(ctx, llm_call=stub)
    # The output may be sanitized (vinyl terms removed), but the stub ran
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
        return "Signal density has shifted over the last 90 seconds."

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    compose.compose_narrative(ctx, llm_call=stub)
    prompt = seen[0]
    assert "scientific register" in prompt
    assert "Hapax" in prompt
    assert "1 to 3" in prompt
    assert "the AI" in prompt  # diegetic-consistency clause


# ── register enforcement ──────────────────────────────────────────────────


def test_personification_sentences_pass_when_not_in_trouble_patterns() -> None:
    """Post-2026-04-27: personification verbs (feels, wants, dreams) are
    warned against in the prompt but NOT in _TROUBLE_PATTERNS. Only
    commercial tells, 'the AI', vinyl/CBIP confabulation, and emoji
    are hard-blocked. Personification relies on prompt instruction."""

    def stub(*, prompt: str, seed: str) -> str:
        return "Hapax feels the rhythm shifting."

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    out = compose.compose_narrative(ctx, llm_call=stub)
    # "feels" is NOT hard-blocked — it passes through the sanitizer.
    # The prompt warns against it but doesn't enforce via regex.
    assert out is not None
    assert "feels" in out


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
        return "Signal density rising over the last 90 seconds."

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    out = compose.compose_narrative(ctx, llm_call=stub)
    assert out is not None
    assert "Signal density" in out


def test_mixed_trouble_and_clean_keeps_clean() -> None:
    """Sanitizer should keep clean sentences when mixed with trouble ones."""

    def stub(*, prompt: str, seed: str) -> str:
        return "Signal density rising. Subscribe for more footage. AUX5 levels steady."

    ctx = _FakeContext(
        chronicle_events=_events(
            {"ts": 1.0, "source": "x", "intent_family": "y", "content": {"narrative": "z"}}
        )
    )
    out = compose.compose_narrative(ctx, llm_call=stub)
    assert out is not None
    assert "Signal density" in out
    assert "AUX5" in out
    assert "Subscribe" not in out


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


def test_chronicle_caps_at_8_unique_events() -> None:
    """Composer caps chronicle bullets at 8 unique events.

    Post-2026-04-27: events are deduplicated by (source, narrative-prefix).
    _summarize_events sorts by ts ascending and takes the first 8 unique,
    so with 20 events we get events 0-7.
    """
    seen = []

    def stub(*, prompt: str, seed: str) -> str:
        seen.append(seed)
        return "Signal density up."

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
