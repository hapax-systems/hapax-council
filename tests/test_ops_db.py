"""Tests for shared.ops_db — operations SQLite builder."""

from __future__ import annotations

import json

from shared.ops_db import build_ops_db, get_table_schemas, run_sql


class TestBuildOpsDb:
    def test_creates_all_tables(self, tmp_path):
        """An empty profiles dir still creates all 5 tables."""
        conn = build_ops_db(tmp_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cursor.fetchall()]
        assert tables == [
            "digest_runs",
            "drift_items",
            "drift_runs",
            "health_runs",
            "knowledge_maint",
        ]
        conn.close()

    def test_loads_health_history(self, tmp_path):
        history = tmp_path / "health-history.jsonl"
        history.write_text(
            json.dumps(
                {
                    "timestamp": "2026-03-10T10:00:00+00:00",
                    "status": "healthy",
                    "healthy": 44,
                    "degraded": 0,
                    "failed": 0,
                    "duration_ms": 2500,
                    "failed_checks": [],
                }
            )
            + "\n"
            + json.dumps(
                {
                    "timestamp": "2026-03-10T10:15:00+00:00",
                    "status": "degraded",
                    "healthy": 42,
                    "degraded": 2,
                    "failed": 0,
                    "duration_ms": 3100,
                    "failed_checks": ["docker_ollama", "gpu_vram"],
                }
            )
            + "\n"
        )
        conn = build_ops_db(tmp_path)
        rows = conn.execute("SELECT COUNT(*) FROM health_runs").fetchone()[0]
        assert rows == 2
        degraded = conn.execute(
            "SELECT failed_checks FROM health_runs WHERE status = 'degraded'"
        ).fetchone()[0]
        assert "docker_ollama" in degraded
        conn.close()

    def test_loads_drift_report(self, tmp_path):
        report = tmp_path / "drift-report.json"
        report.write_text(
            json.dumps(
                {
                    "drift_items": [
                        {
                            "severity": "high",
                            "category": "missing_service",
                            "doc_file": "CLAUDE.md",
                            "doc_claim": "16 services",
                            "reality": "18 services",
                            "suggestion": "Update count",
                        },
                    ],
                    "docs_analyzed": ["CLAUDE.md"],
                    "summary": "1 drift item found",
                }
            )
        )
        conn = build_ops_db(tmp_path)
        rows = conn.execute("SELECT COUNT(*) FROM drift_items").fetchone()[0]
        assert rows == 1
        row = conn.execute("SELECT severity, category FROM drift_items").fetchone()
        assert row == ("high", "missing_service")
        conn.close()

    def test_loads_drift_history(self, tmp_path):
        history = tmp_path / "drift-history.jsonl"
        history.write_text(
            json.dumps(
                {
                    "timestamp": "2026-03-09T17:05:02Z",
                    "drift_count": 25,
                    "docs_analyzed": 18,
                    "summary": "1 cross-project boundary drift",
                }
            )
            + "\n"
        )
        conn = build_ops_db(tmp_path)
        rows = conn.execute("SELECT COUNT(*) FROM drift_runs").fetchone()[0]
        assert rows == 1
        conn.close()

    def test_loads_digest_history(self, tmp_path):
        history = tmp_path / "digest-history.jsonl"
        history.write_text(
            json.dumps(
                {
                    "timestamp": "2026-03-10T06:45:00Z",
                    "hours": 24,
                    "headline": "Test headline",
                    "summary": "Test summary",
                    "new_documents": 15,
                }
            )
            + "\n"
        )
        conn = build_ops_db(tmp_path)
        row = conn.execute("SELECT headline FROM digest_runs").fetchone()
        assert row[0] == "Test headline"
        conn.close()

    def test_loads_knowledge_maint_history(self, tmp_path):
        history = tmp_path / "knowledge-maint-history.jsonl"
        history.write_text(
            json.dumps(
                {
                    "timestamp": "2026-03-09T09:39:00Z",
                    "pruned_count": 12,
                    "merged_count": 3,
                    "duration_ms": 4500,
                }
            )
            + "\n"
        )
        conn = build_ops_db(tmp_path)
        row = conn.execute("SELECT pruned_count, merged_count FROM knowledge_maint").fetchone()
        assert row == (12, 3)
        conn.close()

    def test_skips_malformed_jsonl_lines(self, tmp_path):
        history = tmp_path / "health-history.jsonl"
        history.write_text(
            "not valid json\n"
            + json.dumps(
                {
                    "timestamp": "2026-03-10T10:00:00+00:00",
                    "status": "healthy",
                    "healthy": 44,
                    "degraded": 0,
                    "failed": 0,
                    "duration_ms": 2500,
                    "failed_checks": [],
                }
            )
            + "\n"
        )
        conn = build_ops_db(tmp_path)
        rows = conn.execute("SELECT COUNT(*) FROM health_runs").fetchone()[0]
        assert rows == 1
        conn.close()


class TestRunSql:
    def test_select_returns_formatted_table(self, tmp_path):
        history = tmp_path / "health-history.jsonl"
        history.write_text(
            json.dumps(
                {
                    "timestamp": "2026-03-10T10:00:00+00:00",
                    "status": "healthy",
                    "healthy": 44,
                    "degraded": 0,
                    "failed": 0,
                    "duration_ms": 2500,
                    "failed_checks": [],
                }
            )
            + "\n"
        )
        conn = build_ops_db(tmp_path)
        result = run_sql(conn, "SELECT status, healthy FROM health_runs")
        assert "healthy" in result
        assert "44" in result
        conn.close()

    def test_rejects_non_select(self, tmp_path):
        conn = build_ops_db(tmp_path)
        result = run_sql(conn, "DROP TABLE health_runs")
        assert "error" in result.lower()
        conn.close()

    def test_limits_output_rows(self, tmp_path):
        history = tmp_path / "health-history.jsonl"
        lines = []
        for i in range(150):
            lines.append(
                json.dumps(
                    {
                        "timestamp": f"2026-03-10T{i:02d}:00:00+00:00",
                        "status": "healthy",
                        "healthy": 44,
                        "degraded": 0,
                        "failed": 0,
                        "duration_ms": 2500,
                        "failed_checks": [],
                    }
                )
            )
        history.write_text("\n".join(lines) + "\n")
        conn = build_ops_db(tmp_path)
        result = run_sql(conn, "SELECT * FROM health_runs")
        assert "150 total rows" in result
        assert "showing first 100" in result
        conn.close()

    def test_handles_sql_errors(self, tmp_path):
        conn = build_ops_db(tmp_path)
        result = run_sql(conn, "SELECT * FROM nonexistent_table")
        assert "SQL error" in result
        conn.close()


class TestGetTableSchemas:
    def test_returns_all_create_statements(self, tmp_path):
        conn = build_ops_db(tmp_path)
        schemas = get_table_schemas(conn)
        assert "health_runs" in schemas
        assert "drift_items" in schemas
        assert "drift_runs" in schemas
        assert "digest_runs" in schemas
        assert "knowledge_maint" in schemas
        assert "CREATE TABLE" in schemas
        conn.close()


class TestBuildOpsDbEmpty:
    def test_build_with_empty_dir_all_counts_zero(self, tmp_path):
        """Empty profiles dir creates all tables with zero rows."""
        conn = build_ops_db(tmp_path)
        for table in ("health_runs", "drift_items", "drift_runs", "digest_runs", "knowledge_maint"):
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
            assert cursor.fetchone()[0] == 0
        conn.close()

    def test_query_empty_health_runs_returns_no_results(self, tmp_path):
        """Query empty health_runs table returns 'No results.' message."""
        conn = build_ops_db(tmp_path)
        result = run_sql(conn, "SELECT * FROM health_runs")
        assert result == "No results."
        conn.close()

    def test_query_empty_drift_items_returns_no_results(self, tmp_path):
        """Query empty drift_items table returns 'No results.' message."""
        conn = build_ops_db(tmp_path)
        result = run_sql(conn, "SELECT * FROM drift_items")
        assert result == "No results."
        conn.close()


import pytest


@pytest.mark.parametrize(
    "payload,kind",
    [
        ("null", "null"),
        ('"a string"', "string"),
        ("[1, 2, 3]", "list"),
        ("42", "int"),
    ],
)
def test_build_ops_db_survives_non_dict_drift_report(tmp_path, payload, kind):
    """Pin build_ops_db against a non-dict drift-report.json. The
    _load_json -> _insert_drift_items chain previously crashed on
    non-empty non-dict roots (passed the `if not report` check then
    raised AttributeError on report.get('drift_items'))."""
    drift_path = tmp_path / "drift-report.json"
    drift_path.write_text(payload)
    # Must not raise — _load_json's isinstance gate now coerces non-dict to None.
    conn = build_ops_db(tmp_path)
    result = run_sql(conn, "SELECT * FROM drift_items")
    assert result == "No results.", f"non-dict root={kind} must yield empty drift_items"
    conn.close()
