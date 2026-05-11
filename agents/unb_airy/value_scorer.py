"""10-dimension value scoring for Unb-AIRy assertions.

The scorer combines deterministic priors with a LiteLLM ``balanced`` review.
Tests inject a fake completion callable; production callers use the LiteLLM
proxy route from ``shared.config.MODELS["balanced"]``.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shared.assertion_model import Assertion
from shared.frontmatter import parse_frontmatter_with_diagnostics

log = logging.getLogger(__name__)

ValueDimension = Literal[
    "novelty",
    "empirical_support",
    "internal_consistency",
    "generativity",
    "practical_utility",
    "formalization",
    "cross_domain",
    "explanatory_depth",
    "predictive_power",
    "elegance",
]

VALUE_DIMENSIONS: tuple[ValueDimension, ...] = (
    "novelty",
    "empirical_support",
    "internal_consistency",
    "generativity",
    "practical_utility",
    "formalization",
    "cross_domain",
    "explanatory_depth",
    "predictive_power",
    "elegance",
)

DEFAULT_VALUE_SCORE_WEIGHTS: dict[ValueDimension, float] = {
    "novelty": 0.10,
    "empirical_support": 0.15,
    "internal_consistency": 0.12,
    "generativity": 0.10,
    "practical_utility": 0.12,
    "formalization": 0.08,
    "cross_domain": 0.08,
    "explanatory_depth": 0.10,
    "predictive_power": 0.08,
    "elegance": 0.07,
}

SCORER_VERSION = "unb-airy-value-scorer-v1"

CompletionFn = Callable[..., Any]

_GENERATIVE_TERMS = frozenset(
    {
        "enable",
        "enables",
        "generate",
        "generates",
        "imply",
        "implies",
        "derive",
        "derives",
        "connect",
        "connects",
        "compose",
        "composes",
        "surface",
        "surfaces",
    }
)
_PRACTICAL_TERMS = frozenset(
    {
        "must",
        "never",
        "always",
        "should",
        "route",
        "write",
        "store",
        "validate",
        "block",
        "allow",
        "use",
        "run",
        "create",
        "update",
    }
)
_PREDICTIVE_TERMS = frozenset(
    {
        "if",
        "then",
        "when",
        "predict",
        "predicts",
        "forecast",
        "forecasting",
        "future",
        "before",
        "after",
        "leads",
        "causes",
    }
)
_EXPLANATORY_TERMS = frozenset(
    {
        "because",
        "therefore",
        "why",
        "mechanism",
        "ground",
        "grounds",
        "explains",
        "evidence",
        "causal",
        "reason",
    }
)
_FORMAL_MARKERS_RE = re.compile(r"[=<>]|->|=>|::|\b[A-Z_]{3,}\b")


class ValueScoringError(RuntimeError):
    """Raised when an assertion cannot be scored as requested."""


class CompletionLike(Protocol):
    """Minimal completion response shape used by LiteLLM and tests."""

    choices: Sequence[Any]


class ValueScore(BaseModel):
    """Ten bounded value dimensions for one assertion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    novelty: float = Field(ge=0.0, le=1.0)
    empirical_support: float = Field(ge=0.0, le=1.0)
    internal_consistency: float = Field(ge=0.0, le=1.0)
    generativity: float = Field(ge=0.0, le=1.0)
    practical_utility: float = Field(ge=0.0, le=1.0)
    formalization: float = Field(ge=0.0, le=1.0)
    cross_domain: float = Field(ge=0.0, le=1.0)
    explanatory_depth: float = Field(ge=0.0, le=1.0)
    predictive_power: float = Field(ge=0.0, le=1.0)
    elegance: float = Field(ge=0.0, le=1.0)

    def dimensions(self) -> dict[ValueDimension, float]:
        """Return dimension scores in canonical order."""

        return {dimension: float(getattr(self, dimension)) for dimension in VALUE_DIMENSIONS}

    def composite(
        self,
        weights: Mapping[ValueDimension, float] | None = None,
    ) -> float:
        """Compute a normalized weighted composite in the 0.0-1.0 range."""

        resolved_weights = weights or DEFAULT_VALUE_SCORE_WEIGHTS
        weight_sum = sum(
            max(0.0, float(resolved_weights.get(dim, 0.0))) for dim in VALUE_DIMENSIONS
        )
        if weight_sum <= 0.0:
            raise ValueError("at least one value-score weight must be positive")
        total = sum(
            getattr(self, dim) * max(0.0, float(resolved_weights.get(dim, 0.0)))
            for dim in VALUE_DIMENSIONS
        )
        return round(_bounded(total / weight_sum), 4)


class _LLMValueScore(ValueScore):
    rationale: str = Field(default="", max_length=1200)


ScoringMode = Literal["heuristic", "llm", "hybrid", "heuristic_fallback"]


class AssertionValueScoring(BaseModel):
    """Scoring envelope for persistence on an assertion or assertion note."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assertion_id: str
    scores: ValueScore
    composite: float = Field(ge=0.0, le=1.0)
    weights: dict[ValueDimension, float]
    scoring_mode: ScoringMode
    scoring_model: str
    scorer_version: str = SCORER_VERSION
    rationale: str = ""
    scored_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def frontmatter_payload(self) -> dict[str, Any]:
        """Return the frontmatter shape used by assertion markdown notes."""

        return {
            "value_score": round(self.composite, 4),
            "assertion_value_score": {
                "dimensions": {
                    key: round(value, 4) for key, value in self.scores.dimensions().items()
                },
                "composite": round(self.composite, 4),
                "weights": {key: round(value, 4) for key, value in self.weights.items()},
                "mode": self.scoring_mode,
                "model": self.scoring_model,
                "scorer_version": self.scorer_version,
                "scored_at": self.scored_at.isoformat(),
                "rationale": self.rationale,
            },
        }


def score_assertion_heuristic(
    assertion: Assertion,
    *,
    weights: Mapping[ValueDimension, float] | None = None,
    scored_at: datetime | None = None,
) -> AssertionValueScoring:
    """Score an assertion using deterministic signals only."""

    scores = _heuristic_scores(assertion)
    return AssertionValueScoring(
        assertion_id=assertion.assertion_id,
        scores=scores,
        composite=scores.composite(weights),
        weights=_normalized_weight_dict(weights),
        scoring_mode="heuristic",
        scoring_model="heuristic",
        rationale="Deterministic lexical, provenance, type, and source-structure priors.",
        scored_at=scored_at or datetime.now(UTC),
    )


def score_assertion(
    assertion: Assertion,
    *,
    model_alias: str = "balanced",
    completion_fn: CompletionFn | None = None,
    use_llm: bool = True,
    allow_heuristic_fallback: bool = False,
    weights: Mapping[ValueDimension, float] | None = None,
    scored_at: datetime | None = None,
) -> AssertionValueScoring:
    """Score one assertion across the ten Unb-AIRy value dimensions."""

    heuristic = score_assertion_heuristic(assertion, weights=weights, scored_at=scored_at)
    if not use_llm:
        return heuristic

    model_id = _model_id(model_alias)
    try:
        llm_score = _score_assertion_with_litellm(
            assertion,
            model_id=model_id,
            completion_fn=completion_fn,
        )
    except Exception as exc:
        if not allow_heuristic_fallback:
            raise ValueScoringError(f"LiteLLM value scoring failed: {exc}") from exc
        return heuristic.model_copy(
            update={
                "scoring_mode": "heuristic_fallback",
                "scoring_model": model_id,
                "rationale": f"LiteLLM scoring failed; used heuristic fallback. {exc}",
            }
        )

    scores = _blend_scores(heuristic.scores, llm_score, heuristic_weight=0.35)
    return AssertionValueScoring(
        assertion_id=assertion.assertion_id,
        scores=scores,
        composite=scores.composite(weights),
        weights=_normalized_weight_dict(weights),
        scoring_mode="hybrid",
        scoring_model=model_id,
        rationale=llm_score.rationale,
        scored_at=scored_at or datetime.now(UTC),
    )


def score_assertions(
    assertions: Iterable[Assertion],
    *,
    model_alias: str = "balanced",
    completion_fn: CompletionFn | None = None,
    use_llm: bool = True,
    allow_heuristic_fallback: bool = False,
    weights: Mapping[ValueDimension, float] | None = None,
) -> list[AssertionValueScoring]:
    """Score a batch of assertions in input order."""

    return [
        score_assertion(
            assertion,
            model_alias=model_alias,
            completion_fn=completion_fn,
            use_llm=use_llm,
            allow_heuristic_fallback=allow_heuristic_fallback,
            weights=weights,
        )
        for assertion in assertions
    ]


def apply_value_score(assertion: Assertion, scoring: AssertionValueScoring) -> Assertion:
    """Return a copy of ``assertion`` with composite and dimension scores set."""

    if assertion.assertion_id != scoring.assertion_id:
        raise ValueError("scoring assertion_id does not match assertion")
    return assertion.model_copy(
        update={
            "score": scoring.composite,
            "value_scores": scoring.scores.dimensions(),
        }
    )


def store_score_in_frontmatter(path: Path, scoring: AssertionValueScoring) -> bool:
    """Write score fields into an assertion markdown note's YAML frontmatter."""

    result = parse_frontmatter_with_diagnostics(path)
    if not result.ok or result.frontmatter is None:
        raise ValueError(f"cannot update assertion frontmatter: {result.error_message}")

    frontmatter = dict(result.frontmatter)
    payload = scoring.frontmatter_payload()
    changed = any(frontmatter.get(key) != value for key, value in payload.items())
    if not changed:
        return False

    frontmatter.update(payload)
    rendered = yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False)
    text = f"---\n{rendered}---\n{result.body}"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return True


def _score_assertion_with_litellm(
    assertion: Assertion,
    *,
    model_id: str,
    completion_fn: CompletionFn | None,
) -> _LLMValueScore:
    completion = completion_fn or _default_completion_fn()
    messages = _scoring_messages(assertion)
    response = completion(
        model=model_id,
        messages=messages,
        temperature=0.0,
        max_tokens=900,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "unb_airy_assertion_value_score",
                "strict": True,
                "schema": _LLMValueScore.model_json_schema(),
            },
        },
        **_litellm_proxy_kwargs(completion_fn),
    )
    content = _completion_content(cast("CompletionLike", response))
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueScoringError("LiteLLM response was not JSON") from exc
    try:
        return _LLMValueScore.model_validate(payload)
    except ValidationError as exc:
        raise ValueScoringError("LiteLLM response did not match value-score schema") from exc


def _default_completion_fn() -> CompletionFn:
    import litellm

    return litellm.completion


def _model_id(alias_or_id: str) -> str:
    from shared.config import MODELS

    return MODELS.get(alias_or_id, alias_or_id)


def _litellm_proxy_kwargs(completion_fn: CompletionFn | None) -> dict[str, Any]:
    if completion_fn is not None:
        return {}
    from shared.config import LITELLM_BASE, LITELLM_KEY

    return {
        "api_base": LITELLM_BASE,
        "api_key": LITELLM_KEY or "not-set",
    }


def _completion_content(response: CompletionLike) -> str:
    try:
        message = response.choices[0].message
        content = message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise ValueScoringError("LiteLLM response missing choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise ValueScoringError("LiteLLM response content is empty")
    return content


def _scoring_messages(assertion: Assertion) -> list[dict[str, str]]:
    rubric = "\n".join(
        [
            "- novelty: non-obviousness relative to the local assertion corpus.",
            "- empirical_support: direct evidence, provenance, observability, or source support.",
            "- internal_consistency: absence of contradiction and logical self-coherence.",
            "- generativity: ability to open useful follow-on questions, decompositions, or artifacts.",
            "- practical_utility: usefulness for decisions, operations, implementation, or planning.",
            "- formalization: precision, structure, typedness, or readiness for formal representation.",
            "- cross_domain: ability to bridge domains without losing specificity.",
            "- explanatory_depth: mechanism, causal account, or reason-giving depth.",
            "- predictive_power: ability to constrain future observations or expectations.",
            "- elegance: concise, simple, compressive expression without losing substance.",
        ]
    )
    assertion_payload = {
        "assertion_id": assertion.assertion_id,
        "text": assertion.text,
        "atomic_facts": assertion.atomic_facts,
        "source_type": assertion.source_type.value,
        "source_uri": assertion.source_uri,
        "source_span": assertion.source_span,
        "confidence": assertion.confidence,
        "domain": assertion.domain,
        "assertion_type": assertion.assertion_type.value,
        "tags": assertion.tags,
        "supersedes": assertion.supersedes,
        "superseded_by": assertion.superseded_by,
    }
    return [
        {
            "role": "system",
            "content": (
                "You score Unb-AIRy assertion-plane records. Return JSON only. "
                "Every dimension must be a float from 0.0 to 1.0. Penalize vague, "
                "unsupported, contradictory, or merely decorative assertions."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Rubric:\n{rubric}\n\n"
                "Score this assertion. Include a concise rationale.\n"
                f"{json.dumps(assertion_payload, sort_keys=True)}"
            ),
        },
    ]


def _heuristic_scores(assertion: Assertion) -> ValueScore:
    text = assertion.text.strip()
    words = _words(text)
    unique_ratio = len(set(words)) / max(len(words), 1)
    lower_words = frozenset(words)
    tags = [tag.lower() for tag in assertion.tags]
    source_has_span = assertion.source_span is not None
    is_superseded = assertion.superseded_by is not None
    has_contradiction = any("contradict" in tag for tag in tags)

    novelty = 0.25 + 0.35 * unique_ratio + _keyword_bonus(tags, ("novel", "new", "gap"))
    if is_superseded:
        novelty -= 0.25

    empirical_support = 0.20 + 0.45 * _bounded(assertion.confidence)
    if assertion.atomic_facts:
        empirical_support += 0.12
    if source_has_span:
        empirical_support += 0.08
    if assertion.source_type.value in {"code", "config", "governance"}:
        empirical_support += 0.08

    internal_consistency = 0.82
    if has_contradiction:
        internal_consistency -= 0.35
    if not text:
        internal_consistency = 0.0

    generativity = 0.25 + _term_presence_score(lower_words, _GENERATIVE_TERMS, scale=0.55)
    if assertion.assertion_type.value in {"claim", "corollary", "implication"}:
        generativity += 0.12

    practical_utility = 0.25 + _term_presence_score(lower_words, _PRACTICAL_TERMS, scale=0.45)
    if assertion.assertion_type.value in {"constraint", "decision", "invariant", "goal"}:
        practical_utility += 0.20
    if assertion.source_type.value in {"code", "config", "task", "request"}:
        practical_utility += 0.10

    formalization = 0.20
    if assertion.atomic_facts:
        formalization += 0.20
    if assertion.source_type.value in {"code", "config", "governance"}:
        formalization += 0.25
    if _FORMAL_MARKERS_RE.search(text):
        formalization += 0.20

    domain_markers = {assertion.domain.lower(), assertion.source_type.value}
    domain_markers.update(tag.split(":", 1)[0] for tag in tags if ":" in tag)
    cross_domain = 0.18 + min(0.52, 0.10 * len({marker for marker in domain_markers if marker}))
    if any(term in lower_words for term in {"bridge", "across", "between", "multimodal"}):
        cross_domain += 0.18

    explanatory_depth = 0.22 + _term_presence_score(lower_words, _EXPLANATORY_TERMS, scale=0.45)
    if len(words) >= 18:
        explanatory_depth += 0.10
    if assertion.atomic_facts:
        explanatory_depth += 0.10

    predictive_power = 0.18 + _term_presence_score(lower_words, _PREDICTIVE_TERMS, scale=0.55)
    if assertion.assertion_type.value in {"implication", "invariant"}:
        predictive_power += 0.15

    length_penalty = max(0.0, (len(words) - 32) / 80)
    elegance = 0.72 - length_penalty + min(0.12, unique_ratio * 0.12)
    if any(token in text for token in ("TODO", "<unparseable>", "???")):
        elegance -= 0.20

    return ValueScore(
        novelty=_bounded_round(novelty),
        empirical_support=_bounded_round(empirical_support),
        internal_consistency=_bounded_round(internal_consistency),
        generativity=_bounded_round(generativity),
        practical_utility=_bounded_round(practical_utility),
        formalization=_bounded_round(formalization),
        cross_domain=_bounded_round(cross_domain),
        explanatory_depth=_bounded_round(explanatory_depth),
        predictive_power=_bounded_round(predictive_power),
        elegance=_bounded_round(elegance),
    )


def _blend_scores(
    heuristic: ValueScore,
    llm: ValueScore,
    *,
    heuristic_weight: float,
) -> ValueScore:
    h = _bounded(heuristic_weight)
    llm_weight = 1.0 - h
    return ValueScore(
        **{
            dimension: _bounded_round(
                getattr(heuristic, dimension) * h + getattr(llm, dimension) * llm_weight
            )
            for dimension in VALUE_DIMENSIONS
        }
    )


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9_-]*", text.lower())


def _keyword_bonus(values: Sequence[str], keywords: Sequence[str]) -> float:
    joined = " ".join(values)
    return 0.08 if any(keyword in joined for keyword in keywords) else 0.0


def _term_presence_score(words: frozenset[str], terms: frozenset[str], *, scale: float) -> float:
    if not words:
        return 0.0
    hits = len(words & terms)
    return min(scale, hits * scale / 3)


def _bounded(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _bounded_round(value: float) -> float:
    return round(_bounded(value), 4)


def _normalized_weight_dict(
    weights: Mapping[ValueDimension, float] | None,
) -> dict[ValueDimension, float]:
    resolved = weights or DEFAULT_VALUE_SCORE_WEIGHTS
    return {dimension: float(resolved.get(dimension, 0.0)) for dimension in VALUE_DIMENSIONS}


def _load_assertions(path: Path) -> tuple[list[Assertion], dict[str, Any] | None]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [Assertion.model_validate(item) for item in payload], None
    if isinstance(payload, dict) and isinstance(payload.get("assertions"), list):
        return [Assertion.model_validate(item) for item in payload["assertions"]], payload
    raise ValueError("input must be a JSON array or object with an assertions array")


def _score_output_payload(
    assertions: Sequence[Assertion],
    scorings: Sequence[AssertionValueScoring],
    original_payload: dict[str, Any] | None,
) -> Any:
    scored_assertions = [
        apply_value_score(assertion, scoring).model_dump(mode="json")
        for assertion, scoring in zip(assertions, scorings, strict=True)
    ]
    if original_payload is None:
        return scored_assertions
    output = dict(original_payload)
    output["assertions"] = scored_assertions
    output["value_scoring"] = {
        "scorer_version": SCORER_VERSION,
        "scored_at": datetime.now(UTC).isoformat(),
        "dimensions": list(VALUE_DIMENSIONS),
    }
    return output


def _update_frontmatter_dir(
    frontmatter_dir: Path,
    scorings: Iterable[AssertionValueScoring],
) -> int:
    updated = 0
    for scoring in scorings:
        path = frontmatter_dir / f"{scoring.assertion_id}.md"
        if not path.exists():
            continue
        if store_score_in_frontmatter(path, scoring):
            updated += 1
    return updated


def _cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score Unb-AIRy assertions across 10 dimensions.")
    parser.add_argument(
        "input", type=Path, help="JSON array or {assertions: [...]} extraction output."
    )
    parser.add_argument("-o", "--output", type=Path, help="Output JSON path. Defaults to stdout.")
    parser.add_argument(
        "--model",
        default="balanced",
        help="LiteLLM model alias or id for LLM scoring. Default: balanced.",
    )
    parser.add_argument(
        "--no-llm", action="store_true", help="Use deterministic heuristic scoring only."
    )
    parser.add_argument(
        "--fallback-heuristic",
        action="store_true",
        help="Use heuristic scores if the LiteLLM call fails.",
    )
    parser.add_argument(
        "--frontmatter-dir",
        type=Path,
        help="Optional directory of <assertion_id>.md notes to update with score frontmatter.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        assertions, original_payload = _load_assertions(args.input)
        scorings = score_assertions(
            assertions,
            model_alias=args.model,
            use_llm=not args.no_llm,
            allow_heuristic_fallback=args.fallback_heuristic,
        )
        if args.frontmatter_dir is not None:
            updated = _update_frontmatter_dir(args.frontmatter_dir, scorings)
            log.info("updated %d assertion frontmatter notes", updated)
        output_payload = _score_output_payload(assertions, scorings, original_payload)
        output = json.dumps(output_payload, indent=2, sort_keys=True)
        if args.output is not None:
            args.output.write_text(output + "\n", encoding="utf-8")
        else:
            sys.stdout.write(output + "\n")
    except Exception as exc:  # noqa: BLE001
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())


__all__ = [
    "AssertionValueScoring",
    "DEFAULT_VALUE_SCORE_WEIGHTS",
    "SCORER_VERSION",
    "VALUE_DIMENSIONS",
    "ValueDimension",
    "ValueScore",
    "ValueScoringError",
    "apply_value_score",
    "score_assertion",
    "score_assertion_heuristic",
    "score_assertions",
    "store_score_in_frontmatter",
]
