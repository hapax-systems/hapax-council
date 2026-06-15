#!/usr/bin/env python3
"""Analyze VerifierBench judge results: F1 (AC4), Cohen's kappa + agreement +
conservative-skew (AC3-vs-expert-gold). Reads the jsonl emitted by run_verifierbench.py.

VerifierBench gold_judgment is expert-annotated -> serves as an authoritative
('frontier-grade') reference at zero provider spend. AC3's council-distribution
agreement is accumulated separately via shadow logging; this establishes the
judge's agreement/skew against an authoritative reference now.
"""

import argparse
import json
from collections import Counter

LABELS = ["A", "B", "C"]


def cohen_kappa(gold, pred, labels):
    n = len(gold)
    po = sum(g == p for g, p in zip(gold, pred, strict=False)) / n
    gc = Counter(gold)
    pc = Counter(pred)
    pe = sum((gc.get(l, 0) / n) * (pc.get(l, 0) / n) for l in labels)
    return (po - pe) / (1 - pe) if (1 - pe) else 1.0


def prf(gold, pred, cls):
    tp = sum(g == cls and p == cls for g, p in zip(gold, pred, strict=False))
    fp = sum(g != cls and p == cls for g, p in zip(gold, pred, strict=False))
    fn = sum(g == cls and p != cls for g, p in zip(gold, pred, strict=False))
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return prec, rec, f1, tp + fn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="verifierbench_results.jsonl")
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.results)]
    total = len(rows)

    def err_of(r):
        # JSONL may carry NaN (float) for no-error rows due to pandas None->NaN
        e = r.get("error")
        return e if isinstance(e, str) and e else None

    errs = [r for r in rows if err_of(r)]
    valid = [r for r in rows if not err_of(r) and r.get("pred") in LABELS]
    unparsed = [r for r in rows if not err_of(r) and r.get("pred") not in LABELS]

    gold = [r["gold"] for r in valid]
    pred = [r["pred"] for r in valid]

    print(
        f"total={total}  scored={len(valid)}  errors/ctx-skip={len(errs)}  unparsed={len(unparsed)}"
    )
    if errs:
        print("  error kinds:", Counter(err_of(e)[:40] for e in errs).most_common(3))

    acc = sum(g == p for g, p in zip(gold, pred, strict=False)) / len(valid)
    kappa = cohen_kappa(gold, pred, LABELS)
    print("\n=== AC3 (agreement vs expert gold) ===")
    print(f"Agreement (accuracy): {acc * 100:.2f}%")
    print(f"Cohen's kappa:        {kappa:.3f}")

    print("\n=== AC4 (F1 vs published 83.4) ===")
    print(f"{'class':<6}{'prec':>8}{'recall':>8}{'f1':>8}{'support':>9}")
    macro = []
    for c in LABELS:
        p_, r_, f_, sup = prf(gold, pred, c)
        macro.append(f_)
        print(f"{c:<6}{p_ * 100:>7.1f}%{r_ * 100:>7.1f}%{f_ * 100:>7.1f}%{sup:>9}")
    macro_f1 = sum(macro) / len(macro)
    bp, br, bf, _ = prf(gold, pred, "A")
    print(f"Macro-F1 (A/B/C):            {macro_f1 * 100:.2f}")
    print(f"Binary CORRECT F1 (A vs BC): {bf * 100:.2f}")

    print("\nConfusion (rows=gold, cols=pred):")
    print(f"{'':<6}" + "".join(f"{c:>7}" for c in LABELS))
    for g in LABELS:
        line = [
            sum(1 for gg, pp in zip(gold, pred, strict=False) if gg == g and pp == c)
            for c in LABELS
        ]
        print(f"{g:<6}" + "".join(f"{x:>7}" for x in line))

    disagree = [(g, p) for g, p in zip(gold, pred, strict=False) if g != p]
    false_accept = sum(1 for g, p in disagree if g in ("B", "C") and p == "A")
    false_reject = sum(1 for g, p in disagree if g == "A" and p in ("B", "C"))
    bc = len(disagree) - false_accept - false_reject
    print("\n=== Conservative-skew (AC3) ===")
    print(f"Disagreements: {len(disagree)} ({len(disagree) / len(valid) * 100:.1f}%)")
    print(
        f"  false-ACCEPT (gold B/C -> pred A) [DANGEROUS]: {false_accept} ({false_accept / len(valid) * 100:.2f}% of all)"
    )
    print(f"  false-REJECT (gold A -> pred B/C) [conservative]: {false_reject}")
    print(f"  B<->C (both 'not correct')         [harmless-ish]: {bc}")
    fa_share = false_accept / len(disagree) * 100 if disagree else 0
    print(
        f"  false-accepts are {fa_share:.1f}% of disagreements -> "
        f"{'CONSERVATIVE-SKEWED (good)' if fa_share < 40 else 'NOT conservative-skewed'}"
    )

    # per-domain accuracy
    print("\nPer-domain agreement:")
    doms = sorted(set(r["domain"] for r in valid))
    for d in doms:
        sub = [(r["gold"], r["pred"]) for r in valid if r["domain"] == d]
        a = sum(g == p for g, p in sub) / len(sub)
        print(f"  {d:<20} {a * 100:>5.1f}%  (n={len(sub)})")


if __name__ == "__main__":
    main()
