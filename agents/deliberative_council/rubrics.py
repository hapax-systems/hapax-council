from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RubricAxis(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    min_score: int = 1
    max_score: int = 5
    strong_example: str
    weak_example: str
    floor_example: str = ""


class Rubric(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    version: int = 1
    axes: tuple[RubricAxis, ...]
    instructions: str = ""


class EpistemicQualityRubric(Rubric):
    name: str = "epistemic_quality"
    version: int = 1
    instructions: str = (
        "Score each axis 1-5 based on the excerpt's epistemic quality. "
        "Use research tools to verify source_refs before scoring source_grounding. "
        "Score what the text DOES, not what it CLAIMS to do."
    )
    axes: tuple[RubricAxis, ...] = (
        RubricAxis(
            name="claim_evidence_alignment",
            description="Does the claim ceiling match the attached evidence?",
            strong_example="Claim cites exact command, fixture, timestamp, and failure scope.",
            weak_example="Claim says system is production-ready because related metadata exists.",
        ),
        RubricAxis(
            name="hedge_calibration",
            description="Is confidence language well calibrated to evidence strength?",
            strong_example=(
                "Hypothesis explicitly scoped as unvalidated when evidence is only "
                "a plausible mechanism."
            ),
            weak_example="False or source-free claim padded with hedges to appear cautious.",
        ),
        RubricAxis(
            name="quantifier_precision",
            description="Are quantities exact, scoped, and sourced — or vague/fake?",
            strong_example="Count includes denominator, freshness, data source, and uncertainty.",
            weak_example="'Many', 'most', or 'zero failures' without a measurement source.",
        ),
        RubricAxis(
            name="source_grounding",
            description="Are sources independently traceable, not just metadata?",
            strong_example="Cites primary or independently reachable source material.",
            weak_example="Title, mime type, modified time treated as evidence for contents.",
        ),
    )


class DisconfirmationRubric(Rubric):
    name: str = "disconfirmation"
    version: int = 1
    instructions: str = (
        "Your job is to TRY TO BREAK the claim. Search for counter-evidence, "
        "alternative explanations, and unstated assumptions. Score how well "
        "the claim survives adversarial scrutiny."
    )
    axes: tuple[RubricAxis, ...] = (
        RubricAxis(
            name="evidence_adequacy",
            description="Does the evidence actually support the claim as stated?",
            strong_example="Multiple independent sources converge on the same conclusion.",
            weak_example="Single self-referential source or circular reasoning.",
            floor_example=(
                "Score 1: No evidence cited at all, or evidence is fabricated/hallucinated. "
                "Score 2: Evidence exists but does not actually support THIS claim — "
                "tangential reference or metadata-only (file exists ≠ file supports claim)."
            ),
        ),
        RubricAxis(
            name="counter_evidence_resilience",
            description="Does the claim survive known counter-evidence and objections?",
            strong_example="Addresses and refutes the strongest known counter-argument.",
            weak_example="Ignores obvious counter-evidence or alternative explanations.",
        ),
        RubricAxis(
            name="scope_honesty",
            description="Does the claim accurately bound what it covers and what it doesn't?",
            strong_example="Explicitly states what is NOT claimed and what remains uncertain.",
            weak_example="Implies universal applicability from a narrow evidence base.",
        ),
        RubricAxis(
            name="falsifiability",
            description="Could the claim be proven wrong? Is there a stated test?",
            strong_example="Names a specific observable that would falsify the claim.",
            weak_example="Claim is unfalsifiable or tautological.",
        ),
    )


class CoherenceRubric(Rubric):
    name: str = "coherence"
    version: int = 1
    instructions: str = (
        "Score the FULL segment script as a composed narrative. "
        "Evaluate whether it works as a broadcast segment that an audience "
        "would want to listen to. Score what it DOES, not what it CLAIMS."
    )
    axes: tuple[RubricAxis, ...] = (
        RubricAxis(
            name="opening_pressure",
            description="Does the opening create genuine narrative tension or curiosity?",
            strong_example=(
                "Opens with a specific paradox, failure case, or provocation that "
                "demands resolution. Names a concrete system, event, or contradiction."
            ),
            weak_example=(
                "Opens with generic context-setting: 'In the realm of X, Y is important...'"
            ),
        ),
        RubricAxis(
            name="thematic_progression",
            description="Do beats build on each other logically and thematically?",
            strong_example=(
                "Each beat advances the argument: premise → evidence → complication → "
                "resolution. Later beats reference and deepen earlier ones."
            ),
            weak_example=(
                "Beats are parallel repetitions of the same point with different words. "
                "Removing any beat wouldn't change the argument."
            ),
        ),
        RubricAxis(
            name="argumentative_specificity",
            description="Are claims grounded in named sources, not generic universals?",
            strong_example=(
                "Every claim names a specific system, paper, incident, or framework. "
                "Sources have consequences — removing one changes the argument."
            ),
            weak_example=(
                "'Mechanical governance is crucial for agent-based systems' — "
                "a universal truth that needs no sources and teaches nothing."
            ),
        ),
        RubricAxis(
            name="payoff_resolution",
            description="Does the ending satisfy the opening's promise?",
            strong_example=(
                "The closing reframes the opening hook so the audience sees it differently. "
                "The tension established in beat 0 is resolved with earned insight."
            ),
            weak_example=(
                "The closing recaps what was said or adds a generic 'in conclusion' paragraph. "
                "No transformation of understanding."
            ),
        ),
    )


class NarrativeQualityRubric(Rubric):
    name: str = "narrative_quality"
    version: int = 1
    instructions: str = (
        "Score each axis 1-5 through adversarial deliberation. "
        "The narrator is a non-anthropomorphic system with authentic perspective "
        "(enactivist sense-making, not performed personality). "
        "Evaluate structural narrative quality — does this WORK as broadcast speech? "
        "Axes evaluate FUNCTION, not surface markers."
    )
    axes: tuple[RubricAxis, ...] = (
        RubricAxis(
            name="information_gap_integrity",
            description=(
                "Does the segment open genuine bounded cognitive gaps and service "
                "them proportionately? (Loewenstein information gap theory, "
                "Barthes hermeneutic code)"
            ),
            strong_example=(
                "Opens a specific tension or contradiction the listener can feel "
                "the shape of without knowing the resolution. Gap is bounded "
                "(answerable within this segment) and progressively illuminated."
            ),
            weak_example=(
                "Opens no questions (pure recitation), or manufactures fake curiosity "
                "the system already knows the answer to, or opens gaps it never closes."
            ),
        ),
        RubricAxis(
            name="escalation_architecture",
            description=(
                "Do beats create preconditions for the next? Does the argument "
                "accumulate force rather than spending the same force repeatedly? "
                "(Burke pentad, Berlyne arousal curve)"
            ),
            strong_example=(
                "Each beat is only possible because of what preceded it. The argument "
                "gets more specific, dangerous, or committal. Reordering breaks "
                "intelligibility. There is a point of maximum tension that earlier "
                "beats built toward."
            ),
            weak_example=(
                "Beats are interchangeable mini-essays restating the thesis at the "
                "same abstraction level. The listener at beat 4 has no more framework "
                "than at beat 1."
            ),
        ),
        RubricAxis(
            name="source_consequence_density",
            description=(
                "Are claims bound to named instances that change arguments? "
                "Sources woven into reasoning, not bolted on as decoration. "
                "(Paivio dual coding, Toulmin warrants)"
            ),
            strong_example=(
                "Every claim cites a specific artifact, system, measurement, or "
                "incident. Removing a source changes the argument. Sources produce "
                "discoveries the audience could not predict from any single source."
            ),
            weak_example=(
                "Vague gestures at 'research shows' or 'many experts agree'. "
                "Sources mentioned but relationship to claim is implicit. "
                "'According to X' appended mechanically without consequence."
            ),
        ),
        RubricAxis(
            name="focalization_integrity",
            description=(
                "Does the segment maintain external focalization appropriate to "
                "a non-anthropomorphic narrator with authentic perspective? "
                "(Genette narratology, HARDM governance, enactivist sense-making)"
            ),
            strong_example=(
                "Reports processing, observations, and judgments as genuine system "
                "outputs. Claims force from evidence and source consequence. "
                "'This pattern indicates X' not 'I find this fascinating'. "
                "Voice is forceful through precision and situated authority."
            ),
            weak_example=(
                "Performs enthusiasm, simulated curiosity, artificial warmth, or "
                "fake stakes. Uses 'we/let us/I feel' constructions. OR: robotic "
                "flatness with no variation — technically correct but no reason "
                "to attend."
            ),
        ),
        RubricAxis(
            name="evaluation_sufficiency",
            description=(
                "Does the segment demonstrate why its content matters through "
                "structural means rather than emotional appeal? "
                "(Labov narrative evaluation, Toulmin warrant transparency)"
            ),
            strong_example=(
                "Significance emerges from structure: contrast with prior state, "
                "quantified change, implication chains, demonstrated consequence. "
                "The 'so what' is traceable, not asserted."
            ),
            weak_example=(
                "Significance asserted through emphasis or tone ('this is crucial') "
                "rather than demonstrated through evidence. Or: no evaluation at "
                "all — sequence of events with no 'so what'."
            ),
        ),
        RubricAxis(
            name="promise_delivery_ratio",
            description=(
                "Does the closing discharge the specific tension the opening created? "
                "Are beginning and end architecturally related? "
                "(Zeigarnik effect, gestalt completion)"
            ),
            strong_example=(
                "The closing answers the specific question the opening posed, or "
                "demonstrates why that question was wrong and what the better "
                "question is. A listener remembering the opening recognizes the "
                "closing as its resolution."
            ),
            weak_example=(
                "Trails off repeating the thesis. Or: closes a different topic "
                "than the opening promised. Or: generic platitude that could end "
                "any segment on any topic."
            ),
        ),
        RubricAxis(
            name="authentic_uncertainty",
            description=(
                "Does the segment surface genuine unknowns with specific evidence "
                "gaps? Makes uncertainty productive rather than performing confidence "
                "or humility. (Enactivist sense-making, calibrated epistemic state)"
            ),
            strong_example=(
                "Names specific uncertainties with specific evidence gaps. "
                "Quantifies where possible (posteriors, sample sizes). Makes the "
                "gap productive: a research question, a source recruitment target, "
                "an operator interview prompt."
            ),
            weak_example=(
                "Claims certainty it does not have. Or: performs false modesty "
                "('there are many perspectives'). Or: acknowledges uncertainty "
                "generically without identifying what specifically is unknown."
            ),
        ),
    )
