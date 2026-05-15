from __future__ import annotations

from shared.layout_identity_contract import (
    ActiveMetricsSnapshot,
    LayoutIdentityReport,
    LayoutIdentitySnapshot,
    LayerDisagreement,
    PersistenceSnapshot,
    RenderedReadback,
    hosting_gate,
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


def test_hosting_gate_passes_with_unanimous_non_legacy() -> None:
    report = validate_layout_identity(_unanimous_snapshot("segment-detail"))
    result = hosting_gate(report)
    assert result["ok"] is True
    assert result["reason"] == ""
    assert result["error_disagreements"] == []


def test_hosting_gate_blocks_on_identity_mismatch() -> None:
    snapshot = LayoutIdentitySnapshot(
        filename="segment-detail",
        internal_name="segment-detail",
        selected_layout="segment-detail",
        rendered_readback=RenderedReadback(active_layout="segment-detail"),
        active_metrics=ActiveMetricsSnapshot(gauge_layout="garage-door", gauge_value=1.0),
        persistence_state=PersistenceSnapshot(autosaver_layout_name="segment-detail"),
        capture_source="test",
    )
    report = validate_layout_identity(snapshot)
    assert not report.unanimous
    result = hosting_gate(report)
    assert result["ok"] is False
    assert result["reason"] == "identity_disagreement"
    assert len(result["error_disagreements"]) > 0
    assert all(d.severity == "error" for d in result["error_disagreements"])


def test_hosting_gate_blocks_on_default_layout() -> None:
    report = validate_layout_identity(_unanimous_snapshot("default"))
    assert report.unanimous
    result = hosting_gate(report)
    assert result["ok"] is False
    assert result["reason"] == "legacy_layout_active"
    assert result["error_disagreements"] == []


def test_hosting_gate_blocks_on_garage_door() -> None:
    report = validate_layout_identity(_unanimous_snapshot("garage-door"))
    assert report.unanimous
    result = hosting_gate(report)
    assert result["ok"] is False
    assert result["reason"] == "legacy_layout_active"


def test_hosting_gate_passes_with_warning_only_disagreements() -> None:
    # persistence_state disagreeing with non-error layers (no active_metrics) produces warnings only
    snapshot = LayoutIdentitySnapshot(
        filename="segment-detail",
        internal_name="segment-detail",
        selected_layout="segment-detail",
        rendered_readback=RenderedReadback(active_layout="segment-detail"),
        active_metrics=ActiveMetricsSnapshot(),
        persistence_state=PersistenceSnapshot(autosaver_layout_name="old-layout"),
        capture_source="test",
    )
    report = validate_layout_identity(snapshot)
    assert not report.unanimous
    assert len(report.disagreements) > 0
    # Confirm all disagreements are warnings only (no error-layer pairs)
    assert all(d.severity == "warning" for d in report.disagreements)
    result = hosting_gate(report)
    assert result["ok"] is True
    assert result["reason"] == ""
    assert result["error_disagreements"] == []


def test_hosting_gate_blocks_on_balanced_layout() -> None:
    report = validate_layout_identity(_unanimous_snapshot("balanced"))
    assert report.unanimous
    result = hosting_gate(report)
    assert result["ok"] is False
    assert result["reason"] == "legacy_layout_active"
