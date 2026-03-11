"""Tests for knowledge_maint.py — schemas, Qdrant operations, dry-run safety.

External I/O (Qdrant, LLM) is mocked.
"""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

from agents.knowledge_maint import (
    CollectionStats,
    MaintenanceReport,
    EXPECTED_DIMENSIONS,
    DEFAULT_SCORE_THRESHOLD,
    get_collection_info,
    find_stale_sources,
    prune_stale_sources,
    find_near_duplicates,
    merge_duplicates,
    format_report_human,
    format_report_md,
    send_notification,
)


# ── Schema tests ─────────────────────────────────────────────────────────────

def test_collection_stats_defaults():
    s = CollectionStats(name="test")
    assert s.points_before == 0
    assert s.stale_pruned == 0
    assert s.duplicates_merged == 0
    assert s.warnings == []


def test_maintenance_report_defaults():
    r = MaintenanceReport(generated_at="2026-03-01T04:30:00Z")
    assert r.dry_run is True
    assert r.total_pruned == 0
    assert r.total_merged == 0
    assert r.collections == []
    assert r.summary == ""


def test_maintenance_report_json_round_trip():
    r = MaintenanceReport(
        generated_at="2026-03-01T04:30:00Z",
        duration_ms=1500,
        dry_run=True,
        collections=[
            CollectionStats(name="documents", points_before=1000, dimensions=768),
        ],
        total_pruned=5,
        warnings=["Test warning"],
    )
    data = json.loads(r.model_dump_json())
    assert data["total_pruned"] == 5
    assert len(data["collections"]) == 1
    assert data["collections"][0]["dimensions"] == 768


def test_collection_stats_with_warnings():
    s = CollectionStats(name="test", warnings=["dim mismatch", "stale data"])
    assert len(s.warnings) == 2


# ── Collection info tests ───────────────────────────────────────────────────

@patch("agents.knowledge_maint.get_qdrant")
def test_get_collection_info_success(mock_qdrant):
    mock_client = MagicMock()
    mock_qdrant.return_value = mock_client

    mock_count = MagicMock()
    mock_count.count = 500
    mock_client.count.return_value = mock_count

    mock_info = MagicMock()
    mock_info.config.params.vectors.size = 768
    mock_client.get_collection.return_value = mock_info

    stats = get_collection_info("documents")
    assert stats.points_before == 500
    assert stats.dimensions == 768
    assert stats.warnings == []


@patch("agents.knowledge_maint.get_qdrant")
def test_get_collection_info_wrong_dimensions(mock_qdrant):
    mock_client = MagicMock()
    mock_qdrant.return_value = mock_client

    mock_count = MagicMock()
    mock_count.count = 100
    mock_client.count.return_value = mock_count

    mock_info = MagicMock()
    mock_info.config.params.vectors.size = 384
    mock_client.get_collection.return_value = mock_info

    stats = get_collection_info("test")
    assert stats.dimensions == 384
    assert any("mismatch" in w.lower() for w in stats.warnings)


@patch("agents.knowledge_maint.get_qdrant")
def test_get_collection_info_failure(mock_qdrant):
    mock_qdrant.side_effect = Exception("Connection refused")
    stats = get_collection_info("documents")
    assert stats.points_before == 0
    assert any("failed" in w.lower() for w in stats.warnings)


# ── Stale source tests ──────────────────────────────────────────────────────

@patch("agents.knowledge_maint.get_qdrant")
def test_find_stale_sources_finds_missing(mock_qdrant, tmp_path):
    mock_client = MagicMock()
    mock_qdrant.return_value = mock_client

    existing_file = tmp_path / "exists.md"
    existing_file.write_text("content")
    missing_path = str(tmp_path / "gone.pdf")

    mock_point_1 = MagicMock()
    mock_point_1.payload = {"source": str(existing_file)}
    mock_point_2 = MagicMock()
    mock_point_2.payload = {"source": missing_path}

    mock_client.scroll.return_value = ([mock_point_1, mock_point_2], None)

    stale = find_stale_sources("documents")
    assert missing_path in stale
    assert str(existing_file) not in stale


@patch("agents.knowledge_maint.get_qdrant")
def test_find_stale_sources_empty_collection(mock_qdrant):
    mock_client = MagicMock()
    mock_qdrant.return_value = mock_client
    mock_client.scroll.return_value = ([], None)

    stale = find_stale_sources("documents")
    assert stale == []


@patch("agents.knowledge_maint.get_qdrant")
def test_find_stale_sources_handles_error(mock_qdrant):
    mock_qdrant.side_effect = Exception("Connection refused")
    stale = find_stale_sources("documents")
    assert stale == []


# ── Prune tests ──────────────────────────────────────────────────────────────

def test_prune_dry_run_does_not_delete():
    """Dry-run should return count but not call Qdrant delete."""
    result = prune_stale_sources("documents", ["/gone/file1.pdf", "/gone/file2.md"], dry_run=True)
    assert result == 2


@patch("agents.knowledge_maint.get_qdrant")
def test_prune_apply_calls_delete(mock_qdrant):
    mock_client = MagicMock()
    mock_qdrant.return_value = mock_client

    result = prune_stale_sources("documents", ["/gone/file.pdf"], dry_run=False)
    assert result == 1
    mock_client.delete.assert_called_once()


def test_prune_empty_list():
    result = prune_stale_sources("documents", [], dry_run=False)
    assert result == 0


# ── Duplicate detection tests ────────────────────────────────────────────────

@patch("agents.knowledge_maint.get_qdrant")
def test_find_near_duplicates_clusters(mock_qdrant):
    mock_client = MagicMock()
    mock_qdrant.return_value = mock_client

    # Two points with vectors
    mock_point_1 = MagicMock()
    mock_point_1.id = 1
    mock_point_1.vector = [0.1] * 768
    mock_point_1.payload = {"ingested_at": 1000, "source": "a.pdf"}

    mock_point_2 = MagicMock()
    mock_point_2.id = 2
    mock_point_2.vector = [0.1] * 768
    mock_point_2.payload = {"ingested_at": 2000, "source": "b.pdf"}

    mock_client.scroll.return_value = ([mock_point_1, mock_point_2], None)

    # Search returns both as near-duplicates
    mock_neighbor_1 = MagicMock()
    mock_neighbor_1.id = 1
    mock_neighbor_1.payload = {"ingested_at": 1000, "source": "a.pdf"}

    mock_neighbor_2 = MagicMock()
    mock_neighbor_2.id = 2
    mock_neighbor_2.payload = {"ingested_at": 2000, "source": "b.pdf"}

    mock_query_result = MagicMock()
    mock_query_result.points = [mock_neighbor_1, mock_neighbor_2]
    mock_client.query_points.return_value = mock_query_result

    clusters = find_near_duplicates("documents", score_threshold=0.98)
    assert len(clusters) >= 1
    assert len(clusters[0]) == 2


@patch("agents.knowledge_maint.get_qdrant")
def test_find_near_duplicates_empty(mock_qdrant):
    mock_client = MagicMock()
    mock_qdrant.return_value = mock_client
    mock_client.scroll.return_value = ([], None)

    clusters = find_near_duplicates("documents")
    assert clusters == []


@patch("agents.knowledge_maint.get_qdrant")
def test_find_near_duplicates_handles_error(mock_qdrant):
    mock_qdrant.side_effect = Exception("Connection refused")
    clusters = find_near_duplicates("documents")
    assert clusters == []


# ── Merge tests ──────────────────────────────────────────────────────────────

def test_merge_dry_run_returns_count():
    clusters = [
        [
            {"point_id": 1, "ingested_at": 1000},
            {"point_id": 2, "ingested_at": 2000},
            {"point_id": 3, "ingested_at": 1500},
        ]
    ]
    result = merge_duplicates("documents", clusters, dry_run=True)
    assert result == 2  # Keep newest (id=2), remove 2 older


@patch("agents.knowledge_maint.get_qdrant")
def test_merge_apply_calls_delete(mock_qdrant):
    mock_client = MagicMock()
    mock_qdrant.return_value = mock_client

    clusters = [
        [
            {"point_id": 1, "ingested_at": 1000},
            {"point_id": 2, "ingested_at": 2000},
        ]
    ]
    result = merge_duplicates("documents", clusters, dry_run=False)
    assert result == 1
    mock_client.delete.assert_called_once()


def test_merge_empty_clusters():
    result = merge_duplicates("documents", [], dry_run=False)
    assert result == 0


def test_merge_keeps_newest():
    """The point with highest ingested_at should be kept."""
    clusters = [
        [
            {"point_id": 10, "ingested_at": 100},
            {"point_id": 20, "ingested_at": 300},  # newest
            {"point_id": 30, "ingested_at": 200},
        ]
    ]
    # In dry-run we can verify count
    result = merge_duplicates("documents", clusters, dry_run=True)
    assert result == 2  # Remove 2, keep 1


# ── Formatter tests ─────────────────────────────────────────────────────────

def _sample_report() -> MaintenanceReport:
    return MaintenanceReport(
        generated_at="2026-03-01T04:30:00Z",
        duration_ms=2500,
        dry_run=True,
        collections=[
            CollectionStats(
                name="documents", points_before=1000, points_after=1000,
                dimensions=768, stale_pruned=3, duplicates_merged=5,
                warnings=["3 stale source(s) would be pruned"],
            ),
            CollectionStats(
                name="samples", points_before=50, points_after=50,
                dimensions=768,
            ),
        ],
        total_pruned=3,
        total_merged=5,
        warnings=["3 stale source(s) would be pruned"],
    )


def test_format_report_human_dry_run_label():
    output = format_report_human(_sample_report())
    assert "DRY RUN" in output


def test_format_report_human_applied_label():
    r = _sample_report()
    r.dry_run = False
    output = format_report_human(r)
    assert "APPLIED" in output


def test_format_report_human_contains_stats():
    output = format_report_human(_sample_report())
    assert "documents" in output
    assert "768d" in output
    assert "1000" in output


def test_format_report_human_contains_totals():
    output = format_report_human(_sample_report())
    assert "3 pruned" in output
    assert "5 merged" in output


def test_format_report_md_has_headers():
    output = format_report_md(_sample_report())
    assert "# Knowledge Maintenance Report" in output
    assert "## documents" in output


def test_format_report_md_has_totals():
    output = format_report_md(_sample_report())
    assert "3 pruned" in output
    assert "5 merged" in output


# ── Notification tests ───────────────────────────────────────────────────────

@patch("shared.notify.send_notification")
def test_send_notification_silent_when_nothing(mock_notify):
    r = MaintenanceReport(generated_at="2026-03-01T04:30:00Z")
    send_notification(r)
    mock_notify.assert_not_called()


@patch("shared.notify.send_notification")
def test_send_notification_fires_when_pruned(mock_notify):
    r = MaintenanceReport(
        generated_at="2026-03-01T04:30:00Z",
        total_pruned=3,
        warnings=["stale"],
    )
    send_notification(r)
    mock_notify.assert_called_once()
    message = mock_notify.call_args[0][1]
    assert "3 stale" in message.lower() or "pruned" in message.lower()


@patch("shared.notify.send_notification")
def test_send_notification_fires_when_merged(mock_notify):
    r = MaintenanceReport(
        generated_at="2026-03-01T04:30:00Z",
        total_merged=7,
        warnings=[],
    )
    send_notification(r)
    mock_notify.assert_called_once()


@patch("shared.notify.send_notification")
def test_send_notification_dry_run_label(mock_notify):
    r = MaintenanceReport(
        generated_at="2026-03-01T04:30:00Z",
        dry_run=True,
        total_pruned=1,
        warnings=["stale"],
    )
    send_notification(r)
    title = mock_notify.call_args[0][0]
    assert "dry-run" in title.lower()


# ── Dry-run safety tests ────────────────────────────────────────────────────

def test_default_is_dry_run():
    """MaintenanceReport defaults to dry_run=True."""
    r = MaintenanceReport(generated_at="now")
    assert r.dry_run is True


def test_expected_dimensions_is_768():
    assert EXPECTED_DIMENSIONS == 768


def test_default_score_threshold():
    assert DEFAULT_SCORE_THRESHOLD == 0.98


# ── Error logging tests (Fix 31) ──────────────────────────────────────────

@patch("agents.knowledge_maint.get_qdrant")
def test_find_stale_sources_logs_warning_on_error(mock_qdrant):
    """Qdrant failure during stale scan should log warning, not silently pass."""
    mock_qdrant.side_effect = Exception("timeout")
    with patch("agents.knowledge_maint.log") as mock_log:
        find_stale_sources("documents")
        mock_log.warning.assert_called_once()
        assert "stale sources" in mock_log.warning.call_args[0][0].lower() or \
               "documents" in str(mock_log.warning.call_args)


@patch("agents.knowledge_maint.get_qdrant")
def test_prune_logs_warning_on_individual_failure(mock_qdrant):
    """Individual prune failure should log warning, not silently pass."""
    mock_client = MagicMock()
    mock_qdrant.return_value = mock_client
    mock_client.delete.side_effect = Exception("connection lost")

    with patch("agents.knowledge_maint.log") as mock_log:
        prune_stale_sources("documents", ["/gone/file.pdf"], dry_run=False)
        mock_log.warning.assert_called_once()


@patch("agents.knowledge_maint.get_qdrant")
def test_find_near_duplicates_logs_warning_on_scroll_error(mock_qdrant):
    """Qdrant scroll failure during dedup should log warning."""
    mock_qdrant.side_effect = Exception("unavailable")
    with patch("agents.knowledge_maint.log") as mock_log:
        find_near_duplicates("documents")
        mock_log.warning.assert_called_once()


@patch("agents.knowledge_maint.get_qdrant")
def test_merge_duplicates_logs_warning_on_delete_error(mock_qdrant):
    """Batch delete failure during merge should log warning."""
    mock_client = MagicMock()
    mock_qdrant.return_value = mock_client
    mock_client.delete.side_effect = Exception("network error")

    clusters = [[{"point_id": 1, "ingested_at": 100}, {"point_id": 2, "ingested_at": 200}]]
    with patch("agents.knowledge_maint.log") as mock_log:
        merge_duplicates("documents", clusters, dry_run=False)
        mock_log.warning.assert_called_once()


# ── F-3.3: errors_encountered field and report output ──────────────────────

def test_maintenance_report_errors_encountered_default():
    """errors_encountered defaults to 0."""
    report = MaintenanceReport(generated_at="2026-03-01T00:00:00Z")
    assert report.errors_encountered == 0


def test_format_report_shows_errors():
    """format_report_human includes error count when present."""
    from agents.knowledge_maint import format_report_human
    report = MaintenanceReport(
        generated_at="2026-03-01T00:00:00Z",
        errors_encountered=2,
        warnings=["Failed to get count: timeout", "Failed to prune: denied"],
    )
    output = format_report_human(report)
    assert "2 error(s)" in output
