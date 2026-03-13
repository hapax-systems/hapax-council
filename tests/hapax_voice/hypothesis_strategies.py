"""Composable hypothesis strategies for hapax_voice type system.

Organized by layer (L0–L9). Each layer's strategies compose from layers below,
mirroring the composition ladder's dependency structure.
"""

from __future__ import annotations

from hypothesis import strategies as st

from agents.hapax_voice.governance import (
    FreshnessRequirement,
    FusedContext,
    Veto,
    VetoChain,
    VetoResult,
)
from agents.hapax_voice.primitives import Behavior, Stamped

# ── Shared float strategies ────────────────────────────────────────────

watermarks = st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e9)
small_floats = st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1.0)
safe_text = st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L",)))
default_integers = st.integers()


# ── L0: Stamped[T] ────────────────────────────────────────────────────


@st.composite
def st_stamped(draw, value_strategy=default_integers, watermark_strategy=watermarks):
    """Generate a Stamped[T] with arbitrary value and finite watermark."""
    value = draw(value_strategy)
    wm = draw(watermark_strategy)
    return Stamped(value=value, watermark=wm)


# ── L1: Behavior[T], Event[T] ─────────────────────────────────────────


@st.composite
def st_behavior(draw, value_strategy=default_integers, watermark_strategy=None):
    """Generate a Behavior[T] with initial value and explicit watermark."""
    value = draw(value_strategy)
    wm = draw(
        watermark_strategy
        or st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6)
    )
    return Behavior(value, watermark=wm)


@st.composite
def st_monotonic_timestamps(draw, base=None, count=None):
    """Generate a sorted list of non-decreasing timestamps starting from base."""
    base_wm = draw(
        base or st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6)
    )
    n = draw(count or st.integers(min_value=1, max_value=20))
    deltas = draw(
        st.lists(
            st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
            min_size=n,
            max_size=n,
        )
    )
    timestamps = []
    t = base_wm
    for d in deltas:
        t += d
        timestamps.append(t)
    return base_wm, timestamps


# ── L2: FusedContext, VetoChain, FreshnessGuard ───────────────────────


@st.composite
def st_fused_context(draw, behavior_names=None):
    """Generate a FusedContext with named Stamped samples."""
    names = behavior_names or draw(st.lists(safe_text, min_size=0, max_size=5, unique=True))
    wm_st = st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6)
    samples = {}
    sample_watermarks = []
    for name in names:
        s = draw(st_stamped(value_strategy=small_floats, watermark_strategy=wm_st))
        samples[name] = s
        sample_watermarks.append(s.watermark)
    trigger_time = draw(
        st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e9)
    )
    min_wm = min(sample_watermarks) if sample_watermarks else trigger_time
    return FusedContext(
        trigger_time=trigger_time,
        trigger_value=None,
        samples=samples,
        min_watermark=min_wm,
    )


@st.composite
def st_threshold_veto(draw):
    """Generate a Veto[int] with a random threshold."""
    name = draw(safe_text)
    threshold = draw(st.integers(min_value=-100, max_value=100))
    return Veto(name, predicate=lambda x, t=threshold: x > t)


@st.composite
def st_veto_chain(draw, min_vetoes=0, max_vetoes=5):
    """Generate a VetoChain[int] with random threshold vetoes."""
    n = draw(st.integers(min_value=min_vetoes, max_value=max_vetoes))
    vetoes = [draw(st_threshold_veto()) for _ in range(n)]
    return VetoChain(vetoes)


@st.composite
def st_freshness_requirement(draw):
    """Generate a FreshnessRequirement with random staleness bound."""
    name = draw(safe_text)
    max_staleness = draw(
        st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False)
    )
    return FreshnessRequirement(behavior_name=name, max_staleness_s=max_staleness)


@st.composite
def st_veto_result(draw):
    """Generate a VetoResult."""
    allowed = draw(st.booleans())
    if allowed:
        return VetoResult(allowed=True)
    denied = draw(st.lists(safe_text, min_size=1, max_size=3))
    axioms = draw(st.lists(safe_text, min_size=0, max_size=len(denied)))
    return VetoResult(allowed=False, denied_by=tuple(denied), axiom_ids=tuple(axioms))


# ── L4: Command, Schedule ─────────────────────────────────────────────

from agents.hapax_voice.commands import Command, Schedule  # noqa: E402


@st.composite
def st_command(draw):
    """Generate a Command with arbitrary but valid fields."""
    action = draw(st.text(min_size=1, max_size=20))
    params = draw(st.dictionaries(safe_text, st.integers(), max_size=3))
    trigger_time = draw(watermarks)
    trigger_source = draw(st.text(min_size=0, max_size=20))
    min_wm = draw(watermarks)
    gov = draw(st_veto_result())
    selected_by = draw(safe_text)
    return Command(
        action=action,
        params=params,
        trigger_time=trigger_time,
        trigger_source=trigger_source,
        min_watermark=min_wm,
        governance_result=gov,
        selected_by=selected_by,
    )


@st.composite
def st_schedule(draw, command_strategy=None):
    """Generate a Schedule wrapping a Command."""
    cmd = draw(command_strategy or st_command())
    domain = draw(st.sampled_from(["wall", "beat"]))
    target_time = draw(watermarks)
    wall_time = draw(watermarks)
    tolerance = draw(
        st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False)
    )
    return Schedule(
        command=cmd,
        domain=domain,
        target_time=target_time,
        wall_time=wall_time,
        tolerance_ms=tolerance,
    )


# ── L5: TimelineMapping, SuppressionField ──────────────────────────────

from agents.hapax_voice.timeline import TimelineMapping, TransportState  # noqa: E402


@st.composite
def st_timeline_mapping(draw, playing=None):
    """Generate a TimelineMapping with valid positive tempo."""
    ref_time = draw(st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6))
    ref_beat = draw(st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e4))
    tempo = draw(st.floats(min_value=1.0, max_value=300.0, allow_nan=False, allow_infinity=False))
    if playing is None:
        transport = draw(st.sampled_from(list(TransportState)))
    else:
        transport = TransportState.PLAYING if playing else TransportState.STOPPED
    return TimelineMapping(
        reference_time=ref_time,
        reference_beat=ref_beat,
        tempo=tempo,
        transport=transport,
    )


@st.composite
def st_suppression_config(draw):
    """Generate valid SuppressionField parameters."""
    attack = draw(st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False))
    release = draw(st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False))
    initial = draw(small_floats)
    return attack, release, initial


# ── L7: MC/OBS governance FusedContext ─────────────────────────────────


@st.composite
def st_mc_fused_context(draw):
    """Generate FusedContext with MC-required behavior keys and valid value ranges."""
    wm = draw(st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6))
    trigger_time = draw(
        st.floats(allow_nan=False, allow_infinity=False, min_value=wm, max_value=wm + 100.0)
    )
    mapping = draw(st_timeline_mapping(playing=True))
    samples = {
        "vad_confidence": Stamped(
            draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
            wm,
        ),
        "audio_energy_rms": Stamped(
            draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
            wm,
        ),
        "emotion_arousal": Stamped(
            draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
            wm,
        ),
        "timeline_mapping": Stamped(mapping, wm),
        "conversation_suppression": Stamped(
            draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
            wm,
        ),
    }
    return FusedContext(
        trigger_time=trigger_time, trigger_value=None, samples=samples, min_watermark=wm
    )


# ── L8: EnvironmentState ──────────────────────────────────────────────

from agents.hapax_voice.perception import EnvironmentState  # noqa: E402


@st.composite
def st_environment_state(draw):
    """Generate a valid EnvironmentState for governor testing."""
    return EnvironmentState(
        timestamp=draw(
            st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e9)
        ),
        speech_detected=draw(st.booleans()),
        vad_confidence=draw(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
        ),
        face_count=draw(st.integers(min_value=0, max_value=5)),
        operator_present=draw(st.booleans()),
        activity_mode=draw(
            st.sampled_from(["unknown", "coding", "production", "meeting", "browsing", "idle"])
        ),
        workspace_context="",
    )
