"""Tests for proactive-alert grounding contract + per-issue-key cooldown.

voice-w1-workspace-alert-groundedness: a proactive issue that names a system
surface (SDLC invariant, LUFS/loudness, systemd service) must be confirmed
against the actual surface before it can actuate an alarm; unconfirmed claims
are logged as unconfirmed-perception. A per-issue-key cooldown prevents one
persistent on-screen string from flooding notifications.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agents.hapax_daimonion.screen_models import Issue, WorkspaceAnalysis
from agents.hapax_daimonion.workspace_monitor import WorkspaceMonitor, _tail_lines


def _make_analysis(issues: list[Issue]) -> WorkspaceAnalysis:
    return WorkspaceAnalysis(
        app="terminal",
        context="editing code",
        summary="Operator is working in the terminal.",
        issues=issues,
    )


def _error(description: str, confidence: float = 0.95) -> Issue:
    return Issue(severity="error", description=description, confidence=confidence)


def _make_monitor(tmp_path) -> tuple[WorkspaceMonitor, MagicMock]:
    """Monitor with mock queue, zero global cooldown, surfaces pointed at tmp."""
    monitor = WorkspaceMonitor(enabled=False, proactive_cooldown_s=0.0)
    queue = MagicMock()
    monitor.set_notification_queue(queue)
    # Point grounding surfaces at the (empty) tmp dir — no host state leaks in.
    monitor._invariant_findings_path = tmp_path / "sdlc-invariant-findings.jsonl"
    monitor._lufs_witness_path = tmp_path / "lufs-s.json"
    return monitor, queue


def _write_invariant_finding(path, *, invariant: str, age_s: float = 0.0) -> None:
    ts = (datetime.now(UTC) - timedelta(seconds=age_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = {
        "ts": ts,
        "invariant": invariant,
        "name": "liveness",
        "holds": False,
        "violations": ["task stuck"],
        "advisory": "advisory text",
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")


def _write_lufs_witness(path, *, in_band: bool, age_s: float = 0.0) -> None:
    payload = {
        "monitor": "lufs-s",
        "timestamp": time.time() - age_s,
        "stages": {
            "hapax-broadcast-master": {
                "lufs_s": -40.0 if in_band else -8.0,
                "in_band": in_band,
                "breach_count": 0 if in_band else 3,
                "analyzer_error": None,
                "analyzer_error_count": 0,
            }
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# Grounding contract: SDLC invariant claims
# ---------------------------------------------------------------------------


async def test_invariant_claim_without_ledger_evidence_is_not_alerted(tmp_path):
    """Screen text claiming an invariant violation must not alarm without ledger proof."""
    monitor, queue = _make_monitor(tmp_path)
    analysis = _make_analysis([_error("SDLC invariant violation: INV-2 btrfs-minio-root-metadata")])

    await monitor._route_proactive_issues(analysis)

    queue.enqueue.assert_not_called()


async def test_invariant_claim_with_fresh_ledger_violation_alerts(tmp_path):
    monitor, queue = _make_monitor(tmp_path)
    _write_invariant_finding(monitor._invariant_findings_path, invariant="INV-2")
    analysis = _make_analysis([_error("SDLC invariant violation: INV-2 liveness breach")])

    await monitor._route_proactive_issues(analysis)

    queue.enqueue.assert_called_once()


async def test_invariant_claim_with_stale_ledger_violation_is_not_alerted(tmp_path):
    monitor, queue = _make_monitor(tmp_path)
    _write_invariant_finding(monitor._invariant_findings_path, invariant="INV-2", age_s=7200.0)
    analysis = _make_analysis([_error("SDLC invariant violation: INV-2 liveness breach")])

    await monitor._route_proactive_issues(analysis)

    queue.enqueue.assert_not_called()


async def test_invariant_claim_for_different_invariant_is_not_alerted(tmp_path):
    """A fresh INV-3 finding does not confirm an INV-2 claim."""
    monitor, queue = _make_monitor(tmp_path)
    _write_invariant_finding(monitor._invariant_findings_path, invariant="INV-3")
    analysis = _make_analysis([_error("SDLC invariant violation: INV-2 liveness breach")])

    await monitor._route_proactive_issues(analysis)

    queue.enqueue.assert_not_called()


async def test_unnamed_invariant_claim_is_not_confirmed_by_any_failing_row(tmp_path):
    """A vague 'invariant' claim with no INV-N must not piggyback on an unrelated
    fresh failing ledger row — confirmation requires the named invariant."""
    monitor, queue = _make_monitor(tmp_path)
    event_log = MagicMock()
    monitor.set_event_log(event_log)
    _write_invariant_finding(monitor._invariant_findings_path, invariant="INV-7")
    analysis = _make_analysis([_error("Terminal shows SDLC invariant violations")])

    await monitor._route_proactive_issues(analysis)

    queue.enqueue.assert_not_called()
    event_log.emit.assert_called_once()
    assert event_log.emit.call_args[0][0] == "unconfirmed_perception"
    assert event_log.emit.call_args[1]["surface"] == "invariant"


# ---------------------------------------------------------------------------
# Bounded ledger tail-read (the findings ledger is append-only and unbounded;
# per-check cost must be proportional to the scan window, not the file size)
# ---------------------------------------------------------------------------


def test_tail_lines_returns_last_n_in_order(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_text("".join(f"row-{i}\n" for i in range(200)), encoding="utf-8")

    assert _tail_lines(path, 3) == ["row-197", "row-198", "row-199"]


def test_tail_lines_short_file_returns_all(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_text("a\nb\n", encoding="utf-8")

    assert _tail_lines(path, 50) == ["a", "b"]


def test_tail_lines_without_trailing_newline(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_text("a\nb\nc", encoding="utf-8")

    assert _tail_lines(path, 2) == ["b", "c"]


def test_tail_lines_empty_file(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_text("", encoding="utf-8")

    assert _tail_lines(path, 50) == []


def test_tail_lines_rows_spanning_multiple_chunks(tmp_path):
    """Rows wider than the backward-read chunk must survive reassembly."""
    path = tmp_path / "ledger.jsonl"
    rows = [f"row-{i}:" + "x" * 5000 for i in range(30)]
    path.write_text("".join(r + "\n" for r in rows), encoding="utf-8")

    assert _tail_lines(path, 20) == rows[-20:]


def test_tail_lines_reads_bounded_bytes_not_whole_file(tmp_path):
    """Per-check I/O must stay proportional to the scan window: tailing a few
    rows of a multi-MB ledger must not consume the whole file."""
    path = tmp_path / "ledger.jsonl"
    path.write_text("".join(f"row-{i}\n" for i in range(500_000)), encoding="utf-8")
    file_size = path.stat().st_size

    read_bytes = 0
    real_open = open

    def counting_open(*args, **kwargs):
        fh = real_open(*args, **kwargs)
        real_read = fh.read

        def read(*a, **kw):
            nonlocal read_bytes
            data = real_read(*a, **kw)
            read_bytes += len(data)
            return data

        fh.read = read
        return fh

    with patch("builtins.open", counting_open):
        result = _tail_lines(path, 50)

    assert result == [f"row-{i}" for i in range(499_950, 500_000)]
    assert read_bytes < file_size // 10


# ---------------------------------------------------------------------------
# Grounding contract: LUFS / loudness claims
# ---------------------------------------------------------------------------


async def test_lufs_claim_without_witness_is_not_alerted(tmp_path):
    """No loudness witness on disk → LUFS claim is unconfirmed perception."""
    monitor, queue = _make_monitor(tmp_path)
    analysis = _make_analysis([_error("Audio: LUFS Breach detected on broadcast chain")])

    await monitor._route_proactive_issues(analysis)

    queue.enqueue.assert_not_called()


async def test_lufs_claim_with_in_band_witness_is_not_alerted(tmp_path):
    monitor, queue = _make_monitor(tmp_path)
    _write_lufs_witness(monitor._lufs_witness_path, in_band=True)
    analysis = _make_analysis([_error("Audio: LUFS Breach detected on broadcast chain")])

    await monitor._route_proactive_issues(analysis)

    queue.enqueue.assert_not_called()


async def test_lufs_claim_with_breaching_witness_alerts(tmp_path):
    monitor, queue = _make_monitor(tmp_path)
    _write_lufs_witness(monitor._lufs_witness_path, in_band=False)
    analysis = _make_analysis([_error("Audio: LUFS Breach detected on broadcast chain")])

    await monitor._route_proactive_issues(analysis)

    queue.enqueue.assert_called_once()


async def test_lufs_claim_with_stale_breaching_witness_is_not_alerted(tmp_path):
    """A breach in a stale witness (daemon down) cannot confirm the claim."""
    monitor, queue = _make_monitor(tmp_path)
    _write_lufs_witness(monitor._lufs_witness_path, in_band=False, age_s=600.0)
    analysis = _make_analysis([_error("Audio: LUFS Breach detected on broadcast chain")])

    await monitor._route_proactive_issues(analysis)

    queue.enqueue.assert_not_called()


async def test_loudness_wording_also_requires_grounding(tmp_path):
    monitor, queue = _make_monitor(tmp_path)
    analysis = _make_analysis([_error("Broadcast loudness is way out of range")])

    await monitor._route_proactive_issues(analysis)

    queue.enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# Grounding contract: systemd service claims
# ---------------------------------------------------------------------------


async def test_service_claim_with_active_unit_is_not_alerted(tmp_path):
    monitor, queue = _make_monitor(tmp_path)
    analysis = _make_analysis([_error("hapax-music-player.service failed on screen")])

    with patch("agents.hapax_daimonion.workspace_monitor.subprocess.run") as run:
        run.return_value = SimpleNamespace(stdout="active\n", returncode=1)
        await monitor._route_proactive_issues(analysis)

    queue.enqueue.assert_not_called()


async def test_service_claim_with_failed_unit_alerts(tmp_path):
    monitor, queue = _make_monitor(tmp_path)
    analysis = _make_analysis([_error("hapax-music-player.service failed on screen")])

    with patch("agents.hapax_daimonion.workspace_monitor.subprocess.run") as run:
        run.return_value = SimpleNamespace(stdout="failed\n", returncode=0)
        await monitor._route_proactive_issues(analysis)

    queue.enqueue.assert_called_once()


async def test_service_claim_with_systemctl_error_is_not_alerted(tmp_path):
    """Verification failure is fail-closed: no alarm without confirmation."""
    monitor, queue = _make_monitor(tmp_path)
    analysis = _make_analysis([_error("hapax-music-player.service failed on screen")])

    with patch("agents.hapax_daimonion.workspace_monitor.subprocess.run") as run:
        run.side_effect = FileNotFoundError("systemctl not found")
        await monitor._route_proactive_issues(analysis)

    queue.enqueue.assert_not_called()


async def test_surface_verification_does_not_block_event_loop(tmp_path):
    """Blocking probes (systemctl, ledger reads) must run off the event loop
    so concurrent tasks (face detection, audio) are not stalled."""
    monitor, queue = _make_monitor(tmp_path)
    analysis = _make_analysis([_error("hapax-music-player.service failed on screen")])

    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    def slow_probe(unit: str) -> bool:
        time.sleep(0.3)
        return True

    ticker_task = asyncio.create_task(ticker())
    try:
        with patch.object(WorkspaceMonitor, "_verify_service_failed", side_effect=slow_probe):
            await asyncio.sleep(0.03)  # let the ticker establish a cadence
            before = ticks
            await monitor._route_proactive_issues(analysis)
            progressed = ticks - before
    finally:
        ticker_task.cancel()

    queue.enqueue.assert_called_once()
    assert progressed >= 5, f"event loop starved during verification (ticks={progressed})"


async def test_overlapping_routings_cannot_double_alert_same_key(tmp_path):
    """The per-key cooldown must hold across concurrent routings: overlapping
    analyses (capture_fresh resets the capture cooldown mid staleness-loop
    flight) must not each pass the gate during a slow verification probe."""
    monitor, queue = _make_monitor(tmp_path)
    analysis = _make_analysis([_error("hapax-music-player.service failed on screen")])

    def slow_probe(unit: str) -> bool:
        time.sleep(0.1)
        return True

    with patch.object(WorkspaceMonitor, "_verify_service_failed", side_effect=slow_probe):
        await asyncio.gather(
            monitor._route_proactive_issues(analysis),
            monitor._route_proactive_issues(analysis),
        )

    queue.enqueue.assert_called_once()


# ---------------------------------------------------------------------------
# Unconfirmed perception is witnessed, not silent
# ---------------------------------------------------------------------------


async def test_unconfirmed_perception_emits_event(tmp_path):
    monitor, queue = _make_monitor(tmp_path)
    event_log = MagicMock()
    monitor.set_event_log(event_log)
    analysis = _make_analysis([_error("Audio: LUFS Breach detected")])

    await monitor._route_proactive_issues(analysis)

    queue.enqueue.assert_not_called()
    event_log.emit.assert_called_once()
    call = event_log.emit.call_args
    assert call[0][0] == "unconfirmed_perception"
    assert call[1]["surface"] == "lufs"
    assert "LUFS" in call[1]["description"]


async def test_unconfirmed_surface_does_not_shadow_real_issue(tmp_path):
    """An unconfirmed surface claim must not consume the cycle's one alert."""
    monitor, queue = _make_monitor(tmp_path)
    analysis = _make_analysis(
        [
            _error("Audio: LUFS Breach detected"),
            _error("Docker container crashed with OOM"),
        ]
    )

    await monitor._route_proactive_issues(analysis)

    queue.enqueue.assert_called_once()
    notification = queue.enqueue.call_args[0][0]
    assert "Docker" in notification.message


# ---------------------------------------------------------------------------
# Per-issue-key cooldown + dedup
# ---------------------------------------------------------------------------


def test_issue_cooldown_default_at_least_30_minutes():
    monitor = WorkspaceMonitor(enabled=False)
    assert monitor.issue_cooldown_s >= 1800.0


async def test_same_issue_key_suppressed_within_cooldown(tmp_path):
    monitor, queue = _make_monitor(tmp_path)
    analysis = _make_analysis([_error("Docker container crashed with OOM")])

    await monitor._route_proactive_issues(analysis)
    await monitor._route_proactive_issues(analysis)
    await monitor._route_proactive_issues(analysis)

    queue.enqueue.assert_called_once()


async def test_same_issue_key_realerts_after_cooldown(tmp_path):
    monitor, queue = _make_monitor(tmp_path)
    analysis = _make_analysis([_error("Docker container crashed with OOM")])

    await monitor._route_proactive_issues(analysis)
    # Age the key past the cooldown window.
    key = next(iter(monitor._issue_last_alert))
    monitor._issue_last_alert[key] = time.monotonic() - monitor.issue_cooldown_s - 1.0
    await monitor._route_proactive_issues(analysis)

    assert queue.enqueue.call_count == 2


async def test_different_issue_not_blocked_by_other_key(tmp_path):
    monitor, queue = _make_monitor(tmp_path)

    await monitor._route_proactive_issues(_make_analysis([_error("Docker container crashed")]))
    await monitor._route_proactive_issues(_make_analysis([_error("Disk almost full on /var")]))

    assert queue.enqueue.call_count == 2


async def test_paraphrased_surface_claims_share_one_key(tmp_path):
    """Confirmed invariant claims with different wording dedup to one alert."""
    monitor, queue = _make_monitor(tmp_path)
    _write_invariant_finding(monitor._invariant_findings_path, invariant="INV-2")

    await monitor._route_proactive_issues(
        _make_analysis([_error("SDLC invariant violation: INV-2 liveness breach")])
    )
    await monitor._route_proactive_issues(
        _make_analysis([_error("INV-2 violated again per terminal output")])
    )

    queue.enqueue.assert_called_once()


async def test_global_proactive_cooldown_still_applies(tmp_path):
    """The existing global cooldown is preserved on top of per-key dedup."""
    monitor, queue = _make_monitor(tmp_path)
    monitor.proactive_cooldown_s = 300.0
    monitor._last_proactive_time = time.monotonic()

    await monitor._route_proactive_issues(_make_analysis([_error("Docker container crashed")]))

    queue.enqueue.assert_not_called()
