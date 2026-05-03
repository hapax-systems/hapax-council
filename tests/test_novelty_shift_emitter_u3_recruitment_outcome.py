"""u3-recruitment-outcome-telemetry-back-to-emitter — absorbed counter wiring.

cc-task `u3-recruitment-outcome-telemetry-back-to-emitter`. The novelty-shift
emitter's `absorbed_total` counter was hardcoded to 0 because no feedback
loop existed from `recent-recruitment.json` back to the emitter. This wires
that loop: each dispatched impingement is held in `pending_dispatches` until
either RECRUITED (any family in recent-recruitment.json was recruited after
its dispatch_ts) or ABSORBED (absorption_window_s elapsed without any new
recruitment).

Test surface:
  * `read_max_recruitment_ts` — parses recent-recruitment.json, returns max
    last_recruited_ts; None on missing/malformed/empty
  * `resolve_pending_dispatches` — partitions pending into still-pending +
    newly-absorbed based on max_recruitment_ts + absorption_window_s
  * State roundtrip: `_save_state` + `_load_prev_state` preserve
    pending_dispatches + absorbed_total
  * Tick integration: dispatch → recruit-in-window → absorbed stays flat
  * Tick integration: dispatch → no-recruit-in-window → absorbed increments
  * Tick integration: missing recent-recruitment.json → pending stays
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agents.novelty_emitter._emitter import (
    ABSORPTION_WINDOW_S,
    DEFAULT_RECENT_RECRUITMENT_PATH,
    NoveltyShiftEmitter,
    _load_prev_state,
    _save_state,
    read_max_recruitment_ts,
    resolve_pending_dispatches,
)

# ── read_max_recruitment_ts ─────────────────────────────────────────


class TestReadMaxRecruitmentTs:
    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert read_max_recruitment_ts(tmp_path / "nope.json") is None

    def test_malformed_json_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{not valid json")
        assert read_max_recruitment_ts(p) is None

    def test_no_families_key_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "no_families.json"
        p.write_text(json.dumps({"updated_at": 1.0}))
        assert read_max_recruitment_ts(p) is None

    def test_empty_families_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.json"
        p.write_text(json.dumps({"families": {}}))
        assert read_max_recruitment_ts(p) is None

    def test_returns_max_across_families(self, tmp_path: Path) -> None:
        p = tmp_path / "ok.json"
        p.write_text(
            json.dumps(
                {
                    "families": {
                        "preset.bias": {"last_recruited_ts": 100.0},
                        "ward.size": {"last_recruited_ts": 200.0},
                        "camera.hero": {"last_recruited_ts": 150.0},
                    }
                }
            )
        )
        assert read_max_recruitment_ts(p) == pytest.approx(200.0)

    def test_skips_non_dict_entries(self, tmp_path: Path) -> None:
        """Defensive: a corrupt entry shouldn't crash the read."""
        p = tmp_path / "corrupt.json"
        p.write_text(
            json.dumps(
                {
                    "families": {
                        "preset.bias": {"last_recruited_ts": 100.0},
                        "ward.size": "not-a-dict",
                        "camera.hero": {"last_recruited_ts": "not-a-float"},
                    }
                }
            )
        )
        # Only the first entry's ts is valid.
        assert read_max_recruitment_ts(p) == pytest.approx(100.0)

    def test_default_path_constant_matches_compositor_writer(self) -> None:
        """Pin: the path the emitter reads from must match what the
        compositor's recruitment writers emit. If the compositor
        relocates the file, this pin breaks loudly."""
        assert str(DEFAULT_RECENT_RECRUITMENT_PATH) == (
            "/dev/shm/hapax-compositor/recent-recruitment.json"
        )


# ── resolve_pending_dispatches ──────────────────────────────────────


class TestResolvePendingDispatches:
    def test_empty_pending_returns_empty(self) -> None:
        still, absorbed = resolve_pending_dispatches([], max_recruitment_ts=None, now=0.0)
        assert still == []
        assert absorbed == 0

    def test_recruited_dispatch_is_dropped_no_absorbed_count(self) -> None:
        """Recruitment ts > dispatch ts → consumed, drop from pending."""
        pending = [10.0]
        still, absorbed = resolve_pending_dispatches(
            pending, max_recruitment_ts=11.0, now=12.0, window_s=5.0
        )
        assert still == []
        assert absorbed == 0  # consumed, not absorbed

    def test_no_recruitment_within_window_stays_pending(self) -> None:
        """Window not elapsed → keep in pending."""
        pending = [10.0]
        still, absorbed = resolve_pending_dispatches(
            pending, max_recruitment_ts=None, now=12.0, window_s=5.0
        )
        assert still == [10.0]
        assert absorbed == 0

    def test_no_recruitment_past_window_is_absorbed(self) -> None:
        """Window elapsed without recruitment → absorbed."""
        pending = [10.0]
        still, absorbed = resolve_pending_dispatches(
            pending, max_recruitment_ts=None, now=20.0, window_s=5.0
        )
        assert still == []
        assert absorbed == 1

    def test_old_recruitment_does_not_attribute_to_new_dispatch(self) -> None:
        """Recruitment timestamp BEFORE dispatch can't be the recruitment
        for that dispatch (causality). Past window → still absorbed."""
        pending = [100.0]
        still, absorbed = resolve_pending_dispatches(
            pending, max_recruitment_ts=50.0, now=110.0, window_s=5.0
        )
        assert still == []
        assert absorbed == 1  # window elapsed, no causal recruitment

    def test_partition_across_multiple_pending(self) -> None:
        """Mixed batch: some recruited, some absorbed, some still pending."""
        pending = [10.0, 50.0, 100.0]
        # Recruitment at t=60 → recruits dispatch@10 (10<60) AND dispatch@50 (50<60).
        # dispatch@100 is newer than recruitment; window not elapsed → still pending.
        still, absorbed = resolve_pending_dispatches(
            pending, max_recruitment_ts=60.0, now=102.0, window_s=5.0
        )
        assert still == [100.0]
        assert absorbed == 0  # both pre-100s were recruited

    def test_recruitment_exactly_at_dispatch_ts_counts_as_recruited(self) -> None:
        """`>=` boundary — same-tick recruitment is treated as recruitment."""
        pending = [10.0]
        still, absorbed = resolve_pending_dispatches(
            pending, max_recruitment_ts=10.0, now=20.0, window_s=5.0
        )
        assert still == []
        assert absorbed == 0


# ── State roundtrip ─────────────────────────────────────────────────


class TestStateRoundtrip:
    def test_save_and_load_preserves_pending_dispatches(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        _save_state(
            state_file,
            gqi=0.85,
            dispatched_total=3,
            absorbed_total=2,
            pending_dispatches=[10.5, 20.7, 30.9],
        )
        prev, dispatched, absorbed, pending = _load_prev_state(state_file)
        assert prev == pytest.approx(0.85)
        assert dispatched == 3
        assert absorbed == 2
        assert pending == [10.5, 20.7, 30.9]

    def test_load_missing_returns_defaults(self, tmp_path: Path) -> None:
        prev, dispatched, absorbed, pending = _load_prev_state(tmp_path / "nope.json")
        assert prev is None
        assert dispatched == 0
        assert absorbed == 0
        assert pending == []

    def test_load_malformed_returns_defaults(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{not valid")
        prev, dispatched, absorbed, pending = _load_prev_state(p)
        assert prev is None
        assert pending == []

    def test_load_old_format_state_safe(self, tmp_path: Path) -> None:
        """Pre-u3 state files lack absorbed_total + pending_dispatches.
        Loading must default cleanly so a redeploy doesn't crash."""
        p = tmp_path / "old.json"
        p.write_text(json.dumps({"prev_gqi": 0.5, "dispatched_total": 7}))
        prev, dispatched, absorbed, pending = _load_prev_state(p)
        assert prev == pytest.approx(0.5)
        assert dispatched == 7
        assert absorbed == 0  # default
        assert pending == []  # default

    def test_load_corrupt_pending_skips_bad_entries(self, tmp_path: Path) -> None:
        """Defensive: corrupt entries in pending list are silently dropped."""
        p = tmp_path / "corrupt.json"
        p.write_text(
            json.dumps(
                {
                    "prev_gqi": 0.5,
                    "dispatched_total": 1,
                    "absorbed_total": 0,
                    "pending_dispatches": [10.0, "not-a-float", None, 20.0],
                }
            )
        )
        _, _, _, pending = _load_prev_state(p)
        assert pending == [10.0, 20.0]


# ── Tick integration ────────────────────────────────────────────────


class TestTickAbsorbedCounterIntegration:
    """End-to-end: synthetic emitter reads gqi + recent-recruitment.json
    from tmp paths; absorbed counter increments in the right scenarios.
    """

    def _setup(self, tmp_path: Path, gqi: float, ts: float | None = None) -> dict:
        gqi_path = tmp_path / "gq.json"
        gqi_path.write_text(json.dumps({"gqi": gqi, "timestamp": ts or time.time()}))
        return {
            "emitter": NoveltyShiftEmitter(
                gqi_path=gqi_path,
                bus_path=tmp_path / "imp.jsonl",
                textfile=tmp_path / "metrics.prom",
                state_path=tmp_path / "state.json",
                recent_recruitment_path=tmp_path / "recent-recruitment.json",
                absorption_window_s=5.0,
            ),
            "gqi_path": gqi_path,
            "recruitment_path": tmp_path / "recent-recruitment.json",
        }

    def _write_recruitment(self, path: Path, families: dict) -> None:
        path.write_text(json.dumps({"families": families, "updated_at": time.time()}))

    def test_dispatch_then_recruitment_within_window_does_not_absorb(self, tmp_path: Path) -> None:
        env = self._setup(tmp_path, gqi=0.20)
        env["emitter"].tick()  # seed prev=0.20

        # Force a dispatch.
        env["gqi_path"].write_text(json.dumps({"gqi": 0.85, "timestamp": time.time()}))
        env["emitter"].tick()  # dispatch — now in pending

        # Simulate: recruitment in window — NOW timestamp.
        # The dispatch_ts in pending is approximately now() at dispatch tick.
        # Write recruitment at NOW + epsilon so recruitment ts > dispatch_ts.
        time.sleep(0.05)
        self._write_recruitment(
            env["recruitment_path"], {"preset.bias": {"last_recruited_ts": time.time()}}
        )

        # Bring gqi back down so this tick's outcome is "absorbed" status
        # but NOT a new dispatch — the resolver should drop the pending.
        env["gqi_path"].write_text(json.dumps({"gqi": 0.30, "timestamp": time.time()}))
        report = env["emitter"].tick()
        assert report["newly_absorbed"] == 0
        assert report["absorbed_total"] == 0
        assert report["pending_dispatches"] == 0  # consumed

    def test_dispatch_then_no_recruitment_past_window_absorbs(self, tmp_path: Path) -> None:
        env = self._setup(tmp_path, gqi=0.20)
        env["emitter"].tick()  # seed prev=0.20

        # Override absorption_window to a tiny value so we don't sleep 5s.
        env["emitter"].absorption_window_s = 0.05

        env["gqi_path"].write_text(json.dumps({"gqi": 0.85, "timestamp": time.time()}))
        report = env["emitter"].tick()  # dispatch — now in pending
        assert report["status"] == "dispatched"
        assert report["pending_dispatches"] == 1

        # Wait past absorption window WITHOUT writing any recruitment.
        time.sleep(0.10)

        # Bring gqi back down (no new dispatch).
        env["gqi_path"].write_text(json.dumps({"gqi": 0.30, "timestamp": time.time()}))
        report = env["emitter"].tick()
        assert report["newly_absorbed"] == 1
        assert report["absorbed_total"] == 1
        assert report["pending_dispatches"] == 0  # absorbed, dropped

    def test_missing_recent_recruitment_file_keeps_pending_until_window(
        self, tmp_path: Path
    ) -> None:
        env = self._setup(tmp_path, gqi=0.20)
        env["emitter"].tick()  # seed prev=0.20

        env["gqi_path"].write_text(json.dumps({"gqi": 0.85, "timestamp": time.time()}))
        env["emitter"].tick()  # dispatch (no recruitment file written)

        # Immediately tick again — recruitment file missing, window not
        # elapsed (5s default), pending should still be 1.
        env["gqi_path"].write_text(json.dumps({"gqi": 0.30, "timestamp": time.time()}))
        report = env["emitter"].tick()
        assert report["pending_dispatches"] == 1  # still waiting
        assert report["newly_absorbed"] == 0

    def test_textfile_renders_real_absorbed_count(self, tmp_path: Path) -> None:
        env = self._setup(tmp_path, gqi=0.20)
        env["emitter"].absorption_window_s = 0.05
        env["emitter"].tick()
        env["gqi_path"].write_text(json.dumps({"gqi": 0.85, "timestamp": time.time()}))
        env["emitter"].tick()
        time.sleep(0.10)
        env["gqi_path"].write_text(json.dumps({"gqi": 0.30, "timestamp": time.time()}))
        env["emitter"].tick()
        textfile = env["emitter"].textfile
        content = textfile.read_text()
        assert 'outcome="absorbed"} 1' in content
        assert 'outcome="dispatched"} 1' in content


# ── Module export pin ───────────────────────────────────────────────


def test_module_exports() -> None:
    from agents.novelty_emitter._emitter import (  # noqa: F401
        DEFAULT_RECENT_RECRUITMENT_PATH,
        read_max_recruitment_ts,
        resolve_pending_dispatches,
    )

    assert ABSORPTION_WINDOW_S > 0
    assert callable(read_max_recruitment_ts)
    assert callable(resolve_pending_dispatches)
