"""Per-SurfaceKind system prompts for the Ring 2 classifier.

Phase 1 of docs/superpowers/plans/2026-04-20-demonetization-safety-
plan.md §3. The classifier prompts each broadcast surface differently
because the Content-ID / demonetization risk profile is surface-
dependent:

- **TTS**: spoken audio. Content-ID acoustic fingerprinting catches
  music snippets; spoken brand names / copyrighted lyrics are lower
  risk because ContentID's audio matcher rarely fingerprints speech.
  Main concern is graphic language (demonetization, not Content-ID).
- **CAPTIONS**: visible text synced to speech. Lower Content-ID risk,
  higher demonetization (slur filters, brand-name checks).
- **OVERLAY**: persistent visible text (tickers, zone content). Same
  as captions but longer on-screen → higher weight on brand names.
- **WARD**: visual asset (image, video, shader). Same risk as
  image_search catalog — Content-ID fingerprint on the visual itself.
- **CHRONICLE, NOTIFICATION, LOG**: internal surfaces. Default-pass;
  classifier skipped entirely. If a caller ever routes them through
  the classifier it returns a low-risk verdict without calling an LLM.

The prompts enforce a strict JSON-object output contract so the
parser (`Ring2Classifier._parse_verdict`) never has to guess shape.
Examples-in-prompt anchor the model to the catalog's own risk-level
definitions so the classifier agrees with Ring 1 on the clear cases
and only disagrees when the rendered payload reveals a risk the
catalog couldn't foresee.

References:
    - docs/research/2026-04-19-demonetization-safety-design.md §6
    - shared/governance/monetization_safety.py — SurfaceKind,
      RiskAssessment (the output shape)
    - docs/governance/monetization-risk-classification.md — the
      rubric each prompt references
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, Field

from shared.governance.monetization_safety import SurfaceKind

# Literal risk levels the classifier is allowed to return. Mirrors
# ``MonetizationRisk`` from ``shared.affordance`` but re-declared here
# so the prompt module has no circular import concern.
_VALID_RISKS: Final[tuple[str, ...]] = ("none", "low", "medium", "high")


class Ring2Verdict(BaseModel):
    """Pydantic shape the classifier's LLM response must parse into.

    This is the classifier's wire contract — the JSON the LLM emits
    is validated against this model before being translated to a
    ``RiskAssessment``. Failures raise ``ClassifierParseError`` in
    the classifier's wrapper.
    """

    allowed: bool = Field(
        description="True if the rendered payload is safe to broadcast on this surface."
    )
    risk: str = Field(description="One of: none, low, medium, high. High = block unconditionally.")
    reason: str = Field(description="One-sentence rationale for the verdict.")

    def to_assessment_kwargs(self) -> dict[str, object]:
        """Return kwargs for ``RiskAssessment`` construction."""
        return {"allowed": self.allowed, "risk": self.risk, "reason": self.reason}


# ── Surface-specific prompts ───────────────────────────────────────────

_COMMON_RUBRIC = """\
Risk rubric (matches the capability-catalog annotation):

- `none`: nothing externally-originated; zero demonetization signal.
- `low`: externally-originated but content is permissively-licensed
  (e.g. CC-BY-SA) or non-copyrightable (factual statements, weather,
  short encyclopedic excerpts). Safe for broadcast with standard
  attribution hygiene.
- `medium`: third-party content whose broadcast could trigger brand-
  mention demonetization, political-content demonetization, or which
  contains brand-names / copyrighted titles in a way that warrants a
  Programme opt-in but not an unconditional block.
- `high`: Content-ID fingerprint risk (music clips, commercial video
  snippets, copyrighted imagery), graphic violence / adult content,
  slurs, or any payload that on its face would violate YouTube's
  monetization policies. High-risk verdicts MUST block the payload.

Respond with a strict JSON object and nothing else:
{"allowed": bool, "risk": "none"|"low"|"medium"|"high", "reason": "one sentence"}

Default toward the stricter classification if uncertain. A false
positive (blocking something safe) is cheaper than a false negative
(admitting something that demonetizes the stream).
"""

TTS_PROMPT = f"""\
You are a monetization-risk classifier for spoken text destined for
YouTube livestream audio. Your job is to judge whether the given
rendered text is safe to READ ALOUD on a monetized livestream.

{_COMMON_RUBRIC}

TTS-specific notes:
- Brand-name spoken once in context is generally `low`. Repeated or
  endorsement-framed brand mention is `medium`.
- Song lyrics or copyrighted poetry read aloud is `high` — Content-ID
  can fingerprint even short lyric quotations.
- Profanity is `medium` at most for YouTube's "limited ads" bracket
  unless graphic / slur-adjacent which is `high`.
- Factual encyclopedic statement (e.g. Wikipedia paraphrase) is
  `low` or `none` depending on whether attribution is needed.
"""

CAPTIONS_PROMPT = f"""\
You are a monetization-risk classifier for closed-caption text on a
YouTube livestream. Captions are the text of what is spoken.

{_COMMON_RUBRIC}

Caption-specific notes:
- Same risk profile as TTS for the spoken source material.
- On-screen brand-name text is weighted slightly higher than brand-
  name audio because text is more easily scraped by advertiser
  filters. A borderline brand mention in TTS might be `low`; the
  same text in captions is often `medium`.
- Slurs / graphic language in captions is `high` — the visible form
  is what triggers strict filters.
"""

OVERLAY_PROMPT = f"""\
You are a monetization-risk classifier for persistent on-screen text
overlays on a YouTube livestream (tickers, zone text, chat displays).

{_COMMON_RUBRIC}

Overlay-specific notes:
- Overlays are PERSISTENT — unlike TTS where a risky phrase passes
  in 2 seconds, an overlay can hang on screen for a minute. Weigh
  brand mentions and borderline content one level stricter than you
  would for TTS.
- Third-party screen-names, comments, or unfiltered chat text
  surfaced as overlays are `medium` by default (unknown provenance)
  and `high` if the payload contains slurs, doxxing, or graphic
  language.
- Hapax-authored overlay text (imagination, daily-note quotes) is
  `none` unless it quotes copyrighted material.
"""

WARD_PROMPT = f"""\
You are a monetization-risk classifier for visual assets (images,
video snippets, procedural shaders) destined for a YouTube
livestream ward / surface.

{_COMMON_RUBRIC}

Ward-specific notes:
- Third-party image / video content is `high` by default — Content-
  ID can fingerprint commercial imagery and trailer clips.
- Operator-photographed studio content (cameras, vinyl album art
  photographed by the operator) is `low`-`medium` depending on
  whether the photographed subject is itself copyrighted (e.g. a
  vinyl cover is `medium` — fair-use photo but subject is protected
  cover art).
- Procedural / generative shader content (reverie, HARDM, HOMAGE
  surfaces) authored by Hapax is `none`.
- Screen-captures of third-party video (YouTube embeds, streaming
  services) are `high` — both Content-ID and Terms-of-Service risk.
"""


# Map SurfaceKind → prompt. Internal surfaces (CHRONICLE, NOTIFICATION,
# LOG) are not in the map — callers check ``SURFACE_IS_BROADCAST``
# before invoking the classifier at all.
_PROMPTS_BY_SURFACE: Final[dict[SurfaceKind, str]] = {
    SurfaceKind.TTS: TTS_PROMPT,
    SurfaceKind.CAPTIONS: CAPTIONS_PROMPT,
    SurfaceKind.OVERLAY: OVERLAY_PROMPT,
    SurfaceKind.WARD: WARD_PROMPT,
}


# Broadcast surfaces — Ring 2 classification actually runs. Internal
# surfaces default-pass at the classifier boundary with no LLM call.
SURFACE_IS_BROADCAST: Final[frozenset[SurfaceKind]] = frozenset(
    {SurfaceKind.TTS, SurfaceKind.CAPTIONS, SurfaceKind.OVERLAY, SurfaceKind.WARD}
)


def prompt_for_surface(surface: SurfaceKind) -> str:
    """Return the system prompt for ``surface``.

    Raises ``KeyError`` when called on a non-broadcast surface — the
    caller should have filtered via ``SURFACE_IS_BROADCAST`` first.
    """
    return _PROMPTS_BY_SURFACE[surface]


def is_broadcast_surface(surface: SurfaceKind) -> bool:
    """True when Ring 2 actually runs for ``surface``.

    Internal surfaces (``CHRONICLE``, ``NOTIFICATION``, ``LOG``) are
    considered operator-internal and skip classification entirely.
    """
    return surface in SURFACE_IS_BROADCAST


def format_user_prompt(capability_name: str, rendered_payload: object) -> str:
    """Build the per-call user message.

    The capability name anchors the LLM in the catalog's risk
    annotation (so it rarely disagrees with Ring 1 except on payload
    details Ring 1 can't see). The rendered payload is the thing
    actually being classified.
    """
    # Render payloads deterministically — `str()` is fine for strings
    # (the common case). For dict payloads (structured sources), the
    # caller can pre-format; we don't introspect here.
    rendered = str(rendered_payload) if rendered_payload is not None else "(empty)"
    return (
        f"capability: {capability_name}\n"
        f"rendered_payload:\n"
        f"---\n"
        f"{rendered}\n"
        f"---\n"
        f"Classify this payload. Return JSON verdict only."
    )


__all__ = [
    "CAPTIONS_PROMPT",
    "OVERLAY_PROMPT",
    "Ring2Verdict",
    "SURFACE_IS_BROADCAST",
    "TTS_PROMPT",
    "WARD_PROMPT",
    "format_user_prompt",
    "is_broadcast_surface",
    "prompt_for_surface",
]
