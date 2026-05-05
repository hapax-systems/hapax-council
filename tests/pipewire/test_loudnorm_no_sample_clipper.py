"""Regression pin: NO loudnorm conf may use hard_limiter_1413.

Audit B #10 (2026-05-02): the LADSPA `hard_limiter_1413` is a sample
clipper at the ceiling — it produces a square-wave at the limit
threshold instead of compressing peaks, which is audibly broken on
hot program material. The whole loudnorm family migrated to
`fast_lookahead_limiter_1913` (5 ms lookahead + smooth gain
reduction) in successive phases:

- music-loudnorm — Phase 1.5
- voice-fx-loudnorm — Phase 1.7
- pc-loudnorm — Audit B #10 (this PR)
- yt-loudnorm — Audit B #10 (this PR)

This regression test scans every loudnorm conf in the repo and
fails fast if `hard_limiter_1413` reappears anywhere — comments
that document the migration are filtered out so future docs that
mention the old plugin by name don't trigger a false positive.

Also pins the audit B-extra fix in hapax-broadcast-master.conf:
the broadcast-master-capture loopback must be `node.passive = false`
so external monitor-port readers (pw-cat, OBS attach, parec) see
the same signal the master loopback sees.
"""

from __future__ import annotations

from pathlib import Path

import pytest

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "pipewire"

LOUDNORM_CONFS = (
    "hapax-music-loudnorm.conf",
    "hapax-voice-fx-loudnorm.conf",
    "hapax-pc-loudnorm.conf",
    "hapax-yt-loudnorm.conf",
)


def _strip_comments(text: str) -> str:
    """Drop comment lines so doc-references to the dead plugin name don't
    register as actual config use."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


@pytest.mark.parametrize("conf_name", LOUDNORM_CONFS)
def test_no_hard_limiter_in_loudnorm_conf(conf_name: str) -> None:
    """No active config block in any loudnorm conf may reference
    hard_limiter_1413. Comments are allowed (they document the
    migration); a plugin = "hard_limiter_1413" line is not."""
    path = CONFIG_DIR / conf_name
    if not path.exists():
        pytest.skip(f"{conf_name} not present in repo checkout")
    config_body = _strip_comments(path.read_text(encoding="utf-8"))
    assert "hard_limiter_1413" not in config_body, (
        f"{conf_name} still wires hard_limiter_1413 (sample clipper). "
        "Migrate to fast_lookahead_limiter_1913 — see music-loudnorm "
        "for the canonical shape."
    )
    assert '"hardLimiter"' not in config_body, (
        f"{conf_name} still wires the hardLimiter LADSPA label. Migrate to fastLookaheadLimiter."
    )


@pytest.mark.parametrize("conf_name", ("hapax-pc-loudnorm.conf", "hapax-yt-loudnorm.conf"))
def test_pc_yt_loudnorm_use_fast_lookahead(conf_name: str) -> None:
    """The two confs touched by audit B #10 must explicitly wire the
    new limiter. Belt-and-braces against accidental partial reverts."""
    path = CONFIG_DIR / conf_name
    if not path.exists():
        pytest.skip(f"{conf_name} not present in repo checkout")
    config_body = _strip_comments(path.read_text(encoding="utf-8"))
    assert "fast_lookahead_limiter_1913" in config_body, (
        f"{conf_name} missing fast_lookahead_limiter_1913 (audit B #10)."
    )
    assert "fastLookaheadLimiter" in config_body, (
        f"{conf_name} missing fastLookaheadLimiter LADSPA label."
    )


def test_broadcast_master_capture_is_active() -> None:
    """Audit B-extra (2026-05-02): hapax-broadcast-master-capture must
    be node.passive = false. With passive=true, the upstream
    support.null-audio-sink monitor port suspends buffer publishing
    for casual external readers (pw-cat, OBS session-attach, parec)
    — the internal loopback driver still gets signal, but every
    external probe reads near-silent. Active capture forces the tap
    monitor to publish to all readers."""
    path = CONFIG_DIR / "hapax-broadcast-master.conf"
    if not path.exists():
        pytest.skip("hapax-broadcast-master.conf not present in repo checkout")
    raw = path.read_text(encoding="utf-8")
    body = _strip_comments(raw)
    # Locate the broadcast-master-capture block and check its passive flag.
    capture_idx = body.find('node.name = "hapax-broadcast-master-capture"')
    assert capture_idx >= 0, "hapax-broadcast-master-capture block missing"
    # Pull the surrounding capture.props block (~30 lines is plenty).
    window_start = body.rfind("capture.props", 0, capture_idx)
    window_end = body.find("playback.props", capture_idx)
    assert window_start >= 0 and window_end > window_start, (
        "could not locate capture.props window for broadcast-master-capture"
    )
    window = body[window_start:window_end]
    assert "node.passive = false" in window, (
        "hapax-broadcast-master-capture must be node.passive = false "
        "(audit B-extra: tap monitor port starvation)."
    )
    assert "node.passive = true" not in window, (
        "hapax-broadcast-master-capture must NOT be node.passive = true "
        "(audit B-extra: tap monitor port starvation)."
    )
