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
    """Yield the CLI module with REGISTRY_DIR pointing at a tempdir."""
    cli = _load_cli()
    registry = tmp_path / "registry"
    with (
        patch.object(cli, "REGISTRY_DIR", registry),
        patch.object(cli, "CURRENT_FILE", registry / "current.txt"),
        patch.object(cli, "LOCK_FILE", registry / ".registry.lock"),
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
