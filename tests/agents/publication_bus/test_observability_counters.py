"""Counter coverage for graph_publisher + self_citation_graph_doi.

Pins that the two Prometheus counters added in this audit-followup
PR increment on every labeled path. Existing functional tests in
``test_graph_publisher.py`` and ``test_self_citation_graph_doi.py``
keep passing — these tests only assert observability.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agents.publication_bus.graph_publisher import (
    GraphPublisherError,
    graph_publisher_total,
    mint_or_version,
)
from agents.publication_bus.self_citation_graph_doi import (
    main,
    self_citation_graph_doi_total,
)


def _counter_value(counter, **labels) -> float:
    """Read the current value of a Counter for the given label set.

    Pure-helper so tests can pin deltas across invocations.
    """
    return counter.labels(**labels)._value.get()


# ── graph_publisher counter ──────────────────────────────────────────


class TestGraphPublisherCounter:
    def test_counter_exists_with_outcome_label(self) -> None:
        # The counter is module-level + has a known outcome label.
        graph_publisher_total.labels(outcome="mint-ok")  # must not raise
        graph_publisher_total.labels(outcome="version-ok")
        graph_publisher_total.labels(outcome="mint-error")
        graph_publisher_total.labels(outcome="version-error")

    def test_mint_error_increments_on_missing_requests(self, tmp_path: Path) -> None:
        before = _counter_value(graph_publisher_total, outcome="mint-error")
        with patch("agents.publication_bus.graph_publisher.requests", None):
            with pytest.raises(GraphPublisherError, match="requests library"):
                mint_or_version(
                    zenodo_token="t",
                    graph_dir=tmp_path,
                    snapshot_path=tmp_path / "snap.json",
                    fingerprint="f",
                    metadata={},
                )
        after = _counter_value(graph_publisher_total, outcome="mint-error")
        assert after == before + 1

    def test_version_error_increments_on_corrupt_state(self, tmp_path: Path) -> None:
        # Plant existing concept-doi + corrupt last-deposit-id so
        # mint_or_version takes the version branch and fails on parse.
        (tmp_path / "concept-doi.txt").write_text("10.5281/zenodo.1\n")
        (tmp_path / "last-deposit-id.txt").write_text("not-an-int\n")
        before = _counter_value(graph_publisher_total, outcome="version-error")
        with pytest.raises(GraphPublisherError, match="corrupt last-deposit-id"):
            mint_or_version(
                zenodo_token="t",
                graph_dir=tmp_path,
                snapshot_path=tmp_path / "snap.json",
                fingerprint="f",
                metadata={},
            )
        after = _counter_value(graph_publisher_total, outcome="version-error")
        assert after == before + 1


# ── self_citation_graph_doi counter ──────────────────────────────────


class TestSelfCitationCounter:
    def test_counter_exists_with_all_labels(self) -> None:
        # Smoke each label so subsequent tests can rely on label
        # registration without lazy-create artifacts.
        for outcome in (
            "no-snapshot",
            "no-fingerprint",
            "no-change",
            "material-change-detected",
            "commit-skipped-no-token",
            "commit-attempted",
            "commit-failed",
            "dry-run-ok",
        ):
            self_citation_graph_doi_total.labels(outcome=outcome)

    def test_no_snapshot_outcome_increments_when_mirror_dir_empty(self, tmp_path: Path) -> None:
        before = _counter_value(self_citation_graph_doi_total, outcome="no-snapshot")
        rc = main(
            [
                "--mirror-dir",
                str(tmp_path / "missing"),
                "--graph-dir",
                str(tmp_path / "graph"),
            ]
        )
        assert rc == 0
        after = _counter_value(self_citation_graph_doi_total, outcome="no-snapshot")
        assert after == before + 1

    def test_dry_run_ok_outcome_increments_with_valid_snapshot(self, tmp_path: Path) -> None:
        # Plant a minimal snapshot the fingerprint function accepts.
        mirror = tmp_path / "mirror"
        mirror.mkdir()
        snapshot = mirror / "2026-05-01.json"
        snapshot.write_text(
            '{"data": {"works": {"nodes": [{"doi": "10.5281/zenodo.111", "citationCount": 1}]}}}',
            encoding="utf-8",
        )
        before = _counter_value(self_citation_graph_doi_total, outcome="dry-run-ok")
        rc = main(
            [
                "--mirror-dir",
                str(mirror),
                "--graph-dir",
                str(tmp_path / "graph"),
            ]
        )
        assert rc == 0
        after = _counter_value(self_citation_graph_doi_total, outcome="dry-run-ok")
        assert after == before + 1

    def test_commit_skipped_no_token_outcome_increments(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Plant a snapshot that triggers material change (graph_dir
        # has no last-fingerprint.txt → first-run change).
        mirror = tmp_path / "mirror"
        mirror.mkdir()
        (mirror / "2026-05-01.json").write_text(
            '{"data": {"works": {"nodes": [{"doi": "10.5281/zenodo.222", "citationCount": 5}]}}}',
            encoding="utf-8",
        )
        # Ensure no token in env so the no-token branch fires.
        monkeypatch.delenv("HAPAX_ZENODO_TOKEN", raising=False)
        before = _counter_value(self_citation_graph_doi_total, outcome="commit-skipped-no-token")
        rc = main(
            [
                "--mirror-dir",
                str(mirror),
                "--graph-dir",
                str(tmp_path / "graph"),
                "--commit",
            ]
        )
        assert rc == 0
        after = _counter_value(self_citation_graph_doi_total, outcome="commit-skipped-no-token")
        assert after == before + 1
