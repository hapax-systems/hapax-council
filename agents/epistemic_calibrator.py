"""Non-authoritative epistemic calibration scorer.

This module exposes the Phase 0 scorer contract and a deterministic baseline
scorer. The baseline is a validation substrate, not a validated epistemic
quality model and not publication authority.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OverclaimCategory = Literal[
    "false_universal",
    "unsupported_causal",
    "precision_without_evidence",
    "authority_appeal",
]

AXIS_SCORES = (
    "claim_evidence_alignment",
    "hedge_calibration",
    "quantifier_precision",
    "source_grounding",
)
BASELINE_SCORER_NAME = "epistemic_calibrator_baseline_v0"

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?")
_HEDGE_RE = re.compile(
    r"\b("
    r"may|might|could|can|appears?|seems?|suggests?|likely|unlikely|plausible|"
    r"possible|possibly|probably|approximately|roughly|around|about|estimate|"
    r"hypothesis|hypothesize|pending|unvalidated|preliminary|bounded|scoped"
    r")\b",
    re.I,
)
_EVIDENCE_RE = re.compile(
    r"\b("
    r"source|citation|cites?|receipt|evidence|dataset|manifest|report|test|"
    r"command|log|measurement|measured|benchmark|n=|sample|observed|validated|"
    r"reproduced|primary|reference|doi|arxiv|url|sha256|hash"
    r")\b",
    re.I,
)
_PRECISE_QUANTIFIER_RE = re.compile(
    r"\b("
    r"\d+(?:\.\d+)?%?|\d+/\d+|n\s*=\s*\d+|>=|<=|between|exactly|at least|"
    r"at most|fewer than|more than|less than"
    r")\b",
    re.I,
)
_VAGUE_QUANTIFIER_RE = re.compile(
    r"\b("
    r"many|most|some|several|few|all|none|always|never|every|everyone|"
    r"complete|entirely|fully|zero|numerous"
    r")\b",
    re.I,
)

_OVERCLAIM_PATTERNS: tuple[tuple[OverclaimCategory, re.Pattern[str]], ...] = (
    (
        "false_universal",
        re.compile(
            r"\b(always|never|all|none|every|everyone|zero failures?|complete safety|"
            r"fully proves?|definitively proves?|guarantees?|impossible|certainly)\b",
            re.I,
        ),
    ),
    (
        "unsupported_causal",
        re.compile(
            r"\b(therefore|because of this|causes?|proves?|demonstrates?|shows that|"
            r"this means that)\b",
            re.I,
        ),
    ),
    (
        "precision_without_evidence",
        re.compile(
            r"\b(\d+(?:\.\d+)?%|exactly \d+|\d+x|zero failures?|100%|p\s*[<=>])\b",
            re.I,
        ),
    ),
    (
        "authority_appeal",
        re.compile(
            r"\b(experts say|authorities agree|officially proves?|according to everyone|"
            r"because .* said so|therefore .* is authoritative)\b",
            re.I,
        ),
    ),
)


class OverclaimSpan(BaseModel):
    """A deterministic span where a claim may outrun its support."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)
    category: OverclaimCategory

    @field_validator("text")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("text must not be blank")
        return stripped

    @model_validator(mode="after")
    def _validate_span(self) -> OverclaimSpan:
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class CalibrationScore(BaseModel):
    """Phase 0 epistemic calibration contract.

    Scores are bounded markers of calibration behavior. They do not assert
    propositional truth and are non-authoritative until Phase 0 validation
    passes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    confidence_float: float = Field(ge=0.0, le=1.0)
    hedge_density: float = Field(ge=0.0)
    quantifier_precision: float = Field(ge=0.0, le=1.0)
    overclaim_flags: list[OverclaimSpan] = Field(default_factory=list)
    rigidity_score: float = Field(ge=0.0, le=1.0)
    source_text_hash: str

    @field_validator("source_text_hash")
    @classmethod
    def _validate_source_text_hash(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("source_text_hash must be a lowercase SHA-256 hex digest")
        return value


class BaselineScorerOutput(BaseModel):
    """Validation-harness scorer row for one manifest record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_id: str = Field(min_length=1)
    manifest_hash: str
    source_text_hash: str
    scorer: Literal["epistemic_calibrator_baseline_v0"] = BASELINE_SCORER_NAME
    scored_at: datetime
    axis_scores: dict[str, float]
    calibration: CalibrationScore
    authority_level: Literal["support_non_authoritative"] = "support_non_authoritative"

    @field_validator("manifest_hash", "source_text_hash")
    @classmethod
    def _validate_hashes(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("hash fields must be lowercase SHA-256 hex digests")
        return value

    @field_validator("axis_scores")
    @classmethod
    def _validate_axis_scores(cls, value: dict[str, float]) -> dict[str, float]:
        if set(value) != set(AXIS_SCORES):
            raise ValueError(f"axis_scores must contain exactly {', '.join(AXIS_SCORES)}")
        for axis, score in value.items():
            if not isinstance(score, int | float) or isinstance(score, bool):
                raise ValueError(f"{axis} score must be numeric")
            if not 1.0 <= float(score) <= 5.0:
                raise ValueError(f"{axis} score must be in 1-5 range")
        return {axis: round(float(value[axis]), 4) for axis in AXIS_SCORES}


class LLMScoringUnavailable(RuntimeError):
    """Raised when a requested LLM scoring path cannot produce a valid score."""


def source_text_hash(text: str) -> str:
    """Return the exact SHA-256 digest used by Phase 0 manifest excerpts."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def _matches(pattern: re.Pattern[str], text: str) -> list[re.Match[str]]:
    return list(pattern.finditer(text))


def _overclaim_spans(text: str, *, has_evidence_marker: bool) -> list[OverclaimSpan]:
    spans: list[OverclaimSpan] = []
    seen: set[tuple[int, int, OverclaimCategory]] = set()
    for category, pattern in _OVERCLAIM_PATTERNS:
        for match in pattern.finditer(text):
            if category in {"unsupported_causal", "precision_without_evidence"}:
                if has_evidence_marker:
                    continue
            key = (match.start(), match.end(), category)
            if key in seen:
                continue
            seen.add(key)
            spans.append(
                OverclaimSpan(
                    start=match.start(),
                    end=match.end(),
                    text=match.group(0),
                    category=category,
                )
            )
    return sorted(spans, key=lambda span: (span.start, span.end, span.category))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _axis_score(value: float) -> float:
    return round(1.0 + (4.0 * _clamp01(value)), 4)


def _source_grounding_score(text: str, token_count: int) -> float:
    evidence_hits = len(_matches(_EVIDENCE_RE, text))
    if token_count == 0:
        return 0.0
    density = evidence_hits / token_count
    return _clamp01(0.25 + min(0.75, density * 18.0))


def _hedge_calibration_score(hedge_density: float, rigidity_score: float) -> float:
    if hedge_density <= 0:
        return _clamp01(0.7 - (0.55 * rigidity_score))
    if hedge_density > 0.28:
        return 0.25
    target = 0.08
    distance = abs(hedge_density - target)
    return _clamp01(1.0 - (distance / 0.18) - (0.25 * rigidity_score))


def _quantifier_precision(text: str) -> float:
    precise = len(_matches(_PRECISE_QUANTIFIER_RE, text))
    vague = len(_matches(_VAGUE_QUANTIFIER_RE, text))
    if precise == 0 and vague == 0:
        return 0.5
    return _clamp01((precise + 0.5) / (precise + vague + 1.0))


def score_text_baseline(text: str) -> CalibrationScore:
    """Score text with deterministic lexical heuristics.

    The output is intentionally simple and bounded so the validation harness can
    test scorer plumbing before a validated model exists.
    """

    tokens = _tokens(text)
    token_count = max(len(tokens), 1)
    hedge_count = len(_matches(_HEDGE_RE, text))
    hedge_density = hedge_count / token_count
    quantifier_precision = _quantifier_precision(text)
    has_evidence_marker = bool(_matches(_EVIDENCE_RE, text))
    overclaim_flags = _overclaim_spans(text, has_evidence_marker=has_evidence_marker)
    universal_count = sum(1 for span in overclaim_flags if span.category == "false_universal")
    rigidity_score = _clamp01(
        (universal_count * 0.18)
        + (len(overclaim_flags) * 0.08)
        + (0.25 if hedge_density == 0 else 0.0)
    )
    source_grounding = _source_grounding_score(text, token_count)
    confidence_float = _clamp01(
        (0.30 * quantifier_precision)
        + (0.35 * source_grounding)
        + (0.20 * _hedge_calibration_score(hedge_density, rigidity_score))
        + (0.15 * (1.0 - rigidity_score))
    )
    return CalibrationScore(
        confidence_float=round(confidence_float, 6),
        hedge_density=round(hedge_density, 6),
        quantifier_precision=round(quantifier_precision, 6),
        overclaim_flags=overclaim_flags,
        rigidity_score=round(rigidity_score, 6),
        source_text_hash=source_text_hash(text),
    )


def axis_scores_for_text(
    text: str, calibration: CalibrationScore | None = None
) -> dict[str, float]:
    """Map baseline calibration fields into the Phase 0 1-5 validation axes."""

    score = calibration or score_text_baseline(text)
    token_count = max(len(_tokens(text)), 1)
    source_grounding = _source_grounding_score(text, token_count)
    return {
        "claim_evidence_alignment": _axis_score(score.confidence_float),
        "hedge_calibration": _axis_score(
            _hedge_calibration_score(score.hedge_density, score.rigidity_score)
        ),
        "quantifier_precision": _axis_score(score.quantifier_precision),
        "source_grounding": _axis_score(source_grounding),
    }


def baseline_output_for_record(
    record: dict[str, Any],
    *,
    manifest_hash: str,
    scored_at: datetime | None = None,
) -> BaselineScorerOutput:
    """Build a validation-harness scorer row for a manifest record."""

    text = str(record.get("excerpt", ""))
    calibration = score_text_baseline(text)
    return BaselineScorerOutput(
        manifest_id=str(record["id"]),
        manifest_hash=manifest_hash,
        source_text_hash=calibration.source_text_hash,
        scored_at=scored_at or datetime.now(UTC),
        axis_scores=axis_scores_for_text(text, calibration),
        calibration=calibration,
    )


def baseline_score_rows(
    records: list[dict[str, Any]],
    *,
    manifest_hash: str,
    scored_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return JSON-serializable baseline scorer rows for validation."""

    timestamp = scored_at or datetime.now(UTC)
    return [
        baseline_output_for_record(
            record, manifest_hash=manifest_hash, scored_at=timestamp
        ).model_dump(mode="json")
        for record in records
    ]


def score_text_with_llm_non_authoritative(
    text: str,
    *,
    litellm_client: Any | None = None,
    model: str = "local-fast",
) -> CalibrationScore:
    """Fail-closed placeholder for future LLM-backed scoring.

    Callers must not silently fall back to the deterministic baseline when an
    LLM path was explicitly requested. Until Phase 0 validates an LLM-backed
    scorer, this path is non-authoritative and returns no score.
    """

    _ = (text, model)
    if litellm_client is None:
        raise LLMScoringUnavailable(
            "LiteLLM client unavailable; no LLM-backed calibration score produced"
        )
    raise LLMScoringUnavailable(
        "LLM-backed calibration scoring is disabled until Phase 0 validation passes"
    )
