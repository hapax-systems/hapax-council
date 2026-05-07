"""Regression pins for the 3 counters flagged by the alpha E2E smoketest.

Task: fix(observability) — #129 face-obscure + #157 nondestructive +
#145 audio-ducking prom counters must register on the compositor
``REGISTRY`` at module-import time AND must increment when their helper
functions are called.

An 8th E2E smoketest flagged the face-obscure counters as absent at
``:9482``; the nondestructive and audio-ducking counters had the same
class of symptom. These tests pin the registration + helper-call flow so
any future refactor that drops a ``global`` declaration, forgets a
``labels(...).inc()`` call, or strips the controller wiring from
``lifecycle.py`` fails loudly here rather than in a live smoketest.

The tests assert against ``agents.studio_compositor.metrics.REGISTRY``
(the custom ``CollectorRegistry`` used by ``start_metrics_server``), not
the default prometheus_client REGISTRY — the compositor's HTTP server
binds to the custom registry.
"""

from __future__ import annotations

from prometheus_client.exposition import generate_latest

from agents.studio_compositor import metrics


def _registry_text() -> str:
    """Render the compositor's custom REGISTRY to a str for grep."""
    return generate_latest(metrics.REGISTRY).decode("utf-8")


class TestFaceObscureCounters:
    """Task #129 Stage 3 — per-camera face-obscure counters."""

    def test_frame_counter_registered(self) -> None:
        # Counter metadata must be present even before any .labels() call
        # so Grafana recording rules resolve at compositor boot.
        assert metrics.HAPAX_FACE_OBSCURE_FRAME_TOTAL is not None
        text = _registry_text()
        assert "# HELP hapax_face_obscure_frame_total" in text
        assert "# TYPE hapax_face_obscure_frame_total counter" in text

    def test_errors_counter_registered(self) -> None:
        assert metrics.HAPAX_FACE_OBSCURE_ERRORS_TOTAL is not None
        text = _registry_text()
        assert "# HELP hapax_face_obscure_errors_total" in text
        assert "# TYPE hapax_face_obscure_errors_total counter" in text

    def test_record_frame_increments(self) -> None:
        # Read-before then read-after so we don't assume the process is
        # freshly-booted (tests share a registry if run in the same
        # pytest invocation as other metric-touching tests).
        counter = metrics.HAPAX_FACE_OBSCURE_FRAME_TOTAL.labels(
            camera_role="regression-test-cam",
            has_faces="false",
        )
        before = counter._value.get()
        metrics.record_face_obscure_frame("regression-test-cam", has_faces=False)
        after = counter._value.get()
        assert after == before + 1.0

    def test_record_error_increments(self) -> None:
        counter = metrics.HAPAX_FACE_OBSCURE_ERRORS_TOTAL.labels(
            camera_role="regression-test-cam",
            exception_class="RegressionTestError",
        )
        before = counter._value.get()
        metrics.record_face_obscure_error(
            "regression-test-cam",
            exception_class="RegressionTestError",
        )
        after = counter._value.get()
        assert after == before + 1.0


class TestNondestructiveClampsCounter:
    """Task #157 — per-source non-destructive alpha-clamp counter."""

    def test_counter_registered(self) -> None:
        assert metrics.COMP_NONDESTRUCTIVE_CLAMPS_TOTAL is not None
        text = _registry_text()
        assert "# HELP hapax_compositor_nondestructive_clamps_total" in text
        assert "# TYPE hapax_compositor_nondestructive_clamps_total counter" in text

    def test_increment_from_fx_chain_helper(self) -> None:
        # fx_chain.py calls ``metrics.COMP_NONDESTRUCTIVE_CLAMPS_TOTAL
        # .labels(source=source_id).inc()`` directly; exercise the same
        # path to pin the label contract.
        counter = metrics.COMP_NONDESTRUCTIVE_CLAMPS_TOTAL.labels(
            source="regression-test-source",
        )
        before = counter._value.get()
        counter.inc()
        after = counter._value.get()
        assert after == before + 1.0


class TestAntigravCleanupObservabilityCounters:
    """M7/M9/M10 cleanup counters must be present on the compositor registry."""

    def test_source_backend_errors_counter_registered(self) -> None:
        assert metrics.COMP_SOURCE_BACKEND_ERRORS_TOTAL is not None
        text = _registry_text()
        assert "# HELP studio_compositor_source_backend_errors_total" in text
        assert "# TYPE studio_compositor_source_backend_errors_total counter" in text

    def test_rtmp_side_effect_errors_counter_registered(self) -> None:
        assert metrics.RTMP_SIDE_EFFECT_ERRORS_TOTAL is not None
        text = _registry_text()
        assert "# HELP studio_rtmp_side_effect_errors_total" in text
        assert "# TYPE studio_rtmp_side_effect_errors_total counter" in text

    def test_stop_errors_counter_registered(self) -> None:
        assert metrics.COMP_STOP_ERRORS_TOTAL is not None
        text = _registry_text()
        assert "# HELP studio_compositor_stop_errors_total" in text
        assert "# TYPE studio_compositor_stop_errors_total counter" in text


class TestDirectorRefusalGateCounter:
    """Phase 5 RefusalGate outcome counter must live on the :9482 registry."""

    def test_counter_registered_with_director_outcomes(self) -> None:
        assert metrics.HAPAX_REFUSAL_GATE_REROLLS is not None
        text = _registry_text()
        assert "# HELP hapax_refusal_gate_rerolls_total" in text
        assert "# TYPE hapax_refusal_gate_rerolls_total counter" in text
        for outcome in (
            "accepted_first_pass",
            "accepted_after_reroll",
            "dropped_after_reroll",
        ):
            assert (
                metrics.REGISTRY.get_sample_value(
                    "hapax_refusal_gate_rerolls_total",
                    {"surface": "director", "outcome": outcome},
                )
                is not None
            )

    def test_record_refusal_gate_reroll_increments(self) -> None:
        labels = {"surface": "director", "outcome": "dropped_after_reroll"}
        before = metrics.REGISTRY.get_sample_value(
            "hapax_refusal_gate_rerolls_total",
            labels,
        )
        metrics.record_refusal_gate_reroll(**labels)
        after = metrics.REGISTRY.get_sample_value(
            "hapax_refusal_gate_rerolls_total",
            labels,
        )
        assert before is not None
        assert after == before + 1.0


class TestAudioDuckingGauge:
    """CVS #145 — bidirectional backing-mix ducker state gauge."""

    def test_gauge_registered_with_prepopulated_labels(self) -> None:
        # _init_metrics pre-populates every state label so Grafana always
        # sees the full cardinality on the first scrape. If this ever
        # breaks (e.g. the ``for _st in ...`` loop is dropped), only
        # "normal" would appear and the dashboard would silently lose
        # its voice_active / yt_active / both_active lines.
        assert metrics.HAPAX_AUDIO_DUCKING_STATE is not None
        text = _registry_text()
        assert "# HELP hapax_audio_ducking_state" in text
        assert "# TYPE hapax_audio_ducking_state gauge" in text
        for state in ("normal", "voice_active", "yt_active", "both_active"):
            assert f'hapax_audio_ducking_state{{state="{state}"}}' in text

    def test_set_audio_ducking_state_is_one_hot(self) -> None:
        # Transitioning to each state must leave that label at 1.0 and
        # every other label at 0.0 — the one-hot invariant is what lets
        # Grafana compute dwell time via ``sum_over_time(...)`` per label.
        for target in ("normal", "voice_active", "yt_active", "both_active"):
            metrics.set_audio_ducking_state(target)
            for state in ("normal", "voice_active", "yt_active", "both_active"):
                val = metrics.HAPAX_AUDIO_DUCKING_STATE.labels(state=state)._value.get()
                if state == target:
                    assert val == 1.0, f"{target} set — {state} label should be 1.0, got {val}"
                else:
                    assert val == 0.0, f"{target} set — {state} label should be 0.0, got {val}"

        # Leave the registry in the default "normal" state so subsequent
        # tests don't inherit our scratch state.
        metrics.set_audio_ducking_state("normal")


class TestControllerLifecycleWiring:
    """Pin the lifecycle.py wiring that instantiates AudioDuckingController.

    Without this wiring the gauge is frozen at registration defaults
    (normal=1, others=0) regardless of VAD / YT audio actually flowing —
    the state gauge appears in Prometheus but tells Grafana nothing. The
    test imports ``lifecycle`` and greps the module source for the
    ``AudioDuckingController`` instantiation — a source-level pin that
    does not require spawning the full GStreamer compositor.
    """

    def test_lifecycle_starts_audio_ducking(self) -> None:
        import inspect

        from agents.studio_compositor import lifecycle

        source = inspect.getsource(lifecycle)
        assert "AudioDuckingController()" in source, (
            "lifecycle.start_compositor must instantiate AudioDuckingController "
            "so hapax_audio_ducking_state reflects runtime state"
        )
        assert "._audio_ducking.start()" in source, (
            "lifecycle.start_compositor must start() the AudioDuckingController "
            "thread after instantiation"
        )
