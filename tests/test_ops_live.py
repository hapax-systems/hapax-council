"""Tests for shared.ops_live — live infrastructure queries."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from shared.ops_live import (
    get_infra_snapshot,
    get_manifest_section,
    query_langfuse_cost,
    query_qdrant_stats,
)


class TestGetInfraSnapshot:
    def test_reads_snapshot_file(self, tmp_path):
        snapshot = tmp_path / "infra-snapshot.json"
        snapshot.write_text(
            json.dumps(
                {
                    "timestamp": "2026-03-11T01:33:38Z",
                    "cycle_mode": "prod",
                    "containers": [
                        {
                            "service": "qdrant",
                            "name": "qdrant",
                            "state": "running",
                            "health": "healthy",
                        },
                    ],
                    "timers": [
                        {"unit": "health-monitor.timer", "type": "systemd", "status": "active"},
                    ],
                    "gpu": {
                        "used_mb": 5842,
                        "total_mb": 24576,
                        "free_mb": 18734,
                        "loaded_models": ["nomic-embed-text"],
                    },
                }
            )
        )
        result = get_infra_snapshot(tmp_path)
        assert "qdrant" in result
        assert "running" in result
        assert "prod" in result
        assert "5842" in result

    def test_missing_file_returns_message(self, tmp_path):
        result = get_infra_snapshot(tmp_path)
        assert "not found" in result.lower() or "not available" in result.lower()


class TestGetManifestSection:
    def test_reads_docker_section(self, tmp_path):
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "docker": {"containers": [{"service": "qdrant", "status": "running"}]},
                    "gpu": {"name": "RTX 3090", "vram_total_mb": 24576},
                }
            )
        )
        result = get_manifest_section(tmp_path, "docker")
        assert "qdrant" in result

    def test_unknown_section_returns_available(self, tmp_path):
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"docker": {}, "gpu": {}}))
        result = get_manifest_section(tmp_path, "nonexistent")
        assert "docker" in result.lower() or "available" in result.lower()

    def test_missing_file_returns_message(self, tmp_path):
        result = get_manifest_section(tmp_path, "docker")
        assert "not available" in result.lower() or "not found" in result.lower()


class TestQueryLangfuseCost:
    @patch("shared.langfuse_client.langfuse_get")
    def test_returns_cost_breakdown(self, mock_get):
        mock_get.return_value = {
            "data": [
                {
                    "model": "claude-sonnet",
                    "calculatedTotalCost": 0.05,
                    "startTime": "2026-03-10T10:00:00Z",
                },
                {
                    "model": "claude-haiku",
                    "calculatedTotalCost": 0.01,
                    "startTime": "2026-03-10T11:00:00Z",
                },
            ],
            "meta": {"totalItems": 2},
        }
        result = query_langfuse_cost(days=7)
        assert "claude-sonnet" in result
        assert "0.05" in result or "0.06" in result

    @patch("shared.langfuse_client.langfuse_get", return_value={})
    def test_unavailable_returns_message(self, mock_get):
        result = query_langfuse_cost(days=7)
        assert "not available" in result.lower() or "no data" in result.lower()


class TestQueryQdrantStats:
    @patch("shared.ops_live.get_qdrant")
    def test_returns_collection_stats(self, mock_qdrant):
        mock_collection = MagicMock()
        mock_collection.name = "documents"
        mock_qdrant.return_value.get_collections.return_value.collections = [mock_collection]
        mock_qdrant.return_value.count.return_value.count = 1500
        result = query_qdrant_stats()
        assert "documents" in result
        assert "1500" in result

    @patch("shared.ops_live.get_qdrant", side_effect=Exception("Connection refused"))
    def test_unavailable_returns_message(self, mock_qdrant):
        result = query_qdrant_stats()
        assert "not available" in result.lower() or "error" in result.lower()
