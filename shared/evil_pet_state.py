"""Evil Pet granular-engine ownership flag — single-writer arbitration.

Implements §2, §3, §6, §8 of docs/research/2026-04-20-mode-d-voice-tier-
mutex.md. Mode D (vinyl anti-DMCA granular wash) and voice tiers 5/6
(voice granular wash / obliterated) both configure the same Evil Pet
granular engine over MIDI channel 0. Last-write-wins on CCs produces
state-space thrash; simultaneous engagement also sums two uncorrelated
sources into the engine's L-in and destroys both regimes. This module
provides the authoritative single-owner flag.

Scope:

- **Arbitrate** — which writer may claim the engine (pure function;
  priority classes operator/governance > programme > director).
- **Persist** — authoritative state at
  ``/dev/shm/hapax-compositor/evil-pet-state.json`` via atomic
  tmp+rename. Readers never observe a partial write.
- **Fail-safe** — 15 s heartbeat staleness falls back to ``bypass``; the
  next reader sees the engine as free regardless of crashed writers.
- **Legacy compat** — maintains
  ``/dev/shm/hapax-compositor/mode-d-active`` flag exists/absent
  semantics while downstream consumers migrate.

Does NOT emit MIDI CCs. Ownership is orthogonal to the transition
sequence — the owning capability (``VinylChainCapability``,
``VocalChainCapability``) handles its own CC emission AFTER acquiring
ownership here. See §4 of the research doc for the handoff protocol.

References:
    - ``agents/hapax_daimonion/vinyl_chain.py`` (Mode D consumer)
    - ``agents/hapax_daimonion/vocal_chain.py`` (voice-tier consumer)
    - ``scripts/hapax-vinyl-mode`` (operator CLI)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal

log = logging.getLogger(__name__)

# The operator-tmpfs compositor flag dir. All writes land here.
_STATE_DIR: Final[Path] = Path("/dev/shm/hapax-compositor")
DEFAULT_STATE_PATH: Final[Path] = _STATE_DIR / "evil-pet-state.json"
LEGACY_MODE_D_FLAG: Final[Path] = _STATE_DIR / "mode-d-active"

# Owning-writer heartbeat must land inside this window or readers treat
# the engine as free (§6). 15 s balances "crashed writer released fast"
# against "don't starve a slow writer on a busy GIL tick".
HEARTBEAT_STALE_S: Final[float] = 15.0

# §8 rapid-toggle protection. Same-class writers requesting a DIFFERENT
# mode within this window after the previous transition are rejected.
DEBOUNCE_WINDOW_S: Final[float] = 0.5


class EvilPetMode(StrEnum):
    """Which regime currently owns the granular engine.

    Voice tiers 0–6 map 1:1 to ``voice_tier_N``. ``mode_d`` is the
    vinyl anti-DMCA wash. ``bypass`` is "nothing owns the engine —
    dry signal, grains off, voice-safe base CCs".
    """

    BYPASS = "bypass"
    VOICE_TIER_0 = "voice_tier_0"
    VOICE_TIER_1 = "voice_tier_1"
    VOICE_TIER_2 = "voice_tier_2"
    VOICE_TIER_3 = "voice_tier_3"
    VOICE_TIER_4 = "voice_tier_4"
    VOICE_TIER_5 = "voice_tier_5"
    VOICE_TIER_6 = "voice_tier_6"
    MODE_D = "mode_d"


WriterTag = Literal["operator", "programme", "director", "governance", "system"]


# Priority classes — higher wins unconditionally. Operator + governance
# share priority 3: operator explicit action should never be blocked,
# and governance revert (e.g. Programme opt-in revoked mid-session)
# must be immediate. Ties within priority 3 follow last-explicit-wins
# with debounce.
_WRITER_PRIORITY: Final[dict[str, int]] = {
    "operator": 3,
    "governance": 3,
    "programme": 2,
    "director": 1,
    "system": 0,
}


@dataclass(frozen=True)
class EvilPetState:
    """Authoritative snapshot of engine ownership.

    Writers emit EXACTLY the intended ``mode`` (e.g. voice tier 5 claims
    ``voice_tier_5``, never ``mode_d`` even though their CC footprint
    overlaps). ``tier`` duplicates the numeric tier for ergonomic reads
    and is ``None`` outside voice-tier modes.
    """

    mode: EvilPetMode
    active_since: float
    writer: str
    programme_opt_in: bool = False
    heartbeat: float = 0.0
    tier: int | None = None

    @classmethod
    def bypass(cls, writer: str = "system", now: float | None = None) -> EvilPetState:
        """Synthetic bypass state — returned by read_state() on missing/stale."""
        ts = now if now is not None else time.time()
        return cls(
            mode=EvilPetMode.BYPASS,
            active_since=ts,
            writer=writer,
            heartbeat=ts,
            tier=None,
            programme_opt_in=False,
        )

    def is_stale(self, now: float, window_s: float = HEARTBEAT_STALE_S) -> bool:
        return (now - self.heartbeat) > window_s


@dataclass(frozen=True)
class ArbitrationResult:
    """Outcome of ``arbitrate()`` — decision plus the state that was/would be written."""

    accepted: bool
    state: EvilPetState
    reason: str


def _derive_tier(mode: EvilPetMode) -> int | None:
    if mode.value.startswith("voice_tier_"):
        return int(mode.value.split("_")[-1])
    return None


def _build_new_state(
    target_mode: EvilPetMode,
    writer: str,
    now: float,
    programme_opt_in: bool,
    active_since: float | None = None,
) -> EvilPetState:
    return EvilPetState(
        mode=target_mode,
        active_since=active_since if active_since is not None else now,
        writer=writer,
        programme_opt_in=programme_opt_in,
        heartbeat=now,
        tier=_derive_tier(target_mode),
    )


def arbitrate(
    target_mode: EvilPetMode,
    writer: str,
    current: EvilPetState,
    now: float | None = None,
    programme_opt_in: bool = False,
) -> ArbitrationResult:
    """Decide whether ``writer`` may transition the engine to ``target_mode``.

    Pure function — no I/O. Caller persists the returned state via
    ``write_state()`` only on ``accepted=True``. Rules (§3):

    1. Stale current state ⇒ always accept (engine effectively free).
    2. Higher-priority writer ⇒ preempts.
    3. Lower-priority writer ⇒ rejected, reason ``blocked_by_<current_writer>``.
    4. Same priority:
       - Same target mode ⇒ accept as heartbeat refresh (active_since preserved).
       - Different target mode inside DEBOUNCE_WINDOW_S ⇒ rejected.
       - Different target mode outside debounce ⇒ accept as same-class override.
    """
    ts = now if now is not None else time.time()

    if current.is_stale(ts):
        return ArbitrationResult(
            accepted=True,
            state=_build_new_state(target_mode, writer, ts, programme_opt_in),
            reason="stale_heartbeat_released",
        )

    writer_priority = _WRITER_PRIORITY.get(writer, 0)
    current_priority = _WRITER_PRIORITY.get(current.writer, 0)

    if writer_priority > current_priority:
        return ArbitrationResult(
            accepted=True,
            state=_build_new_state(target_mode, writer, ts, programme_opt_in),
            reason="higher_priority_preempts",
        )

    if writer_priority < current_priority:
        return ArbitrationResult(
            accepted=False,
            state=current,
            reason=f"blocked_by_{current.writer}",
        )

    # Same-class. Heartbeat refresh first (mode unchanged) — always ok.
    if target_mode == current.mode:
        return ArbitrationResult(
            accepted=True,
            state=_build_new_state(
                target_mode,
                writer,
                ts,
                programme_opt_in,
                active_since=current.active_since,
            ),
            reason="heartbeat_refresh",
        )

    if (ts - current.active_since) < DEBOUNCE_WINDOW_S:
        return ArbitrationResult(
            accepted=False,
            state=current,
            reason=f"debounce_{DEBOUNCE_WINDOW_S}s",
        )

    return ArbitrationResult(
        accepted=True,
        state=_build_new_state(target_mode, writer, ts, programme_opt_in),
        reason="same_class_override",
    )


def read_state(
    path: Path = DEFAULT_STATE_PATH,
    now: float | None = None,
) -> EvilPetState:
    """Return current engine ownership. Bypass on missing/stale/parse error.

    Fail-safe by design: a crashed writer cannot lock the engine longer
    than ``HEARTBEAT_STALE_S``. Readers treating the stale state as
    ``bypass`` means the next writer can claim via ``arbitrate()`` with
    reason ``stale_heartbeat_released``.
    """
    ts = now if now is not None else time.time()
    try:
        raw = path.read_text()
        data = json.loads(raw)
        state = EvilPetState(
            mode=EvilPetMode(data["mode"]),
            active_since=float(data["active_since"]),
            writer=str(data["writer"]),
            programme_opt_in=bool(data.get("programme_opt_in", False)),
            heartbeat=float(data.get("heartbeat", 0.0)),
            tier=data.get("tier"),
        )
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError, TypeError):
        return EvilPetState.bypass(now=ts)
    if state.is_stale(ts):
        return EvilPetState.bypass(now=ts)
    return state


def write_state(
    state: EvilPetState,
    path: Path = DEFAULT_STATE_PATH,
    legacy_flag: Path = LEGACY_MODE_D_FLAG,
) -> None:
    """Atomic tmp+rename write. Also maintains the legacy mode-d flag.

    Atomic semantics: write to ``<path>.tmp``, then ``os.replace`` into
    place. tmpfs makes this atomic at the inode level; readers see
    either the old file or the new file, never a half-written one.

    Legacy compat: when ``state.mode == MODE_D``, ``legacy_flag`` is
    ``touch``-ed; otherwise it is removed if present. Downstream code
    checking the legacy boolean flag path continues to work during the
    migration window.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(_serializable(state), sort_keys=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload)
    os.replace(tmp, path)

    if state.mode == EvilPetMode.MODE_D:
        legacy_flag.parent.mkdir(parents=True, exist_ok=True)
        legacy_flag.touch()
    else:
        try:
            legacy_flag.unlink()
        except FileNotFoundError:
            pass


def _serializable(state: EvilPetState) -> dict[str, object]:
    d = asdict(state)
    # asdict keeps EvilPetMode as a StrEnum member; JSON wants its .value.
    d["mode"] = state.mode.value
    return d


def acquire_engine(
    target_mode: EvilPetMode,
    writer: str,
    *,
    programme_opt_in: bool = False,
    path: Path = DEFAULT_STATE_PATH,
    legacy_flag: Path = LEGACY_MODE_D_FLAG,
    now: float | None = None,
) -> ArbitrationResult:
    """Read, arbitrate, and on accept persist the new state.

    Thin convenience — reads current state, runs ``arbitrate()``, and
    writes the result if accepted. Callers interested in the arbitration
    decision (e.g. to log blocked transitions) inspect the returned
    ``ArbitrationResult`` without re-reading.
    """
    ts = now if now is not None else time.time()
    current = read_state(path=path, now=ts)
    result = arbitrate(
        target_mode=target_mode,
        writer=writer,
        current=current,
        now=ts,
        programme_opt_in=programme_opt_in,
    )
    if result.accepted:
        write_state(result.state, path=path, legacy_flag=legacy_flag)
    else:
        log.info(
            "evil-pet-state: %s→%s blocked (writer=%s, reason=%s)",
            current.mode.value,
            target_mode.value,
            writer,
            result.reason,
        )
    return result
