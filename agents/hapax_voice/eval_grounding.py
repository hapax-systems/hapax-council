"""Offline context anchoring evaluation — LLM-as-judge for conversational continuity.

Fetches recent voice session traces from Langfuse, reconstructs conversations,
and evaluates Clark's three grounding mechanisms (Clark 1996):
  1. Presentation: classify each assistant sentence
  2. Acceptance: classify operator response type
  3. Evidence of understanding: check later turns for correct reference

Run as: uv run python -m agents.hapax_voice.eval_grounding [--sessions N] [--since HOURS]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC

log = logging.getLogger(__name__)

try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class TurnEval:
    """Evaluation of a single conversation turn."""

    turn_index: int = 0
    user_text: str = ""
    assistant_text: str = ""

    # Presentation classification
    presentation_type: str = ""  # assertion, question, proposal, phatic, meta

    # Acceptance classification
    acceptance_type: str = ""  # accept, clarify, reject, ignore

    # Evidence of understanding (scored in later turns)
    reference_correct: bool | None = None
    reference_detail: str = ""

    # Raw LLM judge output
    judge_rationale: str = ""


@dataclass
class SessionEval:
    """Evaluation of a complete voice session."""

    session_id: str = ""
    turn_count: int = 0
    turns: list[TurnEval] = field(default_factory=list)

    # Aggregate scores
    acceptance_rate: float = 0.0  # proportion of ACCEPT responses
    reference_accuracy: float = 0.0  # proportion of correct references
    grounding_depth: float = 0.0  # how many turns before references appear

    # Summary
    judge_summary: str = ""


# ── Langfuse Session Reconstruction ─────────────────────────────────────────


def fetch_sessions(since_hours: float = 24, max_sessions: int = 10) -> list[dict]:
    """Fetch recent voice session traces from Langfuse."""
    try:
        from langfuse import get_client

        client = get_client()
    except Exception:
        log.error("Langfuse client unavailable")
        return []

    # Query traces tagged with voice.utterance from the last N hours
    from datetime import datetime, timedelta

    since = datetime.now(UTC) - timedelta(hours=since_hours)

    try:
        traces = client.get_traces(
            name="voice.utterance",
            from_timestamp=since,
            limit=200,  # fetch many, then group by session
        )
    except Exception:
        log.error("Failed to fetch traces from Langfuse", exc_info=True)
        return []

    # Group by session_id
    sessions: dict[str, list] = {}
    for trace in traces.data if hasattr(traces, "data") else traces:
        sid = getattr(trace, "session_id", None) or trace.metadata.get("session_id", "unknown")
        if sid not in sessions:
            sessions[sid] = []
        sessions[sid].append(trace)

    # Sort sessions by first trace timestamp, take most recent
    sorted_sessions = sorted(sessions.items(), key=lambda x: len(x[1]), reverse=True)
    return [{"session_id": sid, "traces": traces} for sid, traces in sorted_sessions[:max_sessions]]


def reconstruct_conversation(session_traces: list) -> list[dict]:
    """Reconstruct conversation turns from Langfuse traces."""
    turns = []
    for trace in sorted(session_traces, key=lambda t: getattr(t, "timestamp", 0)):
        meta = getattr(trace, "metadata", {}) or {}
        turn_idx = meta.get("turn", len(turns))

        # Extract user and assistant text from trace observations
        user_text = ""
        assistant_text = ""

        observations = getattr(trace, "observations", []) or []
        for obs in observations:
            if hasattr(obs, "input") and obs.input:
                if isinstance(obs.input, str):
                    user_text = obs.input
                elif isinstance(obs.input, dict):
                    user_text = obs.input.get("text", obs.input.get("content", ""))

            if hasattr(obs, "output") and obs.output:
                if isinstance(obs.output, str):
                    assistant_text = obs.output

        # Fallback: check trace-level input/output
        if not user_text and hasattr(trace, "input"):
            inp = trace.input
            if isinstance(inp, str):
                user_text = inp
            elif isinstance(inp, dict):
                user_text = inp.get("text", inp.get("content", ""))

        if user_text or assistant_text:
            turns.append(
                {
                    "index": turn_idx,
                    "user": user_text,
                    "assistant": assistant_text,
                }
            )

    return turns


# ── LLM-as-Judge Evaluation ─────────────────────────────────────────────────

_JUDGE_PROMPT = """You are evaluating conversational context anchoring in a voice assistant interaction.

For each turn, classify:

1. **Presentation type** (what the assistant does):
   - assertion: states a fact or answer
   - question: asks the user something
   - proposal: suggests an action
   - phatic: social/greeting exchange
   - meta: talks about the conversation itself

2. **Acceptance type** (how the user responds in the NEXT turn):
   - accept: confirms, agrees, builds on the response
   - clarify: asks for explanation or clarification
   - reject: disagrees or corrects
   - ignore: changes topic without acknowledging

3. **Reference accuracy** (for turns that reference earlier content):
   - correct: reference matches what was actually said
   - incorrect: reference misrepresents earlier content
   - none: no back-reference made

Respond in JSON format:
```json
{
  "turns": [
    {
      "turn": 0,
      "presentation": "assertion",
      "acceptance": "accept",
      "reference": "none",
      "reference_detail": "",
      "rationale": "brief explanation"
    }
  ],
  "summary": "overall context anchoring quality assessment in 1-2 sentences"
}
```

Here is the conversation:
"""


async def judge_session(turns: list[dict]) -> dict:
    """Use LLM-as-judge to evaluate a session's context anchoring."""
    import litellm

    if not turns:
        return {"turns": [], "summary": "Empty session"}

    # Format conversation for the judge
    conv_text = ""
    for t in turns:
        conv_text += f"\n[Turn {t['index']}]\n"
        if t.get("user"):
            conv_text += f"User: {t['user']}\n"
        if t.get("assistant"):
            conv_text += f"Assistant: {t['assistant']}\n"

    try:
        response = await litellm.acompletion(
            model="openai/claude-sonnet",
            messages=[
                {"role": "system", "content": _JUDGE_PROMPT},
                {"role": "user", "content": conv_text},
            ],
            max_tokens=2000,
            temperature=0.0,
            api_base=os.environ.get("LITELLM_API_BASE", "http://127.0.0.1:4000"),
            api_key=os.environ.get("LITELLM_API_KEY", "not-set"),
            timeout=30,
        )

        content: str = response.choices[0].message.content or ""
        # Extract JSON from response
        json_match: str = content
        if "```json" in content:
            json_match = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            json_match = content.split("```")[1].split("```")[0]

        return json.loads(json_match.strip())
    except Exception:
        log.exception("LLM judge failed")
        return {"turns": [], "summary": "Judge evaluation failed"}


# ── Score Aggregation ────────────────────────────────────────────────────────


def aggregate_session(turns: list[dict], judge_result: dict) -> SessionEval:
    """Combine raw turns with judge evaluation into SessionEval."""
    session_eval = SessionEval(turn_count=len(turns))

    judge_turns = {t["turn"]: t for t in judge_result.get("turns", [])}

    accept_count = 0
    ref_correct = 0
    ref_total = 0
    first_reference_turn = None

    for i, turn in enumerate(turns):
        te = TurnEval(
            turn_index=i,
            user_text=turn.get("user", ""),
            assistant_text=turn.get("assistant", ""),
        )

        jt = judge_turns.get(i, {})
        te.presentation_type = jt.get("presentation", "")
        te.acceptance_type = jt.get("acceptance", "")
        te.judge_rationale = jt.get("rationale", "")

        ref = jt.get("reference", "none")
        if ref != "none":
            te.reference_correct = ref == "correct"
            te.reference_detail = jt.get("reference_detail", "")
            ref_total += 1
            if te.reference_correct:
                ref_correct += 1
            if first_reference_turn is None:
                first_reference_turn = i

        if te.acceptance_type == "accept":
            accept_count += 1

        session_eval.turns.append(te)

    # Aggregate scores
    if len(turns) > 1:
        session_eval.acceptance_rate = accept_count / (len(turns) - 1)  # first turn has no prior
    session_eval.reference_accuracy = ref_correct / ref_total if ref_total > 0 else 1.0
    session_eval.grounding_depth = first_reference_turn if first_reference_turn is not None else -1
    session_eval.judge_summary = judge_result.get("summary", "")

    return session_eval


# ── Langfuse Score Push ──────────────────────────────────────────────────────


def push_scores(session_eval: SessionEval, session_id: str) -> None:
    """Push evaluation scores back to Langfuse."""
    try:
        from shared.telemetry import hapax_event

        hapax_event(
            "voice",
            "grounding_eval",
            metadata={
                "session_id": session_id,
                "turn_count": session_eval.turn_count,
                "acceptance_rate": session_eval.acceptance_rate,
                "reference_accuracy": session_eval.reference_accuracy,
                "grounding_depth": session_eval.grounding_depth,
                "summary": session_eval.judge_summary,
            },
        )
    except Exception:
        log.debug("Score push failed (non-fatal)", exc_info=True)


# ── Salience Correlation (Claim 5) ──────────────────────────────────────────


def analyze_salience_correlation(
    evals: list[SessionEval],
    session_traces: dict[str, list],
) -> dict[str, float] | None:
    """Correlate activation_score with response tokens and context_anchor_success.

    Collects per-turn scores from Langfuse traces across all evaluated sessions.
    Returns None if fewer than 50 turns have valid activation scores.
    """
    activations: list[float] = []
    token_counts: list[float] = []
    anchor_scores: list[float] = []

    for se in evals:
        traces = session_traces.get(se.session_id, [])
        for trace in traces:
            scores = getattr(trace, "scores", []) or []
            score_map: dict[str, float] = {}
            for s in scores:
                name = getattr(s, "name", "")
                value = getattr(s, "value", None)
                if name and value is not None:
                    score_map[name] = float(value)

            activation = score_map.get("activation_score")
            if activation is None or activation < 0:
                continue

            # Response tokens: count words in assistant text as proxy
            turn_idx = (getattr(trace, "metadata", {}) or {}).get("turn")
            resp_tokens = 0.0
            if turn_idx is not None and turn_idx < len(se.turns):
                resp_tokens = float(len(se.turns[turn_idx].assistant_text.split()))

            anchor = score_map.get("context_anchor_success", 0.0)

            activations.append(activation)
            token_counts.append(resp_tokens)
            anchor_scores.append(anchor)

    if len(activations) < 50:
        return None

    from agents.hapax_voice.stats import bayes_correlation as _bayes_corr

    corr_tokens = _bayes_corr(activations, token_counts, prior_mu=0.3, prior_sigma=0.15)
    corr_anchor = _bayes_corr(activations, anchor_scores, prior_mu=0.3, prior_sigma=0.15)

    return {
        "r_tokens": corr_tokens["r"],
        "r_anchor": corr_anchor["r"],
        "bf_tokens": corr_tokens["bf"],
        "bf_anchor": corr_anchor["bf"],
        "n_turns": len(activations),
        "ci_tokens": corr_tokens["ci_95"],
        "ci_anchor": corr_anchor["ci_95"],
    }


# ── CLI ──────────────────────────────────────────────────────────────────────


def format_report(evals: list[SessionEval], correlation: dict | None = None) -> str:
    """Format evaluation results as a human-readable report."""
    lines = ["# Context Anchoring Evaluation Report", ""]

    for i, se in enumerate(evals):
        lines.append(f"## Session {i + 1} ({se.session_id})")
        lines.append(f"- Turns: {se.turn_count}")
        lines.append(f"- Acceptance rate: {se.acceptance_rate:.1%}")
        lines.append(f"- Reference accuracy: {se.reference_accuracy:.1%}")
        lines.append(
            f"- First reference at turn: {se.grounding_depth}"
            if se.grounding_depth >= 0
            else "- No back-references detected"
        )
        lines.append(f"- Judge summary: {se.judge_summary}")
        lines.append("")

        for t in se.turns:
            pres = t.presentation_type or "?"
            acc = t.acceptance_type or "?"
            ref = (
                "correct"
                if t.reference_correct
                else "incorrect"
                if t.reference_correct is False
                else "-"
            )
            lines.append(f"  Turn {t.turn_index}: pres={pres} acc={acc} ref={ref}")
            if t.judge_rationale:
                lines.append(f"    rationale: {t.judge_rationale}")
        lines.append("")

    # Aggregate across sessions
    if evals:
        avg_accept = sum(e.acceptance_rate for e in evals) / len(evals)
        avg_ref = sum(e.reference_accuracy for e in evals) / len(evals)
        lines.append("## Aggregate")
        lines.append(f"- Sessions evaluated: {len(evals)}")
        lines.append(f"- Mean acceptance rate: {avg_accept:.1%}")
        lines.append(f"- Mean reference accuracy: {avg_ref:.1%}")

    if correlation is not None:
        lines.append("")
        lines.append("## Claim 5: Salience Correlation")
        lines.append(f"- Turns analyzed: {correlation['n_turns']}")
        lines.append(f"- r(activation, tokens): {correlation['r_tokens']:.3f}")
        lines.append(f"  BF={correlation['bf_tokens']:.2f}, 95% CI={correlation['ci_tokens']}")
        lines.append(f"- r(activation, anchor): {correlation['r_anchor']:.3f}")
        lines.append(f"  BF={correlation['bf_anchor']:.2f}, 95% CI={correlation['ci_anchor']}")

    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Offline context anchoring evaluation")
    parser.add_argument("--sessions", type=int, default=5, help="Max sessions to evaluate")
    parser.add_argument("--since", type=float, default=24, help="Hours to look back")
    args = parser.parse_args()

    from shared.log_setup import configure_logging

    configure_logging(agent="eval-grounding")

    print(f"Fetching sessions from last {args.since}h...")
    sessions = fetch_sessions(since_hours=args.since, max_sessions=args.sessions)
    if not sessions:
        print("No sessions found.")
        return

    print(f"Found {len(sessions)} sessions. Evaluating...")

    evals: list[SessionEval] = []
    for session_data in sessions:
        sid = session_data["session_id"]
        turns = reconstruct_conversation(session_data["traces"])
        if len(turns) < 2:
            print(f"  Session {sid}: too few turns ({len(turns)}), skipping")
            continue

        print(f"  Session {sid}: {len(turns)} turns — judging...")
        judge_result = await judge_session(turns)
        session_eval = aggregate_session(turns, judge_result)
        session_eval.session_id = sid

        push_scores(session_eval, sid)
        evals.append(session_eval)

    # Salience correlation analysis (Claim 5)
    all_traces = {s["session_id"]: s["traces"] for s in sessions}
    correlation = analyze_salience_correlation(evals, all_traces)
    if correlation:
        print(f"  Salience correlation: {correlation['n_turns']} turns analyzed")

    report = format_report(evals, correlation=correlation)
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
