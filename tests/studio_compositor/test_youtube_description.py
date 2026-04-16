"""Tests for YouTube description quota + writer."""

from __future__ import annotations

import json

import pytest

from agents.studio_compositor.youtube_description import (
    QuotaExhausted,
    _pacific_date_now,
    assemble_description,
    check_and_debit,
    update_video_description,
)


def _cfg(
    daily: int = 2000,
    per_stream: int = 5,
    unit_cost: int = 50,
) -> dict:
    return {
        "daily_budget_units": daily,
        "per_stream_max_updates": per_stream,
        "per_update_unit_cost": unit_cost,
        "on_budget_exhausted": "skip_silent",
        "oauth_scope": "https://www.googleapis.com/auth/youtube.force-ssl",
    }


class TestAssemble:
    def test_minimal(self):
        out = assemble_description(
            condition_id="A",
            claim_id=None,
            objective_title=None,
            substrate_model="qwen3.5-9b",
        )
        assert "Condition: A" in out
        assert "Substrate: qwen3.5-9b" in out
        assert "Claim" not in out

    def test_full(self):
        out = assemble_description(
            condition_id="A",
            claim_id="claim-shaikh",
            objective_title="Close LRR epic",
            substrate_model="qwen3.5-9b",
            reaction_count=42,
            extra="Research stream — see ryanklee/hapax-council",
        )
        assert "Condition: A" in out
        assert "claim-shaikh" in out
        assert "Close LRR epic" in out
        assert "Reactions observed: 42" in out
        assert "Research stream" in out


class TestQuota:
    def test_first_debit_succeeds(self, tmp_path):
        qf = tmp_path / "q.json"
        check_and_debit("vid1", cfg=_cfg(), quota_file=qf)
        state = json.loads(qf.read_text())
        assert state["units_spent"] == 50
        assert state["stream_updates"]["vid1"] == 1

    def test_per_stream_cap(self, tmp_path):
        qf = tmp_path / "q.json"
        cfg = _cfg(per_stream=2)
        check_and_debit("vid1", cfg=cfg, quota_file=qf)
        check_and_debit("vid1", cfg=cfg, quota_file=qf)
        with pytest.raises(QuotaExhausted):
            check_and_debit("vid1", cfg=cfg, quota_file=qf)

    def test_daily_cap(self, tmp_path):
        qf = tmp_path / "q.json"
        cfg = _cfg(daily=100, unit_cost=50)
        check_and_debit("vid1", cfg=cfg, quota_file=qf)
        check_and_debit("vid2", cfg=cfg, quota_file=qf)
        with pytest.raises(QuotaExhausted):
            check_and_debit("vid3", cfg=cfg, quota_file=qf)

    def test_other_stream_does_not_share_budget(self, tmp_path):
        qf = tmp_path / "q.json"
        cfg = _cfg(per_stream=1)
        check_and_debit("vid1", cfg=cfg, quota_file=qf)
        # vid1 is at per-stream cap but vid2 is fresh
        check_and_debit("vid2", cfg=cfg, quota_file=qf)

    def test_rollover_resets_counter(self, tmp_path):
        qf = tmp_path / "q.json"
        state = {
            "date": "1999-01-01",
            "units_spent": 1_000_000,
            "stream_updates": {"vid1": 99},
        }
        qf.write_text(json.dumps(state))
        # Stale date triggers reset on read
        check_and_debit("vid1", cfg=_cfg(), quota_file=qf)
        state = json.loads(qf.read_text())
        assert state["date"] == _pacific_date_now()
        assert state["units_spent"] == 50


class TestUpdateSilent:
    def test_quota_exhausted_returns_false(self, tmp_path):
        qf = tmp_path / "q.json"
        cfg = _cfg(daily=0, unit_cost=50)  # impossible-to-succeed budget
        ok = update_video_description("vid1", "body", dry_run=True, cfg=cfg, quota_file=qf)
        assert ok is False

    def test_dry_run_succeeds_when_budget_available(self, tmp_path):
        qf = tmp_path / "q.json"
        ok = update_video_description("vid1", "body", dry_run=True, cfg=_cfg(), quota_file=qf)
        assert ok is True
        # Quota debited even though no API call
        state = json.loads(qf.read_text())
        assert state["units_spent"] == 50
