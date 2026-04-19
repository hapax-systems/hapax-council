"""agents/studio_compositor/music_candidate_surfacer.py — Candidate surfacer for #130+#131.

Watches the derived ``vinyl_playing`` signal (``shared.perceptual_field``)
and, on a ``True → False`` transition, draws candidate tracks from the
combined local + SoundCloud music repo. The surfacer writes the picks
to ``/dev/shm/hapax-compositor/music-candidates.json`` and fires an
ntfy notification + operator-sidechat entry so the operator can reply
``play 1`` / ``play 2`` / ``play 3`` to approve one.

**No auto-playback.** This is strictly an operator-approval gate. Phase
1 terminates at "operator sees candidates, chooses one, selection lands
in music-selection.json". Actual audio dispatch is a Phase 2 task.

**Privacy:** the sidechat channel is local-only by design (see
``shared.operator_sidechat``). The ntfy body is the same shortlist,
which is in line with how other ntfy prompts already surface to the
operator's phone.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from shared.music_repo import DEFAULT_REPO_PATH, LocalMusicRepo, LocalMusicTrack

__all__ = [
    "CANDIDATES_PATH",
    "SELECTION_PATH",
    "SOUNDCLOUD_REPO_PATH",
    "MusicCandidateSurfacer",
    "load_combined_repo",
]

log = logging.getLogger(__name__)

# Output paths. Sidechat + ntfy are the operator-visible surfaces; the
# JSON shortlist on /dev/shm is the machine-readable mirror that the
# Phase 2 playback adapter will read.
CANDIDATES_PATH: Path = Path("/dev/shm/hapax-compositor/music-candidates.json")

# Operator-filled file (written by the sidechat `play <n>` handler) that
# Phase 2 will consume to actually dispatch audio.
SELECTION_PATH: Path = Path("/dev/shm/hapax-compositor/music-selection.json")

# Mirror of the SoundCloud adapter default; duplicated here so this
# module doesn't force-import the agent package.
SOUNDCLOUD_REPO_PATH: Path = Path.home() / "hapax-state" / "music-repo" / "soundcloud.jsonl"

# Only surface one shortlist per cooldown window so a flappy
# vinyl_playing signal doesn't spam the operator.
_DEFAULT_COOLDOWN_S: float = 120.0


def load_combined_repo(
    *,
    local_path: Path | None = None,
    soundcloud_path: Path | None = None,
) -> LocalMusicRepo:
    """Load local + SoundCloud tracks into a single :class:`LocalMusicRepo`.

    Both JSONL files are optional; missing files degrade to empty.
    """
    repo = LocalMusicRepo(path=local_path if local_path is not None else DEFAULT_REPO_PATH)
    repo.load()

    sc_path = soundcloud_path if soundcloud_path is not None else SOUNDCLOUD_REPO_PATH
    if sc_path.exists():
        try:
            for raw in sc_path.read_text(encoding="utf-8").splitlines():
                stripped = raw.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                    track = LocalMusicTrack.model_validate(obj)
                    repo.upsert(track)
                except Exception:
                    log.debug("Skipping malformed soundcloud line: %s", stripped[:80])
        except OSError:
            log.debug("Failed to read SoundCloud repo %s", sc_path, exc_info=True)
    return repo


class MusicCandidateSurfacer:
    """Detects vinyl-off transitions and surfaces candidate tracks.

    Construct once per daemon process; call :meth:`tick` whenever the
    caller wants to evaluate the signal (typically once per second from
    the compositor's auxiliary loop, but cadence is caller-chosen). The
    surfacer carries the only edge-detection state — a boolean of the
    last-observed vinyl_playing, plus a last-surfaced timestamp for
    cooldown.
    """

    def __init__(
        self,
        *,
        cooldown_s: float = _DEFAULT_COOLDOWN_S,
        candidates_path: Path | None = None,
        send_notification=None,  # type: ignore[no-untyped-def]
        append_sidechat=None,  # type: ignore[no-untyped-def]
    ) -> None:
        self._cooldown_s = cooldown_s
        self._candidates_path = candidates_path if candidates_path is not None else CANDIDATES_PATH

        # Lazy-import the real notification / sidechat writers so tests
        # can inject stubs without patching live transport.
        if send_notification is None:
            from shared.notify import send_notification as _send

            send_notification = _send
        if append_sidechat is None:
            from shared.operator_sidechat import append_sidechat as _append

            append_sidechat = _append

        self._send_notification = send_notification
        self._append_sidechat = append_sidechat

        self._last_vinyl: bool | None = None
        self._last_surfaced_ts: float = 0.0

    def tick(
        self,
        vinyl_playing: bool,
        *,
        stance: str = "",
        energy: float = 0.5,
        now: float | None = None,
    ) -> list[LocalMusicTrack]:
        """Evaluate the transition and — if it fired — surface candidates.

        Returns the list of candidates surfaced this tick (empty when no
        transition / in cooldown / no tracks available). The
        :attr:`_last_vinyl` edge tracker is updated unconditionally so
        steady-state True→True / False→False do not fire.
        """
        ts_now = now if now is not None else time.time()
        prior = self._last_vinyl
        self._last_vinyl = vinyl_playing

        # Only fire on True → False. First call with False does NOT fire
        # (no rising edge was seen), so the daemon startup doesn't
        # spam-prompt the operator.
        if prior is not True or vinyl_playing is not False:
            return []
        if ts_now - self._last_surfaced_ts < self._cooldown_s:
            return []

        try:
            repo = load_combined_repo()
        except Exception:
            log.debug("Failed to load combined music repo", exc_info=True)
            return []

        candidates = repo.select_candidates(
            stance=stance,
            energy=energy,
            k=3,
            now=ts_now,
        )
        if not candidates:
            return []

        self._last_surfaced_ts = ts_now
        self._write_shortlist(candidates, ts_now)
        self._emit_notification(candidates)
        self._emit_sidechat(candidates)
        return candidates

    # ── internal surfaces ────────────────────────────────────────────

    def _write_shortlist(self, candidates: list[LocalMusicTrack], ts: float) -> None:
        payload = {
            "ts": ts,
            "candidates": [
                {
                    "index": i + 1,
                    "path": c.path,
                    "title": c.title,
                    "artist": c.artist,
                    "source_type": c.source_type,
                }
                for i, c in enumerate(candidates)
            ],
            "note": (
                "Phase 1 metadata only. Operator approval required — "
                "reply `play <n>` in sidechat to select."
            ),
        }
        try:
            self._candidates_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._candidates_path.with_suffix(self._candidates_path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self._candidates_path)
        except OSError:
            log.debug("Failed to persist candidates", exc_info=True)

    def _format_shortlist_text(self, candidates: list[LocalMusicTrack]) -> str:
        parts = [
            f"{i + 1}) {c.title} — {c.artist} ({c.source_type})" for i, c in enumerate(candidates)
        ]
        return " | ".join(parts) + ". Reply with `play <n>`."

    def _emit_notification(self, candidates: list[LocalMusicTrack]) -> None:
        try:
            self._send_notification(
                "Candidates ready (vinyl stopped)",
                self._format_shortlist_text(candidates),
                priority="low",
                tags=["musical_note"],
            )
        except Exception:
            log.debug("ntfy candidate notification failed (non-fatal)", exc_info=True)

    def _emit_sidechat(self, candidates: list[LocalMusicTrack]) -> None:
        try:
            self._append_sidechat(
                "Candidates: " + self._format_shortlist_text(candidates),
                role="hapax",
            )
        except Exception:
            log.debug("sidechat candidate append failed (non-fatal)", exc_info=True)


# ── sidechat `play <n>` selector ───────────────────────────────────────
# Called by the daimonion sidechat consumer (or any other sidechat tail)
# when the operator's message parses as "play <n>". Writes the chosen
# track to SELECTION_PATH; Phase 2 will pick it up.


def handle_play_command(
    text: str,
    *,
    candidates_path: Path | None = None,
    selection_path: Path | None = None,
) -> dict[str, object] | None:
    """Parse a sidechat utterance as ``play <n>`` and resolve to a track.

    Returns the written selection payload on success, ``None`` when the
    utterance does not match or the requested index is out of range.
    A well-formed command with an unknown shortlist also returns
    ``None`` — the caller should surface a gentle error to the operator.
    """
    stripped = text.strip().lower()
    if not stripped.startswith("play "):
        return None
    rest = stripped[len("play ") :].strip()
    if not rest.isdigit():
        return None
    index = int(rest)

    cpath = candidates_path if candidates_path is not None else CANDIDATES_PATH
    spath = selection_path if selection_path is not None else SELECTION_PATH
    if not cpath.exists():
        log.debug("play %d requested but no shortlist at %s", index, cpath)
        return None
    try:
        shortlist = json.loads(cpath.read_text(encoding="utf-8"))
    except Exception:
        log.debug("Failed to parse shortlist", exc_info=True)
        return None
    candidates = shortlist.get("candidates", [])
    chosen = next((c for c in candidates if c.get("index") == index), None)
    if chosen is None:
        return None

    payload: dict[str, object] = {
        "ts": time.time(),
        "selection": chosen,
        "source": "sidechat",
    }
    try:
        spath.parent.mkdir(parents=True, exist_ok=True)
        tmp = spath.with_suffix(spath.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(spath)
    except OSError:
        log.debug("Failed to persist selection", exc_info=True)
        return None
    return payload
