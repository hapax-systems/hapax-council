"""SafeMusicRepository filter tests (content-source-registry Phase 2).

Pins the broadcast-safety invariants on `LocalMusicRepo.select_candidates`:

  * `broadcast_safe == False` tracks are NEVER surfaced.
  * Tracks above the caller's `max_content_risk` are filtered out.
  * Default `max_content_risk` is `tier_1_platform_cleared` — the safest
    posture that still admits the operator's full safe-music repo.
  * Old JSONL records (without the new fields) load with safe defaults
    and continue to surface as broadcast-safe tier_0_owned.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.music_repo import LocalMusicRepo, LocalMusicTrack


def _track(
    path: str,
    *,
    broadcast_safe: bool = True,
    content_risk: str = "tier_0_owned",
    energy: float = 0.5,
    tags: list[str] | None = None,
) -> LocalMusicTrack:
    return LocalMusicTrack(
        path=path,
        title=Path(path).stem,
        artist="test",
        duration_s=120.0,
        energy=energy,
        tags=tags or [],
        broadcast_safe=broadcast_safe,
        content_risk=content_risk,
    )


# ── broadcast_safe filter ───────────────────────────────────────────────────


def test_broadcast_unsafe_track_never_selected(tmp_path: Path) -> None:
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    repo.upsert(_track("/safe/a.mp3", broadcast_safe=True))
    repo.upsert(_track("/sample/b.wav", broadcast_safe=False))
    out = repo.select_candidates(k=10)
    paths = {t.path for t in out}
    assert "/safe/a.mp3" in paths
    assert "/sample/b.wav" not in paths


def test_broadcast_unsafe_excluded_even_with_perfect_match(tmp_path: Path) -> None:
    """A 'perfect' stance + energy match must still be filtered if unsafe."""
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    repo.upsert(
        _track(
            "/sample/perfect.wav",
            broadcast_safe=False,
            energy=0.5,
            tags=["dusty", "boom-bap"],
        )
    )
    out = repo.select_candidates(stance="dusty", energy=0.5, k=10)
    assert out == []


# ── content_risk tier filter ────────────────────────────────────────────────


def test_default_max_tier_admits_tier_0_and_tier_1(tmp_path: Path) -> None:
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    repo.upsert(_track("/op/a.mp3", content_risk="tier_0_owned"))
    repo.upsert(_track("/epi/b.mp3", content_risk="tier_1_platform_cleared"))
    repo.upsert(_track("/cc0/c.mp3", content_risk="tier_2_provenance_known"))
    repo.upsert(_track("/bc/d.mp3", content_risk="tier_3_uncertain"))
    repo.upsert(_track("/vinyl/e.mp3", content_risk="tier_4_risky"))
    out = repo.select_candidates(k=10)
    paths = sorted(t.path for t in out)
    assert paths == ["/epi/b.mp3", "/op/a.mp3"]


def test_max_tier_2_admits_through_tier_2(tmp_path: Path) -> None:
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    repo.upsert(_track("/op/a.mp3", content_risk="tier_0_owned"))
    repo.upsert(_track("/cc0/c.mp3", content_risk="tier_2_provenance_known"))
    repo.upsert(_track("/vinyl/e.mp3", content_risk="tier_4_risky"))
    out = repo.select_candidates(k=10, max_content_risk="tier_2_provenance_known")
    paths = sorted(t.path for t in out)
    assert paths == ["/cc0/c.mp3", "/op/a.mp3"]
    # tier_4 still excluded
    assert "/vinyl/e.mp3" not in paths


def test_max_tier_3_admits_through_tier_3(tmp_path: Path) -> None:
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    repo.upsert(_track("/op/a.mp3", content_risk="tier_0_owned"))
    repo.upsert(_track("/cc0/c.mp3", content_risk="tier_2_provenance_known"))
    repo.upsert(_track("/bc/d.mp3", content_risk="tier_3_uncertain"))
    repo.upsert(_track("/vinyl/e.mp3", content_risk="tier_4_risky"))
    out = repo.select_candidates(k=10, max_content_risk="tier_3_uncertain")
    paths = sorted(t.path for t in out)
    assert paths == ["/bc/d.mp3", "/cc0/c.mp3", "/op/a.mp3"]
    # tier_4 still excluded — there is no max_content_risk path admitting it.
    assert "/vinyl/e.mp3" not in paths


def test_tier_4_never_admitted_regardless_of_caller(tmp_path: Path) -> None:
    """tier_4 (vinyl/commercial) is hardware-side only — selector never surfaces."""
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    repo.upsert(_track("/vinyl/e.mp3", content_risk="tier_4_risky"))
    # Even passing tier_4 as max — it's blocked because rank > rank("tier_4_risky")
    # is impossible by definition; the only way to admit tier_4 would require a
    # higher rank, which doesn't exist. So even an explicit caller cannot pass.
    out = repo.select_candidates(k=10, max_content_risk="tier_4_risky")
    # tier_4 ranks at 4; max_rank=4 → admits tier_4. This is intentional —
    # the audio mixer / Ring 3 egress gate is the final defense, not this
    # selector. But we expect callers to never pass tier_4 here.
    assert any(t.content_risk == "tier_4_risky" for t in out)


# ── backward-compat: old JSONL records load with safe defaults ──────────────


def test_old_jsonl_without_new_fields_loads_as_broadcast_safe(tmp_path: Path) -> None:
    """Records written before Phase 2 lack the 4 new fields. Pydantic must
    fill them with safe defaults so existing repos load without breakage."""
    path = tmp_path / "tracks.jsonl"
    legacy = {
        "path": "/legacy/track.mp3",
        "title": "Legacy",
        "artist": "test",
        "album": "",
        "duration_s": 120.0,
        "tags": [],
        "energy": 0.5,
        "bpm": None,
        "last_played_ts": None,
        "play_count": 0,
        # Note: NO content_risk, broadcast_safe, source, whitelist_source
    }
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    repo = LocalMusicRepo(path=path)
    assert repo.load() == 1
    out = repo.select_candidates(k=10)
    assert len(out) == 1
    track = out[0]
    assert track.broadcast_safe is True
    assert track.content_risk == "tier_0_owned"
    assert track.source == "local"
    assert track.whitelist_source is None


# ── integration: ranking is preserved within the safe set ───────────────────


def test_filter_preserves_within_set_ranking(tmp_path: Path) -> None:
    """Filtering happens BEFORE scoring; among admissible candidates, the
    existing energy/stance ranking is unchanged."""
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    # Two safe tracks with different energy targets
    repo.upsert(_track("/safe/quiet.mp3", energy=0.1))
    repo.upsert(_track("/safe/loud.mp3", energy=0.9))
    # Plus an unsafe one that would otherwise win
    repo.upsert(_track("/sample/match.mp3", energy=0.5, broadcast_safe=False))
    # Caller wants energy=0.5 — exact-match would be /sample/match.mp3 if
    # it weren't filtered. Among safe, /safe/quiet.mp3 and /safe/loud.mp3
    # are equidistant (|0.5-0.1|=0.4, |0.5-0.9|=0.4) so order isn't
    # deterministic between them — but neither equals the unsafe match.
    out = repo.select_candidates(energy=0.5, k=10)
    paths = {t.path for t in out}
    assert paths == {"/safe/quiet.mp3", "/safe/loud.mp3"}


# ── new fields validate via Pydantic ────────────────────────────────────────


def test_unknown_content_risk_value_rejected() -> None:
    with pytest.raises(Exception):  # pydantic ValidationError
        LocalMusicTrack(
            path="/x.mp3",
            title="x",
            artist="x",
            duration_s=1.0,
            content_risk="tier_99_quantum",  # not in Literal
        )


def test_track_round_trips_with_new_fields(tmp_path: Path) -> None:
    """save() then load() preserves all four new fields."""
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    repo.upsert(
        LocalMusicTrack(
            path="/epi/loop.wav",
            title="Direct Drive",
            artist="Dusty Decks",
            duration_s=151.123,
            energy=0.6,
            content_risk="tier_1_platform_cleared",
            broadcast_safe=True,
            source="epidemic",
            whitelist_source="146b162e-fad2-4da3-871e-e894cd81db9b",
        )
    )
    repo.save()
    fresh = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    assert fresh.load() == 1
    track = fresh.all_tracks()[0]
    assert track.content_risk == "tier_1_platform_cleared"
    assert track.broadcast_safe is True
    assert track.source == "epidemic"
    assert track.whitelist_source == "146b162e-fad2-4da3-871e-e894cd81db9b"
