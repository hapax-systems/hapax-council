"""Tests for shared.vinyl_chain_verify — vinyl broadcast chain verifier (#195)."""

from __future__ import annotations

from shared.audio_topology import ChannelMap, Node, NodeKind, TopologyDescriptor
from shared.vinyl_chain_verify import (
    VinylChainSeverity,
    format_report,
    verify_vinyl_chain,
)


def _descriptor(nodes: list[Node]) -> TopologyDescriptor:
    return TopologyDescriptor(schema_version=2, nodes=nodes, edges=[])


def _l6_source() -> Node:
    return Node(
        id="l6-capture",
        kind=NodeKind.ALSA_SOURCE,
        pipewire_name="alsa_input.usb-ZOOM_Corporation_L6-00.multitrack",
        hw="hw:L6,0",
        channels=ChannelMap(count=12, positions=[f"AUX{i}" for i in range(12)]),
    )


def _livestream_tap() -> Node:
    return Node(
        id="livestream-tap",
        kind=NodeKind.TAP,
        pipewire_name="hapax-livestream-tap",
    )


class TestMinimalHappyPath:
    def test_healthy_chain_returns_ok(self) -> None:
        d = _descriptor([_l6_source(), _livestream_tap()])
        result = verify_vinyl_chain(d)
        assert result.ok is True
        info_findings = result.by_severity(VinylChainSeverity.INFO)
        assert any(f.code == "VINYL_CHAIN_OK" for f in info_findings)


class TestMissingNodes:
    def test_l6_missing_is_error(self) -> None:
        d = _descriptor([_livestream_tap()])
        result = verify_vinyl_chain(d)
        assert result.ok is False
        errors = result.by_severity(VinylChainSeverity.ERROR)
        assert any(f.code == "L6_MULTITRACK_MISSING" for f in errors)

    def test_livestream_tap_missing_is_error(self) -> None:
        d = _descriptor([_l6_source()])
        result = verify_vinyl_chain(d)
        assert result.ok is False
        assert any(
            f.code == "BROADCAST_TAP_MISSING" for f in result.by_severity(VinylChainSeverity.ERROR)
        )

    def test_both_missing_two_errors(self) -> None:
        d = _descriptor([])
        result = verify_vinyl_chain(d)
        errors = result.by_severity(VinylChainSeverity.ERROR)
        codes = {f.code for f in errors}
        assert codes == {"L6_MULTITRACK_MISSING", "BROADCAST_TAP_MISSING"}


class TestModeDActive:
    def test_handytraxx_missing_is_warning_when_mode_d_active(self) -> None:
        """Without Handytraxx in graph under Mode D — warning, not error."""
        d = _descriptor([_l6_source(), _livestream_tap()])
        result = verify_vinyl_chain(d, mode_d_active=True)
        # L6 + tap healthy → no errors. Handytraxx missing → warning.
        warnings = result.by_severity(VinylChainSeverity.WARNING)
        assert any(f.code == "HANDYTRAXX_NOT_VISIBLE" for f in warnings)
        # Mode D was active but the rest of the chain is fine.
        assert result.ok is True

    def test_handytraxx_present_no_warning(self) -> None:
        handytraxx = Node(
            id="handytraxx",
            kind=NodeKind.ALSA_SOURCE,
            pipewire_name="alsa_input.usb-KORG-Handytraxx-00.analog-stereo",
            hw="hw:Handytraxx,0",
        )
        d = _descriptor([_l6_source(), _livestream_tap(), handytraxx])
        result = verify_vinyl_chain(d, mode_d_active=True)
        assert all(
            f.code != "HANDYTRAXX_NOT_VISIBLE"
            for f in result.by_severity(VinylChainSeverity.WARNING)
        )


class TestS4Expected:
    def test_s4_missing_is_warning(self) -> None:
        d = _descriptor([_l6_source(), _livestream_tap()])
        result = verify_vinyl_chain(d, s4_expected=True)
        assert any(
            f.code == "S4_NOT_VISIBLE" for f in result.by_severity(VinylChainSeverity.WARNING)
        )

    def test_s4_present_no_warning(self) -> None:
        s4 = Node(
            id="s4",
            kind=NodeKind.ALSA_SINK,
            pipewire_name="alsa_output.usb-Torso_Electronics_S-4-00.analog-stereo",
            hw="hw:S4,0",
        )
        d = _descriptor([_l6_source(), _livestream_tap(), s4])
        result = verify_vinyl_chain(d, s4_expected=True)
        assert all(
            f.code != "S4_NOT_VISIBLE" for f in result.by_severity(VinylChainSeverity.WARNING)
        )


class TestKindMismatch:
    def test_wrong_kind_surfaces_as_warning(self) -> None:
        """L6 node enumerated as sink instead of source → warning."""
        weird_l6 = Node(
            id="l6-wrong-kind",
            kind=NodeKind.ALSA_SINK,  # wrong side
            pipewire_name="alsa_output.usb-ZOOM_Corporation_L6-00",
            hw="hw:L6,1",
        )
        d = _descriptor([weird_l6, _livestream_tap()])
        result = verify_vinyl_chain(d)
        warnings = result.by_severity(VinylChainSeverity.WARNING)
        assert any(f.code == "L6_MULTITRACK_MISSING_KIND_MISMATCH" for f in warnings)


class TestUnicodeNormalization:
    """D-24 §9.3: NFKD-normalize substring matching so unicode-quirky
    PipeWire node names still match the expected substrings.
    """

    def test_match_survives_compatibility_form(self) -> None:
        # `ﬁ` (U+FB01, latin small ligature fi) decomposes to `fi` under NFKD.
        weird_l6 = Node(
            id="l6-weird",
            kind=NodeKind.ALSA_SOURCE,
            pipewire_name="alsa_input.usb-Zoom_L6-multitrack-mod\u0301ifier",  # combining acute
            hw="hw:L6,0",
        )
        d = _descriptor([weird_l6, _livestream_tap()])
        result = verify_vinyl_chain(d)
        assert result.ok, (
            "NFKD-normalized substring 'multitrack' should match the combining-mark name"
        )

    def test_match_is_case_insensitive_unicode_aware(self) -> None:
        # Casefold (Unicode-aware) catches things plain .lower() misses; here
        # we just verify the casefold path works for ASCII (the Unicode bonus
        # is the same code path).
        upper_l6 = Node(
            id="l6-upper",
            kind=NodeKind.ALSA_SOURCE,
            pipewire_name="ALSA_INPUT.USB-ZOOM_L6-MULTITRACK",
            hw="hw:L6,0",
        )
        d = _descriptor([upper_l6, _livestream_tap()])
        result = verify_vinyl_chain(d)
        assert result.ok


class TestFormatReport:
    def test_report_renders_sections(self) -> None:
        d = _descriptor([])
        result = verify_vinyl_chain(d, mode_d_active=True)
        text = format_report(result)
        assert "FAIL" in text
        assert "ERROR" in text
        assert "L6_MULTITRACK_MISSING" in text
        assert "Plug L6 USB cable" in text

    def test_healthy_report_renders_ok(self) -> None:
        d = _descriptor([_l6_source(), _livestream_tap()])
        result = verify_vinyl_chain(d)
        text = format_report(result)
        assert "OK" in text
        assert "VINYL_CHAIN_OK" in text
