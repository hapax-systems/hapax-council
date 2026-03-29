"""Offline context anchoring evaluation — LLM-as-judge for conversational continuity.

Fetches recent voice session traces from Langfuse, reconstructs conversations,
and evaluates Clark's three grounding mechanisms (Clark 1996):
  1. Presentation: classify each assistant sentence
  2. Acceptance: classify operator response type
  3. Evidence of understanding: check later turns for correct reference

Run as: uv run python -m agents.hapax_daimonion.eval_grounding [--sessions N] [--since HOURS]
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

    # Trajectory scores (Class G — grounding-native, structurally zero for profile-retrieval)
    anchor_trajectory: float = 0.0  # slope of context_anchor_success across turns
    frustration_trajectory: float = 0.0  # slope of frustration across turns (negative = good)

    # Turn-pair coherence (Class G)
    acceptance_after_anchor: float | None = None  # P(ACCEPT | high anchor at prior turn)
    frustration_after_miss: float | None = None  # P(frustration | low anchor at prior turn)


# ── Langfuse Session Reconstruction ─────────────────────────────────────────


def fetch_sessions(since_hours: float = 24, max_sessions: int = 10) -> list[dict]:
    """Fetch recent voice session traces from Langfuse via REST API."""
    from datetime import datetime, timedelta

    from shared.langfuse_client import langfuse_get

    since = (datetime.now(UTC) - timedelta(hours=since_hours)).isoformat()

    # Paginate to get all traces
    all_traces: list[dict] = []
    page = 1
    while page <= 10:
        resp = langfuse_get(
            "/traces",
            {"name": "voice.utterance", "fromTimestamp": since, "limit": 100, "page": str(page)},
        )
        if not resp:
            break
        data = resp.get("data", [])
        if not data:
            break
        all_traces.extend(data)
        total = resp.get("meta", {}).get("totalItems", 0)
        if page * 100 >= total:
            break
        page += 1

    if not all_traces:
        log.info("No voice traces found in last %.0fh", since_hours)
        return []

    # Enrich each trace with full scores (list endpoint only returns score IDs)
    for trace in all_traces:
        detail = langfuse_get(f"/traces/{trace['id']}")
        if detail:
            trace["scores"] = detail.get("scores", [])

    # Group by session_id
    sessions: dict[str, list] = {}
    for trace in all_traces:
        sid = trace.get("sessionId") or (trace.get("metadata") or {}).get("session_id", "unknown")
        sessions.setdefault(sid, []).append(trace)

    # Sort sessions by trace count descending, take most recent
    sorted_sessions = sorted(sessions.items(), key=lambda x: len(x[1]), reverse=True)
    return [{"session_id": sid, "traces": traces} for sid, traces in sorted_sessions[:max_sessions]]


def reconstruct_conversation(session_traces: list[dict]) -> list[dict]:
    """Reconstruct conversation turns from Langfuse trace dicts."""
    turns = []
    for trace in sorted(session_traces, key=lambda t: t.get("timestamp", "")):
        meta = trace.get("metadata") or {}
        turn_raw = meta.get("turn", len(turns))
        turn_idx = turn_raw.get("intValue", turn_raw) if isinstance(turn_raw, dict) else turn_raw

        user_text = ""
        assistant_text = ""

        # Extract from trace-level input/output
        inp = trace.get("input")
        if isinstance(inp, str):
            user_text = inp
        elif isinstance(inp, dict):
            user_text = inp.get("text", inp.get("content", ""))

        out = trace.get("output")
        if isinstance(out, str):
            assistant_text = out
        elif isinstance(out, dict):
            assistant_text = out.get("text", out.get("content", ""))

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


# ── Trajectory & Turn-Pair Analysis ─────────────────────────────────────────


def compute_trajectories(
    session_eval: SessionEval,
    per_turn_scores: list[dict[str, float]],
) -> None:
    """Compute within-session trajectory slopes and turn-pair coherence.

    Trajectory: linear regression slope of a score across turns.
    Positive anchor_trajectory = grounding improving (expected for context anchoring).
    Profile-retrieval produces flat slopes (each turn is independent).

    Turn-pair coherence: conditional probabilities linking consecutive turns.
    These are structurally undefined for stateless systems.

    Mutates session_eval in place.
    """
    n = len(per_turn_scores)
    if n < 3:
        return

    # Extract per-turn values
    anchors = [s.get("context_anchor_success") for s in per_turn_scores]
    frustrations = [s.get("frustration_score") for s in per_turn_scores]
    acceptances = [s.get("acceptance_type") for s in per_turn_scores]

    # ── Trajectory slopes (simple linear regression: slope = cov(x,y)/var(x))
    def _slope(values: list[float | None]) -> float:
        """OLS slope of values against turn index. Returns 0.0 if insufficient data."""
        pairs = [(i, v) for i, v in enumerate(values) if v is not None]
        if len(pairs) < 3:
            return 0.0
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        n_p = len(pairs)
        x_mean = sum(xs) / n_p
        y_mean = sum(ys) / n_p
        cov = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True))
        var = sum((x - x_mean) ** 2 for x in xs)
        if var < 1e-12:
            return 0.0
        return cov / var

    session_eval.anchor_trajectory = round(_slope(anchors), 4)
    session_eval.frustration_trajectory = round(_slope(frustrations), 4)

    # ── Turn-pair coherence: P(ACCEPT at N+1 | high anchor at N)
    high_anchor_threshold = 0.5
    frustration_threshold = 1.0
    low_anchor_threshold = 0.3

    accept_after_high = 0
    total_high = 0
    frust_after_low = 0
    total_low = 0

    for i in range(n - 1):
        anchor_i = anchors[i]
        accept_next = acceptances[i + 1]
        frust_next = frustrations[i + 1]

        if anchor_i is not None and anchor_i >= high_anchor_threshold:
            total_high += 1
            if accept_next is not None and accept_next >= 0.7:  # ACCEPT or CLARIFY
                accept_after_high += 1

        if anchor_i is not None and anchor_i <= low_anchor_threshold:
            total_low += 1
            if frust_next is not None and frust_next >= frustration_threshold:
                frust_after_low += 1

    if total_high >= 2:
        session_eval.acceptance_after_anchor = round(accept_after_high / total_high, 3)
    if total_low >= 2:
        session_eval.frustration_after_miss = round(frust_after_low / total_low, 3)


def collect_per_turn_scores(session_traces: list[dict]) -> list[dict[str, float]]:
    """Extract per-turn Langfuse scores from trace dicts, ordered by turn index."""
    turn_scores: dict[int, dict[str, float]] = {}
    for trace in session_traces:
        meta = trace.get("metadata") or {}
        turn_raw = meta.get("turn", -1)
        turn_idx = turn_raw.get("intValue", turn_raw) if isinstance(turn_raw, dict) else turn_raw
        if not isinstance(turn_idx, int) or turn_idx < 0:
            continue

        scores = trace.get("scores", [])
        score_map: dict[str, float] = {}
        for s in scores:
            name = s.get("name", "") if isinstance(s, dict) else ""
            value = s.get("value") if isinstance(s, dict) else None
            if name and value is not None:
                score_map[name] = float(value)

        if score_map:
            turn_scores[turn_idx] = score_map

    return [turn_scores[k] for k in sorted(turn_scores)]


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
                "anchor_trajectory": session_eval.anchor_trajectory,
                "frustration_trajectory": session_eval.frustration_trajectory,
                "acceptance_after_anchor": session_eval.acceptance_after_anchor,
                "frustration_after_miss": session_eval.frustration_after_miss,
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
            scores = trace.get("scores", []) if isinstance(trace, dict) else []
            score_map: dict[str, float] = {}
            for s in scores:
                name = s.get("name", "") if isinstance(s, dict) else getattr(s, "name", "")
                value = s.get("value") if isinstance(s, dict) else getattr(s, "value", None)
                if name and value is not None:
                    score_map[name] = float(value)

            activation = score_map.get("activation_score")
            if activation is None or activation < 0:
                continue

            # Response tokens: count words in assistant text as proxy
            meta = trace.get("metadata", {}) if isinstance(trace, dict) else {}
            turn_raw = meta.get("turn") if meta else None
            turn_idx = (
                turn_raw.get("intValue", turn_raw) if isinstance(turn_raw, dict) else turn_raw
            )
            resp_tokens = 0.0
            if turn_idx is not None and isinstance(turn_idx, int) and turn_idx < len(se.turns):
                resp_tokens = float(len(se.turns[turn_idx].assistant_text.split()))

            anchor = score_map.get("context_anchor_success", 0.0)

            activations.append(activation)
            token_counts.append(resp_tokens)
            anchor_scores.append(anchor)

    if len(activations) < 50:
        return None

    from agents.hapax_daimonion.stats import bayes_correlation as _bayes_corr

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
        # Trajectory scores (Class G — grounding-native)
        if se.anchor_trajectory != 0.0 or se.frustration_trajectory != 0.0:
            direction = "improving" if se.anchor_trajectory > 0 else "flat/declining"
            lines.append(f"- Anchor trajectory: {se.anchor_trajectory:+.4f} ({direction})")
            lines.append(f"- Frustration trajectory: {se.frustration_trajectory:+.4f}")
        if se.acceptance_after_anchor is not None:
            lines.append(f"- P(accept|high anchor): {se.acceptance_after_anchor:.1%}")
        if se.frustration_after_miss is not None:
            lines.append(f"- P(frustration|low anchor): {se.frustration_after_miss:.1%}")
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
        # Trajectory aggregates
        traj_evals = [e for e in evals if e.anchor_trajectory != 0.0]
        if traj_evals:
            avg_traj = sum(e.anchor_trajectory for e in traj_evals) / len(traj_evals)
            positive = sum(1 for e in traj_evals if e.anchor_trajectory > 0)
            lines.append(
                f"- Mean anchor trajectory: {avg_traj:+.4f} ({positive}/{len(traj_evals)} positive)"
            )
        aaa = [e.acceptance_after_anchor for e in evals if e.acceptance_after_anchor is not None]
        if aaa:
            lines.append(f"- Mean P(accept|high anchor): {sum(aaa) / len(aaa):.1%}")

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

        # Compute trajectory scores from Langfuse per-turn data
        per_turn = collect_per_turn_scores(session_data["traces"])
        compute_trajectories(session_eval, per_turn)

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
