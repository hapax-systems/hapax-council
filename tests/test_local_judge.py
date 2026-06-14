"""Tests for the local answer-verification judge adapter (cost-offload Tier-1)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from shared.local_judge import (
    CV_PROMPT,
    JudgeVerdict,
    LocalJudge,
    process_judgment,
    shadow_compare,
)


def test_process_judgment_bare_letter():
    assert process_judgment("A") == "A"
    assert process_judgment("B") == "B"
    assert process_judgment("C") == "C"


def test_process_judgment_boxed():
    assert process_judgment(r"Final Judgment: \boxed{A}") == "A"
    assert process_judgment(r"analysis... \boxed{B} - INCORRECT") == "B"


def test_process_judgment_final_judgment_paren():
    assert process_judgment("Some analysis.\nFinal Judgment: (C)") == "C"


def test_process_judgment_word_verdicts_not_mischar_extracted():
    # CV_PROMPT permits CORRECT/INCORRECT/INVALID; the upstream catch-all [A-C] regex
    # would misread these (INVALID->A, CORRECT/INCORRECT->C). Whole-word check fixes it.
    assert process_judgment("CORRECT") == "A"
    assert process_judgment("INCORRECT") == "B"
    assert process_judgment("INVALID") == "C"
    assert process_judgment("  correct\n") == "A"


def test_process_judgment_word_verdicts_with_punctuation_or_prefix():
    # the dangerous false-accept case: "INVALID."/prefixed words must NOT fall through
    # to the char fallback (which would read INVALID->A = CORRECT).
    assert process_judgment("INVALID.") == "C"
    assert process_judgment("INCORRECT!") == "B"
    assert process_judgment('"INVALID"') == "C"
    assert process_judgment("Verdict: INCORRECT") == "B"
    assert process_judgment("INVALID - the response is cut off") == "C"
    assert process_judgment("Correct.") == "A"


def test_process_judgment_unparseable_returns_empty():
    assert process_judgment("the answer is fine indeed") == ""
    assert process_judgment("") == ""


def test_prompt_formats_all_placeholders_without_brace_errors():
    prompt = CV_PROMPT.format(question="2+2?", gold_answer="4", llm_response="four")
    assert "2+2?" in prompt
    assert "<Standard Answer Begin>" in prompt
    assert "four" in prompt
    # the escaped \boxed{} guidance must survive .format() literally
    assert r"\boxed{}" in prompt


def test_verdict_properties():
    assert JudgeVerdict(label="A").is_correct
    assert not JudgeVerdict(label="B").is_correct
    assert JudgeVerdict(label="C").is_invalid
    assert JudgeVerdict(label="A").parsed
    assert not JudgeVerdict(label="").parsed


async def test_verify_routes_and_parses():
    fake = AsyncMock()
    fake.return_value.choices = [type("C", (), {"message": type("M", (), {"content": "B"})()})()]
    judge = LocalJudge(shadow=True)
    with patch("litellm.acompletion", fake):
        verdict = await judge.verify("q", "gold", "candidate")
    assert verdict.label == "B"
    assert verdict.shadow is True
    assert verdict.route == "local-judge"
    # routed through the gateway with the openai/<route> idiom
    assert fake.call_args.kwargs["model"] == "openai/local-judge"
    assert fake.call_args.kwargs["temperature"] == 0.0


async def test_verify_surfaces_errors_not_false_correct():
    judge = LocalJudge()
    with patch("litellm.acompletion", AsyncMock(side_effect=RuntimeError("endpoint down"))):
        verdict = await judge.verify("q", "g", "r")
    # a judge failure must NOT silently read as CORRECT
    assert verdict.label == ""
    assert not verdict.is_correct
    assert verdict.error is not None and "endpoint down" in verdict.error


def test_shadow_compare_logs_agreement_and_false_accept(tmp_path):
    log = tmp_path / "shadow.jsonl"
    assert shadow_compare(JudgeVerdict(label="A"), "A", log) is True
    assert shadow_compare(JudgeVerdict(label="A"), "B", log) is False  # false-accept
    assert shadow_compare(JudgeVerdict(label="B"), "A", log) is False  # conservative
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert rows[0]["agree"] is True and rows[0]["false_accept"] is False
    assert rows[1]["false_accept"] is True  # local A vs authoritative B = dangerous
    assert rows[2]["false_accept"] is False  # local B vs authoritative A = safe
