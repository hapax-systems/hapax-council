"""Tests for the Generative Episode Trace (shared/generative_trace.py).

Covers the load-bearing observability logic: re-roll/iteration delta detection,
source operativity resolution (cited=operative / uncited=latent), fail-safe
recording (a bad input must never raise into the generative path), atomic flush +
consent labeling, retention pruning, and the ambient-episode lifecycle.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared import generative_trace as gt


def _trace(**kw: object) -> gt.GenerativeEpisodeTrace:
    base = {"episode_id": "ep-test-1", "programme_id": "prog-1", "role": "rant"}
    base.update(kw)
    return gt.GenerativeEpisodeTrace(**base)


# ── iteration / re-roll delta detection ───────────────────────────────────────


def test_record_draft_flags_identical_reroll() -> None:
    t = _trace()
    t.record_draft(1, "compose", "alpha beta gamma")
    t.record_draft(2, "refine", "alpha beta gamma")  # identical -> re-roll
    assert len(t.iterations) == 2
    assert "IDENTICAL" in t.iterations[1].delta_from_prev
    assert "re-roll" in t.iterations[1].delta_from_prev.lower()


def test_record_draft_summarizes_real_revision() -> None:
    t = _trace()
    t.record_draft(1, "compose", "the quick brown fox jumps")
    t.record_draft(2, "refine", "a completely different sentence entirely rewritten now")
    delta = t.iterations[1].delta_from_prev
    assert "IDENTICAL" not in delta
    assert "chars" in delta and "overlap" in delta


def test_summarize_delta_cases() -> None:
    assert gt._summarize_delta("", "") == "both empty"
    assert "IDENTICAL" in gt._summarize_delta("same text", "same text")
    assert "rewrite" in gt._summarize_delta("one two three four", "five six seven eight nine")


def test_record_draft_counts_beats_and_chars() -> None:
    t = _trace()
    t.record_draft(1, "compose", "beat one\n\nbeat two\n\nbeat three")
    dv = t.iterations[0]
    assert dv.beats == 3
    assert dv.chars == len("beat one\n\nbeat two\n\nbeat three")


# ── source operativity resolution ─────────────────────────────────────────────


def test_resolve_source_operativity_cited_vs_uncited() -> None:
    t = _trace()
    t.record_recruitment(
        [
            {"handle": "src:0", "kind": "source", "summary": "cited one"},
            {"handle": "src:1", "kind": "source", "summary": "uncited one"},
            {"handle": "fact:9", "kind": "profile_fact", "summary": "not a source"},
        ]
    )
    t.resolve_source_operativity(["src:0"])
    by_handle = {r.handle: r for r in t.recruitment}
    assert by_handle["src:0"].operativity == "operative"
    assert by_handle["src:0"].operativity_basis == "cited"
    assert by_handle["src:1"].operativity == "latent"
    assert by_handle["src:1"].operativity_basis == "uncited"
    # non-source inputs are left untouched (self-report only, not cited-derived)
    assert by_handle["fact:9"].operativity == "unknown"


def test_resolve_source_operativity_handles_empty_cites() -> None:
    t = _trace()
    t.record_recruitment([{"handle": "src:0", "kind": "source"}])
    t.resolve_source_operativity([])  # nothing cited -> all sources latent
    assert t.recruitment[0].operativity == "latent"


# ── fail-safe recording (instrumentation must never raise) ─────────────────────


def test_recording_is_fail_safe_on_bad_input() -> None:
    t = _trace()
    # extra=ignore + _safe: malformed records must not raise into the caller
    t.record_recruitment([{"handle": "src:0", "kind": "source", "relevance": "not-a-float"}])
    t.record_stance({"motivated_angle": "bogus"})
    t.record_step("compose", status="low", duration_s="bad")
    # The episode survives; the trace simply drops what it cannot coerce.
    assert isinstance(t.recruitment, list)


def test_process_step_accepts_extended_states() -> None:
    t = _trace()
    t.record_step("refine", status="no_change")
    t.record_step("coherence_check", status="low")
    assert {s.status for s in t.process} == {"no_change", "low"}


# ── flush + consent + retention ────────────────────────────────────────────────


def test_flush_writes_consent_labeled_json(tmp_path: Path) -> None:
    t = _trace()
    t.record_step("compose", status="ok")
    t.finish("released")
    path = t.flush(tmp_path)
    assert path is not None and path.exists()
    payload = json.loads(path.read_text())
    assert payload["episode_id"] == "ep-test-1"
    assert payload["outcome"] == "released"
    assert "_consent" in payload  # consent-labeled, always
    assert path.parent.name == "generative-traces"


def test_flush_prunes_to_retention_cap(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(gt, "_TRACE_KEEP", 3)
    for i in range(6):
        gt.GenerativeEpisodeTrace(episode_id=f"ep-{i}").flush(tmp_path)
    remaining = list((tmp_path / "generative-traces").glob("*.json"))
    assert len(remaining) == 3  # only the most recent 3 survive


def test_prune_disabled_when_keep_zero(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(gt, "_TRACE_KEEP", 0)
    for i in range(4):
        gt.GenerativeEpisodeTrace(episode_id=f"ep-{i}").flush(tmp_path)
    remaining = list((tmp_path / "generative-traces").glob("*.json"))
    assert len(remaining) == 4  # unbounded


# ── ambient episode lifecycle ──────────────────────────────────────────────────


def test_begin_current_clear_episode() -> None:
    assert gt.current() is None
    t = gt.begin_episode(episode_id="ambient-1")
    assert gt.current() is t
    gt.clear_episode()
    assert gt.current() is None


def test_end_episode_finishes_flushes_and_clears(tmp_path: Path) -> None:
    gt.begin_episode(episode_id="ambient-2")
    path = gt.end_episode(tmp_path, outcome="released")
    assert path is not None and path.exists()
    assert gt.current() is None  # cleared
    assert json.loads(path.read_text())["outcome"] == "released"


def test_end_episode_noop_when_no_ambient(tmp_path: Path) -> None:
    gt.clear_episode()
    assert gt.end_episode(tmp_path, outcome="released") is None
