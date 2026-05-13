"""Hapax-authored programme planner — Phase 3 of the programme-layer plan.

The ``ProgrammePlanner`` runs at show-start and at each programme
boundary. It assembles a perceptual + vault + profile context, calls the
resident local grounded Command-R model with the
``programme_plan.md`` prompt, parses the response into a
``ProgrammePlan``, and (on validation failure) retries once with the
error message fed back as a corrective hint.

Architectural invariants enforced at this layer:

- ``plan_author`` is pinned to ``"hapax-director-planner"`` by the
  ``ProgrammePlan`` Literal field. The planner NEVER reads a user-
  supplied programme outline file; the operator authors goals + sprint
  measures + daily notes (vault is a *read source*), but does not
  author programme plans (memory ``feedback_hapax_authors_programmes``).
- Soft-prior strictness: the bias multipliers in every emitted
  programme have ``capability_bias_negative ∈ (0.0, 1.0]`` and
  ``capability_bias_positive ≥ 1.0`` (validator rejects zero or
  negative; this is the ``project_programmes_enable_grounding`` axiom
  applied at the planner output).
- Failure posture: if the LLM call fails OR validation fails twice,
  the planner returns ``None`` and the system falls through to "no
  active programme". Every consumer treats ``None`` as a soft default,
  not a fatal error (Phase 4 + 5 + 6 + 8 + 11 all handle it).

References:
- Plan §Phase 3 (``docs/superpowers/plans/2026-04-20-programme-layer-plan.md``)
- Spec §4 (``docs/research/2026-04-19-content-programming-layer-design.md``)
- shared/programme.py — ``ProgrammePlan``, ``Programme``
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from shared.programme import ProgrammePlan, is_segmented_content_role
from shared.resident_command_r import (
    RESIDENT_COMMAND_R_MODEL,
    call_resident_command_r,
    configured_resident_model,
    tabby_chat_url,
)
from shared.segment_prep_contract import is_content_evidence_ref, programme_source_readiness

log = logging.getLogger(__name__)


# Path to the prompt template. Lifted from inline so prompt drift is a
# git diff on a markdown file (matches the structural director's
# inline-vs-file split — at this scale the prompt deserves its own
# review surface).
_PROMPT_PATH = Path(__file__).parent / "prompts" / "programme_plan.md"

# Model name sent in the API request. Programme planning is content
# programming, so it is pinned to resident Command-R and fails closed on
# non-Command-R environment overrides.
DEFAULT_MODEL = RESIDENT_COMMAND_R_MODEL

# Primary and only endpoint: TabbyAPI (local inference, no external API).
# Resolve at call time so tests and launch wrappers can set HAPAX_TABBY_URL
# before the production caller runs.

# Resident Command-R programme planning is content programming, not a quick
# classification call. Keep the timeout above local long-form inference latency
# so the caller does not interrupt a still-productive resident generation.
_LLM_TIMEOUT_S: float = float(os.environ.get("HAPAX_PROGRAMME_PLANNER_LLM_TIMEOUT_S", "1200"))

# Max number of corrective retries after the first call. Spec mandates
# "retries once" (one corrective re-call), so default is 1.
DEFAULT_MAX_RETRIES = 1


LLMCallable = Callable[[str], str]

_ROLE_CONTRACT_KEYS = frozenset(
    {
        "source_packet_refs",
        "source_refs",
        "role_live_bit_mechanic",
        "event_object",
        "audience_job",
        "payoff",
        "temporality_band",
        "tier_criteria",
        "ordering_criterion",
        "bounded_claim",
        "receipt_flip",
        "media_ref",
        "timestamp_or_locator",
        "claim_under_reaction",
        "layer_refs",
        "bottom_payoff",
        "subject_ref",
        "subject_context",
        "question_ladder",
        "answer_source_policy",
        "topic_selection",
        "operator_agency_policy",
        "teaching_objective",
        "demonstration_object",
        "worked_example",
    }
)
_GENERIC_STAGE_BEAT_RE = re.compile(
    r"^\s*(?P<phase>hook|opening|intro|motivat(?:e|ion)|fram(?:e|ing)|"
    r"main(?:[_ -]?points?|[_ -]?point(?:[_ -]*\d*)?)|body|synthesi[sz]e?|"
    r"questions?|recap|closing|close)\s*:",
    re.IGNORECASE,
)


def _stage_phase_key(phase: str) -> str:
    return re.sub(r"-?\d+$", "", phase.lower().replace("_", "-").replace(" ", "-"))


def _normalized_target_programmes(target_programmes: int | None) -> int | None:
    if target_programmes is None:
        return None
    return max(1, min(5, int(target_programmes)))


def _render_target_directive(target_programmes: int | None) -> str:
    if target_programmes is None:
        return ""
    noun = "programme" if target_programmes == 1 else "programmes"
    return (
        "## Per-run programme target\n\n"
        f"For this prep run, emit exactly {target_programmes} segmented-content {noun}. "
        "This is a run-size constraint inside the normal schema range, not a runtime "
        "authority transfer. Keep all planner outputs as soft-prior programme proposals."
    )


class ProgrammePlanner:
    """Emits a ``ProgrammePlan`` for the next 2-5 programmes.

    The planner is stateless across calls — every ``plan()`` call
    re-reads inputs and re-prompts. Caching is the caller's concern
    (the daimonion typically caches the active plan + only re-plans on
    boundary or abort).
    """

    def __init__(
        self,
        *,
        llm_fn: LLMCallable | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        prompt_path: Path = _PROMPT_PATH,
    ) -> None:
        """``llm_fn`` defaults to the resident Command-R call; tests
        inject a deterministic stub. ``max_retries`` is the
        number of *additional* attempts after the first (so 1 = total
        of 2 tries: initial + one retry)."""
        self._llm_fn = llm_fn or _default_llm_fn
        self._max_retries = max_retries
        self._prompt_path = prompt_path

    # --- public API ------------------------------------------------

    def plan(
        self,
        *,
        show_id: str,
        perception: dict | None = None,
        working_mode: str | None = None,
        vault_state: dict | None = None,
        profile: dict | None = None,
        condition_history: dict | None = None,
        content_state: dict | None = None,
        fore_understanding: list[dict] | None = None,
        target_programmes: int | None = None,
    ) -> ProgrammePlan | None:
        """Compose a context block, call the LLM, validate + return.

        Every input is optional — missing inputs render as "(unavailable)"
        in the prompt so the LLM knows what's known. Returns ``None`` on
        repeated failure; the caller should treat this as "no active
        programme" (Phase 4 fall-through behaviour).
        """
        base_prompt = self._build_prompt(
            show_id=show_id,
            perception=perception,
            working_mode=working_mode,
            vault_state=vault_state,
            profile=profile,
            condition_history=condition_history,
            content_state=content_state,
            fore_understanding=fore_understanding,
            target_programmes=target_programmes,
        )

        prompt = base_prompt
        last_error: str | None = None
        for attempt in range(self._max_retries + 1):
            started = time.time()
            try:
                raw = self._llm_fn(prompt)
            except Exception:
                log.warning("programme planner LLM call failed", exc_info=True)
                return None
            elapsed = time.time() - started
            log.info(
                "programme planner LLM call returned in %.2fs (attempt %d)", elapsed, attempt + 1
            )

            parsed = self._parse_plan(raw, show_id=show_id)
            if isinstance(parsed, ProgrammePlan):
                return parsed
            last_error = parsed
            log.warning(
                "programme plan validation failed (attempt %d): %s", attempt + 1, last_error
            )
            if attempt < self._max_retries:
                prompt = self._build_retry_prompt(base_prompt, last_error)

        log.warning(
            "programme planner exhausted %d attempts; falling through to no-programme",
            self._max_retries + 1,
        )
        return None

    # --- prompt assembly -------------------------------------------

    def _build_prompt(
        self,
        *,
        show_id: str,
        perception: dict | None,
        working_mode: str | None,
        vault_state: dict | None,
        profile: dict | None,
        condition_history: dict | None,
        content_state: dict | None,
        fore_understanding: list[dict] | None = None,
        target_programmes: int | None,
    ) -> str:
        """Render the prompt template + per-call context."""
        template = self._read_prompt_template()
        target = _normalized_target_programmes(target_programmes)
        target_directive = _render_target_directive(target)
        context = self._render_context(
            show_id=show_id,
            perception=perception,
            working_mode=working_mode,
            vault_state=vault_state,
            profile=profile,
            condition_history=condition_history,
            content_state=content_state,
            fore_understanding=fore_understanding,
        )
        blocks = [block for block in (target_directive, template) if block]
        prompt_body = "\n\n".join(blocks)
        return f"{prompt_body}\n\n## Per-call context\n\n{context}"

    def _build_retry_prompt(self, base_prompt: str, error_message: str) -> str:
        """Re-prompt with the validation error message appended.

        The retry prompt explicitly reminds the LLM about the soft-prior
        strictness so a hard-gate attempt (zero multiplier) doesn't
        re-emit on attempt 2 with the same error. This is the single
        point where the planner ESCALATES the soft-prior axiom into the
        prompt — most programmes the LLM emits won't hit this path.
        """
        return (
            f"{base_prompt}\n\n## Validation error on previous attempt\n\n"
            f"```\n{error_message}\n```\n\n"
            "Re-emit the JSON. Common fixes:\n"
            "- `capability_bias_negative` values must be strictly > 0 "
            "and <= 1.0. Zero or negative is a hard gate and is REJECTED.\n"
            "- `capability_bias_positive` values must be >= 1.0.\n"
            "- Every programme's `parent_show_id` must equal the plan's "
            "`show_id`.\n"
            "- `plan_author` must be the literal string "
            '"hapax-director-planner".\n'
            "- 1-5 programmes per plan; each must have `authorship: "
            '"hapax"`.\n'
            "- Segmented-content programmes must satisfy source readiness before "
            "composition: include required `role_contract` fields such as "
            "`tier_criteria`/`ordering_criterion`; for lecture also include "
            "`teaching_objective`, `demonstration_object`, and `worked_example`. "
            "Use real source evidence refs, write concrete segment beats rather "
            "than template/example language, never copy `narrative_beat_template` "
            "or placeholder examples such as `{topic}`, replace generic stage "
            "beats like `hook: Introduce`, `motivation: Explain`, or "
            "`main point 1: ...` with source-bound beats that name the "
            "object/source/consequence, and bind layout intents to content evidence with "
            "`default_static_success_allowed: false`."
        )

    def _read_prompt_template(self) -> str:
        """Read the markdown prompt; cache on the instance.

        The cache means the file is read once per planner instance — the
        daimonion typically constructs one ProgrammePlanner at boot.
        Re-reading on every call would be cheap (~1ms) but pointlessly
        wastes the syscall.
        """
        cached = getattr(self, "_template_cache", None)
        if cached is not None:
            return cached
        try:
            cached = self._prompt_path.read_text(encoding="utf-8")
        except OSError:
            log.error(
                "programme planner prompt unreadable at %s; falling back to empty template",
                self._prompt_path,
            )
            cached = ""
        self._template_cache = cached
        return cached

    @staticmethod
    def _render_context(
        *,
        show_id: str,
        perception: dict | None,
        working_mode: str | None,
        vault_state: dict | None,
        profile: dict | None,
        condition_history: dict | None,
        content_state: dict | None,
        fore_understanding: list[dict] | None = None,
    ) -> str:
        """Render the per-call inputs as a Markdown context block.

        Uses JSON for structured inputs so the LLM can ground specific
        values in the prompt; uses ``(unavailable)`` for missing inputs
        so the LLM knows what it doesn't know rather than silently
        making up plausible values.
        """
        parts: list[str] = [f"- **Show ID**: `{show_id}`"]

        def _section(name: str, payload: dict | str | None) -> None:
            if payload is None:
                parts.append(f"- **{name}**: (unavailable)")
                return
            if isinstance(payload, str):
                parts.append(f"- **{name}**: `{payload}`")
                return
            try:
                rendered = json.dumps(payload, indent=2, default=str, sort_keys=True)
            except Exception:
                rendered = str(payload)
            parts.append(f"- **{name}**:\n```json\n{rendered}\n```")

        _section("Working mode", working_mode)
        _section("Perception", perception)
        _section("Vault state", vault_state)
        _section("Operator profile", profile)
        _section("Condition history", condition_history)
        _section("Content state", content_state)
        if fore_understanding:
            summary = [
                {
                    "topic": p.get("topic", ""),
                    "source_ref": p.get("source_ref", ""),
                    "consequence_kind": p.get("consequence_kind", ""),
                }
                for p in fore_understanding[:10]
            ]
            _section(
                "Fore-understanding (prior source-consequences)",
                {"encounters": summary, "count": len(fore_understanding)},
            )
        else:
            _section("Fore-understanding (prior source-consequences)", None)
        return "\n".join(parts)

    # --- response parsing ------------------------------------------

    @staticmethod
    def _parse_plan(raw: str, *, show_id: str) -> ProgrammePlan | str:
        """Extract + validate a ProgrammePlan JSON.

        Returns the parsed plan on success, or an error string suitable
        for the retry prompt on failure. The error string is the raw
        Pydantic message — the LLM can read it.
        """
        text = (raw or "").strip()
        if not text:
            return "empty response"
        # Tolerate code-fence wrapping despite the prompt's instruction.
        if text.startswith("```"):
            lines = text.splitlines()
            # Drop the opening fence line and a trailing ``` if present.
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as e:
            return f"JSON decode failure: {e}"
        if not isinstance(obj, dict):
            return f"top-level value must be an object, got {type(obj).__name__}"
        # Cross-check show_id at the parser level so a planner caller
        # gets a clear error before pydantic complains opaquely.
        if obj.get("show_id") != show_id:
            return (
                f"show_id mismatch: expected {show_id!r}, got {obj.get('show_id')!r}. "
                "All programmes must use the supplied show_id."
            )
        _normalize_role_contract_shape(obj)
        try:
            plan = ProgrammePlan.model_validate(obj)
        except ValidationError as e:
            return str(e)
        source_readiness_error = _segment_source_readiness_error(plan)
        if source_readiness_error:
            return source_readiness_error
        return plan


def _normalize_role_contract_shape(plan_obj: dict[str, Any]) -> None:
    """Move role-contract fields into content.role_contract before pydantic validation."""

    programmes = plan_obj.get("programmes")
    if not isinstance(programmes, list):
        return
    for programme in programmes:
        if not isinstance(programme, dict):
            continue
        content = programme.get("content")
        if not isinstance(content, dict):
            continue
        role_contract = content.get("role_contract")
        normalized: dict[str, Any] = dict(role_contract) if isinstance(role_contract, dict) else {}
        root_role_contract = programme.get("role_contract")
        if isinstance(root_role_contract, dict):
            for key, value in root_role_contract.items():
                normalized.setdefault(key, value)
        for carrier in (programme, content):
            for key in _ROLE_CONTRACT_KEYS:
                if key in carrier and key not in normalized:
                    normalized[key] = carrier[key]
        for alias in ("segment_role_contract", "format_contract", "content_role_contract"):
            alias_value = programme.get(alias) or content.get(alias)
            if isinstance(alias_value, dict):
                for key, value in alias_value.items():
                    normalized.setdefault(key, value)
        if normalized:
            content["role_contract"] = normalized
        _repair_generic_stage_segment_beats(programme, content)
        _normalize_layout_intent_evidence_refs(content)


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in (
            "source_ref",
            "id",
            "title",
            "claim",
            "consequence",
            "question_text",
            "text",
        ):
            text = _first_text(value.get(key))
            if text:
                return text
        return ""
    if isinstance(value, list | tuple):
        for item in value:
            text = _first_text(item)
            if text:
                return text
    return ""


def _contract_text(role_contract: dict[str, Any], *keys: str) -> str:
    for key in keys:
        text = _first_text(role_contract.get(key))
        if text:
            return text
    return ""


def _repair_generic_stage_segment_beats(programme: dict[str, Any], content: dict[str, Any]) -> None:
    beats = content.get("segment_beats")
    role_contract = content.get("role_contract")
    if not isinstance(beats, list) or not isinstance(role_contract, dict):
        return
    source_refs = _evidence_refs_from_value(
        [
            content.get("source_refs"),
            content.get("evidence_refs"),
            content.get("source_packet_refs"),
            content.get("asset_attributions"),
            role_contract,
        ]
    )
    source_ref = source_refs[0] if source_refs else ""
    if not source_ref:
        return
    role = str(programme.get("role") or "")
    topic = (
        _first_text(content.get("declared_topic"))
        or _first_text(content.get("narrative_beat"))
        or _contract_text(role_contract, "event_object")
        or "the segment object"
    )
    event_object = _contract_text(role_contract, "event_object") or topic
    audience_job = _contract_text(role_contract, "audience_job") or "inspect the source consequence"
    payoff = _contract_text(role_contract, "payoff") or "make the consequence auditable"
    role_mechanic = (
        _contract_text(role_contract, "role_live_bit_mechanic") or "source-backed live bit"
    )

    if role == "lecture":
        teaching_objective = _contract_text(role_contract, "teaching_objective") or topic
        demonstration_object = _contract_text(role_contract, "demonstration_object") or event_object
        worked_example = _contract_text(role_contract, "worked_example") or demonstration_object

        def replacement(phase: str) -> str:
            phase_key = _stage_phase_key(phase)
            if phase_key in {"hook", "opening", "intro", "motivate", "motivation"}:
                return (
                    f"open {topic} by citing {source_ref} and naming why "
                    f"{demonstration_object} makes {teaching_objective} inspectable"
                )
            if phase_key in {"frame", "framing", "body", "main-points", "main-point"}:
                return (
                    f"work through {worked_example} from {source_ref} and compare it "
                    f"against {demonstration_object}"
                )
            if phase_key in {"questions", "question"}:
                return (
                    f"ask What's your pick? after {source_ref} changes the audience job: "
                    f"{audience_job}"
                )
            return f"resolve {topic} by citing {source_ref}, tying {worked_example} to {payoff}"

    else:
        role_object = (
            _contract_text(
                role_contract,
                "tier_criteria",
                "ordering_criterion",
                "bounded_claim",
                "media_ref",
                "bottom_payoff",
                "subject_context",
            )
            or event_object
        )

        def replacement(phase: str) -> str:
            phase_key = _stage_phase_key(phase)
            if phase_key in {"hook", "opening", "intro", "motivate", "motivation"}:
                return (
                    f"open {topic} through {source_ref}; make {role_object} visible as "
                    f"{role_mechanic}"
                )
            if phase_key in {"questions", "question"}:
                return f"ask What's your pick? after {source_ref} changes {audience_job}"
            return (
                f"use {source_ref} to compare {role_object} against {event_object} and "
                f"land {payoff}"
            )

    repaired: list[Any] = []
    changed = False
    for beat in beats:
        if not isinstance(beat, str):
            repaired.append(beat)
            continue
        match = _GENERIC_STAGE_BEAT_RE.search(beat)
        if match is None:
            repaired.append(beat)
            continue
        repaired.append(replacement(match.group("phase")))
        changed = True
    if changed:
        content["segment_beats"] = repaired


def _evidence_refs_from_value(value: Any) -> list[str]:
    refs: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, str):
            if is_content_evidence_ref(item) and item not in refs:
                refs.append(item)
            return
        if isinstance(item, dict):
            for nested in item.values():
                visit(nested)
            return
        if isinstance(item, list | tuple):
            for nested in item:
                visit(nested)

    visit(value)
    return refs


def _normalize_layout_intent_evidence_refs(content: dict[str, Any]) -> None:
    beat_layout_intents = content.get("beat_layout_intents")
    if not isinstance(beat_layout_intents, list):
        return
    fallback_refs: list[str] = []
    for key in (
        "source_refs",
        "evidence_refs",
        "source_packet_refs",
        "asset_attributions",
        "role_contract",
    ):
        fallback_refs.extend(_evidence_refs_from_value(content.get(key)))
    fallback_refs = list(dict.fromkeys(fallback_refs))
    if not fallback_refs:
        return
    for intent in beat_layout_intents:
        if not isinstance(intent, dict):
            continue
        current_refs = _evidence_refs_from_value(
            intent.get("evidence_refs") or intent.get("evidence_ref")
        )
        if not current_refs:
            intent["evidence_refs"] = fallback_refs[:3]


def _segment_source_readiness_error(plan: ProgrammePlan) -> str | None:
    """Return a retry-ready error if any segmented programme cannot enter prep."""

    failures: list[dict[str, object]] = []
    for programme in plan.programmes:
        if not is_segmented_content_role(programme.role):
            continue
        readiness = programme_source_readiness(programme)
        if readiness.get("ok") is True:
            continue
        failures.append(
            {
                "programme_id": programme.programme_id,
                "role": getattr(programme.role, "value", str(programme.role)),
                "violations": readiness.get("violations", []),
            }
        )
    if not failures:
        return None
    return "segment source readiness failed: " + json.dumps(failures, sort_keys=True)


# --- default LLM call ------------------------------------------------


def _default_llm_fn(prompt: str) -> str:
    """Default LLM caller — resident Command-R only.

    There is intentionally no LiteLLM fallback here. Programme plans are
    content-programming artifacts; a wrong-model plan is worse than no plan.
    """
    configured_resident_model("HAPAX_PROGRAMME_PLANNER_MODEL", purpose="programme planning")
    result = call_resident_command_r(
        prompt,
        chat_url=tabby_chat_url(),
        max_tokens=8192,
        temperature=0.7,
        timeout_s=_LLM_TIMEOUT_S,
    )
    log.info("planner LLM: served by resident Command-R")
    return result


__all__ = ["DEFAULT_MAX_RETRIES", "DEFAULT_MODEL", "LLMCallable", "ProgrammePlanner"]
