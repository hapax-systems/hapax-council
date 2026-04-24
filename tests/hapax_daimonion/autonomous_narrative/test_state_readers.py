"""Unit tests for autonomous_narrative.state_readers."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

from agents.hapax_daimonion.autonomous_narrative import state_readers


def _write_chronicle(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")


# ── chronicle window filter ───────────────────────────────────────────────


def test_chronicle_window_filters_old_events(tmp_path: Path) -> None:
    chronicle = tmp_path / "impingements.jsonl"
    now = 10_000.0
    _write_chronicle(
        chronicle,
        [
            {"ts": now - 1200, "source": "external", "salience": 0.9},  # too old
            {"ts": now - 100, "source": "external", "salience": 0.9},  # in window
        ],
    )
    out = state_readers.read_chronicle_window(now=now, window_s=600.0, path=chronicle)
    assert len(out) == 1
    assert out[0]["ts"] == now - 100


def test_chronicle_window_filters_self_authored(tmp_path: Path) -> None:
    """ytb-SS1 must NOT feed its own past output back as input."""
    chronicle = tmp_path / "impingements.jsonl"
    now = 10_000.0
    _write_chronicle(
        chronicle,
        [
            {"ts": now - 100, "source": "self_authored_narrative", "salience": 0.9},
            {"ts": now - 100, "source": "autonomous_narrative", "salience": 0.9},
            {"ts": now - 100, "source": "conversation_pipeline", "salience": 0.9},
            {"ts": now - 100, "source": "external", "salience": 0.9},
        ],
    )
    out = state_readers.read_chronicle_window(now=now, window_s=600.0, path=chronicle)
    sources = [e["source"] for e in out]
    assert sources == ["external"]


def test_chronicle_window_filters_low_salience(tmp_path: Path) -> None:
    chronicle = tmp_path / "impingements.jsonl"
    now = 10_000.0
    _write_chronicle(
        chronicle,
        [
            {"ts": now - 100, "source": "external", "salience": 0.2},  # below floor
            {"ts": now - 100, "source": "external", "salience": 0.5},  # above floor
        ],
    )
    out = state_readers.read_chronicle_window(
        now=now, window_s=600.0, min_salience=0.4, path=chronicle
    )
    assert len(out) == 1
    assert out[0]["salience"] == 0.5


def test_chronicle_window_handles_payload_salience(tmp_path: Path) -> None:
    """Salience can live at top level OR under content/payload."""
    chronicle = tmp_path / "impingements.jsonl"
    now = 10_000.0
    _write_chronicle(
        chronicle,
        [
            {"ts": now - 100, "source": "external", "content": {"salience": 0.7}},
            {"ts": now - 100, "source": "external", "payload": {"salience": 0.7}},
        ],
    )
    out = state_readers.read_chronicle_window(now=now, window_s=600.0, path=chronicle)
    assert len(out) == 2


def test_chronicle_window_no_file_returns_empty(tmp_path: Path) -> None:
    out = state_readers.read_chronicle_window(now=time.time(), path=tmp_path / "missing.jsonl")
    assert out == []


def test_chronicle_window_skips_malformed_lines(tmp_path: Path) -> None:
    chronicle = tmp_path / "impingements.jsonl"
    chronicle.parent.mkdir(parents=True, exist_ok=True)
    chronicle.write_text(
        "not valid json\n" + json.dumps({"ts": 100.0, "source": "external", "salience": 0.9}) + "\n"
    )
    out = state_readers.read_chronicle_window(now=200.0, window_s=600.0, path=chronicle)
    assert len(out) == 1


# ── stimmung + director readers ───────────────────────────────────────────


def test_stimmung_default_when_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(state_readers, "_STIMMUNG_PATH", tmp_path / "missing.json")
    assert state_readers.read_stimmung_tone() == "ambient"


def test_stimmung_reads_tone_first(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "stimmung.json"
    p.write_text(json.dumps({"tone": "focused", "stance": "ambient"}))
    monkeypatch.setattr(state_readers, "_STIMMUNG_PATH", p)
    assert state_readers.read_stimmung_tone() == "focused"


def test_stimmung_falls_back_to_stance(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "stimmung.json"
    p.write_text(json.dumps({"stance": "hothouse"}))
    monkeypatch.setattr(state_readers, "_STIMMUNG_PATH", p)
    assert state_readers.read_stimmung_tone() == "hothouse"


def test_director_activity_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(state_readers, "_RESEARCH_MARKER_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(state_readers, "_DIRECTOR_INTENT_PATH", tmp_path / "missing.jsonl")
    assert state_readers.read_director_activity() == "observe"


def test_director_activity_from_research_marker(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "marker.json"
    p.write_text(json.dumps({"activity": "create"}))
    monkeypatch.setattr(state_readers, "_RESEARCH_MARKER_PATH", p)
    assert state_readers.read_director_activity() == "create"


# ── assemble_context integration ──────────────────────────────────────────


def test_assemble_context_pulls_programme_from_daemon(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(state_readers, "_CHRONICLE_PATH", tmp_path / "missing.jsonl")
    monkeypatch.setattr(state_readers, "_STIMMUNG_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(state_readers, "_RESEARCH_MARKER_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(state_readers, "_DIRECTOR_INTENT_PATH", tmp_path / "missing.jsonl")
    fake_programme = MagicMock(programme_id="prog-1")
    daemon = MagicMock()
    daemon.programme_manager.store.active_programme.return_value = fake_programme
    ctx = state_readers.assemble_context(daemon)
    assert ctx.programme is fake_programme
    assert ctx.stimmung_tone == "ambient"  # default
    assert ctx.director_activity == "observe"  # default
    assert ctx.chronicle_events == ()
