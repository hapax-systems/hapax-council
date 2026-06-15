#!/usr/bin/env bash
# Test for scripts/hapax-aider-lane — exercises arg validation, the local-only
# endpoint guard, and command construction. No live model / uv / aider needed
# (uses HAPAX_AIDER_LANE_DRY_RUN). This is the re-runnable evidence for the
# cheap/local-model SDLC lane wrapper.
set -uo pipefail

LANE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../scripts" && pwd)/hapax-aider-lane"
fail=0
ok() { echo "ok: $1"; }
bad() {
  echo "FAIL: $1"
  fail=1
}
check_exit() { # desc want_exit got_exit
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (want exit $2, got $3)"; fi
}

# 1-2. required-arg failure paths
HAPAX_AIDER_LANE_DRY_RUN=1 "$LANE" >/dev/null 2>&1
check_exit "missing model exits 2" 2 $?
HAPAX_AIDER_LANE_DRY_RUN=1 "$LANE" some-model >/dev/null 2>&1
check_exit "missing message exits 2" 2 $?

# 3. local-only guard: a paid/non-local endpoint must fail closed
HAPAX_AIDER_LANE_DRY_RUN=1 HAPAX_TABBY_URL="https://api.openai.com/v1" \
  "$LANE" m "do x" >/dev/null 2>&1
check_exit "non-local endpoint refused (exit 3)" 3 $?

# 3b. adversarial bypasses must also fail closed (userinfo smuggling, host-suffix,
# path-only) — the effective host, not a prefix, must be local.
for bad in \
  "http://127.0.0.1:5000@api.openai.com/v1" \
  "http://127.0.0.1.evil.com/v1" \
  "http://evil.com/127.0.0.1"; do
  HAPAX_AIDER_LANE_DRY_RUN=1 HAPAX_TABBY_URL="$bad" "$LANE" m "do x" >/dev/null 2>&1
  check_exit "guard rejects bypass ($bad)" 3 $?
done

# 3c. legitimate local endpoints are accepted (dry-run reaches command construction)
for good in "http://localhost:5000/v1" "http://192.168.68.50:5000/v1"; do
  HAPAX_AIDER_LANE_DRY_RUN=1 HAPAX_TABBY_URL="$good" "$LANE" m "do x" >/dev/null 2>&1
  check_exit "guard accepts local ($good)" 0 $?
done

# 4. command construction (dry-run)
out="$(HAPAX_AIDER_LANE_DRY_RUN=1 "$LANE" command-r-x "fix the lint" foo.py bar.py 2>/dev/null)"
has() { # desc pattern
  if printf '%s' "$out" | grep -q -- "$2"; then ok "$1"; else bad "$1"; fi
}
has "model wired" "--model openai/command-r-x"
has "first file arg expanded" "--file foo.py"
has "second file arg expanded" "--file bar.py"
has "message wired" "--message"
has "defaults to local base" "OPENAI_API_BASE=http://127.0.0.1:5000/v1"
has "audioop-lts shim present" "audioop-lts"
has "no-auto-commit (diff stays unstaged)" "--no-auto-commit"

if [ "$fail" -eq 0 ]; then
  echo "ALL PASS"
else
  echo "FAILURES"
  exit 1
fi
