"""Deployed gate module identity, with isolated releases and synthetic claims."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from shared.governance.coord_capabilities import mint_escape_grant, write_grant_file

HOOKS = Path(__file__).resolve().parents[2] / "hooks" / "scripts"


def _deployed_gate(home: Path) -> Path:
    hooks = home / ".local/lib/hapax/hooks"
    hooks.mkdir(parents=True)
    for name in ("agent-role.sh", "escape-grant.sh", "cc-task-root.sh"):
        shutil.copy2(HOOKS / name, hooks / name)
    gate = hooks / "cc-task-gate.sh"
    shutil.copy2(HOOKS / "cc-task-gate.impl.sh", gate)
    return gate


def _module(root: Path, module: str, *, stale: bool = False) -> None:
    path = root / "shared" / f"{module}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.parent / "__init__.py").touch()
    if stale:
        path.write_text("raise RuntimeError('STALE_MODULE_EXECUTED')\n")
        return
    source = (
        "import os\nfrom pathlib import Path\n"
        "Path(os.environ['ROOT_IMPORT_TRACE']).write_text(__file__)\n"
    )
    if module == "mcp_connector_policy":
        source += "import sys\nsys.exit(10)\n"
    elif module == "task_note_lock":
        source += (
            "from contextlib import contextmanager\n"
            "class TaskNoteLockError(RuntimeError): pass\n"
            "@contextmanager\ndef projected_path_lock(*args, **kwargs): yield\n"
        )
    else:
        # Synthetic charter API: observe import identity, not charter policy.
        source += (
            "def _frontmatter(text):\n"
            "    return {'claim_form': 'charter', 'task_id': 'fixture',\n"
            "            'mutation_scope_refs': [], 'charter_scope': []}\n"
            "def _refs(value): return value or []\n"
            "def covers(ref, target): return False\n"
            "def obligation_breaches(*args): return []\n"
            "def write_obligation_report(*args, **kwargs): pass\n"
        )
    path.write_text(source)


def _run(
    home: Path,
    gate: Path,
    module: str,
    *,
    override: Path | None = None,
    cwd: Path | None = None,
):
    vault = home / "Documents/Personal"
    (vault / ".obsidian").mkdir(parents=True, exist_ok=True)
    tasks = vault / "20-projects/hapax-cc-tasks"
    (tasks / "active").mkdir(parents=True, exist_ok=True)
    target = home / "source/change.py"
    target.parent.mkdir(exist_ok=True)
    # Only this fixture home gets test claim markers; live claim state is untouched.
    cache = home / ".cache/hapax"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "cc-active-task-alpha").write_text("fixture\n")
    stage = '""' if module == "task_note_lock" else "S6_IMPLEMENTATION"
    (tasks / "active/fixture.md").write_text(
        "---\ntype: cc-task\ntask_id: fixture\nstatus: in_progress\n"
        "assigned_to: alpha\nclaim_form: charter\n"
        "authority_case: CASE-TEST-001\nparent_spec: fixture-spec.md\n"
        f"stage: {stage}\nimplementation_authorized: true\n"
        "source_mutation_authorized: true\ndocs_mutation_authorized: true\n"
        "route_metadata_schema: 1\nmutation_scope_refs:\n- /unrelated/\n"
        f"charter_scope:\n- {target.parent}/\n---\n"
    )
    env = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
        "XDG_CACHE_HOME": str(home / "xdg"),
        "HAPAX_AGENT_ROLE": "alpha",
        "HAPAX_CC_TASKS_ROOT": str(tasks),
        "ROOT_IMPORT_TRACE": str(home / "origin.txt"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if override:
        env["HAPAX_COORD_REPO_ROOT"] = str(override)
    payload = (
        {"tool_name": "mcp__context7__query-docs", "tool_input": {}}
        if module == "mcp_connector_policy"
        else {"tool_name": "Edit", "tool_input": {"file_path": str(target)}}
    )
    return subprocess.run(
        ["bash", str(gate)],
        input=json.dumps(payload),
        env=env,
        cwd=cwd or home,
        text=True,
        capture_output=True,
        timeout=20,
    )


MODULES = ["mcp_connector_policy", "charter_claim", "task_note_lock"]


@pytest.mark.parametrize("module", MODULES)
def test_deployed_gate_uses_activated_release_without_rebuild(tmp_path, module):
    gate = _deployed_gate(tmp_path)
    release = tmp_path / "xdg/hapax/source-activation/releases/current"
    alias = tmp_path / "xdg/hapax/source-activation/worktree"
    _module(release, module)
    alias.symlink_to(release, target_is_directory=True)
    assert not (tmp_path / "xdg/hapax/rebuild/worktree").exists()
    result = _run(tmp_path, gate, module)
    assert result.returncode == 0, result.stderr
    assert Path((tmp_path / "origin.txt").read_text()).resolve() == (
        release / "shared" / f"{module}.py"
    )
    if module == "task_note_lock":
        note = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active/fixture.md"
        assert "stage: S6_IMPLEMENTATION" in note.read_text()


@pytest.mark.parametrize("module", MODULES)
def test_activated_release_wins_over_stale_candidates(tmp_path, module):
    gate = _deployed_gate(tmp_path)
    release = tmp_path / "xdg/hapax/source-activation/worktree"
    _module(release, module)
    override = tmp_path / "override"
    for stale in (
        override,
        gate.parent.parent.parent,
        tmp_path / "xdg/hapax/rebuild/worktree",
        tmp_path / "projects/hapax-council",
    ):
        _module(stale, module, stale=True)
    result = _run(tmp_path, gate, module, override=override)
    assert result.returncode == 0, result.stderr
    assert Path((tmp_path / "origin.txt").read_text()) == release / "shared" / f"{module}.py"
    assert "STALE_MODULE_EXECUTED" not in result.stderr


@pytest.mark.parametrize("module", MODULES)
def test_missing_module_is_named_and_ledgered_inv5(tmp_path, module):
    gate = _deployed_gate(tmp_path)
    result = _run(tmp_path, gate, module)
    assert result.returncode == 0, result.stderr  # advisory INV-5 substrate failure
    assert "module_root_unavailable" in result.stderr
    assert f"shared/{module}.py" in result.stderr
    assert "INV-5" in result.stderr
    ledger = tmp_path / ".cache/hapax/methodology-emergency-ledger.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert any(
        row.get("kind") == "module_root_unavailable" and row.get("module") == f"shared/{module}.py"
        for row in rows
    )
    assert not (tmp_path / "origin.txt").exists()
    if module == "task_note_lock":
        note = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active/fixture.md"
        assert 'stage: ""' in note.read_text()  # no fictional successful stamp


def test_removable_checkout_is_not_a_module_source(tmp_path):
    gate = _deployed_gate(tmp_path)
    _module(tmp_path / "xdg/hapax/rebuild/worktree", "mcp_connector_policy", stale=True)
    _module(tmp_path / "projects/hapax-council", "mcp_connector_policy", stale=True)
    result = _run(tmp_path, gate, "mcp_connector_policy")
    assert result.returncode == 0, result.stderr
    assert "module_root_unavailable" in result.stderr
    assert "STALE_MODULE_EXECUTED" not in result.stderr


@pytest.mark.parametrize("module", MODULES)
def test_incomplete_activation_does_not_fall_back_to_stale_module(tmp_path, module):
    gate = _deployed_gate(tmp_path)
    (tmp_path / "xdg/hapax/source-activation/worktree/shared").mkdir(parents=True)
    override = tmp_path / "override"
    _module(override, module, stale=True)
    result = _run(tmp_path, gate, module, override=override)
    assert result.returncode == 0, result.stderr
    assert "module_root_unavailable" in result.stderr
    assert f"shared/{module}.py" in result.stderr
    assert "STALE_MODULE_EXECUTED" not in result.stderr


@pytest.mark.parametrize("module", MODULES)
def test_stale_working_directory_cannot_shadow_activated_module(tmp_path, module):
    gate = _deployed_gate(tmp_path)
    release = tmp_path / "xdg/hapax/source-activation/worktree"
    _module(release, module)
    cwd = tmp_path / "stale-working-directory"
    _module(cwd, module, stale=True)
    result = _run(tmp_path, gate, module, cwd=cwd)
    assert result.returncode == 0, result.stderr
    assert Path((tmp_path / "origin.txt").read_text()) == release / "shared" / f"{module}.py"
    assert "STALE_MODULE_EXECUTED" not in result.stderr


def test_available_lock_module_error_is_not_missing_infrastructure(tmp_path):
    gate = _deployed_gate(tmp_path)
    release = tmp_path / "xdg/hapax/source-activation/worktree"
    _module(release, "task_note_lock")
    path = release / "shared/task_note_lock.py"
    path.write_text(path.read_text() + "\nraise SystemExit(4)\n")
    result = _run(tmp_path, gate, "task_note_lock")
    assert Path((tmp_path / "origin.txt").read_text()) == path
    assert result.returncode == 2, result.stderr
    assert "could not be stamped" in result.stderr
    assert "module_root_unavailable" not in result.stderr


@pytest.mark.parametrize("activation", ["incomplete", "dangling"])
def test_signed_escape_grant_denied_with_broken_activation_and_usable_override(
    tmp_path, activation
):
    """An authentic grant cannot authorize importing a stale fallback verifier."""
    gate = _deployed_gate(tmp_path)
    override = tmp_path / "stale-override"
    module = override / "shared/governance/coord_capabilities.py"
    module.parent.mkdir(parents=True)
    shutil.copy2(HOOKS.parents[1] / "shared/governance/coord_capabilities.py", module)
    (override / "shared/__init__.py").touch()
    (module.parent / "__init__.py").touch()
    key = b"isolated-signed-grant-activation-test-key"
    key_file = tmp_path / "grant-key"
    key_file.write_bytes(key)
    grants = tmp_path / "grants"
    grants.mkdir()
    grant = mint_escape_grant(
        grantor="operator",
        scope="cc-task-gate",
        reason="fixture",
        ttl_s=3600,
        key=key,
        now=time.time(),
    )
    write_grant_file(grant, grants / f"{grant.grant_id}.grant")
    ledger = tmp_path / "methodology.jsonl"
    env = {
        "HOME": str(tmp_path),
        "PATH": "/usr/bin:/bin",
        "XDG_CACHE_HOME": str(tmp_path / "xdg"),
        "HAPAX_COORD_REPO_ROOT": str(override),
        "HAPAX_COORD_GRANT_DIR": str(grants),
        "HAPAX_COORD_GRANT_KEY": str(key_file),
        "HAPAX_METHODOLOGY_LEDGER": str(ledger),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    script = (
        f"SCRIPT_DIR={shlex.quote(str(gate.parent))}\n"
        f". {shlex.quote(str(gate.parent / 'escape-grant.sh'))}\n"
        "if escape_grant_allows cc-task-gate; then echo ALLOW; else echo DENY; fi\n"
    )

    def invoke():
        return subprocess.run(
            ["bash", "-c", script],
            env=env,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=10,
        )

    control = invoke()
    assert control.returncode == 0, control.stderr
    assert control.stdout.strip() == "ALLOW", control.stderr
    assert any(
        json.loads(line).get("kind") == "escape_grant_honored"
        for line in ledger.read_text().splitlines()
    )
    ledger.unlink()
    alias = tmp_path / "xdg/hapax/source-activation/worktree"
    alias.parent.mkdir(parents=True)
    if activation == "incomplete":
        (alias / "shared").mkdir(parents=True)
    else:
        alias.symlink_to(tmp_path / "removed-release", target_is_directory=True)
    assert not (alias / "shared/governance/coord_capabilities.py").exists()
    denied = invoke()
    assert denied.returncode == 0, denied.stderr
    assert denied.stdout.strip() == "DENY", denied.stderr
    rows = ledger.read_text().splitlines() if ledger.exists() else []
    assert not any(json.loads(line).get("kind") == "escape_grant_honored" for line in rows)
