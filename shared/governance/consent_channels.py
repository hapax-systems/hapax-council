"""Consent channel selection — offering consent through the right modalities.

When a guest enters an ambient sensing environment, the system must offer
consent through channels that are:

1. Available (guest has the required capabilities)
2. Sufficient (the channel set covers all foreseeable guest profiles)
3. Minimal-friction (low-friction channels presented first)
4. Incentive-compatible (truthful preference revelation is dominant strategy)

The system offers a MENU of available channels — it does not select one.
The guest self-selects, preserving their sovereignty as a principal.

Channel descriptions are Labeled[ChannelDescription]: the description must
be able to flow to the guest (they must be able to understand what they're
consenting to via this channel). A channel whose description can't reach
the guest is informationally invalid.

See: docs/research/2026-03-15-consent-channel-selection-research.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger(__name__)


class Modality(Enum):
    """Sensory/interaction mode a channel requires."""

    VISUAL = "visual"  # requires seeing a screen or display
    AUDITORY = "auditory"  # requires hearing
    TACTILE = "tactile"  # requires touching a surface/button
    DIGITAL = "digital"  # requires a personal device (phone, tablet)


@dataclass(frozen=True)
class FrictionEstimate:
    """Multi-dimensional friction assessment for a channel.

    Each dimension is 0.0 (no friction) to 1.0 (maximum friction).
    Friction is a partial order — different guests experience different
    friction on the same channel.
    """

    cognitive: float = 0.0  # reading, understanding, deciding
    motor: float = 0.0  # physical actions required
    social: float = 0.0  # social cost (speaking aloud, admitting refusal)
    temporal: float = 0.0  # time required
    prerequisite: float = 0.0  # acquiring something not already held

    @property
    def total(self) -> float:
        """Sum of all friction components. Used for sorting, not comparison."""
        return self.cognitive + self.motor + self.social + self.temporal + self.prerequisite

    def dominates(self, other: FrictionEstimate) -> bool:
        """True if self is <= other on ALL dimensions (weakly dominates)."""
        return (
            self.cognitive <= other.cognitive
            and self.motor <= other.motor
            and self.social <= other.social
            and self.temporal <= other.temporal
            and self.prerequisite <= other.prerequisite
        )


@dataclass(frozen=True)
class ConsentChannel:
    """A modality through which consent can be offered and received.

    Each channel has preconditions (what the guest needs), a friction
    estimate, and a constitutive rule (what brute action counts as consent).
    """

    id: str
    name: str
    modality: Modality
    preconditions: frozenset[str]  # guest capabilities required
    default_friction: FrictionEstimate
    scope: frozenset[str]  # data categories this channel can convey consent for
    description: str  # what the guest sees/hears explaining the consent
    constitutive_rule: str  # what action counts as consent via this channel


@dataclass(frozen=True)
class GuestContext:
    """What the system knows about a guest at the moment consent is needed.

    Capabilities are partially observable — the system can detect some
    (face visible implies sighted, speech detected implies can hear) but
    cannot know others (has smartphone, speaks English).

    Unknown capabilities are assumed PRESENT (presumption of competence).
    """

    known_capabilities: frozenset[str] = frozenset()
    known_incapabilities: frozenset[str] = frozenset()
    detected_language: str | None = None
    is_child: bool = False
    guardian_present: bool = False


@dataclass(frozen=True)
class ChannelOffer:
    """A consent channel being offered to a guest, with assessed friction."""

    channel: ConsentChannel
    friction: FrictionEstimate
    available: bool  # False if a known incapability blocks this channel
    reason: str = ""  # why unavailable, if not available


@dataclass(frozen=True)
class ChannelMenu:
    """The complete set of channels offered to a guest.

    Sorted by estimated friction (lowest first). The guest self-selects.
    If no channels are available, the system must alert the operator.
    """

    offers: tuple[ChannelOffer, ...]
    sufficient: bool  # True if at least one channel is available
    insufficiency_reason: str = ""


# ── Channel capability dimensions ────────────────────────────────────

# These are the dimensions that channels can require.
# Sufficiency means: for each dimension, at least one channel
# does NOT require it.
CAPABILITY_DIMENSIONS = frozenset(
    {
        "can_see",
        "can_hear",
        "has_smartphone",
        "speaks_english",
        "can_read",
        "is_adult",
        "motor_fine",
    }
)


# ── Built-in channels ────────────────────────────────────────────────


def default_channels() -> list[ConsentChannel]:
    """The system's configured consent channels.

    Each channel covers different capability profiles. Together they
    must cover all foreseeable guests (the sufficiency requirement).
    """
    return [
        ConsentChannel(
            id="qr-screen",
            name="QR code on screen",
            modality=Modality.VISUAL,
            preconditions=frozenset({"can_see", "has_smartphone"}),
            default_friction=FrictionEstimate(
                cognitive=0.2, motor=0.3, social=0.1, temporal=0.3, prerequisite=0.0
            ),
            scope=frozenset({"audio", "video", "transcription", "presence", "biometric"}),
            description=(
                "Scan the QR code to review what data is being collected "
                "and choose what you're comfortable with."
            ),
            constitutive_rule=(
                "Tapping 'Allow' on the QR-linked consent page counts as "
                "explicit consent for the selected scope categories."
            ),
        ),
        ConsentChannel(
            id="voice-prompt",
            name="Voice prompt and response",
            modality=Modality.AUDITORY,
            preconditions=frozenset({"can_hear"}),
            default_friction=FrictionEstimate(
                cognitive=0.3, motor=0.1, social=0.5, temporal=0.2, prerequisite=0.0
            ),
            scope=frozenset({"audio", "transcription", "presence"}),
            description=(
                "The system will explain what it records and ask if you're "
                "OK with it. You can say yes, no, or ask questions."
            ),
            constitutive_rule=(
                "Verbal affirmative response to the system's consent prompt, "
                "verified by speaker identification, counts as explicit consent."
            ),
        ),
        ConsentChannel(
            id="sms-link",
            name="Link sent to your phone",
            modality=Modality.DIGITAL,
            preconditions=frozenset({"has_smartphone"}),
            default_friction=FrictionEstimate(
                cognitive=0.2, motor=0.2, social=0.0, temporal=0.4, prerequisite=0.0
            ),
            scope=frozenset({"audio", "video", "transcription", "presence", "biometric"}),
            description=(
                "A link is sent to your phone where you can review and "
                "choose what data collection you're comfortable with."
            ),
            constitutive_rule=(
                "Tapping 'Allow' on the linked consent page counts as "
                "explicit consent for the selected scope categories."
            ),
        ),
        ConsentChannel(
            id="operator-mediated",
            name="Operator explains and you decide",
            modality=Modality.AUDITORY,
            preconditions=frozenset(),  # no preconditions — universal fallback
            default_friction=FrictionEstimate(
                cognitive=0.3, motor=0.0, social=0.6, temporal=0.3, prerequisite=0.0
            ),
            scope=frozenset({"audio", "video", "transcription", "presence", "biometric"}),
            description=(
                "The operator will explain what the system records and you "
                "can tell them what you're comfortable with. They'll set it up."
            ),
            constitutive_rule=(
                "Operator creates contract on guest's behalf after verbal "
                "confirmation. Operator records which scope items were agreed."
            ),
        ),
    ]


# ── Channel selection logic ──────────────────────────────────────────


def assess_channel(
    channel: ConsentChannel,
    guest: GuestContext,
) -> ChannelOffer:
    """Assess whether a channel is available for a guest and estimate friction."""
    # Check preconditions against known incapabilities
    blocked_by = channel.preconditions & guest.known_incapabilities
    if blocked_by:
        return ChannelOffer(
            channel=channel,
            friction=channel.default_friction,
            available=False,
            reason=f"Guest lacks: {', '.join(sorted(blocked_by))}",
        )

    # Adjust friction based on context
    friction = channel.default_friction

    # Voice has higher social friction when operator is present
    if channel.modality == Modality.AUDITORY and channel.id == "voice-prompt":
        # Social friction increases — guest may not want to refuse aloud
        friction = FrictionEstimate(
            cognitive=friction.cognitive,
            motor=friction.motor,
            social=min(1.0, friction.social + 0.2),
            temporal=friction.temporal,
            prerequisite=friction.prerequisite,
        )

    # Child without guardian — operator-mediated is the only safe option
    if guest.is_child and not guest.guardian_present:
        if channel.id != "operator-mediated":
            return ChannelOffer(
                channel=channel,
                friction=friction,
                available=False,
                reason="Child without guardian — only operator-mediated consent is valid",
            )

    return ChannelOffer(channel=channel, friction=friction, available=True)


def build_channel_menu(
    channels: list[ConsentChannel] | None = None,
    guest: GuestContext | None = None,
) -> ChannelMenu:
    """Build the consent channel menu for a guest.

    Returns all channels assessed for availability and sorted by friction.
    The guest self-selects from available options.
    """
    ch_list = channels if channels is not None else default_channels()
    ctx = guest or GuestContext()

    offers = [assess_channel(c, ctx) for c in ch_list]

    # Sort: available first, then by friction total
    available = [o for o in offers if o.available]
    unavailable = [o for o in offers if not o.available]
    available.sort(key=lambda o: o.friction.total)

    sufficient = len(available) > 0
    reason = ""
    if not sufficient:
        reason = (
            "No consent channels available for this guest. "
            "Operator must be alerted. System will curtail all "
            "person-adjacent data collection."
        )

    return ChannelMenu(
        offers=tuple(available + unavailable),
        sufficient=sufficient,
        insufficiency_reason=reason,
    )


def check_channel_sufficiency(
    channels: list[ConsentChannel] | None = None,
) -> tuple[bool, list[str]]:
    """Test whether the channel set covers all capability dimensions.

    Requirements:
    1. At least one channel must exist
    2. For each capability dimension, at least one channel must NOT require it

    Returns (sufficient, list of uncovered dimensions).
    """
    ch_list = channels if channels is not None else default_channels()

    if not ch_list:
        return False, sorted(CAPABILITY_DIMENSIONS)

    uncovered: list[str] = []

    for dim in sorted(CAPABILITY_DIMENSIONS):
        # Is there at least one channel that doesn't require this capability?
        has_fallback = any(dim not in c.preconditions for c in ch_list)
        if not has_fallback:
            uncovered.append(dim)

    return len(uncovered) == 0, uncovered
