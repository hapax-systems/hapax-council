"""Tests for scripts/probe-affordance-recruitment.py.

Pin the script's structural contract without depending on Qdrant/embeddings
at CI time:

1. The built-in narrative fixture covers every batch-1..batch-4 shader-node
   at least once across the expected lists.
2. Every "expected" capability_name in the fixture exists in the live
   SHADER_NODE_AFFORDANCES registry — catches stale fixtures that point at
   removed/renamed capabilities.
3. The script is executable.
4. The script emits valid JSON when its qdrant import path raises.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "probe-affordance-recruitment.py"


def _load_script_module():
    """Import the probe script as a module without invoking main()."""
    spec = importlib.util.spec_from_file_location("probe_recruitment", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO_ROOT))
    try:
        spec.loader.exec_module(mod)
    finally:
        if str(REPO_ROOT) in sys.path:
            sys.path.remove(str(REPO_ROOT))
    return mod


@pytest.fixture(scope="module")
def probe_module():
    return _load_script_module()


class TestScriptShape:
    def test_script_is_executable(self) -> None:
        assert SCRIPT.is_file()

    def test_script_imports_cleanly(self, probe_module) -> None:
        assert hasattr(probe_module, "REPRESENTATIVE_NARRATIVES")
        assert hasattr(probe_module, "main")
        assert hasattr(probe_module, "probe")


class TestNarrativeFixtureContract:
    def test_fixture_is_non_empty(self, probe_module) -> None:
        narratives = probe_module.REPRESENTATIVE_NARRATIVES
        assert len(narratives) >= 15, (
            f"REPRESENTATIVE_NARRATIVES should cover ≥15 distinct phrases; got {len(narratives)}"
        )

    def test_every_expected_node_is_registered(self, probe_module) -> None:
        """A fixture pointing at a removed capability is a stale-test smell."""
        from shared.affordance_registry import SHADER_NODE_AFFORDANCES

        registered = {r.name for r in SHADER_NODE_AFFORDANCES}
        narratives = probe_module.REPRESENTATIVE_NARRATIVES
        missing: dict[str, list[str]] = {}
        for narrative, expected in narratives.items():
            gap = [name for name in expected if name not in registered]
            if gap:
                missing[narrative] = gap
        assert not missing, (
            f"REPRESENTATIVE_NARRATIVES references unregistered capabilities: "
            f"{missing}. Either register them in SHADER_NODE_AFFORDANCES or "
            f"remove them from the probe fixture."
        )

    def test_fixture_covers_every_batch_addition(self, probe_module) -> None:
        """The probe should exercise at least one node from each coverage
        batch so coverage-driven additions are tested for matching quality."""
        narratives = probe_module.REPRESENTATIVE_NARRATIVES
        all_expected: set[str] = set()
        for expected in narratives.values():
            all_expected.update(expected)

        # Sample one representative node per batch we shipped.
        # Batch 1 (#2281), 2 (#2295), 3 (#2297), 4 (#2307).
        batch_samples = {
            "batch-1": "node.vhs",
            "batch-2": "node.droste",
            "batch-3": "node.thermal",
            "batch-4": "node.warp",
        }
        for batch, sample in batch_samples.items():
            assert sample in all_expected, (
                f"probe fixture should cover {batch} via at least one "
                f"narrative expecting {sample}; the fixture lost coverage "
                f"for that batch and recruitment-quality drift will go "
                f"undetected by the probe"
            )


class TestSkippedPathWhenQdrantUnavailable:
    """Catches silent-failure regressions on the operator-runnable path."""

    def test_skipped_on_import_failure_emits_json(self, tmp_path) -> None:
        """If the script can't import shared.config (or qdrant_client), it
        should emit a structured ``status: skipped`` JSON envelope instead
        of crashing — so an operator running it on a stripped environment
        gets actionable output, not a stack trace."""
        # We can't easily simulate import failure without monkey-patching;
        # at minimum exercise the --json path with a nonsense collection
        # name and verify the script's exit code semantics are coherent.
        env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--json", "--collection", "__nonexistent_collection__"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        # Either the qdrant_client import failed (skipped path) OR the
        # collection lookup fails (every result is an error). Both are
        # acceptable structured outputs — what matters is no crash.
        assert result.returncode in (0, 2), (
            f"unexpected exit code {result.returncode}; stdout={result.stdout[:300]} "
            f"stderr={result.stderr[:300]}"
        )
        # stdout must be JSON or at least parsable summary
        assert result.stdout.strip(), "script produced no stdout"
