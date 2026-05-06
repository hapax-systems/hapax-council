"""Unit tests for autonomous_narrative.state_readers."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
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


def test_triad_continuity_default_when_missing(tmp_path: Path) -> None:
    assert state_readers.read_triad_continuity(tmp_path / "missing.json") == {}


def test_triad_continuity_reads_current_summary(tmp_path: Path) -> None:
    p = tmp_path / "triad-state.json"
    p.write_text(json.dumps({"open_triads": [{"triad_id": "triad-1"}]}))
    assert state_readers.read_triad_continuity(p)["open_triads"][0]["triad_id"] == "triad-1"


def test_triad_continuity_refreshes_stale_open_outcomes(tmp_path: Path) -> None:
    from shared.narration_triad import NarrationTriadLedger, build_autonomous_narration_triad

    ledger_path = tmp_path / "triads.jsonl"
    state_path = tmp_path / "triad-state.json"
    ledger = NarrationTriadLedger(ledger_path=ledger_path, state_path=state_path)
    triad = build_autonomous_narration_triad(
        text="Hapax is monitoring the public voice witness.",
        context=SimpleNamespace(
            programme=SimpleNamespace(programme_id="prog-1", role="experiment"),
            stimmung_tone="ambient",
            director_activity="observe",
            chronicle_events=(),
            triad_continuity={},
        ),
        impulse_id="impulse-1",
        speech_event_id="speech-1",
        now=100.0,
    )
    ledger.append(triad)

    state = state_readers.read_triad_continuity(
        state_path,
        ledger_path=ledger_path,
        now=1000.0,
    )

    assert state["open_triads"] == []
    assert state["recently_resolved_triads"][0]["status"] == "stale"


def test_triad_continuity_refresh_can_satisfy_from_semantic_chronicle_ref(
    tmp_path: Path,
) -> None:
    from shared.narration_triad import NarrationTriadLedger, build_autonomous_narration_triad

    ledger_path = tmp_path / "triads.jsonl"
    state_path = tmp_path / "triad-state.json"
    ledger = NarrationTriadLedger(ledger_path=ledger_path, state_path=state_path)
    triad = build_autonomous_narration_triad(
        text="Hapax is monitoring the public voice witness.",
        context=SimpleNamespace(
            programme=SimpleNamespace(programme_id="prog-1", role="experiment"),
            stimmung_tone="ambient",
            director_activity="observe",
            chronicle_events=(),
            triad_continuity={},
        ),
        impulse_id="impulse-2",
        speech_event_id="speech-2",
        now=100.0,
    )
    ledger.append(triad)

    state = state_readers.read_triad_continuity(
        state_path,
        ledger_path=ledger_path,
        chronicle_events=(
            {
                "payload": {
                    "capability_outcome_refs": [
                        "capability_outcome:narration.autonomous_first_system"
                    ]
                }
            },
        ),
        now=120.0,
    )

    assert state["open_triads"] == []
    resolved = state["recently_resolved_triads"][0]
    assert resolved["status"] == "satisfied"
    assert resolved["learning_update_allowed"] is True


# ── assemble_context integration ──────────────────────────────────────────


def test_assemble_context_pulls_programme_from_daemon(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(state_readers, "_CHRONICLE_PATH", tmp_path / "missing.jsonl")
    monkeypatch.setattr(state_readers, "_STIMMUNG_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(state_readers, "_RESEARCH_MARKER_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(state_readers, "_DIRECTOR_INTENT_PATH", tmp_path / "missing.jsonl")
    monkeypatch.setattr(state_readers, "_TRIAD_LEDGER_PATH", tmp_path / "missing-triad.jsonl")
    monkeypatch.setattr(state_readers, "_TRIAD_STATE_PATH", tmp_path / "missing-triad.json")
    fake_programme = MagicMock(programme_id="prog-1")
    daemon = MagicMock()
    daemon.programme_manager.store.active_programme.return_value = fake_programme
    ctx = state_readers.assemble_context(daemon)
    assert ctx.programme is fake_programme
    assert ctx.stimmung_tone == "ambient"  # default
    assert ctx.director_activity == "observe"  # default
    assert ctx.chronicle_events == ()
    assert ctx.triad_continuity == {}


# ── Defensive readers — non-dict JSON root ───────────────────────────


import pytest


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_read_stimmung_tone_non_dict_returns_default(monkeypatch, tmp_path, payload, kind):
    """Pin read_stimmung_tone against non-dict JSON. The except clause
    only catches (OSError, ValueError); a non-dict root previously
    raised AttributeError on data.get(...)."""
    path = tmp_path / "stimmung.json"
    path.write_text(payload)
    monkeypatch.setattr(state_readers, "_STIMMUNG_PATH", path)
    assert state_readers.read_stimmung_tone() == "ambient", (
        f"non-dict root={kind} must yield default"
    )


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_read_director_activity_non_dict_marker_returns_default(
    monkeypatch, tmp_path, payload, kind
):
    """Pin read_director_activity against non-dict research-marker JSON."""
    marker_path = tmp_path / "research-marker.json"
    marker_path.write_text(payload)
    monkeypatch.setattr(state_readers, "_RESEARCH_MARKER_PATH", marker_path)
    monkeypatch.setattr(state_readers, "_DIRECTOR_INTENT_PATH", tmp_path / "missing.jsonl")
    assert state_readers.read_director_activity() == "observe", (
        f"non-dict marker root={kind} must yield default"
    )


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_read_director_activity_non_dict_intent_tail_returns_default(
    monkeypatch, tmp_path, payload, kind
):
    """Pin read_director_activity against non-dict director-intent JSONL tail."""
    intent_path = tmp_path / "director-intent.jsonl"
    intent_path.write_text(payload + "\n")
    monkeypatch.setattr(state_readers, "_RESEARCH_MARKER_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(state_readers, "_DIRECTOR_INTENT_PATH", intent_path)
    assert state_readers.read_director_activity() == "observe", (
        f"non-dict tail root={kind} must yield default"
    )
