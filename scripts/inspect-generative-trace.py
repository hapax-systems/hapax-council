#!/usr/bin/env python3
"""Inspect a Generative Episode Trace and answer Hapax's generative-agency questions.

Renders a ``GenerativeEpisodeTrace`` (shared/generative_trace.py) as direct answers
to the operator's question-TYPES, so the trace is read as evidence, not grepped:

  PROCESS      what did Hapax do before its first draft, and at what effort?
  PROVENANCE   what did it recruit — and what was OPERATIVE vs LATENT?
  DECISION     what decisory process / what informed the choices?
  ITERATION    are the iterations TRUE iterations, or re-rolls?
  IMPINGEMENT  what impingements arose, and did they propagate?
  STANCE       motivated angle? non-anthropomorphic voice? stumbling/lost?
  SELF_MODEL   what is Hapax's sense of its role?

Usage:
  inspect-generative-trace.py <trace.json>
  inspect-generative-trace.py --latest [--prep-dir DIR]   # newest trace in the dir
  inspect-generative-trace.py --prep-dir DIR --all        # summary of every episode
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_PREP_DIR = Path(
    os.environ.get("HAPAX_SEGMENT_PREP_DIR", str(Path.home() / ".cache" / "hapax" / "segment-prep"))
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_traces(prep_dir: Path) -> list[Path]:
    hits: list[Path] = []
    for base in (prep_dir, *sorted(prep_dir.glob("*/"))):
        d = base / "generative-traces"
        if d.is_dir():
            hits.extend(d.glob("*.json"))
    return sorted(hits, key=lambda p: p.stat().st_mtime)


def _bar(v: float | None) -> str:
    if v is None:
        return "  ? (not assessed)"
    n = max(0, min(10, round(v * 10)))
    return "█" * n + "·" * (10 - n) + f"  {v:.2f}"


def render(t: dict) -> str:
    out: list[str] = []
    p = out.append
    p(f"╔═ GENERATIVE EPISODE: {t.get('episode_id')}  ({t.get('role')})")
    p(f"║  topic: {t.get('topic', '')[:100]}")
    p(f"║  outcome: {t.get('outcome')}    schema v{t.get('schema_version')}")
    p("╚" + "═" * 70)

    # SELF_MODEL — sense of role
    sm = t.get("self_model") or {}
    p("\n● SELF-MODEL — what is Hapax's sense of its role?")
    p(f"   role={sm.get('role') or '—'}  goal={(sm.get('goal') or '—')[:70]}")
    p(f"   standpoint: {sm.get('standpoint') or '—'}  (from {sm.get('role_source') or '—'})")

    # PROCESS — what it did + effort
    proc = t.get("process") or []
    p("\n● PROCESS — what did it do, at what effort?")
    if not proc:
        p("   (no steps recorded — process unobserved)")
    for s in proc:
        eff = []
        if s.get("duration_s"):
            eff.append(f"{s['duration_s']:.0f}s")
        if s.get("llm_calls"):
            eff.append(f"{s['llm_calls']}llm")
        if s.get("tool_calls"):
            eff.append(f"{s['tool_calls']}tool")
        p(
            f"   - {s.get('name'):16} [{s.get('status')}] {' '.join(eff):10} {s.get('note', '')[:70]}"
        )

    # PROVENANCE — recruited + operative vs latent
    rec = t.get("recruitment") or []
    op = [r for r in rec if r.get("operativity") == "operative"]
    lat = [r for r in rec if r.get("operativity") == "latent"]
    unk = [r for r in rec if r.get("operativity") not in ("operative", "latent")]
    p("\n● PROVENANCE — what did it recruit? what was OPERATIVE vs LATENT?")
    p(
        f"   recruited {len(rec)}  →  operative {len(op)}  |  latent {len(lat)}  |  unknown {len(unk)}"
    )
    if rec and not op:
        p(
            "   ⚠ recruited material but NOTHING was operative — recruitment did not inform the draft"
        )
    for r in op:
        p(
            f"   ✓ OPERATIVE  {r.get('handle'):8} ({r.get('operativity_basis')})  {r.get('summary', '')[:64]}"
        )
    for r in lat[:8]:
        p(
            f"   · latent     {r.get('handle'):8} ({r.get('operativity_basis')})  {r.get('summary', '')[:64]}"
        )
    if len(lat) > 8:
        p(f"   · … +{len(lat) - 8} more latent")

    # DECISION
    dec = t.get("decisions") or []
    p("\n● DECISION — decisory process / what informed the choices?")
    if not dec:
        p("   (no decision records — the decisory reasoning is upstream/unobserved)")
    for d in dec:
        p(f"   - {d.get('decision')}: chose '{d.get('chosen', '')[:50]}' [{d.get('basis')}]")
        if d.get("alternatives"):
            p(f"       alternatives: {', '.join(map(str, d['alternatives']))[:70]}")
        if d.get("reasoning"):
            p(f"       reasoning: {d['reasoning'][:120]}")

    # ITERATION — true iteration vs re-roll
    it = t.get("iterations") or []
    p("\n● ITERATION — are these TRUE iterations, or re-rolls?")
    for d in it:
        p(
            f"   pass {d.get('pass_index')} [{d.get('kind')}] {d.get('beats')} beats, {d.get('chars')} chars"
        )
        if d.get("feedback_in"):
            p(f"       feedback in: {d['feedback_in'][:110]}")
        if d.get("delta_from_prev"):
            flag = (
                "⚠ "
                if "re-roll" in d["delta_from_prev"].lower()
                or "identical" in d["delta_from_prev"].lower()
                else ""
            )
            p(f"       Δ {flag}{d['delta_from_prev']}")
        if d.get("responded_to_feedback") is False:
            p("       ⚠ did NOT respond to feedback (no change)")

    # IMPINGEMENT
    imp = t.get("impingements") or []
    p("\n● IMPINGEMENT — what arose, did it propagate?")
    if not imp:
        p("   (none recorded — seg-prep has no impingement channel wired; itself a finding)")
    for i in imp:
        p(f"   - {i.get('source')} (mag {i.get('magnitude')}) influenced={i.get('influenced')}")

    # STANCE — motivated angle / non-anthro voice / stumbling
    st = t.get("stance") or []
    p("\n● STANCE — motivated angle? non-anthropomorphic voice? stumbling/lost?")
    if not st:
        p("   (no stance assessment recorded)")
    for a in st:
        p(f"   [pass {a.get('assessed_pass')} · assessor={a.get('assessor')}]")
        p(f"     motivated_angle        {_bar(a.get('motivated_angle'))}")
        p(f"     non_anthro_voice       {_bar(a.get('non_anthropomorphic_voice'))}")
        p(f"     argumentative_force    {_bar(a.get('argumentative_force'))}")
        p(f"     discursive_repertoire  {_bar(a.get('discursive_repertoire'))}")
        p(f"     directedness           {_bar(a.get('directedness'))}  (low = stumbling/lost)")
        if a.get("summary"):
            p(f"     summary: {a['summary'][:200]}")
    return "\n".join(out)


def _summary_line(path: Path) -> str:
    t = _load(path)
    rec = t.get("recruitment") or []
    op = sum(1 for r in rec if r.get("operativity") == "operative")
    it = t.get("iterations") or []
    rerolls = sum(1 for d in it if "identical" in (d.get("delta_from_prev") or "").lower())
    return (
        f"{t.get('episode_id'):28} {t.get('role'):10} {t.get('outcome'):16} "
        f"recruit={len(rec)} op={op} passes={len(it)} rerolls={rerolls}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("trace", nargs="?", help="path to a trace JSON")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--prep-dir", default=str(DEFAULT_PREP_DIR))
    args = ap.parse_args()

    prep_dir = Path(args.prep_dir)
    if args.trace:
        print(render(_load(Path(args.trace))))
        return 0
    traces = _find_traces(prep_dir)
    if not traces:
        print(f"no generative traces under {prep_dir}", file=sys.stderr)
        return 1
    if args.all:
        print(f"{len(traces)} episode(s) under {prep_dir}:\n")
        for tp in traces:
            print("  " + _summary_line(tp))
        return 0
    # default / --latest: render the newest
    print(render(_load(traces[-1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
