"""Tests for automatic segment-prep ledger publication enqueue."""

from __future__ import annotations

from pathlib import Path

from scripts import publish_segment_prep_prediction_ledger as mod


def test_should_publish_when_hash_changes(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.md"
    state = tmp_path / "state.sha256"
    ledger.write_text("first", encoding="utf-8")

    changed, digest = mod.should_publish(ledger, state)
    assert changed is True

    mod.save_published_hash(state, digest)
    changed, _ = mod.should_publish(ledger, state)
    assert changed is False

    ledger.write_text("second", encoding="utf-8")
    changed, _ = mod.should_publish(ledger, state)
    assert changed is True


def test_main_queues_and_records_hash(tmp_path: Path, monkeypatch) -> None:
    ledger = tmp_path / "ledger.md"
    state = tmp_path / "state.sha256"
    ledger.write_text("---\ntitle: Test\n---\n\n# Test\n", encoding="utf-8")
    calls: list[Path] = []

    def _fake_queue(path: Path) -> int:
        calls.append(path)
        return 0

    monkeypatch.setattr(mod, "queue_publication", _fake_queue)

    rc = mod.main(["--path", str(ledger), "--state-path", str(state)])

    assert rc == 0
    assert calls == [ledger]
    assert state.read_text(encoding="utf-8").strip() == mod.file_sha256(ledger)
