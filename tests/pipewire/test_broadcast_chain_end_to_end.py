"""End-to-end structural integration test for the music broadcast chain.

Audit `/tmp/effect-cam-orchestration-audit-2026-05-02.md` flagged that no
test exercises the FULL pw-cat → loudnorm → duck → USB-line-driver → L-12
→ broadcast-master → OBS chain end-to-end. This file pins the chain's
PipeWire-graph topology so a future edit cannot silently drop a stage,
flip a target.object, or rename the OBS-readable terminal source.

The L-12 hardware loop (USB OUT → physical mixer + operator patch →
USB IN) is operator-patched on real hardware and not exercisable in CI;
the host-side tap point (`hapax-livestream-tap`) is asserted instead.
The relationship is documented inline at the L-12 hop assertion.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "pipewire"

# Configs that compose the music → broadcast chain. Order is documentary
# only — the test asserts edges, not file order.
CHAIN_CONFIGS = (
    "hapax-music-loudnorm.conf",
    "hapax-music-duck.conf",
    "hapax-music-usb-line-driver.conf",
    "hapax-livestream-tap.conf",
    "hapax-broadcast-master.conf",
)

# L-12 USB OUT ALSA sink name pattern. Uses the first 8 chars of the
# device serial so a card-rev bump or different unit doesn't break the
# pin, but a wrong device class (analog-stereo vs analog-surround-40)
# would. The mixer profile must remain analog-surround-40 so all 10
# channels are addressable per the dual-FX routing pin.
L12_USB_OUT_PATTERN = re.compile(
    r"alsa_output\.usb-ZOOM_Corporation_L-12_[0-9A-F]+-00\.analog-surround-40"
)


@pytest.fixture(scope="module")
def chain_configs() -> dict[str, str]:
    """Read every chain config; skip if any is missing (dev-checkout safety)."""
    payloads: dict[str, str] = {}
    for name in CHAIN_CONFIGS:
        path = CONFIG_DIR / name
        if not path.exists():
            pytest.skip(f"chain config {name} missing from repo checkout")
        payloads[name] = path.read_text(encoding="utf-8")
    return payloads


def _strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _extract_playback_target(conf_text: str, owning_node: str) -> str | None:
    """Return the playback.props.target.object for the loopback module that
    owns ``owning_node`` as its capture-side node.name.

    Each chain stage is a single libpipewire-module-filter-chain or
    libpipewire-module-loopback whose capture.props.node.name identifies
    the stage and whose playback.props.target.object identifies the next
    stage. Search is anchored to the owning_node mention so we don't
    cross-pollute when a config defines multiple modules.
    """
    stripped = _strip_comments(conf_text)
    # Find the capture-side declaration of the owning node, then look
    # for the next playback.props block within the same module.
    capture_pattern = re.compile(
        rf'node\.name\s*=\s*"{re.escape(owning_node)}"',
    )
    capture_match = capture_pattern.search(stripped)
    if capture_match is None:
        return None
    rest = stripped[capture_match.end() :]
    # The playback target lives in the playback.props block following
    # the capture.props block. We just take the first target.object
    # encountered after the capture node declaration.
    target_match = re.search(r'target\.object\s*=\s*"([^"]+)"', rest)
    if target_match is None:
        return None
    return target_match.group(1)


# ── Stage 1: music-loudnorm → music-duck ───────────────────────────────


class TestStage1MusicLoudnormToDuck:
    def test_loudnorm_sink_exists(self, chain_configs: dict[str, str]) -> None:
        text = chain_configs["hapax-music-loudnorm.conf"]
        assert 'node.name = "hapax-music-loudnorm"' in text
        assert 'media.class = "Audio/Sink"' in text

    def test_loudnorm_playback_targets_duck(self, chain_configs: dict[str, str]) -> None:
        target = _extract_playback_target(
            chain_configs["hapax-music-loudnorm.conf"],
            "hapax-music-loudnorm",
        )
        assert target == "hapax-music-duck", (
            f"music-loudnorm must hand off to music-duck (got {target!r}); "
            "breaking this drops the operator-VAD/TTS sidechain duck"
        )


# ── Stage 2: music-duck → music-usb-line-driver ────────────────────────


class TestStage2DuckToUsbLineDriver:
    def test_duck_sink_exists(self, chain_configs: dict[str, str]) -> None:
        text = chain_configs["hapax-music-duck.conf"]
        assert 'node.name = "hapax-music-duck"' in text
        assert 'media.class = "Audio/Sink"' in text

    def test_duck_playback_targets_usb_line_driver(self, chain_configs: dict[str, str]) -> None:
        target = _extract_playback_target(
            chain_configs["hapax-music-duck.conf"],
            "hapax-music-duck",
        )
        assert target == "hapax-music-usb-line-driver", (
            f"music-duck must hand off to music-usb-line-driver (got {target!r}); "
            "breaking this drops the +27 dB USB-vs-analog bias correction"
        )


# ── Stage 3: music-usb-line-driver → L-12 USB OUT ──────────────────────


class TestStage3UsbLineDriverToL12:
    """The L-12 hardware step is operator-patched on physical hardware.

    Host-side responsibility ends at the ALSA sink that pumps audio out
    of the L-12 USB OUT. The operator's L-12 surface routes that signal
    through the Evil Pet wet loop and back to USB IN; the return signal
    is captured into ``hapax-livestream-tap`` separately (Stage 4).
    Spec: ``docs/superpowers/specs/2026-04-23-livestream-audio-unified-architecture-design.md``.
    """

    def test_usb_line_driver_sink_exists(self, chain_configs: dict[str, str]) -> None:
        text = chain_configs["hapax-music-usb-line-driver.conf"]
        assert 'node.name = "hapax-music-usb-line-driver"' in text
        assert 'media.class = "Audio/Sink"' in text

    def test_usb_line_driver_playback_targets_l12_pro_audio_profile(
        self, chain_configs: dict[str, str]
    ) -> None:
        target = _extract_playback_target(
            chain_configs["hapax-music-usb-line-driver.conf"],
            "hapax-music-usb-line-driver",
        )
        assert target is not None, "usb-line-driver missing playback.props.target.object"
        assert L12_USB_OUT_PATTERN.fullmatch(target), (
            f"usb-line-driver target.object must be an L-12 analog-surround-40 ALSA "
            f"sink (got {target!r}); the analog-surround-40 profile is what makes "
            "all 10 L-12 channels addressable per the dual-FX routing contract"
        )


# ── Stage 4: livestream-tap is the canonical broadcast bus tap ─────────


class TestStage4LivestreamTap:
    def test_tap_is_null_audio_sink(self, chain_configs: dict[str, str]) -> None:
        text = chain_configs["hapax-livestream-tap.conf"]
        assert 'node.name        = "hapax-livestream-tap"' in text
        assert "support.null-audio-sink" in text, (
            "tap must be null-audio-sink — filter-chain sinks suspend on passive "
            "links and starve the monitor port (research: pipewire-monitor-fix-research.md)"
        )

    def test_tap_exposes_monitor_port(self, chain_configs: dict[str, str]) -> None:
        text = chain_configs["hapax-livestream-tap.conf"]
        assert "monitor.passthrough     = true" in text or "monitor.passthrough = true" in text


# ── Stage 5: broadcast-master captures from tap, exposes Audio/Source ──


class TestStage5BroadcastMaster:
    def test_master_captures_from_livestream_tap(self, chain_configs: dict[str, str]) -> None:
        target = _extract_playback_target(
            chain_configs["hapax-broadcast-master.conf"],
            "hapax-broadcast-master-capture",
        )
        assert target == "hapax-livestream-tap", (
            f"master capture must target livestream-tap (got {target!r}); "
            "the master must read from the SAME tap that producers write to, "
            "or OBS will read pre-master audio and bypass the safety-net limiter"
        )

    def test_master_playback_exposes_audio_source(self, chain_configs: dict[str, str]) -> None:
        text = chain_configs["hapax-broadcast-master.conf"]
        assert 'node.name = "hapax-broadcast-master"' in text
        # Audio/Source media.class on the playback side is what makes
        # the master output a readable input source for downstream
        # consumers (broadcast-normalized capture stage).
        assert 'media.class = "Audio/Source"' in text


# ── Stage 6: broadcast-normalized is the OBS-readable terminal source ──


class TestStage6BroadcastNormalized:
    """Phase 1 design: ``hapax-broadcast-normalized`` is the canonical
    OBS-binding name. The OBS audio source MUST bind here (not to
    ``hapax-livestream:monitor``, which bypasses the master limiter).
    Pinned in ``hapax-broadcast-master.conf`` § OBS BINDING.
    """

    def test_normalized_capture_targets_master(self, chain_configs: dict[str, str]) -> None:
        target = _extract_playback_target(
            chain_configs["hapax-broadcast-master.conf"],
            "hapax-broadcast-normalized-capture",
        )
        assert target == "hapax-broadcast-master", (
            f"normalized capture must target master (got {target!r}); "
            "if this drops, OBS reads audio that bypasses the master limiter"
        )

    def test_normalized_playback_is_terminal_audio_source(
        self, chain_configs: dict[str, str]
    ) -> None:
        text = chain_configs["hapax-broadcast-master.conf"]
        assert 'node.name = "hapax-broadcast-normalized"' in text

    def test_obs_binding_name_documented_in_master_conf(
        self, chain_configs: dict[str, str]
    ) -> None:
        """Operator/runbook contract: the OBS-binding requirement must
        stay visible in the master conf so a future operator edit can't
        silently swap the binding to a pre-limiter source."""
        text = chain_configs["hapax-broadcast-master.conf"]
        assert "hapax-broadcast-normalized" in text
        assert "OBS audio source MUST bind to" in text


# ── End-to-end chain assembly check ────────────────────────────────────


class TestEndToEndChain:
    """Walk the whole chain via target.object edges and assert it
    forms the expected DAG, with the L-12 hardware hop documented as
    the only operator-patched gap.
    """

    def test_full_host_side_chain(self, chain_configs: dict[str, str]) -> None:
        # Build {source_sink: target_object} for every host-side stage.
        edges: dict[str, str | None] = {
            "hapax-music-loudnorm": _extract_playback_target(
                chain_configs["hapax-music-loudnorm.conf"], "hapax-music-loudnorm"
            ),
            "hapax-music-duck": _extract_playback_target(
                chain_configs["hapax-music-duck.conf"], "hapax-music-duck"
            ),
            "hapax-music-usb-line-driver": _extract_playback_target(
                chain_configs["hapax-music-usb-line-driver.conf"],
                "hapax-music-usb-line-driver",
            ),
            "hapax-broadcast-master-capture": _extract_playback_target(
                chain_configs["hapax-broadcast-master.conf"], "hapax-broadcast-master-capture"
            ),
            "hapax-broadcast-normalized-capture": _extract_playback_target(
                chain_configs["hapax-broadcast-master.conf"],
                "hapax-broadcast-normalized-capture",
            ),
        }
        # Pre-L12 segment is a strict linear chain.
        assert edges["hapax-music-loudnorm"] == "hapax-music-duck"
        assert edges["hapax-music-duck"] == "hapax-music-usb-line-driver"
        assert edges["hapax-music-usb-line-driver"] is not None
        assert L12_USB_OUT_PATTERN.fullmatch(edges["hapax-music-usb-line-driver"])
        # Post-L12 segment: tap → master → normalized.
        assert edges["hapax-broadcast-master-capture"] == "hapax-livestream-tap"
        assert edges["hapax-broadcast-normalized-capture"] == "hapax-broadcast-master"

    def test_no_chain_stage_targets_pre_master_obs_sink(
        self, chain_configs: dict[str, str]
    ) -> None:
        """Defense-in-depth: no chain stage may target hapax-livestream:monitor
        (the pre-master tap that bypasses safety-net limiting). The Phase 1
        design moved every OBS-readable surface to hapax-broadcast-normalized
        precisely to prevent operator-pumping incidents like UNKNOWNTRON
        2026-04-23. A future config edit that re-points OBS at
        hapax-livestream:monitor would silently regress this fix."""
        for name, text in chain_configs.items():
            assert "hapax-livestream:monitor" not in _strip_comments(text), (
                f"{name} must not target hapax-livestream:monitor "
                "(pre-master, bypasses safety-net limiter)"
            )
