"""Non-formal operator referent picker.

Directive 2026-04-24: in non-formal contexts (livestream narration, voice
commentary, captions, social-surface posts, YouTube metadata, chat
attribution of operator utterances), the operator is referred to
exclusively by one of four equally-weighted referents. The legal name
is reserved for formal-address-required contexts (consent contracts,
axiom precedents, persona partner-in-conversation declaration, git
author metadata).

Governance: ``axioms/implications/non-formal-referent-policy.yaml``
(``su-non-formal-referent-001``, tier T1, enforcement review).

Regime: sticky-per-utterance. One referent per director LLM call / per
narration construction. Caller seeds the picker with a stable id
(tick id, VOD segment id, utterance id); same seed → same referent so
a single tick's prompt + output stay internally consistent.
"""

from __future__ import annotations

import hashlib
import random

REFERENTS: tuple[str, ...] = (
    "Oudepode",
    "Oudepode The Operator",
    "OTO",
)


class OperatorReferentPicker:
    """Equal-weighted picker over the four ratified operator referents."""

    @staticmethod
    def pick(seed: str | None = None) -> str:
        """Return one referent. Deterministic when ``seed`` is provided.

        ``seed=None`` uses ``random.choice`` — fully stochastic, suitable
        for one-off callers that do not need per-call consistency.

        ``seed`` is hashed with SHA-256 and indexed modulo 4 so the same
        seed string always resolves to the same referent across Python
        processes and host restarts.
        """
        if seed is None:
            return random.choice(REFERENTS)
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        idx = int(digest, 16) % len(REFERENTS)
        return REFERENTS[idx]

    @staticmethod
    def pick_for_tick(tick_id: int) -> str:
        """Seed from a director tick id. Sticky-per-tick."""
        return OperatorReferentPicker.pick(f"director-tick-{tick_id}")

    @staticmethod
    def pick_for_vod_segment(segment_id: str) -> str:
        """Seed from a VOD segment id (used by ytb-007 orchestrator).

        Every VOD gets one referent for its full 11h span — aligns the
        per-VOD SEO metadata with the per-utterance narration that
        happens inside the segment.
        """
        return OperatorReferentPicker.pick(f"vod-segment-{segment_id}")
