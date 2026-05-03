"""Real-world conf decompose canary.

This test is the load-bearing P1 acceptance gate: it asserts that EVERY
``*.conf`` in ``tests/audio_graph/fixtures/real-confs/`` decomposes
cleanly into the ``AudioGraph`` schema. The fixture directory is a
snapshot of the operator's live ``~/.config/pipewire/pipewire.conf.d/``
at the time P1 lands; refreshing the fixture (when the operator's
confs change) is the trigger for schema iteration.

If this test fails on main, the schema is out of date with reality.
The CI gate (``audio-graph-validate.yml``) runs the same check via the
CLI script ``scripts/hapax-audio-graph-validate``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.audio_graph import AudioGraphValidator

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "real-confs"


@pytest.fixture
def real_confs_report():  # type: ignore[no-untyped-def]
    if not FIXTURES_DIR.is_dir():
        pytest.skip(f"fixture dir not present: {FIXTURES_DIR}")
    validator = AudioGraphValidator()
    return validator.decompose(FIXTURES_DIR)


class TestDecomposeRealConfs:
    def test_no_gaps(self, real_confs_report) -> None:  # type: ignore[no-untyped-def]
        gaps = real_confs_report.gaps
        if gaps:
            msg_lines = ["Real-conf decompose surfaced gaps:"]
            for gap in gaps:
                msg_lines.append(f"  [{gap.kind}] {gap.source_path}: {gap.message}")
                if gap.suggested_schema_change:
                    msg_lines.append(f"    suggestion: {gap.suggested_schema_change}")
            raise AssertionError("\n".join(msg_lines))

    def test_some_decomposed(self, real_confs_report) -> None:  # type: ignore[no-untyped-def]
        # The fixture must have at least 1 active conf — sanity check
        # that we're not silently passing an empty fixture.
        assert len(real_confs_report.decomposed_files) >= 1, (
            "fixture dir contained no active confs — refresh the snapshot"
        )

    def test_graph_has_nodes(self, real_confs_report) -> None:  # type: ignore[no-untyped-def]
        # The decomposed graph should have at least one node
        assert len(real_confs_report.graph.nodes) >= 1

    def test_graph_has_loopbacks(self, real_confs_report) -> None:  # type: ignore[no-untyped-def]
        # The operator's pipewire conf set is broadcast-heavy and
        # uses many loopbacks. At least one should land in the graph.
        assert len(real_confs_report.graph.loopbacks) >= 1

    def test_no_duplicate_pipewire_names_in_real_confs(
        self,
        real_confs_report,  # type: ignore[no-untyped-def]
    ) -> None:
        from shared.audio_graph.invariants import (
            check_no_duplicate_pipewire_names,
        )

        violations = check_no_duplicate_pipewire_names(real_confs_report.graph)
        if violations:
            raise AssertionError(
                "real confs produced duplicate pipewire_name violations: "
                + "; ".join(v.message for v in violations)
            )
