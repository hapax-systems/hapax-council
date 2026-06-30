from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Sequence
from contextvars import ContextVar

from pydantic_ai import (  # noqa: TC002 — runtime use in _call_member
    Agent,
    NativeOutput,
    UsageLimits,
)
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import UserContent

from .aggregation import AxisAggregate, aggregate_scores, should_shortcircuit
from .capability_admission import (
    CapabilityAdmissionReceipt,
    capability_receipt_refs,
    member_capability_admission,
    require_member_admission,
    route_resource_admission_state,
    tool_call_log_label,
    unique_capability_admissions,
)
from .members import (
    ToolLevel,
    build_member,
    cache_policy_for_aliases,
    model_family,
    served_model_family,
)
from .models import (
    AdversarialExchange,
    ConvergenceStatus,
    CouncilConfig,
    CouncilHealth,
    CouncilInput,
    CouncilMode,
    CouncilVerdict,
    EvidenceMatrix,
    EvidenceMatrixAxis,
    MemberFailure,
    PhaseOneResult,
    build_phase1_model,
)
from .prompts import (
    RESEARCH_SYSTEM_PROMPT,
    phase1_system_prompt,
    phase2_alternative_framing_prompt,
    phase3_adversarial_prompt,
    phase3_audience_simulation_prompt,
    phase4_revision_prompt,
)
from .rubrics import Rubric
from .tools import tool_memoization_scope

_log = logging.getLogger(__name__)

_MEMBER_TIMEOUT_S = 120.0
_capability_admission_events: ContextVar[list[CapabilityAdmissionReceipt] | None] = ContextVar(
    "cctv_capability_admission_events", default=None
)

# ── PRINCIPLED EXECUTION BOUNDS ──────────────────────────────────────────────
# cc-task cctv-council-perfect-health-faillloud-convergence. pydantic-ai 1.63's
# default UsageLimits leaves ``tool_calls_limit=None`` (UNBOUNDED): a member ran
# 1124 tool calls in one GATE-1 run before the 120s wall-clock timeout fired,
# producing an empty "Phase 1 failure" (TimeoutError) and budget exhaustion.
# Every member call is now EXPLICITLY bounded; ``retries=0`` is set at Agent
# construction (members.py) so a non-conforming structured output fails loud
# instead of silently retrying.
#
# Research pass: a member needs a few rounds of tool calls to verify a claim,
# never hundreds. Scoring pass: a single provider-enforced structured answer
# with NO tools (tool_calls_limit=0). FLAGGED: these caps are deliberately
# generous-but-finite — tune via the tool_calls_log if a healthy member
# legitimately needs more research depth.
# tool_calls_limit raised 8 -> 12 -> 20 (request 6 -> 8 -> 20) per the live
# seg-prep journal (2026-06-11 23:39): healthy members needed 9-11 research tool
# calls (opus=9, balanced=10, mistral=11, web-research=9); cap=8 then cap=12
# still forced deeper-grounding members over-limit -> discarded -> members_valid
# below floor 4 -> 0 segments released. Paired with the graceful cap-handling
# below (a member that hits the budget now SCORES with the research it has rather
# than being discarded), 20/20 gives ample headroom without sacrificing the floor.
# The FLAGGED comment above invites further tuning via the tool_calls_log.
_RESEARCH_LIMITS = UsageLimits(request_limit=20, tool_calls_limit=20)
_SCORE_LIMITS = UsageLimits(request_limit=2, tool_calls_limit=0)


PromptPayload = str | Sequence[UserContent]


async def _call_member(
    member: Agent[None, Any],
    prompt: PromptPayload,
    *,
    output_type: Any | None = None,
    usage_limits: UsageLimits | None = None,
) -> tuple[Any, list[str], str]:
    """Run a member, bounded and (optionally) under a structured output contract.

    ``usage_limits`` caps tool iterations + requests (the runaway fix);
    ``output_type`` (e.g. ``NativeOutput(Phase1Output)``) forces provider-enforced
    structured output. ``result.output`` is the typed object when output_type is
    set, otherwise the raw text. Wrapped in the per-member wall-clock timeout.
    """
    run_kwargs: dict[str, Any] = {}
    if output_type is not None:
        run_kwargs["output_type"] = output_type
    if usage_limits is not None:
        run_kwargs["usage_limits"] = usage_limits
    admission = member_capability_admission(member)
    admission_events = _capability_admission_events.get()
    if admission is not None and admission_events is not None:
        admission_events.append(admission)
    require_member_admission(member)
    result = await asyncio.wait_for(member.run(prompt, **run_kwargs), timeout=_MEMBER_TIMEOUT_S)
    tool_calls: list[str] = []
    served_model = ""
    try:
        for msg in result.all_messages():
            # ModelResponse messages carry the model that ACTUALLY answered; capture the last so a
            # gateway fail-over (e.g. balanced->gemini-pro on a credit cap) is visible to the
            # family-diversity quorum instead of being miscounted as the requested alias's family.
            model_name = getattr(msg, "model_name", None)
            if model_name:
                served_model = str(model_name)
            parts = getattr(msg, "parts", [])
            for part in parts:
                kind = getattr(part, "part_kind", "")
                if kind == "tool-call":
                    name = getattr(part, "tool_name", "?")
                    args = str(getattr(part, "args", ""))[:200]
                    tool_calls.append(f"{tool_call_log_label(str(name))}({args})")
                elif kind == "tool-return":
                    name = getattr(part, "tool_name", "?")
                    content = str(getattr(part, "content", ""))[:200]
                    tool_calls.append(f"{tool_call_log_label(str(name))} → {content}")
    except Exception:
        pass
    return result.output, tool_calls, served_model


async def run_phase1(
    inp: CouncilInput,
    rubric: Rubric,
    config: CouncilConfig,
    *,
    failures_out: list[MemberFailure] | None = None,
) -> list[PhaseOneResult]:
    """Run Phase 1 across the configured member panel.

    Returns the surviving members' results. When ``failures_out`` is
    provided, every member that fails to produce a result is appended to it
    (alias + reason) so a degraded panel can be recorded transparently by
    the caller — survivors-only behaviour is otherwise unchanged.
    """

    async def _run_one(alias: str, seed: int) -> PhaseOneResult | None:
        try:
            if not rubric.requires_research:
                # JUDGMENT rubric (coherence, narrative_quality): the object of
                # judgment IS inp.text. Skip the claim-verification research pass
                # entirely — forcing "verify the source material" only burns the
                # research budget and times out, then forces the score onto
                # truncated/irrelevant research (the rubric-blind research-pass bug
                # that floored coherence at ~1.0). Score directly from the text.
                # (source_context is intentionally NOT surfaced here — the judgment
                # object is the text itself; building it would be dead work,
                # codex-1/claude-1 PR #4133.)
                tool_calls = []
                findings_text = (
                    "(no external research — this is a judgment rubric; evaluate the "
                    "supplied text on its own terms, not against external sources)"
                )
            else:
                research_member = build_member(
                    alias,
                    system_prompt=RESEARCH_SYSTEM_PROMPT,
                )

                source_ctx_block = ""
                if inp.source_context:
                    source_ctx_block = f"\n\n## Source Context\n```\n{inp.source_context}\n```\n"

                # Only the per-input dynamic content goes in the user message;
                # the role identity and tool-usage instructions are now in
                # system_prompt for prefix-cache reuse.
                investigate_prompt = (
                    f"FIRST, investigate the source material before scoring. "
                    f"Do NOT score yet — only gather evidence.\n\n"
                    f"**Source ref:** {inp.source_ref}\n\n**Text:**\n{inp.text}"
                    f"{source_ctx_block}"
                )
                try:
                    investigate_raw, tool_calls, _ = await _call_member(
                        research_member, investigate_prompt, usage_limits=_RESEARCH_LIMITS
                    )
                    findings_text = str(investigate_raw)[:2000]
                except (UsageLimitExceeded, TimeoutError) as research_err:
                    # A member that exhausts its research budget (over-grounding) or
                    # times out is NOT a failed member. Discarding it dropped
                    # members_valid below the quality floor in the 2026-06-13 seg-prep
                    # incident (5/6 over-grounded -> members_valid=1 -> 0 released). It
                    # still produces a structured score from the rubric + source text;
                    # the source_grounding axis honestly reflects truncated research.
                    # Only a SCORING failure (outer except) discards a member.
                    _log.warning(
                        "Research budget/timeout for %s (%s); scoring with truncated research",
                        alias,
                        type(research_err).__name__,
                    )
                    tool_calls = []
                    findings_text = (
                        "(research truncated: budget/timeout reached before a findings "
                        "summary was produced; score from the source text directly and "
                        "rate source_grounding conservatively)"
                    )

            # Build the score member with the full rubric in system_prompt.
            # The user message is just the input text + prior research.
            scoring_sys = phase1_system_prompt(rubric, seed=seed)
            score_member = build_member(
                alias,
                tool_level=ToolLevel.NONE,
                system_prompt=scoring_sys,
            )
            score_prompt = (
                f"## Input\n\n**Source ref:** {inp.source_ref}\n\n"
                f"**Text:**\n{inp.text}\n\n"
                f"## Your Prior Research Findings\n{findings_text}\n\n"
                "Score based on your research above. Do NOT re-investigate. "
                "Respond ONLY with the structured score object (an integer "
                f"{rubric.axes[0].min_score}-{rubric.axes[0].max_score} per axis)."
            )
            phase1_output, score_tools, served_model = await _call_member(
                score_member,
                score_prompt,
                output_type=NativeOutput(build_phase1_model(rubric)),
                usage_limits=_SCORE_LIMITS,
            )
            score_admission = member_capability_admission(score_member)
        except Exception as e:
            # Full detail (which may include a request URL or auth header from
            # an upstream LiteLLM error) goes only to the server log, where
            # credential scrubbing applies.
            _log.error("Phase 1 failure for %s: %s", alias, e)
            if failures_out is not None:
                # The verdict receipt is a durable, downstream-published
                # artifact — record only the exception *type*, never str(e),
                # so a secret/PII-bearing error message cannot leak into it.
                failures_out.append(MemberFailure(model_alias=alias, reason=type(e).__name__))
            return None

        # The output type produces a scores sub-model (per-rubric required axis fields);
        # legacy/mocked callers may pass a plain dict — accept both at the boundary.
        _raw_scores = phase1_output.scores
        score_dict = (
            _raw_scores.model_dump() if hasattr(_raw_scores, "model_dump") else dict(_raw_scores)
        )
        # Enforce the 1-5 rubric range in Python: the output type uses PLAIN ints
        # (Anthropic's json_schema rejects integer min/max, which silently forces an
        # off-family substitution), so the range cannot live in the schema. An empty or
        # out-of-range result is a LOUD member failure — never a phantom abstainer that
        # shrinks the denominator and lets a lone real survivor masquerade as consensus.
        lo, hi = rubric.axes[0].min_score, rubric.axes[0].max_score
        if not score_dict:
            _log.error("Phase 1 failure for %s: structured output carried no scores", alias)
            if failures_out is not None:
                failures_out.append(MemberFailure(model_alias=alias, reason="EmptyScores"))
            return None
        if any(not (lo <= int(v) <= hi) for v in score_dict.values()):
            _log.error("Phase 1 failure for %s: score out of rubric range %s", alias, score_dict)
            if failures_out is not None:
                failures_out.append(MemberFailure(model_alias=alias, reason="ScoreOutOfRange"))
            return None

        return PhaseOneResult(
            model_alias=alias,
            scores={k: int(v) for k, v in score_dict.items()},
            rationale=phase1_output.rationale,
            research_findings=phase1_output.research_findings,
            tool_calls_log=tool_calls + score_tools,
            served_model=served_model,
            capability_id=score_admission.capability_id if score_admission else "",
            route_id=score_admission.route_id if score_admission else "",
            capability_admission_action=(
                score_admission.admission_action if score_admission else ""
            ),
            capability_receipt_refs=score_admission.receipt_refs if score_admission else (),
        )

    results_or_none = await asyncio.gather(
        *(_run_one(alias, i) for i, alias in enumerate(config.model_aliases))
    )
    return [r for r in results_or_none if r is not None]


def _assess_health(
    results: list[PhaseOneResult],
    failed: list[MemberFailure],
    config: CouncilConfig,
) -> CouncilHealth:
    """Typed health of a panel measured against the principled quorum floor.

    A verdict is trustworthy only across INDEPENDENT families, so coverage is
    counted both by member and by DISTINCT family. ``below_quorum`` is True when
    either floor is unmet — the engine turns that into ConvergenceStatus.REFUSED.
    """
    requested = config.model_aliases
    valid_aliases = [r.model_alias for r in results]

    # Count family-diversity by the SERVED model, not the requested alias. A LiteLLM fail-over
    # (e.g. balanced->gemini-pro on an Anthropic credit cap) means the seat's TRUE family is the
    # one that answered; counting by the requested alias would let a phantom-anthropic gemini
    # satisfy the diversity floor and silently contaminate the ruler. Fall back to the requested
    # alias's family when the served name is unknown (no regression on the all-up path).
    def _served_family_of(r: PhaseOneResult) -> str:
        fam = served_model_family(r.served_model) if r.served_model else "unknown"
        return fam if fam != "unknown" else model_family(r.model_alias)

    families_valid = {_served_family_of(r) for r in results}
    served_substitutions = sum(
        1
        for r in results
        if r.served_model
        and served_model_family(r.served_model) != "unknown"
        and served_model_family(r.served_model) != model_family(r.model_alias)
    )
    families_requested = {model_family(a) for a in requested}
    below = (
        len(valid_aliases) < config.min_valid_members
        or len(families_valid) < config.min_valid_families
    )
    return CouncilHealth(
        members_requested=len(requested),
        members_valid=len(valid_aliases),
        families_requested=len(families_requested),
        families_valid=len(families_valid),
        failed_members=tuple(failed),
        below_quorum=below,
        quorum_floor_members=config.min_valid_members,
        quorum_floor_families=config.min_valid_families,
        served_substitutions=served_substitutions,
    )


def _fold_overall(agg: dict[str, AxisAggregate]) -> ConvergenceStatus:
    """Fold per-axis statuses into one verdict — REFUSED-priority, fail-CLOSED.

    A REFUSED (under-covered) axis, or an empty axis set, can NEVER fall through
    to CONVERGED — closing the original ``else -> CONVERGED`` fail-open. Genuine
    disagreement (HUNG, always with real scores) and partial disagreement
    (CONTESTED) keep their meaning.
    """
    statuses = [v.status for v in agg.values()]
    if not statuses or ConvergenceStatus.REFUSED in statuses:
        return ConvergenceStatus.REFUSED
    if ConvergenceStatus.HUNG in statuses:
        return ConvergenceStatus.HUNG
    if ConvergenceStatus.CONTESTED in statuses:
        return ConvergenceStatus.CONTESTED
    return ConvergenceStatus.CONVERGED


def _capability_admission_receipt_fields(
    admissions: list[CapabilityAdmissionReceipt],
) -> dict[str, object]:
    unique = unique_capability_admissions(tuple(admissions))
    return {
        "capability_admissions": [admission.model_dump(mode="json") for admission in unique],
        "route_resource_admission": route_resource_admission_state(unique),
        "capability_receipt_refs": list(capability_receipt_refs(unique)),
        "capability_admission_source": "member_call_gate",
        "capability_admission_call_count": len(admissions),
    }


async def deliberate(
    inp: CouncilInput,
    mode: CouncilMode,
    rubric: Rubric,
    config: CouncilConfig | None = None,
) -> CouncilVerdict:
    if config is None:
        config = CouncilConfig()
    # R4 (cctv-prompt-caching-quality-neutral-20260607): identical read_source /
    # grep_evidence sub-calls within ONE deliberation short-circuit via a per-run
    # cache shared across this deliberation's member tasks only (distinct
    # deliberations stay isolated; callers outside deliberate() run uncached).
    with tool_memoization_scope():
        return await _deliberate(inp, mode, rubric, config)


async def _deliberate(
    inp: CouncilInput,
    mode: CouncilMode,
    rubric: Rubric,
    config: CouncilConfig,
) -> CouncilVerdict:
    capability_admission_events: list[CapabilityAdmissionReceipt] = []
    token = _capability_admission_events.set(capability_admission_events)
    try:
        return await _deliberate_inner(inp, mode, rubric, config, capability_admission_events)
    finally:
        _capability_admission_events.reset(token)


async def _deliberate_inner(
    inp: CouncilInput,
    mode: CouncilMode,
    rubric: Rubric,
    config: CouncilConfig,
    capability_admission_events: list[CapabilityAdmissionReceipt],
) -> CouncilVerdict:
    if not inp.source_context:
        from agents.deliberative_council.source_context import populate_source_context

        ctx = populate_source_context(inp.text, inp.source_ref, inp.metadata)
        if ctx:
            inp = inp.model_copy(update={"source_context": ctx})

    input_hash = hashlib.sha256(
        json.dumps({"text": inp.text, "source_ref": inp.source_ref}, sort_keys=True).encode()
    ).hexdigest()
    cache_policy = cache_policy_for_aliases(config.model_aliases)

    failed_members: list[MemberFailure] = []
    phase1_results = await run_phase1(inp, rubric, config, failures_out=failed_members)
    failed_members_payload = [
        {"model_alias": f.model_alias, "reason": f.reason} for f in failed_members
    ]
    health = _assess_health(phase1_results, failed_members, config)
    health_payload = health.model_dump(mode="json")

    if health.below_quorum:
        # Refuse LOUDLY. The panel is below the principled quorum / family-
        # diversity floor (or every member failed). A broken panel is typed
        # REFUSED — never HUNG (genuine disagreement) and never a silent pass.
        reason = "all_models_failed" if not phase1_results else "below_quorum_or_family_floor"
        _log.warning(
            "Council REFUSED (%s): members_valid=%d/%d (floor %d), families_valid=%d/%d (floor %d)",
            reason,
            health.members_valid,
            health.members_requested,
            config.min_valid_members,
            health.families_valid,
            health.families_requested,
            config.min_valid_families,
        )
        return CouncilVerdict(
            scores={},
            confidence_bands={},
            convergence_status=ConvergenceStatus.REFUSED,
            disagreement_log=[f"Council refused: {reason}"],
            research_findings=[f for r in phase1_results for f in r.research_findings],
            evidence_matrix=None,
            receipt={
                "input_hash": input_hash,
                "refused": True,
                "refusal_reason": reason,
                "council_health": health_payload,
                "failed_members": failed_members_payload,
                "cache_policy": cache_policy,
                **_capability_admission_receipt_fields(capability_admission_events),
            },
        )

    if should_shortcircuit(phase1_results, config.shortcircuit_iqr_threshold):
        agg = aggregate_scores(
            phase1_results, config.contested_iqr_threshold, min_values=config.min_axis_values
        )
        return CouncilVerdict(
            scores={k: v.score for k, v in agg.items()},
            confidence_bands={k: v.confidence_band for k, v in agg.items()},
            convergence_status=_fold_overall(agg),
            disagreement_log=[],
            research_findings=[f for r in phase1_results for f in r.research_findings],
            evidence_matrix=None,
            receipt={
                "input_hash": input_hash,
                "shortcircuited": True,
                "council_health": health_payload,
                "models_used": [r.model_alias for r in phase1_results],
                "served_models": [r.served_model for r in phase1_results],
                "ruler_substituted": (health_payload.get("served_substitutions") or 0) > 0,
                "failed_members": failed_members_payload,
                "cache_policy": cache_policy,
                **_capability_admission_receipt_fields(capability_admission_events),
                "phases_completed": [1],
                "phase1_transcript": [
                    {"model": r.model_alias, "tool_calls": r.tool_calls_log} for r in phase1_results
                ],
            },
        )

    # Phase 2: Evidence matrix (epistemic) or Alternative Framing Matrix (narrative)
    evidence_matrix = await _run_phase2(phase1_results, rubric, config, mode=mode, text=inp.text)

    # Phase 3: Adversarial challenge (epistemic) or Audience Simulation (narrative)
    adversarial_exchanges = await _run_phase3(
        phase1_results, evidence_matrix, rubric, config, mode=mode, text=inp.text
    )

    # Phase 4: Revised private judgment
    phase4_results = await _run_phase4(
        phase1_results, evidence_matrix, adversarial_exchanges, rubric, config
    )

    # Phase 5: Final convergence on revised scores
    final_results = phase4_results if phase4_results else phase1_results
    agg = aggregate_scores(
        final_results, config.contested_iqr_threshold, min_values=config.min_axis_values
    )
    overall = _fold_overall(agg)

    return CouncilVerdict(
        scores={k: v.score for k, v in agg.items()},
        confidence_bands={k: v.confidence_band for k, v in agg.items()},
        convergence_status=overall,
        disagreement_log=[
            f"{a}: IQR={v.iqr:.1f} values={v.values}" for a, v in agg.items() if v.iqr > 1.0
        ],
        research_findings=[f for r in phase1_results for f in r.research_findings],
        evidence_matrix=evidence_matrix,
        adversarial_exchanges=tuple(adversarial_exchanges),
        receipt={
            "input_hash": input_hash,
            "shortcircuited": False,
            "council_health": health_payload,
            "models_used": [r.model_alias for r in phase1_results],
            "served_models": [r.served_model for r in phase1_results],
            "ruler_substituted": (health_payload.get("served_substitutions") or 0) > 0,
            "failed_members": failed_members_payload,
            "cache_policy": cache_policy,
            **_capability_admission_receipt_fields(capability_admission_events),
            "phases_completed": [1, 2, 3, 4, 5],
            "phase1_transcript": [
                {"model": r.model_alias, "tool_calls": r.tool_calls_log} for r in phase1_results
            ],
            "phase2_transcript": {
                "built_by": evidence_matrix.built_by if evidence_matrix else None,
                "contested_axes": (list(evidence_matrix.axes.keys()) if evidence_matrix else []),
            },
            "phase3_transcript": [
                {
                    "axis": e.axis,
                    "high_scorer": e.high_scorer,
                    "high_score": e.high_score,
                    "low_scorer": e.low_scorer,
                    "low_score": e.low_score,
                }
                for e in adversarial_exchanges
            ],
            "phase4_transcript": [
                {"model": r.model_alias, "scores": r.scores} for r in final_results
            ],
            "phase5_convergence": {
                a: {"status": v.status.value, "iqr": v.iqr, "score": v.score}
                for a, v in agg.items()
            },
        },
    )


async def _run_phase2(
    phase1_results: list[PhaseOneResult],
    rubric: Rubric,
    config: CouncilConfig,
    *,
    mode: CouncilMode = CouncilMode.DISCONFIRMATION,
    text: str = "",
) -> EvidenceMatrix | None:
    """Phase 2: Build ACH evidence matrix (epistemic) or Alternative Framing Matrix (narrative)."""
    from .aggregation import compute_iqr

    contested_axes: list[str] = []
    all_axes: set[str] = set()
    for r in phase1_results:
        all_axes.update(r.scores.keys())
    for axis in all_axes:
        values = [r.scores[axis] for r in phase1_results if axis in r.scores]
        if compute_iqr(values) > config.shortcircuit_iqr_threshold:
            contested_axes.append(axis)

    if not contested_axes:
        return None

    all_findings = []
    for r in phase1_results:
        for f in r.research_findings:
            all_findings.append(f"{r.model_alias}: {f}")

    findings_block = "\n".join(all_findings) if all_findings else "No research findings."
    scores_block = "\n".join(f"  {r.model_alias}: {r.scores}" for r in phase1_results)

    if mode == CouncilMode.INTAKE:
        prompt = (
            "You are building an Impediment Matrix for a work request.\n\n"
            f"## Contested axes: {contested_axes}\n\n"
            f"## Phase 1 scores:\n{scores_block}\n\n"
            f"## Research findings:\n{findings_block}\n\n"
            "For each contested axis, identify WHAT SPECIFIC INFORMATION IS MISSING\n"
            "that prevents convergence. Be concrete — name the missing section,\n"
            "field, or specification that would resolve the disagreement.\n\n"
            "Respond in JSON:\n"
            '{"axes": {"axis_name": {"impediment": "what is missing", '
            '"resolution": "what the requester should add"}, ...}}'
        )
    elif mode == CouncilMode.NARRATIVE and text:
        phase1_scores = {r.model_alias: r.scores for r in phase1_results}
        prompt = phase2_alternative_framing_prompt(text, phase1_scores)
    else:
        prompt = (
            "You are building an Analysis of Competing Hypotheses (ACH) evidence matrix.\n\n"
            f"## Contested axes: {contested_axes}\n\n"
            f"## Phase 1 scores:\n{scores_block}\n\n"
            f"## Research findings:\n{findings_block}\n\n"
            "For each contested axis, classify each research finding as:\n"
            "- consistent: supports this score level\n"
            "- inconsistent: contradicts this score level\n"
            "- irrelevant: neither supports nor contradicts\n\n"
            "Identify the LEAST INCONSISTENT score level per axis (ACH logic).\n\n"
            "Respond in JSON:\n"
            '{"axes": {"axis_name": {"least_inconsistent_score": int, '
            '"summary": "..."}, ...}}'
        )

    try:
        member = build_member(config.model_aliases[0])
        raw, _, _ = await _call_member(member, prompt)
        text = raw.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()
        data = json.loads(text, strict=False)

        matrix_axes = {}
        for axis, info in data.get("axes", {}).items():
            matrix_axes[axis] = EvidenceMatrixAxis(
                axis=axis,
                least_inconsistent_score=info.get("least_inconsistent_score"),
            )
        return EvidenceMatrix(axes=matrix_axes, built_by=config.model_aliases[0])
    except Exception as e:
        _log.warning("Phase 2 failed: %s", e)
        return None


async def _run_phase3(
    phase1_results: list[PhaseOneResult],
    evidence_matrix: EvidenceMatrix | None,
    rubric: Rubric,
    config: CouncilConfig,
    *,
    mode: CouncilMode = CouncilMode.DISCONFIRMATION,
    text: str = "",
) -> list[AdversarialExchange]:
    """Phase 3: Adversarial challenge (epistemic) or Audience Simulation (narrative)."""
    from .aggregation import compute_iqr

    exchanges: list[AdversarialExchange] = []
    all_axes: set[str] = set()
    for r in phase1_results:
        all_axes.update(r.scores.keys())

    for axis in all_axes:
        scores_for_axis = [
            (r.model_alias, r.scores.get(axis, 0)) for r in phase1_results if axis in r.scores
        ]
        if not scores_for_axis:
            continue

        values = [s for _, s in scores_for_axis]
        if compute_iqr(values) <= config.shortcircuit_iqr_threshold:
            continue

        high_alias, high_score = max(scores_for_axis, key=lambda x: x[1])
        low_alias, low_score = min(scores_for_axis, key=lambda x: x[1])

        if high_score == low_score:
            continue

        high_result = next(r for r in phase1_results if r.model_alias == high_alias)
        low_result = next(r for r in phase1_results if r.model_alias == low_alias)

        matrix_summary = ""
        if evidence_matrix and axis in evidence_matrix.axes:
            em_axis = evidence_matrix.axes[axis]
            matrix_summary = f"Least inconsistent score: {em_axis.least_inconsistent_score}"

        if mode == CouncilMode.INTAKE:
            prompt = (
                f"You are evaluating a work request on axis '{axis}'.\n\n"
                f"One evaluator scored {high_score}/5: {high_result.rationale.get(axis, '')}\n"
                f"Another scored {low_score}/5: {low_result.rationale.get(axis, '')}\n\n"
                f"Evidence matrix: {matrix_summary}\n\n"
                "TASK: Role-play as a task creator trying to decompose this request.\n"
                "What specific cc-tasks would you create for this axis?\n"
                "What acceptance criteria would each task have?\n"
                "If you CANNOT create concrete tasks, explain why — that's diagnostic.\n\n"
                "Respond concisely (under 300 words)."
            )
        elif mode == CouncilMode.NARRATIVE and text:
            prompt = phase3_audience_simulation_prompt(
                text=text,
                axis=axis,
                your_score=high_score,
                your_rationale=high_result.rationale.get(axis, ""),
                opponent_score=low_score,
                opponent_rationale=low_result.rationale.get(axis, ""),
            )
        else:
            prompt = phase3_adversarial_prompt(
                axis=axis,
                your_score=high_score,
                your_rationale=high_result.rationale.get(axis, ""),
                opponent_score=low_score,
                opponent_rationale=low_result.rationale.get(axis, ""),
                opponent_findings=low_result.research_findings,
                evidence_matrix_summary=matrix_summary,
            )

        try:
            member = build_member(high_alias)
            raw, _, _ = await _call_member(member, prompt)
            exchanges.append(
                AdversarialExchange(
                    axis=axis,
                    high_scorer=high_alias,
                    high_score=high_score,
                    low_scorer=low_alias,
                    low_score=low_score,
                    challenge_text=f"Low scorer ({low_alias}) rationale: {low_result.rationale.get(axis, '')}",
                    response_text=raw[:2000],
                )
            )
        except Exception as e:
            _log.warning("Phase 3 adversarial exchange failed for %s: %s", axis, e)

    return exchanges


async def _run_phase4(
    phase1_results: list[PhaseOneResult],
    evidence_matrix: EvidenceMatrix | None,
    adversarial_exchanges: list[AdversarialExchange],
    rubric: Rubric,
    config: CouncilConfig,
) -> list[PhaseOneResult]:
    """Phase 4: All models re-score privately after seeing evidence + challenges."""
    if not adversarial_exchanges:
        return phase1_results

    matrix_summary = (
        "No evidence matrix."
        if not evidence_matrix
        else json.dumps(
            {
                k: {"least_inconsistent": v.least_inconsistent_score}
                for k, v in evidence_matrix.axes.items()
            }
        )
    )
    exchanges_summary = "\n".join(
        f"  {e.axis}: {e.high_scorer}({e.high_score}) vs {e.low_scorer}({e.low_score}) — response: {e.response_text[:200]}"
        for e in adversarial_exchanges
    )

    revised_results: list[PhaseOneResult] = []

    async def _revise_one(original: PhaseOneResult) -> PhaseOneResult:
        prompt = phase4_revision_prompt(
            rubric=rubric,
            original_scores=original.scores,
            evidence_matrix_summary=matrix_summary,
            adversarial_exchanges=exchanges_summary,
        )
        try:
            member = build_member(original.model_alias)
            raw, _, _ = await _call_member(member, prompt)
            revision_admission = member_capability_admission(member)
            text = raw.strip()
            if "```json" in text:
                text = text.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in text:
                text = text.split("```", 1)[1].split("```", 1)[0].strip()
            data = json.loads(text, strict=False)
            revised_scores = {k: int(v) for k, v in data.get("revised_scores", {}).items()}
            if revised_scores:
                return PhaseOneResult(
                    model_alias=original.model_alias,
                    capability_id=(revision_admission.capability_id if revision_admission else ""),
                    route_id=revision_admission.route_id if revision_admission else "",
                    capability_admission_action=(
                        revision_admission.admission_action if revision_admission else ""
                    ),
                    capability_receipt_refs=(
                        revision_admission.receipt_refs if revision_admission else ()
                    ),
                    scores=revised_scores,
                    rationale=data.get("revision_rationale", original.rationale),
                    research_findings=original.research_findings,
                )
        except Exception as e:
            _log.warning("Phase 4 revision failed for %s: %s", original.model_alias, e)
        return original

    revised_results = list(await asyncio.gather(*(_revise_one(r) for r in phase1_results)))
    return revised_results
