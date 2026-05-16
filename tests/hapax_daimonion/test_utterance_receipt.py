"""Tests for utterance receipt publisher."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agents.hapax_daimonion.utterance_receipt import publish_utterance_receipt


class TestPublishUtteranceReceipt:
    def test_returns_receipt_with_all_fields(self) -> None:
        receipt = publish_utterance_receipt(
            utterance_text="I notice the stimmung is shifting",
            stimmung_region="nominal",
            du_state="GROUNDED",
            gqi=0.85,
            routing_tier="LOCAL",
            acceptance_signal="ACCEPT",
            strategy_directive="elaborate",
            turn_number=5,
            model_id="local-fast",
        )
        assert receipt["stimmung_region"] == "nominal"
        assert receipt["du_state"] == "GROUNDED"
        assert receipt["gqi"] == 0.85
        assert receipt["routing_tier"] == "LOCAL"
        assert receipt["acceptance_signal"] == "ACCEPT"
        assert receipt["strategy_directive"] == "elaborate"
        assert receipt["turn"] == 5
        assert receipt["model_id"] == "local-fast"
        assert len(receipt["utterance_hash"]) == 16

    def test_writes_to_shm(self, tmp_path: Path) -> None:
        with patch(
            "agents.hapax_daimonion.utterance_receipt.RECEIPT_DIR", tmp_path
        ), patch(
            "agents.hapax_daimonion.utterance_receipt.RECEIPT_PATH",
            tmp_path / "utterance-receipt.json",
        ), patch(
            "agents.hapax_daimonion.utterance_receipt.RECEIPT_LOG_PATH",
            tmp_path / "utterance-receipts.jsonl",
        ):
            publish_utterance_receipt(
                utterance_text="test",
                stimmung_region="critical",
                du_state="PENDING",
                gqi=0.0,
                routing_tier="CAPABLE",
            )
            assert (tmp_path / "utterance-receipt.json").exists()
            assert (tmp_path / "utterance-receipts.jsonl").exists()

    def test_handles_write_failure_gracefully(self) -> None:
        with patch(
            "agents.hapax_daimonion.utterance_receipt.RECEIPT_DIR",
            Path("/nonexistent/path"),
        ):
            receipt = publish_utterance_receipt(utterance_text="test")
            assert "utterance_hash" in receipt

    def test_gqi_rounded(self) -> None:
        receipt = publish_utterance_receipt(
            utterance_text="test",
            gqi=0.123456789,
        )
        assert receipt["gqi"] == 0.123
