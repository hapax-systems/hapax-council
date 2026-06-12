"""Rails event log (spec §2): idempotent folds, stable ids, honest provenance."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import shared.rails_event_log as rel


def _setup(tmp_path, monkeypatch):
    vault = tmp_path / "active"
    vault.mkdir()
    monkeypatch.setattr(rel, "VAULT", vault)
    monkeypatch.setattr(rel, "EVENT_LOG", tmp_path / "sdlc-events.jsonl")
    monkeypatch.setattr(rel, "SHADOW", tmp_path / "shadow.json")
    monkeypatch.setattr(rel, "DEPLOY_SHA_FILE", tmp_path / ".deployed-sha")
    return vault


def _events(tmp_path):
    p = tmp_path / "sdlc-events.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines()]


def test_stage_transition_emits_one_event_then_stays_quiet(tmp_path, monkeypatch):
    vault = _setup(tmp_path, monkeypatch)
    note = vault / "task-a.md"
    note.write_text("---\nstage: S5_REVIEW_GATE\nstatus: offered\n---\n")

    first = rel.fold_once()
    assert first >= 2  # stage + status birth events
    # idempotence: an unchanged world emits nothing
    assert rel.fold_once() == 0

    note.write_text("---\nstage: S6_IMPLEMENTATION\nstatus: claimed\nassigned_to: zeta\n---\n")
    n = rel.fold_once()
    assert n == 2
    evts = _events(tmp_path)
    stage_evt = [e for e in evts if e["kind"] == "stage" and e["stage_to"] == "S6_IMPLEMENTATION"][
        0
    ]
    assert stage_evt["stage_from"] == "S5_REVIEW_GATE"
    assert stage_evt["item_id"] == "task-a"
    assert stage_evt["lane"] == "zeta"
    assert stage_evt["source_file"].endswith("task-a.md")
    assert stage_evt["event_id"]


def test_quiet_fold_refreshes_event_log_heartbeat(tmp_path, monkeypatch):
    vault = _setup(tmp_path, monkeypatch)
    note = vault / "task-heartbeat.md"
    note.write_text("---\nstage: S5_REVIEW_GATE\nstatus: offered\n---\n")
    assert rel.fold_once() >= 2
    os.utime(rel.EVENT_LOG, (1, 1))

    assert rel.fold_once() == 0

    assert rel.EVENT_LOG.stat().st_mtime > 1


def test_missing_vault_fails_closed_without_heartbeat_or_shadow_rewrite(tmp_path, monkeypatch):
    vault = _setup(tmp_path, monkeypatch)
    note = vault / "task-source.md"
    note.write_text("---\nstage: S5_REVIEW_GATE\nstatus: offered\n---\n")
    assert rel.fold_once() >= 2
    event_before = rel.EVENT_LOG.read_bytes()
    shadow_before = rel.SHADOW.read_bytes()
    event_mtime_before = rel.EVENT_LOG.stat().st_mtime_ns
    shadow_mtime_before = rel.SHADOW.stat().st_mtime_ns

    vault.rename(tmp_path / "active-offline")

    with pytest.raises(rel.SourceVaultUnavailable, match="cc-task active vault missing"):
        rel.fold_once()

    assert rel.EVENT_LOG.read_bytes() == event_before
    assert rel.SHADOW.read_bytes() == shadow_before
    assert rel.EVENT_LOG.stat().st_mtime_ns == event_mtime_before
    assert rel.SHADOW.stat().st_mtime_ns == shadow_mtime_before


def test_unreadable_task_note_fails_closed_without_heartbeat_or_shadow_rewrite(
    tmp_path, monkeypatch
):
    vault = _setup(tmp_path, monkeypatch)
    note = vault / "task-source.md"
    note.write_text("---\nstage: S5_REVIEW_GATE\nstatus: offered\n---\n")
    assert rel.fold_once() >= 2
    event_before = rel.EVENT_LOG.read_bytes()
    shadow_before = rel.SHADOW.read_bytes()
    event_mtime_before = rel.EVENT_LOG.stat().st_mtime_ns
    shadow_mtime_before = rel.SHADOW.stat().st_mtime_ns
    original_read_text = Path.read_text

    def flaky_read_text(self, *args, **kwargs):
        if self == note:
            raise OSError("permission denied")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)

    with pytest.raises(rel.SourceVaultUnavailable, match="cc-task active note unreadable"):
        rel.fold_once()

    assert rel.EVENT_LOG.read_bytes() == event_before
    assert rel.SHADOW.read_bytes() == shadow_before
    assert rel.EVENT_LOG.stat().st_mtime_ns == event_mtime_before
    assert rel.SHADOW.stat().st_mtime_ns == shadow_mtime_before


def test_review_and_receipt_events(tmp_path, monkeypatch):
    vault = _setup(tmp_path, monkeypatch)
    (vault / "task-b.review-dossier.yaml").write_text(
        "task_id: task-b\nreview_team_verdict: blocked\nhead_sha: abc123def456\n"
    )
    (vault / "task-b.acceptance.yaml").write_text("verdict: accepted\nacceptor: review-team\n")
    rel.fold_once()
    evts = _events(tmp_path)
    assert any(e["kind"] == "review" and e["verdict"] == "blocked" for e in evts)
    assert any(e["kind"] == "receipt" and e["verdict"] == "accepted" for e in evts)


def test_deploy_transition(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    (tmp_path / ".deployed-sha").write_text("aaaa111122223333\n")
    rel.fold_once()
    (tmp_path / ".deployed-sha").write_text("bbbb444455556666\n")
    rel.fold_once()
    deploys = [e for e in _events(tmp_path) if e["kind"] == "deploy"]
    assert len(deploys) == 2
    assert deploys[1]["stage_from"] == "aaaa11112"
    assert deploys[1]["stage_to"] == "bbbb44445"


def test_unparseable_dossier_is_an_honest_event(tmp_path, monkeypatch):
    vault = _setup(tmp_path, monkeypatch)
    # genuinely invalid yaml (an unclosed flow sequence raises in safe_load;
    # the first fixture attempt "::: not yaml" turned out to PARSE as a dict)
    (vault / "task-c.review-dossier.yaml").write_text("verdict: [unclosed\n  - {{{\n")
    rel.fold_once()
    evts = _events(tmp_path)
    assert any(e["kind"] == "review" and e["verdict"] == "unparseable" for e in evts)


def test_repeated_transition_gets_a_distinct_event_id(tmp_path, monkeypatch):
    # review finding (PR #4100): a flip-flop returning to the same edge must
    # NOT reuse the first crossing's event_id, or dedup eats real history
    vault = _setup(tmp_path, monkeypatch)
    note = vault / "task-f.md"
    note.write_text("---\nstage: S5_REVIEW_GATE\n---\n")
    rel.fold_once()
    note.write_text("---\nstage: S6_IMPLEMENTATION\n---\n")
    rel.fold_once()
    note.write_text("---\nstage: S5_REVIEW_GATE\n---\n")
    rel.fold_once()
    note.write_text("---\nstage: S6_IMPLEMENTATION\n---\n")
    rel.fold_once()
    crossings = [
        e
        for e in _events(tmp_path)
        if e["kind"] == "stage"
        and e["stage_from"] == "S5_REVIEW_GATE"
        and e["stage_to"] == "S6_IMPLEMENTATION"
    ]
    assert len(crossings) == 2
    assert crossings[0]["event_id"] != crossings[1]["event_id"]
    assert crossings[0]["seq"] != crossings[1]["seq"]


def test_replay_after_crash_rederives_identical_event_ids(tmp_path, monkeypatch):
    # the dedupe contract: a re-fold whose shadow write was lost re-emits the
    # SAME ids (consumers drop them); only a persisted shadow advances seq
    vault = _setup(tmp_path, monkeypatch)
    note = vault / "task-g.md"
    note.write_text("---\nstage: S5_REVIEW_GATE\n---\n")
    rel.fold_once()
    shadow_snapshot = (tmp_path / "shadow.json").read_text()
    note.write_text("---\nstage: S6_IMPLEMENTATION\n---\n")
    rel.fold_once()
    # crash simulation: shadow reverts to its pre-fold state, fold replays
    (tmp_path / "shadow.json").write_text(shadow_snapshot)
    rel.fold_once()
    replayed = [e for e in _events(tmp_path) if e["stage_to"] == "S6_IMPLEMENTATION"]
    assert len(replayed) == 2
    assert replayed[0]["event_id"] == replayed[1]["event_id"]


def test_body_fields_never_shadow_frontmatter(tmp_path, monkeypatch):
    # review finding (PR #4100): a `status:`/`stage:` line in the note BODY
    # must not be read as task state
    vault = _setup(tmp_path, monkeypatch)
    note = vault / "task-h.md"
    note.write_text(
        "---\nstage: S5_REVIEW_GATE\nstatus: offered\n---\n## Log\nstage: S11\nstatus: abandoned\n"
    )
    rel.fold_once()
    evts = _events(tmp_path)
    assert any(e["kind"] == "stage" and e["stage_to"] == "S5_REVIEW_GATE" for e in evts)
    assert not any(e["stage_to"] in ("S11", "abandoned") for e in evts)
