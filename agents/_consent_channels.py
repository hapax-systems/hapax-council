"""agents/_consent_channels.py — Shim for shared.governance.consent_channels.

Re-exports consent channel types during shared/ dissolution.
Will be replaced with vendored code when shared/ is deleted (phase 3.8).
"""

from shared.governance.consent_channels import (  # noqa: F401
    CAPABILITY_DIMENSIONS,
    ChannelMenu,
    ChannelOffer,
    ConsentChannel,
    FrictionEstimate,
    GuestContext,
    Modality,
    assess_channel,
    build_channel_menu,
    check_channel_sufficiency,
    default_channels,
)
