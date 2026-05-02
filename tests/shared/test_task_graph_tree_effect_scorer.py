"""Tests for the task-graph tree-effect scorer.

Uses tmp_path with synthetic vault notes so the suite never depends
on the operator's live vault state.
"""

from __future__ import annotations

from pathlib import Path

from shared.task_graph_tree_effect_scorer import (
    DEFAULT_DRIFT_THRESHOLD,
    TREE_EFFECT_SCORE_CAP,
    ScoreReport,
    _build_reverse_edges,
    _normalize_to_score_cap,
    _parse_depends_on,
    _transitive_downstream,
    build_score_report,
    compute_drift,
    compute_tree_effect_scores,
    load_task_graph,
)


def _write_task(
    vault: Path,
    *,
    subdir: str,
    task_id: str,
    status: str,
    depends_on: list[str] | None = None,
    declared_tree_effect: float | None = None,
) -> None:
    """Write a minimal vault cc-task note for testing."""
    body = ["---", "type: cc-task", f"task_id: {task_id}", f"status: {status}"]
    if depends_on:
        body.append("depends_on:")
        for dep in depends_on:
            body.append(f"  - {dep}")
    else:
        body.append("depends_on: []")
    if declared_tree_effect is not None:
        body.append(f"braid_tree_effect: {declared_tree_effect}")
    body.append("---")
    body.append(f"# {task_id}")
    (vault / subdir).mkdir(parents=True, exist_ok=True)
    (vault / subdir / f"{task_id}.md").write_text("\n".join(body), encoding="utf-8")


# ── depends_on parser ───────────────────────────────────────────────


class TestDependsOnParser:
    def test_inline_empty_list(self) -> None:
        assert _parse_depends_on("depends_on: []\n") == ()

    def test_inline_single(self) -> None:
        assert _parse_depends_on("depends_on: [foo]\n") == ("foo",)

    def test_inline_multiple(self) -> None:
        assert _parse_depends_on("depends_on: [foo, bar, baz]\n") == ("foo", "bar", "baz")

    def test_block_form(self) -> None:
        text = "depends_on:\n  - foo\n  - bar\n  - baz\nstatus: offered\n"
        assert _parse_depends_on(text) == ("foo", "bar", "baz")

    def test_block_form_quotes_stripped(self) -> None:
        text = "depends_on:\n  - \"foo\"\n  - 'bar'\nstatus: offered\n"
        assert _parse_depends_on(text) == ("foo", "bar")

    def test_no_depends_on_field(self) -> None:
        assert _parse_depends_on("status: offered\nproducer: x\n") == ()


# ── load_task_graph ─────────────────────────────────────────────────


class TestLoadTaskGraph:
    def test_loads_active_and_closed(self, tmp_path: Path) -> None:
        _write_task(tmp_path, subdir="active", task_id="a", status="offered")
        _write_task(tmp_path, subdir="closed", task_id="b", status="done")
        graph = load_task_graph(tmp_path)
        assert set(graph.keys()) == {"a", "b"}
        assert graph["a"].status == "offered"
        assert graph["b"].status == "done"

    def test_active_overrides_closed_for_duplicate_id(self, tmp_path: Path) -> None:
        _write_task(tmp_path, subdir="closed", task_id="a", status="done")
        _write_task(tmp_path, subdir="active", task_id="a", status="offered")
        graph = load_task_graph(tmp_path)
        assert graph["a"].status == "offered"

    def test_skips_non_cc_task_files(self, tmp_path: Path) -> None:
        (tmp_path / "active").mkdir()
        (tmp_path / "active" / "readme.md").write_text("# README\nNo frontmatter.")
        graph = load_task_graph(tmp_path)
        assert graph == {}

    def test_missing_directories_returns_empty(self, tmp_path: Path) -> None:
        assert load_task_graph(tmp_path) == {}

    def test_braid_tree_effect_parsed_when_present(self, tmp_path: Path) -> None:
        _write_task(
            tmp_path,
            subdir="active",
            task_id="a",
            status="offered",
            declared_tree_effect=7.5,
        )
        graph = load_task_graph(tmp_path)
        assert graph["a"].declared_braid_tree_effect == 7.5


# ── Reverse edges + transitive downstream ───────────────────────────


class TestGraphAlgorithms:
    def test_reverse_edges_built_correctly(self, tmp_path: Path) -> None:
        # a → depends on → root
        # b → depends on → root
        # c → depends on → a (so root unblocks a, a unblocks c)
        _write_task(tmp_path, subdir="active", task_id="root", status="offered")
        _write_task(tmp_path, subdir="active", task_id="a", status="offered", depends_on=["root"])
        _write_task(tmp_path, subdir="active", task_id="b", status="offered", depends_on=["root"])
        _write_task(tmp_path, subdir="active", task_id="c", status="offered", depends_on=["a"])
        graph = load_task_graph(tmp_path)
        reverse = _build_reverse_edges(graph)
        assert reverse["root"] == {"a", "b"}
        assert reverse["a"] == {"c"}
        assert reverse["b"] == set()
        assert reverse["c"] == set()

    def test_transitive_downstream_walks_full_chain(self, tmp_path: Path) -> None:
        _write_task(tmp_path, subdir="active", task_id="root", status="offered")
        _write_task(tmp_path, subdir="active", task_id="a", status="offered", depends_on=["root"])
        _write_task(tmp_path, subdir="active", task_id="b", status="offered", depends_on=["a"])
        _write_task(tmp_path, subdir="active", task_id="c", status="offered", depends_on=["b"])
        graph = load_task_graph(tmp_path)
        reverse = _build_reverse_edges(graph)
        assert _transitive_downstream("root", reverse) == {"a", "b", "c"}

    def test_unknown_dep_is_silently_dropped(self, tmp_path: Path) -> None:
        _write_task(
            tmp_path,
            subdir="active",
            task_id="a",
            status="offered",
            depends_on=["nonexistent"],
        )
        graph = load_task_graph(tmp_path)
        reverse = _build_reverse_edges(graph)
        # 'a' depends on something not in the graph; reverse map for
        # 'nonexistent' isn't created → no crash, no entry
        assert "nonexistent" not in reverse


# ── Score normalization ─────────────────────────────────────────────


class TestScoreNormalization:
    def test_zero_unblocks_yields_zero_score(self) -> None:
        assert _normalize_to_score_cap(0) == 0.0

    def test_score_caps_at_ten(self) -> None:
        assert _normalize_to_score_cap(100) == TREE_EFFECT_SCORE_CAP
        assert _normalize_to_score_cap(1000) == TREE_EFFECT_SCORE_CAP

    def test_score_monotonic(self) -> None:
        prev = -1.0
        for n in (0, 1, 2, 4, 8, 16, 32):
            score = _normalize_to_score_cap(n)
            assert score > prev or score == TREE_EFFECT_SCORE_CAP
            prev = score


# ── compute_tree_effect_scores ──────────────────────────────────────


class TestComputeTreeEffect:
    def test_only_offered_default(self, tmp_path: Path) -> None:
        # done task has 2 downstream — should NOT appear in scores
        _write_task(tmp_path, subdir="closed", task_id="root", status="done")
        _write_task(tmp_path, subdir="active", task_id="a", status="offered", depends_on=["root"])
        _write_task(tmp_path, subdir="active", task_id="b", status="offered", depends_on=["root"])
        graph = load_task_graph(tmp_path)
        scores = compute_tree_effect_scores(graph)
        score_ids = {s.task_id for s in scores}
        assert "root" not in score_ids
        assert "a" in score_ids
        assert "b" in score_ids

    def test_root_with_two_offered_downstream_scored(self, tmp_path: Path) -> None:
        _write_task(tmp_path, subdir="active", task_id="root", status="offered")
        _write_task(tmp_path, subdir="active", task_id="a", status="offered", depends_on=["root"])
        _write_task(tmp_path, subdir="active", task_id="b", status="offered", depends_on=["root"])
        graph = load_task_graph(tmp_path)
        scores = {s.task_id: s for s in compute_tree_effect_scores(graph)}
        root_score = scores["root"]
        assert root_score.unblock_count == 2
        assert root_score.downstream_offered_count == 2
        assert root_score.computed_tree_effect > 0

    def test_scores_sorted_by_computed_descending(self, tmp_path: Path) -> None:
        _write_task(tmp_path, subdir="active", task_id="root", status="offered")
        _write_task(tmp_path, subdir="active", task_id="leaf", status="offered")
        _write_task(tmp_path, subdir="active", task_id="a", status="offered", depends_on=["root"])
        _write_task(tmp_path, subdir="active", task_id="b", status="offered", depends_on=["root"])
        graph = load_task_graph(tmp_path)
        scores = compute_tree_effect_scores(graph)
        assert scores[0].task_id == "root"  # highest
        assert scores[-1].computed_tree_effect <= scores[0].computed_tree_effect


# ── compute_drift ───────────────────────────────────────────────────


class TestDrift:
    def test_drift_flagged_when_above_threshold(self, tmp_path: Path) -> None:
        _write_task(
            tmp_path,
            subdir="active",
            task_id="root",
            status="offered",
            declared_tree_effect=2.0,
        )
        # 4 downstream → computed ~5.8, declared 2.0, delta ~3.8 → flagged
        for child in ("a", "b", "c", "d"):
            _write_task(
                tmp_path,
                subdir="active",
                task_id=child,
                status="offered",
                depends_on=["root"],
            )
        graph = load_task_graph(tmp_path)
        scores = compute_tree_effect_scores(graph)
        drifts = compute_drift(graph, scores, threshold=DEFAULT_DRIFT_THRESHOLD)
        assert any(d.task_id == "root" for d in drifts)
        root_drift = next(d for d in drifts if d.task_id == "root")
        assert root_drift.declared == 2.0
        assert root_drift.computed > 4.0
        assert root_drift.delta > 0

    def test_drift_skipped_when_no_declared_value(self, tmp_path: Path) -> None:
        # No declared tree effect → no drift comparison possible
        _write_task(tmp_path, subdir="active", task_id="root", status="offered")
        _write_task(tmp_path, subdir="active", task_id="a", status="offered", depends_on=["root"])
        graph = load_task_graph(tmp_path)
        scores = compute_tree_effect_scores(graph)
        drifts = compute_drift(graph, scores)
        assert not any(d.task_id == "root" for d in drifts)


# ── End-to-end build_score_report ───────────────────────────────────


class TestBuildScoreReport:
    def test_report_round_trip(self, tmp_path: Path) -> None:
        _write_task(
            tmp_path,
            subdir="active",
            task_id="root",
            status="offered",
            declared_tree_effect=8.0,
        )
        _write_task(tmp_path, subdir="active", task_id="a", status="offered", depends_on=["root"])
        _write_task(tmp_path, subdir="closed", task_id="old", status="done")
        report = build_score_report(vault_root=tmp_path, scored_at="2026-05-02T03:00Z")
        assert isinstance(report, ScoreReport)
        assert report.task_count == 3
        assert report.scored_count == 2  # only 'offered' counted
        assert report.scored_at == "2026-05-02T03:00Z"
        # Report serializes cleanly via Pydantic
        dumped = report.model_dump_json()
        assert "root" in dumped
        assert "scores" in dumped
