#!/usr/bin/env python3
"""Compose-model bakeoff — which model can compose a segment that clears coherence?

The verified diagnosis (2026-06-14) + the post-src:N canary established that the
resident Command-R 35B is at its COMPOSITIONAL ceiling: even on real cited
sources, with a genuine 47%-rewrite refine responding to per-axis feedback, it
scores coherence mean=2.0 (opening_pressure=2, payoff_resolution=1) — a rhetorical
deficit independent of source quality. Fixing the coherence gate therefore needs
a stronger COMPOSER, and there are two paths with very different governance cost:

  (B) swap the resident compose model to a stronger LOCAL model (e.g. the
      Qwen3.6-35B-A3B-abliterated already served on TabbyAPI) — preserves the
      resident/local architecture, modest governance.
  (A) outsource compose to a cloud family (opus/gemini) — high governance, a
      provenance-invariant amendment, and a question about Hapax's broadcast voice.

This bakeoff produces the decision data: hold the topic + sources + compose
instruction CONSTANT and compose with each candidate model, then score every
composition with the SAME validated coherence council (the eval calibrated to
AUC 1.0 in PR #4133). It isolates compositional capability and answers: does a
local swap clear coherence>=3, or is cloud outsourcing required?

Usage:
    uv run python scripts/compose-model-bakeoff.py
    uv run python scripts/compose-model-bakeoff.py --json PATH
    uv run python scripts/compose-model-bakeoff.py --only opus,local-qwen36
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.request
from dataclasses import dataclass, field

from shared.config import LITELLM_BASE, LITELLM_KEY

TABBY_CHAT_URL = "http://localhost:5000/v1/chat/completions"
LITELLM_CHAT_URL = LITELLM_BASE.rstrip("/") + "/chat/completions"


# ── candidate composers (label -> endpoint + model id) ────────────────────────


@dataclass(frozen=True)
class Composer:
    label: str
    endpoint: str  # "tabby" | "litellm"
    model_id: str
    note: str


COMPOSERS: list[Composer] = [
    Composer(
        "resident-command-r",
        "tabby",
        "command-r-08-2024-exl3-5.0bpw",
        "current resident (baseline)",
    ),
    Composer(
        "local-qwen36",
        "tabby",
        "Qwen3.6-35B-A3B-abliterated-exl3-6.0bpw",
        "local swap candidate (path B)",
    ),
    Composer("opus", "litellm", "opus", "cloud outsource candidate (path A)"),
    Composer("gemini-3-pro", "litellm", "gemini-3-pro", "cloud outsource candidate (path A)"),
]


# ── the constant compose task (topic + real sources + rubric-aligned instruction) ─
# Sources are genuine, self-contained domain facts so every model has identical
# grounding material; the variable under test is compositional capability.

TOPIC = "Why adding a database index can make a query a thousand times slower"

SOURCES = [
    (
        "src:0  [Gray & Putzolu, the five-minute rule]",
        "An index access is paid for in RANDOM I/O. Gray's five-minute-rule analysis "
        "frames the trade: random reads are where storage is weakest, so an index only "
        "pays off when it lets you touch FEW rows instead of many.",
    ),
    (
        "src:1  [PostgreSQL planner: random_page_cost]",
        "PostgreSQL's planner estimates index cost with random_page_cost, default 4.0, "
        "versus a sequential read's 1.0. When a query's selectivity is low (it will "
        "touch most of the table anyway), the planner correctly chooses a sequential "
        "scan over the index.",
    ),
    (
        "src:2  [B-tree selectivity crossover]",
        "The crossover point where an index stops helping and starts hurting depends on "
        "selectivity and the cost constant; most operators never tune random_page_cost "
        "for their actual storage (SSD random reads are far cheaper than the 4.0 default "
        "assumes), so the planner's index/scan choice is often miscalibrated.",
    ),
]

COMPOSE_INSTRUCTION = (
    "You are composing a single spoken-word broadcast segment (4 beats). Compose it "
    "to WORK as narrative, not to summarize. Hard requirements:\n"
    "- OPENING: open on a concrete paradox or failure that demands resolution — name "
    "a specific system. Do NOT open with generic context-setting ('In the realm of "
    "X, Y is important').\n"
    "- PROGRESSION: each beat must BUILD on the last (premise -> evidence -> "
    "complication -> resolution); no parallel repetition.\n"
    "- SPECIFICITY: ground every claim in the named sources below; cite them.\n"
    "- PAYOFF: the final beat must resolve the opening paradox.\n"
    "- Each beat 800-2000 characters. Non-anthropomorphic; no host filler "
    "('Welcome to', 'Let's delve into').\n\n"
    f"TOPIC: {TOPIC}\n\nSOURCES:\n"
    + "\n".join(f"{ref}\n{text}" for ref, text in SOURCES)
    + "\n\nRespond with ONLY the segment as 4 beats separated by blank lines."
)


def _chat(composer: Composer, *, timeout: float = 180.0) -> str:
    url = TABBY_CHAT_URL if composer.endpoint == "tabby" else LITELLM_CHAT_URL
    payload = {
        "model": composer.model_id,
        "messages": [{"role": "user", "content": COMPOSE_INSTRUCTION}],
        "max_tokens": 3000,
        "temperature": 0.7,
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if composer.endpoint == "litellm" and LITELLM_KEY:
        headers["Authorization"] = f"Bearer {LITELLM_KEY}"
    req = urllib.request.Request(url, body, headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


# ── scoring via the validated coherence council ───────────────────────────────


@dataclass
class BakeoffResult:
    composer: Composer
    composed_chars: int = 0
    mean_score: float | None = None
    scores: dict[str, int] = field(default_factory=dict)
    members_valid: int | None = None
    convergence: str = "error"
    error: str | None = None

    @property
    def clears_gate(self) -> bool:
        return (
            self.mean_score is not None and self.mean_score >= 3.0 and self.convergence != "refused"
        )


async def _score(script_text: str, label: str) -> tuple[float | None, dict, int | None, str]:
    from agents.deliberative_council.engine import deliberate
    from agents.deliberative_council.models import CouncilConfig, CouncilInput, CouncilMode
    from agents.deliberative_council.rubrics import CoherenceRubric

    verdict = await deliberate(
        CouncilInput(text=script_text[:4000], source_ref=f"bakeoff:{label}"),
        CouncilMode.DISCONFIRMATION,
        CoherenceRubric(),
        CouncilConfig(),
    )
    scores = {k: v for k, v in verdict.scores.items() if v is not None}
    mean = (sum(scores.values()) / len(scores)) if scores else None
    health = verdict.receipt.get("council_health", {})
    return mean, scores, health.get("members_valid"), verdict.convergence_status.value


async def _run_one(composer: Composer) -> BakeoffResult:
    result = BakeoffResult(composer=composer)
    try:
        print(f"  composing with {composer.label} ...", file=sys.stderr, flush=True)
        script = _chat(composer)
        result.composed_chars = len(script)
        print(f"  scoring {composer.label} ({len(script)} chars) ...", file=sys.stderr, flush=True)
        mean, scores, mv, conv = await _score(script, composer.label)
        result.mean_score, result.scores, result.members_valid, result.convergence = (
            mean,
            scores,
            mv,
            conv,
        )
    except Exception as e:  # noqa: BLE001 — bakeoff records failures, never raises
        result.error = f"{type(e).__name__}: {e}"
    return result


def render(results: list[BakeoffResult]) -> str:
    lines = [
        "=" * 78,
        "COMPOSE-MODEL BAKEOFF — coherence of each composer (gate = mean>=3)",
        "=" * 78,
        "",
    ]
    for r in results:
        lines.append(f"[{r.composer.label}]  ({r.composer.note})")
        if r.error:
            lines.append(f"    ERROR: {r.error}")
            lines.append("")
            continue
        gate = "✓ CLEARS GATE" if r.clears_gate else "✗ below gate"
        mean = f"{r.mean_score:.2f}" if r.mean_score is not None else "—"
        lines.append(
            f"    coherence mean={mean}/5  [{gate}]  members_valid={r.members_valid}  "
            f"conv={r.convergence}  composed={r.composed_chars}c"
        )
        for axis, score in sorted(r.scores.items()):
            lines.append(f"      {axis:<26} {score}")
        lines.append("")
    lines.append("-" * 78)
    cleared = [r.composer.label for r in results if r.clears_gate]
    lines.append(f"CLEARS coherence gate (mean>=3): {', '.join(cleared) or 'NONE'}")
    lines.append(
        "DECISION INPUT: if a LOCAL model clears the gate, a resident swap (path B) "
        "fixes coherence without cloud outsourcing; if only CLOUD models clear it, the "
        "producer-seam (path A) is required."
    )
    lines.append("=" * 78)
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", help="comma-separated composer labels to run")
    ap.add_argument("--json", metavar="PATH", help="write a JSON receipt")
    args = ap.parse_args()

    composers = COMPOSERS
    if args.only:
        wanted = {s.strip() for s in args.only.split(",")}
        composers = [c for c in COMPOSERS if c.label in wanted]

    async def _run() -> list[BakeoffResult]:
        out = []
        for c in composers:  # sequential — each scoring fans out ~6 council members
            out.append(await _run_one(c))
        return out

    results = asyncio.run(_run())
    print(render(results))

    if args.json:
        with open(args.json, "w") as f:
            json.dump(
                [
                    {
                        "label": r.composer.label,
                        "model_id": r.composer.model_id,
                        "endpoint": r.composer.endpoint,
                        "mean_score": r.mean_score,
                        "scores": r.scores,
                        "members_valid": r.members_valid,
                        "convergence": r.convergence,
                        "clears_gate": r.clears_gate,
                        "composed_chars": r.composed_chars,
                        "error": r.error,
                    }
                    for r in results
                ],
                f,
                indent=2,
            )
        print(f"\nreceipt -> {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
