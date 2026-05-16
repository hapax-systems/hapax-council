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
