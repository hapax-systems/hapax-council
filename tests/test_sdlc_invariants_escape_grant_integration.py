"""Cross-boundary integration: the SDLC auto-mint must produce a grant the REAL
``escape-grant.sh`` shim accepts.

reform-inv-trace-checker-activate (CASE-SDLC-REFORM-001). The in-process chaos
test (``test_sdlc_invariants_chaos.py``) mints and verifies with a *shared
tmp_path key* — which MASKS the production disconnect this task fixes: the
auto-mint historically wrote ``<slug>-<id>.json`` into ``~/.cache/hapax/escape-grants``
signed with ``~/.config/hapax/coord-capability.key`` — none of which the live shim
reads (it globs ``<coord>/grants/*.grant`` verified with ``<coord>/grant-key``).

This test drives BOTH the Python minter and the bash shim through the SAME
canonical coord resolvers (``shared.coord_event_log`` redirected to a tmp tree via
``HAPAX_COORD_DIR``) and asserts the shim's real glob + signature-verify path
ACCEPTS the auto-minted grant. It FAILS if the directory, file extension, or
signing key diverge across the Python→bash boundary — exactly the regression this
task closes. It never touches the operator's real ``~/.cache``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from shared.coord_event_log import default_grant_dir, default_grant_key
from shared.governance.coord_capabilities import load_or_create_key
from shared.sdlc_invariants import (
    InvariantResult,
    Ladder,
    mint_escape_for_violation,
    run_evaluator,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIM = REPO_ROOT / "hooks" / "scripts" / "escape-grant.sh"

#: A ladder whose BLOCKED state has no escape edge → a genuine INV-3 violation
#: that ``run_evaluator`` auto-mints for (mirrors the chaos test's no-escape
#: ladder, but here the minted grant must survive the REAL shim, not an
#: in-process key).
_NO_ESCAPE_LADDER = Ladder(
    stages=("S0", "S11", "BLOCKED"),
    transitions={"S0": frozenset({"S11"}), "S11": frozenset(), "BLOCKED": frozenset()},
    terminal=frozenset({"S11"}),
    blocked=frozenset({"BLOCKED"}),
)


def _shim_allows(gate: str, env: dict[str, str]) -> tuple[bool, str]:
    """Invoke the REAL ``escape-grant.sh`` exactly as an irreversible-harm shim
    does: set ``SCRIPT_DIR``, ``source`` the shim, then call ``escape_grant_allows``
    from inside an ``if`` (the shim's documented ``set -e``-safe contract)."""
    script = (
        "set -uo pipefail; "
        f"export SCRIPT_DIR={SHIM.parent!s}; "
        f"source {SHIM!s}; "
        f"if escape_grant_allows {gate}; then echo __ALLOW__; else echo __DENY__; fi"
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )
    return ("__ALLOW__" in proc.stdout), (proc.stdout + proc.stderr)


@pytest.fixture
def coord_env(tmp_path, monkeypatch):
    """Redirect the canonical coord tree (BOTH minter and shim) to a hermetic tmp
    dir, and clear any explicit per-surface overrides so resolution flows through
    ``HAPAX_COORD_DIR`` identically on each side."""
    coord = tmp_path / "coord"
    for var in (
        "HAPAX_COORD_GRANT_DIR",
        "HAPAX_COORD_GRANT_KEY",
        "HAPAX_ESCAPE_GRANT_DIR",  # the OLD divergent dir override
        "HAPAX_COORD_GRANT_KEY_FILE",  # the OLD divergent key override
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HAPAX_COORD_DIR", str(coord))
    # keep the shim's "grant honored" ledger out of the operator's real cache
    monkeypatch.setenv("HAPAX_METHODOLOGY_LEDGER", str(tmp_path / "methodology.jsonl"))
    env = dict(os.environ)
    return coord, env


@pytest.mark.skipif(not SHIM.exists(), reason="escape-grant.sh shim absent")
@pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("python3") is None,
    reason="bash + python3 required for the real shim round-trip",
)
class TestAutoMintShimRoundTrip:
    def test_run_evaluator_inv3_mint_is_accepted_by_real_shim(self, coord_env):
        coord, env = coord_env

        # Control: with no grant minted yet, the REAL shim MUST deny — proves this
        # test is capable of failing (not trivially green).
        allowed_before, out = _shim_allows("floor:merge", env)
        assert not allowed_before, f"shim allowed with an empty grant dir:\n{out}"

        grant_dir = default_grant_dir()
        key = load_or_create_key(default_grant_key())

        report = run_evaluator(
            (),
            now=time.time(),
            ladder=_NO_ESCAPE_LADDER,
            findings_path=coord / "findings.jsonl",
            key=key,
            alert=False,
        )
        assert "INV-3" in report.violations
        inv3 = [g for g in report.minted if "INV-3" in g.reason]
        assert inv3, f"INV-3 did not auto-mint; minted reasons={[g.reason for g in report.minted]}"

        # Canonical contract: <coord>/grants/<grant_id>.grant (NOT <slug>-<id>.json).
        minted = grant_dir / f"{inv3[0].grant_id}.grant"
        found = sorted(p.name for p in grant_dir.glob("*")) if grant_dir.exists() else "NO DIR"
        assert minted.exists(), (
            f"auto-mint did not write {minted} — dir/extension divergence ({found})"
        )

        # THE cross-boundary assertion: the REAL shim's glob + HMAC verify accepts it.
        allowed, out = _shim_allows("floor:merge", env)
        assert allowed, f"real escape-grant.sh REJECTED the auto-minted grant:\n{out}"

    def test_mint_escape_for_violation_is_accepted_by_real_shim(self, coord_env):
        coord, env = coord_env
        key = load_or_create_key(default_grant_key())

        grant = mint_escape_for_violation(
            InvariantResult("INV-4", "authority", holds=False, violations=("boom",), advisory="x"),
            key=key,
            now=time.time(),
        )
        assert grant is not None
        minted = default_grant_dir() / f"{grant.grant_id}.grant"
        assert minted.exists(), f"auto-mint did not write {minted}"

        # universal "*" scope covers any gate the shim asks about
        allowed, out = _shim_allows("cc-task-gate", env)
        assert allowed, f"real escape-grant.sh REJECTED the auto-minted grant:\n{out}"
