from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, create_model


class CouncilMode(StrEnum):
    LABELING = "labeling"
    SCORING = "scoring"
    DISCONFIRMATION = "disconfirmation"
    AUDIT = "audit"
    NARRATIVE = "narrative"
    INTAKE = "intake"
    RESEARCH_ASSESSMENT = "research_assessment"


class ConvergenceStatus(StrEnum):
    """Outcome of a council deliberation.

    "Converged" vs "broke" are TYPED and DISTINCT (cc-task
    cctv-council-perfect-health-faillloud-convergence):

    - ``CONVERGED`` / ``CONTESTED`` / ``HUNG`` describe a HEALTHY panel that
      actually deliberated — members agreed, partly disagreed, or genuinely
      disagreed (HUNG always carries real scores).
    - ``REFUSED`` means the panel could NOT be trusted to produce a verdict at
      all: below the quorum / family-diversity floor, all members failed, or an
      axis had insufficient independent coverage. It is never a quiet pass — it
      forces the downstream consumer to refuse the segment. A REFUSED panel must
      NEVER be collapsed into CONVERGED/CONTESTED by a fall-through ``else``.
    """

    CONVERGED = "converged"
    CONTESTED = "contested"
    HUNG = "hung"
    REFUSED = "refused"


class CouncilInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    source_context: str = Field(default="")
    metadata: dict[str, Any] = Field(default_factory=dict)


class CouncilConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    phases: tuple[int, ...] = (1, 2, 3, 4, 5)
    model_aliases: tuple[str, ...] = (
        "opus",
        "balanced",
        "gemini-3-pro",
        # "local-fast" (Command-R on appendix TabbyAPI :5000) is DROPPED while
        # appendix is down (HTTP 000): a dead canonical seat fails over to
        # gemini-flash (a cross-family substitution) and falsely trips the
        # served_substitutions>0 quarantine. RESTORE this line when appendix
        # TabbyAPI is back up. Panel stays above the 4-family/4-member floor
        # (7 members / 6 families remain). 2026-06-21.
        "web-research",
        "mistral-large",
        "deepseek",
        "glm",
    )
    shortcircuit_iqr_threshold: float = 1.0
    contested_iqr_threshold: float = 2.0

    # ── PRINCIPLED QUORUM / FAMILY-DIVERSITY FLOOR ──────────────────────────
    # Replaces the dead ``family_correlation_penalty_threshold``. A convergence
    # verdict is trustworthy ONLY when INDEPENDENT model families agree;
    # correlated members (same family) add no independent evidence. The default
    # panel is 8 members across 7 families (anthropic x2, google, cohere,
    # perplexity, mistral, deepseek, zhipu/glm — deepseek + glm added 2026-06-20
    # for cap-resilient diversity, all cloud so no Resource-Constitution/GPU
    # conflict). The floor is FAMILY COVERAGE, not a tuned magic constant; it is
    # kept at the prior absolute values so the added families are REDUNDANCY
    # (more ways to satisfy the floor under a provider outage), not a stricter bar:
    #   - min_valid_families: >= this many DISTINCT families must emit a valid
    #     scored result (default 4 — now of 7; tolerates losing up to 3 families).
    #   - min_valid_members:  >= this many valid members (default 4 of 8).
    # A panel below the floor -> ConvergenceStatus.REFUSED (never CONVERGED).
    # FLAGGED FOR OPERATOR RATIFICATION: "CCTV full-power" implies 6 members /
    # 5 families; the operator may ratify that stricter floor by raising these.
    min_valid_members: int = 4
    min_valid_families: int = 4
    # Per-axis coverage floor: the minimum number of independent member scores
    # required to certify a single axis (a lone score's IQR is 0.0, which must
    # not read as consensus). Applied in aggregate_scores().
    min_axis_values: int = 2

    # ── RDLC FREEZE AXIS (resilience vs confirmatory honesty) ───────────────
    # None = NOT frozen (R1_PROTOCOL pilot / operational): the release criterion is the
    # family-diversity FLOOR (below_quorum) + C_k; a served substitution is a transparency
    # LABEL, never a refusal — so the council is resilient to single-provider drop-out
    # while the abundant live pool keeps the floor met. A set ruler_hash = the protocol is
    # FROZEN (R2_PREREGISTER -> R3_COLLECTION confirmatory): the committed roster matters,
    # so a served substitution refuses (frozen_ruler_deviation). The #4224 served-family
    # floor computation is unchanged in BOTH stages; only the gate's RESPONSE is staged.
    ruler_hash: str | None = None


class PhaseOneResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_alias: str
    capability_id: str = ""
    route_id: str = ""
    capability_admission_action: str = ""
    capability_receipt_refs: tuple[str, ...] = ()
    scores: dict[str, int]
    rationale: dict[str, str]
    research_findings: list[str] = Field(default_factory=list)
    tool_calls_log: list[str] = Field(default_factory=list)
    # The model that ACTUALLY answered (LiteLLM ModelResponse.model_name), which can differ from
    # model_alias when the gateway fails over (e.g. balanced->gemini-pro on an Anthropic credit cap).
    # Empty when unknown. The engine counts family-diversity by the SERVED family so a silent
    # substitution cannot fool the quorum floor (the 2026-06-19 credit-cap incident).
    served_model: str = ""


class MemberFailure(BaseModel):
    """A council member that failed to produce a Phase 1 result.

    Recorded into the verdict receipt so a degraded panel is *visible*
    rather than silently dropped. A survivors-only verdict can otherwise
    masquerade as consensus (e.g. a mean of 2.0 drawn from 2 of 6 members),
    which corrupts the downstream substance gate. See cc-task
    segment-prep-council-model-alias-reliability-20260607.
    """

    model_config = ConfigDict(frozen=True)

    model_alias: str
    # Exception *type name* only (e.g. "TimeoutError") — never the raw
    # exception message, which can carry upstream URLs/credentials. Full
    # detail stays in the server log. See _run_one in engine.py.
    reason: str


class Phase1Output(BaseModel):
    """Provider-enforced structured output for a Phase 1 member scoring call.

    Used as pydantic-ai ``output_type=NativeOutput(Phase1Output)`` so the model
    is constrained to emit valid JSON via the provider's native structured-output
    (``response_format: json_schema`` for cloud routes; the same standard OpenAI
    field is forwarded to TabbyAPI :5000 and enforced by Formatron for the local
    Command-R member). Guided decoding constrains the TOKENS, not the model's
    power. Scores are constrained to the 1-5 rubric scale; an output that parses
    but carries NO scores is treated by the engine as a LOUD member failure, not
    a phantom abstainer. cc-task cctv-council-perfect-health-faillloud-convergence.
    """

    model_config = ConfigDict(extra="forbid")

    scores: dict[str, Annotated[int, Field(ge=1, le=5)]] = Field(default_factory=dict)
    rationale: dict[str, str] = Field(default_factory=dict)
    research_findings: list[str] = Field(default_factory=list)


def build_phase1_model(rubric: Any) -> type[BaseModel]:
    """Per-rubric Phase 1 output type with a REQUIRED named int field per axis.

    The prior ``Phase1Output.scores`` was a free-form ``dict[str, int]`` with no
    required keys, so a structurally-valid empty ``{}`` satisfied the output type and
    only failed LOUDLY downstream (EmptyScores) — Claude/Perplexity comply with the
    JSON shape but decline to invent axis keys. Requiring one named int field per
    axis forces a real per-axis score; an omitted axis is a hard validation failure
    (a real member failure), never a phantom abstainer.

    The axis fields are PLAIN ``int`` — deliberately NOT ``Annotated[int, Field(ge/le)]``:
    Anthropic's json_schema rejects integer ``minimum``/``maximum`` (HTTP 400), which
    silently forces an off-family gateway substitution (live-proven 2026-06-21). The
    1-5 rubric range is enforced in Python after extraction (engine._run_one), where an
    out-of-range value is dropped as a real member failure, not silently clamped.
    """
    score_fields: dict[str, Any] = {axis.name: (int, ...) for axis in rubric.axes}
    scores_model = create_model(
        "Phase1Scores", __config__=ConfigDict(extra="forbid"), **score_fields
    )
    return create_model(
        "Phase1OutputDynamic",
        __config__=ConfigDict(extra="forbid"),
        scores=(scores_model, ...),
        rationale=(dict[str, str], Field(default_factory=dict)),
        research_findings=(list[str], Field(default_factory=list)),
    )


class CouncilHealth(BaseModel):
    """Typed health of a council panel — recorded so a degraded panel is VISIBLE.

    A verdict is only trustworthy across independent families. This records how
    many members and DISTINCT families produced a valid scored result vs how many
    were requested, plus every member that failed (alias + exception type). The
    engine sets ``below_quorum`` from the CouncilConfig floor; a below-quorum or
    no-family-diversity panel yields ConvergenceStatus.REFUSED.
    """

    model_config = ConfigDict(frozen=True)

    members_requested: int
    members_valid: int
    families_requested: int
    families_valid: int
    failed_members: tuple[MemberFailure, ...] = ()
    below_quorum: bool = False
    quorum_floor_members: int = 0
    quorum_floor_families: int = 0
    # Count of valid seats whose SERVED family differs from the requested alias's family — i.e. the
    # gateway substituted a model (credit-cap fail-over). > 0 means the panel ran partly off-roster;
    # for a frozen-phase SCED run this flags ruler substitution (the run is recorded but suspect).
    served_substitutions: int = 0


class EvidenceClassification(BaseModel):
    model_config = ConfigDict(frozen=True)

    finding: str
    classification: str
    score_level: int


class EvidenceMatrixAxis(BaseModel):
    model_config = ConfigDict(frozen=True)

    axis: str
    classifications: tuple[EvidenceClassification, ...] = ()
    least_inconsistent_score: int | None = None


class EvidenceMatrix(BaseModel):
    model_config = ConfigDict(frozen=True)

    axes: dict[str, EvidenceMatrixAxis] = Field(default_factory=dict)
    built_by: str = ""


class AdversarialExchange(BaseModel):
    model_config = ConfigDict(frozen=True)

    axis: str
    high_scorer: str
    high_score: int
    low_scorer: str
    low_score: int
    challenge_text: str
    response_text: str


class PhaseFourResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_alias: str
    revised_scores: dict[str, int]
    revision_rationale: dict[str, str]
    changed_axes: list[str] = Field(default_factory=list)


class CouncilVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    scores: dict[str, int | None]
    confidence_bands: dict[str, tuple[int, int]]
    convergence_status: ConvergenceStatus
    disagreement_log: list[str]
    research_findings: list[str]
    evidence_matrix: EvidenceMatrix | None
    adversarial_exchanges: tuple[AdversarialExchange, ...] = ()
    receipt: dict[str, Any] = Field(default_factory=dict)


class NarrativeVerdictStatus(StrEnum):
    BROADCAST_READY = "broadcast_ready"
    REVISE_AND_RESUBMIT = "revise_and_resubmit"
    STRUCTURAL_REWORK = "structural_rework"
    GENERIC_DETECTED = "generic_detected"


class NarrativeVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    scores: dict[str, int | None]
    confidence_bands: dict[str, tuple[int, int]]
    convergence_status: ConvergenceStatus
    verdict_status: NarrativeVerdictStatus
    alternative_framings: list[str] = Field(default_factory=list)
    audience_breaks: list[str] = Field(default_factory=list)
    disagreement_log: list[str] = Field(default_factory=list)
    revision_directives: list[str] = Field(default_factory=list)
    receipt: dict[str, Any] = Field(default_factory=dict)
