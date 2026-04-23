"""Tests for ward properties cache + SHM I/O."""

from __future__ import annotations

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
        wp.set_ward_properties("hardm_dot_matrix", wp.WardProperties(alpha=0.8), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        props = wp.resolve_ward_properties("hardm_dot_matrix")
        assert props.z_plane == "on-scrim"
        assert props.z_index_float == 0.5
        assert props.alpha == 0.8


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
