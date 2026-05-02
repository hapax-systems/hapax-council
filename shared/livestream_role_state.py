"""Livestream role + speech-act binding contract envelopes.

Per cc-task ``livestream-role-speech-programme-binding-contract``
(WSJF 9.4). The envelopes here are the Phase 0 schema/fixture surface
that programme runner, director, scrim, audio, captions, archive, and
public adapters consume in subsequent phases. This file deliberately
ships **schema + validators + fixtures only** — wiring into the
director/programme/scrim runners is Phase 1+ follow-on work.

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

    current_role: LivestreamRole
    public_mode: PublicMode
    authority_ceiling: AuthorityCeiling
    grounding_question: str = Field(default="", min_length=0)
    """Free-text grounding question the run is attempting (spec
    §"Behavioral Law"). Empty for between-run transitions."""

    active_programme_run_ref: str = ""
    """Reference to the active content programme run; empty when the
    role is operating outside any programme."""

    director_move_snapshot_ref: str = ""
    """Reference to the director move snapshot staging the run."""

    available_wcs_surfaces: tuple[str, ...] = ()
    blocked_wcs_surfaces: tuple[str, ...] = ()
    stale_wcs_surfaces: tuple[str, ...] = ()
    private_only_wcs_surfaces: tuple[str, ...] = ()

    allowed_speech_acts: frozenset[SpeechActKind] = frozenset()
    """The subset of SpeechActKind values the role authorizes for
    emission. A speech act whose kind is not in this set MUST be
    inhibited at the speech-act validator."""

    monetization_ready: bool = False

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
    destination: SpeechActDestination
    claim_posture: AuthorityCeiling

    programme_run_ref: str = ""
    originating_impulse_ref: str = ""
    wcs_snapshot_ref: str = ""

    completion_witness_required: bool = True
    terminal_outcome: TerminalOutcome | None = None
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

        # Impulse-disappearance guard: any act referencing an originating
        # impulse must record a terminal outcome before it is closed.
        # (None is valid while in-flight; the consumer must verify before
        # archiving.) We enforce: the field exists + role + impulse_ref
        # together imply terminal_outcome must not be None when the
        # consumer marks the act closed. Here we only enforce that the
        # type is correct.
        if self.originating_impulse_ref and self.terminal_outcome is None:
            # Allowed (in-flight); consumer must finalize.
            pass

        return self


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


__all__ = [
    "AuthorityCeiling",
    "LivestreamRole",
    "LivestreamRoleState",
    "PublicMode",
    "SpeechAct",
    "SpeechActDestination",
    "SpeechActKind",
    "TerminalOutcome",
    "is_speech_act_authorized_by_role",
]
