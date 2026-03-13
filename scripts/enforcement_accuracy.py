#!/usr/bin/env python3
"""enforcement_accuracy.py — Observability for output enforcement pattern accuracy.

Three modes:
  backfill   Scan historical output files, write matches to audit log
  label      Interactively label audit entries as TP/FP
  report     Per-pattern accuracy stats + readiness assessment

Usage:
    uv run python scripts/enforcement_accuracy.py backfill
    uv run python scripts/enforcement_accuracy.py label
    uv run python scripts/enforcement_accuracy.py report
    uv run python scripts/enforcement_accuracy.py report --json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────

COUNCIL_ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = COUNCIL_ROOT / "profiles"
AUDIT_LOG = PROFILES_DIR / ".enforcement-audit.jsonl"
LABELS_FILE = PROFILES_DIR / ".enforcement-labels.jsonl"

# Historical output sources
VAULT_BRIEFINGS = Path.home() / "Documents" / "Work" / "30-system" / "briefings"
VAULT_DIGESTS = Path.home() / "Documents" / "Work" / "30-system" / "digests"
DIGEST_HISTORY = PROFILES_DIR / "digest-history.jsonl"

# Minimum labeled samples per pattern before it's considered "assessed"
MIN_SAMPLES_FOR_CONFIDENCE = 5
# Maximum FP rate to recommend enabling blocking
MAX_FP_RATE_FOR_BLOCKING = 0.10


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class AuditEntry:
    timestamp: str
    agent_id: str
    output_path: str
    allowed: bool
    audit_only: bool
    violations: list[dict]
    source: str = "live"  # "live" | "backfill"


@dataclass
class Label:
    timestamp: str
    pattern_id: str
    matched_text: str
    context: str  # surrounding text
    verdict: str  # "tp" | "fp"
    agent_id: str
    note: str = ""


@dataclass
class PatternStats:
    pattern_id: str
    total: int
    labeled: int
    tp: int
    fp: int
    unlabeled: int

    @property
    def precision(self) -> float | None:
        if self.labeled == 0:
            return None
        return self.tp / self.labeled

    @property
    def fp_rate(self) -> float | None:
        if self.labeled == 0:
            return None
        return self.fp / self.labeled

    @property
    def assessed(self) -> bool:
        return self.labeled >= MIN_SAMPLES_FOR_CONFIDENCE


# ── Backfill ─────────────────────────────────────────────────────────────────


def _scan_file(path: Path, agent_id: str) -> list[dict]:
    """Run enforcement patterns against a single file, return audit entries."""
    from shared.axiom_pattern_checker import check_output

    try:
        text = path.read_text()
    except OSError:
        return []

    violations = check_output(text)
    if not violations:
        return []

    entries = []
    for v in violations:
        # Extract context: 60 chars before and after the match
        start = max(0, v.match_start - 60)
        end = min(len(text), v.match_end + 60)
        context = text[start:end].replace("\n", " ").strip()

        entries.append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "agent_id": agent_id,
            "output_path": str(path),
            "allowed": True,
            "audit_only": True,
            "source": "backfill",
            "violations": [{
                "pattern_id": v.pattern_id,
                "tier": v.tier,
                "matched_text": v.matched_text,
                "axiom_id": v.axiom_id,
                "context": context,
            }],
        })

    return entries


def cmd_backfill() -> None:
    """Scan all historical output and write matches to audit log."""
    sources: list[tuple[Path, str]] = []

    # Vault briefings
    if VAULT_BRIEFINGS.exists():
        for f in sorted(VAULT_BRIEFINGS.glob("*.md")):
            sources.append((f, "briefing"))

    # Vault digests
    if VAULT_DIGESTS.exists():
        for f in sorted(VAULT_DIGESTS.glob("*.md")):
            sources.append((f, "digest"))

    # Current profiles
    for name in ("briefing.md", "digest.md", "operator-profile.md", "scout-report.md"):
        p = PROFILES_DIR / name
        if p.exists():
            agent = name.replace(".md", "").replace("-", "_")
            sources.append((p, agent))

    # Digest history (JSONL — extract text fields)
    if DIGEST_HISTORY.exists():
        from shared.axiom_pattern_checker import check_output

        count = 0
        for line in DIGEST_HISTORY.read_text().splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            # Check headline + body + notable items
            parts = []
            for field in ("headline", "body", "summary"):
                val = record.get(field, "")
                if val:
                    parts.append(val)
            items = record.get("notable_items", [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        parts.append(item.get("title", ""))
                        parts.append(item.get("summary", ""))
            text = "\n".join(p for p in parts if p)
            if text:
                violations = check_output(text)
                if violations:
                    for v in violations:
                        start = max(0, v.match_start - 60)
                        end = min(len(text), v.match_end + 60)
                        context = text[start:end].replace("\n", " ").strip()
                        entry = {
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "agent_id": "digest",
                            "output_path": f"digest-history.jsonl:{count}",
                            "allowed": True,
                            "audit_only": True,
                            "source": "backfill",
                            "violations": [{
                                "pattern_id": v.pattern_id,
                                "tier": v.tier,
                                "matched_text": v.matched_text,
                                "axiom_id": v.axiom_id,
                                "context": context,
                            }],
                        }
                        with AUDIT_LOG.open("a") as f:
                            f.write(json.dumps(entry) + "\n")
                count += 1

    total = 0
    matched = 0
    for path, agent_id in sources:
        entries = _scan_file(path, agent_id)
        if entries:
            matched += 1
            total += len(entries)
            with AUDIT_LOG.open("a") as f:
                for entry in entries:
                    f.write(json.dumps(entry) + "\n")

    print(f"Scanned {len(sources)} files + digest history")
    print(f"  {matched} files with matches, {total} violation entries written")
    print(f"  Audit log: {AUDIT_LOG}")
    print(f"\nNext: run 'label' to classify matches as TP/FP")


# ── Label ────────────────────────────────────────────────────────────────────


def _load_labels() -> dict[str, Label]:
    """Load existing labels keyed by 'pattern_id:matched_text:agent_id'."""
    labels: dict[str, Label] = {}
    if not LABELS_FILE.exists():
        return labels
    for line in LABELS_FILE.read_text().splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            key = f"{data['pattern_id']}:{data['matched_text']}:{data['agent_id']}"
            labels[key] = Label(**data)
        except (json.JSONDecodeError, KeyError):
            continue
    return labels


def _save_label(label: Label) -> None:
    """Append a label to the labels file."""
    LABELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LABELS_FILE.open("a") as f:
        f.write(json.dumps({
            "timestamp": label.timestamp,
            "pattern_id": label.pattern_id,
            "matched_text": label.matched_text,
            "context": label.context,
            "verdict": label.verdict,
            "agent_id": label.agent_id,
            "note": label.note,
        }) + "\n")


def cmd_label() -> None:
    """Interactive labeling of audit entries."""
    if not AUDIT_LOG.exists():
        print("No audit log found. Run 'backfill' first.")
        sys.exit(1)

    existing_labels = _load_labels()

    # Collect unlabeled violations
    unlabeled: list[tuple[dict, dict]] = []  # (entry, violation)
    for line in AUDIT_LOG.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        for v in entry.get("violations", []):
            key = f"{v['pattern_id']}:{v['matched_text']}:{entry['agent_id']}"
            if key not in existing_labels:
                unlabeled.append((entry, v))

    if not unlabeled:
        print("All violations already labeled. Nothing to do.")
        print(f"  {len(existing_labels)} labels in {LABELS_FILE}")
        return

    print(f"{len(unlabeled)} unlabeled violation(s). Label each as:")
    print("  t = true positive (real violation)")
    print("  f = false positive (benign match)")
    print("  s = skip (come back later)")
    print("  q = quit\n")

    labeled = 0
    for i, (entry, v) in enumerate(unlabeled):
        context = v.get("context", v.get("matched_text", ""))
        print(f"─── [{i+1}/{len(unlabeled)}] ─────────────────────────")
        print(f"  Pattern:  {v['pattern_id']} [{v['tier']}]")
        print(f"  Agent:    {entry['agent_id']}")
        print(f"  Source:   {entry['output_path']}")
        print(f"  Match:    \033[1m{v['matched_text']}\033[0m")
        print(f"  Context:  ...{context}...")
        print()

        while True:
            try:
                choice = input("  [t]p / [f]p / [s]kip / [q]uit: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                choice = "q"

            if choice in ("t", "tp"):
                verdict = "tp"
                break
            elif choice in ("f", "fp"):
                verdict = "fp"
                break
            elif choice in ("s", "skip"):
                verdict = None
                break
            elif choice in ("q", "quit"):
                print(f"\nLabeled {labeled} entries this session.")
                return
            else:
                print("  Invalid choice. Use t/f/s/q")

        if verdict is None:
            continue

        note = ""
        if verdict == "fp":
            try:
                note = input("  FP note (why benign? enter to skip): ").strip()
            except (EOFError, KeyboardInterrupt):
                note = ""

        label = Label(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            pattern_id=v["pattern_id"],
            matched_text=v["matched_text"],
            context=context,
            verdict=verdict,
            agent_id=entry["agent_id"],
            note=note,
        )
        _save_label(label)
        existing_labels[f"{v['pattern_id']}:{v['matched_text']}:{entry['agent_id']}"] = label
        labeled += 1
        print()

    print(f"\nLabeled {labeled} entries. Run 'report' for accuracy stats.")


# ── Report ───────────────────────────────────────────────────────────────────


def _compute_stats() -> dict[str, PatternStats]:
    """Compute per-pattern accuracy stats from audit log + labels."""
    # Count total matches per pattern from audit log
    pattern_matches: dict[str, list[tuple[str, str]]] = defaultdict(list)
    if AUDIT_LOG.exists():
        for line in AUDIT_LOG.read_text().splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            for v in entry.get("violations", []):
                pid = v["pattern_id"]
                pattern_matches[pid].append((v["matched_text"], entry["agent_id"]))

    # Load labels
    labels = _load_labels()

    # Compute stats
    stats: dict[str, PatternStats] = {}
    all_pattern_ids = set(pattern_matches.keys())

    # Also include patterns with no matches (zero baseline)
    try:
        from shared.axiom_pattern_checker import load_patterns
        for p in load_patterns():
            all_pattern_ids.add(p.id)
    except Exception:
        pass

    for pid in sorted(all_pattern_ids):
        matches = pattern_matches.get(pid, [])
        tp = 0
        fp = 0
        for matched_text, agent_id in matches:
            key = f"{pid}:{matched_text}:{agent_id}"
            if key in labels:
                if labels[key].verdict == "tp":
                    tp += 1
                elif labels[key].verdict == "fp":
                    fp += 1

        labeled = tp + fp
        stats[pid] = PatternStats(
            pattern_id=pid,
            total=len(matches),
            labeled=labeled,
            tp=tp,
            fp=fp,
            unlabeled=len(matches) - labeled,
        )

    return stats


def cmd_report(*, as_json: bool = False) -> None:
    """Print per-pattern accuracy report + blocking readiness assessment."""
    stats = _compute_stats()

    if as_json:
        result = {
            "patterns": {},
            "readiness": {},
        }
        for pid, s in stats.items():
            result["patterns"][pid] = {
                "total": s.total,
                "labeled": s.labeled,
                "tp": s.tp,
                "fp": s.fp,
                "unlabeled": s.unlabeled,
                "precision": s.precision,
                "fp_rate": s.fp_rate,
                "assessed": s.assessed,
            }

        # Readiness
        t0_patterns = {pid: s for pid, s in stats.items() if pid.startswith("out-") and s.total > 0}
        assessed = [s for s in t0_patterns.values() if s.assessed]
        all_precise = all(
            (s.fp_rate or 0) <= MAX_FP_RATE_FOR_BLOCKING
            for s in assessed
        )
        result["readiness"] = {
            "t0_patterns_with_matches": len(t0_patterns),
            "assessed": len(assessed),
            "unassessed": len(t0_patterns) - len(assessed),
            "all_below_fp_threshold": all_precise,
            "fp_threshold": MAX_FP_RATE_FOR_BLOCKING,
            "min_samples": MIN_SAMPLES_FOR_CONFIDENCE,
            "recommendation": _readiness_recommendation(stats),
        }
        print(json.dumps(result, indent=2))
        return

    # Human-readable report
    print("=" * 72)
    print("OUTPUT ENFORCEMENT PATTERN ACCURACY REPORT")
    print("=" * 72)
    print()

    if not any(s.total > 0 for s in stats.values()):
        print("No matches found in audit log.")
        print("Run 'backfill' to scan historical output, then 'label' to classify.")
        return

    # Per-pattern table
    print(f"{'Pattern':<28} {'Total':>5} {'TP':>4} {'FP':>4} {'?':>4} {'Prec':>7} {'Status':<12}")
    print("-" * 72)

    for pid in sorted(stats.keys()):
        s = stats[pid]
        if s.total == 0:
            continue
        prec_str = f"{s.precision:.0%}" if s.precision is not None else "—"
        if s.assessed:
            status = "PASS" if (s.fp_rate or 0) <= MAX_FP_RATE_FOR_BLOCKING else "HIGH FP"
        else:
            status = f"need {MIN_SAMPLES_FOR_CONFIDENCE - s.labeled} more"
        print(f"{pid:<28} {s.total:>5} {s.tp:>4} {s.fp:>4} {s.unlabeled:>4} {prec_str:>7} {status:<12}")

    print()

    # Summary
    total_matches = sum(s.total for s in stats.values())
    total_labeled = sum(s.labeled for s in stats.values())
    total_tp = sum(s.tp for s in stats.values())
    total_fp = sum(s.fp for s in stats.values())
    print(f"Total: {total_matches} matches, {total_labeled} labeled ({total_tp} TP, {total_fp} FP)")
    if total_labeled > 0:
        print(f"Overall precision: {total_tp/total_labeled:.0%}")
    print()

    # Readiness assessment
    print("─" * 72)
    print("BLOCKING READINESS")
    print("─" * 72)
    recommendation = _readiness_recommendation(stats)
    print(f"\n  {recommendation}\n")


def _readiness_recommendation(stats: dict[str, PatternStats]) -> str:
    """Generate a readiness recommendation for enabling T0 blocking."""
    t0_with_matches = {
        pid: s for pid, s in stats.items()
        if s.total > 0
    }

    if not t0_with_matches:
        return (
            "NOT READY: No pattern matches in audit log. "
            "Run 'backfill' then 'label' to build accuracy data."
        )

    total_labeled = sum(s.labeled for s in t0_with_matches.values())
    if total_labeled == 0:
        return (
            f"NOT READY: {len(t0_with_matches)} pattern(s) have matches but none are labeled. "
            f"Run 'label' to classify {sum(s.total for s in t0_with_matches.values())} matches."
        )

    assessed = [s for s in t0_with_matches.values() if s.assessed]
    unassessed = [s for s in t0_with_matches.values() if not s.assessed and s.total > 0]
    high_fp = [s for s in assessed if (s.fp_rate or 0) > MAX_FP_RATE_FOR_BLOCKING]

    if unassessed:
        need = sum(max(0, MIN_SAMPLES_FOR_CONFIDENCE - s.labeled) for s in unassessed)
        return (
            f"NOT READY: {len(unassessed)} pattern(s) need more labels "
            f"({need} more labels needed across "
            f"{', '.join(s.pattern_id for s in unassessed)}). "
            f"{len(assessed)} pattern(s) assessed so far."
        )

    if high_fp:
        return (
            f"NOT READY: {len(high_fp)} pattern(s) exceed {MAX_FP_RATE_FOR_BLOCKING:.0%} FP rate: "
            f"{', '.join(f'{s.pattern_id} ({s.fp_rate:.0%})' for s in high_fp)}. "
            f"Tune regexes or add exceptions before enabling blocking."
        )

    total_tp = sum(s.tp for s in assessed)
    total_labeled = sum(s.labeled for s in assessed)
    return (
        f"READY: All {len(assessed)} active pattern(s) below {MAX_FP_RATE_FOR_BLOCKING:.0%} FP threshold. "
        f"Overall precision: {total_tp}/{total_labeled} ({total_tp/total_labeled:.0%}). "
        f"Enable blocking with: AXIOM_ENFORCE_BLOCK=1"
    )


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Output enforcement pattern accuracy tooling",
        prog="enforcement_accuracy.py",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("backfill", help="Scan historical output and write matches to audit log")
    sub.add_parser("label", help="Interactively label matches as TP/FP")
    report_parser = sub.add_parser("report", help="Per-pattern accuracy report")
    report_parser.add_argument("--json", action="store_true", help="JSON output")

    args = parser.parse_args()

    if args.command == "backfill":
        cmd_backfill()
    elif args.command == "label":
        cmd_label()
    elif args.command == "report":
        cmd_report(as_json=args.json)


if __name__ == "__main__":
    main()
