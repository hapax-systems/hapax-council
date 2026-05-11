"""Cross-provider LLM review gate for publication artifacts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Literal, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.publication_hardening.entity_checker import check_attributions, load_registry

DEFAULT_REVIEW_MODEL = "balanced"
DEFAULT_REVIEW_THRESHOLD = 0.7

AXIOM_REVIEW_IDS: tuple[str, ...] = (
    "single_user",
    "executive_function",
    "corporate_boundary",
    "interpersonal_transparency",
    "management_governance",
)

AXIOM_REVIEW_SUMMARIES: dict[str, str] = {
    "single_user": "do not introduce community show-control, request queues, or role workflows",
    "executive_function": "be concrete, actionable, and avoid hidden operator labor",
    "corporate_boundary": "do not route employer/private data into public surfaces",
    "interpersonal_transparency": (
        "do not persist claims about non-operator people without consent"
    ),
    "management_governance": "LLMs may prepare text, but humans own managerial decisions",
}


class CompletionFn(Protocol):
    def __call__(
        self,
        *,
        model: str,
        messages: tuple[dict[str, str], ...],
        temperature: float,
        max_tokens: int,
    ) -> str: ...


class PublicationReviewModel(BaseModel):
    """Strict immutable base for review outputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ReviewClaim(PublicationReviewModel):
    """One reviewed claim extracted from a draft."""

    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    issues: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("issues", mode="before")
    @classmethod
    def _coerce_issues(cls, value: object) -> tuple[str, ...]:
        return _tuple_strings(value)


class ReviewReport(PublicationReviewModel):
    """Structured report returned by the publication review gate."""

    schema_version: Literal[1] = 1
    reviewer_model: str
    author_model: str | None = None
    claims: tuple[ReviewClaim, ...] = Field(default_factory=tuple)
    overall_confidence: float = Field(ge=0.0, le=1.0)
    flagged_issues: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("claims", mode="before")
    @classmethod
    def _coerce_claims(cls, value: object) -> tuple[ReviewClaim, ...]:
        if value is None:
            return ()
        if isinstance(value, Sequence) and not isinstance(value, str):
            return tuple(
                item if isinstance(item, ReviewClaim) else ReviewClaim.model_validate(item)
                for item in value
            )
        return ()

    @field_validator("flagged_issues", mode="before")
    @classmethod
    def _coerce_flagged_issues(cls, value: object) -> tuple[str, ...]:
        return _tuple_strings(value)

    def passes(self, *, threshold: float = DEFAULT_REVIEW_THRESHOLD) -> bool:
        return self.overall_confidence >= threshold

    def to_frontmatter(self) -> dict[str, object]:
        return self.model_dump(mode="json")


@dataclass(frozen=True)
class ReviewPass:
    """LLM-backed review pass for outbound publication text."""

    model: str = DEFAULT_REVIEW_MODEL
    threshold: float = DEFAULT_REVIEW_THRESHOLD
    completion: CompletionFn | None = None
    registry_path: Path | None = None
    timeout_s: float = 30.0

    def review_text(
        self,
        text: str,
        *,
        author_model: str | None = None,
        lint_report: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> ReviewReport:
        """Review publication text and return a structured confidence report.

        Failures are represented as low-confidence reports so callers can
        consistently hold for operator review instead of accidentally sending.
        """

        deterministic_issues = self._deterministic_issues(text)
        messages = build_review_messages(
            text,
            author_model=author_model,
            lint_report=lint_report,
            axiom_constraints=axiom_review_constraints(),
            known_entities_summary=self._known_entities_summary(),
            deterministic_issues=deterministic_issues,
            metadata=metadata,
        )
        try:
            raw = self._completion()(
                model=self.model, messages=messages, temperature=0.0, max_tokens=900
            )
        except Exception as exc:  # noqa: BLE001 - fail closed as a report
            return ReviewReport(
                reviewer_model=self.model,
                author_model=author_model,
                overall_confidence=0.0,
                flagged_issues=(f"review_call_failed: {type(exc).__name__}",),
            )

        report = parse_review_response(raw, reviewer_model=self.model, author_model=author_model)
        if deterministic_issues:
            issues = tuple(dict.fromkeys((*report.flagged_issues, *deterministic_issues)))
            return ReviewReport(
                reviewer_model=report.reviewer_model,
                author_model=report.author_model,
                claims=report.claims,
                overall_confidence=min(report.overall_confidence, self.threshold - 0.01),
                flagged_issues=issues,
            )
        return report

    def _completion(self) -> CompletionFn:
        if self.completion is not None:
            return self.completion
        return partial(_call_litellm_gateway, timeout_s=self.timeout_s)

    def _known_entities_summary(self) -> str:
        registry = load_registry(self.registry_path)
        items = sorted(registry.product_to_company.items())
        return "; ".join(f"{product} -> {company}" for product, company in items[:80])

    def _deterministic_issues(self, text: str) -> tuple[str, ...]:
        findings = check_attributions(text, registry_path=self.registry_path)
        return tuple(
            f"known_entity_misattribution: {finding.product} attributed to "
            f"{finding.claimed_company}; actual {finding.actual_company}"
            for finding in findings
        )


def build_review_messages(
    text: str,
    *,
    author_model: str | None,
    lint_report: str | None,
    known_entities_summary: str,
    axiom_constraints: Sequence[str] | None = None,
    deterministic_issues: Sequence[str] = (),
    metadata: Mapping[str, object] | None = None,
) -> tuple[dict[str, str], ...]:
    """Build the review prompt without exposing the full axiom registry."""

    metadata_text = json.dumps(dict(metadata or {}), sort_keys=True, default=str)
    constraints = tuple(axiom_constraints or axiom_review_constraints())
    user = "\n\n".join(
        (
            "Review this outbound publication draft before any surface receives it.",
            f"Author model: {author_model or 'unknown'}",
            f"Metadata: {metadata_text}",
            "Axiom constraints:\n- " + "\n- ".join(constraints),
            f"Known entity ownership summary:\n{known_entities_summary}",
            f"Lint report:\n{lint_report or 'none supplied'}",
            "Deterministic issues:\n- " + "\n- ".join(deterministic_issues or ("none",)),
            f"Draft:\n{text}",
        )
    )
    return (
        {
            "role": "system",
            "content": (
                "You are an independent publication quality gate. Check quality, tone, "
                "accuracy, attribution, unsupported claims, privacy, and public-surface risk. "
                "Return JSON only with shape: "
                '{"claims":[{"text":"...","confidence":0.0,"issues":["..."]}],'
                '"overall_confidence":0.0,"flagged_issues":["..."]}. '
                "Use 0.0-1.0 confidence. Scores below 0.7 hold for operator."
            ),
        },
        {"role": "user", "content": user},
    )


def axiom_review_constraints() -> tuple[str, ...]:
    """Return five concise review constraints grounded in the axiom registry."""

    axioms_by_id = {}
    try:
        from shared.axiom_registry import load_axioms

        axioms_by_id = {axiom.id: axiom for axiom in load_axioms()}
    except Exception:  # noqa: BLE001 - prompt can still use static summaries
        axioms_by_id = {}

    constraints: list[str] = []
    for axiom_id in AXIOM_REVIEW_IDS:
        summary = AXIOM_REVIEW_SUMMARIES[axiom_id]
        axiom = axioms_by_id.get(axiom_id)
        if axiom is None:
            constraints.append(f"{axiom_id}: {summary}")
        else:
            constraints.append(f"{axiom.id} (weight {axiom.weight}): {summary}")
    return tuple(constraints)


def parse_review_response(
    raw: str,
    *,
    reviewer_model: str,
    author_model: str | None = None,
) -> ReviewReport:
    """Parse model JSON into a ReviewReport, failing closed on bad shape."""

    try:
        data = json.loads(_extract_json_object(raw))
        return ReviewReport(
            reviewer_model=reviewer_model,
            author_model=author_model,
            claims=data.get("claims", ()),
            overall_confidence=_clamp_confidence(data.get("overall_confidence")),
            flagged_issues=data.get("flagged_issues", ()),
        )
    except Exception as exc:  # noqa: BLE001 - parse failure must hold
        return ReviewReport(
            reviewer_model=reviewer_model,
            author_model=author_model,
            overall_confidence=0.0,
            flagged_issues=(f"review_parse_failed: {type(exc).__name__}",),
        )


def attach_review_report_to_frontmatter(path: Path, report: ReviewReport) -> bool:
    """Attach a review report to Markdown YAML frontmatter when available."""

    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return False
    end = text.find("\n---", 4)
    if end == -1:
        return False
    frontmatter_text = text[4:end]
    body = text[end + 4 :]
    frontmatter = yaml.safe_load(frontmatter_text) or {}
    if not isinstance(frontmatter, dict):
        return False
    frontmatter["publication_review"] = report.to_frontmatter()
    rendered = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---" + body
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(rendered, encoding="utf-8")
    tmp.replace(path)
    return True


def _call_litellm_gateway(
    *,
    model: str,
    messages: tuple[dict[str, str], ...],
    temperature: float,
    max_tokens: int,
    timeout_s: float,
) -> str:
    from openai import OpenAI

    from shared.config import LITELLM_BASE, LITELLM_KEY, MODELS

    base = LITELLM_BASE.rstrip("/")
    base_url = base if base.endswith("/v1") else f"{base}/v1"
    client = OpenAI(base_url=base_url, api_key=LITELLM_KEY or "not-set", timeout=timeout_s)
    model_id = MODELS.get(model, model)
    response = client.chat.completions.create(
        model=model_id,
        messages=list(messages),
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


def _extract_json_object(raw: str) -> str:
    stripped = raw.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if match is None:
        raise ValueError("no JSON object found")
    return match.group(0)


def _clamp_confidence(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, numeric))


def _tuple_strings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value if item is not None)
    return (str(value),)


__all__ = [
    "AXIOM_REVIEW_IDS",
    "AXIOM_REVIEW_SUMMARIES",
    "DEFAULT_REVIEW_MODEL",
    "DEFAULT_REVIEW_THRESHOLD",
    "CompletionFn",
    "ReviewClaim",
    "ReviewPass",
    "ReviewReport",
    "attach_review_report_to_frontmatter",
    "axiom_review_constraints",
    "build_review_messages",
    "parse_review_response",
]
