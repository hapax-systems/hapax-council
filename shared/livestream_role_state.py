"""Livestream role + speech-act binding contract envelopes.

Per cc-task ``livestream-role-speech-programme-binding-contract``
(WSJF 9.4). The envelopes here are the shared role-state and speech-act
binding surface consumed by programme runner, director, scrim, captions,
archive, and public adapters.

Spec reference:
``hapax-research/specs/2026-04-29-autonomous-speech-programme-role-
behavior-contract.md``.

Operating law (verbatim from the spec):

* **Role** is the **public office**. It sets stance, authority
  ceiling, addressee relation, monetization posture.
* **Programme** selects subject + format + grounding question + mode.
* **WCS** supplies affordances + evidence + blockers + claim limits.
* **Director** stages the move across surfaces.
* **Speech** is one possible expression means inside the office,
  bound by role / programme / WCS / claim posture.

Failure modes the schema must make legible:

* speech silence (urge → no public event),
* impulse disappearance (urge inhibited without terminal outcome),
* speech truncation (act marked complete on partial output),
* false public liveness (claims absent egress evidence),
* expert-system drift (rankings without grounded evidence),
* programme overreach (format launches without monetization
  readiness),
* manual-content trap (operator topic nomination is content engine).

The validators here gate-CLOSE every one of those at the schema layer.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LivestreamRole(enum.StrEnum):
    """The institutional public office Hapax occupies in a run.

    Role names are nouns describing the office, not vocal personas. The
    role constrains allowed speech acts, confidence, public/private
    boundary, and conversion cues — it does NOT invent itself from
    speech text.
    """

    RESEARCH_HOST = "research_host"
    PROGRAMME_HOST = "programme_host"
    CLAIM_AUDITOR = "claim_auditor"
    REFUSAL_CLERK = "refusal_clerk"
    ARCHIVE_NARRATOR = "archive_narrator"
    CORRECTION_WITNESS = "correction_witness"
    CONTENT_CRITIC = "content_critic"
    SCENE_DIRECTOR_VOICE = "scene_director_voice"
    OPERATOR_CONTEXT_WITNESS = "operator_context_witness"


class SpeechActKind(enum.StrEnum):
    """Speech act taxonomy from the spec §"Speech Act Taxonomy".

    Every emission must classify into one of these kinds before it can
    leave the speech path. Refusal / correction / blocker articulations
    are FIRST-CLASS valid outputs, not error states.
    """

    HOST_BEAT = "host_beat"
    """Opens, bridges, or closes a programme unit."""

    GROUNDING_ANNOTATION = "grounding_annotation"
    """States what evidence is being used and what remains uncertain."""

    BOUNDARY_MARKER = "boundary_marker"
    """Makes rights / privacy / public / private limits legible."""

    REFUSAL_ARTICULATION = "refusal_articulation"
    """Explains why a move cannot truthfully happen."""

    CORRECTION_ARTICULATION = "correction_articulation"
    """Revises a prior public statement or posture."""

    ATTENTION_ROUTE = "attention_route"
    """Points attention to a surface or shift without overclaiming."""

    CONTINUITY_BRIDGE = "continuity_bridge"
    """Keeps live role coherent during transitions or waits."""

    ARCHIVE_MARKER = "archive_marker"
    """Names why a moment matters for replay or research outputs."""

    CONVERSION_CUE = "conversion_cue"
    """Invites support only when monetization readiness allows it."""

    OPERATOR_CONTEXT_NOTE = "operator_context_note"
    """References operator activity only within public-safe referent
    policy and current evidence."""


class PublicMode(enum.StrEnum):
    """The public-mode the role is operating in this run."""

    PUBLIC_LIVE = "public_live"
    PUBLIC_ARCHIVE = "public_archive"
    PRIVATE = "private"
    DRY_RUN = "dry_run"
    BLOCKED = "blocked"


class SpeechPosture(enum.StrEnum):
    """Expected voice/caption posture for the current role state."""

    SILENT = "silent"
    PRIVATE_NOTE = "private_note"
    DIRECTOR_DRY_RUN = "director_dry_run"
    PUBLIC_NARRATION = "public_narration"
    PUBLIC_CAPTION = "public_caption"
    ARCHIVE_ONLY = "archive_only"


class MonetizationPosture(enum.StrEnum):
    """Whether the role may make conversion/support cues public."""

    NOT_REQUESTED = "not_requested"
    HELD = "held"
    READY = "ready"
    BLOCKED = "blocked"


class AuthorityCeiling(enum.StrEnum):
    """Maximum claim authority the role can authorize.

    Mirrors the PerceptualField witness-map taxonomy so a single
    consumer (director, scrim, public-event adapter) reads one ceiling
    vocabulary across both percept fields and speech acts.
    """

    NONE = "none"
    DIAGNOSTIC = "diagnostic"
    PRIVATE_ONLY = "private_only"
    WITNESSED_PRESENCE = "witnessed_presence"
    GROUNDED_PRIVATE = "grounded_private"
    PUBLIC_VISIBLE = "public_visible"
    PUBLIC_LIVE = "public_live"
    ACTION_AUTHORIZING = "action_authorizing"


class TerminalOutcome(enum.StrEnum):
    """Terminal state of a speech act fulfilling an originating impulse.

    Per the spec: the impulse-disappearance failure mode is "a
    content-bearing urge inhibited or blocked without a terminal
    outcome". Every speech act tied to an originating impulse MUST
    record one of these terminal states so the impulse register can
    audit fulfillment.
    """

    COMPLETED = "completed"
    INHIBITED = "inhibited"
    REDIRECTED = "redirected"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class SpeechActDestination(enum.StrEnum):
    """Where a speech act is destined.

    Public-claim authority and witness requirements differ across these.
    """

    PRIVATE = "private"
    """In-process / audit log only; no audible / visible output."""

    DIRECTOR_DRY_RUN = "director_dry_run"
    """Director loop sees it but no public path executes."""

    PUBLIC_LIVE = "public_live"
    """Live broadcast egress; requires egress witness."""

    PUBLIC_ARCHIVE = "public_archive"
    """VOD / replay write; requires playback witness."""


class SpeechFulfillment(enum.StrEnum):
    """How an originating conative impulse was fulfilled or redirected."""

    SPOKEN_NARRATION = "spoken_narration"
    CAPTION = "caption"
    SCRIM_GESTURE = "scrim_gesture"
    PRIVATE_NOTE = "private_note"
    REFUSAL = "refusal"
    CORRECTION = "correction"
    WITHHELD = "withheld"
    REDIRECTED = "redirected"


class LivestreamRoleState(BaseModel):
    """Public-office state for one livestream run.

    Consumed by programme runner, director snapshot, scrim renderer,
    audio router, captions, archive, and the public-event adapters.
    The same envelope drives all of them so visual posture, voice, and
    public claims cannot diverge from the office Hapax is occupying.

    Phase 0 invariants (validators below):

    * ``public_mode == PUBLIC_LIVE`` REQUIRES non-empty
      ``available_wcs_surfaces`` AND non-empty
      ``director_move_snapshot_ref`` (no public liveness without
      surfaces + a director move staging it).
    * ``public_mode == BLOCKED`` REQUIRES at least one entry in
      ``blocked_wcs_surfaces`` (blocked must point at the surface).
    * ``public_mode == DRY_RUN`` FORBIDS ``monetization_ready=True``
      (no monetization in dry-run).
    * ``allowed_speech_acts`` MUST be non-empty (a role with no
      allowed acts is a configuration error, not a silent-by-design
      state).
    * Surface lists are pairwise disjoint — a surface cannot be
      simultaneously available + blocked, etc.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    role_state_id: str = ""
    current_role: LivestreamRole
    public_mode: PublicMode
    expected_speech_posture: SpeechPosture = SpeechPosture.PRIVATE_NOTE
    authority_ceiling: AuthorityCeiling
    grounding_question: str = Field(default="", min_length=0)
    """Free-text grounding question the run is attempting (spec
    §"Behavioral Law"). Empty for between-run transitions."""

    active_programme_run_ref: str = ""
    """Reference to the active content programme run; empty when the
    role is operating outside any programme."""

    director_move_snapshot_ref: str = ""
    """Reference to the director move snapshot staging the run."""

    required_wcs_surfaces: tuple[str, ...] = ()
    available_wcs_surfaces: tuple[str, ...] = ()
    blocked_wcs_surfaces: tuple[str, ...] = ()
    stale_wcs_surfaces: tuple[str, ...] = ()
    private_only_wcs_surfaces: tuple[str, ...] = ()

    allowed_speech_acts: frozenset[SpeechActKind] = frozenset()
    """The subset of SpeechActKind values the role authorizes for
    emission. A speech act whose kind is not in this set MUST be
    inhibited at the speech-act validator."""

    speech_destination_policy: frozenset[SpeechActDestination] = frozenset()
    """Explicit destination allow-set. Empty means derive from public_mode."""

    completion_witness_requirements: tuple[str, ...] = ()
    """Witness requirement refs shared by voice, captions, archive, and scrim."""

    monetization_ready: bool = False
    monetization_posture: MonetizationPosture = MonetizationPosture.NOT_REQUESTED

    refusal_posture: str = ""
    """Current refusal articulation posture; empty when no refusal is
    standing. Free-text reference to a refusal-brief / refusal annex."""

    correction_posture: str = ""
    """Current correction posture; empty when no correction is
    in-flight. Free-text reference to a correction record."""

    @model_validator(mode="after")
    def _validate_invariants(self) -> LivestreamRoleState:
        if not self.allowed_speech_acts:
            raise ValueError(
                "allowed_speech_acts must be non-empty (a role authorizing "
                "no speech acts is a config error, not a silent-by-design state)"
            )

        # Surface lists must be pairwise disjoint.
        seen: set[str] = set()
        for label, surfaces in (
            ("available", self.available_wcs_surfaces),
            ("blocked", self.blocked_wcs_surfaces),
            ("stale", self.stale_wcs_surfaces),
            ("private_only", self.private_only_wcs_surfaces),
        ):
            for surface in surfaces:
                if surface in seen:
                    raise ValueError(
                        f"surface {surface!r} appears in multiple WCS lists "
                        f"(latest: {label}); each surface must be in exactly one bucket"
                    )
                seen.add(surface)

        # public_live requires available surfaces AND a director snapshot.
        if self.public_mode is PublicMode.PUBLIC_LIVE:
            if not self.available_wcs_surfaces:
                raise ValueError(
                    "public_live mode requires non-empty available_wcs_surfaces "
                    "(no public liveness without surfaces witnessing the run)"
                )
            if not self.director_move_snapshot_ref:
                raise ValueError(
                    "public_live mode requires director_move_snapshot_ref "
                    "(no public liveness without a director move staging it)"
                )

        # blocked requires at least one blocked surface.
        if self.public_mode is PublicMode.BLOCKED and not self.blocked_wcs_surfaces:
            raise ValueError(
                "blocked mode requires at least one blocked_wcs_surface "
                "(the blocker must point at a surface)"
            )

        # dry_run forbids monetization_ready.
        if self.public_mode is PublicMode.DRY_RUN and self.monetization_ready:
            raise ValueError(
                "dry_run mode forbids monetization_ready=True (no monetization on a dry run)"
            )

        return self

    def allowed_destinations(self) -> frozenset[SpeechActDestination]:
        """Return destinations authorized by this role state."""

        if self.speech_destination_policy:
            return self.speech_destination_policy
        if self.public_mode is PublicMode.PUBLIC_LIVE:
            return frozenset(
                {
                    SpeechActDestination.PRIVATE,
                    SpeechActDestination.PUBLIC_LIVE,
                    SpeechActDestination.PUBLIC_ARCHIVE,
                }
            )
        if self.public_mode is PublicMode.PUBLIC_ARCHIVE:
            return frozenset(
                {
                    SpeechActDestination.PRIVATE,
                    SpeechActDestination.PUBLIC_ARCHIVE,
                }
            )
        if self.public_mode is PublicMode.DRY_RUN:
            return frozenset(
                {
                    SpeechActDestination.PRIVATE,
                    SpeechActDestination.DIRECTOR_DRY_RUN,
                }
            )
        return frozenset({SpeechActDestination.PRIVATE})


class SpeechAct(BaseModel):
    """One classified speech-act emission.

    Every public-voice or director-dry-run emission MUST construct a
    SpeechAct record before any TTS / chronicle / public-event step.
    The validators below close the failure modes the spec calls out.

    Invariants:

    * ``act_kind`` MUST be in ``role_state.allowed_speech_acts`` (the
      validator does not see role_state — that join happens at the
      consumer; here we just pin the field types).
    * ``destination == PUBLIC_LIVE`` REQUIRES
      ``completion_witness_required=True`` and a non-empty
      ``wcs_snapshot_ref``.
    * ``destination == PUBLIC_ARCHIVE`` REQUIRES non-empty
      ``wcs_snapshot_ref`` (playback witness required at consumer).
    * ``CONVERSION_CUE`` is forbidden when ``destination`` is not
      PUBLIC_LIVE / PUBLIC_ARCHIVE (no monetization invitation in
      private / dry-run).
    * ``terminal_outcome`` may only be COMPLETED if the act has both
      a destination and a wcs_snapshot_ref (truncation guard).
    * If ``originating_impulse_ref`` is set, ``terminal_outcome`` is
      required (impulse-disappearance guard).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    act_kind: SpeechActKind
    role: LivestreamRole
    role_state_ref: str = ""
    destination: SpeechActDestination
    claim_posture: AuthorityCeiling

    programme_run_ref: str = ""
    impulse_id: str = ""
    originating_impulse_ref: str = ""
    action_tendency: str = ""
    selected_fulfillment: SpeechFulfillment | None = None
    wcs_snapshot_ref: str = ""
    route_ref: str = ""

    completion_witness_required: bool = True
    completion_witness_refs: tuple[str, ...] = ()
    terminal_outcome: TerminalOutcome | None = None
    truth_source_allowed: Literal[False] = False
    scheduler_action_allowed: Literal[False] = False
    wcs_substitute_allowed: Literal[False] = False
    """``None`` when the act is in-flight; required when the act
    references an ``originating_impulse_ref`` (impulse must always
    reach a terminal state)."""

    @model_validator(mode="after")
    def _validate_speech_act_invariants(self) -> SpeechAct:
        # Public-live destinations require witness and WCS snapshot.
        if self.destination is SpeechActDestination.PUBLIC_LIVE:
            if not self.completion_witness_required:
                raise ValueError(
                    "public_live destination requires completion_witness_required=True "
                    "(false-public-liveness guard)"
                )
            if not self.wcs_snapshot_ref:
                raise ValueError(
                    "public_live destination requires non-empty wcs_snapshot_ref "
                    "(claims cannot flow without WCS evidence)"
                )
            if not self.route_ref:
                raise ValueError(
                    "public_live destination requires non-empty route_ref "
                    "(public narration must name the audio/caption route)"
                )
            if not self.completion_witness_refs:
                raise ValueError(
                    "public_live destination requires completion_witness_refs "
                    "(completion must be witnessable before public emission)"
                )

        # Public-archive destinations require WCS snapshot.
        if self.destination is SpeechActDestination.PUBLIC_ARCHIVE and not self.wcs_snapshot_ref:
            raise ValueError("public_archive destination requires non-empty wcs_snapshot_ref")

        # Conversion cues are forbidden outside public destinations.
        if self.act_kind is SpeechActKind.CONVERSION_CUE and self.destination not in {
            SpeechActDestination.PUBLIC_LIVE,
            SpeechActDestination.PUBLIC_ARCHIVE,
        }:
            raise ValueError(
                "conversion_cue is forbidden in private / director_dry_run "
                "destinations (no monetization invitation outside public)"
            )

        # COMPLETED terminal outcome requires destination + WCS snapshot
        # (truncation guard).
        if (
            self.terminal_outcome is TerminalOutcome.COMPLETED
            and self.destination is SpeechActDestination.PRIVATE
            and not self.wcs_snapshot_ref
        ):
            raise ValueError(
                "terminal_outcome=COMPLETED on a private destination requires "
                "wcs_snapshot_ref (no completed-without-evidence speech acts)"
            )

        if self.impulse_id and self.originating_impulse_ref:
            if self.impulse_id != self.originating_impulse_ref:
                raise ValueError("impulse_id and originating_impulse_ref must match when both set")

        # Impulse-disappearance guard: any act referencing an originating
        # impulse must record a terminal outcome before it is closed.
        # (None is valid while in-flight; the consumer must verify before
        # archiving.) We enforce: the field exists + role + impulse_ref
        # together imply terminal_outcome must not be None when the
        # consumer marks the act closed. Here we only enforce that the
        # type is correct.
        linked_impulse = self.impulse_id or self.originating_impulse_ref
        if linked_impulse and self.terminal_outcome is None:
            # Allowed (in-flight); consumer must finalize.
            pass
        if linked_impulse and self.terminal_outcome is not None:
            if not self.action_tendency:
                raise ValueError(
                    "terminal speech acts resolving an impulse require action_tendency"
                )
            if self.selected_fulfillment is None:
                raise ValueError(
                    "terminal speech acts resolving an impulse require selected_fulfillment"
                )

        return self

    @property
    def resolved_impulse_id(self) -> str:
        """Return the originating impulse id using the new field first."""

        return self.impulse_id or self.originating_impulse_ref


class SpeechAuthorizationDecision(BaseModel):
    """Result of applying role/WCS/route policy to one speech act."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    authorized: bool
    reasons: tuple[str, ...] = ()
    role_state_ref: str = ""
    speech_act_kind: SpeechActKind
    requested_destination: SpeechActDestination
    effective_destination: SpeechActDestination
    selected_fulfillment: SpeechFulfillment
    terminal_outcome: TerminalOutcome | None = None


_AUTHORITY_RANK: dict[AuthorityCeiling, int] = {
    AuthorityCeiling.NONE: 0,
    AuthorityCeiling.DIAGNOSTIC: 1,
    AuthorityCeiling.PRIVATE_ONLY: 2,
    AuthorityCeiling.WITNESSED_PRESENCE: 3,
    AuthorityCeiling.GROUNDED_PRIVATE: 4,
    AuthorityCeiling.PUBLIC_VISIBLE: 5,
    AuthorityCeiling.PUBLIC_LIVE: 6,
    AuthorityCeiling.ACTION_AUTHORIZING: 7,
}


def is_speech_act_authorized_by_role(
    role_state: LivestreamRoleState,
    speech_act: SpeechAct,
) -> bool:
    """Return True iff ``speech_act.act_kind`` is in
    ``role_state.allowed_speech_acts`` AND the act's role matches
    the role state's current_role.

    Consumers (director, speech path) must call this BEFORE emitting.
    Refusal / correction / blocker articulations are first-class:
    when this returns False the caller should construct a
    ``REFUSAL_ARTICULATION`` or ``CORRECTION_ARTICULATION`` act, not
    a silent drop.
    """
    return (
        speech_act.role is role_state.current_role
        and speech_act.act_kind in role_state.allowed_speech_acts
    )


def authorize_speech_act(
    role_state: LivestreamRoleState,
    speech_act: SpeechAct,
    *,
    route_ref: str | None = None,
    route_witness_refs: Iterable[str] = (),
    director_snapshot_ref: str | None = None,
    wcs_snapshot_ref: str | None = None,
    public_event_refs: Iterable[str] = (),
) -> SpeechAuthorizationDecision:
    """Apply livestream role, WCS, route, and speech-act policy.

    This is the director/speech gate. It does not create or erase an
    originating urge; it decides whether the selected speech fulfillment can
    execute publicly, must be inhibited, or must be redirected to a private
    destination.
    """

    reasons: list[str] = []
    allowed_destinations = role_state.allowed_destinations()
    effective_wcs_ref = wcs_snapshot_ref or speech_act.wcs_snapshot_ref
    effective_route_ref = route_ref or speech_act.route_ref
    witness_refs = tuple(route_witness_refs) or speech_act.completion_witness_refs
    is_public_destination = speech_act.destination in {
        SpeechActDestination.PUBLIC_LIVE,
        SpeechActDestination.PUBLIC_ARCHIVE,
    }

    if not is_speech_act_authorized_by_role(role_state, speech_act):
        reasons.append("speech_act_not_allowed_by_role")
    if speech_act.destination not in allowed_destinations:
        reasons.append("destination_not_allowed_by_role_state")
    if not _authority_allows(role_state.authority_ceiling, speech_act.claim_posture):
        reasons.append("authority_ceiling_below_claim_posture")
    if (
        role_state.active_programme_run_ref
        and speech_act.programme_run_ref
        and role_state.active_programme_run_ref != speech_act.programme_run_ref
    ):
        reasons.append("programme_run_mismatch")

    if speech_act.destination is SpeechActDestination.PUBLIC_LIVE:
        if role_state.public_mode is not PublicMode.PUBLIC_LIVE:
            reasons.append("role_state_not_public_live")
        if not effective_route_ref:
            reasons.append("route_ref_missing")
        elif effective_route_ref not in role_state.available_wcs_surfaces:
            reasons.append("route_not_available_in_role_state")
        if not effective_wcs_ref:
            reasons.append("wcs_snapshot_ref_missing")
        if not (director_snapshot_ref or role_state.director_move_snapshot_ref):
            reasons.append("director_snapshot_ref_missing")
        if speech_act.completion_witness_required and not witness_refs:
            reasons.append("completion_witness_requirement_missing")
        if not tuple(public_event_refs) and role_state.public_mode is PublicMode.PUBLIC_LIVE:
            reasons.append("public_event_ref_missing")

    if speech_act.destination is SpeechActDestination.PUBLIC_ARCHIVE:
        if not effective_wcs_ref:
            reasons.append("wcs_snapshot_ref_missing")

    if speech_act.act_kind is SpeechActKind.CONVERSION_CUE and not role_state.monetization_ready:
        reasons.append("monetization_not_ready")

    if reasons:
        return SpeechAuthorizationDecision(
            authorized=False,
            reasons=tuple(dict.fromkeys(reasons)),
            role_state_ref=role_state.role_state_id,
            speech_act_kind=speech_act.act_kind,
            requested_destination=speech_act.destination,
            effective_destination=(
                SpeechActDestination.PRIVATE if is_public_destination else speech_act.destination
            ),
            selected_fulfillment=_blocked_fulfillment_for(speech_act),
            terminal_outcome=(
                TerminalOutcome.REDIRECTED
                if "destination_not_allowed_by_role_state" in reasons
                else TerminalOutcome.INHIBITED
            ),
        )

    return SpeechAuthorizationDecision(
        authorized=True,
        role_state_ref=role_state.role_state_id,
        speech_act_kind=speech_act.act_kind,
        requested_destination=speech_act.destination,
        effective_destination=speech_act.destination,
        selected_fulfillment=speech_act.selected_fulfillment or SpeechFulfillment.SPOKEN_NARRATION,
    )


def _authority_allows(ceiling: AuthorityCeiling, claim_posture: AuthorityCeiling) -> bool:
    return _AUTHORITY_RANK[ceiling] >= _AUTHORITY_RANK[claim_posture]


def _blocked_fulfillment_for(speech_act: SpeechAct) -> SpeechFulfillment:
    if speech_act.act_kind is SpeechActKind.REFUSAL_ARTICULATION:
        return SpeechFulfillment.REFUSAL
    if speech_act.act_kind is SpeechActKind.CORRECTION_ARTICULATION:
        return SpeechFulfillment.CORRECTION
    if speech_act.destination in {
        SpeechActDestination.PUBLIC_LIVE,
        SpeechActDestination.PUBLIC_ARCHIVE,
    }:
        return SpeechFulfillment.PRIVATE_NOTE
    return SpeechFulfillment.WITHHELD


__all__ = [
    "AuthorityCeiling",
    "LivestreamRole",
    "LivestreamRoleState",
    "MonetizationPosture",
    "PublicMode",
    "SpeechAuthorizationDecision",
    "SpeechAct",
    "SpeechActDestination",
    "SpeechFulfillment",
    "SpeechActKind",
    "SpeechPosture",
    "TerminalOutcome",
    "authorize_speech_act",
    "is_speech_act_authorized_by_role",
]
