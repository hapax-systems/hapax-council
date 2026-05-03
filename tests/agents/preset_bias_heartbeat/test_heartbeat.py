"""Tests for the preset.bias heartbeat fallback agent.

Provenance: cc-task ``preset-bias-heartbeat-fallback`` per
``/tmp/effect-cam-orchestration-audit-2026-05-02.md`` §7 QW2.

These tests cover the eight invariants from the cc-task spec:

1. fresh entry → no-op
2. stale entry → write a uniform-sampled family
3. written entry carries the heartbeat-fallback marker
4. write is atomic (no partial-read window)
5. missing recruitment file → write initial entry
6. malformed JSON → log + recover (no crash)
7. tick cadence respects the configured interval
8. family list comes from disk inventory (not a hardcoded list)

Plus three observability + structural assertions:

9. heartbeat preserves sibling family entries on upsert
10. ``run_forever`` survives a single bad tick (broad except)
11. CLI ``__main__`` argument plumbing wires through to ``run_forever``
"""

from __future__ import annotations

import json
import random
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.preset_bias_heartbeat import heartbeat as hb
from agents.studio_compositor.preset_family_selector import family_names

# ── helpers ────────────────────────────────────────────────────────────────


def _write_payload(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ── invariants 1-8 from the spec ──────────────────────────────────────────


class TestFreshness:
    """Invariant 1 — fresh ``preset.bias`` entry → heartbeat no-ops."""

    def test_tick_no_op_when_fresh(self, tmp_path: Path) -> None:
        path = tmp_path / "recent-recruitment.json"
        now = 1_000_000.0
        _write_payload(
            path,
            {
                "families": {
                    "preset.bias": {
                        "family": "audio-reactive",
                        "last_recruited_ts": now - 5.0,
                    }
                }
            },
        )

        result = hb.tick_once(path=path, freshness_s=60.0, now=now)
        assert result is None
        # File untouched — still has the original ts.
        payload = _read_payload(path)
        assert payload["families"]["preset.bias"]["last_recruited_ts"] == now - 5.0
        # No heartbeat marker added.
        assert "source" not in payload["families"]["preset.bias"]

    def test_is_fresh_returns_true_for_recent_entry(self) -> None:
        now = 100.0
        payload = {"families": {"preset.bias": {"last_recruited_ts": now - 30.0}}}
        assert hb.is_fresh(payload, freshness_s=60.0, now=now) is True

    def test_is_fresh_returns_false_for_old_entry(self) -> None:
        now = 100.0
        payload = {"families": {"preset.bias": {"last_recruited_ts": now - 90.0}}}
        assert hb.is_fresh(payload, freshness_s=60.0, now=now) is False


class TestStaleSampling:
    """Invariant 2 — stale entry → uniform-sample a family + write."""

    def test_tick_fires_when_stale(self, tmp_path: Path) -> None:
        path = tmp_path / "recent-recruitment.json"
        now = 1_000_000.0
        _write_payload(
            path,
            {
                "families": {
                    "preset.bias": {
                        "family": "calm-textural",
                        "last_recruited_ts": now - 90.0,  # >60s stale
                    }
                }
            },
        )

        rng = random.Random(42)
        result = hb.tick_once(path=path, freshness_s=60.0, now=now, rng=rng)
        assert result in family_names()

        payload = _read_payload(path)
        entry = payload["families"]["preset.bias"]
        assert entry["family"] == result
        assert entry["last_recruited_ts"] == now

    def test_pick_family_uniform_distribution(self) -> None:
        """Sample a lot, expect every family at least once."""
        rng = random.Random(0)
        seen = {hb.pick_family(rng=rng) for _ in range(500)}
        assert seen == set(family_names())

    def test_pick_family_empty_pool_raises(self) -> None:
        with pytest.raises(RuntimeError, match="empty family pool"):
            hb.pick_family(families=[])


class TestObservabilityMarker:
    """Invariant 3 — written entry carries the ``source`` marker."""

    def test_written_entry_has_heartbeat_source(self, tmp_path: Path) -> None:
        path = tmp_path / "recent-recruitment.json"
        now = 1_000_000.0
        # No prior file — heartbeat fires on first tick.
        rng = random.Random(7)
        family = hb.tick_once(path=path, freshness_s=60.0, now=now, rng=rng)
        assert family is not None

        payload = _read_payload(path)
        entry = payload["families"]["preset.bias"]
        assert entry["source"] == hb.HEARTBEAT_SOURCE
        assert hb.HEARTBEAT_SOURCE == "heartbeat-fallback"  # exact spec marker


class TestAtomicWrite:
    """Invariant 4 — atomic write (no partial-read window)."""

    def test_write_is_atomic_no_intermediate_partial(self, tmp_path: Path) -> None:
        """We can't easily race the writer in a unit test, so we assert
        the structural invariant: the writer never opens the final path
        for write — it goes through a tmp file + os.replace (verified
        by inspecting atomic_write_json's contract via behavioural
        proof: a successful write produces a file whose every read
        observes a syntactically-complete JSON document).
        """
        path = tmp_path / "recent-recruitment.json"
        # Hammer the writer — every read between writes should parse cleanly.
        for i in range(20):
            hb.write_heartbeat_entry(
                "audio-reactive",
                path=path,
                now=1_000_000.0 + i,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert "families" in payload
            assert payload["families"]["preset.bias"]["family"] == "audio-reactive"

    def test_write_uses_tempfile_then_replace(self, tmp_path: Path) -> None:
        """Behavioural pin — call atomic_write_json via the heartbeat path
        and assert we see no leftover ``.tmp`` siblings."""
        path = tmp_path / "recent-recruitment.json"
        hb.write_heartbeat_entry("warm-minimal", path=path, now=1.0)
        siblings = list(tmp_path.iterdir())
        # Exactly one file: the final recruitment file. Tmp got renamed.
        assert siblings == [path]


class TestMissingFile:
    """Invariant 5 — missing recruitment file → write initial entry."""

    def test_tick_creates_file_when_absent(self, tmp_path: Path) -> None:
        path = tmp_path / "recent-recruitment.json"
        assert not path.exists()
        rng = random.Random(11)
        family = hb.tick_once(path=path, freshness_s=60.0, now=1.0, rng=rng)

        assert family is not None
        assert path.exists()
        payload = _read_payload(path)
        assert payload["families"]["preset.bias"]["source"] == hb.HEARTBEAT_SOURCE


class TestMalformedJson:
    """Invariant 6 — malformed JSON → log + recover (no crash)."""

    def test_tick_recovers_from_garbage(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "recent-recruitment.json"
        path.write_text("{this is not json", encoding="utf-8")

        with caplog.at_level("WARNING"):
            family = hb.tick_once(path=path, freshness_s=60.0, now=1.0, rng=random.Random(0))
        assert family is not None
        # The warning surfaced.
        assert any("malformed" in r.message for r in caplog.records)
        # Garbage replaced with a valid heartbeat entry.
        payload = _read_payload(path)
        assert payload["families"]["preset.bias"]["source"] == hb.HEARTBEAT_SOURCE

    def test_read_returns_empty_on_oserror(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "recent-recruitment.json"
        path.write_text("{}", encoding="utf-8")

        def _boom(*_a: object, **_k: object) -> str:
            raise OSError("simulated read failure")

        monkeypatch.setattr(Path, "read_text", _boom)
        # is_fresh should treat as stale (empty payload).
        result = hb.read_recruitment(path)
        assert result == {}


class TestTickCadence:
    """Invariant 7 — ``run_forever`` respects the configured ``tick_s``."""

    def test_run_forever_calls_sleep_with_tick_s(self, tmp_path: Path) -> None:
        """Bound the loop with a sleep that throws on the second call so
        we can assert ``tick_s`` was passed without an infinite loop."""
        path = tmp_path / "recent-recruitment.json"
        sleep_calls: list[float] = []

        class _StopAfter(Exception):
            pass

        def _sleep(s: float) -> None:
            sleep_calls.append(s)
            if len(sleep_calls) >= 2:
                raise _StopAfter

        with pytest.raises(_StopAfter):
            hb.run_forever(tick_s=30.0, freshness_s=60.0, path=path, sleep=_sleep)

        assert sleep_calls == [30.0, 30.0]


class TestDiskInventoryFamilies:
    """Invariant 8 — family list comes from disk inventory, not hardcoded."""

    def test_pick_family_uses_preset_family_selector(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Patch the upstream `family_names` to a custom list and prove the
        heartbeat sees the change without any local hardcoded fallback."""
        canary = ["only-this-one"]
        monkeypatch.setattr(hb, "family_names", lambda: canary)
        rng = random.Random(0)
        # Fifty samples, all must be the canary value — the heartbeat must
        # NOT fall back to a hardcoded list.
        for _ in range(50):
            assert hb.pick_family(rng=rng) == "only-this-one"

    def test_no_hardcoded_family_list_in_module(self) -> None:
        """Negative-form pin: scan the heartbeat module for any literal
        family name. Catches drift if someone adds a hardcoded list."""
        source = Path(hb.__file__).read_text(encoding="utf-8")
        # The audit's 5 family names — none should appear as literals.
        # Comments + docstrings + the audit url are fine; literal-string
        # use in code would mean a hardcoded list.
        for fam in family_names():
            # Check that the family name doesn't appear as a quoted string.
            assert f'"{fam}"' not in source, (
                f"family {fam!r} appears as a string literal in heartbeat.py — "
                f"this risks drift from preset_family_selector. Use family_names() instead."
            )


# ── observability + structural assertions ─────────────────────────────────


class TestSiblingPreservation:
    """Invariant 9 — heartbeat upsert preserves other family entries."""

    def test_other_family_entries_preserved(self, tmp_path: Path) -> None:
        path = tmp_path / "recent-recruitment.json"
        sibling_ts = 999_999.0
        _write_payload(
            path,
            {
                "families": {
                    "overlay.emphasis": {"last_recruited_ts": sibling_ts},
                    "structural.intent": {"last_recruited_ts": sibling_ts},
                }
            },
        )
        hb.write_heartbeat_entry("glitch-dense", path=path, now=1_000_000.0)

        payload = _read_payload(path)
        # Heartbeat entry exists.
        assert "preset.bias" in payload["families"]
        # Siblings still present + untouched.
        assert payload["families"]["overlay.emphasis"]["last_recruited_ts"] == sibling_ts
        assert payload["families"]["structural.intent"]["last_recruited_ts"] == sibling_ts


class TestRunForeverResilience:
    """Invariant 10 — ``run_forever`` survives a single bad tick."""

    def test_run_forever_continues_after_tick_exception(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """tick_once raises once, then run_forever should continue
        sleeping + ticking; we bound the loop with a sentinel sleep."""
        path = tmp_path / "recent-recruitment.json"
        call_count = [0]
        sleep_calls: list[float] = []

        class _StopAfter(Exception):
            pass

        def _flaky_tick(**_kwargs: object) -> str | None:
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("simulated tick failure")
            return "audio-reactive"

        def _sleep(s: float) -> None:
            sleep_calls.append(s)
            if len(sleep_calls) >= 2:
                raise _StopAfter

        with patch.object(hb, "tick_once", _flaky_tick), caplog.at_level("WARNING"):
            with pytest.raises(_StopAfter):
                hb.run_forever(tick_s=1.0, freshness_s=60.0, path=path, sleep=_sleep)

        assert call_count[0] == 2  # second tick ran AFTER the first crashed
        assert any("tick failed" in r.message for r in caplog.records)


class TestCliPlumbing:
    """Invariant 11 — CLI ``__main__`` wires args through to ``run_forever``."""

    def test_main_passes_args_to_run_forever(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from agents.preset_bias_heartbeat import __main__ as entry

        captured: dict[str, object] = {}

        def _spy_run(**kwargs: object) -> None:
            captured.update(kwargs)

        # Don't actually configure logging in the test; would interfere
        # with caplog in other tests.
        monkeypatch.setattr(entry, "configure_logging", lambda **_k: None)
        monkeypatch.setattr(entry, "_install_sigterm_handler", lambda: None)
        monkeypatch.setattr(entry, "run_forever", _spy_run)

        rec_path = str(tmp_path / "rec.json")
        entry.main(["--tick-s", "5.0", "--freshness-s", "12.0", "--path", rec_path])

        assert captured["tick_s"] == 5.0
        assert captured["freshness_s"] == 12.0
        assert str(captured["path"]) == rec_path


# ── thread-safety smoke (no race-condition guarantee, just cleanliness) ───


class TestConcurrentReadDuringWrite:
    """Background reader thread observes only complete JSON during many writes.

    Empirical proof of atomicity from the consumer's POV. Not a strict
    invariant — the OS replace() is the actual guarantee — but a
    regression pin: if anyone changes write_heartbeat_entry to do a
    non-atomic write, this test starts producing JSONDecodeError
    failures.
    """

    def test_no_partial_reads_under_concurrent_write(self, tmp_path: Path) -> None:
        path = tmp_path / "recent-recruitment.json"
        # Seed with a valid file so the reader has something to read.
        hb.write_heartbeat_entry("audio-reactive", path=path, now=0.0)

        stop = threading.Event()
        errors: list[Exception] = []

        def _reader() -> None:
            while not stop.is_set():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    # Sanity: every read must see a coherent shape.
                    assert "families" in payload
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
                time.sleep(0.0005)

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()
        try:
            for i in range(200):
                hb.write_heartbeat_entry("calm-textural", path=path, now=float(i))
        finally:
            stop.set()
            reader.join(timeout=2.0)

        assert errors == [], f"saw {len(errors)} partial reads: {errors[:3]}"
