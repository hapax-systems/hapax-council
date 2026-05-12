"""Phase D task 14 — StudioCompositor LayoutState + SourceRegistry wiring.

These tests exercise ``StudioCompositor.start_layout_only`` without
touching GStreamer so the Layout wiring can be validated on any
machine without a display, GPU, or v4l2 device nodes. The production
path runs this same helper from ``StudioCompositor.start`` before the
lifecycle pulls in the GStreamer bits, so whatever these tests lock in
also locks in the production wiring.

Source-registry epic Phase D task 14. See
``docs/superpowers/plans/2026-04-12-compositor-source-registry-foundation-plan.md``.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest import mock

from agents.studio_compositor.compositor import StudioCompositor
from agents.studio_compositor.config import _default_config
from tests.studio_compositor.test_default_layout_loading import DEFAULT_JSON

if TYPE_CHECKING:
    import pytest


class _FakeCounter:
    def __init__(self) -> None:
        self.labels_seen: list[dict[str, str]] = []

    def labels(self, **labels: str) -> _FakeCounter:
        self.labels_seen.append(labels)
        return self

    def inc(self) -> None:
        pass


def _make_compositor(layout_path: Path | None = None) -> StudioCompositor:
    """Construct a compositor with a minimal config, patching load_camera_profiles.

    ``StudioCompositor.__init__`` calls ``load_camera_profiles`` eagerly, which
    opens ``~/.config/hapax-compositor/profiles.yaml`` if it exists. In CI and
    on fresh workstations, the file may be absent or carry an unrelated schema
    — neither is a bug in this test's scope. Patch the loader to a no-op so the
    test exercises the Layout wiring and nothing else.
    """
    with mock.patch(
        "agents.studio_compositor.compositor.load_camera_profiles",
        return_value=[],
    ):
        return StudioCompositor(_default_config(), layout_path=layout_path)


class TestStartLayoutOnly:
    """Happy-path, fallback, and idempotency coverage."""

    def test_reads_disk_layout_and_populates_state_and_registry(self, tmp_path: Path) -> None:
        layout_file = tmp_path / "default.json"
        layout_file.write_text(DEFAULT_JSON.read_text())

        compositor = _make_compositor(layout_path=layout_file)
        compositor.start_layout_only()

        assert compositor.layout_state is not None
        assert compositor.source_registry is not None

        layout = compositor.layout_state.get()
        assert layout.name == "default"
        expected_ids = {
            "activity_header",
            "activity_variety_log",
            "album",
            "ascii_schematic",
            "cbip_dual_ir_displacement",
            "cbip_signal_density",
            "chat_ambient",
            "chronicle_ticker",
            "coding_session_reveal",
            "constructivist_research_poster",
            "durf",
            "egress_footer",
            "gem",
            "grounding_provenance_ticker",
            "impingement_cascade",
            "interactive_lore_query",
            "m8-display",
            "m8_oscilloscope",
            "polyend_instrument_reveal",
            "precedent_ticker",
            "pressure_gauge",
            "programme_banner",
            "programme_history",
            "programme_state",
            "recruitment_candidate_panel",
            "research_instrument_dashboard",
            "reverie",
            "segment_content",
            "sierpinski",
            "stance_indicator",
            "steamdeck-display",
            "stream_overlay",
            "thinking_indicator",
            "token_pole",
            "tufte_density",
            "whos_here",
        }
        assert {s.id for s in layout.sources} == expected_ids
        registered = set(compositor.source_registry.ids())
        assert registered == expected_ids or registered == expected_ids - {
            "interactive_lore_query",
        }

    def test_missing_layout_file_resolves_to_fallback(self, tmp_path: Path) -> None:
        """Missing on-disk layout must NOT stop the compositor from booting."""
        compositor = _make_compositor(layout_path=tmp_path / "does-not-exist.json")
        compositor.start_layout_only()

        assert compositor.layout_state is not None
        layout = compositor.layout_state.get()
        assert layout.name == "default"
        # Fallback layout is the in-Python ``_FALLBACK_LAYOUT``. As of
        # ward-family-compositor-layout-integration (2026-05-04) the
        # fallback now mirrors the on-disk JSON for programme_banner
        # and the ytb-LORE-EXT family — the rescue path stays
        # structurally identical to default.json.
        registered = set(compositor.source_registry.ids())
        expected = {
            "token_pole",
            "album",
            "stream_overlay",
            "sierpinski",
            "reverie",
            "activity_header",
            "stance_indicator",
            "grounding_provenance_ticker",
            "impingement_cascade",
            "recruitment_candidate_panel",
            "thinking_indicator",
            "pressure_gauge",
            "activity_variety_log",
            "whos_here",
            "durf",
            "m8-display",
            "steamdeck-display",
            "egress_footer",
            "gem",
            "programme_banner",
            "precedent_ticker",
            "programme_history",
            "research_instrument_dashboard",
            "cbip_signal_density",
            "chat_ambient",
            "chronicle_ticker",
            "coding_session_reveal",
            "programme_state",
            "polyend_instrument_reveal",
            "interactive_lore_query",
            "constructivist_research_poster",
            "tufte_density",
            "ascii_schematic",
            "segment_content",
            "m8_oscilloscope",
            "cbip_dual_ir_displacement",
        }
        # Sources whose __init__ requires non-default args may fail to
        # construct in test environments (e.g. InteractiveLoreQueryWard
        # needs an allowlist YAML that doesn't exist in tmp_path).
        # The compositor logs and skips these gracefully.
        assert registered == expected or registered == expected - {
            "interactive_lore_query",
        }

    def test_broken_json_resolves_to_fallback(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken.json"
        broken.write_text("{not json")

        compositor = _make_compositor(layout_path=broken)
        compositor.start_layout_only()

        assert compositor.layout_state is not None
        assert compositor.layout_state.get().name == "default"

    def test_idempotent_when_called_twice(self, tmp_path: Path) -> None:
        """Calling start_layout_only twice must not re-register sources."""
        layout_file = tmp_path / "default.json"
        layout_file.write_text(DEFAULT_JSON.read_text())

        compositor = _make_compositor(layout_path=layout_file)
        compositor.start_layout_only()

        first_state = compositor.layout_state
        first_registry = compositor.source_registry

        compositor.start_layout_only()

        assert compositor.layout_state is first_state
        assert compositor.source_registry is first_registry

    def test_default_layout_path_is_absolute_and_resolvable(self) -> None:
        """Default layout path is computed from __file__ and points at the real file.

        Regression pin for the PR #735 audit finding: the previous default
        was a CWD-relative ``Path("config/compositor-layouts/default.json")``,
        which silently fell through to ``_FALLBACK_LAYOUT`` when the
        compositor was invoked from any directory other than the repo root.
        The new default resolves from ``__file__.resolve().parents[2]`` so
        the path is stable regardless of process CWD, and the file it points
        at must actually exist in the repo (``test_default_json_exists_and_is_valid_layout``
        in ``test_default_layout_loading.py`` pins the file's existence from
        the other side).
        """
        compositor = _make_compositor()
        assert compositor._layout_path.is_absolute(), (
            "default layout path must be absolute so it works from any CWD"
        )
        assert compositor._layout_path.name == "default.json"
        assert compositor._layout_path.parent.name == "compositor-layouts"
        assert compositor._layout_path.exists(), (
            f"default layout file must resolve on disk at {compositor._layout_path}"
        )

    def test_continues_past_broken_source_backend(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch,
    ) -> None:
        """A source with an unknown backend must log + skip, not crash."""
        import logging

        from agents.studio_compositor import metrics

        raw = json.loads(DEFAULT_JSON.read_text())
        raw["sources"].append(
            {
                "id": "broken",
                "kind": "cairo",
                "backend": "cairo",
                "params": {"class_name": "DoesNotExist"},
            }
        )
        layout_file = tmp_path / "default.json"
        layout_file.write_text(json.dumps(raw))

        compositor = _make_compositor(layout_path=layout_file)
        counter = _FakeCounter()
        monkeypatch.setattr(metrics, "COMP_SOURCE_BACKEND_ERRORS_TOTAL", counter)
        caplog.set_level(logging.ERROR, logger="agents.studio_compositor.compositor")
        compositor.start_layout_only()

        assert compositor.source_registry is not None
        assert "broken" not in compositor.source_registry.ids()
        assert {"token_pole", "album", "sierpinski", "reverie"}.issubset(
            set(compositor.source_registry.ids())
        )
        assert any("failed to construct backend" in rec.message for rec in caplog.records)
        assert {
            "phase": "construct",
            "source_id": "broken",
            "backend": "cairo",
            "exception_class": "KeyError",
        } in counter.labels_seen

    def test_start_layout_only_wires_director_segment_runner(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        layout_file = tmp_path / "default.json"
        layout_file.write_text(DEFAULT_JSON.read_text())
        runner = SimpleNamespace(stop=lambda: None)
        calls: list[Path] = []

        def _fake_start(compositor: StudioCompositor, *, command_socket_path: Path):
            calls.append(command_socket_path)
            return runner

        monkeypatch.setattr(
            "agents.studio_compositor.director_segment_runner.maybe_start_director_segment_runner",
            _fake_start,
        )
        compositor = _make_compositor(layout_path=layout_file)

        compositor.start_layout_only()

        assert compositor._director_segment_runner is runner
        assert calls
        assert calls[0].name == "hapax-compositor-commands.sock"

    def test_start_layout_only_wires_autosaver_and_file_watcher(self, tmp_path: Path) -> None:
        """Post-epic audit finding #1 regression pin.

        ``LayoutAutoSaver`` and ``LayoutFileWatcher`` existed in
        ``layout_persistence.py`` after Phase 5 of the completion epic
        but were never instantiated by ``StudioCompositor``, leaving
        AC-5 (file-watch reload) unwired. This test pins that both
        persistence threads are started on ``start_layout_only()`` and
        stopped on ``stop()`` so the finding cannot silently regress.
        """
        layout_file = tmp_path / "default.json"
        layout_file.write_text(DEFAULT_JSON.read_text())

        compositor = _make_compositor(layout_path=layout_file)
        assert compositor._layout_autosaver is None
        assert compositor._layout_file_watcher is None

        compositor.start_layout_only()

        assert compositor._layout_autosaver is not None, (
            "LayoutAutoSaver must be wired into start_layout_only"
        )
        assert compositor._layout_file_watcher is not None, (
            "LayoutFileWatcher must be wired into start_layout_only"
        )
        # Threads should be running.
        assert compositor._layout_autosaver._thread is not None
        assert compositor._layout_autosaver._thread.is_alive()
        assert compositor._layout_file_watcher._thread is not None
        assert compositor._layout_file_watcher._thread.is_alive()

        # Stopping without the full lifecycle attached still has to
        # tear down the persistence threads cleanly. The lifecycle
        # import inside ``stop()`` will no-op on an unbuilt pipeline.
        try:
            compositor.stop()
        except Exception:
            # lifecycle.stop_compositor may require a built pipeline —
            # the persistence teardown runs BEFORE that call, so the
            # threads should already be stopped by the time we get
            # here regardless of whether the lifecycle call succeeds.
            pass

        assert compositor._layout_autosaver is None
        assert compositor._layout_file_watcher is None

    def test_stop_exceptions_increment_teardown_counter(self, monkeypatch) -> None:
        from agents.studio_compositor import metrics

        class StopRaises:
            def stop(self) -> None:
                raise RuntimeError("stop failed")

        fake = SimpleNamespace(
            _scene_classifier_thread=StopRaises(),
            _camera_classifier_publisher=None,
            _command_server=StopRaises(),
            _recent_pub=None,
            _layout_file_watcher=StopRaises(),
            _layout_autosaver=None,
        )
        counter = _FakeCounter()
        monkeypatch.setattr(metrics, "COMP_STOP_ERRORS_TOTAL", counter)
        monkeypatch.setattr(
            "agents.studio_compositor.lifecycle.stop_compositor",
            lambda _compositor: None,
        )

        StudioCompositor.stop(fake)  # type: ignore[arg-type]

        assert {
            "component": "scene_classifier_thread",
            "exception_class": "RuntimeError",
        } in counter.labels_seen
        assert {
            "component": "command_server",
            "exception_class": "RuntimeError",
        } in counter.labels_seen
        assert {
            "component": "layout_file_watcher",
            "exception_class": "RuntimeError",
        } in counter.labels_seen


class TestStartDelegatesThroughStartLayoutOnly:
    """The full ``start()`` path must invoke ``start_layout_only()`` before GStreamer."""

    def test_start_invokes_layout_loader_before_lifecycle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        layout_file = tmp_path / "default.json"
        layout_file.write_text(DEFAULT_JSON.read_text())

        compositor = _make_compositor(layout_path=layout_file)

        calls: list[str] = []
        original_layout_only = compositor.start_layout_only

        def _tracking_layout_only() -> None:
            calls.append("layout_only")
            original_layout_only()

        compositor.start_layout_only = _tracking_layout_only  # type: ignore[method-assign]

        fake_lifecycle = mock.Mock()

        def _track_lifecycle(c: StudioCompositor) -> None:
            calls.append("lifecycle")
            fake_lifecycle(c)

        monkeypatch.setattr(
            "agents.studio_compositor.lifecycle.start_compositor",
            _track_lifecycle,
        )

        compositor.start()

        assert calls == ["layout_only", "lifecycle"]
        assert compositor.layout_state is not None
        assert compositor.source_registry is not None
        fake_lifecycle.assert_called_once_with(compositor)


class TestStudioCompositorBudgetWiring:
    """Phase 10 (delta 2026-04-14-compositor-frame-budget-forensics) regression pins.

    Delta's drop identified that the Phase 7 BudgetTracker was never
    instantiated and no CairoSourceRunner ever had a tracker wired —
    publish_costs + publish_degraded_signal both showed age_seconds=+Inf
    for the process lifetime. These tests pin the wiring so any future
    regression is visible.
    """

    def test_compositor_owns_a_budget_tracker_after_init(self) -> None:
        from agents.studio_compositor.budget import BudgetTracker

        compositor = _make_compositor()
        assert isinstance(compositor._budget_tracker, BudgetTracker)

    def test_overlay_zone_manager_runner_has_tracker_wired(self) -> None:
        compositor = _make_compositor()
        runner = compositor._overlay_zone_manager._runner
        assert runner._budget_tracker is compositor._budget_tracker

    def test_start_layout_only_wires_tracker_to_cairo_backends(self, tmp_path: Path) -> None:
        """Every cairo backend in the SourceRegistry shares the compositor tracker."""
        from agents.studio_compositor.cairo_source import CairoSourceRunner

        layout_file = tmp_path / "default.json"
        layout_file.write_text(DEFAULT_JSON.read_text())

        compositor = _make_compositor(layout_path=layout_file)
        compositor.start_layout_only()

        assert compositor.source_registry is not None
        cairo_runners = [
            compositor.source_registry._backends[sid]
            for sid in compositor.source_registry.ids()
            if isinstance(compositor.source_registry._backends[sid], CairoSourceRunner)
        ]
        assert cairo_runners, "layout must contain at least one cairo-backed source"
        for runner in cairo_runners:
            assert runner._budget_tracker is compositor._budget_tracker, (
                f"cairo runner {runner.source_id} is missing tracker wiring"
            )

    def test_tracker_collects_samples_across_runner_ticks(self, tmp_path: Path) -> None:
        """After ticking every cairo runner once, the tracker has per-source samples."""
        from agents.studio_compositor.cairo_source import CairoSourceRunner

        layout_file = tmp_path / "default.json"
        layout_file.write_text(DEFAULT_JSON.read_text())

        compositor = _make_compositor(layout_path=layout_file)
        compositor.start_layout_only()

        assert compositor.source_registry is not None
        for sid in compositor.source_registry.ids():
            backend = compositor.source_registry._backends[sid]
            if isinstance(backend, CairoSourceRunner):
                backend.tick_once()

        snap = compositor._budget_tracker.snapshot()
        recorded = {sid for sid, cost in snap.items() if cost.sample_count > 0}
        assert recorded, (
            "BudgetTracker.snapshot() had zero samples after ticking cairo runners — "
            "wiring is dead, regression of T1/T2 from the delta drop"
        )

    def test_publish_costs_round_trips_to_json(self, tmp_path: Path) -> None:
        """publish_costs(tracker, path) writes a parseable JSON snapshot."""
        from agents.studio_compositor.budget import publish_costs
        from agents.studio_compositor.cairo_source import CairoSourceRunner

        layout_file = tmp_path / "default.json"
        layout_file.write_text(DEFAULT_JSON.read_text())

        compositor = _make_compositor(layout_path=layout_file)
        compositor.start_layout_only()

        assert compositor.source_registry is not None
        for sid in compositor.source_registry.ids():
            backend = compositor.source_registry._backends[sid]
            if isinstance(backend, CairoSourceRunner):
                backend.tick_once()

        costs_path = tmp_path / "costs.json"
        publish_costs(compositor._budget_tracker, costs_path)
        assert costs_path.is_file()
        payload = json.loads(costs_path.read_text())
        assert payload["schema_version"] == 1
        assert "sources" in payload
        assert any(source.get("sample_count", 0) > 0 for source in payload["sources"].values())

    def test_publish_degraded_signal_round_trips(self, tmp_path: Path) -> None:
        """publish_degraded_signal writes a parseable degraded-signal JSON."""
        from agents.studio_compositor.budget_signal import publish_degraded_signal

        compositor = _make_compositor()
        compositor._budget_tracker.record("overlay-zones", 4.5)
        compositor._budget_tracker.record_skip("overlay-zones")

        degraded_path = tmp_path / "degraded.json"
        publish_degraded_signal(compositor._budget_tracker, degraded_path)
        assert degraded_path.is_file()
        payload = json.loads(degraded_path.read_text())
        assert payload["total_skip_count"] == 1
        assert payload["degraded_source_count"] == 1
        assert payload["worst_source"]["source_id"] == "overlay-zones"


class TestStudioCompositorOutputRouterWiring:
    """Phase 10 carry-over from Phase 2 item 10.

    ``OutputRouter.from_layout`` is pure data plumbing that enumerates
    video_out surfaces into typed OutputBinding records. Phase 2
    documented this migration as a carry-over; this test pins the
    compositor-side wiring so the router is available to any
    downstream consumer (diagnostics, future router-driven sinks).
    """

    def test_compositor_initializes_output_router_to_none(self) -> None:
        compositor = _make_compositor()
        assert compositor.output_router is None

    def test_start_layout_only_populates_output_router(self, tmp_path: Path) -> None:
        from agents.studio_compositor.output_router import OutputRouter

        layout_file = tmp_path / "default.json"
        layout_file.write_text(DEFAULT_JSON.read_text())

        compositor = _make_compositor(layout_path=layout_file)
        compositor.start_layout_only()

        assert isinstance(compositor.output_router, OutputRouter)
        # Default layout has 3 video_out surfaces from Phase 2 item 10:
        # v4l2 loopback + rtmp MediaMTX + hls local.
        assert len(compositor.output_router) >= 3
        sink_kinds = {b.sink_kind for b in compositor.output_router}
        assert {"v4l2", "rtmp", "hls"}.issubset(sink_kinds)

    def test_output_router_bindings_cover_every_video_out_surface(self, tmp_path: Path) -> None:
        """Every video_out surface in the layout must yield a binding."""
        layout_file = tmp_path / "default.json"
        layout_file.write_text(DEFAULT_JSON.read_text())

        compositor = _make_compositor(layout_path=layout_file)
        compositor.start_layout_only()

        assert compositor.output_router is not None
        assert compositor.layout_state is not None
        layout = compositor.layout_state.get()
        video_out_ids = {s.id for s in layout.surfaces if s.geometry.kind == "video_out"}
        binding_ids = {b.surface_id for b in compositor.output_router}
        assert video_out_ids.issubset(binding_ids), (
            f"router missing bindings for video_out surfaces: {video_out_ids - binding_ids}"
        )


class TestResearchMarkerOverlayRegistered:
    """Phase 10 carry-over from Phase 2 item 4.

    The Phase 2 ResearchMarkerOverlay class was implemented but not
    registered with the cairo_sources class-name registry, making it
    undeclarable from layout JSON. Pin the registration so a future
    layout entry can reach the class via ``class_name``.
    """

    def test_research_marker_overlay_is_registered(self) -> None:
        from agents.studio_compositor.cairo_sources import (
            get_cairo_source_class,
            list_classes,
        )
        from agents.studio_compositor.research_marker_overlay import ResearchMarkerOverlay

        assert "ResearchMarkerOverlay" in list_classes()
        cls = get_cairo_source_class("ResearchMarkerOverlay")
        assert cls is ResearchMarkerOverlay


class TestFeatureProbeLog:
    """Phase 10 / delta metric-coverage-gaps D3 — startup feature-probe log.

    Delta's drop #1 and drop #6 each spent investigation cycles on
    features that were installed but runtime-disabled (BudgetTracker,
    OpenCV CUDA). A per-boot ``feature-probe: NAME=BOOL`` inventory
    makes every latent-feature disable loud from startup.
    """

    def test_log_feature_probes_emits_expected_keys(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging as _logging

        from agents.studio_compositor.lifecycle import _log_feature_probes

        layout_file = tmp_path / "default.json"
        layout_file.write_text(DEFAULT_JSON.read_text())
        compositor = _make_compositor(layout_path=layout_file)
        compositor.start_layout_only()

        with caplog.at_level(_logging.INFO, logger="agents.studio_compositor.lifecycle"):
            _log_feature_probes(compositor)

        messages = [rec.message for rec in caplog.records if "feature-probe:" in rec.message]
        joined = " | ".join(messages)
        for key in [
            "prometheus_client=",
            "budget_tracker_active=",
            "opencv_cuda=",
            "output_router=",
            "research_marker_overlay_registered=",
        ]:
            assert key in joined, f"feature-probe log missing key: {key!r}"
        assert "budget_tracker_active=true" in joined, (
            "budget_tracker should read as active after start_layout_only"
        )
        assert "output_router=true" in joined, (
            "output_router should read as wired after start_layout_only"
        )
        assert "research_marker_overlay_registered=true" in joined
