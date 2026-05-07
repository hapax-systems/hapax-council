"""Tests for ward properties cache + SHM I/O."""

from __future__ import annotations

import json
import threading
import time

import pytest

from agents.studio_compositor import ward_properties as wp


@pytest.fixture(autouse=True)
def _redirect_path(monkeypatch, tmp_path):
    monkeypatch.setattr(wp, "WARD_PROPERTIES_PATH", tmp_path / "ward-properties.json")
    wp.clear_ward_properties_cache()
    yield
    wp.clear_ward_properties_cache()


class TestDefaults:
    def test_no_file_returns_defaults(self):
        props = wp.resolve_ward_properties("nonexistent")
        assert props.visible is True
        assert props.alpha == 1.0
        assert props.scale == 1.0
        assert props.position_offset_x == 0.0
        assert props.color_override_rgba is None

    def test_unknown_ward_returns_default(self):
        wp.set_ward_properties("known", wp.WardProperties(alpha=0.5), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("unrelated").alpha == 1.0

    @pytest.mark.parametrize(
        "payload,kind",
        [
            ("null", "null"),
            ('"a string"', "string"),
            ("[1, 2, 3]", "list"),
            ("42", "int"),
        ],
    )
    def test_non_dict_root_falls_back_to_defaults(self, payload, kind):
        """Schema drift: a writer producing valid JSON whose root is not
        a mapping previously raised AttributeError out of
        ``_build_snapshot``'s ``raw.get(...)`` call into the Cairo render
        callback. The cache now falls back to defaults instead of
        crashing the source."""
        wp.WARD_PROPERTIES_PATH.write_text(payload)
        wp.clear_ward_properties_cache()
        # Hot-path call in cairo render — must not raise.
        props = wp.resolve_ward_properties("token_pole")
        assert props.alpha == 1.0, f"root={kind} must yield default WardProperties"
        assert props.visible is True


class TestSetAndResolve:
    def test_set_then_resolve_returns_value(self):
        wp.set_ward_properties("album", wp.WardProperties(alpha=0.4, scale=1.2), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        props = wp.resolve_ward_properties("album")
        assert props.alpha == 0.4
        assert props.scale == 1.2

    def test_all_fallback_applies_to_other_wards(self):
        wp.set_ward_properties("all", wp.WardProperties(alpha=0.7), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("anything").alpha == 0.7

    def test_specific_ward_overrides_all_fallback(self):
        # Specific entries are *full takes* — they don't merge with the
        # ``all`` fallback because the dataclass cannot distinguish
        # "deliberately set to default" from "not specified". Operators
        # wanting the all-fallback on a ward should not register a
        # per-ward entry at all.
        wp.set_ward_properties("all", wp.WardProperties(alpha=0.7), ttl_s=10.0)
        wp.set_ward_properties("album", wp.WardProperties(alpha=1.0, scale=1.5), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        album = wp.resolve_ward_properties("album")
        assert album.alpha == 1.0  # specific full-take wins
        assert album.scale == 1.5
        # An unrelated ward gets the all-fallback alpha.
        other = wp.resolve_ward_properties("token_pole")
        assert other.alpha == 0.7

    def test_invisible_ward(self):
        wp.set_ward_properties("hothouse", wp.WardProperties(visible=False), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("hothouse").visible is False

    def test_many_ward_write_uses_shared_expiry(self):
        wp.set_many_ward_properties(
            {
                "chat_ambient": wp.WardProperties(border_pulse_hz=2.0),
                "token_pole": wp.WardProperties(border_pulse_hz=2.0),
            },
            ttl_s=0.5,
        )

        raw = json.loads(wp.WARD_PROPERTIES_PATH.read_text())
        wards = raw["wards"]
        assert wards["chat_ambient"]["expires_at"] == wards["token_pole"]["expires_at"]

        wp.clear_ward_properties_cache()
        assert wp.get_specific_ward_properties("chat_ambient") is not None
        assert wp.get_specific_ward_properties("token_pole") is not None


class TestExpiry:
    def test_expired_entries_dropped_at_read(self):
        # Generous TTL + sleep margin so CI runners with coarse clock
        # resolution still observe the expiry.
        wp.set_ward_properties("album", wp.WardProperties(alpha=0.3), ttl_s=0.1)
        wp.clear_ward_properties_cache()
        time.sleep(0.3)
        props = wp.resolve_ward_properties("album")
        assert props.alpha == 1.0  # back to defaults

    def test_negative_ttl_rejected(self):
        wp.set_ward_properties("album", wp.WardProperties(alpha=0.3), ttl_s=0.0)
        # nothing written — file doesn't exist
        assert not wp.WARD_PROPERTIES_PATH.exists()

    def test_expired_entries_pruned_from_disk_on_next_write(self):
        """Stale entries drop off the on-disk file when ANY write touches
        it, not just the entry being overwritten. Prior behaviour: a
        ward entry past ``expires_at`` lingered on disk indefinitely
        because the resolver only filtered at read time. Operators
        inspecting ``ward-properties.json`` saw lies (e.g. a 37h-old
        entry overriding what the dataclass default would actually
        produce). Pruning at write keeps disk view in sync with runtime
        semantics."""
        # Write a short-TTL entry for ``album``.
        wp.set_ward_properties("album", wp.WardProperties(alpha=0.3), ttl_s=0.1)
        wp.clear_ward_properties_cache()
        time.sleep(0.3)
        # Confirm the stale ``album`` entry IS on disk (legacy state).
        raw = json.loads(wp.WARD_PROPERTIES_PATH.read_text())
        assert "album" in raw["wards"], "precondition: stale entry on disk before next write"

        # Write a fresh entry for a DIFFERENT ward. The prune step
        # should drop ``album`` even though we never touched it.
        wp.set_ward_properties("token_pole", wp.WardProperties(alpha=0.5), ttl_s=10.0)
        raw = json.loads(wp.WARD_PROPERTIES_PATH.read_text())
        assert "album" not in raw["wards"], (
            "stale album entry should have been pruned by token_pole write"
        )
        assert "token_pole" in raw["wards"], "fresh entry must persist"

    def test_fresh_entries_preserved_on_other_ward_write(self):
        """Pruning must NOT touch entries whose ``expires_at`` is still
        in the future. Sister test to the prune case — pins the prune
        condition so it doesn't accidentally widen to "drop everything
        not in the current write batch"."""
        wp.set_ward_properties("album", wp.WardProperties(alpha=0.3), ttl_s=10.0)
        wp.set_ward_properties("token_pole", wp.WardProperties(alpha=0.5), ttl_s=10.0)
        raw = json.loads(wp.WARD_PROPERTIES_PATH.read_text())
        assert set(raw["wards"].keys()) == {"album", "token_pole"}, (
            "both fresh entries must coexist on disk"
        )


class TestAllResolved:
    def test_returns_every_ward_with_an_entry(self):
        wp.set_ward_properties("a", wp.WardProperties(alpha=0.1), ttl_s=10.0)
        wp.set_ward_properties("b", wp.WardProperties(alpha=0.2), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        out = wp.all_resolved_properties()
        assert set(out.keys()) == {"a", "b"}
        assert out["a"].alpha == 0.1
        assert out["b"].alpha == 0.2


class TestColorRoundtrip:
    def test_color_override_round_trips(self):
        red = (1.0, 0.0, 0.0, 1.0)
        wp.set_ward_properties("album", wp.WardProperties(color_override_rgba=red), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("album").color_override_rgba == red


class TestModulatorFieldPreservation:
    """Regression pin for the 2026-04-23 read-modify-write race.

    ``ward_stimmung_modulator`` writes ``z_plane`` + ``z_index_float`` on a
    5 Hz cadence. Non-modulator consumers use a read-modify-write merge
    pattern whose cached read can go stale between the modulator's write
    and the consumer's. Without preservation, the consumer's stale-read
    (``z_plane="on-scrim"`` default) silently clobbers the modulator's
    non-default write. These tests pin the preserve-on-write behavior.
    """

    def test_consumer_default_preserves_modulator_zplane(self):
        # Modulator writes non-default z_plane first.
        wp.set_ward_properties(
            "sierpinski",
            wp.WardProperties(z_plane="beyond-scrim", z_index_float=0.2, alpha=0.7),
            ttl_s=10.0,
        )
        wp.clear_ward_properties_cache()
        # Consumer writes a default z_plane (simulating a stale-read merge)
        # with a different alpha. The modulator's z_plane must survive.
        wp.set_ward_properties(
            "sierpinski",
            wp.WardProperties(z_plane="on-scrim", z_index_float=0.5, alpha=0.9),
            ttl_s=10.0,
        )
        wp.clear_ward_properties_cache()
        props = wp.resolve_ward_properties("sierpinski")
        assert props.z_plane == "beyond-scrim"
        assert props.z_index_float == 0.2
        # Non-modulator fields from the consumer's write still land.
        assert props.alpha == 0.9

    def test_explicit_nondefault_zplane_overwrites(self):
        # When the caller passes a non-default z_plane, that's an explicit
        # modulator-domain write and must overwrite whatever was there.
        wp.set_ward_properties(
            "album",
            wp.WardProperties(z_plane="beyond-scrim", z_index_float=0.2),
            ttl_s=10.0,
        )
        wp.clear_ward_properties_cache()
        wp.set_ward_properties(
            "album",
            wp.WardProperties(z_plane="mid-scrim", z_index_float=0.5),
            ttl_s=10.0,
        )
        wp.clear_ward_properties_cache()
        props = wp.resolve_ward_properties("album")
        assert props.z_plane == "mid-scrim"
        # z_index_float at default 0.5 when disk was non-default triggers
        # preservation — this is by design (modulator owns both fields).
        assert props.z_index_float == 0.2

    def test_first_write_with_defaults_persists_defaults(self):
        # No existing entry, caller writes defaults → defaults are written
        # (no preservation source to pull from).
        wp.set_ward_properties("token_pole", wp.WardProperties(alpha=0.8), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        props = wp.resolve_ward_properties("token_pole")
        assert props.z_plane == "on-scrim"
        assert props.z_index_float == 0.5
        assert props.alpha == 0.8


class TestVideoContainerPhase2Fields:
    """New fields added 2026-04-23 for the video-container + emissive epic.

    All default to neutral values so existing wards render unchanged.
    """

    def test_defaults(self):
        props = wp.WardProperties()
        assert props.front_state == "integrated"
        assert props.front_t0 == 0.0
        assert props.parallax_scalar_video == 1.0
        assert props.parallax_scalar_emissive == 1.0
        assert props.crop_rect_override is None

    def test_front_state_values(self):
        # Literal values accepted by the dataclass (no runtime enum coercion,
        # but the type checker pins the set).
        for state in ("integrated", "fronting", "fronted", "retiring"):
            props = wp.WardProperties(front_state=state)
            assert props.front_state == state

    def test_parallax_scalars_differ_per_leg(self):
        props = wp.WardProperties(parallax_scalar_video=0.8, parallax_scalar_emissive=1.4)
        assert props.parallax_scalar_video == 0.8
        assert props.parallax_scalar_emissive == 1.4

    def test_crop_rect_override_roundtrip(self):
        # Normalised rect tightening the peephole.
        props = wp.WardProperties(crop_rect_override=(0.1, 0.1, 0.8, 0.8))
        wp.set_ward_properties("zoomed", props, ttl_s=10.0)
        wp.clear_ward_properties_cache()
        resolved = wp.resolve_ward_properties("zoomed")
        assert resolved.crop_rect_override == (0.1, 0.1, 0.8, 0.8)

    def test_new_fields_roundtrip_through_shm(self):
        props = wp.WardProperties(
            front_state="fronting",
            front_t0=1234.5,
            parallax_scalar_video=0.5,
            parallax_scalar_emissive=2.0,
        )
        wp.set_ward_properties("paired_ward", props, ttl_s=10.0)
        wp.clear_ward_properties_cache()
        resolved = wp.resolve_ward_properties("paired_ward")
        assert resolved.front_state == "fronting"
        assert resolved.front_t0 == 1234.5
        assert resolved.parallax_scalar_video == 0.5
        assert resolved.parallax_scalar_emissive == 2.0


class TestConcurrentWriteSafety:
    """Regression pin for the 2026-04-23 tmp-suffix-collision race.

    Prior to the fix, every ``set_ward_properties`` call wrote to a single
    shared ``ward-properties.json.tmp`` path. Two concurrent callers would
    race: the first's ``tmp.replace(dest)`` would consume the tmp file,
    then the second's ``tmp.replace(dest)`` would raise ``FileNotFoundError``
    (source missing), losing that write. Per-writer tmp suffixes (PID +
    monotonic counter) eliminate the collision.
    """

    def test_concurrent_writers_all_land(self):
        # 20 threads each write a distinct ward. All 20 writes must survive.
        ward_count = 20
        errors: list[BaseException] = []

        def _writer(idx: int) -> None:
            try:
                wp.set_ward_properties(
                    f"w{idx}",
                    wp.WardProperties(alpha=0.01 * idx),
                    ttl_s=10.0,
                )
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=_writer, args=(i,)) for i in range(ward_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        wp.clear_ward_properties_cache()
        # Every ward must be resolvable with the exact alpha we wrote.
        for i in range(ward_count):
            props = wp.resolve_ward_properties(f"w{i}")
            assert props.alpha == pytest.approx(0.01 * i)

    def test_tmp_files_cleaned_up(self, tmp_path):
        # After a successful write, no ``.tmp.*`` files should remain in the
        # ward-properties directory.
        wp.set_ward_properties("album", wp.WardProperties(alpha=0.5), ttl_s=10.0)
        leftovers = list(tmp_path.glob("ward-properties.json.tmp*"))
        assert leftovers == []


# ── lssh-010: orphan ward filter ──────────────────────────────────────


class TestOrphanWardFilter:
    """Pin: lssh-010 — orphan ward IDs are dropped at write time.

    Provenance: 2026-04-21 livestream-surface inventory audit §3.H
    found 5 ward entries in ``/dev/shm/.../ward-properties.json`` not
    declared in any layout. The producer code is left intact (legacy
    callers can still call set_ward_properties without checking) but
    writes are silently dropped at the bus boundary.
    """

    ORPHANS = (
        "vinyl_platter",
        "objectives_overlay",
        "music_candidate_surfacer",
        "scene_director",
        "structural_director",
    )

    def test_orphan_ids_are_constant(self) -> None:
        from agents.studio_compositor.ward_properties import ORPHAN_WARD_IDS

        for orphan in self.ORPHANS:
            assert orphan in ORPHAN_WARD_IDS

    def test_set_ward_properties_drops_orphan_writes(self, tmp_path, monkeypatch) -> None:
        from agents.studio_compositor import ward_properties as wp

        # Redirect the SHM path to a tmp file so the test stays
        # hermetic and doesn't pollute /dev/shm during CI.
        path = tmp_path / "ward-properties.json"
        monkeypatch.setattr(wp, "WARD_PROPERTIES_PATH", path)
        wp.clear_ward_properties_cache()

        for orphan in self.ORPHANS:
            wp.set_ward_properties(orphan, wp.WardProperties(), ttl_s=60.0)

        # No file should exist because every write was dropped.
        # (set_ward_properties is the only thing that creates the file.)
        assert not path.exists()

    def test_legitimate_ward_still_writes(self, tmp_path, monkeypatch) -> None:
        from agents.studio_compositor import ward_properties as wp

        path = tmp_path / "ward-properties.json"
        monkeypatch.setattr(wp, "WARD_PROPERTIES_PATH", path)
        wp.clear_ward_properties_cache()

        wp.set_ward_properties("sierpinski", wp.WardProperties(), ttl_s=60.0)

        assert path.exists()
        import json

        data = json.loads(path.read_text())
        assert "sierpinski" in data["wards"]

    def test_orphan_does_not_clobber_existing_legitimate_wards(self, tmp_path, monkeypatch) -> None:
        from agents.studio_compositor import ward_properties as wp

        path = tmp_path / "ward-properties.json"
        monkeypatch.setattr(wp, "WARD_PROPERTIES_PATH", path)
        wp.clear_ward_properties_cache()

        wp.set_ward_properties("sierpinski", wp.WardProperties(), ttl_s=60.0)
        wp.set_ward_properties("vinyl_platter", wp.WardProperties(), ttl_s=60.0)

        import json

        data = json.loads(path.read_text())
        # Sierpinski survives; orphan never lands.
        assert "sierpinski" in data["wards"]
        assert "vinyl_platter" not in data["wards"]
