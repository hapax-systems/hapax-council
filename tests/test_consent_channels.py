"""Tests for consent channel selection — menu offering, sufficiency, friction ordering.

Provable properties:
1. Default channels cover all capability dimensions (sufficiency)
2. Guest with no incapabilities gets all channels (universality)
3. Available channels are friction-sorted (ordering)
4. Operator-mediated is always available (universal fallback)
5. Child without guardian only gets operator-mediated (safety)

Self-contained, unittest.mock only.
"""

from __future__ import annotations

import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from shared.governance.consent_channels import (
    CAPABILITY_DIMENSIONS,
    ConsentChannel,
    FrictionEstimate,
    GuestContext,
    Modality,
    assess_channel,
    build_channel_menu,
    check_channel_sufficiency,
    default_channels,
)

# ── Sufficiency ──────────────────────────────────────────────────────


class TestChannelSufficiency(unittest.TestCase):
    def test_default_channels_cover_all_dimensions(self):
        """The built-in channel set covers every capability dimension."""
        sufficient, uncovered = check_channel_sufficiency()
        assert sufficient, f"Uncovered dimensions: {uncovered}"

    def test_removing_all_except_visual_breaks_sufficiency(self):
        """Keeping only visual channels breaks sufficiency for can_see."""
        channels = [c for c in default_channels() if c.modality == Modality.VISUAL]
        sufficient, uncovered = check_channel_sufficiency(channels)
        assert not sufficient
        assert "can_see" in uncovered

    def test_single_channel_insufficient(self):
        """A single channel with preconditions cannot cover all dimensions."""
        channels = [
            ConsentChannel(
                id="qr-only",
                name="QR only",
                modality=Modality.VISUAL,
                preconditions=frozenset({"can_see", "has_smartphone"}),
                default_friction=FrictionEstimate(),
                scope=frozenset({"audio"}),
                description="test",
                constitutive_rule="test",
            )
        ]
        sufficient, uncovered = check_channel_sufficiency(channels)
        assert not sufficient
        assert "can_see" in uncovered
        assert "has_smartphone" in uncovered

    def test_empty_channels_insufficient(self):
        sufficient, uncovered = check_channel_sufficiency([])
        assert not sufficient
        assert len(uncovered) == len(CAPABILITY_DIMENSIONS)


# ── Menu building ────────────────────────────────────────────────────


class TestBuildChannelMenu(unittest.TestCase):
    def test_unknown_guest_gets_all_channels(self):
        """Guest with no known incapabilities sees all channels."""
        menu = build_channel_menu()
        available = [o for o in menu.offers if o.available]
        assert len(available) == len(default_channels())
        assert menu.sufficient

    def test_blind_guest_loses_visual_channel(self):
        """Guest who can't see loses QR code channel."""
        guest = GuestContext(known_incapabilities=frozenset({"can_see"}))
        menu = build_channel_menu(guest=guest)
        available = [o for o in menu.offers if o.available]
        assert all(o.channel.id != "qr-screen" for o in available)
        assert menu.sufficient  # other channels still work

    def test_no_phone_guest_loses_digital_channels(self):
        """Guest without smartphone loses QR and SMS channels."""
        guest = GuestContext(known_incapabilities=frozenset({"has_smartphone"}))
        menu = build_channel_menu(guest=guest)
        available = [o for o in menu.offers if o.available]
        ids = {o.channel.id for o in available}
        assert "qr-screen" not in ids
        assert "sms-link" not in ids
        assert "voice-prompt" in ids
        assert "operator-mediated" in ids
        assert menu.sufficient

    def test_available_channels_sorted_by_friction(self):
        """Available channels are presented in ascending friction order."""
        menu = build_channel_menu()
        available = [o for o in menu.offers if o.available]
        frictions = [o.friction.total for o in available]
        assert frictions == sorted(frictions)

    def test_child_without_guardian_only_operator_mediated(self):
        """Child without guardian can only use operator-mediated consent."""
        guest = GuestContext(is_child=True, guardian_present=False)
        menu = build_channel_menu(guest=guest)
        available = [o for o in menu.offers if o.available]
        assert len(available) == 1
        assert available[0].channel.id == "operator-mediated"

    def test_child_with_guardian_gets_all_channels(self):
        """Child with guardian present can use any channel."""
        guest = GuestContext(is_child=True, guardian_present=True)
        menu = build_channel_menu(guest=guest)
        available = [o for o in menu.offers if o.available]
        assert len(available) == len(default_channels())

    def test_all_incapable_guest_gets_operator_mediated(self):
        """Guest with every incapability still gets operator-mediated."""
        guest = GuestContext(
            known_incapabilities=frozenset(
                {"can_see", "can_hear", "has_smartphone", "can_read", "motor_fine"}
            )
        )
        menu = build_channel_menu(guest=guest)
        available = [o for o in menu.offers if o.available]
        assert menu.sufficient
        assert any(o.channel.id == "operator-mediated" for o in available)

    def test_empty_channel_set_insufficient(self):
        menu = build_channel_menu(channels=[])
        assert not menu.sufficient
        assert "alert" in menu.insufficiency_reason.lower()


# ── Friction ─────────────────────────────────────────────────────────


class TestFrictionEstimate(unittest.TestCase):
    def test_zero_friction(self):
        f = FrictionEstimate()
        assert f.total == 0.0

    def test_dominates_self(self):
        f = FrictionEstimate(cognitive=0.3, motor=0.2)
        assert f.dominates(f)

    def test_lower_dominates_higher(self):
        low = FrictionEstimate(cognitive=0.1, motor=0.1)
        high = FrictionEstimate(cognitive=0.5, motor=0.5)
        assert low.dominates(high)
        assert not high.dominates(low)

    def test_incomparable_frictions(self):
        """Friction is a partial order — some pairs are incomparable."""
        a = FrictionEstimate(cognitive=0.1, social=0.9)
        b = FrictionEstimate(cognitive=0.9, social=0.1)
        assert not a.dominates(b)
        assert not b.dominates(a)

    def test_sms_lower_social_friction_than_voice(self):
        """SMS link has lower social friction than voice prompt."""
        channels = default_channels()
        sms = next(c for c in channels if c.id == "sms-link")
        voice = next(c for c in channels if c.id == "voice-prompt")
        assert sms.default_friction.social < voice.default_friction.social


# ── Channel assessment ───────────────────────────────────────────────


class TestAssessChannel(unittest.TestCase):
    def test_available_when_no_blockers(self):
        channel = default_channels()[0]
        offer = assess_channel(channel, GuestContext())
        assert offer.available

    def test_blocked_by_incapability(self):
        qr = next(c for c in default_channels() if c.id == "qr-screen")
        guest = GuestContext(known_incapabilities=frozenset({"can_see"}))
        offer = assess_channel(qr, guest)
        assert not offer.available
        assert "can_see" in offer.reason

    def test_operator_mediated_always_available(self):
        """Operator-mediated has no preconditions — universally available."""
        op = next(c for c in default_channels() if c.id == "operator-mediated")
        guest = GuestContext(
            known_incapabilities=frozenset({"can_see", "can_hear", "has_smartphone", "can_read"})
        )
        offer = assess_channel(op, guest)
        assert offer.available


# ── Hypothesis properties ────────────────────────────────────────────


class TestChannelProperties(unittest.TestCase):
    @given(
        incapabilities=st.frozensets(
            st.sampled_from(sorted(CAPABILITY_DIMENSIONS)),
            max_size=len(CAPABILITY_DIMENSIONS),
        )
    )
    @settings(max_examples=100)
    def test_operator_mediated_always_survives(self, incapabilities):
        """∀ guest profiles: operator-mediated channel is always available.

        This is the universal fallback property — no combination of
        incapabilities can block the operator-mediated channel because
        it has no preconditions.
        """
        guest = GuestContext(known_incapabilities=incapabilities)
        menu = build_channel_menu(guest=guest)
        available_ids = {o.channel.id for o in menu.offers if o.available}
        assert "operator-mediated" in available_ids

    @given(
        incapabilities=st.frozensets(
            st.sampled_from(sorted(CAPABILITY_DIMENSIONS)),
            max_size=len(CAPABILITY_DIMENSIONS),
        )
    )
    @settings(max_examples=100)
    def test_menu_always_sufficient_with_defaults(self, incapabilities):
        """∀ guest profiles: default channel set is always sufficient.

        Because operator-mediated has no preconditions, the default
        set covers every possible guest.
        """
        guest = GuestContext(known_incapabilities=incapabilities)
        menu = build_channel_menu(guest=guest)
        assert menu.sufficient

    @given(
        incapabilities=st.frozensets(
            st.sampled_from(sorted(CAPABILITY_DIMENSIONS)),
            max_size=len(CAPABILITY_DIMENSIONS),
        )
    )
    @settings(max_examples=100)
    def test_friction_ordering_preserved(self, incapabilities):
        """∀ guest profiles: available channels are friction-sorted."""
        guest = GuestContext(known_incapabilities=incapabilities)
        menu = build_channel_menu(guest=guest)
        available = [o for o in menu.offers if o.available]
        frictions = [o.friction.total for o in available]
        assert frictions == sorted(frictions)
