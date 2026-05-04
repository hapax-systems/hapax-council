"""Hapax-authored programme planner — Phase 3 of the programme-layer plan.

The ``ProgrammePlanner`` runs at show-start and at each programme
boundary. It assembles a perceptual + vault + profile context, calls a
grounded LLM (LiteLLM `balanced` tier — Claude Sonnet) with the
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
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from shared.config import LITELLM_KEY
from shared.programme import ProgrammePlan

log = logging.getLogger(__name__)


# Path to the prompt template. Lifted from inline so prompt drift is a
# git diff on a markdown file (matches the structural director's
# inline-vs-file split — at this scale the prompt deserves its own
# review surface).
_PROMPT_PATH = Path(__file__).parent / "prompts" / "programme_plan.md"

# Model name sent in the API request. When the planner routes to
# TabbyAPI (primary), the model field is informational — TabbyAPI
# serves whatever is loaded. When falling back to LiteLLM, this is
# the LiteLLM model alias.
DEFAULT_MODEL = os.environ.get("HAPAX_PROGRAMME_PLANNER_MODEL", "command-r-08-2024-exl3-5.0bpw")

# Primary endpoint: TabbyAPI (local inference, no external API).
# Fallback: LiteLLM gateway (for when TabbyAPI is down or model-swapping).
_TABBY_URL = os.environ.get("HAPAX_TABBY_URL", "http://localhost:5000/v1/chat/completions")

# Budget raised from 60s → 120s: the enriched programme plan prompt
# (~23KB) plus per-call context regularly exceeds 60s on the balanced
# tier (Claude Sonnet via Anthropic API). Local Qwen3.6 at 33 tok/s
# needs ~130s for the full prompt + response.
_LLM_TIMEOUT_S: float = 300.0

# Max number of corrective retries after the first call. Spec mandates
# "retries once" (one corrective re-call), so default is 1.
DEFAULT_MAX_RETRIES = 1


LLMCallable = Callable[[str], str]


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
        """``llm_fn`` defaults to the LiteLLM ``balanced``-tier call;
        tests inject a deterministic stub. ``max_retries`` is the
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
    ) -> str:
        """Render the prompt template + per-call context."""
        template = self._read_prompt_template()
        context = self._render_context(
            show_id=show_id,
            perception=perception,
            working_mode=working_mode,
            vault_state=vault_state,
            profile=profile,
            condition_history=condition_history,
            content_state=content_state,
        )
        return f"{template}\n\n## Per-call context\n\n{context}"

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
            '"hapax"`.'
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
        try:
            return ProgrammePlan.model_validate(obj)
        except ValidationError as e:
            return str(e)


# --- default LLM call ------------------------------------------------


def _call_endpoint(url: str, prompt: str, auth: str | None = None) -> str | None:
    """Call an OpenAI-compatible chat endpoint. Returns content or None on failure."""
    body = json.dumps(
        {
            "model": DEFAULT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 8192,
            "temperature": 0.7,
            "chat_template_kwargs": {"enable_thinking": False},
        }
    ).encode()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = f"Bearer {auth}"
    req = urllib.request.Request(url, body, headers)
    try:
        with urllib.request.urlopen(req, timeout=_LLM_TIMEOUT_S) as resp:
            data = json.loads(resp.read())
        content = data["choices"][0]["message"]["content"] or ""
        # Strip Qwen3's <think>...</think> chain-of-thought
        import re

        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        return content
    except Exception:
        return None


def _default_llm_fn(prompt: str) -> str:
    """Default LLM caller — local TabbyAPI first, LiteLLM fallback.

    Primary: TabbyAPI at localhost:5000 (Command-R or whatever is loaded).
    No external API dependency. If TabbyAPI is down (model swap, restart),
    falls back to LiteLLM at localhost:4000 which has its own fallback chain.
    """
    # Primary: TabbyAPI (local, no auth needed — disable_auth: true)
    result = _call_endpoint(_TABBY_URL, prompt)
    if result is not None:
        log.info("planner LLM: served by TabbyAPI (local)")
        return result

    # Fallback: LiteLLM gateway
    log.info("planner LLM: TabbyAPI unavailable, falling back to LiteLLM")
    litellm_url = os.environ.get("HAPAX_LITELLM_URL", "http://localhost:4000/v1/chat/completions")
    result = _call_endpoint(litellm_url, prompt, auth=LITELLM_KEY)
    if result is not None:
        return result

    raise RuntimeError("planner LLM: both TabbyAPI and LiteLLM failed")


__all__ = ["DEFAULT_MAX_RETRIES", "DEFAULT_MODEL", "LLMCallable", "ProgrammePlanner"]
