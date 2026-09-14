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
from collections.abc import Iterable, Mapping
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

    Mirrors agent-role.sh ``hapax_session_id`` exactly: first non-blank value
    in :data:`SESSION_ID_ENV_PRECEDENCE` order, stripped.
    """
    for var in SESSION_ID_ENV_PRECEDENCE:
        value = (env.get(var) or "").strip()
        if value:
            return value
    return None


def mint_session_id() -> str:
    """Mint a fresh per-spawn session id (uuid4 — never pid-derived)."""
    return str(uuid.uuid4())


#: uuid4 as it lands in a filename, and the alpha-infixed last resort the bash
#: mirror falls back to when no uuid source exists
#: (agent-role.sh ``hapax_mint_session_id``: ``sid<nanos>x<rand><rand>``).
_MINTED_ID_RE = re.compile(
    r"(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|sid[0-9]+x[0-9]+)\Z"
)


def is_minted_session_id(session_id: str | None) -> bool:
    """True when ``session_id`` has a shape :func:`mint_session_id` (or its bash
    mirror's last-resort branch) actually produces.

    Narrower than :func:`is_claim_keyable_session_id`, and for a different
    question. *Keyable* asks "may this id key an artifact" — deliberately
    permissive, since ids arrive from several spawners. *Minted* asks "did THIS
    system's minter produce this", which is what a sweep needs before retiring a
    marker it did not write.

    The distinction has teeth: ``cc-active-task-cx-blue-shadow-<uuid>`` split
    against the single role ``cx-blue`` yields the remainder
    ``shadow-<uuid>``, which IS keyable — so a keyable check would let cc-close
    delete a different role's lease. :func:`split_claim_marker_key` resolves that
    correctly only when given every role that exists, which a closing lane does
    not know.

    Lives here, beside the minter, on purpose: cc-close carried this as a
    hand-rolled bash regex, which is the second-divergent-copy shape this module's
    own contract exists to prevent. **Change the minter and change this together**
    — tests/test_session_identity.py holds them in step.
    """
    if not session_id:
        return False
    return bool(_MINTED_ID_RE.fullmatch(session_id.strip()))


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
    sid = session_id.strip()
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


def split_claim_marker_key(key: str, known_roles: Iterable[str]) -> tuple[str, str | None] | None:
    """Inverse of :func:`claim_paths`: split a marker key into ``(role, sid)``.

    A marker filename is ``cc-active-task-<role>[-<session_id>]`` and **both
    halves contain hyphens** — roles like ``cx-crit`` and ``vbe-1``, uuids
    throughout. So ``cc-active-task-cx-crit-15c99664-780f-…`` is not decomposable
    by splitting on ``-`` at any fixed position, and a reader that takes the
    whole suffix as a lane id (the pattern found in
    ``agents/studio_compositor/durf_source.py`` and ``scripts/codex-claim-audit``)
    reports ``cx-crit-15c99664-780f-…`` as the lane.

    The ambiguity is only resolvable against the set of roles that actually
    exist, so that set is a required argument rather than a guess. The longest
    matching role wins, and the remainder must be a **minted** session id.

    Minted, not merely claim-keyable: ``shadow-<uuid>`` is keyable, so a keyable
    test reads ``cx-blue-shadow-<uuid>`` as role ``cx-blue`` with session
    ``shadow-<uuid>`` whenever ``cx-blue-shadow`` is not in the known set — and the
    known set comes from *current* ``assigned_to`` values, which do not enumerate
    former assignees. A task reassigned away from ``cx-blue-shadow`` therefore made
    its leftover marker read as ``cx-blue``'s own, and a contested claim reported
    as healthy. Requiring a minted remainder makes that unrepresentable: the key
    resolves to ``None``, and the caller reports it as unattributable rather than
    inventing an owner.

    Returns ``None`` when no reading works.
    """
    candidates = sorted({r for r in known_roles if r}, key=len, reverse=True)
    for role in candidates:
        if key == role:
            return role, None
        remainder = key[len(role) + 1 :] if key.startswith(f"{role}-") else ""
        if remainder and is_minted_session_id(remainder):
            return role, remainder
    return None


def session_role_marker_path(session_id: str, *, cache_dir: Path) -> Path:
    """Path of the per-session identity marker (agent-role.sh convention)."""
    return cache_dir / f"{_MARKER_PREFIX}{session_id}"


#: The ONE var naming the model, published by whichever launcher actually chose it.
#:
#: It reached this shape by removing two earlier readers, each of which recorded a
#: value some other process had decided:
#:   * a flat precedence list (HAPAX_CAPABILITY_MODEL -> HAPAX_CLAUDE_MODEL ->
#:     HAPAX_CODEX_MODEL) recorded `model_family=<a claude model>` beside
#:     `harness=codex` for a codex lane dispatched from a claude lane, because
#:     dispatchers do `os.environ.copy()`.
#:   * a harness-keyed map ({"claude": "HAPAX_CLAUDE_MODEL"}) fixed the cross-harness
#:     case and left the same-harness one: HAPAX_CLAUDE_MODEL is an INPUT that
#:     hapax-claude-headless reads to pick `--model`, so a claude lane launched from
#:     inside another claude lane recorded a model it had inherited and never passed.
#:
#: Reading an input is the defect in both. A launcher knows what it executed with;
#: nothing else does. So hapax-claude-headless exports HAPAX_CAPABILITY_MODEL in the
#: same branch that appends `--model`, and this records that and nothing else. A
#: launcher that publishes nothing records nothing — never a guess, and never
#: another launch's value.
_MODEL_ENV = "HAPAX_CAPABILITY_MODEL"

#: Route id, written by hapax-methodology-dispatch at each governed launch and kept
#: only by the launcher its HAPAX_CAPABILITY_PINNED addresses
#: (hooks/scripts/agent-role.sh::hapax_consume_launch_capability_descriptors).
_ROUTE_ENV = "HAPAX_CAPABILITY_ROUTE"


def capability_shape_from_env(
    env: Mapping[str, str], *, scaffold_revision: str | None = None
) -> dict[str, str | None]:
    """The condition vector for whatever this session produces.

    Mirrors ``shared/route_metadata_schema.CapabilityShape`` as a plain dict so
    this module stays stdlib-only (it must import under the bare system python3 on
    every dispatch host). The schema side is the typed contract; this is the
    producer, and a field the environment cannot answer stays ``None`` — "not
    recorded", never a guess, and never another harness's value.

    Credential location is deliberately absent here as it is there: these values
    land in vault notes that sync.

    Every field is read from a var some process PUBLISHED about this launch — never
    from one it merely inherited. That property is not enforced here: it is enforced
    where the launch happens, by launchers clearing any descriptor not addressed to
    them. This function is the recorder, and it can only be as true as its inputs.
    """

    def _clean(name: str) -> str | None:
        return (env.get(name) or "").strip() or None

    return {
        "model_family": _clean(_MODEL_ENV),
        "harness": _clean("HAPAX_AGENT_INTERFACE"),
        "route": _clean(_ROUTE_ENV),
        "scaffold_revision": scaffold_revision,
    }


def format_capability_shape(shape: Mapping[str, str | None]) -> str:
    """One-line ``k=v`` rendering for a session-log entry; omits unrecorded fields.

    Returns ``""`` when nothing is known, so a caller can append it unconditionally
    without emitting an empty ``shape=()`` that would read as a recorded absence.
    """
    parts = [f"{k}={v}" for k, v in shape.items() if v]
    return ", ".join(parts)


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
