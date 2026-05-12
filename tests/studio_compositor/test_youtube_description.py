"""Tests for YouTube description quota + writer."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from agents.studio_compositor.youtube_description import (
    QuotaExhausted,
    _pacific_date_now,
    _read_quota_state,
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

    def test_private_nonbroadcast_markers_are_omitted_from_text_fields(self):
        out = assemble_description(
            condition_id="PRIVATE_MEDIA_ROLE",
            claim_id="claim-PRIVATE",
            objective_title="Review non-broadcast private monitor route",
            substrate_model="hapax-private",
            extra="audio.private_assistant_monitor should stay local",
        )

        assert "Condition: unknown" in out
        assert "Substrate: unknown" in out
        assert "Claim:" not in out
        assert "Current objective:" not in out
        assert "private" not in out.lower()
        assert "non-broadcast" not in out.lower()
        assert "audio.private" not in out

    def test_private_sentinel_redaction_does_not_leave_private_marker(self):
        sentinel = "PRIVATE_SENTINEL_DO_NOT_PUBLISH_20260505_XSURF_9F4C2A"
        out = assemble_description(
            condition_id=f"condition {sentinel}",
            claim_id=f"claim {sentinel}",
            objective_title=f"public objective {sentinel}",
            substrate_model=f"model {sentinel}",
            extra=f"extra {sentinel}",
        )

        assert sentinel not in out
        assert "PRIVATE" not in out
        assert "[redacted]" in out


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


# ── YT bundle B2 — attribution backflow into description ──────────────


class TestAttributionRendering:
    """assemble_description renders attribution entries as a Sources
    section grouped by kind, deduplicated by (kind, url), newest-first,
    capped on entry count + character budget."""

    def _entry(self, kind: str, url: str, title: str | None = None, ts: int = 1):
        from datetime import UTC, datetime

        from shared.attribution import AttributionEntry

        return AttributionEntry(
            kind=kind,  # type: ignore[arg-type]
            url=url,
            title=title,
            source="test",
            emitted_at=datetime.fromtimestamp(ts, tz=UTC),
        )

    def test_no_attributions_no_sources_section(self):
        desc = assemble_description(
            condition_id="cond-1",
            claim_id=None,
            objective_title=None,
            substrate_model="x",
        )
        assert "Sources:" not in desc

    def test_single_attribution_renders(self):
        entries = [self._entry("youtube", "https://youtu.be/abc")]
        desc = assemble_description(
            condition_id="cond-1",
            claim_id=None,
            objective_title=None,
            substrate_model="x",
            attributions=entries,
        )
        assert "Sources:" in desc
        assert "[youtube]" in desc
        assert "https://youtu.be/abc" in desc

    def test_grouped_by_kind(self):
        entries = [
            self._entry("youtube", "https://youtu.be/aaa"),
            self._entry("github", "https://github.com/x/y"),
            self._entry("youtube", "https://youtu.be/bbb"),
        ]
        desc = assemble_description(
            condition_id="cond-1",
            claim_id=None,
            objective_title=None,
            substrate_model="x",
            attributions=entries,
        )
        assert desc.index("[github]") < desc.index("[youtube]"), "kinds must be sorted"
        # Both youtube entries land under the [youtube] heading.
        yt_section = desc.split("[youtube]", 1)[1]
        assert "https://youtu.be/aaa" in yt_section
        assert "https://youtu.be/bbb" in yt_section

    def test_dedup_by_kind_and_url(self):
        entries = [
            self._entry("youtube", "https://youtu.be/aaa", title="first", ts=1),
            self._entry("youtube", "https://youtu.be/aaa", title="duplicate", ts=2),
        ]
        desc = assemble_description(
            condition_id="cond-1",
            claim_id=None,
            objective_title=None,
            substrate_model="x",
            attributions=entries,
        )
        # URL appears exactly once.
        assert desc.count("https://youtu.be/aaa") == 1

    def test_title_renders_when_present(self):
        entries = [self._entry("github", "https://github.com/x/y", title="cool repo")]
        desc = assemble_description(
            condition_id="cond-1",
            claim_id=None,
            objective_title=None,
            substrate_model="x",
            attributions=entries,
        )
        assert "cool repo: https://github.com/x/y" in desc

    def test_max_entries_caps_count(self):
        entries = [self._entry("youtube", f"https://youtu.be/{i}", ts=i) for i in range(20)]
        desc = assemble_description(
            condition_id="cond-1",
            claim_id=None,
            objective_title=None,
            substrate_model="x",
            attributions=entries,
            attribution_max=5,
        )
        # Only 5 URLs make it in.
        url_count = sum(1 for line in desc.splitlines() if "https://youtu.be/" in line)
        assert url_count == 5

    def test_max_chars_truncates_with_notice(self):
        entries = [
            self._entry("github", f"https://github.com/long-org/very-long-repo-name-{i}", ts=i)
            for i in range(50)
        ]
        desc = assemble_description(
            condition_id="cond-1",
            claim_id=None,
            objective_title=None,
            substrate_model="x",
            attributions=entries,
            attribution_max=50,
            attribution_max_chars=300,
        )
        assert "more truncated" in desc

    def test_other_description_fields_not_clobbered(self):
        entries = [self._entry("github", "https://github.com/x/y")]
        desc = assemble_description(
            condition_id="cond-1",
            claim_id="claim-A",
            objective_title="ship the thing",
            substrate_model="qwen3",
            attributions=entries,
        )
        # Pre-existing fields all still present.
        assert "Condition: cond-1" in desc
        assert "Claim: claim-A" in desc
        assert "Current objective: ship the thing" in desc
        assert "Substrate: qwen3" in desc
        # Attribution section appears AFTER the rest.
        assert desc.index("Sources:") > desc.index("Substrate:")

    def test_private_attribution_title_is_redacted_without_private_marker(self):
        sentinel = "PRIVATE_SENTINEL_DO_NOT_PUBLISH_20260505_XSURF_9F4C2A"
        entries = [self._entry("github", "https://github.com/x/y", title=f"repo {sentinel}")]
        desc = assemble_description(
            condition_id="cond-1",
            claim_id=None,
            objective_title=None,
            substrate_model="x",
            attributions=entries,
        )

        assert sentinel not in desc
        assert "PRIVATE" not in desc
        assert "repo [redacted]: https://github.com/x/y" in desc

    def test_private_attribution_url_and_metadata_are_dropped(self):
        sentinel = "PRIVATE_SENTINEL_DO_NOT_PUBLISH_20260505_XSURF_9F4C2A"
        entries = [
            self._entry(
                "github",
                "https://github.com/public/repo",
                title="safe",
                ts=3,
            ),
            self._entry(
                "github",
                "https://example.invalid/PRIVATE_MEDIA_ROLE",
                title="bad url",
                ts=2,
            ),
            self._entry(
                "github",
                f"https://example.invalid/{sentinel}",
                title="bad sentinel url",
                ts=2,
            ),
            replace(
                self._entry(
                    "other",
                    "https://example.invalid/private-audio",
                    title="private audio",
                    ts=1,
                ),
                metadata={
                    "broadcast_safe": False,
                    "source_id": "hapax-private",
                },
            ),
        ]
        desc = assemble_description(
            condition_id="cond-1",
            claim_id=None,
            objective_title=None,
            substrate_model="x",
            attributions=entries,
        )

        assert "https://github.com/public/repo" in desc
        assert sentinel not in desc
        assert "PRIVATE_MEDIA_ROLE" not in desc
        assert "bad sentinel url" not in desc
        assert "hapax-private" not in desc
        assert "private audio" not in desc


class TestReadQuotaState:
    """Defensive parsing — non-dict JSON roots fall back to a fresh state."""

    def _expected_fresh(self) -> dict:
        return {"date": _pacific_date_now(), "units_spent": 0, "stream_updates": {}}

    def test_missing_file_returns_fresh(self, tmp_path):
        state = _read_quota_state(tmp_path / "missing.json")
        assert state == self._expected_fresh()

    def test_truncated_json_returns_fresh(self, tmp_path):
        path = tmp_path / "trunc.json"
        path.write_text("{not valid json")
        assert _read_quota_state(path) == self._expected_fresh()

    @pytest.mark.parametrize(
        "payload",
        ["[]", "null", '"a string"', "42", "true"],
    )
    def test_non_dict_root_returns_fresh(self, tmp_path, payload):
        path = tmp_path / "nondict.json"
        path.write_text(payload)
        assert _read_quota_state(path) == self._expected_fresh()

    def test_dict_with_stale_date_returns_fresh(self, tmp_path):
        path = tmp_path / "stale.json"
        path.write_text(
            json.dumps({"date": "1970-01-01", "units_spent": 999, "stream_updates": {}})
        )
        assert _read_quota_state(path) == self._expected_fresh()

    def test_dict_with_today_returns_persisted_state(self, tmp_path):
        path = tmp_path / "today.json"
        persisted = {"date": _pacific_date_now(), "units_spent": 150, "stream_updates": {"v1": 3}}
        path.write_text(json.dumps(persisted))
        assert _read_quota_state(path) == persisted
