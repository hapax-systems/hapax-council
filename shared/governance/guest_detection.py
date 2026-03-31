"""Guest detection and consent facilitation trigger.

When the system detects a non-operator person (face_count > 1, speaker
not identified as operator), this module:

1. Emits a guest_detected event
2. Checks for existing consent contracts
3. If no contract: builds the channel menu and sends notification
4. If contract exists: allows data flow normally

This is the bridge between the perception layer (detection) and the
governance layer (consent). It does NOT decide what to do with data —
that's ConsentGatedWriter's job. It only ensures consent is offered.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GuestDetectionEvent:
    """Emitted when a non-operator person is detected in the space."""

    timestamp: str
    face_count: int
    speaker_id: str  # "operator", "not_operator", "unknown"
    has_consent: bool  # True if an active contract exists
    contract_id: str | None = None
    channel_menu_sufficient: bool = True


def check_guest_consent(
    person_id: str,
    data_category: str = "audio",
    face_count: int = 2,
) -> GuestDetectionEvent:
    """Check if a detected guest has consent. Build channel menu if not.

    This is the function called by the perception engine or audio processor
    when face_count > 1 or speaker_id != "operator".

    Returns a GuestDetectionEvent with the consent state and channel info.
    """
    now = datetime.now(UTC).isoformat()

    # Check for existing contract
    try:
        from shared.governance.consent import load_contracts

        registry = load_contracts()
        has_consent = registry.contract_check(person_id, data_category)
        contract = registry.get_contract_for(person_id)
        contract_id = contract.id if contract else None
    except Exception:
        has_consent = False
        contract_id = None

    # If no consent, check channel sufficiency
    channel_sufficient = True
    if not has_consent:
        try:
            from shared.governance.consent_channels import (
                GuestContext,
                build_channel_menu,
            )

            menu = build_channel_menu(guest=GuestContext())
            channel_sufficient = menu.sufficient
        except Exception:
            channel_sufficient = False

    return GuestDetectionEvent(
        timestamp=now,
        face_count=face_count,
        speaker_id=person_id,
        has_consent=has_consent,
        contract_id=contract_id,
        channel_menu_sufficient=channel_sufficient,
    )


def notify_guest_detected(
    event: GuestDetectionEvent,
    person_label: str = "Someone",
) -> bool:
    """Send notification to operator about guest detection.

    If the guest has no consent, includes a link to the consent
    creation endpoint. Returns True if notification was sent.
    """
    if event.has_consent:
        return False  # No notification needed

    try:
        from shared.notify import send_notification

        title = f"Guest detected: {person_label}"
        if event.channel_menu_sufficient:
            message = (
                f"{person_label} is in the room. No consent contract found. "
                f"Data collection is curtailed. "
                f"Grant consent: http://localhost:8051/consent/channels"
            )
        else:
            message = (
                f"{person_label} is in the room. No consent channels available. "
                f"Data collection is curtailed. Manual facilitation needed."
            )

        send_notification(
            title=title,
            message=message,
            priority="high",
            tags="warning,bust_in_silhouette",
            click_url="http://localhost:8051/consent/channels",
        )
        log.info("Guest detection notification sent for %s", person_label)
        return True
    except Exception:
        log.debug("Failed to send guest notification", exc_info=True)
        return False
