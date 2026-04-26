"""Awareness digest at mode-shift trigger.

Per cc-task ``awareness-voice-digest-mode-shift`` (WSJF 5.5):
daimonion reads a condensed ``## Awareness`` section from the
operator's current daily note ONLY at trigger boundaries — when the
working mode flips (research ↔ rnd ↔ fortress) OR stimmung crosses a
regulation threshold. NOT on a clock schedule. Scheduled summaries
imply operator monitoring; mode-shift is already an operator-context-
shift, so reading at that boundary is ambient by definition (drop §3
fresh pattern #1).

Constitutional posture:
- ``feedback_full_automation_or_no_engagement`` — trigger is ambient,
  never a "read me the digest" voice command.
- ``feedback_hapax_authors_programmes`` — daimonion synthesizes the
  read prose; not a fixed template.
- ``feedback_scientific_register`` — the read is brief, factual,
  scientific register only.

This module ships the **pure trigger logic + section extraction +
LLM-condense**. The watcher loop (subscribing to working-mode + stimmung
event streams) and the voice playback (handing the prose to daimonion's
TTS chain) are deferred to a follow-up PR that wires this into
``run_loops_aux`` alongside the existing impingement consumer.

The split is deliberate: pure logic is testable end-to-end without
spinning up an async event loop, and the voice integration touches the
hot CPAL path which warrants its own review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# Regulation buckets for stimmung crossings. The "value" component of
# stimmung lives in ``[0.0, 1.0]``; the canonical buckets coarsen this
# into three meaningful regions for trigger purposes.
StimmungBucket = Literal["low_load", "nominal", "high_load"]

# Bucket boundaries — chosen to match the existing
# ``stimmung_ceiling`` thresholds in ``GainController``.
_LOW_LOAD_CEILING = 0.33
_HIGH_LOAD_FLOOR = 0.66


def stimmung_bucket(value: float) -> StimmungBucket:
    """Classify a stimmung value into one of three regulation buckets.

    Boundaries are inclusive of the lower edge: ``0.33 → nominal``,
    ``0.66 → high_load``. Out-of-range inputs clamp to nearest bucket.
    """
    if value < _LOW_LOAD_CEILING:
        return "low_load"
    if value < _HIGH_LOAD_FLOOR:
        return "nominal"
    return "high_load"


@dataclass
class AwarenessDigestState:
    """Per-process state — last-seen mode + stimmung bucket.

    Mutated only via :func:`update_for_event` so trigger detection
    and state advancement stay coupled. Initial state is ``None`` for
    both fields; the first event of either kind always triggers.
    """

    last_mode: str | None = None
    last_stimmung_bucket: StimmungBucket | None = None


def is_mode_shift(state: AwarenessDigestState, new_mode: str) -> bool:
    """``True`` iff ``new_mode`` differs from the last seen mode.

    The first event of any mode ever (``last_mode is None``) counts as a
    shift — daimonion has no prior context to compare against and the
    digest read at boot is informative.
    """
    return state.last_mode != new_mode


def is_stimmung_threshold_cross(state: AwarenessDigestState, new_value: float) -> bool:
    """``True`` iff bucketing ``new_value`` differs from the last bucket."""
    new_bucket = stimmung_bucket(new_value)
    return state.last_stimmung_bucket != new_bucket


def update_for_event(
    state: AwarenessDigestState,
    *,
    mode: str | None = None,
    stimmung_value: float | None = None,
) -> bool:
    """Advance ``state`` for one event; return ``True`` if it's a trigger.

    Exactly one of ``mode`` / ``stimmung_value`` should be set; passing
    both is allowed but only the mode comparison is consulted (mode
    shifts are coarser-grained and dominate stimmung crossings when
    they coincide).
    """
    if mode is not None:
        triggered = is_mode_shift(state, mode)
        state.last_mode = mode
        return triggered
    if stimmung_value is not None:
        triggered = is_stimmung_threshold_cross(state, stimmung_value)
        state.last_stimmung_bucket = stimmung_bucket(stimmung_value)
        return triggered
    return False


# ── Section extraction ────────────────────────────────────────────────


_SECTION_HEADER_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def extract_awareness_section(daily_note: str) -> str:
    """Return the body of the ``## Awareness`` section, or empty string.

    Section body runs from the line AFTER the matched header up to (but
    not including) the next ``## ...`` header at the same depth, or end
    of file. Whitespace is preserved.
    """
    matches = list(_SECTION_HEADER_RE.finditer(daily_note))
    for i, m in enumerate(matches):
        if m.group(1).strip().lower() == "awareness":
            body_start = m.end() + 1  # skip the header's trailing newline
            body_end = matches[i + 1].start() if i + 1 < len(matches) else len(daily_note)
            return daily_note[body_start:body_end].strip()
    return ""


# ── LLM condense (interface only) ─────────────────────────────────────


CONDENSE_SYSTEM_PROMPT = (
    "You are condensing the operator's awareness section into a single "
    "60-word factual paragraph. Use scientific register: no rhetorical "
    "flourish, no second-person address, no generated coaching language. "
    "Refer to the operator only as 'The Operator', 'Oudepode', "
    "'Oudepode The Operator', or 'OTO' (sticky-per-utterance: pick one "
    "and stay consistent). Output prose only — no headers, no bullets, "
    "no closing remarks. If the source is empty, output the literal "
    "string '(no awareness logged)'."
)


def build_condense_prompt(awareness_section: str) -> list[dict[str, str]]:
    """Compose the messages list for the LLM condense call.

    The actual LLM invocation happens in the follow-up that wires the
    TabbyAPI client (``shared.config.get_litellm_client``) into the
    voice path. This helper is split out so the prompt shape is testable
    in isolation.
    """
    return [
        {"role": "system", "content": CONDENSE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Awareness section:\n\n"
                f"{awareness_section if awareness_section else '(empty)'}\n\n"
                "Condense to one factual paragraph, ≤60 words."
            ),
        },
    ]


# ── Fortress-mode trigger semantics ───────────────────────────────────
#
# Fortress mode is council's third working-mode for studio livestream
# gating. The digest read should adapt:
#
# * Entering fortress: pre-stream last-look — cross_account state +
#   pending refusals.
# * Exiting fortress: post-stream summary — events accumulated during
#   the stream window (refusals deferred, outbound publishes,
#   publishing pipeline state).
# * Within fortress: SUPPRESS all stimmung-driven digests. Daimonion
#   stays silent on awareness while the livestream is live (governed
#   by `feedback_l12_equals_livestream_invariant` and
#   `feedback_consent_latency_obligation` — the daemon must not
#   interrupt the stream's consent flow).
#
# Mode-shift triggers (research↔rnd) land in the base `is_mode_shift`
# helper above; the helpers below are fortress-specific so the watcher
# loop (deferred PR) can branch cleanly.

FORTRESS_MODE = "fortress"


def is_entering_fortress(state: AwarenessDigestState, new_mode: str) -> bool:
    """``True`` iff ``new_mode == 'fortress'`` and prior mode was not.

    Pre-stream last-look fires here. Note that the very first event of
    any session that lands on ``fortress`` (when ``last_mode is None``)
    counts as entering — daimonion has no prior context, so the
    pre-stream digest is informative.
    """
    return new_mode == FORTRESS_MODE and state.last_mode != FORTRESS_MODE


def is_exiting_fortress(state: AwarenessDigestState, new_mode: str) -> bool:
    """``True`` iff prior mode was ``'fortress'`` and ``new_mode`` is not.

    Post-stream summary fires here. Returns ``False`` if there is no
    prior mode (a session that boots in non-fortress mode has nothing
    to summarize).
    """
    return state.last_mode == FORTRESS_MODE and new_mode != FORTRESS_MODE


def is_within_fortress(state: AwarenessDigestState) -> bool:
    """``True`` iff the last observed mode is ``'fortress'``.

    Used by the stimmung-trigger path to suppress within-fortress
    digests. The fortress entry/exit transitions handle their own
    summaries; in-stream stimmung crossings would interrupt the
    livestream consent flow per
    ``feedback_consent_latency_obligation``.
    """
    return state.last_mode == FORTRESS_MODE


def should_emit_stimmung_digest(state: AwarenessDigestState) -> bool:
    """``True`` iff a stimmung-bucket-cross should fire a digest read.

    Returns ``False`` when within fortress mode (livestream gating).
    Other contexts (research, rnd, or pre-first-mode) emit normally.
    """
    return not is_within_fortress(state)


# ── Fortress-mode condense prompts ────────────────────────────────────

# Per the cc-task spec, fortress entry/exit prose is brief (≤40 words),
# factual, no rhetorical valence (per `feedback_scientific_register`).
# These prompts intentionally use the same operator-referent rules and
# scientific register as `CONDENSE_SYSTEM_PROMPT`.

FORTRESS_PRE_STREAM_SYSTEM_PROMPT = (
    "You are condensing the operator's pre-stream context into a single "
    "≤40-word factual paragraph for daimonion to read aloud just before "
    "the livestream goes live. Use scientific register: no rhetorical "
    "flourish, no second-person address, no generated coaching language. "
    "Refer to the operator only as 'The Operator', 'Oudepode', "
    "'Oudepode The Operator', or 'OTO' (sticky-per-utterance: pick one "
    "and stay consistent). Output prose only — no headers, no bullets, "
    "no closing remarks. Focus on cross-account state and pending "
    "refusals — items the operator should know before going live. "
    "If the source is empty, output the literal string '(no pre-stream "
    "context).'"
)


FORTRESS_POST_STREAM_SYSTEM_PROMPT = (
    "You are condensing the operator's post-stream window into a single "
    "≤40-word factual paragraph for daimonion to read aloud just after "
    "the livestream ends. Use scientific register: no rhetorical "
    "flourish, no second-person address, no generated coaching language. "
    "Refer to the operator only as 'The Operator', 'Oudepode', "
    "'Oudepode The Operator', or 'OTO' (sticky-per-utterance: pick one "
    "and stay consistent). Output prose only — no headers, no bullets, "
    "no closing remarks. Focus on events that accumulated during the "
    "fortress window: refusals deferred, outbound publishes, pipeline "
    "state changes. If the source is empty, output the literal string "
    "'(no post-stream events).'"
)


def build_fortress_pre_stream_prompt(context_section: str) -> list[dict[str, str]]:
    """Compose the messages list for the pre-stream condense call.

    ``context_section`` is the assembled cross-account + pending-refusal
    snapshot (the watcher loop assembles this from awareness state).
    Empty input is permitted; the system prompt instructs the model to
    emit the canonical empty-string sentinel.
    """
    return [
        {"role": "system", "content": FORTRESS_PRE_STREAM_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Pre-stream context:\n\n"
                f"{context_section if context_section else '(empty)'}\n\n"
                "Condense to one factual paragraph, ≤40 words."
            ),
        },
    ]


def build_fortress_post_stream_prompt(events_section: str) -> list[dict[str, str]]:
    """Compose the messages list for the post-stream condense call.

    ``events_section`` is the assembled summary of events accumulated
    during the fortress window (refusals deferred, publishes shipped,
    pipeline transitions). Empty input emits the canonical empty-string
    sentinel via the system prompt.
    """
    return [
        {"role": "system", "content": FORTRESS_POST_STREAM_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Post-stream events:\n\n"
                f"{events_section if events_section else '(empty)'}\n\n"
                "Condense to one factual paragraph, ≤40 words."
            ),
        },
    ]
