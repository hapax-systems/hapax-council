"""Daily Velocity:Quality Observatory feeder.

Verifies the feeder honours the observatory ISAP anti-gaming constraint (objective
sources only) and that its daily note is a daemon-owned projection written through
the OQ-9 governed vault writer.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from shared.code_churn import ChurnResult
from shared.frontmatter import parse_frontmatter
from shared.vault_ownership import is_daemon_writable
from shared.velocity_quality_observatory import (
    NOTE_TYPE,
    Observation,
    build_body,
    build_frontmatter,
    collect_observation,
    count_hook_rejections,
    read_velocity_report,
    write_observation,
)


def _obs(**kw: object) -> Observation:
    base: dict = dict(
        date="2026-05-31",
        commits=12,
        lines_added=300,
        lines_deleted=40,
        churn_ratio=0.133,
        hook_rejections=3,
        prs_merged=7,
    )
    base.update(kw)
    return Observation(**base)  # type: ignore[arg-type]


def test_observatory_note_type_is_daemon_owned() -> None:
    # The feeder writes a pure system projection: every key is daemon-owned.
    assert is_daemon_writable(NOTE_TYPE, "commits")
    assert is_daemon_writable(NOTE_TYPE, "anything_at_all")


def test_build_frontmatter_carries_objective_fields() -> None:
    fm = build_frontmatter(_obs())
    assert fm["type"] == "observatory"
    assert fm["commits"] == 12
    assert fm["churn_ratio"] == 0.133
    assert fm["hook_rejections"] == 3
    assert fm["prs_merged"] == 7
    assert fm["generated_by"] == "velocity_quality_observatory"


def test_build_body_is_honest_about_absent_sources() -> None:
    body = build_body(_obs(hook_rejections=None, prs_merged=None))
    assert "uninstrumented" in body
    assert "Churn ratio" in body


def test_write_observation_writes_parseable_governed_note(tmp_path: Path) -> None:
    path = write_observation(_obs(), observatory_dir=tmp_path)
    assert path == tmp_path / "2026-05-31-velocity-quality.md"
    fm, body = parse_frontmatter(path)
    assert fm["type"] == "observatory"
    assert fm["commits"] == 12
    assert "Churn ratio" in body


def test_count_hook_rejections_absent_returns_none(tmp_path: Path) -> None:
    assert count_hook_rejections(tmp_path / "absent.jsonl") is None


def test_count_hook_rejections_counts_and_filters_by_date(tmp_path: Path) -> None:
    p = tmp_path / "hooks.jsonl"
    p.write_text(
        json.dumps({"ts": "2026-05-31T10:00:00Z", "hook": "a"})
        + "\n"
        + json.dumps({"ts": "2026-05-31T11:00:00Z", "hook": "b"})
        + "\n"
        + json.dumps({"ts": "2026-05-30T09:00:00Z", "hook": "c"})
        + "\n",
        encoding="utf-8",
    )
    assert count_hook_rejections(p, date="2026-05-31") == 2
    assert count_hook_rejections(p) == 3


def test_count_hook_rejections_skips_malformed_when_filtering(tmp_path: Path) -> None:
    p = tmp_path / "h.jsonl"
    p.write_text(json.dumps({"ts": "2026-05-31T00:00:00Z"}) + "\ngarbage line\n", encoding="utf-8")
    assert count_hook_rejections(p, date="2026-05-31") == 1


def test_read_velocity_report(tmp_path: Path) -> None:
    (tmp_path / "2026-05-31-velocity.json").write_text(
        json.dumps({"velocity": {"prs_merged": 9}}), encoding="utf-8"
    )
    data = read_velocity_report("2026-05-31", observatory_dir=tmp_path)
    assert data is not None
    assert data["velocity"]["prs_merged"] == 9
    assert read_velocity_report("1999-01-01", observatory_dir=tmp_path) is None


def test_collect_observation_assembles_objective_sources(tmp_path: Path) -> None:
    obsdir = tmp_path / "obs"
    obsdir.mkdir()
    (obsdir / "2026-05-31-velocity.json").write_text(
        json.dumps({"velocity": {"prs_merged": 7}}), encoding="utf-8"
    )
    hooks = tmp_path / "h.jsonl"
    hooks.write_text(json.dumps({"ts": "2026-05-31T01:00:00Z"}) + "\n", encoding="utf-8")

    with patch(
        "shared.velocity_quality_observatory.compute_churn",
        return_value=ChurnResult(commits=5, lines_added=100, lines_deleted=20),
    ):
        obs = collect_observation(
            "2026-05-31", repo=tmp_path, observatory_dir=obsdir, hook_path=hooks
        )

    assert obs.commits == 5
    assert obs.lines_added == 100
    assert obs.churn_ratio == 0.2
    assert obs.hook_rejections == 1
    assert obs.prs_merged == 7
