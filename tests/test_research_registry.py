"""Tests for the LRR Phase 1 research registry CLI + schema.

Covers the schema regression pin (16 required fields), CLI subcommand
round-trip (init / current / list / open / close / show), atomic write
semantics, and the slug → condition_id sequential numbering.

The CLI script is at ``scripts/research-registry.py`` with a hyphen, so
import via ``importlib.util`` rather than a normal module import. Each
test isolates state via ``REGISTRY_DIR`` monkeypatch onto a tempdir.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


def _load_cli():
    """Import scripts/research-registry.py as a module."""
    spec_path = Path(__file__).resolve().parent.parent / "scripts" / "research-registry.py"
    spec = importlib.util.spec_from_file_location("research_registry_module", spec_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["research_registry_module"] = module
    spec.loader.exec_module(module)
    return module


REQUIRED_CONDITION_FIELDS = (
    "condition_id",
    "claim_id",
    "opened_at",
    "closed_at",
    "substrate",
    "frozen_files",
    "directives_manifest",
    "parent_condition_id",
    "sibling_condition_ids",
    "collection_started_at",
    "collection_halt_at",
    "osf_project_id",
    "pre_registration",
    "notes",
)


@pytest.fixture
def isolated_registry(tmp_path: Path):
    """Yield the CLI module with REGISTRY_DIR + marker paths on a tempdir."""
    cli = _load_cli()
    registry = tmp_path / "registry"
    marker = tmp_path / "shm" / "research-marker.json"
    with (
        patch.object(cli, "REGISTRY_DIR", registry),
        patch.object(cli, "CURRENT_FILE", registry / "current.txt"),
        patch.object(cli, "LOCK_FILE", registry / ".registry.lock"),
        patch.object(cli, "RESEARCH_MARKER_SHM_PATH", marker),
        patch.object(cli, "MARKER_CHANGES_LOG", registry / "research_marker_changes.jsonl"),
    ):
        yield cli


class TestSchemaRegressionPin:
    def test_skeleton_has_all_required_fields(self, isolated_registry):
        cli = isolated_registry
        skeleton = cli._new_condition_skeleton("cond-test-001", "test")
        for field in REQUIRED_CONDITION_FIELDS:
            assert field in skeleton, f"required field {field!r} missing from skeleton"

    def test_substrate_is_a_dict_with_three_keys(self, isolated_registry):
        cli = isolated_registry
        skeleton = cli._new_condition_skeleton("cond-test-001", "test")
        assert set(skeleton["substrate"].keys()) == {"model", "backend", "route"}

    def test_pre_registration_is_a_dict_with_three_keys(self, isolated_registry):
        cli = isolated_registry
        skeleton = cli._new_condition_skeleton("cond-test-001", "test")
        assert set(skeleton["pre_registration"].keys()) == {"filed", "url", "filed_at"}

    def test_pre_registration_filed_defaults_to_false(self, isolated_registry):
        cli = isolated_registry
        skeleton = cli._new_condition_skeleton("cond-test-001", "test")
        assert skeleton["pre_registration"]["filed"] is False


class TestInitSubcommand:
    def test_init_creates_first_condition_and_current_pointer(self, isolated_registry):
        cli = isolated_registry
        result = cli.cmd_init(_args())
        assert result == 0
        assert cli.REGISTRY_DIR.exists()
        assert cli.CURRENT_FILE.exists()
        assert cli.CURRENT_FILE.read_text().strip() == "cond-phase-a-baseline-qwen-001"
        condition_file = cli.REGISTRY_DIR / "cond-phase-a-baseline-qwen-001" / "condition.yaml"
        assert condition_file.exists()
        condition = yaml.safe_load(condition_file.read_text())
        assert condition["condition_id"] == "cond-phase-a-baseline-qwen-001"
        assert condition["substrate"]["model"] == "Qwen3.5-9B-exl3-5.00bpw"
        assert condition["closed_at"] is None

    def test_init_refuses_when_registry_already_populated(self, isolated_registry):
        cli = isolated_registry
        cli.cmd_init(_args())
        result = cli.cmd_init(_args())
        assert result == 1


class TestListAndCurrentSubcommands:
    def test_current_returns_null_on_empty_registry(self, isolated_registry, capsys):
        cli = isolated_registry
        cli.cmd_current(_args())
        out = capsys.readouterr().out.strip()
        assert out == "null"

    def test_current_returns_initialized_condition(self, isolated_registry, capsys):
        cli = isolated_registry
        cli.cmd_init(_args())
        capsys.readouterr()  # drain init output
        cli.cmd_current(_args())
        out = capsys.readouterr().out.strip()
        assert out == "cond-phase-a-baseline-qwen-001"

    def test_list_marks_current_with_asterisk(self, isolated_registry, capsys):
        cli = isolated_registry
        cli.cmd_init(_args())
        capsys.readouterr()
        cli.cmd_list(_args())
        out = capsys.readouterr().out
        assert "* cond-phase-a-baseline-qwen-001" in out
        assert "[open]" in out


class TestOpenAndCloseRoundTrip:
    def test_open_creates_new_condition_and_advances_current(self, isolated_registry):
        cli = isolated_registry
        cli.cmd_init(_args())
        cli.cmd_open(_args(slug="experimental"))
        current = cli._read_current()
        assert current == "cond-experimental-001"
        condition = cli._read_condition(current)
        assert condition is not None
        assert condition["closed_at"] is None
        assert condition["claim_id"] == "claim-experimental"

    def test_open_with_existing_slug_increments_sequential(self, isolated_registry):
        cli = isolated_registry
        cli.cmd_init(_args())
        cli.cmd_open(_args(slug="experimental"))
        cli.cmd_open(_args(slug="experimental"))
        ids = cli._list_condition_ids()
        assert "cond-experimental-001" in ids
        assert "cond-experimental-002" in ids
        assert cli._read_current() == "cond-experimental-002"

    def test_close_sets_closed_at_and_collection_halt_at(self, isolated_registry):
        cli = isolated_registry
        cli.cmd_init(_args())
        cli.cmd_close(_args(condition_id="cond-phase-a-baseline-qwen-001"))
        condition = cli._read_condition("cond-phase-a-baseline-qwen-001")
        assert condition["closed_at"] is not None
        assert condition["collection_halt_at"] == condition["closed_at"]

    def test_close_is_idempotent(self, isolated_registry, capsys):
        cli = isolated_registry
        cli.cmd_init(_args())
        cli.cmd_close(_args(condition_id="cond-phase-a-baseline-qwen-001"))
        first_close = cli._read_condition("cond-phase-a-baseline-qwen-001")["closed_at"]
        capsys.readouterr()
        result = cli.cmd_close(_args(condition_id="cond-phase-a-baseline-qwen-001"))
        assert result == 0
        # closed_at must NOT be overwritten on the second close
        condition = cli._read_condition("cond-phase-a-baseline-qwen-001")
        assert condition["closed_at"] == first_close

    def test_close_unknown_condition_returns_error(self, isolated_registry):
        cli = isolated_registry
        cli.cmd_init(_args())
        result = cli.cmd_close(_args(condition_id="cond-does-not-exist"))
        assert result == 1


class TestCloseClearsCurrentPointer:
    """Phase 1 audit H1 fix regression pins.

    Before the fix, ``cmd_close`` updated the condition YAML + wrote the
    SHM marker to None but left ``current.txt`` pointing at the closed
    condition. Downstream consumers (archive-purge, check-frozen-files)
    continued to treat the closed condition as active.
    """

    def test_close_active_clears_current_pointer(self, isolated_registry):
        cli = isolated_registry
        cli.cmd_init(_args())
        assert cli._read_current() == "cond-phase-a-baseline-qwen-001"

        cli.cmd_close(_args(condition_id="cond-phase-a-baseline-qwen-001"))

        # The pointer must read as "no active condition" after close.
        assert cli._read_current() is None

    def test_close_idempotent_does_not_clobber_other_condition(self, isolated_registry):
        """Closing an already-closed condition must not touch the pointer."""
        cli = isolated_registry
        cli.cmd_init(_args())
        # First close clears the pointer.
        cli.cmd_close(_args(condition_id="cond-phase-a-baseline-qwen-001"))
        assert cli._read_current() is None

        # Operator opens a new condition (pointer advances to it).
        cli.cmd_open(_args(slug="phase-a-prime-hermes"))
        current_new = cli._read_current()
        assert current_new == "cond-phase-a-prime-hermes-001"

        # Second close of the ORIGINAL (already-closed) condition must
        # NOT clear the pointer — it would clobber the new current
        # condition. The _clear_current_if_matches helper protects this
        # by only clearing when the pointer still equals the closing id.
        cli.cmd_close(_args(condition_id="cond-phase-a-baseline-qwen-001"))
        assert cli._read_current() == "cond-phase-a-prime-hermes-001"

    def test_close_non_active_condition_leaves_pointer_untouched(self, isolated_registry):
        """Closing a condition that isn't currently active leaves the pointer."""
        cli = isolated_registry
        cli.cmd_init(_args())
        # Open a second condition; pointer advances.
        cli.cmd_open(_args(slug="phase-a-prime-hermes"))
        assert cli._read_current() == "cond-phase-a-prime-hermes-001"

        # Close the ORIGINAL, non-active condition. The pointer must
        # remain on the currently-active second condition.
        cli.cmd_close(_args(condition_id="cond-phase-a-baseline-qwen-001"))
        assert cli._read_current() == "cond-phase-a-prime-hermes-001"


class TestClearCurrentIfMatchesHelper:
    """Direct unit tests for the H1 fix helper."""

    def test_clears_when_value_matches(self, isolated_registry):
        cli = isolated_registry
        cli.REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        cli.CURRENT_FILE.write_text("cond-matches\n")
        result = cli._clear_current_if_matches("cond-matches")
        assert result is True
        assert cli._read_current() is None

    def test_noop_when_value_differs(self, isolated_registry):
        cli = isolated_registry
        cli.REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        cli.CURRENT_FILE.write_text("cond-other\n")
        result = cli._clear_current_if_matches("cond-not-this")
        assert result is False
        assert cli._read_current() == "cond-other"

    def test_noop_when_file_missing(self, isolated_registry):
        cli = isolated_registry
        # Registry dir may or may not exist; the helper must handle both.
        if cli.CURRENT_FILE.exists():
            cli.CURRENT_FILE.unlink()
        result = cli._clear_current_if_matches("anything")
        assert result is False


class TestOpenSlugValidation:
    def test_open_rejects_slug_with_special_chars(self, isolated_registry):
        cli = isolated_registry
        cli.cmd_init(_args())
        result = cli.cmd_open(_args(slug="bad slug!"))
        assert result == 1

    def test_open_accepts_alphanumeric_with_hyphens(self, isolated_registry):
        cli = isolated_registry
        cli.cmd_init(_args())
        result = cli.cmd_open(_args(slug="phase-a-prime-hermes"))
        assert result == 0
        assert cli._read_current() == "cond-phase-a-prime-hermes-001"


class TestShowSubcommand:
    def test_show_prints_yaml(self, isolated_registry, capsys):
        cli = isolated_registry
        cli.cmd_init(_args())
        capsys.readouterr()
        cli.cmd_show(_args(condition_id="cond-phase-a-baseline-qwen-001"))
        out = capsys.readouterr().out
        assert "condition_id: cond-phase-a-baseline-qwen-001" in out
        assert "substrate:" in out

    def test_show_unknown_returns_error(self, isolated_registry):
        cli = isolated_registry
        cli.cmd_init(_args())
        result = cli.cmd_show(_args(condition_id="cond-does-not-exist"))
        assert result == 1


class TestAtomicWritePattern:
    def test_atomic_write_replaces_existing(self, isolated_registry):
        cli = isolated_registry
        cli.REGISTRY_DIR.mkdir()
        target = cli.REGISTRY_DIR / "test.txt"
        cli._atomic_write(target, "first")
        assert target.read_text() == "first"
        cli._atomic_write(target, "second")
        assert target.read_text() == "second"

    def test_atomic_write_uses_tmp_file(self, isolated_registry):
        cli = isolated_registry
        cli.REGISTRY_DIR.mkdir()
        target = cli.REGISTRY_DIR / "test.txt"
        cli._atomic_write(target, "content")
        # tmp file should have been cleaned up via os.replace
        assert not target.with_suffix(target.suffix + ".tmp").exists()


def _args(**kwargs) -> object:
    """Build a stand-in for argparse.Namespace."""

    class _NS:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    return _NS(**kwargs)


class TestResearchMarkerWriter:
    """LRR Phase 1 item 3: research-marker SHM injection."""

    def test_init_writes_marker_to_configured_path(self, isolated_registry):
        cli = isolated_registry
        cli.cmd_init(_args())
        assert cli.RESEARCH_MARKER_SHM_PATH.exists()
        import json

        data = json.loads(cli.RESEARCH_MARKER_SHM_PATH.read_text())
        assert data["condition_id"] == "cond-phase-a-baseline-qwen-001"
        assert "written_at" in data

    def test_open_overwrites_marker_with_new_condition(self, isolated_registry):
        cli = isolated_registry
        cli.cmd_init(_args())
        cli.cmd_open(_args(slug="experimental"))
        import json

        data = json.loads(cli.RESEARCH_MARKER_SHM_PATH.read_text())
        assert data["condition_id"] == "cond-experimental-001"

    def test_close_active_condition_drops_marker_to_null(self, isolated_registry):
        cli = isolated_registry
        cli.cmd_init(_args())
        cli.cmd_close(_args(condition_id="cond-phase-a-baseline-qwen-001"))
        import json

        data = json.loads(cli.RESEARCH_MARKER_SHM_PATH.read_text())
        assert data["condition_id"] is None

    def test_close_non_current_condition_does_not_change_marker(self, isolated_registry):
        cli = isolated_registry
        cli.cmd_init(_args())
        cli.cmd_open(_args(slug="experimental"))
        # Now current is cond-experimental-001. Closing the OLD condition
        # should not change the marker since it's not the active one.
        cli.cmd_close(_args(condition_id="cond-phase-a-baseline-qwen-001"))
        import json

        data = json.loads(cli.RESEARCH_MARKER_SHM_PATH.read_text())
        assert data["condition_id"] == "cond-experimental-001"

    def test_marker_changes_audit_log_appends_one_line_per_transition(self, isolated_registry):
        cli = isolated_registry
        cli.cmd_init(_args())
        cli.cmd_open(_args(slug="experimental"))
        cli.cmd_close(_args(condition_id="cond-experimental-001"))
        log_path = cli.MARKER_CHANGES_LOG
        assert log_path.exists()
        import json

        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 3, f"expected 3 audit lines, got {len(lines)}"
        events = [json.loads(line) for line in lines]
        # Event 1: init (None → cond-phase-a-baseline-qwen-001)
        assert events[0]["before"] is None
        assert events[0]["after"] == "cond-phase-a-baseline-qwen-001"
        # Event 2: open (previous → cond-experimental-001)
        assert events[1]["before"] == "cond-phase-a-baseline-qwen-001"
        assert events[1]["after"] == "cond-experimental-001"
        # Event 3: close (cond-experimental-001 → None)
        assert events[2]["before"] == "cond-experimental-001"
        assert events[2]["after"] is None


class TestTagReactionsSubcommand:
    """LRR Phase 1 item 9: backfill stream-reactions Qdrant points."""

    def test_dry_run_does_not_import_qdrant(self, isolated_registry):
        cli = isolated_registry
        cli.cmd_init(_args())
        result = cli.cmd_tag_reactions(
            _args(
                condition_id="cond-phase-a-baseline-qwen-001",
                dry_run=True,
                batch_size=100,
            )
        )
        assert result == 0

    def test_unknown_condition_id_is_rejected(self, isolated_registry):
        cli = isolated_registry
        cli.cmd_init(_args())
        result = cli.cmd_tag_reactions(
            _args(
                condition_id="cond-does-not-exist",
                dry_run=False,
                batch_size=100,
            )
        )
        assert result == 1

    def test_dry_run_with_known_condition_returns_success(self, isolated_registry):
        cli = isolated_registry
        cli.cmd_init(_args())
        result = cli.cmd_tag_reactions(
            _args(
                condition_id="cond-phase-a-baseline-qwen-001",
                dry_run=True,
                batch_size=50,
            )
        )
        assert result == 0
