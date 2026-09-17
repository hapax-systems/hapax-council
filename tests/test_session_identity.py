"""Tests for shared/session_identity.py — taxonomy-a3-session-identity-20260611.

The coordination-plane session-identity SSOT: unifies the two prior prose
designs (coordination reform Phase 1 cluster 6 / FM-2 session-keyed claims,
and reform-identity-coherence cluster 11 / per-session identity markers) into
one importable contract. The bash mirror is hooks/scripts/agent-role.sh
(hapax_session_id / hapax_agent_claim_key); the parity canary below keeps the
two resolvers from forking (A7 SSOT-FORK guard, anti-thesis ii: the mechanism
carries its own canary).

Self-contained per project convention — no shared conftest fixtures.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from shared.session_identity import (
    SESSION_ID_ENV_PRECEDENCE,
    claim_paths,
    identity_stamp,
    is_claim_keyable_session_id,
    mint_session_id,
    resolve_session_id,
    session_role_marker_path,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROLE = REPO_ROOT / "hooks" / "scripts" / "agent-role.sh"

_UUID = "12345678-1234-4321-8765-123456789abc"

# Every env var either resolver consults, scrubbed before each matrix case so
# the test host's own session identity never leaks in.
_IDENTITY_ENV = (
    "HAPAX_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_SESSION",
    "CODEX_THREAD_ID",
    "CODEX_THREAD_NAME",
)

# (env, expected) — precedence ladder, one rung dropped per case.
_PRECEDENCE_MATRIX: list[tuple[dict[str, str], str | None]] = [
    ({"HAPAX_SESSION_ID": "sid-h", "CLAUDE_CODE_SESSION_ID": "sid-c"}, "sid-h"),
    ({"CLAUDE_CODE_SESSION_ID": "sid-c", "CODEX_SESSION": "sid-s"}, "sid-c"),
    ({"CODEX_SESSION": "sid-s", "CODEX_THREAD_ID": "sid-t"}, "sid-s"),
    ({"CODEX_THREAD_ID": "sid-t", "CODEX_THREAD_NAME": "sid-n"}, "sid-t"),
    ({"CODEX_THREAD_NAME": "sid-n"}, "sid-n"),
    ({}, None),
]


class TestResolvePrecedence:
    def test_precedence_matrix(self) -> None:
        for env, expected in _PRECEDENCE_MATRIX:
            assert resolve_session_id(env) == expected, f"env={env}"

    def test_blank_values_are_skipped(self) -> None:
        env = {"HAPAX_SESSION_ID": "  ", "CLAUDE_CODE_SESSION_ID": "sid-c"}
        assert resolve_session_id(env) == "sid-c"

    def test_resolved_value_is_stripped(self) -> None:
        assert resolve_session_id({"HAPAX_SESSION_ID": " sid-h \n"}) == "sid-h"

    def test_precedence_constant_matches_matrix_order(self) -> None:
        assert SESSION_ID_ENV_PRECEDENCE == _IDENTITY_ENV


class TestBashParityCanary:
    """resolve_session_id and agent-role.sh hapax_session_id are mirrors; this
    canary fails the build the day either side's precedence drifts."""

    def test_parity_across_precedence_matrix(self) -> None:
        for env, expected in _PRECEDENCE_MATRIX:
            bash_env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
            bash_env.update(env)
            r = subprocess.run(
                ["bash", "-c", f'. "{AGENT_ROLE}"; hapax_session_id'],
                env=bash_env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            bash_sid = r.stdout.strip() if r.returncode == 0 else None
            assert bash_sid == expected, f"bash drifted for env={env}"
            assert resolve_session_id(env) == bash_sid, f"python drifted for env={env}"


class TestMint:
    def test_mint_is_uuid_shaped(self) -> None:
        sid = mint_session_id()
        assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", sid)

    def test_mint_is_unique_per_call(self) -> None:
        assert mint_session_id() != mint_session_id()

    def test_mint_is_claim_keyable(self) -> None:
        assert is_claim_keyable_session_id(mint_session_id())


class TestMintedShapeRecognizer:
    """`is_minted_session_id` must stay in step with BOTH minters.

    cc-close needs "did this system mint this id" before retiring a marker it did
    not write, and it carried that as a hand-rolled bash regex — the second
    divergent copy this module's contract exists to prevent. The predicate now
    lives beside the minter; these pins are what keep them from drifting.
    """

    def test_python_mint_is_recognized(self) -> None:
        from shared.session_identity import is_minted_session_id

        assert is_minted_session_id(mint_session_id())

    def test_bash_mint_is_recognized(self) -> None:
        """The bash mirror's uuid branch."""
        import subprocess

        from shared.session_identity import is_minted_session_id

        out = subprocess.run(
            ["bash", "-c", f'. "{AGENT_ROLE}"; hapax_mint_session_id'],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        assert is_minted_session_id(out), f"bash mint not recognized: {out!r}"

    def test_bash_last_resort_shape_is_recognized(self) -> None:
        """`sid<nanos>x<rand><rand>` — the branch taken with no uuid source.

        Runs the REAL `hapax_mint_session_id` with every uuid source denied, rather
        than a copy of its printf. The copy version passed no matter what the
        production fallback did — review round 19 named it exactly: "breaking the
        production fallback therefore leaves this test passing", and the ordinary
        mint tests all take the uuid branch, so nothing covered this one.

        The three sources are denied the way the helper reaches them: `cat` (for the
        kernel uuid file), `uuidgen` and `python3` are shadowed on PATH by stubs
        that exit 1. `date` is left real, because the last-resort branch needs it.
        """
        import os
        import subprocess
        import tempfile
        from pathlib import Path as _Path

        from shared.session_identity import is_claim_keyable_session_id, is_minted_session_id

        repo_root = _Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            stubs = _Path(tmp)
            for denied in ("cat", "uuidgen", "python3"):
                stub = stubs / denied
                stub.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
                stub.chmod(0o755)
            out = subprocess.run(
                [
                    "bash",
                    "-c",
                    f'. "{repo_root}/hooks/scripts/agent-role.sh"\n'
                    "hapax_mint_session_id\nhapax_mint_session_id\n",
                ],
                text=True,
                capture_output=True,
                check=True,
                env={**os.environ, "PATH": f"{stubs}:{os.environ.get('PATH', '')}"},
            ).stdout.split()

        assert len(out) == 2, f"the real helper did not mint twice: {out}"
        assert out[0] != out[1], (
            f"the last-resort branch minted one id twice, so it cannot distinguish "
            f"two sessions: {out}"
        )
        for candidate in out:
            assert candidate.startswith("sid"), (
                f"a uuid source still answered, so the fallback was never reached: {candidate!r}"
            )
            assert is_minted_session_id(candidate), (
                f"last-resort mint not recognized: {candidate!r}"
            )
            assert is_claim_keyable_session_id(candidate), (
                f"the fallback minted an id cc-claim refuses to key on: {candidate!r}"
            )

    def test_is_narrower_than_claim_keyable(self) -> None:
        """The distinction is the point: a foreign role suffix is keyable, not minted.

        `cc-active-task-cx-blue-shadow-<uuid>` split against the single role
        `cx-blue` leaves `shadow-<uuid>`, which IS keyable — so a keyable check
        would let cc-close delete another role's lease.
        """
        from shared.session_identity import is_minted_session_id

        foreign = "shadow-9d4e1f77-2a3b-4c58-b0e6-1f2a3b4c5d6e"
        assert is_claim_keyable_session_id(foreign)
        assert not is_minted_session_id(foreign)

    def test_pid_shape_is_not_minted(self) -> None:
        from shared.session_identity import is_minted_session_id

        assert not is_minted_session_id("12345")
        assert not is_minted_session_id("epsilon-12345")
        assert not is_minted_session_id(None)


class TestClaimKeyablePredicate:
    """Claim-by-pid unrepresentable: ids without per-session entropy (bare pids,
    the retired `<role>-$$` launcher fallback) must never key a claim."""

    def test_accepts_uuids(self) -> None:
        assert is_claim_keyable_session_id(_UUID)

    def test_accepts_alpha_infixed_fallback_mints(self) -> None:
        # The launcher's last-resort mint shape: epoch-ns + random, alpha-infixed.
        assert is_claim_keyable_session_id("sid1749672000123456789x12345")

    def test_rejects_bare_pid(self) -> None:
        assert not is_claim_keyable_session_id("12345")

    def test_rejects_role_pid_fallback_shape(self) -> None:
        # The exact shape the pre-fix launcher minted: printf '%s-%s' "$ROLE" "$$".
        assert not is_claim_keyable_session_id("epsilon-12345")
        assert not is_claim_keyable_session_id("beta-99")

    def test_accepts_uuid_with_all_digit_tail(self) -> None:
        # ~0.4% of genuine uuid4 mints have a pure-digit final field; pids never
        # exceed 7 digits, so a 12-char digit tail must NOT read as pid-shaped.
        assert is_claim_keyable_session_id("12345678-1234-4321-8765-555555555555")

    def test_rejects_empty_and_whitespace(self) -> None:
        assert not is_claim_keyable_session_id("")
        assert not is_claim_keyable_session_id("   ")

    def test_rejects_path_unsafe_ids(self) -> None:
        assert not is_claim_keyable_session_id("a/../b")
        assert not is_claim_keyable_session_id("a b c d e f")
        assert not is_claim_keyable_session_id("../../../../etc/passwd")

    def test_rejects_low_entropy_short_ids(self) -> None:
        assert not is_claim_keyable_session_id("cx-red")
        assert not is_claim_keyable_session_id("abc")

    def test_rejects_oversized_ids(self) -> None:
        assert not is_claim_keyable_session_id("x" * 300)


class TestClaimPaths:
    def test_keyable_sid_yields_both_paths(self, tmp_path: Path) -> None:
        legacy, keyed = claim_paths("epsilon", _UUID, cache_dir=tmp_path)
        assert legacy == tmp_path / "cc-active-task-epsilon"
        assert keyed == tmp_path / f"cc-active-task-epsilon-{_UUID}"

    def test_pid_shaped_sid_yields_legacy_only(self, tmp_path: Path) -> None:
        legacy, keyed = claim_paths("epsilon", "epsilon-12345", cache_dir=tmp_path)
        assert legacy == tmp_path / "cc-active-task-epsilon"
        assert keyed is None

    def test_absent_sid_yields_legacy_only(self, tmp_path: Path) -> None:
        legacy, keyed = claim_paths("epsilon", None, cache_dir=tmp_path)
        assert legacy == tmp_path / "cc-active-task-epsilon"
        assert keyed is None

    def test_marker_path_matches_bash_convention(self, tmp_path: Path) -> None:
        # agent-role.sh hapax_session_role_marker: $cache/session-role-<sid>.
        assert session_role_marker_path(_UUID, cache_dir=tmp_path) == (
            tmp_path / f"session-role-{_UUID}"
        )


class TestIdentityStamp:
    """The relay/witness-receipt identity block: role + session_id + host + ts."""

    def test_stamp_carries_session_identity(self) -> None:
        env = {"HAPAX_SESSION_ID": _UUID, "HAPAX_AGENT_ROLE": "epsilon"}
        stamp = identity_stamp(env=env, host="hapax-appendix")
        assert stamp["session_id"] == _UUID
        assert stamp["role"] == "epsilon"
        assert stamp["host"] == "hapax-appendix"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp["stamped_at"])

    def test_stamp_tolerates_missing_identity(self) -> None:
        stamp = identity_stamp(env={}, host="h")
        assert stamp["session_id"] is None
        assert stamp["role"] is None
