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
import yaml

UNITS = Path(__file__).resolve().parents[2] / "systemd" / "units"
MCP = UNITS / "hapax-research-desk-mcp.service"
TUNNEL = UNITS / "hapax-research-desk-tunnel.service"


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


@pytest.mark.parametrize("unit", [MCP, TUNNEL])
def test_units_exist(unit: Path) -> None:
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


def test_readwritepaths_still_covers_both_vault_write_surfaces() -> None:
    rwp = " ".join(directives(MCP, "ReadWritePaths"))
    assert "hapax-cc-tasks/active" in rwp
    assert "hapax/lanebus" in rwp
    assert directives(MCP, "ProtectSystem") == ["strict"]
    assert directives(MCP, "ProtectHome") == ["read-only"]


def test_the_tunnel_is_bound_to_the_origin_not_merely_required() -> None:
    """Requires= propagates a stop only when the origin is stopped EXPLICITLY.

    If the desk crashes and exhausts Restart=on-failure, a Requires= tunnel keeps
    running and the published hostname answers 502 — the exact state the unit's own
    comment says must not exist.
    """
    assert directives(TUNNEL, "BindsTo") == ["hapax-research-desk-mcp.service"]
    assert directives(TUNNEL, "Requires") == [], "BindsTo supersedes Requires here"
    assert "hapax-research-desk-mcp.service" in " ".join(directives(TUNNEL, "After"))


@pytest.mark.parametrize("unit", [MCP, TUNNEL])
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


@pytest.mark.parametrize("unit", [MCP, TUNNEL])
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


def test_the_tunnel_never_writes_its_credentials_outside_the_runtime_directory() -> None:
    assert directives(TUNNEL, "RuntimeDirectory") == ["cloudflared"]
    assert directives(TUNNEL, "RuntimeDirectoryMode") == ["0700"]
    pre = " ".join(directives(TUNNEL, "ExecStartPre"))
    assert "${RUNTIME_DIRECTORY}" in pre
    assert "cloudflared-research-desk-tunnel-credentials" in pre
    assert "umask 0077" in pre


def test_the_tunnel_stays_inert_until_its_ingress_config_exists() -> None:
    assert directives(TUNNEL, "ConditionPathExists") == ["%h/.cloudflared/research-desk.yml"]


def test_the_shipped_ingress_template_matches_what_the_unit_gates_on() -> None:
    """The gating file was prose only; it is a committed artifact now."""
    template = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "architecture"
        / "research-desk-tunnel.example.yml"
    )
    assert template.is_file()
    # Parsed, not grepped. A substring check would assert that a hostname appears
    # SOMEWHERE in the file, which is both weaker than checking the ingress rule and
    # what CodeQL's py/incomplete-url-substring-sanitization heuristic flags.
    spec = yaml.safe_load(template.read_text(encoding="utf-8"))
    assert spec["tunnel"] == "REPLACE-WITH-TUNNEL-UUID", "a template must carry no real tunnel id"
    assert spec["credentials-file"] == "/run/user/1000/cloudflared/research-desk.json", (
        "the credentials path must match what the unit's ExecStartPre materialises"
    )
    ingress = spec["ingress"]
    assert ingress[0] == {
        "hostname": "desk.hapaxrnd.com",
        "service": "http://127.0.0.1:8790",
    }, "the template must route the published hostname at the loopback bind"
    assert ingress[-1] == {"service": "http_status:404"}, "the catch-all must not be a proxy"
