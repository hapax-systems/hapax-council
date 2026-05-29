"""Tests for the methodology gate-loosening ledger surfacing (FR-EMERGENCY-BYPASS-UNSURFACED).

Two surfaces share one jq summary:
  - hooks/scripts/methodology-ledger-digest.sh — the reusable digest tool that
    powers the daily ntfy digest, the CI PR check (--exit-code), and the review-SLA
    escalation (--sla).
  - hooks/scripts/session-context.sh — the inline SessionStart digest block.

Both are read-only/advisory. The digest script is exercised directly; the
session-context block is exercised via fragment extraction (the established
pattern in test_session_context_advisories.py — the full hook is slow + non-hermetic).
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
DIGEST = REPO_ROOT / "hooks" / "scripts" / "methodology-ledger-digest.sh"
SESSION_CONTEXT = REPO_ROOT / "hooks" / "scripts" / "session-context.sh"


def _iso(hours_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_ledger(tmp_path: Path, entries: list[dict]) -> Path:
    ledger = tmp_path / "methodology-emergency-ledger.jsonl"
    ledger.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return ledger


def _run_digest(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(DIGEST), *args],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=15,
    )


# ── digest script ────────────────────────────────────────────────────────


class TestDigestScript:
    def test_missing_ledger_is_quiet(self, tmp_path: Path) -> None:
        result = _run_digest("--ledger", str(tmp_path / "nope.jsonl"))
        assert result.returncode == 0
        assert "empty" in result.stdout.lower()

    def test_recent_inferences_summarized_without_bypass_warning(self, tmp_path: Path) -> None:
        ledger = _write_ledger(
            tmp_path,
            [
                {"ts": _iso(1), "kind": "cognition_allow"},
                {"ts": _iso(2), "kind": "cognition_allow"},
                {"ts": _iso(3), "kind": "stage_derived"},
                {"ts": _iso(4), "kind": "route_schema_defaulted"},
                {"ts": _iso(100), "kind": "cognition_allow"},  # outside 24h window
            ],
        )
        result = _run_digest("--ledger", str(ledger), "--since", "24")
        assert result.returncode == 0
        assert "4 loosening(s)" in result.stdout
        assert "cognition_allow×2" in result.stdout
        assert "REVIEW" not in result.stdout  # no bypasses → nothing to review

    def test_emergency_bypass_flagged_for_review(self, tmp_path: Path) -> None:
        # An entry with no "kind" defaults to emergency_bypass.
        ledger = _write_ledger(
            tmp_path,
            [
                {"ts": _iso(2), "role": "alpha", "task": "t", "case": "C", "tool": "Bash"},
                {"ts": _iso(3), "kind": "cognition_allow"},
            ],
        )
        result = _run_digest("--ledger", str(ledger), "--since", "24")
        assert result.returncode == 0
        assert "REVIEW" in result.stdout
        assert "1 emergency bypass" in result.stdout

    def test_overdue_bypass_flagged(self, tmp_path: Path) -> None:
        ledger = _write_ledger(
            tmp_path,
            [{"ts": _iso(40), "kind": "emergency_bypass"}],
        )
        result = _run_digest("--ledger", str(ledger), "--since", "168", "--sla", "24")
        assert "OVERDUE" in result.stdout

    def test_json_output_shape(self, tmp_path: Path) -> None:
        ledger = _write_ledger(
            tmp_path,
            [
                {"ts": _iso(1), "kind": "emergency_bypass"},
                {"ts": _iso(2), "kind": "cognition_allow"},
            ],
        )
        result = _run_digest("--ledger", str(ledger), "--json")
        payload = json.loads(result.stdout)
        assert payload["total"] == 2
        assert payload["bypasses"] == 1
        assert payload["by_kind"]["cognition_allow"] == 1

    def test_exit_code_nonzero_on_bypass(self, tmp_path: Path) -> None:
        ledger = _write_ledger(tmp_path, [{"ts": _iso(1), "kind": "emergency_bypass"}])
        result = _run_digest("--ledger", str(ledger), "--exit-code")
        assert result.returncode == 2

    def test_exit_code_zero_without_bypass(self, tmp_path: Path) -> None:
        ledger = _write_ledger(tmp_path, [{"ts": _iso(1), "kind": "cognition_allow"}])
        result = _run_digest("--ledger", str(ledger), "--exit-code")
        assert result.returncode == 0


# ── session-context.sh inline surfacing (fragment extraction) ──────────────

# The exact METHODOLOGY_LEDGER block from session-context.sh, parameterized only
# by the ledger path. Kept in sync with the hook; the digest script above is the
# canonical logic.
_FRAGMENT = r"""
METHODOLOGY_LEDGER="__LEDGER__"
if [ -f "$METHODOLOGY_LEDGER" ] && command -v jq >/dev/null 2>&1; then
  LEDGER_DIGEST="$(jq -rs '
    (now - 86400) as $cutoff
    | [ .[]
        | {kind: (.kind // "emergency_bypass"),
           t: (try (.ts | fromdateiso8601) catch 0)}
        | select(.t >= $cutoff) ] as $recent
    | if ($recent | length) == 0 then empty
      else
        ($recent | map(select(.kind | test("bypass")))) as $byp
        | (($recent | group_by(.kind)
            | map("\(.[0].kind)×\(length)")) | join(", ")) as $by_kind
        | ($recent | map(.t) | min) as $oldest
        | ((now - $oldest) / 3600 | floor) as $age_h
        | "METHODOLOGY LEDGER (24h): \($recent | length) loosening(s) — \($by_kind)"
          + (if ($byp | length) > 0
             then "\n  ⚠ \($byp | length) emergency bypass(es) — REVIEW (oldest \($age_h)h ago)"
                  + (if $age_h > 24 then " — OVERDUE (review SLA 24h)" else "" end)
             else "" end)
      end
  ' "$METHODOLOGY_LEDGER" 2>/dev/null || true)"
  if [ -n "$LEDGER_DIGEST" ]; then
    echo ""
    printf '%s\n' "$LEDGER_DIGEST"
  fi
fi
"""


def _run_fragment(tmp_path: Path, ledger: Path) -> subprocess.CompletedProcess:
    script = tmp_path / "frag.sh"
    script.write_text("#!/bin/bash\nset -u\n" + _FRAGMENT.replace("__LEDGER__", str(ledger)))
    return subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=15,
    )


class TestSessionContextSurfacing:
    def test_emits_digest_for_recent_entries(self, tmp_path: Path) -> None:
        ledger = _write_ledger(
            tmp_path,
            [
                {"ts": _iso(1), "kind": "emergency_bypass"},
                {"ts": _iso(2), "kind": "cognition_allow"},
            ],
        )
        result = _run_fragment(tmp_path, ledger)
        assert result.returncode == 0
        assert "METHODOLOGY LEDGER (24h)" in result.stdout
        assert "REVIEW" in result.stdout

    def test_silent_when_no_recent_entries(self, tmp_path: Path) -> None:
        ledger = _write_ledger(tmp_path, [{"ts": _iso(100), "kind": "cognition_allow"}])
        result = _run_fragment(tmp_path, ledger)
        assert result.returncode == 0
        assert "METHODOLOGY LEDGER" not in result.stdout

    def test_silent_when_ledger_missing(self, tmp_path: Path) -> None:
        result = _run_fragment(tmp_path, tmp_path / "absent.jsonl")
        assert result.returncode == 0
        assert result.stdout.strip() == ""
