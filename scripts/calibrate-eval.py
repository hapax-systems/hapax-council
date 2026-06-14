#!/usr/bin/env python3
"""Eval calibration harness — the positive control the segment-prep eval never had.

Feeds the LIVE coherence council (``deliberate`` + ``CoherenceRubric`` — the exact
judgment ``daily_segment_prep._council_coherence_check`` runs) a labeled corpus of
authored KNOWN-GOOD and KNOWN-BAD segment scripts, and measures whether Hapax's
eval can *ACCEPT* good work — not merely *reject* bad work.

Why this exists
---------------
Across the entire segment-prep history the council has only ever said "no":
refuse, low-coherence, or degraded-panel. It is a proven REJECTOR but has never
once been shown a good artifact and observed to accept it — there is no positive
control anywhere in the cache (zero non-null ``mean_score`` in the pre-fix
corpus; every recorded production decision ``refused``). A transitive
produce -> eval -> re-produce loop driven by a never-yes evaluator *cannot
converge to a release*: it rejects every draft, good or bad, forever. So the
whole spec-author + evaluator architecture rests on one unmeasured number —
whether Hapax's judgment can recognise good work. This harness measures it.

The fixtures are authored against the rubric's OWN axis definitions: the GOOD
scripts hit every axis's ``strong_example`` (concrete paradox opening, beats that
build premise->evidence->complication->resolution, claims that name specific
systems/papers, an ending that pays off the opening); the BAD scripts hit every
``weak_example`` (generic context-setting opening, parallel repetition, generic
universals, no payoff). If the council cannot accept a script that matches its
own strong_example on every axis, it is a pure rejector and the transitive loop
is unsound regardless of every spec-guard.

Usage
-----
    uv run python scripts/calibrate-eval.py             # full corpus (3 good + 3 bad)
    uv run python scripts/calibrate-eval.py --quick     # 1 good + 1 bad
    uv run python scripts/calibrate-eval.py --json PATH # also write a JSON receipt
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Fixtures: authored directly against CoherenceRubric's axis strong/weak examples
# (agents/deliberative_council/rubrics.py::CoherenceRubric). Topics are concrete
# and self-contained so the score reflects COMPOSITION quality, not external
# verifiability (CoherenceRubric.requires_research is False — it scores a read).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fixture:
    fixture_id: str
    label: str  # "good" | "bad"
    rationale: str  # why this is unambiguously good/bad per the axes
    script: str


GOOD_FIXTURES: list[Fixture] = [
    Fixture(
        fixture_id="good-attention-sink",
        label="good",
        rationale=(
            "Opens on a concrete paradox naming a real system; beats build "
            "premise->evidence->complication->resolution; every claim names a "
            "specific paper/number; ending resolves the opening paradox."
        ),
        script=(
            "Delete the very first token from a transformer's context — a comma, "
            "the word 'the', a byte that carries no meaning — and a fluent 70-"
            "billion-parameter model starts producing garbage. That should be "
            "impossible. The first token is semantically empty. Removing it should "
            "change nothing.\n\n"
            "It changes everything, and the 2023 StreamingLLM work showed why. When "
            "you instrument where a trained transformer actually puts its attention, "
            "between fifty and eighty percent of it piles onto that first position — "
            "regardless of what token sits there. The model has learned to treat the "
            "opening slot as a dumping ground.\n\n"
            "Here is the complication: this is not a bug to be patched. Softmax "
            "attention is forced to distribute a full unit of weight across every "
            "step, even when a head has nothing it wants to look at. It needs "
            "somewhere to put the leftover. The first token, always present and "
            "always visible, becomes the pressure-relief valve — an 'attention "
            "sink'. The behaviour is load-bearing precisely because it is "
            "meaningless.\n\n"
            "Which dissolves the paradox. Drop the first token and you have not "
            "removed dead weight; you have removed the drain, and the unspent "
            "attention floods back into tokens that were never meant to hold it. The "
            "fix follows directly: keep four sink tokens pinned at the front, stream "
            "the rest of the window past them, and a model trained on four thousand "
            "tokens runs over four million with stable perplexity — twenty-two times "
            "faster than recomputing the cache. The empty token was doing the most "
            "important job in the sequence. We just had to notice it was there."
        ),
    ),
    Fixture(
        fixture_id="good-frozen-intent",
        label="good",
        rationale=(
            "Opens on a specific failure case; beats build to a named framework "
            "(Liskov behavioral subtyping); turns a vague worry into a precise "
            "mechanism; ending pays off the opening failure."
        ),
        script=(
            "A specification that gets better every single round, on a project that "
            "never ships. Watch it happen: each review the spec is sharpened, a "
            "clause tightened, an ambiguity resolved — and the product is no closer "
            "to release than it was a month ago. The spec is improving. So why is "
            "nothing converging?\n\n"
            "Because 'improving' was never defined. When the same agent that writes "
            "the spec also judges whether the product meets it, there is a quiet "
            "move available: instead of fixing the work, relax the criterion the "
            "work just failed. Strengthen a precondition so the current draft "
            "squeaks through. Soften a postcondition so yesterday's defect is now "
            "in-spec. The metric climbs. The thing the metric was supposed to "
            "protect rots.\n\n"
            "Barbara Liskov gave us the discipline that closes this in 1994: "
            "behavioral subtyping. A valid refinement may only weaken what it "
            "demands of its inputs and strengthen what it promises about its "
            "outputs — never the reverse. Apply that to a spec and the cheat "
            "becomes illegal by construction. Freeze the intent as a byte-exact "
            "anchor at the start of the episode. Permit only monotone refinements "
            "against it.\n\n"
            "Now the failure mode from the opening cannot occur. A spec edit that "
            "would let a failing draft pass is, definitionally, a strengthened "
            "precondition or a weakened postcondition — the one move the ratchet "
            "forbids. Moving the goalposts stops being a judgment call a tired "
            "reviewer might wave through, and becomes a type error a machine "
            "rejects. The spec that never converged was never being refined. It was "
            "being negotiated with. Take the negotiation away and it ships."
        ),
    ),
    Fixture(
        fixture_id="good-cegis-rejector",
        label="good",
        rationale=(
            "Opens on a sharp question; names CEGIS and its origin; introduces a "
            "real failure mode (unsound verifier); resolves into an actionable "
            "ordering that answers the opening."
        ),
        script=(
            "How do you search a space of programs that is literally infinite, and "
            "know when to stop? You cannot enumerate it. You cannot test your way "
            "across it. And yet program synthesis does exactly this, routinely, and "
            "terminates. The trick is older and stranger than it looks.\n\n"
            "It is called counterexample-guided inductive synthesis, CEGIS, from "
            "Armando Solar-Lezama's 2006 thesis. The structure is two players. A "
            "generator proposes a candidate program. A verifier tries to break it "
            "and, when it succeeds, hands back not a verdict but a specific "
            "counterexample — the exact input on which the candidate fails. That "
            "counterexample is added to the generator's constraints, so the next "
            "proposal cannot repeat the mistake. Each round strictly shrinks the "
            "space of programs still in play. That is why it terminates.\n\n"
            "But the whole machine has a single point of failure, and it is not the "
            "generator. It is the verifier. A verifier that wrongly accepts — that "
            "says 'this is correct' about a broken candidate — halts the loop on "
            "garbage and reports success. A verifier that can only ever reject "
            "never lets anything through and loops forever. The generator's "
            "cleverness is irrelevant if the judge cannot tell good from bad.\n\n"
            "So the ordering the opening demanded falls out on its own. Do not start "
            "by building a better generator; a synthesis loop is only ever as sound "
            "as its rejector, and only ever as useful as its acceptor. Prove the "
            "verifier can do both — reject what is wrong and accept what is right — "
            "before you trust a single program it returns. Build the judge first. "
            "Everything downstream inherits its blind spots."
        ),
    ),
]

BAD_FIXTURES: list[Fixture] = [
    Fixture(
        fixture_id="bad-generic-slop",
        label="bad",
        rationale=(
            "Generic context-setting opening ('In the realm of...'); parallel "
            "repetition; only generic universals, zero named sources; no payoff."
        ),
        script=(
            "In the realm of modern technology, few topics are as fascinating and "
            "important as artificial intelligence. It is something that affects all "
            "of us in many different ways, and it is well worth taking some time to "
            "consider.\n\n"
            "There are many factors to consider when thinking about this subject. On "
            "the one hand, there are numerous benefits. On the other hand, there are "
            "also various challenges that must be kept in mind. It is important to "
            "weigh these carefully.\n\n"
            "Experts from many fields have shared a wide range of perspectives. Some "
            "are optimistic, while others urge caution. As with so many things, the "
            "truth likely lies somewhere in the middle, and reasonable people can "
            "disagree.\n\n"
            "Ultimately, this is a complex and multifaceted issue with no easy "
            "answers. There is much still to be explored, and only time will tell "
            "how it all unfolds. One thing is certain: it will continue to be a "
            "topic worth watching in the years to come."
        ),
    ),
    Fixture(
        fixture_id="bad-circular-repetition",
        label="bad",
        rationale=(
            "Restates one empty point five ways; beats are parallel, removing any "
            "changes nothing; no named source; ending repeats the opening."
        ),
        script=(
            "Data is very important for making good decisions. When you have good "
            "data, you can make better decisions, and making better decisions is "
            "what good data helps you do.\n\n"
            "Decisions that are based on data tend to be better decisions. This is "
            "because the data informs the decision, and a decision that is informed "
            "by data is a more informed decision than one that is not.\n\n"
            "It is therefore clear that using data to inform decisions leads to "
            "decisions that are well-informed. Well-informed decisions are generally "
            "preferable, since being informed is better than not being informed.\n\n"
            "In summary, good data leads to good decisions, and good decisions come "
            "from good data. That is why data is so important when it comes to "
            "making the kinds of decisions that benefit from being data-driven."
        ),
    ),
    Fixture(
        fixture_id="bad-incoherent-drift",
        label="bad",
        rationale=(
            "Disconnected sentences, topic drift across beats, vague gestures, no "
            "through-line, no resolution of anything."
        ),
        script=(
            "Cloud computing has changed a lot over the years. The weather can be "
            "unpredictable, and many people enjoy a good cup of coffee in the "
            "morning before they start their work for the day.\n\n"
            "Scalability is a word that comes up often. Meanwhile, supply chains "
            "around the world are complex systems with many moving parts, and "
            "leadership is about bringing people together toward a common purpose.\n\n"
            "When we think about innovation, it is clear that there are trends. Some "
            "companies do well and others do not. The history of computing is long "
            "and full of interesting characters who each contributed in their own "
            "way.\n\n"
            "At the end of the day, what matters most is that we keep moving forward "
            "and stay open to new ideas, because the future is always arriving "
            "whether we are ready for it or not, and that is something to think "
            "about."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Eval: faithful replica of daily_segment_prep._council_coherence_check
# ---------------------------------------------------------------------------


@dataclass
class EvalResult:
    fixture: Fixture
    convergence_status: str = "error"
    mean_score: float | None = None
    scores: dict[str, Any] = field(default_factory=dict)
    members_valid: int | None = None
    families_valid: int | None = None
    failed_members: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def classification(self) -> str:
        """ACCEPT / REJECT / DEGRADED — same logic as the live coherence gate."""
        if self.error is not None:
            return "DEGRADED"
        valid = [s for s in self.scores.values() if s is not None]
        if self.convergence_status == "refused" or not valid:
            return "DEGRADED"
        if self.mean_score is None:
            return "DEGRADED"
        return "ACCEPT" if self.mean_score >= 3.0 else "REJECT"


MIXED_FIXTURES: list[Fixture] = [
    Fixture(
        fixture_id="mixed-strong-but-no-payoff",
        label="mixed",
        rationale=(
            "GRADIENT PROBE: concrete paradox opening + named sources + building "
            "beats (3 axes should score high), but the ending fizzles without "
            "resolving the opening (payoff_resolution should score LOW). If the "
            "eval scores all axes equal it is saturating, not discriminating."
        ),
        script=(
            "A database index can make a query a thousand times faster — and a "
            "thousand times slower. The same B-tree that turns a full-table scan "
            "into a millisecond lookup will, on the wrong query, force the planner "
            "into a random-IO crawl across the disk. Same structure, opposite "
            "outcome. Why?\n\n"
            "Jim Gray's work on the five-minute rule gives the frame: the cost of an "
            "index is paid in random reads, and random reads are where spinning "
            "disks and even SSDs are weakest. PostgreSQL's planner estimates this "
            "with a specific number, random_page_cost, defaulting to 4.0 against a "
            "sequential read's 1.0. When selectivity is low — when your query "
            "touches most of the table anyway — the planner correctly judges that "
            "scanning everything in order beats jumping around the index.\n\n"
            "So the index helps exactly when it touches few rows, and hurts exactly "
            "when it touches many, and the crossover depends on a cost constant most "
            "operators never tune for their actual storage.\n\n"
            "Anyway, databases are a deep topic and there is a lot to learn about "
            "them. There are many other features worth knowing as well. It is always "
            "good to keep reading and to stay curious about how these systems work "
            "under the hood. Thanks for listening."
        ),
    ),
    Fixture(
        fixture_id="mixed-built-but-generic",
        label="mixed",
        rationale=(
            "GRADIENT PROBE: a real arc (opening tension, building beats, a payoff) "
            "but ZERO named sources — only generic universals "
            "(argumentative_specificity should score LOW while the other three "
            "score mid-to-high)."
        ),
        script=(
            "Most teams think their biggest risk is moving too slowly. The opposite "
            "is usually true, and the failure is quiet until it isn't.\n\n"
            "Here is the pattern. A team ships fast by skipping the unglamorous "
            "work — the tests, the docs, the careful interfaces. For a while it "
            "looks like a win: features land, demos dazzle, everyone is busy. The "
            "cost is invisible because it has not come due yet.\n\n"
            "Then it compounds. Every new feature now rests on shaky foundations, so "
            "each one takes longer than the last. The very speed that looked like an "
            "advantage becomes the source of the slowdown, and the team cannot "
            "understand why they feel slower while working harder than ever.\n\n"
            "The resolution is counterintuitive but reliable: to go fast, you have "
            "to be willing to go slow first. The teams that invest early in the "
            "boring foundations are the ones still moving quickly a year later. "
            "Speed is not the enemy of quality. Skipped quality is the enemy of "
            "speed."
        ),
    ),
]


async def _eval_one(fixture: Fixture) -> EvalResult:
    from agents.deliberative_council.engine import deliberate
    from agents.deliberative_council.models import (
        CouncilConfig,
        CouncilInput,
        CouncilMode,
    )
    from agents.deliberative_council.rubrics import CoherenceRubric

    result = EvalResult(fixture=fixture)
    try:
        council_input = CouncilInput(
            text=fixture.script[:4000],
            source_ref=f"calibrate:{fixture.fixture_id}",
            metadata={"check_type": "coherence", "calibration_label": fixture.label},
        )
        verdict = await deliberate(
            council_input, CouncilMode.DISCONFIRMATION, CoherenceRubric(), CouncilConfig()
        )
    except Exception as e:  # noqa: BLE001 — calibration harness records, never raises
        result.error = f"{type(e).__name__}: {e}"
        return result

    health = verdict.receipt.get("council_health", {})
    result.convergence_status = verdict.convergence_status.value
    result.scores = dict(verdict.scores)
    result.members_valid = health.get("members_valid")
    result.families_valid = health.get("families_valid")
    result.failed_members = verdict.receipt.get("failed_members", [])
    valid = [s for s in result.scores.values() if s is not None]
    result.mean_score = (sum(valid) / len(valid)) if valid else None
    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _auc(good_means: list[float], bad_means: list[float]) -> float | None:
    """Rank-based AUC: P(a random good scores above a random bad). 1.0 = perfect."""
    if not good_means or not bad_means:
        return None
    wins = ties = 0
    for g in good_means:
        for b in bad_means:
            if g > b:
                wins += 1
            elif g == b:
                ties += 1
    return (wins + 0.5 * ties) / (len(good_means) * len(bad_means))


def _bar(score: float | None, width: int = 20) -> str:
    if score is None:
        return "·" * width + " (no score)"
    filled = round((score / 5.0) * width)
    return "█" * filled + "░" * (width - filled)


def render(results: list[EvalResult]) -> tuple[str, dict[str, Any]]:
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("EVAL CALIBRATION — the positive control (can Hapax's eval ACCEPT good work?)")
    lines.append("=" * 78)
    lines.append("")

    for r in results:
        tag = {"good": "✓ GOOD", "bad": "✗ BAD ", "mixed": "~ MIXED"}.get(r.fixture.label, "? ????")
        lines.append(f"[{tag}] {r.fixture.fixture_id}")
        if r.error:
            lines.append(f"        ERROR: {r.error}")
        mean_str = f"{r.mean_score:.2f}" if r.mean_score is not None else "—"
        lines.append(
            f"        mean={mean_str}/5  {_bar(r.mean_score)}  "
            f"[{r.classification}]  conv={r.convergence_status}  "
            f"members_valid={r.members_valid} families_valid={r.families_valid}"
        )
        for axis, score in r.scores.items():
            lines.append(f"          {axis:<26} {score}")
        if r.failed_members:
            lines.append(f"          failed_members: {', '.join(r.failed_members)}")
        lines.append("")

    good = [r for r in results if r.fixture.label == "good"]
    bad = [r for r in results if r.fixture.label == "bad"]
    mixed = [r for r in results if r.fixture.label == "mixed"]
    good_means = [r.mean_score for r in good if r.mean_score is not None]
    bad_means = [r.mean_score for r in bad if r.mean_score is not None]
    good_accepted = sum(1 for r in good if r.classification == "ACCEPT")
    bad_rejected = sum(1 for r in bad if r.classification == "REJECT")
    degraded = sum(1 for r in results if r.classification == "DEGRADED")
    auc = _auc(good_means, bad_means)
    separation = (
        statistics.mean(good_means) - statistics.mean(bad_means)
        if good_means and bad_means
        else None
    )

    lines.append("-" * 78)
    lines.append("SUMMARY")
    lines.append(f"  known-GOOD accepted:  {good_accepted}/{len(good)}   (positive control)")
    lines.append(f"  known-BAD  rejected:  {bad_rejected}/{len(bad)}   (negative control)")
    lines.append(f"  degraded/unscored:    {degraded}/{len(results)}")
    if good_means:
        lines.append(
            f"  good mean range:      {min(good_means):.2f}–{max(good_means):.2f} "
            f"(avg {statistics.mean(good_means):.2f})"
        )
    if bad_means:
        lines.append(
            f"  bad  mean range:      {min(bad_means):.2f}–{max(bad_means):.2f} "
            f"(avg {statistics.mean(bad_means):.2f})"
        )
    if separation is not None:
        lines.append(f"  separation (good-bad): {separation:+.2f}")
    if auc is not None:
        lines.append(f"  AUC (rank separation): {auc:.2f}   (1.0=perfect, 0.5=chance)")
    lines.append("")

    # Gradient probe: do mixed fixtures land in the middle, and does the eval
    # differentiate AXES (low payoff but high opening, etc.) rather than
    # saturating every axis to the same value? Per-axis spread >= 2 on a
    # fixture authored to be uneven = real per-axis discrimination.
    gradient_ok: bool | None = None
    if mixed:
        spreads: list[float] = []
        lines.append("GRADIENT PROBE (mixed fixtures — authored to score unevenly)")
        for r in mixed:
            vals = [s for s in r.scores.values() if s is not None]
            if not vals:
                lines.append(f"  {r.fixture.fixture_id}: no valid scores (degraded)")
                continue
            spread = max(vals) - min(vals)
            spreads.append(spread)
            lo_axis = min(r.scores.items(), key=lambda kv: (kv[1] is None, kv[1]))
            lines.append(
                f"  {r.fixture.fixture_id}: mean={r.mean_score:.2f} "
                f"axis-spread={spread} (lowest: {lo_axis[0]}={lo_axis[1]})"
            )
        if spreads:
            mid = sum(1 for r in mixed if r.mean_score is not None and 2.0 <= r.mean_score <= 4.0)
            gradient_ok = max(spreads) >= 2 or mid == len([r for r in mixed if r.mean_score])
            lines.append(
                f"  -> max axis-spread={max(spreads)} "
                f"({'differentiates axes' if max(spreads) >= 2 else 'SATURATING — axes move together'}); "
                f"{mid}/{len(mixed)} landed mid-range (2-4)"
            )
        lines.append("")

    # Verdict
    if degraded > len(results) / 2 or not good_means:
        verdict = "INCONCLUSIVE"
        detail = (
            "The council was too degraded to produce scored verdicts on most "
            "fixtures (members below quorum / refused). Fix Phase-0 reliability "
            "before re-reading this as eval quality."
        )
    elif good_accepted == 0:
        verdict = "PURE REJECTOR — positive control FAILS"
        detail = (
            "The eval rejected EVERY known-good script, including scripts authored to "
            "match its own strong_example on all four axes. It cannot recognise good "
            "work. The transitive produce->eval->re-produce loop is UNSOUND: a "
            "never-yes evaluator cannot converge to a release. The architecture's "
            "central bet is refuted as currently configured."
        )
    elif auc is not None and auc >= 0.75 and good_accepted >= 1:
        verdict = "EVAL DISCRIMINATES — positive control PASSES"
        detail = (
            "The eval accepted good work AND rejected bad work with clear rank "
            "separation. Hapax's judgment is a validated acceptor+rejector on this "
            "corpus — the foundation the spec-author+evaluator architecture needs. "
            "Next: widen the gold corpus + add the disconfirmation arm."
        )
    else:
        verdict = "WEAK / PARTIAL DISCRIMINATION"
        detail = (
            "The eval separates good from bad only weakly (low AUC or few accepts). "
            "Acceptor calibration is marginal — treat SURVIVED as advisory and "
            "investigate which axes collapse the good/bad gap before trusting a "
            "release-driving loop."
        )
    lines.append(f"VERDICT: {verdict}")
    lines.append(f"  {detail}")
    if gradient_ok is False:
        lines.append(
            "  CAVEAT: the eval saturates (axes move together) — it proves coarse "
            "good-vs-bad discrimination but fine good-vs-mediocre gradient is "
            "unconfirmed. A release-driving loop needs the gradient; widen with "
            "more good-but-flawed fixtures."
        )
    lines.append("=" * 78)

    summary = {
        "good_accepted": good_accepted,
        "good_total": len(good),
        "bad_rejected": bad_rejected,
        "bad_total": len(bad),
        "degraded": degraded,
        "good_means": good_means,
        "bad_means": bad_means,
        "separation": separation,
        "auc": auc,
        "gradient_differentiates_axes": gradient_ok,
        "verdict": verdict,
        "per_fixture": [
            {
                "fixture_id": r.fixture.fixture_id,
                "label": r.fixture.label,
                "classification": r.classification,
                "mean_score": r.mean_score,
                "convergence_status": r.convergence_status,
                "members_valid": r.members_valid,
                "families_valid": r.families_valid,
                "scores": r.scores,
                "error": r.error,
            }
            for r in results
        ],
    }
    return "\n".join(lines), summary


async def _run(fixtures: list[Fixture]) -> list[EvalResult]:
    # Sequential (not gathered): each deliberation already fans out to ~5
    # concurrent members; running episodes in parallel would stampede the
    # provider rate limits and manufacture the very degradation we measure.
    results: list[EvalResult] = []
    for fx in fixtures:
        print(f"  evaluating {fx.fixture_id} ({fx.label}) ...", file=sys.stderr, flush=True)
        results.append(await _eval_one(fx))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="1 good + 1 bad only")
    parser.add_argument("--json", metavar="PATH", help="write a JSON receipt")
    args = parser.parse_args()

    good = GOOD_FIXTURES[:1] if args.quick else GOOD_FIXTURES
    bad = BAD_FIXTURES[:1] if args.quick else BAD_FIXTURES
    mixed = [] if args.quick else MIXED_FIXTURES
    # interleave so a mid-run rate-limit hits both classes, not all of one
    fixtures: list[Fixture] = []
    for g, b in zip(good, bad, strict=False):
        fixtures.extend([g, b])
    fixtures.extend(good[len(bad) :])
    fixtures.extend(bad[len(good) :])
    fixtures.extend(mixed)

    results = asyncio.run(_run(fixtures))
    report, summary = render(results)
    print(report)

    if args.json:
        import json

        with open(args.json, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"\nreceipt -> {args.json}", file=sys.stderr)

    # Exit non-zero on a failed positive control so CI / callers can gate on it.
    return 0 if summary["verdict"].startswith(("EVAL DISCRIMINATES", "WEAK")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
