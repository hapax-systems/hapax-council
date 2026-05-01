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
import uuid
from pathlib import Path

from shared.music_repo import DEFAULT_REPO_PATH, LocalMusicRepo, LocalMusicTrack

__all__ = [
    "CANDIDATES_PATH",
    "DEFAULT_IMPINGEMENT_PATH",
    "MUSIC_REQUEST_TOKEN",
    "SELECTION_PATH",
    "SOUNDCLOUD_REPO_PATH",
    "MusicCandidateSurfacer",
    "build_music_request_impingement",
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

# Impingement emission targets — Phase 4 of the content-source-registry
# plan (`docs/superpowers/plans/2026-04-23-content-source-registry-plan.md`)
# routes operator `play <n>` requests through the volitional impingement
# path so they enter the same recruitment + governance surface as
# automatic candidates. The recruitment loop (a follow-up slice) reads
# the JSONL queue and decides whether/when to dispatch; for now the
# direct ``music-selection.json`` write below is preserved as a
# transitional fallback so the existing dispatch chain keeps working.
DEFAULT_IMPINGEMENT_PATH: Path = Path("/dev/shm/hapax-dmn/impingements.jsonl")

#: Interrupt token tagging operator-initiated music requests. The
#: future ``OudepodeRateGate`` (Phase 4 of the plan) bypasses its rate
#: filter when an impingement carries this token (``selection_source``
#: in content == ``"sidechat"``).
MUSIC_REQUEST_TOKEN: str = "music.request"

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
                    "source": c.source,
                    "content_risk": c.content_risk,
                    "broadcast_safe": c.broadcast_safe,
                    "music_provenance": c.music_provenance,
                    "music_license": c.music_license,
                    "provenance_token": c.provenance_token,
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


def build_music_request_impingement(chosen: dict[str, object]) -> dict[str, object]:
    """Build a ``music.request`` impingement payload from a chosen track.

    Per Phase 4 of the content-source-registry plan: operator ``play
    <n>`` requests should enter the affordance recruitment surface as
    ``pattern_match`` impingements with ``interrupt_token =
    'music.request'`` and ``content.selection_source = 'sidechat'`` so
    the future ``OudepodeRateGate`` can bypass the auto-recruit
    rate-limit on explicit operator requests while keeping automatic
    candidates subject to the gate.

    The ``content.narrative`` line is what the affordance pipeline
    will embed for cosine similarity, so it carries the human-readable
    artist + title + source so the recruitment loop matches it against
    music-related capabilities rather than something incidental.
    """
    title = chosen.get("title") or "unknown title"
    artist = chosen.get("artist") or "unknown artist"
    source = chosen.get("source") or "unknown"
    narrative = f"operator requested via sidechat: play {artist} — {title} (source: {source})"
    return {
        "id": uuid.uuid4().hex[:12],
        "timestamp": time.time(),
        "source": "operator.sidechat",
        "type": "pattern_match",
        "strength": 0.95,
        "interrupt_token": MUSIC_REQUEST_TOKEN,
        "content": {
            "narrative": narrative,
            "selection_source": "sidechat",
            "track": chosen,
            "title": title,
            "artist": artist,
            "track_source": source,
            "music_provenance": chosen.get("music_provenance"),
            "music_license": chosen.get("music_license"),
            "provenance_token": chosen.get("provenance_token"),
        },
    }


def _append_impingement(record: dict[str, object], path: Path) -> bool:
    """Atomically append one impingement record as a JSONL line.

    Returns ``True`` on success, ``False`` if the write fails. Failures
    are logged but never raise — the operator's selection should still
    land in ``music-selection.json`` even when the impingement queue is
    unavailable (e.g., tmpfs unmounted, filesystem full).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
        return True
    except OSError:
        log.debug("music.request impingement append failed (non-fatal)", exc_info=True)
        return False


def handle_play_command(
    text: str,
    *,
    candidates_path: Path | None = None,
    selection_path: Path | None = None,
    impingement_path: Path | None = None,
) -> dict[str, object] | None:
    """Parse a sidechat utterance as ``play <n>`` and resolve to a track.

    Returns the written selection payload on success, ``None`` when the
    utterance does not match or the requested index is out of range.
    A well-formed command with an unknown shortlist also returns
    ``None`` — the caller should surface a gentle error to the operator.

    On a valid request a ``music.request`` impingement is also appended
    to ``impingement_path`` so the affordance recruitment loop sees the
    request through the same surface as automatic candidates. The
    direct ``music-selection.json`` write is preserved as a
    transitional fallback until the recruitment loop honors the
    impingement; both paths land on every successful request.
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
    ipath = impingement_path if impingement_path is not None else DEFAULT_IMPINGEMENT_PATH
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

    # Phase 4 routing: operator request → music.request impingement.
    # Best-effort — failure here must not block the transitional
    # selection write below (the operator's request still needs to
    # dispatch).
    impingement = build_music_request_impingement(chosen)
    _append_impingement(impingement, ipath)

    payload: dict[str, object] = {
        "ts": time.time(),
        "path": chosen.get("path"),
        "title": chosen.get("title"),
        "artist": chosen.get("artist"),
        "source": chosen.get("source"),
        "content_risk": chosen.get("content_risk"),
        "music_provenance": chosen.get("music_provenance"),
        "music_license": chosen.get("music_license"),
        "provenance_token": chosen.get("provenance_token"),
        "selection": chosen,
        "selection_source": "sidechat",
        "impingement_id": impingement["id"],
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
