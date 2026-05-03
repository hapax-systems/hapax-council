"""Tests for shared.audio_source_class (cc-task audio-audit-D Phase 0).

Pin the 4-class taxonomy + the private->public edge guard. Exhaustive 4x4
edge sweep ensures no other (src, dst) pair gets silently classified as a
leak.
"""

from __future__ import annotations

import pytest

from shared.audio_source_class import (
    ALL_AUDIO_SOURCE_CLASSES,
    AudioEdgeRef,
    PrivateToPublicEdgeError,
    is_private_to_public_edge,
    validate_no_private_to_public_edges,
)


class TestTaxonomyShape:
    def test_four_classes_exposed(self) -> None:
        """Pin the exact 4 classes. Adding a 5th must be a deliberate edit."""
        assert set(ALL_AUDIO_SOURCE_CLASSES) == {"private", "public", "monitor", "unknown"}

    def test_class_values_are_strings(self) -> None:
        """YAML parses Literal values from strings; reject any non-string
        regression."""
        for cls in ALL_AUDIO_SOURCE_CLASSES:
            assert isinstance(cls, str)


class TestIsPrivateToPublicEdge:
    """Exhaustive 4x4 sweep — every (src, dst) pair tested explicitly."""

    @pytest.mark.parametrize("src", ALL_AUDIO_SOURCE_CLASSES)
    @pytest.mark.parametrize("dst", ALL_AUDIO_SOURCE_CLASSES)
    def test_only_private_to_public_returns_true(self, src: str, dst: str) -> None:
        result = is_private_to_public_edge(src, dst)  # type: ignore[arg-type]
        if src == "private" and dst == "public":
            assert result is True
        else:
            assert result is False, f"({src}, {dst}) wrongly flagged as leak"

    def test_private_to_private_is_safe(self) -> None:
        """private -> private is the operator's monitor mix; not a leak."""
        assert not is_private_to_public_edge("private", "private")

    def test_public_to_public_is_safe(self) -> None:
        assert not is_private_to_public_edge("public", "public")

    def test_unknown_to_public_is_NOT_flagged_here(self) -> None:
        """unknown->public is a leak-guard concern (the runtime daemon
        refuses to broadcast through an unclassified source) but is NOT a
        private->public edge. Phase 1's leak-guard handles unknown
        separately via its own check; this helper stays narrow."""
        assert not is_private_to_public_edge("unknown", "public")


class TestValidateNoPrivateToPublicEdges:
    def test_empty_edges_passes(self) -> None:
        validate_no_private_to_public_edges([])

    def test_safe_edges_pass(self) -> None:
        edges = [
            AudioEdgeRef("contact-mic", "private", "operator-monitor", "private"),
            AudioEdgeRef("music-loudnorm", "public", "obs-broadcast", "public"),
            AudioEdgeRef("music-duck.monitor", "monitor", "metric-exporter", "monitor"),
        ]
        validate_no_private_to_public_edges(edges)

    def test_private_to_public_raises(self) -> None:
        edges = [
            AudioEdgeRef(
                src_name="rode-talkback",
                src_class="private",
                dst_name="rtmp-egress",
                dst_class="public",
            ),
        ]
        with pytest.raises(PrivateToPublicEdgeError) as exc:
            validate_no_private_to_public_edges(edges)
        msg = str(exc.value)
        assert "rode-talkback" in msg
        assert "rtmp-egress" in msg
        assert "private" in msg
        assert "public" in msg
        # The message must reference audit finding #1 so a future operator
        # encountering this in a log knows which incident motivated it.
        assert "audit finding #1" in msg

    def test_first_violation_wins(self) -> None:
        """Phase 0 semantic: raise on first leak. (Phase 1 may enumerate all.)"""
        edges = [
            AudioEdgeRef("first-leak", "private", "first-sink", "public"),
            AudioEdgeRef("second-leak", "private", "second-sink", "public"),
        ]
        with pytest.raises(PrivateToPublicEdgeError) as exc:
            validate_no_private_to_public_edges(edges)
        assert "first-leak" in str(exc.value)
        assert "second-leak" not in str(exc.value)

    def test_safe_then_leak_still_raises(self) -> None:
        edges = [
            AudioEdgeRef("ok-src", "private", "ok-dst", "private"),
            AudioEdgeRef("leak-src", "private", "leak-dst", "public"),
        ]
        with pytest.raises(PrivateToPublicEdgeError):
            validate_no_private_to_public_edges(edges)


class TestExceptionClass:
    def test_subclasses_value_error(self) -> None:
        """Backward compat: leak-guard daemons that catch ValueError must
        still see this exception."""
        assert issubclass(PrivateToPublicEdgeError, ValueError)

    def test_distinct_from_value_error_for_targeted_catch(self) -> None:
        """Phase 1's leak-guard catches PrivateToPublicEdgeError specifically
        to differentiate the leak fence from other validation failures."""
        edge = AudioEdgeRef("a", "private", "b", "public")
        try:
            validate_no_private_to_public_edges([edge])
        except PrivateToPublicEdgeError:
            pass
        except ValueError:
            pytest.fail("Should have caught PrivateToPublicEdgeError specifically")


class TestAuditFinding1Regression:
    """The exact failure mode the cc-task is fencing against."""

    def test_l12_leak_pattern_blocked(self) -> None:
        """Audit #1: private contact-mic -> L-12 USB DAC (which then routes
        to the obs-broadcast egress). Pin this exact shape so a future yaml
        edit that reintroduces it fails fast."""
        edges = [
            AudioEdgeRef(
                src_name="cortado-mkiii-contact",
                src_class="private",
                dst_name="l12-usb-line-out",
                dst_class="public",
            ),
        ]
        with pytest.raises(PrivateToPublicEdgeError) as exc:
            validate_no_private_to_public_edges(edges)
        assert "cortado-mkiii-contact" in str(exc.value)
        assert "l12-usb-line-out" in str(exc.value)
