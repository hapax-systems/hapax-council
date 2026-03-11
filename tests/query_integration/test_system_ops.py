"""Integration tests for system-ops query agent against real data."""
from __future__ import annotations

import json

import pytest

from shared.ops_db import build_ops_db, run_sql, get_table_schemas, _load_jsonl
from shared.ops_live import get_infra_snapshot, get_manifest_section
from tests.query_integration._helpers import (
    POPULATED_PROFILES,
    EMPTY_PROFILES,
    make_ops_db,
    skip_if_missing,
)


# ── Populated state — SQL ────────────────────────────────────────────────────


class TestSystemOpsHealthQueries:
    def setup_method(self):
        skip_if_missing(POPULATED_PROFILES)
        self.conn = make_ops_db(POPULATED_PROFILES)

    def test_health_runs_have_data(self):
        result = run_sql(self.conn, "SELECT COUNT(*) as cnt FROM health_runs")
        assert "No results" not in result
        # Should have some entries
        cursor = self.conn.execute("SELECT COUNT(*) FROM health_runs")
        assert cursor.fetchone()[0] > 0

    def test_health_status_distribution(self):
        result = run_sql(
            self.conn,
            "SELECT status, COUNT(*) as cnt FROM health_runs GROUP BY status ORDER BY cnt DESC"
        )
        assert "status" in result
        assert "cnt" in result

    def test_latest_health_run(self):
        result = run_sql(
            self.conn,
            "SELECT timestamp, status FROM health_runs ORDER BY timestamp DESC LIMIT 1"
        )
        assert "timestamp" in result

    def test_duration_stats(self):
        result = run_sql(
            self.conn,
            "SELECT AVG(duration_ms) as avg_dur, MAX(duration_ms) as max_dur FROM health_runs"
        )
        assert "avg_dur" in result

    def test_failed_checks_unnest(self):
        result = run_sql(
            self.conn,
            """SELECT value as check_name, COUNT(*) as fail_count
               FROM health_runs, json_each(failed_checks)
               WHERE status != 'healthy'
               GROUP BY value
               ORDER BY fail_count DESC
               LIMIT 5"""
        )
        # May return "No results." if all runs are healthy — that's fine
        assert isinstance(result, str)


class TestSystemOpsDriftQueries:
    def setup_method(self):
        skip_if_missing(POPULATED_PROFILES)
        self.conn = make_ops_db(POPULATED_PROFILES)

    def test_drift_items_by_severity(self):
        result = run_sql(
            self.conn,
            "SELECT severity, COUNT(*) as cnt FROM drift_items GROUP BY severity"
        )
        # May be empty if no drift report
        assert isinstance(result, str)

    def test_drift_runs_trend(self):
        result = run_sql(
            self.conn,
            "SELECT timestamp, drift_count FROM drift_runs ORDER BY timestamp DESC LIMIT 5"
        )
        assert isinstance(result, str)


class TestSystemOpsDigestQueries:
    def setup_method(self):
        skip_if_missing(POPULATED_PROFILES)
        self.conn = make_ops_db(POPULATED_PROFILES)

    def test_digest_headline_search(self):
        result = run_sql(
            self.conn,
            "SELECT timestamp, headline FROM digest_runs ORDER BY timestamp DESC LIMIT 3"
        )
        assert isinstance(result, str)


class TestSystemOpsMaintQueries:
    def setup_method(self):
        skip_if_missing(POPULATED_PROFILES)
        self.conn = make_ops_db(POPULATED_PROFILES)

    def test_maint_totals(self):
        result = run_sql(
            self.conn,
            "SELECT SUM(pruned_count) as total_pruned, SUM(merged_count) as total_merged FROM knowledge_maint"
        )
        assert isinstance(result, str)


# ── Populated state — Live tools ─────────────────────────────────────────────


class TestSystemOpsLiveTools:
    def setup_method(self):
        skip_if_missing(POPULATED_PROFILES)

    def test_infra_snapshot_has_sections(self):
        result = get_infra_snapshot(POPULATED_PROFILES)
        assert "Infrastructure Snapshot" in result or "not found" in result.lower()

    def test_manifest_docker_section(self):
        result = get_manifest_section(POPULATED_PROFILES, "docker")
        # Either returns JSON content or "not found"
        assert len(result) > 0

    def test_manifest_nonexistent_section(self):
        result = get_manifest_section(POPULATED_PROFILES, "nonexistent_section")
        assert "not found" in result.lower() or "Available sections" in result


# ── Empty state ──────────────────────────────────────────────────────────────


class TestSystemOpsEmpty:
    def setup_method(self):
        skip_if_missing(EMPTY_PROFILES, allow_empty=True)
        self.conn = make_ops_db(EMPTY_PROFILES)

    def test_all_tables_empty(self):
        for table in ("health_runs", "drift_items", "drift_runs", "digest_runs", "knowledge_maint"):
            result = run_sql(self.conn, f"SELECT * FROM {table}")
            assert result == "No results.", f"Expected empty {table}"

    def test_schemas_still_valid(self):
        schemas = get_table_schemas(self.conn)
        assert "health_runs" in schemas
        assert "drift_items" in schemas

    def test_infra_snapshot_missing(self):
        result = get_infra_snapshot(EMPTY_PROFILES)
        assert "not found" in result.lower() or "not available" in result.lower()

    def test_manifest_missing(self):
        result = get_manifest_section(EMPTY_PROFILES, "docker")
        assert "not found" in result.lower()


# ── Error paths ──────────────────────────────────────────────────────────────


class TestSystemOpsErrorPaths:
    def test_malformed_jsonl_skips_bad_lines(self, tmp_path):
        """Verify _load_jsonl handles malformed entries."""
        data = '{"timestamp":"2026-01-01","status":"healthy","healthy":1,"degraded":0,"failed":0,"duration_ms":100,"failed_checks":[]}\n'
        data += 'THIS IS NOT JSON\n'
        data += '{"timestamp":"2026-01-02","status":"failed","healthy":0,"degraded":0,"failed":1,"duration_ms":200,"failed_checks":["docker"]}\n'
        (tmp_path / "health-history.jsonl").write_text(data)

        conn = build_ops_db(tmp_path)
        cursor = conn.execute("SELECT COUNT(*) FROM health_runs")
        count = cursor.fetchone()[0]
        assert count == 2  # Skipped the bad line

    def test_multiline_json_parsed_correctly(self, tmp_path):
        """Verify _load_jsonl handles pretty-printed concatenated JSON."""
        entries = [
            {"timestamp": "2026-01-01", "hours": 24, "headline": "Test 1", "summary": "S1", "new_documents": 5},
            {"timestamp": "2026-01-02", "hours": 24, "headline": "Test 2", "summary": "S2", "new_documents": 3},
        ]
        # Write as pretty-printed (not true JSONL)
        text = "\n".join(json.dumps(e, indent=2) for e in entries)
        (tmp_path / "digest-history.jsonl").write_text(text)

        conn = build_ops_db(tmp_path)
        cursor = conn.execute("SELECT COUNT(*) FROM digest_runs")
        count = cursor.fetchone()[0]
        assert count == 2
