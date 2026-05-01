"""Tests for shared.music_repo + music candidate surfacer (tasks #130 / #131).

Coverage:

* ``LocalMusicTrack`` validation: energy [0,1], duration > 0, tag norm.
* ``LocalMusicRepo.scan``: walks a tmp tree, upserts records. Runs both
  with and without ``mutagen`` installed (pinned via monkeypatch of
  ``import mutagen``) — we want graceful degradation either way.
* ``select_candidates`` honors ``exclude_recent_s`` cooldown and stance
  tag bonus.
* JSONL round-trip: save → load returns the same records.
* ``MusicCandidateSurfacer`` fires on True→False transition, and NOT on
  True→True or False→False.
* SoundCloud adapter graceful degradation when no client lib available.
* ``handle_play_command`` parses ``play <n>`` and writes a selection.
"""

from __future__ import annotations

import builtins
import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from shared.music_repo import (
    SUPPORTED_EXTENSIONS,
    LocalMusicRepo,
    LocalMusicTrack,
)

# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------


class TestLocalMusicTrackValidation:
    def test_minimal_valid_track(self) -> None:
        t = LocalMusicTrack(
            path="/tmp/a.mp3",
            title="Piece",
            artist="Performer",
            duration_s=120.5,
        )
        assert t.energy == 0.5
        assert t.play_count == 0
        assert t.tags == []
        assert t.source_type == "local"

    def test_rejects_energy_over_one(self) -> None:
        with pytest.raises(ValidationError):
            LocalMusicTrack(
                path="/tmp/a.mp3",
                title="t",
                artist="a",
                duration_s=1.0,
                energy=1.1,
            )

    def test_rejects_negative_energy(self) -> None:
        with pytest.raises(ValidationError):
            LocalMusicTrack(
                path="/tmp/a.mp3",
                title="t",
                artist="a",
                duration_s=1.0,
                energy=-0.01,
            )

    def test_rejects_zero_duration(self) -> None:
        with pytest.raises(ValidationError):
            LocalMusicTrack(
                path="/tmp/a.mp3",
                title="t",
                artist="a",
                duration_s=0.0,
            )

    def test_rejects_negative_play_count(self) -> None:
        with pytest.raises(ValidationError):
            LocalMusicTrack(
                path="/tmp/a.mp3",
                title="t",
                artist="a",
                duration_s=1.0,
                play_count=-1,
            )

    def test_tags_normalized_lowercase_and_deduped(self) -> None:
        t = LocalMusicTrack(
            path="/tmp/a.mp3",
            title="t",
            artist="a",
            duration_s=1.0,
            tags=["Ambient", " ambient ", "RAP", "rap"],
        )
        assert t.tags == ["ambient", "rap"]

    def test_source_type_is_soundcloud_when_tagged(self) -> None:
        t = LocalMusicTrack(
            path="https://soundcloud.com/x/y",
            title="t",
            artist="a",
            duration_s=1.0,
            tags=["soundcloud"],
        )
        assert t.source_type == "soundcloud"


# ---------------------------------------------------------------------------
# Scan + round-trip
# ---------------------------------------------------------------------------


def _touch_audio(root: Path, relpath: str) -> Path:
    """Create a zero-byte file with an audio extension for scan testing."""
    p = root / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")
    return p


def _write_sidecar(audio_path: Path, body: str) -> None:
    audio_path.with_suffix(".yaml").write_text(body, encoding="utf-8")


class TestRepoScanAndRoundTrip:
    def test_scan_without_mutagen_produces_degraded_records(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_import = builtins.__import__

        def _fail_import(name: str, *a: object, **kw: object) -> ModuleType:
            if name == "mutagen" or name.startswith("mutagen."):
                raise ImportError("forced for test")
            return real_import(name, *a, **kw)

        monkeypatch.delitem(sys.modules, "mutagen", raising=False)
        monkeypatch.setattr(builtins, "__import__", _fail_import)

        root = tmp_path / "library"
        _touch_audio(root, "artist/album/01-track.mp3")
        _touch_audio(root, "artist/album/02-track.flac")
        _touch_audio(root, "readme.txt")

        repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
        count = repo.scan(root)
        assert count == 2
        paths = {t.path for t in repo.all_tracks()}
        assert any(p.endswith("01-track.mp3") for p in paths)
        assert any(p.endswith("02-track.flac") for p in paths)
        for t in repo.all_tracks():
            assert t.title
            assert t.artist == "unknown"
            assert t.duration_s >= 1.0
            assert t.music_provenance == "unknown"
            assert t.quarantine_reason == "missing_provenance_sidecar"
            assert t.broadcast_safe is False

    def test_scan_skips_unsupported_extensions(self, tmp_path: Path) -> None:
        root = tmp_path / "library"
        _touch_audio(root, "notes.txt")
        _touch_audio(root, "cover.jpg")
        repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
        count = repo.scan(root)
        assert count == 0

    def test_scan_with_valid_sidecar_admits_hapax_pool_provenance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_import = builtins.__import__

        def _fail_import(name: str, *a: object, **kw: object) -> ModuleType:
            if name == "mutagen" or name.startswith("mutagen."):
                raise ImportError("forced for test")
            return real_import(name, *a, **kw)

        monkeypatch.delitem(sys.modules, "mutagen", raising=False)
        monkeypatch.setattr(builtins, "__import__", _fail_import)

        root = tmp_path / "library"
        audio = _touch_audio(root, "found-sounds/direct-drive.flac")
        _write_sidecar(
            audio,
            """
attribution:
  artist: Dusty Decks
  title: Direct Drive
license:
  spdx: CC-BY-4.0
content_risk: tier_3_uncertain
broadcast_safe: true
source: bandcamp-direct
whitelist_source: dusty-decks-direct-drive
bpm: 92
mood_tags: [dusty, warm]
taxonomy_tags: [boom-bap]
duration_seconds: 151
""".lstrip(),
        )

        repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
        assert repo.scan(root) == 1
        track = repo.all_tracks()[0]
        assert track.music_provenance == "hapax-pool"
        assert track.music_license == "cc-by"
        assert track.provenance_token is not None
        assert track.broadcast_safe is True
        assert track.content_risk == "tier_3_uncertain"
        assert track.quarantine_reason is None
        assert repo.select_candidates(
            k=10,
            max_content_risk="tier_3_uncertain",
        ) == [track]

    def test_scan_quarantines_missing_or_unallowed_provenance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_import = builtins.__import__

        def _fail_import(name: str, *a: object, **kw: object) -> ModuleType:
            if name == "mutagen" or name.startswith("mutagen."):
                raise ImportError("forced for test")
            return real_import(name, *a, **kw)

        monkeypatch.delitem(sys.modules, "mutagen", raising=False)
        monkeypatch.setattr(builtins, "__import__", _fail_import)

        root = tmp_path / "library"
        missing = _touch_audio(root, "missing-sidecar.mp3")
        proprietary = _touch_audio(root, "proprietary.mp3")
        _write_sidecar(
            proprietary,
            """
license:
  spdx: all-rights-reserved
content_risk: tier_4_risky
broadcast_safe: true
source: local
""".lstrip(),
        )

        repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
        assert repo.scan(root) == 2
        by_path = {Path(track.path).name: track for track in repo.all_tracks()}
        assert by_path[missing.name].quarantine_reason == "missing_provenance_sidecar"
        assert by_path[proprietary.name].music_provenance == "unknown"
        assert by_path[proprietary.name].broadcast_safe is False
        assert repo.select_candidates(k=10, max_content_risk="tier_4_risky") == []

    def test_supported_extensions_covers_common_formats(self) -> None:
        for ext in (".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav"):
            assert ext in SUPPORTED_EXTENSIONS

    def test_scan_is_idempotent(self, tmp_path: Path) -> None:
        root = tmp_path / "library"
        _touch_audio(root, "a.mp3")
        _touch_audio(root, "b.mp3")
        repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
        first = repo.scan(root)
        second = repo.scan(root)
        assert first == 2
        assert second == 2
        assert len({t.path for t in repo.all_tracks()}) == 2

    def test_round_trip_save_load(self, tmp_path: Path) -> None:
        path = tmp_path / "tracks.jsonl"
        repo = LocalMusicRepo(path=path)
        repo.upsert(
            LocalMusicTrack(
                path="/tmp/a.mp3",
                title="A",
                artist="Alpha",
                duration_s=30.0,
                tags=["ambient"],
                energy=0.2,
                music_provenance="hapax-pool",
                music_license="licensed-for-broadcast",
            )
        )
        repo.upsert(
            LocalMusicTrack(
                path="/tmp/b.flac",
                title="B",
                artist="Beta",
                duration_s=200.0,
                tags=["rap"],
                energy=0.8,
                music_provenance="hapax-pool",
                music_license="licensed-for-broadcast",
            )
        )
        repo.save()

        reloaded = LocalMusicRepo(path=path)
        reloaded.load()
        all_tracks = {t.path: t for t in reloaded.all_tracks()}
        assert "/tmp/a.mp3" in all_tracks
        assert "/tmp/b.flac" in all_tracks
        assert all_tracks["/tmp/a.mp3"].energy == 0.2
        assert all_tracks["/tmp/b.flac"].tags == ["rap"]

    def test_load_tolerates_malformed_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "tracks.jsonl"
        path.write_text(
            "\n".join(
                [
                    '{"path": "/tmp/a.mp3", "title": "A", "artist": "X", "duration_s": 10.0}',
                    "{ broken",
                    "",
                    '{"path": "/tmp/b.mp3", "title": "B", "artist": "Y", "duration_s": 20.0}',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        repo = LocalMusicRepo(path=path)
        assert repo.load() == 2


# ---------------------------------------------------------------------------
# select_candidates + mark_played
# ---------------------------------------------------------------------------


class TestCandidateSelection:
    def _make_repo(self, tmp_path: Path) -> LocalMusicRepo:
        repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
        repo.upsert(
            LocalMusicTrack(
                path="/tmp/low.mp3",
                title="Low",
                artist="X",
                duration_s=60.0,
                tags=["ambient"],
                energy=0.1,
                music_provenance="hapax-pool",
                music_license="licensed-for-broadcast",
            )
        )
        repo.upsert(
            LocalMusicTrack(
                path="/tmp/mid.mp3",
                title="Mid",
                artist="X",
                duration_s=60.0,
                tags=["boom-bap"],
                energy=0.5,
                music_provenance="hapax-pool",
                music_license="licensed-for-broadcast",
            )
        )
        repo.upsert(
            LocalMusicTrack(
                path="/tmp/high.mp3",
                title="High",
                artist="X",
                duration_s=60.0,
                tags=["hype"],
                energy=0.95,
                music_provenance="hapax-pool",
                music_license="licensed-for-broadcast",
            )
        )
        return repo

    def test_energy_target_biases_ordering(self, tmp_path: Path) -> None:
        repo = self._make_repo(tmp_path)
        picks = repo.select_candidates(energy=0.95, k=3, now=1000.0)
        assert picks[0].title == "High"

    def test_exclude_recent_drops_tracks(self, tmp_path: Path) -> None:
        repo = self._make_repo(tmp_path)
        repo.mark_played("/tmp/high.mp3", when=1000.0 - 30.0)
        picks = repo.select_candidates(energy=0.95, exclude_recent_s=3600, k=3, now=1000.0)
        assert all(p.title != "High" for p in picks)

    def test_stance_tag_bonus(self, tmp_path: Path) -> None:
        repo = self._make_repo(tmp_path)
        picks = repo.select_candidates(stance="ambient", energy=0.95, k=3, now=1000.0)
        titles = [p.title for p in picks]
        assert "Low" in titles

    def test_mark_played_increments_count_and_persists(self, tmp_path: Path) -> None:
        repo = self._make_repo(tmp_path)
        repo.path = tmp_path / "tracks.jsonl"
        repo.save()
        updated = repo.mark_played("/tmp/high.mp3", when=2000.0)
        assert updated is not None
        assert updated.play_count == 1
        assert updated.last_played_ts == 2000.0

        reloaded = LocalMusicRepo(path=repo.path)
        reloaded.load()
        high = next(t for t in reloaded.all_tracks() if t.path == "/tmp/high.mp3")
        assert high.play_count == 1
        assert high.last_played_ts == 2000.0

    def test_mark_played_unknown_returns_none(self, tmp_path: Path) -> None:
        repo = self._make_repo(tmp_path)
        assert repo.mark_played("/tmp/nonexistent.mp3") is None


# ---------------------------------------------------------------------------
# Candidate surfacer
# ---------------------------------------------------------------------------


class TestMusicCandidateSurfacer:
    def _primed_repo(self, tmp_path: Path) -> Path:
        path = tmp_path / "tracks.jsonl"
        repo = LocalMusicRepo(path=path)
        for i in range(5):
            repo.upsert(
                LocalMusicTrack(
                    path=f"/tmp/t{i}.mp3",
                    title=f"Track {i}",
                    artist="A",
                    duration_s=60.0,
                    energy=0.5,
                    music_provenance="hapax-pool",
                    music_license="licensed-for-broadcast",
                )
            )
        repo.save()
        return path

    def _make_surfacer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[object, MagicMock, MagicMock, Path]:
        from agents.studio_compositor import music_candidate_surfacer as mcs

        local_path = self._primed_repo(tmp_path)
        monkeypatch.setattr(mcs, "DEFAULT_REPO_PATH", local_path)
        monkeypatch.setattr(mcs, "SOUNDCLOUD_REPO_PATH", tmp_path / "soundcloud.jsonl")

        send = MagicMock(return_value=True)
        sidechat = MagicMock()
        candidates_path = tmp_path / "shm" / "music-candidates.json"
        surfacer = mcs.MusicCandidateSurfacer(
            cooldown_s=60.0,
            candidates_path=candidates_path,
            send_notification=send,
            append_sidechat=sidechat,
        )
        return surfacer, send, sidechat, candidates_path

    def test_true_to_false_transition_fires(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        surfacer, send, sidechat, cpath = self._make_surfacer(tmp_path, monkeypatch)
        assert surfacer.tick(True, now=100.0) == []
        picks = surfacer.tick(False, now=101.0)
        assert picks
        assert cpath.exists()
        assert send.call_count == 1
        assert sidechat.call_count == 1
        args, kwargs = sidechat.call_args
        assert "Candidates:" in args[0]
        assert kwargs.get("role") == "hapax"

    def test_true_to_true_does_not_fire(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        surfacer, send, _, cpath = self._make_surfacer(tmp_path, monkeypatch)
        surfacer.tick(True, now=100.0)
        picks = surfacer.tick(True, now=101.0)
        assert picks == []
        assert send.call_count == 0
        assert not cpath.exists()

    def test_false_to_false_does_not_fire(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        surfacer, send, _, cpath = self._make_surfacer(tmp_path, monkeypatch)
        surfacer.tick(False, now=100.0)
        picks = surfacer.tick(False, now=101.0)
        assert picks == []
        assert send.call_count == 0
        assert not cpath.exists()

    def test_cooldown_suppresses_rapid_retransitions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        surfacer, send, _, _ = self._make_surfacer(tmp_path, monkeypatch)
        surfacer.tick(True, now=100.0)
        surfacer.tick(False, now=101.0)
        assert send.call_count == 1
        surfacer.tick(True, now=102.0)
        surfacer.tick(False, now=103.0)
        assert send.call_count == 1

    def test_shortlist_payload_shape(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        surfacer, _, _, cpath = self._make_surfacer(tmp_path, monkeypatch)
        surfacer.tick(True, now=100.0)
        surfacer.tick(False, now=101.0)
        data = json.loads(cpath.read_text())
        assert "candidates" in data
        assert len(data["candidates"]) == 3
        for i, c in enumerate(data["candidates"], start=1):
            assert c["index"] == i
            assert "path" in c
            assert "title" in c
            assert "source_type" in c
            assert "music_provenance" in c
            assert "provenance_token" in c
        assert "Phase 1" in data["note"]


# ---------------------------------------------------------------------------
# Sidechat `play <n>` handler
# ---------------------------------------------------------------------------


class TestHandlePlayCommand:
    def _seed_candidates(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "ts": 1000.0,
                    "candidates": [
                        {
                            "index": 1,
                            "path": "/tmp/a.mp3",
                            "title": "A",
                            "artist": "X",
                            "source_type": "local",
                            "source": "local",
                            "content_risk": "tier_0_owned",
                            "broadcast_safe": True,
                            "music_provenance": "hapax-pool",
                            "music_license": "licensed-for-broadcast",
                            "provenance_token": "music:hapax-pool:a",
                        },
                        {
                            "index": 2,
                            "path": "https://soundcloud.com/x/y",
                            "title": "B",
                            "artist": "Y",
                            "source_type": "soundcloud",
                            "source": "soundcloud-oudepode",
                            "content_risk": "tier_0_owned",
                            "broadcast_safe": True,
                            "music_provenance": "soundcloud-licensed",
                            "music_license": "licensed-for-broadcast",
                            "provenance_token": "music:soundcloud-licensed:b",
                        },
                    ],
                    "note": "",
                }
            )
        )

    def test_returns_none_on_non_play_text(self, tmp_path: Path) -> None:
        from agents.studio_compositor.music_candidate_surfacer import handle_play_command

        result = handle_play_command(
            "good morning",
            candidates_path=tmp_path / "c.json",
            selection_path=tmp_path / "s.json",
            impingement_path=tmp_path / "impingements.jsonl",
        )
        assert result is None

    def test_returns_none_when_no_shortlist(self, tmp_path: Path) -> None:
        from agents.studio_compositor.music_candidate_surfacer import handle_play_command

        result = handle_play_command(
            "play 1",
            candidates_path=tmp_path / "missing.json",
            selection_path=tmp_path / "s.json",
            impingement_path=tmp_path / "impingements.jsonl",
        )
        assert result is None

    def test_resolves_index_and_writes_selection(self, tmp_path: Path) -> None:
        from agents.studio_compositor.music_candidate_surfacer import handle_play_command

        cpath = tmp_path / "c.json"
        spath = tmp_path / "s.json"
        self._seed_candidates(cpath)
        result = handle_play_command(
            "play 2",
            candidates_path=cpath,
            selection_path=spath,
            impingement_path=tmp_path / "impingements.jsonl",
        )
        assert result is not None
        assert result["selection"]["title"] == "B"
        assert spath.exists()
        on_disk = json.loads(spath.read_text())
        assert on_disk["selection"]["source_type"] == "soundcloud"
        assert on_disk["path"] == "https://soundcloud.com/x/y"
        assert on_disk["music_provenance"] == "soundcloud-licensed"

    def test_unknown_index_returns_none(self, tmp_path: Path) -> None:
        from agents.studio_compositor.music_candidate_surfacer import handle_play_command

        cpath = tmp_path / "c.json"
        self._seed_candidates(cpath)
        result = handle_play_command(
            "play 99",
            candidates_path=cpath,
            selection_path=tmp_path / "s.json",
            impingement_path=tmp_path / "impingements.jsonl",
        )
        assert result is None

    def test_non_numeric_tail_returns_none(self, tmp_path: Path) -> None:
        from agents.studio_compositor.music_candidate_surfacer import handle_play_command

        cpath = tmp_path / "c.json"
        self._seed_candidates(cpath)
        result = handle_play_command(
            "play now",
            candidates_path=cpath,
            selection_path=tmp_path / "s.json",
            impingement_path=tmp_path / "impingements.jsonl",
        )
        assert result is None


class TestPlayCommandImpingementRouting:
    """Phase 4 routing: ``play <n>`` emits a ``music.request`` impingement
    so operator requests enter the affordance recruitment surface, while
    the transitional direct ``music-selection.json`` write keeps the
    existing dispatch chain working until the recruitment loop honors
    the impingement (separate slice)."""

    def _seed(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "ts": 1000.0,
                    "candidates": [
                        {
                            "index": 1,
                            "path": "/tmp/a.mp3",
                            "title": "Heliotrope",
                            "artist": "Oudepode",
                            "source_type": "local",
                            "source": "local",
                            "music_provenance": "hapax-pool",
                            "music_license": "licensed-for-broadcast",
                            "provenance_token": "music:hapax-pool:a",
                        }
                    ],
                    "note": "",
                }
            )
        )

    def test_emits_impingement_with_music_request_token(self, tmp_path: Path) -> None:
        from agents.studio_compositor.music_candidate_surfacer import (
            MUSIC_REQUEST_TOKEN,
            handle_play_command,
        )

        cpath = tmp_path / "c.json"
        spath = tmp_path / "s.json"
        ipath = tmp_path / "impingements.jsonl"
        self._seed(cpath)

        result = handle_play_command(
            "play 1",
            candidates_path=cpath,
            selection_path=spath,
            impingement_path=ipath,
        )
        assert result is not None
        assert ipath.exists()

        lines = ipath.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["interrupt_token"] == MUSIC_REQUEST_TOKEN
        assert record["source"] == "operator.sidechat"
        assert record["type"] == "pattern_match"
        assert 0.0 <= record["strength"] <= 1.0
        # Bypass-by-content for the future OudepodeRateGate.
        assert record["content"]["selection_source"] == "sidechat"
        assert record["content"]["title"] == "Heliotrope"
        assert record["content"]["artist"] == "Oudepode"

    def test_selection_payload_carries_impingement_id(self, tmp_path: Path) -> None:
        """The transitional selection write back-references the impingement
        id so downstream consumers can correlate the two records."""
        from agents.studio_compositor.music_candidate_surfacer import handle_play_command

        cpath = tmp_path / "c.json"
        spath = tmp_path / "s.json"
        ipath = tmp_path / "impingements.jsonl"
        self._seed(cpath)

        result = handle_play_command(
            "play 1",
            candidates_path=cpath,
            selection_path=spath,
            impingement_path=ipath,
        )
        assert result is not None
        impingement_id = result["impingement_id"]
        record = json.loads(ipath.read_text(encoding="utf-8").splitlines()[0])
        assert record["id"] == impingement_id
        on_disk_selection = json.loads(spath.read_text(encoding="utf-8"))
        assert on_disk_selection["impingement_id"] == impingement_id

    def test_non_play_does_not_emit_impingement(self, tmp_path: Path) -> None:
        from agents.studio_compositor.music_candidate_surfacer import handle_play_command

        cpath = tmp_path / "c.json"
        ipath = tmp_path / "impingements.jsonl"
        self._seed(cpath)

        result = handle_play_command(
            "good morning",
            candidates_path=cpath,
            selection_path=tmp_path / "s.json",
            impingement_path=ipath,
        )
        assert result is None
        assert not ipath.exists()

    def test_unknown_index_does_not_emit_impingement(self, tmp_path: Path) -> None:
        from agents.studio_compositor.music_candidate_surfacer import handle_play_command

        cpath = tmp_path / "c.json"
        ipath = tmp_path / "impingements.jsonl"
        self._seed(cpath)

        result = handle_play_command(
            "play 99",
            candidates_path=cpath,
            selection_path=tmp_path / "s.json",
            impingement_path=ipath,
        )
        assert result is None
        assert not ipath.exists()

    def test_appends_rather_than_overwrites(self, tmp_path: Path) -> None:
        """Two consecutive ``play <n>`` requests must produce two JSONL
        lines so the affordance loop can replay the queue."""
        from agents.studio_compositor.music_candidate_surfacer import handle_play_command

        cpath = tmp_path / "c.json"
        spath = tmp_path / "s.json"
        ipath = tmp_path / "impingements.jsonl"
        self._seed(cpath)

        for _ in range(2):
            handle_play_command(
                "play 1",
                candidates_path=cpath,
                selection_path=spath,
                impingement_path=ipath,
            )
        lines = ipath.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_impingement_failure_does_not_block_selection(self, tmp_path: Path) -> None:
        """If the impingement append fails (e.g., parent dir is a regular
        file rather than a directory), the operator's selection should
        still land in ``music-selection.json`` so the request still
        dispatches via the transitional path."""
        from agents.studio_compositor.music_candidate_surfacer import handle_play_command

        cpath = tmp_path / "c.json"
        spath = tmp_path / "s.json"
        # Make the impingement parent a regular file → mkdir fails.
        bad_parent = tmp_path / "blocked"
        bad_parent.write_text("not a directory")
        ipath = bad_parent / "impingements.jsonl"
        self._seed(cpath)

        result = handle_play_command(
            "play 1",
            candidates_path=cpath,
            selection_path=spath,
            impingement_path=ipath,
        )
        assert result is not None
        assert spath.exists()


class TestBuildMusicRequestImpingement:
    def test_carries_canonical_fields(self) -> None:
        from agents.studio_compositor.music_candidate_surfacer import (
            MUSIC_REQUEST_TOKEN,
            build_music_request_impingement,
        )

        chosen = {
            "index": 1,
            "path": "/tmp/a.mp3",
            "title": "Heliotrope",
            "artist": "Oudepode",
            "source": "local",
            "music_provenance": "hapax-pool",
            "music_license": "licensed-for-broadcast",
            "provenance_token": "music:hapax-pool:a",
        }
        record = build_music_request_impingement(chosen)
        assert record["source"] == "operator.sidechat"
        assert record["type"] == "pattern_match"
        assert record["interrupt_token"] == MUSIC_REQUEST_TOKEN
        assert isinstance(record["id"], str) and len(record["id"]) >= 8
        assert isinstance(record["timestamp"], float)
        # The narrative must reference both the artist and title so the
        # affordance pipeline embeds the right music context.
        narrative = record["content"]["narrative"]
        assert "Oudepode" in narrative
        assert "Heliotrope" in narrative
        assert record["content"]["track"] is chosen
        assert record["content"]["selection_source"] == "sidechat"

    def test_unknown_metadata_falls_back(self) -> None:
        from agents.studio_compositor.music_candidate_surfacer import (
            build_music_request_impingement,
        )

        record = build_music_request_impingement({})
        assert "unknown title" in record["content"]["narrative"]
        assert "unknown artist" in record["content"]["narrative"]


# ---------------------------------------------------------------------------
# SoundCloud adapter graceful degradation
# ---------------------------------------------------------------------------


class TestSoundCloudAdapterGracefulDegradation:
    def test_fetch_likes_returns_empty_when_no_lib(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agents.soundcloud_adapter import __main__ as sc

        monkeypatch.setattr(sc, "_try_import_client", lambda: None)
        rows = sc.fetch_likes("some-user")
        assert rows == []

    def test_main_exits_nonzero_without_configured_sources(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from agents.soundcloud_adapter import __main__ as sc

        monkeypatch.delenv("HAPAX_SOUNDCLOUD_USER_ID", raising=False)
        monkeypatch.delenv("HAPAX_SOUNDCLOUD_USERNAME", raising=False)
        monkeypatch.delenv("HAPAX_SOUNDCLOUD_BANKED_URL", raising=False)
        monkeypatch.setattr(sc, "SOUNDCLOUD_REPO_PATH", tmp_path / "sc.jsonl")

        rc = sc.main(["--auto"])
        assert rc == 2

    def test_main_writes_empty_jsonl_when_lib_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from agents.soundcloud_adapter import __main__ as sc

        monkeypatch.setenv("HAPAX_SOUNDCLOUD_USER_ID", "12345")
        monkeypatch.setattr(sc, "SOUNDCLOUD_REPO_PATH", tmp_path / "sc.jsonl")
        monkeypatch.setattr(sc, "_try_import_client", lambda: None)

        rc = sc.main(["--auto"])
        assert rc == 0
        out = tmp_path / "sc.jsonl"
        assert out.exists()
        assert out.read_text(encoding="utf-8").strip() == ""

    def test_normalize_sclib_track_handles_sparse_fields(self) -> None:
        from agents.soundcloud_adapter.__main__ import _normalize_sclib_track

        class _Track:
            permalink_url = "https://soundcloud.com/x/y"
            title = "A Thing"
            artist = "Someone"
            duration = 184000
            genre = "house, deep"

        row = _normalize_sclib_track(_Track())
        assert row["path"] == "https://soundcloud.com/x/y"
        assert row["title"] == "A Thing"
        assert row["duration_s"] == pytest.approx(184.0)
        assert "soundcloud" in row["tags"]
        assert "house" in row["tags"]
        assert "deep" in row["tags"]
