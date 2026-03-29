"""Consent identity resolution — linking principals to contracts.

Solves the enrollment paradox: the system needs consent to identify
someone, but needs to identify them to check consent.

Resolution:
1. First visit: anonymous detection → consent offering → grant
2. On grant: enroll voice embedding (consent enables enrollment)
3. Subsequent visits: identify speaker → look up contract → seamless

Also handles:
- Multiple guests (per-speaker tracking)
- Children (age-unknown default to maximum curtailment)
- Re-entry (existing contract → no re-prompt)
- Retroactive processing of curtailed segments after consent grant
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

ENROLLMENT_DIR = Path.home() / ".local" / "share" / "hapax-daimonion" / "speaker-embeddings"


@dataclass(frozen=True)
class GuestIdentity:
    """Resolved identity for a detected guest."""

    person_id: str  # "wife", "guest-1", "unknown"
    has_contract: bool
    contract_scope: frozenset[str] = frozenset()
    confidence: float = 0.0
    source: str = ""  # "speaker_id" | "operator_assigned" | "unknown"


@dataclass
class GuestTracker:
    """Tracks multiple guests across a session.

    Each detected non-operator speaker gets a slot. As speakers are
    identified (via enrollment or operator assignment), slots are
    linked to person IDs and contract states.
    """

    _guests: dict[str, GuestIdentity] = field(default_factory=dict)
    _pending_enrollment: list[tuple[str, np.ndarray]] = field(default_factory=list)

    @property
    def guest_count(self) -> int:
        return len(self._guests)

    @property
    def all_consented(self) -> bool:
        """True if every tracked guest has an active contract."""
        if not self._guests:
            return True  # no guests = no consent needed
        return all(g.has_contract for g in self._guests.values())

    @property
    def any_pending(self) -> bool:
        """True if any guest lacks a contract."""
        return any(not g.has_contract for g in self._guests.values())

    @property
    def unconsented_guests(self) -> list[str]:
        """Person IDs of guests without contracts."""
        return [pid for pid, g in self._guests.items() if not g.has_contract]

    def add_or_update(self, identity: GuestIdentity) -> None:
        """Add a new guest or update an existing one."""
        self._guests[identity.person_id] = identity

    def get(self, person_id: str) -> GuestIdentity | None:
        return self._guests.get(person_id)

    def remove(self, person_id: str) -> None:
        self._guests.pop(person_id, None)

    def clear(self) -> None:
        self._guests.clear()
        self._pending_enrollment.clear()

    def queue_enrollment(self, person_id: str, embedding: np.ndarray) -> None:
        """Queue a voice embedding for enrollment after consent is granted."""
        self._pending_enrollment.append((person_id, embedding))

    def pop_pending_enrollments(self) -> list[tuple[str, np.ndarray]]:
        """Pop all pending enrollments (called after consent grant)."""
        pending = list(self._pending_enrollment)
        self._pending_enrollment.clear()
        return pending


def resolve_guest_identity(
    speaker_label: str,
    confidence: float = 0.0,
) -> GuestIdentity:
    """Resolve a detected speaker to a guest identity.

    Checks ConsentRegistry for an existing contract. If found,
    the guest is identified and no consent flow is needed.

    Args:
        speaker_label: From SpeakerIdentifier ("operator", "not_operator", "uncertain")
                       or an enrolled person_id ("wife", "guest-1")
        confidence: Speaker ID confidence score
    """
    if speaker_label in ("operator", "operator"):
        return GuestIdentity(
            person_id="operator",
            has_contract=True,  # operator needs no contract
            confidence=confidence,
            source="speaker_id",
        )

    # Check if this speaker has an enrolled identity with a contract
    person_id = speaker_label if speaker_label not in ("not_operator", "uncertain") else "unknown"

    try:
        from shared.governance.consent import load_contracts

        registry = load_contracts()
        contract = registry.get_contract_for(person_id)
        if contract is not None and contract.active:
            return GuestIdentity(
                person_id=person_id,
                has_contract=True,
                contract_scope=contract.scope,
                confidence=confidence,
                source="speaker_id",
            )
    except Exception:
        pass

    return GuestIdentity(
        person_id=person_id,
        has_contract=False,
        confidence=confidence,
        source="speaker_id" if person_id != "unknown" else "unknown",
    )


def enroll_guest_speaker(
    person_id: str,
    embedding: np.ndarray,
    speaker_identifier: object | None = None,
) -> bool:
    """Enroll a guest's voice embedding for future identification.

    Called after consent is granted. Saves the embedding to disk
    so subsequent visits can bypass the consent flow.

    Args:
        person_id: Guest identifier (e.g., "wife")
        embedding: Voice embedding from pyannote
        speaker_identifier: Optional SpeakerIdentifier to update in-memory

    Returns:
        True if enrollment succeeded
    """
    try:
        ENROLLMENT_DIR.mkdir(parents=True, exist_ok=True)
        save_path = ENROLLMENT_DIR / f"{person_id}.npy"

        # Normalize before saving
        norm = np.linalg.norm(embedding)
        if norm > 0:
            normalized = embedding / norm
        else:
            normalized = embedding

        np.save(save_path, normalized)
        log.info("Enrolled guest speaker embedding: %s → %s", person_id, save_path)

        # Update in-memory identifier if available
        if speaker_identifier is not None and hasattr(speaker_identifier, "_enrolled"):
            # For multi-speaker support, we'd need a dict of enrollments
            # For now, this is a single-guest path
            pass

        return True
    except Exception:
        log.error("Failed to enroll guest speaker: %s", person_id, exc_info=True)
        return False


def find_enrolled_guests() -> list[str]:
    """List all enrolled guest person IDs (from saved embeddings)."""
    if not ENROLLMENT_DIR.exists():
        return []
    return [p.stem for p in ENROLLMENT_DIR.glob("*.npy") if p.stem != "operator"]


def process_curtailed_segments(
    guest_first_seen: float,
    person_id: str,
    scope: frozenset[str],
) -> int:
    """Retroactively process FLAC segments from the curtailment window.

    Called after consent is granted. Identifies FLAC segments that
    were recorded during curtailment and marks them for processing
    by the audio processor (with consent label and provenance).

    Args:
        guest_first_seen: Monotonic timestamp when guest was first detected
        person_id: Guest's person ID for the consent contract
        scope: Consented data categories

    Returns:
        Number of segments queued for retroactive processing
    """
    if "audio" not in scope:
        return 0

    raw_dir = Path.home() / "audio-recording" / "raw"
    if not raw_dir.exists():
        return 0

    queued = 0
    for flac in raw_dir.glob("rec-*.flac"):
        try:
            # Check if this segment overlaps with the curtailment window
            if flac.stat().st_mtime >= guest_first_seen:
                # Tag the segment's sidecar with consent metadata
                sidecar = flac.with_suffix(".consent.json")
                import json

                sidecar.write_text(
                    json.dumps(
                        {
                            "person_id": person_id,
                            "scope": sorted(scope),
                            "granted_at": time.time(),
                            "retroactive": True,
                        }
                    )
                )
                queued += 1
                log.info("Tagged segment for retroactive processing: %s", flac.name)
        except Exception:
            pass

    return queued
