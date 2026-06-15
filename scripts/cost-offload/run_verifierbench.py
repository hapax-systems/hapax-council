#!/usr/bin/env python3
"""Validate the local CompassVerifier-7B judge against VerifierBench gold labels.

Faithful replication of the official eval:
  - CV_PROMPT (non-CoT, single-letter A/B/C) from open-compass/CompassVerifier src/prompts.py
  - process_judgment() verdict parser, verbatim from src/cv_eval.ipynb
  - greedy decoding (temperature=0)

AC4: measured F1 within +/-3 of the published CompassVerifier-7B number (83.4),
confirming the GGUF Q5_K_M quant did not degrade the judge.

Zero provider spend: gold labels are the dataset's own expert annotations.
"""

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

# --- verbatim from src/prompts.py (CV_PROMPT, the non-CoT single-letter variant) ---
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


def process_judgment(judgment_str: str) -> str:
    """Verbatim from src/cv_eval.ipynb."""
    boxed_matches = re.findall(r"boxed{([A-C])}", judgment_str)
    if boxed_matches:
        return boxed_matches[-1]
    if judgment_str in ["A", "B", "C"]:
        return judgment_str
    else:
        final_judgment_str = judgment_str.split("Final Judgment:")[-1]
        matches = re.findall(r"\(([A-C])\)*", final_judgment_str)
        if matches:
            return matches[-1]
        matches = re.findall(r"([A-C])", final_judgment_str)
        if matches:
            return matches[-1]
        return ""


def judge_one(endpoint, model, row, timeout=120):
    content = CV_PROMPT.format(
        question=row["question"],
        gold_answer=row["gold_answer"],
        llm_response=row["llm_response"],
    )
    try:
        r = requests.post(
            f"{endpoint}/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": 8,
                "temperature": 0,
            },
            timeout=timeout,
        )
        if r.status_code != 200:
            return {"pred": "", "raw": "", "error": f"http{r.status_code}:{r.text[:120]}"}
        out = r.json()["choices"][0]["message"]["content"]
        return {"pred": process_judgment(out.strip()), "raw": out, "error": None}
    except Exception as e:  # noqa: BLE001
        return {"pred": "", "raw": "", "error": str(e)[:160]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="verifierbench_test.parquet")
    ap.add_argument("--endpoint", default="http://192.168.68.50:5001")
    ap.add_argument("--model", default="compassverifier-7b")
    ap.add_argument("--n", type=int, default=0, help="0 = all rows")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default="verifierbench_results.jsonl")
    args = ap.parse_args()

    df = pd.read_parquet(args.parquet).reset_index(drop=True)
    if args.n and args.n < len(df):
        # stratified by gold_judgment to preserve class balance
        frac = args.n / len(df)
        df = (
            df.groupby("gold_judgment", group_keys=False)
            .sample(frac=frac, random_state=42)
            .reset_index(drop=True)
        )
    print(
        f"judging {len(df)} items via {args.endpoint} ({args.model}) workers={args.workers}",
        flush=True,
    )

    results = [None] * len(df)
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(judge_one, args.endpoint, args.model, df.iloc[i]): i for i in range(len(df))
        }
        for fut in as_completed(futs):
            i = futs[fut]
            res = fut.result()
            results[i] = res
            done += 1
            if done % 200 == 0:
                print(f"  {done}/{len(df)}  ({time.time() - t0:.0f}s)", flush=True)

    df["pred"] = [r["pred"] for r in results]
    df["raw"] = [r["raw"] for r in results]
    df["error"] = [r["error"] for r in results]

    with open(args.out, "w") as f:
        for i in range(len(df)):
            f.write(
                json.dumps(
                    {
                        "gold": df.iloc[i]["gold_judgment"],
                        "pred": df.iloc[i]["pred"],
                        "domain": df.iloc[i]["domain"],
                        "error": df.iloc[i]["error"],
                        "raw": df.iloc[i]["raw"],
                    }
                )
                + "\n"
            )

    # ---- metrics ----
    errs = df[df["error"].notnull()]
    valid = df[(df["error"].isnull()) & (df["pred"].isin(["A", "B", "C"]))]
    print(f"\nelapsed {time.time() - t0:.0f}s | errors/skips: {len(errs)} | scored: {len(valid)}")
    if len(errs):
        print("error sample:", errs["error"].value_counts().head(3).to_dict())

    labels = ["A", "B", "C"]
    gold = valid["gold_judgment"].tolist()
    pred = valid["pred"].tolist()
    acc = sum(g == p for g, p in zip(gold, pred, strict=False)) / len(valid)

    def prf(cls):
        tp = sum(g == cls and p == cls for g, p in zip(gold, pred, strict=False))
        fp = sum(g != cls and p == cls for g, p in zip(gold, pred, strict=False))
        fn = sum(g == cls and p != cls for g, p in zip(gold, pred, strict=False))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        return prec, rec, f1, tp + fn

    print(f"\nAccuracy: {acc * 100:.1f}%  (n={len(valid)})")
    print(f"{'class':<6}{'prec':>8}{'recall':>8}{'f1':>8}{'support':>9}")
    macro = []
    for c in labels:
        p_, r_, f_, sup = prf(c)
        macro.append(f_)
        print(f"{c:<6}{p_ * 100:>7.1f}%{r_ * 100:>7.1f}%{f_ * 100:>7.1f}%{sup:>9}")
    macro_f1 = sum(macro) / len(macro)
    # binary correctness F1 (A = positive)
    bp, br, bf, _ = prf("A")
    print(f"\nMacro-F1 (A/B/C): {macro_f1 * 100:.1f}")
    print(f"Binary 'CORRECT' F1 (A vs B,C): {bf * 100:.1f}")

    # confusion matrix
    print("\nConfusion (rows=gold, cols=pred):")
    print(f"{'':<6}" + "".join(f"{c:>7}" for c in labels))
    for g in labels:
        row = [
            sum(1 for gg, pp in zip(gold, pred, strict=False) if gg == g and pp == c)
            for c in labels
        ]
        print(f"{g:<6}" + "".join(f"{x:>7}" for x in row))

    # conservative-skew analysis: a judge error is "conservative" if it does NOT
    # turn an incorrect/invalid answer into CORRECT (i.e. does not false-accept).
    # false-accept = gold in {B,C} but pred == A.
    disagree = [(g, p) for g, p in zip(gold, pred, strict=False) if g != p]
    false_accept = sum(1 for g, p in disagree if g in ("B", "C") and p == "A")
    false_reject = sum(1 for g, p in disagree if g == "A" and p in ("B", "C"))
    print(f"\nDisagreements: {len(disagree)}")
    print(f"  false-ACCEPT (gold B/C -> pred A, the dangerous kind): {false_accept}")
    print(f"  false-REJECT (gold A -> pred B/C, the conservative kind): {false_reject}")
    other = len(disagree) - false_accept - false_reject
    print(f"  B<->C confusions (both 'not correct'): {other}")


if __name__ == "__main__":
    main()
