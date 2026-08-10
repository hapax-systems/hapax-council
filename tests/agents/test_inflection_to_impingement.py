"""The inflection bridge reads the severity that inflections already declare.

Before this, `build_impingement_record` stamped a constant 0.6 on every file, so a P0 reading
"ACTIVE DATA LOSS, still running at time of writing" entered the affordance pipeline at exactly
the salience of a P1 the operator had de-escalated as "just a note". Measured 2026-08-10: 16 P0
and 4 P1 in the live directory, all at 0.6.

The boundary these tests defend is that this is SEVERITY and not AUTHOR weighting. Severity is a
declared, author-independent field; no measured reliability exists for any author on this
surface, and inventing one would be the unmeasured weight the doctrine forbids.

Self-contained per the repo testing convention (no shared conftest fixtures).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.inflection_to_impingement import (  # noqa: E402
    _DEFAULT_STRENGTH,
    build_impingement_record,
    read_severity,
    strength_for,
    tick,
)

HEADER = "# {title}\n\n**Severity:** {sev}\n**Source:** measured\n\nbody text\n"


def _write(d: Path, name: str, sev: str | None, title: str = "T") -> Path:
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    if sev is None:
        path.write_text(f"# {title}\n\nno severity declared\n", encoding="utf-8")
    else:
        path.write_text(HEADER.format(title=title, sev=sev), encoding="utf-8")
    return path


def test_declared_severity_sets_strength(tmp_path: Path) -> None:
    assert strength_for(_write(tmp_path, "a.md", "P0")) == 0.95
    assert strength_for(_write(tmp_path, "b.md", "P1")) == 0.75
    assert strength_for(_write(tmp_path, "c.md", "P2")) == 0.5


def test_p0_outranks_p1_which_outranks_p2(tmp_path: Path) -> None:
    """The ordering is the point; the exact constants are tuning."""
    p0 = strength_for(_write(tmp_path, "a.md", "P0"))
    p1 = strength_for(_write(tmp_path, "b.md", "P1"))
    p2 = strength_for(_write(tmp_path, "c.md", "P2"))
    assert p0 > p1 > p2


def test_undeclared_severity_keeps_the_old_constant(tmp_path: Path) -> None:
    """An inflection with no header is no less urgent than it was yesterday.

    Demoting it would make the bridge punish the author for a missing field instead of
    reporting the gap, and would quietly lower the salience of every pre-existing file.
    """
    assert strength_for(_write(tmp_path, "a.md", None)) == _DEFAULT_STRENGTH
    assert read_severity(_write(tmp_path, "b.md", None)) is None


def test_severity_is_recorded_but_source_stays_constant(tmp_path: Path) -> None:
    """`source` MUST remain the channel tag.

    shared/affordance_pipeline.py hashes `impingement.source` into feed_habituation and dedupes
    on source + content_hash. Varying it per author or severity would partition the habituation
    key for every producer on the bus and re-fire every already-seen impingement as novel.
    """
    record = build_impingement_record(_write(tmp_path, "a.md", "P0"))
    assert record["source"] == "relay.inflection"
    assert record["strength"] == 0.95
    assert record["content"]["severity"] == "P0"


def test_emission_is_ordered_by_severity_not_filename(tmp_path: Path) -> None:
    """The regression that existed: a P1 named `b-*` went out ahead of a P0 named `c-*`.

    Filename is a provenance-adjacent proxy and was the only ranking signal in the channel.
    """
    inflections = tmp_path / "inflections"
    _write(inflections, "b-note.md", "P1")
    _write(inflections, "c-data-loss.md", "P0")
    _write(inflections, "a-minor.md", "P2")

    emitted = tick(
        inflections_dir=inflections,
        impingement_path=tmp_path / "imp.jsonl",
        dry_run=True,
    )
    assert emitted == ["c-data-loss.md", "b-note.md", "a-minor.md"]


def test_equal_severity_ties_break_on_filename(tmp_path: Path) -> None:
    """Deterministic order at equal severity, so emission is reproducible."""
    inflections = tmp_path / "inflections"
    _write(inflections, "z.md", "P0")
    _write(inflections, "a.md", "P0")
    emitted = tick(
        inflections_dir=inflections,
        impingement_path=tmp_path / "imp.jsonl",
        dry_run=True,
    )
    assert emitted == ["a.md", "z.md"]


def test_records_are_written_with_severity_strength(tmp_path: Path) -> None:
    inflections = tmp_path / "inflections"
    _write(inflections, "a.md", "P0")
    out = tmp_path / "imp.jsonl"
    tick(inflections_dir=inflections, impingement_path=out)
    record = json.loads(out.read_text(encoding="utf-8").strip())
    assert record["strength"] == 0.95
    assert record["content"]["severity"] == "P0"


def test_severity_is_not_read_from_the_body(tmp_path: Path) -> None:
    """Only the declared header counts.

    Prose mentioning P0 must not promote a file, or every inflection discussing severity
    promotes itself.
    """
    path = tmp_path / "a.md"
    path.write_text(
        "# Title\n\nThis note discusses **Severity:** levels and mentions P0 in passing.\n",
        encoding="utf-8",
    )
    assert read_severity(path) is None
    assert strength_for(path) == _DEFAULT_STRENGTH
