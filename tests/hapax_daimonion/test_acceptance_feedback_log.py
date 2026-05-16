from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agents.hapax_daimonion.acceptance_feedback_log import log_acceptance


class TestLogAcceptance:
    def test_returns_entry_with_all_fields(self) -> None:
        entry = log_acceptance(
            turn=5,
            acceptance_type="ACCEPT",
            utterance_hash="abc123",
            du_state="GROUNDED",
            score=1.0,
        )
        assert entry["turn"] == 5
        assert entry["acceptance_type"] == "ACCEPT"
        assert entry["du_state"] == "GROUNDED"

    def test_writes_jsonl(self, tmp_path: Path) -> None:
        with patch("agents.hapax_daimonion.acceptance_feedback_log.LOG_DIR", tmp_path), patch(
            "agents.hapax_daimonion.acceptance_feedback_log.LOG_PATH",
            tmp_path / "acceptance.jsonl",
        ):
            log_acceptance(turn=1, acceptance_type="REJECT")
            assert (tmp_path / "acceptance.jsonl").exists()

    def test_handles_write_failure(self) -> None:
        with patch(
            "agents.hapax_daimonion.acceptance_feedback_log.LOG_DIR",
            Path("/nonexistent"),
        ):
            entry = log_acceptance(turn=1, acceptance_type="IGNORE")
            assert entry["acceptance_type"] == "IGNORE"
