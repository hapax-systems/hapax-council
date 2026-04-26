"""Tests for ``agents.operator_awareness.weekly_review``.

Pure-function coverage: section extraction, awareness/refused
parsers, week-bounds math, rollup correctness across synthetic
daily notes, render shape (no verdicts, no aggregate severity),
write idempotency.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from agents.operator_awareness.weekly_review import (
    REFUSED_CAP,
    WeeklyRollup,
    _extract_section,
    _week_bounds,
    collect_week,
    parse_awareness_section,
    parse_refused_section,
    render_weekly_review,
    write_weekly_review,
)

# ── _week_bounds ────────────────────────────────────────────────────


class TestWeekBounds:
    def test_monday_to_sunday(self):
        # 2026-04-26 is a Sunday (ISO weekday 7).
        monday, sunday = _week_bounds(date(2026, 4, 26))
        assert monday == date(2026, 4, 20)
        assert sunday == date(2026, 4, 26)

    def test_midweek_input_yields_same_iso_week(self):
        monday, sunday = _week_bounds(date(2026, 4, 22))  # Wednesday
        assert monday == date(2026, 4, 20)
        assert sunday == date(2026, 4, 26)


# ── _extract_section ────────────────────────────────────────────────


class TestExtractSection:
    def test_returns_none_when_heading_absent(self):
        assert _extract_section("# Daily\n\n## Log\n\n- entry\n", "## Awareness") is None

    def test_extracts_until_next_h2(self):
        text = "## Awareness\n\n- a\n- b\n\n## Refused\n\n- r1\n"
        body = _extract_section(text, "## Awareness")
        assert body is not None
        assert "- a" in body
        assert "- b" in body
        assert "Refused" not in body

    def test_extracts_until_eof_when_no_next_heading(self):
        text = "## Awareness\n\n- a\n- b\n"
        body = _extract_section(text, "## Awareness")
        assert body is not None
        assert "- a" in body and "- b" in body


# ── parse_awareness_section ─────────────────────────────────────────


class TestParseAwareness:
    def test_extracts_known_fields(self):
        body = (
            "_15m tick · last sync 14:00 UTC_\n\n"
            "- Stream: live · 12 events/5min\n"
            "- Health: degraded · failed=2 · disk 42% · GPU 33%\n"
            "- Daimonion: stance=ALERT · voice-on\n"
            "- Music: source=soundcloud · playing\n"
            "- Publishing: inbox=3 · in-flight=1\n"
            "- Research: in-flight=2\n"
            "- Programmes: active=GEM\n"
            "- Marketing: pending=5\n"
            "- Fleet: pi 3/5 online\n"
            "- Sprint: day=28 · completed=14 · blocked=1\n"
            "- Governance: contracts=4\n"
        )
        out = parse_awareness_section(body)
        assert out["stream_events_5min"] == 12
        assert out["health_failed_units"] == 2
        assert out["disk_pct"] == 42
        assert out["gpu_pct"] == 33
        assert out["publishing_inbox"] == 3
        assert out["publishing_in_flight"] == 1
        assert out["research_in_flight"] == 2
        assert out["marketing_pending"] == 5
        assert out["sprint_completed"] == 14
        assert out["sprint_blocked"] == 1
        assert out["governance_contracts"] == 4
        assert out["fleet_pi_online"] == 3

    def test_missing_lines_omitted(self):
        out = parse_awareness_section("- Stream: live · 5 events/5min\n")
        assert out == {"stream_events_5min": 5}


# ── parse_refused_section ───────────────────────────────────────────


class TestParseRefused:
    def test_extracts_rows(self):
        body = (
            "- 14:00 · axiom=single_user · surface=publication_bus:bandcamp · reason=ToS\n"
            "- 14:05 · axiom=interpersonal_transparency · surface=affordance_pipeline:consent_gate · reason=no contract\n"
        )
        rows = parse_refused_section(body)
        assert len(rows) == 2
        assert rows[0]["axiom"] == "single_user"
        assert rows[0]["surface"] == "publication_bus:bandcamp"
        assert rows[1]["reason"] == "no contract"

    def test_skips_non_row_lines(self):
        body = (
            "_first-class refusal log · raw entries, no aggregation_\n\n"
            "- 14:00 · axiom=x · surface=y · reason=r\n"
            "Some prose line\n"
        )
        rows = parse_refused_section(body)
        assert len(rows) == 1


# ── collect_week ────────────────────────────────────────────────────


def _write_daily(dir: Path, day: date, *, awareness: str = "", refused: str = "") -> None:
    sections: list[str] = [f"# Daily {day.isoformat()}"]
    if awareness:
        sections.append(f"## Awareness\n\n{awareness}")
    if refused:
        sections.append(f"## Refused\n\n{refused}")
    (dir / f"{day.isoformat()}.md").write_text("\n\n".join(sections) + "\n", encoding="utf-8")


class TestCollectWeek:
    def test_empty_window(self, tmp_path: Path):
        rollup = collect_week(week_end=date(2026, 4, 26), daily_dir=tmp_path)
        assert rollup.days_observed == 0
        assert rollup.awareness_totals == {}
        assert rollup.refused_total == 0

    def test_aggregates_across_days(self, tmp_path: Path):
        _write_daily(
            tmp_path,
            date(2026, 4, 22),
            awareness="- Publishing: inbox=3 · in-flight=1\n",
            refused="- 14:00 · axiom=x · surface=y · reason=r1\n",
        )
        _write_daily(
            tmp_path,
            date(2026, 4, 23),
            awareness="- Publishing: inbox=2 · in-flight=4\n",
            refused="- 09:00 · axiom=x · surface=z · reason=r2\n",
        )
        rollup = collect_week(week_end=date(2026, 4, 26), daily_dir=tmp_path)
        assert rollup.days_observed == 2
        assert rollup.awareness_totals["publishing_inbox"] == 5
        assert rollup.awareness_totals["publishing_in_flight"] == 5
        assert rollup.refused_total == 2
        assert rollup.refused_by_axiom == {"x": 2}
        assert rollup.refused_by_surface == {"y": 1, "z": 1}

    def test_skips_missing_daily_notes(self, tmp_path: Path):
        _write_daily(tmp_path, date(2026, 4, 24), awareness="- Marketing: pending=7\n")
        rollup = collect_week(week_end=date(2026, 4, 26), daily_dir=tmp_path)
        assert rollup.days_observed == 1
        assert rollup.awareness_totals["marketing_pending"] == 7


# ── render_weekly_review ────────────────────────────────────────────


class TestRender:
    def _rollup(self, **k: object) -> WeeklyRollup:
        defaults: dict[str, object] = {
            "week_start": date(2026, 4, 20),
            "week_end": date(2026, 4, 26),
            "iso_year": 2026,
            "iso_week": 17,
            "days_observed": 7,
        }
        defaults.update(k)
        return WeeklyRollup(**defaults)  # type: ignore[arg-type]

    def test_includes_week_label_and_range(self):
        text = render_weekly_review(self._rollup())
        assert "2026-W17" in text
        assert "2026-04-20 → 2026-04-26" in text
        assert "7/7 days observed" in text

    def test_renders_zero_refusals_explicitly(self):
        text = render_weekly_review(self._rollup())
        assert "total refusals: 0" in text

    def test_no_verdict_or_severity_language(self):
        """Constitutional invariant: no aggregate verdict, no
        severity ranking, no recommended-action prose. Per drop §3
        fresh pattern #3 caveat: refusals never get summary judgment."""
        text = render_weekly_review(
            self._rollup(
                refused_total=42,
                refused_by_axiom={"x": 30, "y": 12},
                refused_by_surface={"a": 25, "b": 17},
                refused_entries=[
                    {
                        "date": "2026-04-22",
                        "ts": "10:00",
                        "axiom": "x",
                        "surface": "a",
                        "reason": "r",
                    }
                ],
            )
        )
        lower = text.lower()
        for forbidden in (
            "verdict",
            "severity",
            "worst",
            "best week",
            "recommend",
            "you should",
            "operator should",
        ):
            assert forbidden not in lower

    def test_caps_refused_entries(self):
        entries = [
            {
                "date": "2026-04-22",
                "ts": f"10:{i:02d}",
                "axiom": "x",
                "surface": "y",
                "reason": str(i),
            }
            for i in range(REFUSED_CAP + 25)
        ]
        text = render_weekly_review(
            self._rollup(refused_total=len(entries), refused_entries=entries)
        )
        # Cap line acknowledges omission + points at archive.
        assert "+25 more entries" in text
        assert "hapax-state/refusals" in text


# ── write_weekly_review ─────────────────────────────────────────────


class TestWriteIdempotent:
    def test_two_runs_produce_identical_file(self, tmp_path: Path):
        daily = tmp_path / "daily"
        weekly = tmp_path / "weekly"
        daily.mkdir()
        _write_daily(
            daily,
            date(2026, 4, 22),
            awareness="- Publishing: inbox=1 · in-flight=0\n",
            refused="- 09:00 · axiom=x · surface=y · reason=r\n",
        )
        path_a = write_weekly_review(week_end=date(2026, 4, 26), daily_dir=daily, weekly_dir=weekly)
        text_a = path_a.read_text(encoding="utf-8")
        path_b = write_weekly_review(week_end=date(2026, 4, 26), daily_dir=daily, weekly_dir=weekly)
        text_b = path_b.read_text(encoding="utf-8")
        # Same path (deterministic from week label) + same content.
        assert path_a == path_b
        assert text_a == text_b

    def test_writes_to_weekly_subdir_creating_it(self, tmp_path: Path):
        daily = tmp_path / "daily"
        weekly = tmp_path / "deep" / "nested" / "weekly"
        daily.mkdir()
        path = write_weekly_review(week_end=date(2026, 4, 26), daily_dir=daily, weekly_dir=weekly)
        assert weekly.exists()
        assert path.parent == weekly
        assert path.name == "weekly-2026-W17.md"
