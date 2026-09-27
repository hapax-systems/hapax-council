"""Tests for hooks/scripts/authorization-packet-validator.sh (FR-PACKET-VALIDATOR-TEMPLATE-GAP).

The validator must stop hard-blocking a release command merely because a no-go
field is *absent*. All five no-go fields default to ``false`` at the PRESENCE
check only (a ledger line is emitted), so:
  - absent docs_mutation_authorized / public_current no longer wall a push, and
  - absent implementation_authorized still blocks — but on the defaulted VALUE
    (not authorized), never "solely on absence".

Invokes the shell hook via subprocess against synthetic vault fixtures under
``tmp_path`` (HOME override). No shared conftest — each test builds its own note.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "authorization-packet-validator.sh"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.governance.coord_capabilities import (  # noqa: E402
    mint_escape_grant,
    write_grant_file,
)

# A well-formed authorization packet, minus whatever a test omits.
_BASE_FIELDS = {
    "type": "cc-task",
    "task_id": "pkt-001",
    "title": '"Packet fixture"',
    "status": "in_progress",
    "assigned_to": "beta",
    "authority_case": "CASE-TEST-001",
    "parent_spec": "~/projects/hapax-council/docs/specs/x.md",
    "stage": "S6_IMPLEMENTATION",
    "implementation_authorized": "true",
    "source_mutation_authorized": "true",
    "docs_mutation_authorized": "true",
    "runtime_mutation_authorized": "false",
    "release_authorized": "false",
    "public_current": "false",
}


def _make_note(tmp_path: Path, *, task_id: str = "pkt-001", omit: tuple[str, ...] = ()) -> Path:
    vault = tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    vault.mkdir(parents=True, exist_ok=True)
    fields = {k: v for k, v in _BASE_FIELDS.items() if k not in omit}
    fields["task_id"] = task_id
    front = "\n".join(f"{k}: {v}" for k, v in fields.items())
    note = vault / f"{task_id}-fixture.md"
    note.write_text(f"---\n{front}\n---\n\n# Packet fixture\n\n## Session log\n")
    return note


def _write_claim(tmp_path: Path, role: str, task_id: str) -> None:
    cache = tmp_path / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"cc-active-task-{role}").write_text(task_id + "\n")


def _run(
    command: str,
    *,
    tmp_path: Path,
    role: str = "beta",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "t"}
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["CLAUDE_ROLE"] = role
    env.pop("HAPAX_AGENT_ROLE", None)
    env.pop("CODEX_ROLE", None)
    env.pop("HAPAX_METHODOLOGY_EMERGENCY", None)
    # The escape-grant substrate resolves its grant dir, key and ledger from these; a
    # live operator grant on the developer's machine must never reach the fixture.
    for key in (
        "HAPAX_COORD_DIR",
        "HAPAX_COORD_GRANT_DIR",
        "HAPAX_COORD_GRANT_KEY",
        "HAPAX_METHODOLOGY_LEDGER",
        "XDG_CACHE_HOME",
    ):
        env.pop(key, None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def _ledger_records(tmp_path: Path) -> list[dict]:
    ledger = tmp_path / ".cache" / "hapax" / "methodology-emergency-ledger.jsonl"
    if not ledger.exists():
        return []
    return [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]


def test_absent_docs_and_public_no_longer_block_push(tmp_path: Path) -> None:
    _make_note(tmp_path, omit=("docs_mutation_authorized", "public_current"))
    _write_claim(tmp_path, "beta", "pkt-001")
    result = _run("git push -u origin HEAD", tmp_path=tmp_path)
    assert result.returncode == 0, f"absent docs/public must not block push: {result.stderr}"


def test_default_emits_ledger_line(tmp_path: Path) -> None:
    _make_note(tmp_path, omit=("docs_mutation_authorized", "public_current"))
    _write_claim(tmp_path, "beta", "pkt-001")
    result = _run("git push -u origin HEAD", tmp_path=tmp_path)
    assert result.returncode == 0, result.stderr
    records = _ledger_records(tmp_path)
    defaulted = [r for r in records if r.get("kind") == "nogo_field_defaulted"]
    assert defaulted, f"expected a nogo_field_defaulted ledger line; got {records}"
    joined = json.dumps(defaulted)
    assert "docs_mutation_authorized" in joined
    assert "public_current" in joined


def test_absent_impl_blocks_on_value_not_presence(tmp_path: Path) -> None:
    # implementation_authorized absent -> defaults false -> blocks, but as a
    # value decision ("not authorized"), never the old "missing required" wall.
    _make_note(
        tmp_path,
        omit=("implementation_authorized", "docs_mutation_authorized", "public_current"),
    )
    _write_claim(tmp_path, "beta", "pkt-001")
    result = _run("git push -u origin HEAD", tmp_path=tmp_path)
    assert result.returncode == 2, f"absent impl must still fail closed: {result.stdout}"
    assert "implementation_authorized" in result.stderr
    assert "missing required no-go fields" not in result.stderr


def test_fully_present_valid_packet_passes_without_ledger(tmp_path: Path) -> None:
    _make_note(tmp_path)  # all fields present
    _write_claim(tmp_path, "beta", "pkt-001")
    result = _run("git push -u origin HEAD", tmp_path=tmp_path)
    assert result.returncode == 0, result.stderr
    assert not [r for r in _ledger_records(tmp_path) if r.get("kind") == "nogo_field_defaulted"]


def test_merge_still_requires_release_authorized(tmp_path: Path) -> None:
    # The default-false touches only the PRESENCE check; the merge VALUE gate is
    # untouched, so a merge with release_authorized:false is still refused.
    _make_note(tmp_path)
    _write_claim(tmp_path, "beta", "pkt-001")
    result = _run("gh pr merge 123 --squash", tmp_path=tmp_path)
    assert result.returncode == 2, f"merge without release auth must block: {result.stdout}"
    assert "release" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Escape grants (reform Phase 4, NEW-2 / INV-4) — the validator honours the same
# signed, scoped, time-boxed grant file the write gate honours. Measured
# 2026-09-03: the refusal text told the operator to "mint a coord-grant, then
# re-run"; the operator did; the gate never read it, because escape-grant.sh was
# sourced by cc-task-gate only. These tests pin that a grant covering THIS gate
# (or "*") lifts a refusal, that any other grant leaves it closed, and that a
# non-release command never touches the grant at all.
# ---------------------------------------------------------------------------

_GRANT_KEY = b"test-operator-grant-key-0123456789abcdef"
_THIS_GATE = "authorization-packet-validator"


def _grant_env(tmp_path: Path) -> dict[str, str]:
    """Create a grant dir + operator key under tmp_path; return env pointing the gate at them."""
    coord = tmp_path / "coord"
    grant_dir = coord / "grants"
    grant_dir.mkdir(parents=True, exist_ok=True)
    key_file = coord / "grant-key"
    key_file.write_bytes(_GRANT_KEY)
    return {
        "HAPAX_COORD_GRANT_DIR": str(grant_dir),
        "HAPAX_COORD_GRANT_KEY": str(key_file),
    }


def _drop_grant(
    tmp_path: Path, *, scope: str, ttl_s: float = 3600.0, now: float | None = None
) -> Path:
    """Mint + write a signed grant file into the tmp grant dir (no daemon involved)."""
    grant_dir = tmp_path / "coord" / "grants"
    grant_dir.mkdir(parents=True, exist_ok=True)
    grant = mint_escape_grant(
        grantor="operator",
        scope=scope,
        reason="test incident",
        ttl_s=ttl_s,
        key=_GRANT_KEY,
        now=now if now is not None else time.time(),
    )
    path = grant_dir / f"{grant.grant_id}.grant"
    write_grant_file(grant, path)
    return path


def _honored(tmp_path: Path) -> list[dict]:
    # `_ledger_records` is the module-level reader defined above; a review that read only
    # this diff took it for undefined.
    return [r for r in _ledger_records(tmp_path) if r.get("kind") == "escape_grant_honored"]


WRITE_GATE = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.sh"


def _run_write_gate(
    command: str, *, tmp_path: Path, extra_env: dict[str, str]
) -> subprocess.CompletedProcess:
    """The gate that runs BEFORE this one in the production PreToolUse chain.

    The shim resolves the deployed canonical impl first and falls back to the co-located
    `cc-task-gate.impl.sh`; with HOME pointed at the fixture there is no canonical, so the
    committed impl runs and the chain is hermetic.
    """
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "t"}
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["CLAUDE_ROLE"] = "beta"
    for key in (
        "HAPAX_AGENT_ROLE",
        "CODEX_ROLE",
        "HAPAX_METHODOLOGY_EMERGENCY",
        "HAPAX_COORD_DIR",
        "HAPAX_COORD_GRANT_DIR",
        "HAPAX_COORD_GRANT_KEY",
        "HAPAX_METHODOLOGY_LEDGER",
        "HAPAX_CANONICAL_HOOKS",
        "XDG_CACHE_HOME",
    ):
        env.pop(key, None)
    env.update(extra_env)
    return subprocess.run(
        [str(WRITE_GATE)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


class TestEscapeGrant:
    """A signed grant file covering this gate converts a refusal into an allow, ledgered."""

    def test_grant_for_this_gate_lifts_the_no_claim_refusal(self, tmp_path: Path) -> None:
        # No claim file and no note: the gate would refuse with "no claimed task".
        env = _grant_env(tmp_path)
        _drop_grant(tmp_path, scope=_THIS_GATE)
        result = _run("git push -u origin HEAD", tmp_path=tmp_path, extra_env=env)
        assert result.returncode == 0, (
            f"a grant for this gate must lift the refusal: {result.stderr}"
        )
        assert "escape grant honored" in result.stderr
        honored = _honored(tmp_path)
        assert honored and honored[0]["gate"] == _THIS_GATE, honored

    def test_wildcard_grant_lifts_the_refusal(self, tmp_path: Path) -> None:
        env = _grant_env(tmp_path)
        _drop_grant(tmp_path, scope="*")
        result = _run("git push -u origin HEAD", tmp_path=tmp_path, extra_env=env)
        assert result.returncode == 0, result.stderr

    def test_a_validator_only_grant_cannot_unblock_a_real_push(self, tmp_path: Path) -> None:
        """Review finding (2026-09-04): scopes are exact and cc-task-gate runs FIRST in the
        production chain, so a grant minted for this gate alone never reaches it on a real
        push — the write gate refuses before this one is consulted. The runbook therefore
        says: mint scope `*` for a no-claim push. This pins both halves of the chain."""
        env = _grant_env(tmp_path)
        _drop_grant(tmp_path, scope=_THIS_GATE)
        first = _run_write_gate("git push -u origin HEAD", tmp_path=tmp_path, extra_env=env)
        assert first.returncode != 0, (
            "cc-task-gate must still refuse a no-claim push under a validator-only grant: "
            f"{first.stderr}"
        )
        assert "escape grant honored" not in first.stderr

    def test_a_wildcard_grant_passes_the_whole_chain(self, tmp_path: Path) -> None:
        env = _grant_env(tmp_path)
        _drop_grant(tmp_path, scope="*")
        first = _run_write_gate("git push -u origin HEAD", tmp_path=tmp_path, extra_env=env)
        assert first.returncode == 0, f"cc-task-gate must honour a `*` grant: {first.stderr}"
        second = _run("git push -u origin HEAD", tmp_path=tmp_path, extra_env=env)
        assert second.returncode == 0, f"the validator must honour it too: {second.stderr}"
        gates = sorted({r.get("gate") for r in _honored(tmp_path)})
        assert "authorization-packet-validator" in gates, gates

    def test_grant_for_the_write_gate_leaves_this_gate_closed(self, tmp_path: Path) -> None:
        # Scope is exact: a grant minted for cc-task-gate says nothing about releases.
        env = _grant_env(tmp_path)
        _drop_grant(tmp_path, scope="cc-task-gate")
        result = _run("git push -u origin HEAD", tmp_path=tmp_path, extra_env=env)
        assert result.returncode == 2, result.stderr
        assert "no claimed task" in result.stderr
        assert "escape grant honored" not in result.stderr
        assert not _honored(tmp_path)

    def test_expired_grant_leaves_this_gate_closed(self, tmp_path: Path) -> None:
        env = _grant_env(tmp_path)
        _drop_grant(tmp_path, scope=_THIS_GATE, ttl_s=60.0, now=time.time() - 3600.0)
        result = _run("git push -u origin HEAD", tmp_path=tmp_path, extra_env=env)
        assert result.returncode == 2, result.stderr
        assert not _honored(tmp_path)

    def test_grant_lifts_a_release_not_authorized_merge(self, tmp_path: Path) -> None:
        # The packet-value refusal is a refusal of this gate too; the refusal text stays
        # visible so the operator sees exactly what the grant lifted.
        _make_note(tmp_path)
        _write_claim(tmp_path, "beta", "pkt-001")
        env = _grant_env(tmp_path)
        _drop_grant(tmp_path, scope=_THIS_GATE)
        result = _run("gh pr merge 123 --squash", tmp_path=tmp_path, extra_env=env)
        assert result.returncode == 0, result.stderr
        assert "release_authorized" in result.stderr
        assert "escape grant honored" in result.stderr

    def test_non_release_command_never_consults_the_grant(self, tmp_path: Path) -> None:
        env = _grant_env(tmp_path)
        _drop_grant(tmp_path, scope=_THIS_GATE)
        result = _run("ls -la", tmp_path=tmp_path, extra_env=env)
        assert result.returncode == 0, result.stderr
        assert not _honored(tmp_path)

    def test_no_grant_dir_at_all_is_the_old_behaviour(self, tmp_path: Path) -> None:
        result = _run("git push -u origin HEAD", tmp_path=tmp_path)
        assert result.returncode == 2
        assert "no claimed task" in result.stderr
