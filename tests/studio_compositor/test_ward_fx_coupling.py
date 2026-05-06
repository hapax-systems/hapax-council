"""Ward↔FX bidirectional coupling tests.

HOMAGE Phase 6 Layer 5. Covers:
* Publishing a WardEvent fires the expected shader-param updates in
  uniforms.json.
* Publishing an FXEvent fires the expected ward-property updates.
* Ring-buffer JSONL observability writes atomically.
* Latency histogram populated on each coupling event.
* Domain → preset-family mapping respects the operator-tunable table.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_bus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Reset the module singleton + redirect the JSONL sink per test."""
    # Point the bus JSONL + reactor SHM sinks at tmp_path so tests never
    # touch /dev/shm. Reset the singleton so each test constructs a
    # fresh bus with the overridden path.
    monkeypatch.setenv("HAPAX_WARD_FX_JSONL_PATH", str(tmp_path / "events.jsonl"))

    from shared import ward_fx_bus

    ward_fx_bus.reset_bus_for_testing()

    yield tmp_path

    ward_fx_bus.reset_bus_for_testing()


@pytest.fixture
def uniforms_path(tmp_path: Path) -> Path:
    return tmp_path / "uniforms.json"


@pytest.fixture
def substrate_hint_path(tmp_path: Path) -> Path:
    return tmp_path / "homage-substrate-package.json"


@pytest.fixture
def recent_recruitment_path(tmp_path: Path) -> Path:
    return tmp_path / "recent-recruitment.json"


@pytest.fixture
def ward_properties_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect the ward-properties SHM file to tmp_path."""
    from agents.studio_compositor import ward_properties

    override = tmp_path / "ward-properties.json"
    monkeypatch.setattr(ward_properties, "WARD_PROPERTIES_PATH", override)
    ward_properties.clear_ward_properties_cache()
    yield override
    ward_properties.clear_ward_properties_cache()


class TestWardEventToFxChain:
    """Direction 1: ward FSM events → FX chain reactions."""

    def test_entering_flashes_bloom_and_chromatic(
        self, uniforms_path, substrate_hint_path, recent_recruitment_path
    ):
        from agents.studio_compositor.fx_chain_ward_reactor import WardFxReactor
        from shared.ward_fx_bus import WardEvent, get_bus

        reactor = WardFxReactor(
            uniforms_path=uniforms_path,
            substrate_hint_path=substrate_hint_path,
            recent_recruitment_path=recent_recruitment_path,
        )
        reactor.connect()

        event = WardEvent(
            ward_id="chat_ambient",
            transition="ABSENT_TO_ENTERING",
            domain="communication",
            intensity=1.0,
        )
        get_bus().publish_ward(event)

        assert uniforms_path.exists()
        data = json.loads(uniforms_path.read_text())
        assert data["signal.ward_fx_bloom_boost"] > 0.0
        assert data["signal.ward_fx_chromatic_boost"] > 0.0
        assert "signal.ward_fx_pulse_started_at" in data
        assert "signal.ward_fx_pulse_duration_s" in data

    def test_entering_biases_preset_family_by_domain(
        self, uniforms_path, substrate_hint_path, recent_recruitment_path
    ):
        """Token-domain ward ENTERING → ``glitch-dense`` family bias."""
        from agents.studio_compositor.fx_chain_ward_reactor import WardFxReactor
        from shared.ward_fx_bus import WardEvent, get_bus

        reactor = WardFxReactor(
            uniforms_path=uniforms_path,
            substrate_hint_path=substrate_hint_path,
            recent_recruitment_path=recent_recruitment_path,
        )
        reactor.connect()

        event = WardEvent(
            ward_id="token_pole",
            transition="ABSENT_TO_ENTERING",
            domain="token",
            intensity=0.8,
        )
        get_bus().publish_ward(event)

        payload = json.loads(recent_recruitment_path.read_text())
        assert payload["family"] == "glitch-dense"
        assert payload["source"] == "ward_fx_reactor"
        assert payload["domain"] == "token"

    def test_emphasized_boosts_temporal_and_spectral(
        self, uniforms_path, substrate_hint_path, recent_recruitment_path
    ):
        from agents.studio_compositor.fx_chain_ward_reactor import WardFxReactor
        from shared.ward_fx_bus import WardEvent, get_bus

        reactor = WardFxReactor(
            uniforms_path=uniforms_path,
            substrate_hint_path=substrate_hint_path,
            recent_recruitment_path=recent_recruitment_path,
        )
        reactor.connect()

        event = WardEvent(
            ward_id="pressure_gauge",
            transition="HOLD_TO_EMPHASIZED",
            domain="presence",
            intensity=1.0,
        )
        get_bus().publish_ward(event)

        data = json.loads(uniforms_path.read_text())
        assert data["signal.ward_fx_temporal_boost"] > 0.0
        assert data["signal.ward_fx_spectral_boost"] > 0.0

    def test_exiting_decays_modulation(
        self, uniforms_path, substrate_hint_path, recent_recruitment_path
    ):
        """EXITING transition zeroes the modulation keys."""
        from agents.studio_compositor.fx_chain_ward_reactor import WardFxReactor
        from shared.ward_fx_bus import WardEvent, get_bus

        # Pre-populate a non-zero state from a prior ENTERING.
        uniforms_path.parent.mkdir(parents=True, exist_ok=True)
        uniforms_path.write_text(
            json.dumps(
                {
                    "signal.ward_fx_bloom_boost": 0.25,
                    "signal.ward_fx_chromatic_boost": 0.15,
                }
            )
        )

        reactor = WardFxReactor(
            uniforms_path=uniforms_path,
            substrate_hint_path=substrate_hint_path,
            recent_recruitment_path=recent_recruitment_path,
        )
        reactor.connect()

        event = WardEvent(
            ward_id="chat_ambient",
            transition="EMPHASIZED_TO_EXITING",
            domain="communication",
            intensity=1.0,
        )
        get_bus().publish_ward(event)

        data = json.loads(uniforms_path.read_text())
        assert data["signal.ward_fx_bloom_boost"] == 0.0
        assert data["signal.ward_fx_chromatic_boost"] == 0.0
        assert data["signal.ward_fx_temporal_boost"] == 0.0
        assert data["signal.ward_fx_spectral_boost"] == 0.0

    def test_entering_writes_reverie_intensity_boost(
        self, uniforms_path, substrate_hint_path, recent_recruitment_path
    ):
        from agents.studio_compositor.fx_chain_ward_reactor import WardFxReactor
        from shared.ward_fx_bus import WardEvent, get_bus

        # Seed the substrate hint as if the choreographer had already published.
        substrate_hint_path.parent.mkdir(parents=True, exist_ok=True)
        substrate_hint_path.write_text(
            json.dumps(
                {
                    "package": "bitchx",
                    "palette_accent_hue_deg": 180.0,
                    "substrate_source_ids": ["reverie"],
                }
            )
        )

        reactor = WardFxReactor(
            uniforms_path=uniforms_path,
            substrate_hint_path=substrate_hint_path,
            recent_recruitment_path=recent_recruitment_path,
        )
        reactor.connect()

        event = WardEvent(
            ward_id="token_pole",
            transition="ABSENT_TO_ENTERING",
            domain="token",
            intensity=1.0,
        )
        get_bus().publish_ward(event)

        payload = json.loads(substrate_hint_path.read_text())
        assert payload["package"] == "bitchx"  # preserved
        assert payload["reverie_intensity_boost"] > 0.0
        assert payload["reverie_boost_domain"] == "token"


class TestFxEventToWardProperties:
    """Direction 2: FX chain events → ward property pulses/bumps."""

    def test_preset_family_change_pulses_all_wards(
        self,
        uniforms_path,
        substrate_hint_path,
        recent_recruitment_path,
        ward_properties_isolated,
    ):
        from agents.studio_compositor import ward_properties
        from agents.studio_compositor.fx_chain_ward_reactor import WardFxReactor
        from shared.ward_fx_bus import FXEvent, get_bus

        reactor = WardFxReactor(
            uniforms_path=uniforms_path,
            substrate_hint_path=substrate_hint_path,
            recent_recruitment_path=recent_recruitment_path,
        )
        reactor.connect()

        get_bus().publish_fx(FXEvent(kind="preset_family_change", preset_family="audio-reactive"))

        # Force cache refresh then inspect a representative ward.
        ward_properties.clear_ward_properties_cache()
        props = ward_properties.get_specific_ward_properties("chat_ambient")
        assert props is not None
        assert props.border_pulse_hz > 0.0

        props2 = ward_properties.get_specific_ward_properties("token_pole")
        assert props2 is not None
        assert props2.border_pulse_hz > 0.0

    def test_audio_kick_onset_bumps_only_audio_reactive_wards(
        self,
        uniforms_path,
        substrate_hint_path,
        recent_recruitment_path,
        ward_properties_isolated,
    ):
        from agents.studio_compositor import ward_properties
        from agents.studio_compositor.fx_chain_ward_reactor import WardFxReactor
        from shared.ward_fx_bus import FXEvent, get_bus

        reactor = WardFxReactor(
            uniforms_path=uniforms_path,
            substrate_hint_path=substrate_hint_path,
            recent_recruitment_path=recent_recruitment_path,
        )
        reactor.connect()

        get_bus().publish_fx(FXEvent(kind="audio_kick_onset"))

        ward_properties.clear_ward_properties_cache()
        pressure = ward_properties.get_specific_ward_properties("pressure_gauge")
        assert pressure is not None
        assert pressure.scale_bump_pct > 0.0

        # Non-audio-reactive ward remains unset.
        chat = ward_properties.get_specific_ward_properties("chat_ambient")
        assert chat is None or chat.scale_bump_pct == 0.0

    def test_chain_swap_bumps_token_pole_and_variety_log(
        self,
        uniforms_path,
        substrate_hint_path,
        recent_recruitment_path,
        ward_properties_isolated,
    ):
        from agents.studio_compositor import ward_properties
        from agents.studio_compositor.fx_chain_ward_reactor import WardFxReactor
        from shared.ward_fx_bus import FXEvent, get_bus

        reactor = WardFxReactor(
            uniforms_path=uniforms_path,
            substrate_hint_path=substrate_hint_path,
            recent_recruitment_path=recent_recruitment_path,
        )
        reactor.connect()

        get_bus().publish_fx(FXEvent(kind="chain_swap"))

        ward_properties.clear_ward_properties_cache()
        for ward_id in ("token_pole", "activity_variety_log"):
            props = ward_properties.get_specific_ward_properties(ward_id)
            assert props is not None
            assert props.scale > 1.0, ward_id

    def test_intensity_spike_pulses_audio_reactive_wards(
        self,
        uniforms_path,
        substrate_hint_path,
        recent_recruitment_path,
        ward_properties_isolated,
    ):
        from agents.studio_compositor import ward_properties
        from agents.studio_compositor.fx_chain_ward_reactor import WardFxReactor
        from shared.ward_fx_bus import FXEvent, get_bus

        reactor = WardFxReactor(
            uniforms_path=uniforms_path,
            substrate_hint_path=substrate_hint_path,
            recent_recruitment_path=recent_recruitment_path,
        )
        reactor.connect()

        get_bus().publish_fx(FXEvent(kind="intensity_spike"))

        ward_properties.clear_ward_properties_cache()
        # HARDM retired 2026-04-23; pressure_gauge substitutes as the
        # audio-reactive ward asserted to pulse on intensity_spike.
        pressure = ward_properties.get_specific_ward_properties("pressure_gauge")
        assert pressure is not None
        assert pressure.border_pulse_hz > 0.0


class TestJsonlObservability:
    def test_ring_buffer_writes_atomically_on_each_publish(self, isolated_bus):
        from shared.ward_fx_bus import FXEvent, WardEvent, get_bus

        jsonl_path = isolated_bus / "events.jsonl"
        bus = get_bus()

        bus.publish_ward(
            WardEvent(
                ward_id="token_pole",
                transition="ABSENT_TO_ENTERING",
                domain="token",
                intensity=0.9,
            )
        )
        bus.publish_fx(FXEvent(kind="preset_family_change", preset_family="glitch-dense"))
        bus.publish_fx(FXEvent(kind="audio_kick_onset"))

        assert jsonl_path.exists()
        lines = [line for line in jsonl_path.read_text().splitlines() if line.strip()]
        assert len(lines) == 3
        first = json.loads(lines[0])
        assert first["kind"] == "ward"
        assert first["data"]["ward_id"] == "token_pole"
        assert first["data"]["domain"] == "token"

        second = json.loads(lines[1])
        assert second["kind"] == "fx"
        assert second["data"]["preset_family"] == "glitch-dense"

        third = json.loads(lines[2])
        assert third["kind"] == "fx"
        assert third["data"]["kind"] == "audio_kick_onset"

    def test_ring_buffer_capped_at_capacity(self, isolated_bus):
        from shared import ward_fx_bus
        from shared.ward_fx_bus import FXEvent, get_bus

        bus = get_bus()
        for _ in range(ward_fx_bus._RING_BUFFER_CAPACITY + 20):
            bus.publish_fx(FXEvent(kind="audio_kick_onset"))

        recent = bus.recent()
        assert len(recent) == ward_fx_bus._RING_BUFFER_CAPACITY


class TestLatencyHistogram:
    def test_latency_observed_for_each_ward_event(
        self, uniforms_path, substrate_hint_path, recent_recruitment_path
    ):
        from agents.studio_compositor import metrics
        from agents.studio_compositor.fx_chain_ward_reactor import WardFxReactor
        from shared.ward_fx_bus import WardEvent, get_bus

        if metrics.HAPAX_WARD_FX_LATENCY_SECONDS is None:
            pytest.skip("prometheus_client unavailable — histogram not registered")

        reactor = WardFxReactor(
            uniforms_path=uniforms_path,
            substrate_hint_path=substrate_hint_path,
            recent_recruitment_path=recent_recruitment_path,
        )
        reactor.connect()

        # Fabricate a small event-age so the histogram sees a real value.
        event = WardEvent(
            ward_id="token_pole",
            transition="ABSENT_TO_ENTERING",
            domain="token",
            intensity=1.0,
            ts=time.monotonic() - 0.002,
        )
        get_bus().publish_ward(event)

        hist = metrics.HAPAX_WARD_FX_LATENCY_SECONDS.labels(direction="ward_to_fx")
        # prometheus_client Histogram exposes ``_sum`` + ``_count`` via
        # ``_sum.get()`` on the internal storage; cross-version-safe
        # inspection is through ``collect()``.
        samples = _collect_samples(hist)
        assert samples["count"] >= 1
        assert samples["sum"] >= 0.0

    def test_latency_observed_for_each_fx_event(
        self, uniforms_path, substrate_hint_path, recent_recruitment_path
    ):
        from agents.studio_compositor import metrics
        from agents.studio_compositor.fx_chain_ward_reactor import WardFxReactor
        from shared.ward_fx_bus import FXEvent, get_bus

        if metrics.HAPAX_WARD_FX_LATENCY_SECONDS is None:
            pytest.skip("prometheus_client unavailable — histogram not registered")

        reactor = WardFxReactor(
            uniforms_path=uniforms_path,
            substrate_hint_path=substrate_hint_path,
            recent_recruitment_path=recent_recruitment_path,
        )
        reactor.connect()

        get_bus().publish_fx(FXEvent(kind="audio_kick_onset", ts=time.monotonic() - 0.001))

        hist = metrics.HAPAX_WARD_FX_LATENCY_SECONDS.labels(direction="fx_to_ward")
        samples = _collect_samples(hist)
        assert samples["count"] >= 1


class TestDomainPresetFamilyMapping:
    def test_every_domain_has_a_mapped_family(self):
        from agents.studio_compositor.ward_fx_mapping import (
            DOMAIN_PRESET_FAMILY,
            preset_family_for_domain,
        )

        for domain in (
            "communication",
            "presence",
            "token",
            "music",
            "cognition",
            "director",
            "perception",
        ):
            assert domain in DOMAIN_PRESET_FAMILY
            assert preset_family_for_domain(domain) in (
                "audio-reactive",
                "calm-textural",
                "glitch-dense",
                "warm-minimal",
                "neutral-ambient",
            )

    def test_unknown_ward_falls_back_to_perception_domain(self):
        from agents.studio_compositor.ward_fx_mapping import domain_for_ward

        assert domain_for_ward("this_ward_does_not_exist") == "perception"

    def test_known_wards_resolve_to_declared_domain(self):
        from agents.studio_compositor.ward_fx_mapping import domain_for_ward

        assert domain_for_ward("token_pole") == "token"
        assert domain_for_ward("chat_ambient") == "communication"
        assert domain_for_ward("album") == "music"
        assert domain_for_ward("objectives_overlay") == "director"

    def test_legibility_wards_classified_not_falling_back_to_perception(self):
        """The four legibility Cairo sources emit ward_ids in
        legibility_sources.py; each must have an explicit domain so the
        per-domain accent resolver in homage/rendering.py paints them in
        the operator-intended hue rather than silently green."""
        from agents.studio_compositor.ward_fx_mapping import domain_for_ward

        assert domain_for_ward("activity_header") == "cognition"
        assert domain_for_ward("stance_indicator") == "presence"
        assert domain_for_ward("grounding_provenance_ticker") == "director"
        assert domain_for_ward("chat_keyword_legend") == "communication"

    def test_compositor_dynamic_wards_classified(self):
        """Wards constructed in compositor.py (m8-display, programme-banner,
        precedent-ticker, programme-history, research-instrument-dashboard)
        emit hyphen-separated ward_ids; pin their domain so the border-pulse
        accent and preset-family selection don't fall back to perception."""
        from agents.studio_compositor.ward_fx_mapping import domain_for_ward

        assert domain_for_ward("m8-display") == "music"
        assert domain_for_ward("programme-banner") == "director"
        assert domain_for_ward("precedent-ticker") == "director"
        assert domain_for_ward("programme-history") == "cognition"
        assert domain_for_ward("research-instrument-dashboard") == "cognition"

    def test_audio_reactive_set_matches_expected_wards(self):
        from agents.studio_compositor.ward_fx_mapping import (
            AUDIO_REACTIVE_WARDS,
            is_audio_reactive,
        )

        # At least the operator's named set is in the audio-reactive bucket.
        # (HARDM retired 2026-04-23 — dropped from this assertion.)
        assert "pressure_gauge" in AUDIO_REACTIVE_WARDS
        assert is_audio_reactive("token_pole")
        assert not is_audio_reactive("captions")

    def test_audio_reactive_wards_all_have_domain_assignment(self):
        """Every member of ``AUDIO_REACTIVE_WARDS`` must also appear in
        ``WARD_DOMAIN`` — otherwise ``domain_for_ward`` returns the
        ``perception`` fallback for an audio-reactive ward, which
        contradicts the reactor's "music-domain ward gets bus-level
        beat coupling" pattern. A future addition to the audio-reactive
        set without a paired domain entry would silently misclassify
        the new ward."""
        from agents.studio_compositor.ward_fx_mapping import (
            AUDIO_REACTIVE_WARDS,
            WARD_DOMAIN,
        )

        missing = sorted(w for w in AUDIO_REACTIVE_WARDS if w not in WARD_DOMAIN)
        assert not missing, (
            f"AUDIO_REACTIVE_WARDS members missing from WARD_DOMAIN "
            f"(would default to 'perception'): {missing}"
        )

    def test_m8_oscilloscope_is_audio_reactive(self):
        """The M8 oscilloscope ward renders the M8's SLIP-packet waveform
        directly (intrinsic audio reactivity) AND participates in
        bus-level FX-event modulation alongside the other music-domain
        wards. Pin both invariants — domain=music + audio-reactive — so
        a future change can't silently drop the ward from the reactor's
        scale_bump / border_pulse path."""
        from agents.studio_compositor.ward_fx_mapping import (
            AUDIO_REACTIVE_WARDS,
            domain_for_ward,
            is_audio_reactive,
        )

        assert "m8_oscilloscope" in AUDIO_REACTIVE_WARDS
        assert is_audio_reactive("m8_oscilloscope")
        assert domain_for_ward("m8_oscilloscope") == "music"


# ── helpers ──────────────────────────────────────────────────────────────


class TestChoreographerPublishesWardEvents:
    """Choreographer.reconcile() emits WardEvent per planned transition."""

    def test_entry_plan_publishes_absent_to_entering(self, isolated_bus):
        from agents.studio_compositor.homage.choreographer import (
            Choreographer,
            PlannedTransition,
        )
        from shared.ward_fx_bus import WardEvent, get_bus

        captured: list[WardEvent] = []
        get_bus().subscribe_ward(captured.append)

        choreographer = Choreographer(
            pending_file=isolated_bus / "pending.json",
            uniforms_file=isolated_bus / "uniforms.json",
            shader_reading_file=isolated_bus / "reading.json",
            substrate_package_file=isolated_bus / "substrate.json",
            consent_safe_flag_file=isolated_bus / "consent-safe.json",
            voice_register_file=isolated_bus / "voice.json",
            structural_intent_file=isolated_bus / "intent.json",
        )

        choreographer._publish_ward_events(
            [
                PlannedTransition(
                    source_id="token_pole",
                    transition="zero-cut-in",
                    phase="entry",
                    start_at=100.0,
                ),
                PlannedTransition(
                    source_id="album",
                    transition="ticker-scroll-out",
                    phase="exit",
                    start_at=100.5,
                ),
                PlannedTransition(
                    source_id="stream_overlay",
                    transition="netsplit-burst",
                    phase="modify",
                    start_at=101.0,
                ),
            ]
        )

        assert len(captured) == 3
        assert captured[0].ward_id == "token_pole"
        assert captured[0].transition == "ABSENT_TO_ENTERING"
        assert captured[0].domain == "token"
        assert captured[1].transition == "HOLD_TO_EXITING"
        assert captured[2].transition == "HOLD_TO_EMPHASIZED"


class TestPresetChangePublishesFamilyFxEvent:
    """effects.try_graph_preset publishes FXEvent(preset_family_change)
    only when the family actually changes."""

    def test_same_family_preset_does_not_publish(self, isolated_bus):
        from agents.studio_compositor import effects
        from shared.ward_fx_bus import FXEvent, get_bus

        class _FakeCompositor:
            _fx_last_published_family = "warm-minimal"

        captured: list[FXEvent] = []
        get_bus().subscribe_fx(captured.append)

        fake = _FakeCompositor()
        effects._maybe_publish_family_change(fake, "vhs_preset", "vhs_preset")
        assert captured == []

    def test_cross_family_preset_publishes(self, isolated_bus):
        from agents.studio_compositor import effects
        from shared.ward_fx_bus import FXEvent, get_bus

        class _FakeCompositor:
            _fx_last_published_family: str | None = None

        captured: list[FXEvent] = []
        get_bus().subscribe_fx(captured.append)

        fake = _FakeCompositor()
        effects._maybe_publish_family_change(fake, "feedback_preset", "feedback_preset")
        assert len(captured) == 1
        event = captured[0]
        assert event.kind == "preset_family_change"
        assert event.preset_family == "audio-reactive"
        assert fake._fx_last_published_family == "audio-reactive"

    def test_unknown_preset_does_not_publish(self, isolated_bus):
        from agents.studio_compositor import effects
        from shared.ward_fx_bus import FXEvent, get_bus

        class _FakeCompositor:
            _fx_last_published_family: str | None = None

        captured: list[FXEvent] = []
        get_bus().subscribe_fx(captured.append)

        fake = _FakeCompositor()
        effects._maybe_publish_family_change(fake, "this_preset_is_not_catalogued", "alias")
        assert captured == []


class TestFxChainAudioPublishers:
    """fx_chain._maybe_publish_audio_fx_events emits kick/spike on threshold."""

    def test_kick_onset_emits_on_threshold(self, isolated_bus):
        from agents.studio_compositor import fx_chain
        from shared.ward_fx_bus import FXEvent, get_bus

        class _FakeCompositor:
            pass

        captured: list[FXEvent] = []
        get_bus().subscribe_fx(captured.append)

        fake = _FakeCompositor()
        fx_chain._maybe_publish_audio_fx_events(fake, {"onset_kick": 0.9})
        kinds = [e.kind for e in captured]
        assert "audio_kick_onset" in kinds

    def test_kick_below_threshold_does_not_emit(self, isolated_bus):
        from agents.studio_compositor import fx_chain
        from shared.ward_fx_bus import FXEvent, get_bus

        class _FakeCompositor:
            pass

        captured: list[FXEvent] = []
        get_bus().subscribe_fx(captured.append)

        fake = _FakeCompositor()
        fx_chain._maybe_publish_audio_fx_events(fake, {"onset_kick": 0.3})
        assert all(e.kind != "audio_kick_onset" for e in captured)

    def test_kick_cooldown_enforced(self, isolated_bus):
        from agents.studio_compositor import fx_chain
        from shared.ward_fx_bus import FXEvent, get_bus

        class _FakeCompositor:
            pass

        captured: list[FXEvent] = []
        get_bus().subscribe_fx(captured.append)

        fake = _FakeCompositor()
        fx_chain._maybe_publish_audio_fx_events(fake, {"onset_kick": 0.9})
        fx_chain._maybe_publish_audio_fx_events(fake, {"onset_kick": 0.9})
        kicks = [e for e in captured if e.kind == "audio_kick_onset"]
        # Cooldown: second call within _AUDIO_KICK_FX_COOLDOWN_S (150ms) must be suppressed.
        assert len(kicks) == 1

    def test_intensity_spike_emits_on_threshold(self, isolated_bus):
        from agents.studio_compositor import fx_chain
        from shared.ward_fx_bus import FXEvent, get_bus

        class _FakeCompositor:
            pass

        captured: list[FXEvent] = []
        get_bus().subscribe_fx(captured.append)

        fake = _FakeCompositor()
        fx_chain._maybe_publish_audio_fx_events(fake, {"mixer_energy": 0.85})
        kinds = [e.kind for e in captured]
        assert "intensity_spike" in kinds


# ── helpers ──────────────────────────────────────────────────────────────


def _collect_samples(histogram) -> dict[str, float]:
    """Extract sum + count from a labelled histogram child.

    prometheus_client exposes ``collect()`` on both parent and child
    histograms; the cleanest cross-version API is to iterate samples
    and pick off the ``_count`` / ``_sum`` suffixes.
    """
    total_sum = 0.0
    total_count = 0.0
    for metric_family in histogram.collect():
        for sample in metric_family.samples:
            if sample.name.endswith("_count"):
                total_count = float(sample.value)
            elif sample.name.endswith("_sum"):
                total_sum = float(sample.value)
    return {"sum": total_sum, "count": total_count}
