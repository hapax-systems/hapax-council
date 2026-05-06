"""Tests for the DURF Codex coding-session HOMAGE ward."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from agents.studio_compositor import coding_activity_reveal as _coding_activity_module
from agents.studio_compositor import durf_source as _durf_module
from agents.studio_compositor.activity_reveal_ward import ActivityRevealMixin
from agents.studio_compositor.cairo_sources import get_cairo_source_class
from agents.studio_compositor.coding_activity_reveal import CodingActivityReveal
from agents.studio_compositor.durf_redaction import RedactionAction
from agents.studio_compositor.durf_source import (
    CodexPaneRegistry,
    DURFCairoSource,
    DURFPaneState,
    DURFSourceSnapshot,
    build_wcs_row,
    capture_tmux_text,
    is_pane_stale,
    redact_terminal_lines,
)
from agents.studio_compositor.homage.transitional_source import (
    HomageTransitionalSource,
    TransitionState,
)


@pytest.fixture
def codex_config(tmp_path: Path) -> Path:
    cfg = {
        "defaults": {
            "capture_lines": 3,
            "stale_after_seconds": 5,
            "max_visible_panes": 4,
        },
        "panes": [
            {"lane": "cx-cyan", "tmux_target": "hapax-codex-cx-cyan:0.0", "glyph": "C-<>"},
            {"lane": "cx-blue", "tmux_target": "hapax-codex-cx-blue:0.0", "glyph": "B-|/"},
            {"lane": "cx-violet", "tmux_target": "hapax-codex-cx-violet:0.0", "glyph": "V-\\\\"},
        ],
    }
    path = tmp_path / "durf-panes.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


@pytest.fixture
def registry_paths(tmp_path: Path, codex_config: Path) -> tuple[Path, Path, Path, Path]:
    relay_dir = tmp_path / "relay"
    claim_dir = tmp_path / "claims"
    relay_dir.mkdir()
    claim_dir.mkdir()
    health_path = tmp_path / "codex-session-health.md"
    return codex_config, relay_dir, claim_dir, health_path


def _registry(paths: tuple[Path, Path, Path, Path]) -> CodexPaneRegistry:
    config_path, relay_dir, claim_dir, health_path = paths
    return CodexPaneRegistry(
        config_path=config_path,
        relay_dir=relay_dir,
        claim_dir=claim_dir,
        session_health_path=health_path,
    )


def _surface_region_has_signal(
    surface: Any,
    *,
    x: int,
    y: int,
    w: int,
    h: int,
) -> bool:
    data = bytes(surface.get_data())
    stride = surface.get_stride()
    width = surface.get_width()
    height = surface.get_height()
    x0 = max(0, x)
    x1 = min(width, x + w)
    y0 = max(0, y)
    y1 = min(height, y + h)
    for row in range(y0, y1):
        start = row * stride + x0 * 4
        end = row * stride + x1 * 4
        if any(byte != 0 for byte in data[start:end]):
            return True
    return False


def _write_health(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "| Session | Role | Control | Screen | Task | Task status | Branch | PR | Why / current status | Warnings |",
                "|---|---|---|---|---|---|---|---|---|---|",
                "| cx-cyan | production worker lane | tmux | not required | coding-session-livestream-homage-ward - Coding session livestream HOMAGE ward | claimed | codex/cx-cyan-coding-session-livestream-homage-ward | - | implementing | - |",
                "| cx-violet | protected research lane | tmux | visible | - | idle | codex/cx-violet | - | protected | protected_do_not_relaunch_or_kill |",
            ]
        ),
        encoding="utf-8",
    )


class TestDURFSourceRegistration:
    def test_registered_in_cairo_sources(self) -> None:
        cls = get_cairo_source_class("DURFCairoSource")
        assert cls is DURFCairoSource

    def test_instantiates_without_starting_poll_thread(self, codex_config: Path) -> None:
        src = DURFCairoSource(config_path=codex_config, start_thread=False)
        try:
            assert src.source_id == "durf"
            assert src._config_path == codex_config
            state = src.state()
            assert "alpha" in state
            assert "wcs" in state
        finally:
            src.stop()


class TestCodexPaneRegistry:
    def test_discovers_codex_lane_from_relay_claim_health_and_config(
        self, registry_paths: tuple[Path, Path, Path, Path]
    ) -> None:
        _, relay_dir, claim_dir, health_path = registry_paths
        (claim_dir / "cc-active-task-cx-cyan").write_text(
            "coding-session-livestream-homage-ward\n",
            encoding="utf-8",
        )
        (relay_dir / "cx-cyan.yaml").write_text(
            yaml.safe_dump(
                {
                    "status": "review_fix_ci_pending",
                    "task_id": "coding-session-livestream-homage-ward",
                    "branch": "codex/cx-cyan-coding-session-livestream-homage-ward",
                    "current_pr": 1860,
                }
            ),
            encoding="utf-8",
        )
        _write_health(health_path)

        lanes, max_visible = _registry(registry_paths).discover_lanes()
        cyan = next(lane for lane in lanes if lane.lane_id == "cx-cyan")

        assert max_visible == 4
        assert cyan.tmux_target == "hapax-codex-cx-cyan:0.0"
        assert cyan.task_id == "coding-session-livestream-homage-ward"
        assert cyan.branch == "codex/cx-cyan-coding-session-livestream-homage-ward"
        assert cyan.pr == "1860"
        assert cyan.impingement_kind == "review"
        assert any("cc-active-task-cx-cyan" in ref for ref in cyan.source_refs)

    def test_lane_without_configured_tmux_target_is_suppressed(
        self, registry_paths: tuple[Path, Path, Path, Path]
    ) -> None:
        _, relay_dir, claim_dir, health_path = registry_paths
        (claim_dir / "cc-active-task-cx-amber").write_text(
            "director-scrim-gesture-adapter\n",
            encoding="utf-8",
        )
        (relay_dir / "cx-amber.yaml").write_text(
            yaml.safe_dump({"status": "claimed", "task_id": "director-scrim-gesture-adapter"}),
            encoding="utf-8",
        )
        _write_health(health_path)

        source = DURFCairoSource(registry=_registry(registry_paths), start_thread=False)
        try:
            snapshot = source._poll_once(now=100.0)
        finally:
            source.stop()

        amber = next(pane for pane in snapshot.panes if pane.lane_id == "cx-amber")
        assert amber.visible is False
        assert amber.suppressed_reason == "tmux_target_unconfigured"


class TestTmuxCapture:
    def test_capture_tmux_text_uses_bounded_tmux_command(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = MagicMock()
        fake.returncode = 0
        fake.stdout = "\x1b[31mone\x1b[0m\n" + "\n".join(["two", "three", "four", "five"])
        fake.stderr = ""
        run_spy = MagicMock(return_value=fake)
        monkeypatch.setattr(_durf_module.subprocess, "run", run_spy)

        result = capture_tmux_text("hapax-codex-cx-cyan:0.0", capture_lines=3)

        assert result.ok is True
        assert result.lines == ("three", "four", "five")
        assert run_spy.call_args.args[0] == [
            "tmux",
            "capture-pane",
            "-p",
            "-S",
            "-3",
            "-t",
            "hapax-codex-cx-cyan:0.0",
        ]

    def test_missing_tmux_target_reports_suppression_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = MagicMock()
        fake.returncode = 1
        fake.stdout = ""
        fake.stderr = "can't find pane"
        monkeypatch.setattr(_durf_module.subprocess, "run", MagicMock(return_value=fake))

        result = capture_tmux_text("missing:0.0", capture_lines=80)

        assert result.ok is False
        assert result.reason == "tmux_target_missing"
        assert "find pane" in (result.detail or "")


class TestRedaction:
    def test_redaction_suppresses_secret_like_text(self) -> None:
        result = redact_terminal_lines(("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456",))

        assert result.action is RedactionAction.SUPPRESS
        assert result.matched_pattern == "bearer_token"
        assert result.lines == ()

    def test_redaction_suppresses_operator_home_paths(self) -> None:
        result = redact_terminal_lines(("/home/hapax/.ssh/id_ed25519",))

        assert result.action is RedactionAction.SUPPRESS
        assert result.matched_pattern == "operator_home_path"

    def test_raw_bypass_fails_closed_in_public_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HAPAX_DURF_RAW", "1")

        result = redact_terminal_lines(("ordinary line",))

        assert result.action is RedactionAction.SUPPRESS
        assert result.matched_pattern == "unsafe_public_bypass"


class TestSourceState:
    def test_consent_safe_suppresses_before_tmux_capture(
        self, registry_paths: tuple[Path, Path, Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, relay_dir, claim_dir, health_path = registry_paths
        (claim_dir / "cc-active-task-cx-cyan").write_text("task\n", encoding="utf-8")
        (relay_dir / "cx-cyan.yaml").write_text(
            yaml.safe_dump({"status": "claimed", "task_id": "task"}),
            encoding="utf-8",
        )
        _write_health(health_path)
        monkeypatch.setattr(_durf_module, "_consent_safe_active", lambda: True)
        capture_spy = MagicMock()
        monkeypatch.setattr(_durf_module, "capture_tmux_text", capture_spy)

        source = DURFCairoSource(registry=_registry(registry_paths), start_thread=False)
        try:
            snapshot = source._poll_once(now=100.0)
        finally:
            source.stop()

        assert capture_spy.call_count == 0
        assert snapshot.wcs_row["mode"] == "suppressed"
        assert snapshot.wcs_row["egress_allowed"] is False
        assert snapshot.panes[0].suppressed_reason == "consent_safe"

    def test_source_state_shape_for_clean_visible_lane(
        self, registry_paths: tuple[Path, Path, Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, relay_dir, claim_dir, health_path = registry_paths
        (claim_dir / "cc-active-task-cx-cyan").write_text(
            "coding-session-livestream-homage-ward\n",
            encoding="utf-8",
        )
        (relay_dir / "cx-cyan.yaml").write_text(
            yaml.safe_dump(
                {
                    "status": "claimed",
                    "task_id": "coding-session-livestream-homage-ward",
                    "branch": "codex/cx-cyan-coding-session-livestream-homage-ward",
                }
            ),
            encoding="utf-8",
        )
        _write_health(health_path)
        monkeypatch.setattr(_durf_module, "_consent_safe_active", lambda: False)
        monkeypatch.setattr(_durf_module, "_unsafe_public_bypass_active", lambda: False)
        monkeypatch.setattr(
            _durf_module,
            "capture_tmux_text",
            MagicMock(
                return_value=_durf_module.TmuxCaptureResult(
                    True,
                    lines=(
                        "uv run pytest tests/studio_compositor/test_durf_source.py -q",
                        "12 passed",
                    ),
                )
            ),
        )

        source = DURFCairoSource(registry=_registry(registry_paths), start_thread=False)
        try:
            snapshot = source._poll_once(now=100.0)
            state = source.state()
        finally:
            source.stop()

        assert snapshot.wcs_row["surface_id"] == "coding_sessions.durf"
        assert snapshot.wcs_row["mode"] == "text_panes"
        assert snapshot.wcs_row["visible_lanes"] == ["cx-cyan"]
        assert snapshot.wcs_row["public_claim_ceiling"] == "work_trace_visible"
        assert snapshot.wcs_row["redaction_state"] == "clean"
        assert snapshot.wcs_row["egress_allowed"] is True
        assert state["wcs"]["surface_id"] == "coding_sessions.durf"

    def test_stale_pane_helper_marks_old_capture(self) -> None:
        pane = DURFPaneState(
            lane_id="cx-cyan",
            glyph="C-<>",
            tmux_target="hapax-codex-cx-cyan:0.0",
            visible=True,
            lines=("old",),
            captured_at=50.0,
            redaction_state="clean",
        )

        assert is_pane_stale(pane, now=100.0, stale_after_s=20.0) is True
        assert is_pane_stale(pane, now=55.0, stale_after_s=20.0) is False

    def test_wcs_row_records_redacted_suppression(self) -> None:
        pane = DURFPaneState(
            lane_id="cx-cyan",
            glyph="C-<>",
            tmux_target="hapax-codex-cx-cyan:0.0",
            visible=False,
            captured_at=100.0,
            redaction_state="suppress",
            suppressed_reason="bearer_token",
        )

        row = build_wcs_row((pane,), now=100.0, egress_allowed=True)

        assert row["mode"] == "metadata"
        assert row["redaction_state"] == "suppressed"
        assert row["suppressed_lanes"] == [
            {
                "lane_id": "cx-cyan",
                "reason": "bearer_token",
                "redaction_state": "suppress",
            }
        ]

    def test_render_smoke_nonblank_without_dashboard_labels(self, codex_config: Path) -> None:
        import cairo

        pane = DURFPaneState(
            lane_id="cx-cyan",
            glyph="C-<>",
            tmux_target="hapax-codex-cx-cyan:0.0",
            visible=True,
            lines=("uv run pytest tests/studio_compositor/test_durf_source.py -q", "15 passed"),
            captured_at=100.0,
            redaction_state="clean",
        )
        source = DURFCairoSource(config_path=codex_config, start_thread=False)
        try:
            source._snapshot = DURFSourceSnapshot(
                panes=(pane,),
                captured_at=100.0,
                wcs_row=build_wcs_row((pane,), now=100.0, egress_allowed=True),
            )
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 640, 360)
            cr = cairo.Context(surface)
            source.render_content(cr, 640, 360, 0.0, {"alpha": 0.9})
            assert any(byte != 0 for byte in bytes(surface.get_data()))
            rendered_text = "\n".join(pane.lines)
            assert "DURF" not in rendered_text
            assert "SESSION" not in rendered_text
        finally:
            source.stop()


class TestDURFReflectionLayer:
    def test_reflection_lines_use_last_two_redacted_pane_lines(self) -> None:
        lines = ("claim acquired", "uv run pytest", "17 passed")

        assert _coding_activity_module._reflection_lines(lines) == ("17 passed", "uv run pytest")

    def test_reflection_warp_is_slow_and_bounded(self) -> None:
        offset_0 = _coding_activity_module._reflection_warp_offset(0.0)
        offset_5 = _coding_activity_module._reflection_warp_offset(5.0)
        offset_10 = _coding_activity_module._reflection_warp_offset(10.0)

        assert abs(offset_0) <= _coding_activity_module._REFLECTION_WARP_MAX_PX
        assert abs(offset_5) <= _coding_activity_module._REFLECTION_WARP_MAX_PX
        assert abs(offset_10) <= _coding_activity_module._REFLECTION_WARP_MAX_PX
        assert offset_0 != pytest.approx(offset_5)

    def test_reflection_layer_renders_only_in_bottom_region(self, codex_config: Path) -> None:
        import cairo

        rect = (20, 20, 300, 140)
        rx, ry, rw, rh = _coding_activity_module._reflection_region(rect)
        pane = DURFPaneState(
            lane_id="cx-cyan",
            glyph="C-<>",
            tmux_target="hapax-codex-cx-cyan:0.0",
            visible=True,
            lines=(
                "uv run pytest tests/studio_compositor/test_durf_source.py -q",
                "reflection layer pinned",
                "18 passed",
            ),
            captured_at=100.0,
            redaction_state="clean",
        )
        source = CodingActivityReveal(config_path=codex_config, start_thread=False)
        try:
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 360, 200)
            cr = cairo.Context(surface)
            source._render_reflection_layer(cr, rect, pane, alpha=1.0, t=0.0)
            assert _surface_region_has_signal(surface, x=rx, y=ry, w=rw, h=rh)
            assert not _surface_region_has_signal(surface, x=20, y=20, w=300, h=40)
        finally:
            source.stop()


class TestLayoutIntegration:
    def test_default_layout_includes_durf(self) -> None:
        from shared.compositor_model import Layout

        path = (
            Path(__file__).resolve().parent.parent.parent
            / "config"
            / "compositor-layouts"
            / "default.json"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        layout = Layout.model_validate(data)
        assert any(s.id == "durf" for s in layout.sources)
        assert any(s.id == "durf-fullframe" for s in layout.surfaces)
        assert any(a.source == "durf" for a in layout.assignments)

    def test_durf_source_full_frame_geometry(self) -> None:
        path = (
            Path(__file__).resolve().parent.parent.parent
            / "config"
            / "compositor-layouts"
            / "default.json"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        surf = next(s for s in data["surfaces"] if s["id"] == "durf-fullframe")
        assert surf["geometry"]["w"] == 1920
        assert surf["geometry"]["h"] == 1080
        # z=5 per antigrav constellation intent: DURF is a BACKGROUND
        # substrate (faint full-frame text under Sierpinski + cameras +
        # wards), not a foreground occluder. Earlier z=50 was a draft
        # contract that contradicted the constellation aesthetic and made
        # DURF dominate the frame (operator visual feedback 2026-05-06).
        assert surf["z_order"] == 5


# ── Cc-task ``activity-reveal-ward-p1-durf-migration`` ──────────────────────


class TestActivityRevealMigration:
    """Five new tests for the P1 lift into the activity-reveal-ward family.

    Coverage: alias resolution, FSM integration timings, suppression
    wiring, redaction unchanged, claim score map.
    """

    def test_alias_resolution(self) -> None:
        """``DURFCairoSource`` alias resolves to ``CodingActivityReveal``.

        Both the module-level attribute on ``durf_source`` (via the
        ``__getattr__`` shim) and the ``cairo_sources`` registry entry
        return the same class.
        """

        # Module-level alias.
        assert _durf_module.DURFCairoSource is CodingActivityReveal
        assert DURFCairoSource is CodingActivityReveal
        # cairo_sources registry — both names resolve to the same class.
        assert get_cairo_source_class("CodingActivityReveal") is CodingActivityReveal
        assert get_cairo_source_class("DURFCairoSource") is CodingActivityReveal

    def test_inherits_both_parents_and_declares_family_contract(self) -> None:
        """``CodingActivityReveal`` is a Cairo source AND a family member."""

        assert issubclass(CodingActivityReveal, HomageTransitionalSource)
        assert issubclass(CodingActivityReveal, ActivityRevealMixin)
        # Mixin-required class vars.
        assert CodingActivityReveal.WARD_ID == "durf"
        assert CodingActivityReveal.SOURCE_KIND == "cairo"
        assert (
            frozenset({"album", "gem", "grounding_provenance_ticker"})
            == CodingActivityReveal.SUPPRESS_WHEN_ACTIVE
        )

    def test_fsm_integration_timings(self, codex_config: Path) -> None:
        """Constructor wires ``entering_duration_s=0.4`` and ``exiting_duration_s=0.6``.

        Matches legacy ``durf_source._ENTER_RAMP_MS=400`` /
        ``_EXIT_RAMP_MS=600``.
        """

        src = CodingActivityReveal(config_path=codex_config, start_thread=False)
        try:
            assert src.transition_state in (
                TransitionState.HOLD,
                TransitionState.ABSENT,
                TransitionState.ENTERING,
            )
            assert src._entering_duration_s == pytest.approx(0.4)
            assert src._exiting_duration_s == pytest.approx(0.6)
        finally:
            src.stop()

    def test_suppression_writes_visible_false_when_gate_active(
        self,
        registry_paths: tuple[Path, Path, Path, Path],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Gate-active poll cycle writes ``visible=false`` to the three
        suppressed wards' ``ward-properties.json`` entries."""

        from agents.studio_compositor import ward_properties as wp

        # Redirect the ward-properties JSON to tmp + clear the cache so
        # the test reads only what this test wrote.
        ward_path = tmp_path / "ward-properties.json"
        monkeypatch.setattr(wp, "WARD_PROPERTIES_PATH", ward_path)
        wp.clear_ward_properties_cache()

        # Wire registry + claim + relay state so the gate is active.
        _, relay_dir, claim_dir, health_path = registry_paths
        (claim_dir / "cc-active-task-cx-cyan").write_text(
            "coding-session-livestream-homage-ward\n",
            encoding="utf-8",
        )
        (relay_dir / "cx-cyan.yaml").write_text(
            yaml.safe_dump(
                {
                    "status": "claimed",
                    "task_id": "coding-session-livestream-homage-ward",
                    "branch": "codex/cx-cyan-coding-session-livestream-homage-ward",
                }
            ),
            encoding="utf-8",
        )
        _write_health(health_path)
        # Force the consent path to "not consent_safe" so the gate
        # decision uses pane visibility, and stub the tmux capture so a
        # selected lane comes back visible.
        monkeypatch.setattr(_durf_module, "_consent_safe_active", lambda: False)
        monkeypatch.setattr(_durf_module, "_unsafe_public_bypass_active", lambda: False)
        monkeypatch.setattr(
            _durf_module,
            "capture_tmux_text",
            lambda *args, **kwargs: _durf_module.TmuxCaptureResult(
                ok=True, lines=("ok line one", "ok line two")
            ),
        )

        src = CodingActivityReveal(registry=_registry(registry_paths), start_thread=False)
        try:
            snapshot = src._poll_once(now=100.0)
            # Gate must actually be active for the suppression to fire.
            assert any(p.visible for p in snapshot.panes)
        finally:
            src.stop()

        # ward-properties.json now carries ``visible=false`` for all
        # three suppressed wards.
        for ward_id in CodingActivityReveal.SUPPRESS_WHEN_ACTIVE:
            props = wp.get_specific_ward_properties(ward_id)
            assert props is not None, f"no entry written for {ward_id}"
            assert props.visible is False, f"{ward_id}: expected visible=False, got {props.visible}"

    def test_redaction_unchanged(self) -> None:
        """The redaction pipeline (RISK_PATTERNS, redact_terminal_lines)
        keeps the same behaviour the legacy DURFCairoSource relied on."""

        # Lines containing a known risk substring should suppress.
        suppressed = redact_terminal_lines(("ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQDxxx",))
        assert suppressed.action == RedactionAction.SUPPRESS

        # Operator legal-name pattern still suppresses.
        legal_hit = redact_terminal_lines(("git log Ryan Kleeberger",))
        assert legal_hit.action == RedactionAction.SUPPRESS

        # Clean text passes through.
        clean = redact_terminal_lines(("def foo(): return 42", "tests pass"))
        assert clean.action != RedactionAction.SUPPRESS

    def test_claim_score_maps_visible_pane_count(self, codex_config: Path) -> None:
        """``_compute_claim_score`` returns visible-pane-count / 4 in [0, 1].

        Drives the snapshot directly to exercise the score map without
        spinning up the full registry / capture path.
        """

        src = CodingActivityReveal(config_path=codex_config, start_thread=False)
        try:

            def _make_pane(visible: bool, lane_id: str) -> DURFPaneState:
                return DURFPaneState(
                    lane_id=lane_id,
                    glyph="?",
                    tmux_target=None,
                    visible=visible,
                )

            # 0 visible → 0.0
            with src._snapshot_lock:
                src._snapshot = DURFSourceSnapshot(panes=(), captured_at=0.0)
            assert src._compute_claim_score() == pytest.approx(0.0)

            # 2 visible / 4 → 0.5
            with src._snapshot_lock:
                src._snapshot = DURFSourceSnapshot(
                    panes=(
                        _make_pane(True, "cx-cyan"),
                        _make_pane(False, "cx-blue"),
                        _make_pane(True, "cx-violet"),
                        _make_pane(False, "cx-amber"),
                    ),
                    captured_at=0.0,
                )
            assert src._compute_claim_score() == pytest.approx(0.5)

            # 4 visible → 1.0 (full score)
            with src._snapshot_lock:
                src._snapshot = DURFSourceSnapshot(
                    panes=tuple(_make_pane(True, f"cx-{i}") for i in range(4)),
                    captured_at=0.0,
                )
            assert src._compute_claim_score() == pytest.approx(1.0)

            # 5 visible → still capped at 1.0 (defensive against >4)
            with src._snapshot_lock:
                src._snapshot = DURFSourceSnapshot(
                    panes=tuple(_make_pane(True, f"cx-{i}") for i in range(5)),
                    captured_at=0.0,
                )
            assert src._compute_claim_score() == pytest.approx(1.0)
        finally:
            src.stop()
