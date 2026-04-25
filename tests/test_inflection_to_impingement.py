"""AUDIT-20 — tests for the relay-inflection → impingement bridge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.inflection_to_impingement import (
    DEFAULT_CURSOR_FILENAME,
    _interrupt_token,
    _stable_id,
    build_impingement_record,
    load_seen,
    tick,
)


def _write_inflection(dir_: Path, name: str, body: str = "# headline\n\nBody.") -> Path:
    p = dir_ / name
    p.write_text(body)
    return p


def test_stable_id_is_deterministic_and_unique() -> None:
    a = _stable_id("20260425-040000-beta-phase-shipped.md")
    b = _stable_id("20260425-040000-beta-phase-shipped.md")
    c = _stable_id("20260425-040000-alpha-phase-shipped.md")
    assert a == b
    assert a != c
    assert a.startswith("inflection-")


def test_interrupt_token_extracts_post_timestamp_segment() -> None:
    assert _interrupt_token("20260425-040000-beta-phase-shipped.md") == "beta-phase-shipped"
    assert _interrupt_token("short.md") == "inflection"


def test_build_impingement_record_has_required_fields(tmp_path: Path) -> None:
    p = _write_inflection(tmp_path, "20260425-040000-beta-test.md", "# Phase 6 shipped\n")
    record = build_impingement_record(p, now=1714000000.0)

    assert record["source"] == "relay.inflection"
    assert record["type"] == "pattern_match"
    assert record["strength"] == 0.6
    assert record["timestamp"] == 1714000000.0
    assert record["id"] == _stable_id(p.name)
    assert record["interrupt_token"] == "beta-test"
    assert record["content"]["filename"] == p.name
    assert record["content"]["narrative"] == "Phase 6 shipped"


def test_tick_emits_one_record_per_new_file(tmp_path: Path) -> None:
    inflections = tmp_path / "inflections"
    inflections.mkdir()
    bus = tmp_path / "impingements.jsonl"

    _write_inflection(inflections, "20260425-040000-alpha-mode-switch.md", "research → rnd")
    _write_inflection(inflections, "20260425-041500-beta-phase-shipped.md", "Phase 0 FULL on main")

    emitted = tick(
        inflections_dir=inflections,
        impingement_path=bus,
    )

    assert sorted(emitted) == [
        "20260425-040000-alpha-mode-switch.md",
        "20260425-041500-beta-phase-shipped.md",
    ]
    lines = bus.read_text().strip().splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert {r["source"] for r in records} == {"relay.inflection"}
    assert {r["interrupt_token"] for r in records} == {"alpha-mode-switch", "beta-phase-shipped"}


def test_tick_is_idempotent_via_cursor(tmp_path: Path) -> None:
    inflections = tmp_path / "inflections"
    inflections.mkdir()
    bus = tmp_path / "impingements.jsonl"

    _write_inflection(inflections, "20260425-040000-alpha-mode-switch.md")
    first = tick(inflections_dir=inflections, impingement_path=bus)
    second = tick(inflections_dir=inflections, impingement_path=bus)

    assert len(first) == 1
    assert second == []
    assert len(bus.read_text().strip().splitlines()) == 1
    assert load_seen(inflections / DEFAULT_CURSOR_FILENAME) == {first[0]}


def test_tick_picks_up_new_files_after_first_run(tmp_path: Path) -> None:
    inflections = tmp_path / "inflections"
    inflections.mkdir()
    bus = tmp_path / "impingements.jsonl"

    _write_inflection(inflections, "20260425-040000-alpha-mode-switch.md")
    tick(inflections_dir=inflections, impingement_path=bus)

    _write_inflection(inflections, "20260425-041500-beta-phase-shipped.md")
    second = tick(inflections_dir=inflections, impingement_path=bus)

    assert second == ["20260425-041500-beta-phase-shipped.md"]
    assert len(bus.read_text().strip().splitlines()) == 2


def test_dry_run_does_not_touch_bus_or_cursor(tmp_path: Path) -> None:
    inflections = tmp_path / "inflections"
    inflections.mkdir()
    bus = tmp_path / "impingements.jsonl"

    _write_inflection(inflections, "20260425-040000-alpha-mode-switch.md")
    emitted = tick(inflections_dir=inflections, impingement_path=bus, dry_run=True)

    assert emitted == ["20260425-040000-alpha-mode-switch.md"]
    assert not bus.exists()
    assert not (inflections / DEFAULT_CURSOR_FILENAME).exists()


def test_backfill_re_emits_existing_files_and_overwrites_cursor(tmp_path: Path) -> None:
    inflections = tmp_path / "inflections"
    inflections.mkdir()
    bus = tmp_path / "impingements.jsonl"

    _write_inflection(inflections, "20260425-040000-alpha-mode-switch.md")
    tick(inflections_dir=inflections, impingement_path=bus)
    assert len(bus.read_text().strip().splitlines()) == 1

    re_emitted = tick(inflections_dir=inflections, impingement_path=bus, backfill=True)
    assert re_emitted == ["20260425-040000-alpha-mode-switch.md"]
    assert len(bus.read_text().strip().splitlines()) == 2


def test_qm2_sampler_observes_pattern_match_after_emit(tmp_path: Path) -> None:
    """Acceptance criterion from v4 audit doc — sampler shows non-zero rate
    after a peer relay event.

    Loads the same ``ImpingementConsumer`` the QM2 sampler uses and
    verifies the bridge's records validate as ``Impingement`` with
    ``type == ImpingementType.PATTERN_MATCH``.
    """
    pytest.importorskip("shared.impingement_consumer")
    from shared.impingement import ImpingementType
    from shared.impingement_consumer import ImpingementConsumer

    inflections = tmp_path / "inflections"
    inflections.mkdir()
    bus = tmp_path / "impingements.jsonl"

    _write_inflection(inflections, "20260425-040000-alpha-mode-switch.md")
    tick(inflections_dir=inflections, impingement_path=bus)

    consumer = ImpingementConsumer(path=bus)
    rows = consumer.read_new()
    assert len(rows) == 1
    assert rows[0].type == ImpingementType.PATTERN_MATCH
    assert rows[0].source == "relay.inflection"
