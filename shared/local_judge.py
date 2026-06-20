"""Local answer-verification judge — CompassVerifier-7B via the ``local-judge`` route.

Cost-offload Tier-1 (ISAP ``S5-CAPACITY-ROUTING-COST-OFFLOAD-TIER1``). A reusable,
shadow-defaulted adapter that offloads *mechanical answer-verification* gates
(question + gold answer + candidate response -> CORRECT / INCORRECT / INVALID)
from frontier cloud models onto a local CompassVerifier-7B served on the appendix
5060 Ti. See ``docs/runbooks/local-judge-stack.md``.

Design notes
------------
- This judge does **answer-verification against a gold reference** (CompassVerifier's
  trained task). It is *not* a gold-free quality judge — the council's existing
  LLM-as-judge gates (``eval_grounding`` context-anchoring, ``demo_eval`` demo
  quality) grade open-ended quality without a reference and need a rubric/GenRM
  judge instead. The natural first consumer here is the grounding-fitness Step-6
  grader (``grounding-fitness/REPORT.md``) and future mechanical correctness gates.
- Routes through the existing LiteLLM gateway (``model="openai/local-judge"``),
  identical idiom to ``agents.hapax_daimonion.eval_grounding.judge_session`` — so
  the fallback chain (``local-judge -> claude-haiku``) and observability apply.
- ``shadow=True`` by default: a verdict is produced and may be logged, but callers
  MUST NOT treat it as authoritative until the agreement gate (AC3: >=90% agreement,
  Cohen's kappa >=0.8, conservative-skewed) has cleared on the gate's own traffic.
  ``shadow_compare`` appends authoritative-vs-local pairs for that accumulation.
"""

from __future__ import annotations

import json
import os
import re
from contextlib import nullcontext
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

try:
    from agents.telemetry.llm_call_span import llm_call_span
except ImportError:  # telemetry is optional in offline/eval contexts
    llm_call_span = None  # type: ignore[assignment]

# Verbatim CV_PROMPT (non-CoT, single-letter) from open-compass/CompassVerifier
# src/prompts.py. Doubled braces escape .format(); {question}/{gold_answer}/
# {llm_response} are the only live placeholders.
CV_PROMPT = """
Please as a grading expert, judge whether the final answers given by the candidates below are consistent with the standard answers, that is, whether the candidates answered correctly.
Here are some evaluation criteria:
1. Please refer to the given standard answer. You don't need to re-generate the answer to the question because the standard answer has been given. You only need to judge whether the candidate's answer is consistent with the standard answer according to the form of the question. THE STANDARD ANSWER IS ALWAYS CORRECT AND THE QUESTION IS PERFECTLY VALID. NEVER QUESTION THEM.
2. ONLY compare the FINAL ANSWER - COMPLETELY IGNORE any potential errors in the REASONING PROCESSES.
3. Some answers may be expressed in different ways, such as some answers may be a mathematical expression, some answers may be a textual description, as long as the meaning expressed is the same. Before making a judgment, please understand the question and the standard answer first, and then judge whether the candidate's answer is correct.
4. Some answers may consist of multiple items, such as multiple-choice questions, multiple-select questions, fill-in-the-blank questions, etc. Regardless of the question type, the final answer will be considered correct as long as it matches the standard answer, regardless of whether the reasoning process is correct. For multiple-select questions and multi-blank fill-in-the-blank questions, all corresponding options or blanks must be answered correctly and match the standard answer exactly to be deemed correct.
5. If the prediction is given with \\boxed{{}}, please ignore the \\boxed{{}} and only judge whether the candidate's answer is consistent with the standard answer.
6. If the candidate's answer is invalid (e.g., incomplete (cut off mid-response), lots of unnormal repetitive content, or irrelevant to the question, saying it can't answer the question because some irresistible factors, like ethical issues, no enough information, etc.), select option C (INVALID).Please judge whether the following answers are consistent with the standard answer based on the above criteria. Grade the predicted answer of this new question as one of:
A: CORRECT
B: INCORRECT
C: INVALID
Just return the letters "A", "B", or "C", with no text around it.
Here is your task. Simply reply with either CORRECT, INCORRECT, or INVALID. Don't apologize or correct yourself if there was a mistake; we are just trying to grade the answer.
<Original Question Begin>:
{question}
<Original Question End>
<Standard Answer Begin>:
{gold_answer}
<Standard Answer End>
<Candidate's Answer Begin>:
{llm_response}
<Candidate's Answer End>
Judging the correctness of the candidate's answer:
"""

_LABELS = ("A", "B", "C")


def process_judgment(judgment_str: str) -> str:
    """Extract the A/B/C verdict from raw judge output.

    Port of ``process_judgment`` from open-compass/CompassVerifier src/cv_eval.ipynb
    (so verdicts match the published evaluation), hardened for the prompt-permitted
    *word* verdicts: CV_PROMPT tells the model it may reply CORRECT/INCORRECT/INVALID,
    and the LiteLLM fallback judge (claude-haiku) may follow that wording — possibly
    with punctuation or a prefix ("INVALID.", "Verdict: INCORRECT"). The upstream
    catch-all ``[A-C]`` regex would misread those (INVALID->A, CORRECT/INCORRECT->C),
    so a whole-word search (``\b`` bounded, INCORRECT before its CORRECT substring,
    last occurrence wins) runs before the char fallback. Returns "" when nothing
    parseable is found.
    """
    boxed_matches = re.findall(r"boxed{([A-C])}", judgment_str)
    if boxed_matches:
        return boxed_matches[-1]
    if judgment_str in _LABELS:
        return judgment_str
    # prompt-permitted whole-word verdicts, robust to punctuation/prefix. \b boundaries
    # stop the [A-C] letters inside the words from being mis-extracted; the alternation
    # lists INCORRECT first so it can't be shadowed by the CORRECT substring.
    _WORD_LABELS = {"CORRECT": "A", "INCORRECT": "B", "INVALID": "C"}
    word_hits = re.findall(r"\b(INCORRECT|INVALID|CORRECT)\b", judgment_str.upper())
    if word_hits:
        return _WORD_LABELS[word_hits[-1]]
    final_judgment_str = judgment_str.split("Final Judgment:")[-1]
    matches = re.findall(r"\(([A-C])\)*", final_judgment_str)
    if matches:
        return matches[-1]
    matches = re.findall(r"([A-C])", final_judgment_str)
    if matches:
        return matches[-1]
    return ""


class JudgeVerdict(BaseModel):
    """Structured verdict from the local judge."""

    label: Literal["A", "B", "C", ""] = Field(
        description="A=CORRECT, B=INCORRECT, C=INVALID, ''=unparseable"
    )
    raw: str = Field(default="", description="Raw model output before parsing")
    route: str = Field(default="local-judge")
    served_model: str = Field(
        default="",
        description="The model that actually answered (response.model) — provenance, not the route alias",
    )
    shadow: bool = Field(
        default=True,
        description="True = non-authoritative; do not act on it until the agreement gate clears",
    )
    error: str | None = Field(default=None)

    @property
    def is_correct(self) -> bool:
        return self.label == "A"

    @property
    def is_invalid(self) -> bool:
        return self.label == "C"

    @property
    def parsed(self) -> bool:
        return self.label in _LABELS


class LocalJudge:
    """Answer-verification judge backed by the ``local-judge`` LiteLLM route."""

    def __init__(
        self,
        route: str = "local-judge",
        *,
        shadow: bool = True,
        api_base: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
        max_tokens: int = 8,
    ) -> None:
        self.route = route
        self.shadow = shadow
        self.api_base = api_base or os.environ.get("LITELLM_API_BASE", "http://127.0.0.1:4000")
        self.api_key = api_key or os.environ.get("LITELLM_API_KEY", "not-set")
        self.timeout = timeout
        self.max_tokens = max_tokens

    def _prompt(self, question: str, gold_answer: str, llm_response: str) -> str:
        return CV_PROMPT.format(
            question=question, gold_answer=gold_answer, llm_response=llm_response
        )

    async def verify(self, question: str, gold_answer: str, llm_response: str) -> JudgeVerdict:
        """Grade ``llm_response`` against ``gold_answer`` -> A/B/C verdict."""
        import litellm

        content = self._prompt(question, gold_answer, llm_response)
        span = (
            llm_call_span(model=self.route, route="local-judge")
            if llm_call_span is not None
            else nullcontext(None)
        )
        try:
            with span:
                response = await litellm.acompletion(
                    model=f"openai/{self.route}",
                    messages=[{"role": "user", "content": content}],
                    max_tokens=self.max_tokens,
                    temperature=0.0,
                    api_base=self.api_base,
                    api_key=self.api_key,
                    timeout=self.timeout,
                )
            raw = response.choices[0].message.content or ""
            served = str(getattr(response, "model", "") or "")
            if served and "compassverifier" not in served.lower():
                # Provenance mismatch: the local-judge route did NOT serve
                # CompassVerifier (e.g. it fell back to claude-haiku/gemini). Refuse
                # to label this a local-judge CV verdict — force label='' so a caller
                # MUST escalate and can never act on a foreign-model answer-verification
                # as if it were the trained judge (the silent-degrade the eval audit
                # flagged for a future shadow=False caller).
                return JudgeVerdict(
                    label="",
                    raw=raw,
                    route=f"degraded:served={served}",
                    served_model=served,
                    shadow=self.shadow,
                    error=(
                        f"local-judge provenance mismatch: served '{served}', not "
                        "CompassVerifier — escalate to the incumbent judge"
                    ),
                )
            return JudgeVerdict(
                label=process_judgment(raw.strip()),  # type: ignore[arg-type]
                raw=raw,
                route=self.route,
                served_model=served,
                shadow=self.shadow,
            )
        except Exception as exc:  # noqa: BLE001 — surface, never silently pass/fail-correct
            # Include the next action so a caller/operator knows where to look: the
            # judge endpoint, the gateway route, or the API-base env. The verdict is
            # label="" (unparsed) — callers MUST escalate, never treat it as CORRECT.
            hint = (
                "judge call failed — check the hapax-local-judge unit (:5001), the "
                f"'{self.route}' LiteLLM route, and LITELLM_API_BASE ({self.api_base}); "
                "escalate this item to the incumbent judge"
            )
            return JudgeVerdict(
                label="",
                raw="",
                route=self.route,
                shadow=self.shadow,
                error=f"{str(exc)[:160]} | {hint}",
            )


def shadow_compare(
    verdict: JudgeVerdict,
    authoritative_label: str,
    log_path: str | os.PathLike[str] = "~/.cache/hapax/local-judge-shadow.jsonl",
) -> bool:
    """Append a (local, authoritative) pair to the shadow log and return agreement.

    The AC3 council-distribution agreement gate (>=150 items, agreement >=90%,
    Cohen's kappa >=0.8, conservative-skewed) is evaluated from this accumulated
    log before the gate is ever promoted out of shadow. Conservative errors
    (local says B/C while authoritative says A) are safe; a false-accept (local
    says A while authoritative says B/C) is the dangerous kind.
    """
    path = Path(os.path.expanduser(str(log_path)))
    path.parent.mkdir(parents=True, exist_ok=True)
    agree = verdict.label == authoritative_label
    false_accept = verdict.label == "A" and authoritative_label in ("B", "C")
    with path.open("a") as fh:
        fh.write(
            json.dumps(
                {
                    "local": verdict.label,
                    "authoritative": authoritative_label,
                    "agree": agree,
                    "false_accept": false_accept,
                    "route": verdict.route,
                    "error": verdict.error,
                }
            )
            + "\n"
        )
    return agree


def _main() -> int:
    """One-shot judge probe: `python -m shared.local_judge --question ... --gold ... --response ...`."""
    import argparse
    import asyncio

    ap = argparse.ArgumentParser(description="Probe the local-judge route on a single item.")
    ap.add_argument("--question", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--response", required=True)
    ap.add_argument("--route", default="local-judge")
    args = ap.parse_args()

    judge = LocalJudge(route=args.route, shadow=True)
    verdict = asyncio.run(judge.verify(args.question, args.gold, args.response))
    if not verdict.parsed:
        print(f"UNPARSEABLE (error={verdict.error}) raw={verdict.raw!r}")
        return 2
    label = {"A": "CORRECT", "B": "INCORRECT", "C": "INVALID"}[verdict.label]
    flags = []
    if verdict.is_correct:
        flags.append("is_correct")
    if verdict.is_invalid:
        flags.append("is_invalid")
    print(
        f"{verdict.label} ({label})  route={verdict.route} shadow={verdict.shadow} {' '.join(flags)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
