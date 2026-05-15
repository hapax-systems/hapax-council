from __future__ import annotations

import pytest

from shared.layout_identity_contract import (
    ActiveMetricsSnapshot,
    LayoutIdentitySnapshot,
    PersistenceSnapshot,
    RenderedReadback,
    validate_layout_identity,
)


def _unanimous_snapshot(name: str = "segment-detail") -> LayoutIdentitySnapshot:
    return LayoutIdentitySnapshot(
        filename=name,
        internal_name=name,
        selected_layout=name,
        rendered_readback=RenderedReadback(
            active_layout=name,
            visible_wards=("artifact-detail-panel",),
            source_placements=("cam-desk", "cam-overhead"),
        ),
        active_metrics=ActiveMetricsSnapshot(gauge_layout=name, gauge_value=1.0),
        persistence_state=PersistenceSnapshot(
            autosaver_path=f"{name}.json",
            autosaver_layout_name=name,
            last_write_age_s=1.5,
        ),
        capture_source="test",
    )


def _filename_internal_mismatch() -> LayoutIdentitySnapshot:
    return LayoutIdentitySnapshot(
        filename="default",
        internal_name="garage-door",
        selected_layout="default",
        rendered_readback=RenderedReadback(active_layout="default"),
        active_metrics=ActiveMetricsSnapshot(gauge_layout="default", gauge_value=1.0),
        persistence_state=PersistenceSnapshot(
            autosaver_path="default.json", autosaver_layout_name="default"
        ),
        capture_source="test",
    )


def _metrics_disagree_with_selection() -> LayoutIdentitySnapshot:
    return LayoutIdentitySnapshot(
        filename="segment-detail",
        internal_name="segment-detail",
        selected_layout="segment-detail",
        rendered_readback=RenderedReadback(
            active_layout="segment-detail",
            visible_wards=("artifact-detail-panel",),
        ),
        active_metrics=ActiveMetricsSnapshot(gauge_layout="default", gauge_value=1.0),
        persistence_state=PersistenceSnapshot(autosaver_layout_name="segment-detail"),
        capture_source="test",
    )


def _may_11_full_incident() -> LayoutIdentitySnapshot:
    return LayoutIdentitySnapshot(
        filename="segment-detail",
        internal_name="segment-detail",
        selected_layout="segment-detail",
        rendered_readback=RenderedReadback(active_layout="default"),
        active_metrics=ActiveMetricsSnapshot(gauge_layout="default", gauge_value=1.0),
        persistence_state=PersistenceSnapshot(
            autosaver_layout_name="default",
            write_skipped=True,
            skip_reason="name_mismatch",
        ),
        capture_source="test",
    )


class TestUnanimousIdentity:
    def test_all_layers_agree(self) -> None:
        report = validate_layout_identity(_unanimous_snapshot())
        assert report.unanimous is True
        assert report.canonical_name == "segment-detail"
        assert len(report.disagreements) == 0
        assert report.agreement_count == 6
        assert report.participating_count == 6
        assert len(report.absent_layers) == 0

    def test_all_layers_agree_default(self) -> None:
        report = validate_layout_identity(_unanimous_snapshot("default"))
        assert report.unanimous is True
        assert report.canonical_name == "default"

    def test_absent_layers_do_not_disagree(self) -> None:
        snapshot = LayoutIdentitySnapshot(
            filename="default",
            internal_name="default",
            selected_layout="default",
            rendered_readback=RenderedReadback(active_layout=None),
            active_metrics=ActiveMetricsSnapshot(gauge_layout=None),
            persistence_state=PersistenceSnapshot(autosaver_layout_name=None),
            capture_source="test",
        )
        report = validate_layout_identity(snapshot)
        assert report.unanimous is True
        assert report.canonical_name == "default"
        assert report.participating_count == 3
        assert len(report.absent_layers) == 3

    def test_all_absent_is_vacuously_unanimous(self) -> None:
        report = validate_layout_identity(LayoutIdentitySnapshot(capture_source="test"))
        assert report.unanimous is True
        assert report.canonical_name is None
        assert len(report.absent_layers) == 6


class TestFilenameInternalNameMismatch:
    def test_detects_mismatch(self) -> None:
        report = validate_layout_identity(_filename_internal_mismatch())
        assert report.unanimous is False
        fn_vs_name = [
            d
            for d in report.disagreements
            if {d.layer_a, d.layer_b} == {"filename", "internal_name"}
        ]
        assert len(fn_vs_name) == 1
        assert fn_vs_name[0].severity == "error"

    def test_detail_mentions_layout_store(self) -> None:
        report = validate_layout_identity(_filename_internal_mismatch())
        fn_vs_name = [
            d
            for d in report.disagreements
            if {d.layer_a, d.layer_b} == {"filename", "internal_name"}
        ]
        assert "LayoutStore" in fn_vs_name[0].detail

    def test_canonical_follows_majority(self) -> None:
        report = validate_layout_identity(_filename_internal_mismatch())
        assert report.canonical_name == "default"


class TestMetricsDisagreeWithSelection:
    def test_detects_metrics_mismatch(self) -> None:
        report = validate_layout_identity(_metrics_disagree_with_selection())
        assert report.unanimous is False
        metrics_d = [d for d in report.disagreements if "active_metrics" in (d.layer_a, d.layer_b)]
        assert len(metrics_d) >= 1
        assert all(d.severity == "error" for d in metrics_d)

    def test_canonical_is_segment_detail(self) -> None:
        report = validate_layout_identity(_metrics_disagree_with_selection())
        assert report.canonical_name == "segment-detail"


class TestMay11FullIncident:
    def test_detects_all_disagreements(self) -> None:
        report = validate_layout_identity(_may_11_full_incident())
        assert report.unanimous is False
        assert len(report.disagreements) >= 3

    def test_canonical_prefers_rendered_readback(self) -> None:
        report = validate_layout_identity(_may_11_full_incident())
        assert report.canonical_name == "default"

    def test_error_severity_on_selected_vs_rendered(self) -> None:
        report = validate_layout_identity(_may_11_full_incident())
        sel_vs_render = [
            d
            for d in report.disagreements
            if {d.layer_a, d.layer_b} == {"selected_layout", "rendered_readback"}
        ]
        assert len(sel_vs_render) == 1
        assert sel_vs_render[0].severity == "error"


class TestEdgeCases:
    def test_persistence_vs_internal_is_warning(self) -> None:
        snapshot = LayoutIdentitySnapshot(
            filename="default",
            internal_name="default",
            selected_layout="default",
            rendered_readback=RenderedReadback(active_layout="default"),
            active_metrics=ActiveMetricsSnapshot(gauge_layout="default"),
            persistence_state=PersistenceSnapshot(
                autosaver_layout_name="garage-door",
                write_skipped=True,
                skip_reason="name_mismatch",
            ),
            capture_source="test",
        )
        report = validate_layout_identity(snapshot)
        assert report.unanimous is False
        pi = [
            d
            for d in report.disagreements
            if {d.layer_a, d.layer_b} == {"persistence_state", "internal_name"}
        ]
        if pi:
            assert pi[0].severity == "warning"

    def test_snapshot_is_frozen(self) -> None:
        snapshot = _unanimous_snapshot()
        with pytest.raises(Exception):
            snapshot.filename = "hacked"  # type: ignore[misc]
