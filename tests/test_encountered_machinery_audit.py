"""ENCOUNTERED-MACHINERY auditor: the catalogue must convert, at thresholds, into action.

Operator, 2026-09-25 ~01:20Z: "establish a trigger that goes like this: ENCOUNTERED-MACHINERY gains
property X or fulfills test Y -> Do something about it ... We need to make sure that happens in a
methodical way were the pile gets smaller."

The unsafe cases come first. Each is a way the auditor could make the pile look smaller than it is,
act with authority it does not hold, or overwrite a record it does not own.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared import encountered_machinery_audit as ema

REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = REPO_ROOT / "scripts" / "hapax-encountered-machinery-audit"
_spec = importlib.util.spec_from_file_location(
    "hapax_encountered_machinery_audit",
    _SCRIPT,
    loader=importlib.machinery.SourceFileLoader("hapax_encountered_machinery_audit", str(_SCRIPT)),
)
assert _spec and _spec.loader
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

NOW = datetime(2026, 9, 25, 2, 0, 0, tzinfo=UTC)

CATALOGUE = """---
title: fixture
---

# Encountered Machinery

## Current Encounter Register

### M50 Qualification: 2026-09-10T04:25:19Z

Qualified repair.

M40 Awareness readiness and restart limits: left the unit down.

| ID / binding | Obligation | Evaluation | Priority |
|---|---|---|---|
| M01 Installed claim publication | refused twice | repair | NOW |
| M02 Task gate adapter | refused | retain | NEXT |

## Change Record

- M53 (encountered 09-05→present): renameat2 EINVAL on NFS4.

## Change Record — 2026-09-24 fold

| # | encountered defect | witness | cost | owner / disposition | status |
|---|---|---|---|---|---|
| M75 | env leak into child launches | seat 22:27Z | a launch refused | #4729 | FIX-IN-FLIGHT |
| M76 | dispatch broken | seat 22:2xZ | lanes by hand | row `owner-row-20260920` | OPEN |
| M83 | hand-armed release | dev2 23:00Z | 1 h | seat practice | LIVE (practice) |

| M104 | scope spelling | dev16 00:06Z | refusal | practice | OPEN |
| M104 | vibe refuses | seat 00:16Z | blocked | bundle | OPEN |

| M | status | evidence |
|---|---|---|
| M01 | OPEN | not requalified |
| M02 | delivered by #1 | x |
| M40 | ACCEPTED | retained |
| M50 | LIVE | fixed; measured passing (readback) |
| M53 | OPEN | killswitch |
| M104 | FIX-IN-FLIGHT | which one? |
| M104b | FIX-IN-FLIGHT | vibe fix in flight |

| (new, dev17-a) | push/edit deadlock | dev17 00:4xZ | refusal | durable | OPEN |
"""

LEDGER = """# thresholds

## Class ledger (authored; the auditor reads it and never writes it)

| class | members | disposition | row |
|---|---|---|---|
| `claim`: claim state | M01×2, M104b×2 | owed | — |
| `gate`: gate proxy | M02, M76, M104a, new-dev17-a | repair | owner-row-20260920 |
| `liveness`: silent gap | M40, M50, M83×2, M75 | row forced | #4729 |
| `nfs`: mount | M53, M999 | TBD | — |
| `retained`: healthy | | retain | — |
"""


def _owner_rows(**over: ema.OwnerRow | None) -> dict[str, ema.OwnerRow | None]:
    rows: dict[str, ema.OwnerRow | None] = {
        "owner-row-20260920": ema.OwnerRow(
            task_id="owner-row-20260920",
            status="offered",
            created_at=datetime(2026, 9, 20, 0, 0, tzinfo=UTC),
            updated_at=datetime(2026, 9, 20, 0, 0, tzinfo=UTC),
        )
    }
    rows.update(over)
    return rows


def _audit(catalogue: str = CATALOGUE, ledger: str = LEDGER, **kw) -> ema.Audit:
    kw.setdefault("owner_rows", _owner_rows())
    kw.setdefault("trend", ema.Trend.unobserved("fixture"))
    return ema.evaluate(
        ema.parse_catalogue(catalogue),
        ema.parse_ledger(ledger),
        now=NOW,
        **kw,
    )


def _flags(audit: ema.Audit, trigger: str) -> list[ema.Flag]:
    return [f for f in audit.flags if f.trigger == trigger]


# ---------------------------------------------------------------------------------------------
# Unsafe cases: the pile must never be under-reported.


def test_an_unrecognized_status_counts_as_open_never_as_closed() -> None:
    audit = _audit()
    m02 = audit.entry_state["M02"]
    assert m02.effective == "OPEN"
    assert m02.in_pile
    assert any(f.subject == "M02" and "vocabulary" in f.detail for f in _flags(audit, "T7"))


def test_live_without_readback_stays_in_the_pile_as_fix_in_flight() -> None:
    audit = _audit()
    m83 = audit.entry_state["M83"]
    assert m83.effective == "FIX-IN-FLIGHT"
    assert m83.in_pile
    assert [f.subject for f in _flags(audit, "T6")] == ["M83"]
    # LIVE with a readback token leaves the pile.
    assert not audit.entry_state["M50"].in_pile


@pytest.mark.parametrize(
    "evidence",
    [
        "repaired in runner SEATS; no activation readback recorded",
        "fixed without readback",
        "readback missing",
    ],
)
def test_a_negated_readback_is_not_readback(evidence: str) -> None:
    catalogue = CATALOGUE.replace(
        "| M50 | LIVE | fixed; measured passing (readback) |", f"| M50 | LIVE | {evidence} |"
    )
    audit = _audit(catalogue)
    assert audit.entry_state["M50"].in_pile
    assert "M50" in {f.subject for f in _flags(audit, "T6")}


def test_an_entry_with_no_status_counts_as_open() -> None:
    catalogue = CATALOGUE.replace("| M53 | OPEN | killswitch |\n", "")
    audit = _audit(catalogue)
    assert audit.entry_state["M53"].effective == "OPEN"
    assert any(f.subject == "M53" and "no status" in f.detail for f in _flags(audit, "T7"))


def test_an_ambiguous_bare_status_update_is_applied_to_neither_duplicate() -> None:
    audit = _audit()
    assert audit.entry_state["M104a"].effective == "OPEN"
    assert audit.entry_state["M104b"].effective == "FIX-IN-FLIGHT"
    subjects = {f.subject for f in _flags(audit, "T7")}
    assert "M104" in subjects  # duplicate definition and ambiguous update are both flagged


# ---------------------------------------------------------------------------------------------
# The ladder predicates, one pin each.


def test_t1_weighted_two_without_disposition_is_flagged() -> None:
    audit = _audit()
    assert [f.subject for f in _flags(audit, "T1")] == ["claim"]
    # `TBD` is not a disposition, but `nfs` has weight 1 so it is below the threshold.
    assert audit.class_state["nfs"].weighted == 1


def test_t2_weighted_three_without_row_mints_a_reduction_candidate() -> None:
    audit = _audit()
    assert [f.subject for f in _flags(audit, "T2")] == ["claim"]
    kinds = {(c.kind, c.subject) for c in audit.mint_candidates}
    assert ("reduce", "claim") in kinds


def test_t3_owner_row_offered_over_24h_is_escalated_by_flag_only() -> None:
    audit = _audit()
    t3 = _flags(audit, "T3")
    assert [f.subject for f in t3] == ["gate"]
    assert "owner-row-20260920" in t3[0].detail
    assert "p1" in t3[0].detail


def test_t3_a_fresh_owner_row_is_not_escalated() -> None:
    fresh = ema.OwnerRow(
        task_id="owner-row-20260920",
        status="offered",
        created_at=datetime(2026, 9, 25, 1, 0, tzinfo=UTC),
        updated_at=None,
    )
    audit = _audit(owner_rows=_owner_rows(**{"owner-row-20260920": fresh}))
    assert _flags(audit, "T3") == []


def test_t4_three_open_entries_in_one_class_mints_structural_reduction() -> None:
    audit = _audit()
    assert [f.subject for f in _flags(audit, "T4")] == ["gate"]
    assert ("reduce", "gate") in {(c.kind, c.subject) for c in audit.mint_candidates}


def _trend(*shares_and_piles: tuple[float, int]) -> ema.Trend:
    labels = ("-14d", "-7d", "now")
    return ema.Trend(
        points=tuple(
            ema.TrendPoint(label, share, pile, 10, 0)
            for label, (share, pile) in zip(labels, shares_and_piles, strict=True)
        ),
        note="fixture",
    )


def test_t5_an_accidental_share_that_does_not_fall_mints_a_sweep() -> None:
    audit = _audit(trend=_trend((1.0, 3), (1.0, 3), (1.0, 3)))
    assert len(_flags(audit, "T5")) == 1
    assert audit.trend_verdict == "not_falling"
    assert "sweep" in {c.kind for c in audit.mint_candidates}


def test_t5_a_shrinking_pile_of_accidents_still_fires() -> None:
    """Operator: a shrinking pile of accidents is still failure."""
    audit = _audit(trend=_trend((0.8, 30), (0.8, 20), (0.9, 5)))
    assert len(_flags(audit, "T5")) == 1


def test_t5_count_growth_with_a_falling_share_does_not_fire() -> None:
    audit = _audit(trend=_trend((0.9, 3), (0.7, 9), (0.5, 30)))
    assert _flags(audit, "T5") == []
    assert audit.trend_verdict == "falling"


def test_t5_at_zero_accident_does_not_fire() -> None:
    audit = _audit(trend=_trend((0.0, 3), (0.0, 3), (0.0, 3)))
    assert _flags(audit, "T5") == []
    assert audit.trend_verdict == "at_zero"


def test_t5_unobserved_history_never_fires_and_never_claims_improvement() -> None:
    audit = _audit(trend=ema.Trend.unobserved("git unavailable"))
    assert _flags(audit, "T5") == []
    assert audit.trend_verdict == "unobserved"


# ---------------------------------------------------------------------------------------------
# Essential vs accident (operator refinement, 2026-09-25 ~01:50Z).

JUDGMENTS = """
| M | judgment | justification | walls |
|---|---|---|---|
| M40 | RETAIN | the restart budget is an essential bound on liveness, already in its form | W-fx-1 |
| M53 | REMOVE | accidental: an atomic-rename contract the substrate cannot satisfy |  |
| M01 | RECONSTITUTE | claim publication is essential; its NFS-bound form is accidental | W-fx-1, W-fx-2 |
| M02 | RETAIN |  |  |
"""


def test_a_judgment_citing_no_wall_is_flagged() -> None:
    audit = _audit(CATALOGUE + JUDGMENTS)
    no_wall = {f.subject for f in _flags(audit, "T7") if f.detail == "judgment cites no wall ids"}
    assert no_wall == {"M53"}  # M02's RETAIN is already void for want of a justification


def test_t9_a_judgment_resting_on_an_unjudged_or_accidental_wall_is_flagged() -> None:
    # Fixture wall ids only; the wall catalogue owns the real ones.
    assert _flags(_audit(CATALOGUE + JUDGMENTS), "T9") == []  # no wall catalogue yet: not run
    audit = _audit(CATALOGUE + JUDGMENTS, wall_judgments={"W-fx-1": "RETAIN", "W-fx-2": "REMOVE"})
    t9 = {f.subject: f.detail for f in _flags(audit, "T9")}
    assert set(t9) == {"M01"}
    assert "W-fx-2" in t9["M01"] and "W-fx-1" not in t9["M01"]
    audit = _audit(CATALOGUE + JUDGMENTS, wall_judgments={"W-fx-1": None})
    assert {f.subject for f in _flags(audit, "T9")} == {"M40", "M01"}


def test_an_unjudged_catalogue_is_entirely_accidental() -> None:
    audit = _audit()
    assert audit.accidental_share == 1.0
    assert audit.unjudged == audit.entries


def test_judgments_move_the_accidental_share_and_retain_needs_a_justification() -> None:
    audit = _audit(CATALOGUE + JUDGMENTS)
    # total weight 14; not accidental: M40 RETAIN (1) and M01 RECONSTITUTE (2).
    # M02 RETAIN has no justification, so it counts as unjudged. M53 REMOVE is not yet retired.
    assert (audit.accidental_weight, audit.total_weight) == (11, 14)
    assert audit.awaiting_reconstitution == ["M01"]
    assert any(f.subject == "M02" and "justification" in f.detail for f in _flags(audit, "T7"))


def test_a_removed_accident_leaves_the_pile_entirely() -> None:
    retired = "\n| M | status | evidence |\n|---|---|---|\n| M53 | RETIRED | archived |\n"
    audit = _audit(CATALOGUE + JUDGMENTS + retired)
    assert (audit.accidental_weight, audit.total_weight) == (10, 13)


def test_t8_entries_older_than_seven_days_without_judgment_go_to_the_seat() -> None:
    audit = _audit()
    t8 = {f.subject: f.detail for f in _flags(audit, "T8")}
    assert set(t8) == {"claim", "gate", "liveness", "nfs"}
    assert "M76" not in t8["gate"]  # encountered 09-24: younger than 7 d
    judged = {f.subject: f.detail for f in _flags(_audit(CATALOGUE + JUDGMENTS), "T8")}
    assert "nfs" not in judged
    assert "M40" not in judged["liveness"]


def test_t6_is_pinned_above_and_t7_flags_unclassified_and_missing_members() -> None:
    catalogue = CATALOGUE + "| M120 | new thing | dev9 01:00Z | x | y | OPEN |\n"
    audit = _audit(catalogue)
    details = {(f.subject, f.detail.split(":")[0]) for f in _flags(audit, "T7")}
    assert ("M120", "in no class") in details
    assert ("M999", "ledger member not in catalogue") in details
    assert ("new-dev17-a", "no M-number") in details


# ---------------------------------------------------------------------------------------------
# Metric.


def test_weighted_pile_counts_only_hazard_entries_in_the_pile() -> None:
    audit = _audit()
    # claim: M01 (OPEN) 2 + M104b (FIX) 2; gate: M02 1 + M76 1 + M104a 1 + new 1;
    # liveness: M83 (LIVE no readback) 2 + M75 (FIX) 1; nfs: M53 1. M40 ACCEPTED, M50 LIVE+readback.
    assert audit.weighted_pile == 12


# ---------------------------------------------------------------------------------------------
# Actions (the script). Unsafe cases first.


def _layout(tmp_path: Path) -> dict[str, Path]:
    frame = tmp_path / "frame"
    frame.mkdir()
    catalogue = frame / "ENCOUNTERED-MACHINERY.md"
    catalogue.write_text(CATALOGUE, encoding="utf-8")
    ledger = frame / "THRESHOLDS.md"
    ledger.write_text(LEDGER, encoding="utf-8")
    tasks = tmp_path / "tasks"
    for state in ("active", "closed", "refused"):
        (tasks / state).mkdir(parents=True)
    (tasks / "active" / "owner-row-20260920.md").write_text(
        "---\ntype: cc-task\ntask_id: owner-row-20260920\nstatus: offered\n"
        "created_at: 2026-09-20T00:00:00Z\n---\n\n# owner\n",
        encoding="utf-8",
    )
    seat = tmp_path / "lanebus" / "dev1"
    seat.mkdir(parents=True)
    return {
        "catalogue": catalogue,
        "ledger": ledger,
        "tasks": tasks,
        "seat": seat,
        "status": frame / "ENCOUNTERED-MACHINERY-PILE-STATUS.md",
    }


def _run(paths: dict[str, Path], *extra: str) -> tuple[int, dict]:
    argv = [
        "--catalogue",
        str(paths["catalogue"]),
        "--ledger",
        str(paths["ledger"]),
        "--task-root",
        str(paths["tasks"]),
        "--seat-inbox",
        str(paths["seat"]),
        "--pile-status",
        str(paths["status"]),
        "--no-trend",
        "--now",
        "2026-09-25T02:00:00Z",
        *extra,
    ]
    out: list[str] = []
    rc = cli.main(argv, emit=out.append)
    return rc, json.loads(out[-1])


def test_the_auditor_never_writes_the_catalogue_ledger_or_owner_rows(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    owner = paths["tasks"] / "active" / "owner-row-20260920.md"
    before = {p: p.read_bytes() for p in (paths["catalogue"], paths["ledger"], owner)}
    rc, _ = _run(paths)
    assert rc == 0
    for p, data in before.items():
        assert p.read_bytes() == data, f"{p.name} was rewritten"


def test_minted_rows_carry_no_authority_and_are_not_claimable(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    rc, report = _run(paths)
    assert rc == 0
    assert report["minted"], "the fixture backlog must mint"
    for rel in report["minted"]:
        text = Path(rel).read_text(encoding="utf-8")
        front, _ = ema.split_frontmatter(text)
        assert front["status"] == "offered"
        assert front["assigned_to"] == "unassigned"
        assert "claimable" not in front
        for key in (
            "implementation_authorized",
            "source_mutation_authorized",
            "runtime_mutation_authorized",
            "release_authorized",
        ):
            assert front[key] is False, key
        assert "same shape again is prohibited" in text.lower()


def test_minting_never_overwrites_and_never_remints_a_closed_reduction(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    closed = paths["tasks"] / "closed" / "encountered-machinery-reduce-claim-20260901.md"
    closed.write_text("---\ntask_id: x\nstatus: done\n---\n", encoding="utf-8")
    rc, report = _run(paths)
    assert rc == 0
    assert not any("reduce-claim" in m for m in report["minted"])
    assert closed.read_text(encoding="utf-8") == "---\ntask_id: x\nstatus: done\n---\n"
    assert any("still firing" in f["detail"] for f in report["flags"] if f["subject"] == "claim")
    # A second run mints nothing new: every candidate now has an active row.
    rc, again = _run(paths)
    assert rc == 0
    assert again["minted"] == []


def test_the_wip_cap_bounds_open_auto_minted_rows(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    rc, report = _run(paths, "--wip-cap", "1")
    assert rc == 0
    assert len(report["minted"]) == 1
    assert report["deferred"], "candidates past the cap are reported, not dropped"


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    rc, report = _run(paths, "--dry-run")
    assert rc == 0
    assert report["would_mint"]
    assert not paths["status"].exists()
    assert list(paths["seat"].iterdir()) == []
    assert list((paths["tasks"] / "active").iterdir()) == [
        paths["tasks"] / "active" / "owner-row-20260920.md"
    ]


def test_flags_post_once_per_change_and_status_rewrites_only_on_change(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    rc, first = _run(paths)
    assert rc == 0
    drops = sorted(paths["seat"].iterdir())
    assert len(drops) == 1
    assert "from: encountered-machinery-audit" in drops[0].read_text(encoding="utf-8")
    status_bytes = paths["status"].read_bytes()
    rc, second = _run(paths)
    assert rc == 0
    assert sorted(paths["seat"].iterdir()) == drops, "an unchanged flag set must not re-post"
    assert paths["status"].read_bytes() == status_bytes
    assert second["status_written"] is False


def test_a_missing_seat_inbox_is_an_error_and_is_not_created(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    paths["seat"].rmdir()
    rc, report = _run(paths)
    assert rc == 1
    assert not paths["seat"].exists()
    assert report["errors"]
    # The fingerprint is not recorded, so the next run posts again.
    front, _ = ema.split_frontmatter(paths["status"].read_text(encoding="utf-8"))
    assert front.get("posted_flag_fingerprint") in (None, "")


def test_a_non_designated_host_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    """Every host runs hapax-determine against one shared vault; only one may act on it."""
    paths = _layout(tmp_path)
    monkeypatch.setattr(cli.socket, "gethostname", lambda: "hapax-appendix")
    rc, report = _run(paths, "--run-on-host", "hapax-podium")
    assert rc == 0
    assert report["skipped"].startswith("not the designated host")
    assert not paths["status"].exists()
    assert list(paths["seat"].iterdir()) == []
    assert len(list((paths["tasks"] / "active").iterdir())) == 1
    monkeypatch.setattr(cli.socket, "gethostname", lambda: "hapax-podium.local")
    rc, report = _run(paths, "--run-on-host", "hapax-podium")
    assert rc == 0
    assert "skipped" not in report
    assert paths["status"].exists()


def test_an_unreadable_catalogue_fails_loudly(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    paths["catalogue"].unlink()
    rc, report = _run(paths)
    assert rc == 2
    assert "next action" in report["errors"][0]


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("| `nfs`: mount | M53, M999 | TBD | — |", "| `nfs`: mount | M53, M999 | TBD |"),
        ("| `nfs`: mount |", "| nfs mount |"),
    ],
)
def test_every_ledger_error_names_a_next_action(old: str, new: str) -> None:
    """executive_function: errors must include next actions (review finding on #4754)."""
    with pytest.raises(ema.LedgerError, match="next action"):
        ema.parse_ledger(LEDGER.replace(old, new))


# ---------------------------------------------------------------------------------------------
# T5 input: the catalogue's own git history, through the real path (review finding on #4754).

FOLD = (
    "# E\n\n## Change Record — 2026-09-24 fold\n\n"
    "| # | encountered defect | witness | cost | owner / disposition | status |\n"
    "|---|---|---|---|---|---|\n"
)
ROW75 = "| M75 | env leak | seat 22:27Z | a launch refused | #4729 | FIX-IN-FLIGHT |\n"
ROW76 = "| M76 | dispatch broken | seat 22:2xZ | lanes by hand | bundle | OPEN |\n"
ROW83 = "| M83 | hand-armed release | dev2 23:00Z | 1 h | seat practice | LIVE (practice) |\n"


def _git_repo_with_history(tmp_path: Path) -> Path:
    repo = tmp_path / "vault"
    catalogue = repo / "frame" / "ENCOUNTERED-MACHINERY.md"
    catalogue.parent.mkdir(parents=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    for text, when in (
        (FOLD + ROW75, "2026-09-10T00:00:00Z"),  # before -14 d
        (FOLD + ROW75 + ROW76, "2026-09-17T00:00:00Z"),  # before -7 d
    ):
        catalogue.write_text(text, encoding="utf-8")
        dated = {**env, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=dated)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", when], check=True, env=dated)
    catalogue.write_text(FOLD + ROW75 + ROW76 + ROW83, encoding="utf-8")  # now, uncommitted
    return catalogue


def test_load_trend_reconstructs_past_windows_from_real_git_history(tmp_path: Path) -> None:
    catalogue = _git_repo_with_history(tmp_path)
    ledger = ema.parse_ledger(LEDGER)
    current = ema.evaluate(
        ema.parse_catalogue(catalogue.read_text(encoding="utf-8")),
        ledger,
        now=NOW,
        owner_rows={},
        trend=ema.Trend.unobserved("pending"),
    )
    trend = cli.load_trend(catalogue, ledger, NOW, current)
    assert [(p.label, p.pile, p.entries) for p in trend.points] == [
        ("-14d", 1, 1),
        ("-7d", 2, 2),
        ("now", 4, 3),
    ], trend.note
    assert "frame/ENCOUNTERED-MACHINERY.md" in trend.note


def test_load_trend_outside_git_is_unobserved_not_an_error(tmp_path: Path) -> None:
    catalogue = tmp_path / "ENCOUNTERED-MACHINERY.md"
    catalogue.write_text(FOLD + ROW75, encoding="utf-8")
    current = ema.evaluate(
        ema.parse_catalogue(FOLD + ROW75),
        ema.parse_ledger(LEDGER),
        now=NOW,
        owner_rows={},
        trend=ema.Trend.unobserved("pending"),
    )
    trend = cli.load_trend(catalogue, ema.parse_ledger(LEDGER), NOW, current)
    assert trend.points == ()
    assert trend.note.startswith("trend unobserved")


@pytest.mark.parametrize("bad", ["M01 x2 y", "Mfoo"])
def test_an_unparseable_ledger_member_is_a_hygiene_flag(bad: str) -> None:
    ledger = LEDGER.replace("M53, M999", f"M53, {bad}")
    audit = _audit(ledger=ledger)
    assert any("unparseable" in f.detail for f in _flags(audit, "T7"))
