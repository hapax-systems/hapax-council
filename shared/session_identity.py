"""Session identity in the coordination plane — the Python SSOT.

Unifies the two prior prose designs that were each written and never wired
end-to-end (taxonomy-a3-session-identity-20260611, LLM-agent failure taxonomy
B2/A7/B1 root):

1. **Coordination reform Phase 1, cluster 6 (FM-2)** — claims key on
   ``<role>-<session_id>`` so two same-role sessions never collide on one
   shared claim file. Writers: scripts/cc-claim; readers:
   hooks/scripts/cc-task-gate.impl.sh, scripts/cc-close, the stale-claim
   sweeper.
2. **reform-identity-coherence, cluster 11** — every spawn mints a fresh
   per-session id and records a WM-independent ``session-role-<sid>`` marker,
   so identity survives compositor-less hosts and resolves without a restart.

The bash mirror of the resolution ladder is
``hooks/scripts/agent-role.sh::hapax_session_id``; tests/test_session_identity.py
carries a parity canary that fails the build the day either side drifts
(A7 SSOT-fork guard — the mechanism ships with its own canary).

Hard invariant (claim-by-pid unrepresentable): an id with no per-session
entropy — a bare pid, or the retired ``<role>-$$`` launcher fallback — must
never key a claim, a marker, or a witness. :func:`is_claim_keyable_session_id`
is the single predicate; every writer defers to it.

Stdlib-only by contract: this module must import under the bare system
python3 on every dispatch host (appendix has no PyYAML outside the uv venv).
"""

from __future__ import annotations

import re
import socket
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

# Resolution ladder, highest precedence first. Mirror of agent-role.sh
# hapax_session_id — change BOTH or the parity canary fails.
SESSION_ID_ENV_PRECEDENCE: tuple[str, ...] = (
    "HAPAX_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_SESSION",
    "CODEX_THREAD_ID",
    "CODEX_THREAD_NAME",
)

# Role vars consulted for receipt stamping, highest precedence first. This is
# the cheap env-only subset of agent-role.sh's full identity ladder — receipt
# stamps must never invoke compositor queries or path inference.
_ROLE_ENV_PRECEDENCE: tuple[str, ...] = (
    "HAPAX_AGENT_NAME",
    "HAPAX_AGENT_ROLE",
    "CLAUDE_ROLE",
    "CODEX_ROLE",
)

_CLAIM_PREFIX = "cc-active-task-"
_MARKER_PREFIX = "session-role-"

# Path-safe, single-token ids only: these land verbatim in filenames.
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_MAX_ID_LEN = 128
_MIN_ID_LEN = 8


def resolve_session_id(env: Mapping[str, str]) -> str | None:
    """Return the session id the given environment carries, or ``None``.

    Mirrors agent-role.sh ``hapax_session_id`` exactly: first non-empty raw
    value in :data:`SESSION_ID_ENV_PRECEDENCE` order. Path-key consumers must
    pass that value to :func:`is_claim_keyable_session_id`, which rejects
    whitespace and other unsafe bytes rather than silently normalizing them.
    """
    for var in SESSION_ID_ENV_PRECEDENCE:
        value = env.get(var) or ""
        if value:
            return value
    return None


def mint_session_id() -> str:
    """Mint a fresh per-spawn session id (uuid4 — never pid-derived)."""
    return str(uuid.uuid4())


def is_claim_keyable_session_id(session_id: str | None) -> bool:
    """True when ``session_id`` may key coordination-plane artifacts.

    Rejects ids whose shape cannot distinguish two sessions (the ambiguity
    this contract exists to make unrepresentable):

    - bare pids (``12345``) and the retired ``<role>-$$`` launcher fallback
      (``epsilon-12345``) — pids recycle and do not cross hosts;
    - low-entropy short ids (``cx-red``) — no better than the role itself;
    - path-unsafe or oversized tokens — these land verbatim in filenames.
    """
    if not session_id:
        return False
    # Claim paths use the caller's value verbatim. Validation must therefore
    # reject surrounding whitespace instead of accepting a normalized token
    # that the Bash writers never actually use.
    sid = session_id
    if len(sid) < _MIN_ID_LEN or len(sid) > _MAX_ID_LEN:
        return False
    if not _SAFE_ID_RE.fullmatch(sid):
        return False
    # Pid-shaped: pure digits, or a final hyphen-field of pure digits short
    # enough to be a pid (pid_max is 4194304 — 7 digits; a uuid4 tail is 12 hex
    # chars, so a genuine uuid whose tail happens to be all-decimal stays
    # keyable).
    if sid.isdigit():
        return False
    tail = sid.rsplit("-", 1)[-1]
    return not (tail.isdigit() and len(tail) <= 7)


def claim_paths(role: str, session_id: str | None, *, cache_dir: Path) -> tuple[Path, Path | None]:
    """Return ``(legacy, session_keyed)`` claim paths for ``role``.

    ``session_keyed`` is ``None`` when there is no claim-keyable session id —
    the caller must then fall back to legacy-only keying, never invent a key.
    """
    legacy = cache_dir / f"{_CLAIM_PREFIX}{role}"
    if not is_claim_keyable_session_id(session_id):
        return legacy, None
    return legacy, cache_dir / f"{_CLAIM_PREFIX}{role}-{session_id}"


def session_role_marker_path(session_id: str, *, cache_dir: Path) -> Path:
    """Path of the per-session identity marker (agent-role.sh convention)."""
    return cache_dir / f"{_MARKER_PREFIX}{session_id}"


def identity_stamp(env: Mapping[str, str], host: str | None = None) -> dict[str, str | None]:
    """The canonical identity block for relay receipts and witness artifacts.

    Every coordination-plane artifact a session writes should carry this
    stamp so forensics join on ``session_id``, never on pid.
    """
    role = None
    for var in _ROLE_ENV_PRECEDENCE:
        value = (env.get(var) or "").strip()
        if value:
            role = value
            break
    return {
        "session_id": resolve_session_id(env),
        "role": role,
        "host": host if host is not None else socket.gethostname(),
        "stamped_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
