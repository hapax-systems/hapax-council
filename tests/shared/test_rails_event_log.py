"""Rails event log (spec §2): idempotent folds, stable ids, honest provenance."""

from __future__ import annotations

import json

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
