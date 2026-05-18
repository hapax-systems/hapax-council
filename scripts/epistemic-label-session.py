#!/usr/bin/env python3
"""Interactive epistemic quality labeling session.

Presents golden dataset records one at a time, collects operator scores
on 4 axes (1-5), writes labels to JSONL output file.

Usage:
    uv run python scripts/epistemic-label-session.py [--start N] [--batch N]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

DATASET = (
    Path.home()
    / "Documents/Personal/20-projects/hapax-research/datasets/epistemic-quality/phase0-golden-dataset-v0-curated.jsonl"
)
OUTPUT = (
    Path.home()
    / "Documents/Personal/20-projects/hapax-research/datasets/epistemic-quality/phase0-human-labels-round1-v0.jsonl"
)

AXES = [
    (
        "claim_evidence_alignment",
        "Does the claim ceiling match the attached evidence? (1=outruns, 5=matches)",
    ),
    ("hedge_calibration", "Is confidence language well calibrated? (1=mismatched, 5=calibrated)"),
    ("quantifier_precision", "Are quantities exact and scoped? (1=vague/fake, 5=exact/absent)"),
    ("source_grounding", "Are sources independently traceable? (1=source-free, 5=traceable)"),
]


def load_dataset() -> list[dict]:
    rows = []
    for line in DATASET.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_existing_labels() -> set[str]:
    if not OUTPUT.exists():
        return set()
    labeled = set()
    for line in OUTPUT.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            labeled.add(row["id"])
    return labeled


def dataset_hash() -> str:
    return hashlib.sha256(DATASET.read_bytes()).hexdigest()


def write_label(record: dict, labels: dict[str, int], manifest_hash: str) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "id": record["id"],
        "manifest_hash": manifest_hash,
        "source_ref": record["source_ref"],
        "source_text_hash": record["excerpt_hash"],
        "label_round": "round1",
        "labeler": "operator",
        "label_origin": "operator",
        "labeled_at": datetime.now(UTC).isoformat(),
        "provenance": "operator_label_entry",
        "labels": labels,
    }
    with OUTPUT.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_score(axis_name: str, description: str) -> int:
    while True:
        try:
            val = input(f"  {axis_name} — {description}: ").strip()
            if val.lower() in ("q", "quit", "exit"):
                return -1
            score = int(val)
            if 1 <= score <= 5:
                return score
            print("    Enter 1-5 (or q to quit)")
        except (ValueError, EOFError):
            print("    Enter 1-5 (or q to quit)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0, help="Start at record N (0-indexed)")
    parser.add_argument("--batch", type=int, default=10, help="How many records per session")
    parser.add_argument("--tier", type=str, default=None, help="Filter to tier A/B/C/D")
    args = parser.parse_args()

    records = load_dataset()
    labeled = load_existing_labels()
    manifest_hash = dataset_hash()

    if args.tier:
        records = [r for r in records if r["tier"].upper() == args.tier.upper()]

    unlabeled = [r for r in records if r["id"] not in labeled]

    print("\n=== Epistemic Quality Phase 0 Labeling ===")
    print(f"Dataset: {len(records)} records ({len(records) - len(unlabeled)} already labeled)")
    print(f"This session: up to {args.batch} records starting from offset {args.start}")
    print("Score each excerpt on 4 axes (1-5). Enter 'q' to stop.\n")

    batch = unlabeled[args.start : args.start + args.batch]
    completed = 0

    for i, record in enumerate(batch):
        print(f"\n{'=' * 70}")
        print(
            f"[{args.start + i + 1}/{len(unlabeled)}] {record['id']}  |  Tier {record['tier']}  |  {record['domain_partition']}"
        )
        print(f"Source: {record['source_ref']}")
        if record.get("relabel_required"):
            print("** This record is in the relabel subset **")
        print(f"{'─' * 70}")
        excerpt = record["excerpt"]
        if len(excerpt) > 800:
            print(excerpt[:800] + f"\n... [{len(excerpt) - 800} more chars]")
        else:
            print(excerpt)
        print(f"{'─' * 70}")

        labels = {}
        quit_requested = False
        for axis_name, description in AXES:
            score = get_score(axis_name, description)
            if score == -1:
                quit_requested = True
                break
            labels[axis_name] = score

        if quit_requested:
            print(f"\nStopping. {completed} labels written this session.")
            break

        write_label(record, labels, manifest_hash)
        completed += 1
        total_labeled = len(labeled) + completed
        print(f"  ✓ Saved. Total labeled: {total_labeled}/200")

    print(f"\n=== Session complete: {completed} new labels ===")
    print(f"Total labeled: {len(labeled) + completed}/200")
    if len(labeled) + completed < 200:
        print(f"Remaining: {200 - len(labeled) - completed}")
        print("Resume with: uv run python scripts/epistemic-label-session.py")


if __name__ == "__main__":
    main()
