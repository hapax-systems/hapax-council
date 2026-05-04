"""Default compositor layout validation tests.

Source-registry epic Phase D task 12. These tests assert that the
on-disk baseline layout at ``config/compositor-layouts/default.json``
parses as a valid ``shared.compositor_model.Layout`` and carries the
expected source/surface/assignment shape.

Task 13 will extend this file with end-to-end compositor loader tests
(``load_layout_or_fallback``) once that helper lands in ``compositor.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.compositor_model import Layout

DEFAULT_JSON = Path(__file__).parents[2] / "config" / "compositor-layouts" / "default.json"


def test_default_json_exists_and_is_valid_layout() -> None:
    assert DEFAULT_JSON.exists(), f"missing {DEFAULT_JSON}"
    raw = json.loads(DEFAULT_JSON.read_text())
    layout = Layout.model_validate(raw)

    assert layout.name == "default"

    source_ids = {s.id for s in layout.sources}
    assert source_ids == {
        "token_pole",
        "album",
        "stream_overlay",
        "sierpinski",
        "reverie",
        # Volitional-director epic Phase 4 legibility surfaces
        # (PR #1017/§3.5 + follow-ups #1018).
        "activity_header",
        "stance_indicator",
        # chat_ambient retired 2026-04-23 (PR #1239 — aspect-ratio mismatch).
        "grounding_provenance_ticker",
        # Epic 2 Phase C (2026-04-17) — hothouse pressure surfaces.
        "impingement_cascade",
        "recruitment_candidate_panel",
        "thinking_indicator",
        "pressure_gauge",
        "activity_variety_log",
        # Epic 2 Phase D — operator-always-here indicator.
        "whos_here",
        "durf",
        "m8-display",
        # cc-task ``re-splay-homage-ward-steam-deck`` (2026-05-04).
        "steamdeck-display",
        "egress_footer",
        # HOMAGE follow-on #191 (2026-04-21) — GEM (Graffiti Emphasis
        # Mural) is the 15th HOMAGE ward; lower-band geometry, retires
        # captions in same surface area. See
        # docs/superpowers/plans/2026-04-21-gem-ward-activation-plan.md.
        "gem",
        # cc-task ``programme-banner-ward`` (PR #2366, 2026-05-03).
        "programme_banner",
        # ytb-LORE-EXT family (2026-05-04, ward-family-compositor-layout-
        # integration cc-task) — three lore-surface wards composing the
        # mid-band lore strip. Each is feature-flagged OFF by default.
        # The fourth family member (interactive_lore_query, #2484) is
        # not wired here: its constructor requires a non-default
        # ``allowlist`` kwarg incompatible with the compositor's
        # no-arg auto-construction path; wiring it needs a follow-up.
        "precedent_ticker",
        "programme_history",
        "research_instrument_dashboard",
    }

    # LRR Phase 2 item 10: video_out surfaces declared for OutputRouter.from_layout()
    # enumeration. The 4 pip-* quadrants are the input surfaces; the 3 video_out_*
    # surfaces are the output sinks (v4l2 loopback, RTMP, HLS).
    # Volitional-director Phase 4 adds 4 legibility surfaces.
    surface_ids = {s.id for s in layout.surfaces}
    assert surface_ids == {
        "pip-ul",
        "pip-ur",
        "pip-ll",
        "pip-lr",
        "video_out_v4l2_loopback",
        "video_out_rtmp_mediamtx",
        "video_out_hls_playlist",
        "activity-header-top",
        "stance-indicator-tr",
        "grounding-ticker-bl",
        # Epic 2 Phase C hothouse surfaces.
        "impingement-cascade-midright",
        "recruitment-candidate-top",
        "thinking-indicator-tr",
        "pressure-gauge-ul",
        "activity-variety-log-mid",
        # Epic 2 Phase D — operator-always-here indicator.
        "whos-here-tr",
        "durf-fullframe",
        "m8-display-surface",
        "m8-display-tiny-surface",
        # cc-task ``re-splay-homage-ward-steam-deck`` (2026-05-04).
        "steamdeck-display-pip",
        "steamdeck-display-fullscreen",
        "egress-footer-bottom",
        # HOMAGE follow-on #191 — GEM mural surface (lower-band).
        "gem-mural-bottom",
        # cc-task ``programme-banner-ward`` (PR #2366, 2026-05-03).
        "programme-banner-top",
        # ytb-LORE-EXT mid-band lore strip (2026-05-04). Three slots
        # span the mid-band x=20 → x=1520 at y=380, the family's
        # "side-by-side" rendering.
        "lore-precedent-ticker",
        "lore-programme-history",
        "lore-research-instrument-dashboard",
    }

    assignment_pairs = {(a.source, a.surface) for a in layout.assignments}
    assert assignment_pairs == {
        ("token_pole", "pip-ul"),
        ("reverie", "pip-ur"),
        ("album", "pip-ll"),
        ("stream_overlay", "pip-lr"),
        # captions retired at GEM cutover (2026-04-21); GEM ward (#191)
        # takes the lower-band geometry.
        # Volitional-director Phase 4 legibility assignments.
        ("activity_header", "activity-header-top"),
        ("stance_indicator", "stance-indicator-tr"),
        ("grounding_provenance_ticker", "grounding-ticker-bl"),
        # Epic 2 Phase C hothouse assignments.
        ("impingement_cascade", "impingement-cascade-midright"),
        ("recruitment_candidate_panel", "recruitment-candidate-top"),
        ("thinking_indicator", "thinking-indicator-tr"),
        ("pressure_gauge", "pressure-gauge-ul"),
        ("activity_variety_log", "activity-variety-log-mid"),
        # Epic 2 Phase D.
        ("whos_here", "whos-here-tr"),
        ("durf", "durf-fullframe"),
        ("m8-display", "m8-display-surface"),
        ("m8-display", "m8-display-tiny-surface"),
        # cc-task ``re-splay-homage-ward-steam-deck`` (2026-05-04).
        ("steamdeck-display", "steamdeck-display-pip"),
        ("steamdeck-display", "steamdeck-display-fullscreen"),
        ("egress_footer", "egress-footer-bottom"),
        # HOMAGE follow-on #191 — GEM mural assignment.
        ("gem", "gem-mural-bottom"),
        # cc-task ``programme-banner-ward`` (PR #2366, 2026-05-03).
        ("programme_banner", "programme-banner-top"),
        # ytb-LORE-EXT family (2026-05-04).
        ("precedent_ticker", "lore-precedent-ticker"),
        ("programme_history", "lore-programme-history"),
        ("research_instrument_dashboard", "lore-research-instrument-dashboard"),
    }


def test_default_json_source_backends_match_registry_dispatch() -> None:
    """Each source's backend matches the SourceRegistry dispatcher keys."""
    raw = json.loads(DEFAULT_JSON.read_text())
    layout = Layout.model_validate(raw)

    backend_by_id = {s.id: s.backend for s in layout.sources}
    assert backend_by_id == {
        "gem": "cairo",
        "token_pole": "cairo",
        "album": "cairo",
        "stream_overlay": "cairo",
        "sierpinski": "cairo",
        "reverie": "shm_rgba",
        # Volitional-director Phase 4 legibility sources.
        "activity_header": "cairo",
        "stance_indicator": "cairo",
        "grounding_provenance_ticker": "cairo",
        # Epic 2 Phase C hothouse sources.
        "impingement_cascade": "cairo",
        "recruitment_candidate_panel": "cairo",
        "thinking_indicator": "cairo",
        "pressure_gauge": "cairo",
        "activity_variety_log": "cairo",
        # Epic 2 Phase D.
        "whos_here": "cairo",
        "durf": "cairo",
        "m8-display": "shm_rgba",
        # cc-task ``re-splay-homage-ward-steam-deck`` (2026-05-04).
        "steamdeck-display": "shm_rgba",
        "egress_footer": "cairo",
        # cc-task ``programme-banner-ward`` (PR #2366, 2026-05-03) +
        # ytb-LORE-EXT family (2026-05-04).
        "programme_banner": "cairo",
        "precedent_ticker": "cairo",
        "programme_history": "cairo",
        "research_instrument_dashboard": "cairo",
    }


def test_default_json_cairo_sources_name_registered_classes() -> None:
    """Cairo sources carry a ``class_name`` matching the cairo_sources registry."""
    from agents.studio_compositor.cairo_sources import get_cairo_source_class

    raw = json.loads(DEFAULT_JSON.read_text())
    layout = Layout.model_validate(raw)

    for source in layout.sources:
        if source.backend != "cairo":
            continue
        class_name = source.params.get("class_name")
        assert class_name, f"source {source.id}: cairo backend requires class_name"
        cls = get_cairo_source_class(class_name)
        assert cls is not None


def test_default_json_reverie_points_at_producer_shm_path() -> None:
    """The reverie source reads the exact shm path hapax-visual's write_side_output writes.

    Coupling regression pin: if either side of the producer/consumer
    pair moves, this test flags the drift. The producer path is
    ``SIDE_OUTPUT_FILE`` in ``hapax-logos/crates/hapax-visual/src/output.rs``.
    """
    raw = json.loads(DEFAULT_JSON.read_text())
    layout = Layout.model_validate(raw)

    reverie = next(s for s in layout.sources if s.id == "reverie")
    assert reverie.params.get("shm_path") == "/dev/shm/hapax-sources/reverie.rgba"


def test_default_json_operator_quadrant_defaults() -> None:
    """Four-quadrant operator default: reverie UR, token_pole UL, album LL, stream_overlay LR.

    Post-epic operator spec: every quadrant has a default source so the
    stream output is legible the moment the compositor boots. These
    assignments are a starting point — Hapax content programming drives
    runtime re-assignment via the affordance pipeline + command registry.
    """
    raw = json.loads(DEFAULT_JSON.read_text())
    layout = Layout.model_validate(raw)

    assignments_by_surface = {a.surface: a.source for a in layout.assignments}
    assert assignments_by_surface["pip-ul"] == "token_pole"
    assert assignments_by_surface["pip-ur"] == "reverie"
    assert assignments_by_surface["pip-ll"] == "album"
    assert assignments_by_surface["pip-lr"] == "stream_overlay"


def test_default_json_stream_overlay_source_is_registered() -> None:
    """stream_overlay appears in the source list with a registered class_name."""
    from agents.studio_compositor.cairo_sources import get_cairo_source_class

    raw = json.loads(DEFAULT_JSON.read_text())
    layout = Layout.model_validate(raw)

    stream_overlay = next(
        (s for s in layout.sources if s.id == "stream_overlay"),
        None,
    )
    assert stream_overlay is not None, "stream_overlay source missing from default.json"
    assert stream_overlay.backend == "cairo"
    class_name = stream_overlay.params.get("class_name")
    assert class_name == "StreamOverlayCairoSource"
    # Getting the class via the registry must not raise — that's the
    # `construct_backend` path the compositor hits at startup.
    cls = get_cairo_source_class(class_name)
    assert cls.__name__ == "StreamOverlayCairoSource"


# chat_ambient retired 2026-04-23 (PR #1239 — aspect-ratio mismatch).
# Original test pinned its binding to ChatAmbientWard; the source and
# surface are no longer in default.json so the pin is obsolete.


# ---------------------------------------------------------------------------
# Phase D task 13 — load_layout_or_fallback
# ---------------------------------------------------------------------------


def test_load_layout_or_fallback_reads_valid_file(tmp_path: Path) -> None:
    """Reads a Layout JSON file from disk and returns the parsed model."""
    from agents.studio_compositor.compositor import load_layout_or_fallback

    src = DEFAULT_JSON.read_text()
    target = tmp_path / "default.json"
    target.write_text(src)

    layout = load_layout_or_fallback(target)

    assert layout.name == "default"
    source_ids = {s.id for s in layout.sources}
    assert source_ids == {
        "token_pole",
        "album",
        "stream_overlay",
        "sierpinski",
        "reverie",
        # Volitional-director Phase 4 legibility additions.
        "activity_header",
        "stance_indicator",
        # chat_ambient retired 2026-04-23 (PR #1239 — aspect-ratio mismatch).
        "grounding_provenance_ticker",
        # Epic 2 Phase C hothouse additions.
        "impingement_cascade",
        "recruitment_candidate_panel",
        "thinking_indicator",
        "pressure_gauge",
        "activity_variety_log",
        # Epic 2 Phase D.
        "whos_here",
        "durf",
        "m8-display",
        # cc-task ``re-splay-homage-ward-steam-deck`` (2026-05-04).
        "steamdeck-display",
        "egress_footer",
        # HOMAGE follow-on #191 — GEM mural ward (15th HOMAGE).
        "gem",
        # cc-task ``programme-banner-ward`` (PR #2366, 2026-05-03).
        "programme_banner",
        # ytb-LORE-EXT family (2026-05-04, ward-family-compositor-layout-
        # integration cc-task) — three lore-surface wards on the
        # default layout's mid-band lore strip.
        "precedent_ticker",
        "programme_history",
        "research_instrument_dashboard",
    }


def test_load_layout_or_fallback_uses_fallback_when_file_missing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Missing file path resolves to the hardcoded fallback without raising."""
    import logging

    from agents.studio_compositor.compositor import load_layout_or_fallback

    caplog.set_level(logging.WARNING, logger="agents.studio_compositor.compositor")
    layout = load_layout_or_fallback(tmp_path / "does-not-exist.json")

    assert layout.name == "default"
    assert any("fallback" in rec.message.lower() for rec in caplog.records), (
        "missing-file path should log a fallback warning"
    )


def test_load_layout_or_fallback_uses_fallback_on_invalid_json(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Malformed JSON resolves to fallback without raising."""
    import logging

    from agents.studio_compositor.compositor import load_layout_or_fallback

    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    caplog.set_level(logging.WARNING, logger="agents.studio_compositor.compositor")

    layout = load_layout_or_fallback(broken)

    assert layout.name == "default"
    assert any("fallback" in rec.message.lower() for rec in caplog.records)


def test_load_layout_or_fallback_uses_fallback_on_schema_violation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Valid JSON that fails pydantic validation also resolves to fallback."""
    import logging

    from agents.studio_compositor.compositor import load_layout_or_fallback

    bad_schema = tmp_path / "bad-schema.json"
    bad_schema.write_text(json.dumps({"not_a_layout": True}))
    caplog.set_level(logging.WARNING, logger="agents.studio_compositor.compositor")

    layout = load_layout_or_fallback(bad_schema)

    assert layout.name == "default"
    assert any("fallback" in rec.message.lower() for rec in caplog.records)


def test_load_layout_or_fallback_fires_ntfy_on_missing_file(tmp_path: Path, monkeypatch) -> None:
    """Post-epic audit Phase 1 finding #6 regression pin.

    AC-8 ("deleting default.json → fallback layout + ntfy") only had
    the fallback half wired. ``load_layout_or_fallback`` must also
    fire a one-shot notification so operators see the fallback event
    without grepping logs.
    """
    from agents.studio_compositor import compositor as compositor_module

    sent: list[dict] = []

    def _fake_send(**kwargs) -> None:
        sent.append(kwargs)

    # Patch ``shared.notify.send_notification`` at the module level —
    # ``_notify_fallback`` imports it lazily inside its body, so the
    # monkeypatch lands on the shared module, not a local alias.
    import shared.notify as notify_mod

    monkeypatch.setattr(notify_mod, "send_notification", _fake_send)

    _ = compositor_module.load_layout_or_fallback(tmp_path / "does-not-exist.json")

    assert len(sent) == 1, "exactly one ntfy should fire on fallback"
    body = sent[0].get("body", "")
    assert "does-not-exist.json" in body
    assert "file missing" in body


def test_fallback_layout_parses_to_same_shape_as_default_json() -> None:
    """The hardcoded _FALLBACK_LAYOUT is structurally identical to default.json.

    Regression pin: if someone edits one side without the other, this
    fires. The fallback is the rescue path when the JSON cannot be
    loaded — it should produce the same runtime layout.
    """
    from agents.studio_compositor.compositor import _FALLBACK_LAYOUT

    raw = json.loads(DEFAULT_JSON.read_text())
    disk = Layout.model_validate(raw)

    assert _FALLBACK_LAYOUT.name == disk.name
    assert {s.id for s in _FALLBACK_LAYOUT.sources} == {s.id for s in disk.sources}
    assert {s.id for s in _FALLBACK_LAYOUT.surfaces} == {s.id for s in disk.surfaces}
    assert {(a.source, a.surface) for a in _FALLBACK_LAYOUT.assignments} == {
        (a.source, a.surface) for a in disk.assignments
    }


def test_load_layout_or_fallback_rescales_to_canvas_size() -> None:
    """A+ Stage 2 invariant: layout JSON coords (1920×1080) get rescaled
    to the active canvas (LAYOUT_COORD_SCALE) before reaching the renderer.

    Regression pin for the bug where ``load_layout_or_fallback`` returned
    the unscaled Layout, leaving every ward shifted ~33% right of its
    intended position and right-edge wards off-canvas.
    """
    from agents.studio_compositor.compositor import load_layout_or_fallback
    from agents.studio_compositor.config import LAYOUT_COORD_SCALE

    layout = load_layout_or_fallback(DEFAULT_JSON)
    activity_header = next(s for s in layout.surfaces if s.id == "activity-header-top")
    expected_x = int(round(560 * LAYOUT_COORD_SCALE))
    expected_w = int(round(800 * LAYOUT_COORD_SCALE))
    assert activity_header.geometry.x == expected_x, (
        f"activity-header-top x should be {expected_x} (560 × {LAYOUT_COORD_SCALE}), "
        f"got {activity_header.geometry.x}"
    )
    assert activity_header.geometry.w == expected_w
    # chat-legend-right retired 2026-04-23 (PR #1239). Stance indicator is
    # the closest-analogue right-edge ward; pin its rescale to cover the
    # same "right-edge wards off-canvas" regression space.
    stance_ind = next(s for s in layout.surfaces if s.id == "stance-indicator-tr")
    # stance-indicator-tr x=1800 in 1920-coord space.
    expected_stance_x = int(round(1800 * LAYOUT_COORD_SCALE))
    assert stance_ind.geometry.x == expected_stance_x


# HARDM retired 2026-04-23 (GEAL spec §12) — the z-order collision tests
# that pinned thinking-indicator and whos-here above HARDM are no longer
# applicable because HARDM is no longer in the layout. GEAL inhabits the
# central Sierpinski triangle instead of a dedicated 256×256 surface, so
# upper-right z-cluster collisions cannot recur through this vector.
