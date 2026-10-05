#!/usr/bin/env bash
# write-stamp-ahead-guard.sh -- PreToolUse hook (Write).
#
# Refuses a Write under the Personal vault whose filename stamp or frontmatter
# `created_at` is more than 15 s ahead of the clock, and prints the current
# `date -u`. All semantics live in write_stamp_ahead_guard.py (unit-tested in
# tests/hooks/test_write_stamp_ahead_guard.py); this shim only picks the
# interpreter and fails open when there is none.
#
# Row: write-stamp-ahead-of-clock-hook-20261004 (dispatch terms 2026-10-04T23:24:46Z).
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "write-stamp-ahead-guard: python3 unavailable; failing open (no refusal)." >&2
  exit 0
fi

exec python3 "$(dirname "${BASH_SOURCE[0]}")/write_stamp_ahead_guard.py"
