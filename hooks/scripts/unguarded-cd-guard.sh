#!/usr/bin/env bash
# unguarded-cd-guard.sh — block Bash commands where a bare `cd` failure would
# let subsequent commands run in the WRONG DIRECTORY.
#
# v2: thin wrapper. All semantics live in unguarded_cd_guard.py (a real
# quote/heredoc/subshell-aware analyzer with positional set-e tracking and
# and-or-list failure simulation), unit-tested in
# tests/test_unguarded_cd_guard.py. The v1 regex approach was verified
# fail-open on quoted cd targets — the exact incident shape it existed to
# block — by the PR #4091 review team.
#
# Contract, wiring and the documented fail-open-on-payload choice: see the
# analyzer's module docstring.
set -euo pipefail
exec python3 "$(dirname "${BASH_SOURCE[0]}")/unguarded_cd_guard.py"
