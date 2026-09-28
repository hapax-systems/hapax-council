"""Unit-file pins for the research desk.

`systemd-analyze verify` checks syntax. It does not check that a sandbox permits the
writes, that a dependency propagates the stop it claims to, or that a Documentation=
path exists on the host that actually runs the service. Every assertion here is a
review finding from 2026-09-16 that verification could not have caught.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

UNITS = Path(__file__).resolve().parents[2] / "systemd" / "units"
MCP = UNITS / "hapax-research-desk-mcp.service"


def directives(path: Path, key: str) -> list[str]:
    """Every value of one directive, comments stripped.

    Comments are stripped because this file's own prose names these directives, and a
    grep that matches its own commentary proves nothing.
    """
    values: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        if name.strip() == key:
            values.append(value.strip())
    return values


def test_mcp_unit_exists() -> None:
    unit = MCP
    assert unit.is_file(), f"{unit} is missing"


def test_the_cache_root_is_created_by_systemd_not_asserted_by_readwritepaths() -> None:
    """A ReadWritePaths= entry that does not exist fails mount-namespace setup.

    Namespace setup happens BEFORE ExecStartPre, so the desk's own mkdir can never
    rescue it: on a host that has never run the desk the unit would fail to start with
    a namespace error carrying no next action. CacheDirectory= makes systemd create
    the directory first instead.
    """
    cache = directives(MCP, "CacheDirectory")
    assert cache == ["hapax/research-desk"]
    assert directives(MCP, "CacheDirectoryMode") == ["0700"]

    rwp = " ".join(directives(MCP, "ReadWritePaths"))
    assert ".cache/hapax/research-desk" not in rwp, (
        "the cache root must come from CacheDirectory=, not ReadWritePaths="
    )


def test_uv_cache_and_ledger_are_separate_from_purgeable_cache() -> None:
    """Red-first pin for #4674's EROFS/ledger majors.

    `uv run` must write below the systemd-created cache root while ProtectHome remains
    read-only, and the receipt ledger must live in StateDirectory so a cache purge cannot
    erase call evidence.
    """

    assert directives(MCP, "Environment") and any(
        "UV_CACHE_DIR=%h/.cache/hapax/research-desk/uv" in value
        for value in directives(MCP, "Environment")
    ), "uv needs an explicit writable cache below CacheDirectory"
    assert directives(MCP, "StateDirectory") == ["hapax/research-desk"], (
        "the per-call ledger must be in StateDirectory, not purgeable CacheDirectory"
    )


def test_readwritepaths_still_covers_both_vault_write_surfaces() -> None:
    rwp = " ".join(directives(MCP, "ReadWritePaths"))
    assert "hapax-cc-tasks/active" in rwp
    assert "hapax/lanebus" in rwp
    assert directives(MCP, "ProtectSystem") == ["strict"]
    assert directives(MCP, "ProtectHome") == ["read-only"]


@pytest.mark.parametrize("unit", [MCP])
def test_documentation_points_at_a_path_that_exists_where_the_service_runs(unit: Path) -> None:
    """The only path an operator follows during an incident must not be the one that
    dangles on a host carrying only the activation worktree."""
    docs = directives(unit, "Documentation")
    assert docs, f"{unit.name} carries no Documentation="
    assert not any("/projects/hapax-council/" in doc for doc in docs), (
        "Documentation= must not point at the mutable ~/projects dev tree"
    )
    assert any(".cache/hapax/source-activation/worktree/docs/" in doc for doc in docs)
    assert any(doc.startswith("https://github.com/") for doc in docs)


@pytest.mark.parametrize("unit", [MCP])
def test_units_run_from_the_activation_worktree(unit: Path) -> None:
    execs = directives(unit, "ExecStart") + directives(unit, "ExecStartPre")
    assert execs
    for line in execs:
        assert "/projects/hapax-council" not in line, (
            f"{unit.name} executes from the mutable dev tree: {line}"
        )


def test_the_mcp_unit_validates_the_credential_before_it_binds() -> None:
    pre = directives(MCP, "ExecStartPre")
    assert any("--check" in line for line in pre), (
        "--check validates the FileStore credential and both directories; without it a "
        "desk that cannot authenticate would still bind"
    )
    assert any("--require-file scripts/hapax-research-desk-mcp" in line for line in pre), (
        "the unit must refuse a release tree that predates the desk"
    )


def test_the_mcp_unit_binds_loopback_only() -> None:
    exec_start = directives(MCP, "ExecStart")
    assert len(exec_start) == 1
    assert "--host 127.0.0.1" in exec_start[0]
    assert re.search(r"--port\s+8790", exec_start[0])
