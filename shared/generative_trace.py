"""Generative Episode Trace (GET) — observability for Hapax's generative agency.

The pre-review pipeline (plan -> recruit -> compose -> coherence-check -> refine)
emits only OUTCOMES — counts ("gathered 8 sources", "6 beats"), scores
("coherence 1.0"), and the final artifact (or its absence). It discards the
PROCESS: what was actually recruited and whether it mattered, why a topic/role/
angle was chosen, the draft at each pass, the council's findings, which
impingements arose and whether they propagated. That makes Hapax's generative
AGENCY unobservable by construction — we cannot answer whether it recruits well,
decides with reason, iterates truly, argues from a motivated non-anthropomorphic
standpoint, or is simply stumbling.

This module makes the process a first-class, durable, inspectable object. A
``GenerativeEpisodeTrace`` is structured around the question-TYPES it must
answer, so it answers them BY CONSTRUCTION rather than incidentally:

  1. PROCESS      - ordered, timed, costed steps (what it did, what effort)
  2. PROVENANCE   - recruited inputs tagged operative|latent (what informed it)
  3. DECISION     - choice records: inputs, reasoning, alternatives (why this)
  4. ITERATION    - draft versions + feedback + deltas (true iteration vs re-roll)
  5. IMPINGEMENT  - perturbations present + whether they propagated
  6. STANCE       - the actual artifact + a stance assessment (angle, voice, force)
  7. SELF_MODEL   - Hapax's snapshot of its role/goal/standpoint at episode time

One trace per generative episode (per segment). Written as JSON under the prep
dir, consent-labeled (the trace embeds operator-vault-derived material). It is
inspectable post-hoc via ``scripts/inspect-generative-trace.py`` and can later
stream as impingements for Hapax's own self-observation (the DASEIN loop).

DESIGN NOTE — operativity is the hard type. "Operative vs latent" requires an
INFLUENCE signal, not just a list of inputs. For recruited SOURCES this is
directly observable: a source the composer actually CITED (its handle appears in
the segment's ``cited_handles``) is operative; a recruited-but-uncited source is
latent. ``resolve_source_operativity`` computes this. For non-source inputs
(density signals, profile facts, impingements) influence is self-reported in the
decision record and is therefore tagged ``operativity_basis="self-report"`` —
honestly weaker evidence, flagged as such rather than asserted.

Every method is fail-safe: instrumentation must never raise into the generative
path. A broken trace loses observability, not a segment.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger("generative_trace")

SCHEMA_VERSION = 1

# Retention: one trace JSON is written per generative episode. Over a long live
# run these would grow without bound, so flush() prunes the oldest, keeping the
# most recent N (0 disables pruning). Tunable via env.
_TRACE_KEEP = int(os.environ.get("HAPAX_GENERATIVE_TRACE_KEEP", "500"))

Operativity = Literal["operative", "latent", "unknown"]


# ── Typed sub-records (one family per question-type) ──────────────────────────


class ProcessStep(BaseModel):
    """Type 1 — PROCESS. One generative operation, timed and costed."""

    model_config = ConfigDict(extra="ignore")

    name: str  # plan | recruit | compose | coherence_check | refine | council | select
    # Free string (not a Literal) so a new caller state can never raise into the
    # fail-safe recording path. Known states callers emit:
    #   ok | failed | skipped | refused | low | no_change
    status: str = "ok"
    started_at: float = 0.0
    duration_s: float = 0.0
    llm_calls: int = 0
    tool_calls: int = 0
    note: str = ""


class RecruitedInput(BaseModel):
    """Type 2 — PROVENANCE / OPERATIVITY. An input candidate + whether it mattered."""

    model_config = ConfigDict(extra="ignore")

    handle: str  # src:N | vault:... | fact:... | rag:... | impingement:...
    kind: str  # source | profile_fact | density_signal | impingement | episode | reaction
    topic: str = ""
    relevance: float | None = None  # recruiter score when one exists
    summary: str = ""  # short human-readable identity of the input
    operativity: Operativity = "unknown"
    operativity_basis: str = ""  # cited | uncited | self-report | unobserved
    output_link: str = ""  # where it surfaced (beat id / cited handle / decision id)


class DecisionRecord(BaseModel):
    """Type 3 — DECISION. A choice with its grounds and the roads not taken."""

    model_config = ConfigDict(extra="ignore")

    decision: str  # topic | role | angle | beat:<id> | refine_keep_original | ...
    chosen: str
    alternatives: list[str] = Field(default_factory=list)
    inputs_consulted: list[str] = Field(default_factory=list)  # handles
    reasoning: str = ""
    basis: str = "self-report"  # self-report | derived | absent


class DraftVersion(BaseModel):
    """Type 4 — ITERATION. One draft pass + its lineage to the prior pass."""

    model_config = ConfigDict(extra="ignore")

    pass_index: int
    kind: str  # compose | refine
    beats: int = 0
    chars: int = 0
    content: str = ""  # the ACTUAL prose (the thing the pipeline currently discards)
    feedback_in: str = ""  # the feedback that prompted this pass (empty for pass 1)
    delta_from_prev: str = ""  # summary of what changed vs the previous pass
    responded_to_feedback: bool | None = None  # True/False/None(unknown)


class ImpingementRecord(BaseModel):
    """Type 5 — IMPINGEMENT. A perturbation present during the episode."""

    model_config = ConfigDict(extra="ignore")

    source: str
    text: str = ""
    magnitude: float | None = None
    arose_at: float = 0.0
    influenced: bool | None = None
    influence_note: str = ""


class StanceAssessment(BaseModel):
    """Type 6 — STANCE / VOICE. The qualitative character of a draft.

    Dimensions are scored 0.0-1.0 (or None when not assessed). ``evidence`` holds
    a short quote/justification per dimension so the score is auditable, not a
    bare number. This is what lets us answer "motivated angle?",
    "non-anthropomorphic standpoint?", "discursive force?", "stumbling/lost?".
    """

    model_config = ConfigDict(extra="ignore")

    assessed_pass: int = 0
    assessor: str = "heuristic"  # heuristic | council | rubric | operator
    motivated_angle: float | None = None
    non_anthropomorphic_voice: float | None = None
    argumentative_force: float | None = None
    discursive_repertoire: float | None = None
    directedness: float | None = None  # inverse of "stumbling/lost"
    evidence: dict[str, str] = Field(default_factory=dict)
    summary: str = ""


class SelfModelSnapshot(BaseModel):
    """Type 7 — SELF-MODEL / ROLE. Hapax's sense of what it is doing and why."""

    model_config = ConfigDict(extra="ignore")

    role: str = ""
    goal: str = ""  # the narrative_beat / teaching objective driving the episode
    standpoint: str = ""  # the non-anthropomorphic frame in force (envelope/claim floor)
    role_source: str = ""  # where the role-sense came from (planner | aperture | envelope)


# ── The episode trace ─────────────────────────────────────────────────────────


class GenerativeEpisodeTrace(BaseModel):
    """One generative episode (one segment), captured as the process unfolds."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = SCHEMA_VERSION
    episode_id: str
    programme_id: str = ""
    role: str = ""
    topic: str = ""
    created_at: float = Field(default_factory=time.time)
    outcome: str = "in_progress"  # released | refuted | low_coherence | error | in_progress

    process: list[ProcessStep] = Field(default_factory=list)
    recruitment: list[RecruitedInput] = Field(default_factory=list)
    decisions: list[DecisionRecord] = Field(default_factory=list)
    iterations: list[DraftVersion] = Field(default_factory=list)
    impingements: list[ImpingementRecord] = Field(default_factory=list)
    stance: list[StanceAssessment] = Field(default_factory=list)
    self_model: SelfModelSnapshot = Field(default_factory=SelfModelSnapshot)

    # ── recording API (all fail-safe) ─────────────────────────────────────────

    def record_step(self, name: str, **kw: Any) -> None:
        self._safe(lambda: self.process.append(ProcessStep(name=name, **kw)))

    def record_recruitment(self, items: list[dict] | list[RecruitedInput]) -> None:
        def _do() -> None:
            for it in items:
                self.recruitment.append(
                    it if isinstance(it, RecruitedInput) else RecruitedInput(**it)
                )

        self._safe(_do)

    def record_decision(self, decision: str, chosen: str, **kw: Any) -> None:
        self._safe(
            lambda: self.decisions.append(DecisionRecord(decision=decision, chosen=chosen, **kw))
        )

    def record_draft(self, pass_index: int, kind: str, content: str, **kw: Any) -> None:
        def _do() -> None:
            prev = self.iterations[-1].content if self.iterations else ""
            dv = DraftVersion(
                pass_index=pass_index,
                kind=kind,
                content=content,
                beats=kw.pop("beats", content.count("\n\n") + 1 if content else 0),
                chars=len(content or ""),
                **kw,
            )
            if prev and dv.delta_from_prev == "":
                dv.delta_from_prev = _summarize_delta(prev, content)
            self.iterations.append(dv)

        self._safe(_do)

    def record_impingement(self, source: str, **kw: Any) -> None:
        self._safe(lambda: self.impingements.append(ImpingementRecord(source=source, **kw)))

    def record_stance(self, assessment: StanceAssessment | dict) -> None:
        def _do() -> None:
            self.stance.append(
                assessment
                if isinstance(assessment, StanceAssessment)
                else StanceAssessment(**assessment)
            )

        self._safe(_do)

    def set_self_model(self, **kw: Any) -> None:
        self._safe(lambda: setattr(self, "self_model", SelfModelSnapshot(**kw)))

    def resolve_source_operativity(self, cited_handles: list[str]) -> None:
        """After composition: tag each recruited SOURCE operative (cited) or latent
        (recruited-but-uncited). This is the directly-observable influence signal."""

        def _do() -> None:
            cited = {str(h).strip() for h in (cited_handles or [])}
            for inp in self.recruitment:
                if inp.kind != "source":
                    continue
                if inp.handle in cited:
                    inp.operativity, inp.operativity_basis = "operative", "cited"
                    inp.output_link = inp.handle
                else:
                    inp.operativity, inp.operativity_basis = "latent", "uncited"

        self._safe(_do)

    def finish(self, outcome: str) -> None:
        self._safe(lambda: setattr(self, "outcome", outcome))

    def flush(self, prep_dir: Path | str) -> Path | None:
        """Atomically write the trace to ``<prep_dir>/generative-traces/<episode>.json``,
        consent-labeled. Returns the path, or None on failure (never raises)."""
        try:
            out_dir = Path(prep_dir) / "generative-traces"
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"{_safe_name(self.episode_id)}.json"
            payload = self.model_dump(mode="json")
            payload["_consent"] = _consent_value()
            tmp = tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=out_dir,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            )
            with tmp:
                json.dump(payload, tmp, ensure_ascii=False, indent=2)
            os.replace(tmp.name, path)
            _prune_traces(out_dir)
            return path
        except Exception:
            log.warning("generative_trace: flush failed for %s", self.episode_id, exc_info=True)
            return None

    @staticmethod
    def _safe(fn: Any) -> None:
        try:
            fn()
        except Exception:
            log.debug("generative_trace: record failed (non-fatal)", exc_info=True)


# ── helpers ───────────────────────────────────────────────────────────────────


def _prune_traces(out_dir: Path) -> None:
    """Keep only the most recent ``_TRACE_KEEP`` trace files (0 = unbounded).
    Best-effort: a prune failure must never break a flush."""
    if _TRACE_KEEP <= 0:
        return
    try:
        files = sorted(out_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for stale in files[_TRACE_KEEP:]:
            stale.unlink(missing_ok=True)
    except Exception:
        log.debug("generative_trace: prune failed (non-fatal)", exc_info=True)


def _summarize_delta(prev: str, cur: str) -> str:
    """Cheap, dependency-free delta summary so 'true iteration vs re-roll' is
    legible without loading both blobs. Reports size change + overlap ratio."""
    if not prev and not cur:
        return "both empty"
    if prev == cur:
        return "IDENTICAL to previous (re-roll produced no change)"
    pw, cw = set(prev.split()), set(cur.split())
    overlap = len(pw & cw) / max(1, len(pw | cw))
    return (
        f"chars {len(prev)}->{len(cur)} ({len(cur) - len(prev):+d}); "
        f"token overlap {overlap:.0%} ("
        + (
            "near-identical re-roll"
            if overlap > 0.9
            else "substantial rewrite"
            if overlap < 0.5
            else "partial revision"
        )
        + ")"
    )


def _safe_name(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in str(value))[:120] or "episode"


def _consent_value() -> Any:
    try:
        from shared.governance.consent_label import ConsentLabel
        from shared.labeled_trace import serialize_label

        # Traces embed actual draft prose + recruited (operator-vault-derived)
        # source material — sensitive, NOT public. Label fail-CLOSED to the
        # operator so a downstream consent-aware reader/exporter treats them as
        # restricted; bottom() (the prior value) is public and would leak them
        # as unrestricted (codex-1, PR #4133).
        operator_only = ConsentLabel(frozenset({("operator", frozenset({"operator"}))}))
        return serialize_label(operator_only)
    except Exception:
        return "unlabeled"


# ── Ambient episode (so participants deep in the call tree can record without
#    threading the trace through every signature). One episode at a time per
#    context; segment prep is sequential per-segment so a ContextVar is enough. ──

import contextvars  # noqa: E402

_current_episode: contextvars.ContextVar[GenerativeEpisodeTrace | None] = contextvars.ContextVar(
    "generative_episode", default=None
)


def begin_episode(**kw: Any) -> GenerativeEpisodeTrace:
    """Start (and make ambient) a new episode trace."""
    trace = GenerativeEpisodeTrace(**kw)
    _current_episode.set(trace)
    return trace


def current() -> GenerativeEpisodeTrace | None:
    """The ambient episode, or None. Callers MUST tolerate None (no-op when off)."""
    return _current_episode.get()


def clear_episode() -> None:
    _current_episode.set(None)


def end_episode(prep_dir: Path | str, outcome: str | None = None) -> Path | None:
    """Finish, flush, and clear the ambient episode. Returns the written path."""
    trace = _current_episode.get()
    if trace is None:
        return None
    if outcome is not None and trace.outcome == "in_progress":
        trace.finish(outcome)
    path = trace.flush(prep_dir)
    clear_episode()
    return path
