#!/bin/bash
# check-legal-name-leaks.sh — operator legal-name leak guard.
#
# Per `interpersonal_transparency` axiom + 2026-04-24 operator-referent
# policy (`docs/superpowers/specs/2026-04-24-operator-referent-policy-design.md`):
# in source code, docs, configuration, and any committed text the
# operator is referred to ONLY by one of the four equally-weighted
# non-formal referents — "The Operator", "Oudepode",
# "Oudepode The Operator", "OTO". The legal name is reserved for
# formal-address-required contexts that live OUTSIDE the public
# source tree.
#
# This script scans staged or specified files for hardcoded operator
# legal-name strings and exits non-zero when any are found in
# disallowed locations.
#
# Allowed locations (whitelist):
#   - .github/CODEOWNERS — github usernames, not legal names
#   - axioms/contracts/  — formal consent contracts
#   - profiles/          — operator profile data
#   - .git/              — git internals (commit author metadata)
#   - This script itself + its tests (must contain the patterns it scans for)
#
# Usage:
#   scripts/check-legal-name-leaks.sh            # scan staged files
#   scripts/check-legal-name-leaks.sh <file>...  # scan named files
#   scripts/check-legal-name-leaks.sh --diff <base>..<head>  # PR-mode

set -euo pipefail

# Patterns we consider legal-name leaks. Case-insensitive match. Add
# variants as discovered; do NOT add the four sanctioned referents
# ("The Operator" / "Oudepode" / "Oudepode The Operator" / "OTO").
#
# Only the legal NAME is gated. The operator's email
# (rylklee@gmail.com) is an operational identifier that legitimately
# appears in mail-monitor specs, integration tests targeting the
# operator's inbox, and similar system-config docs — not a personal-
# identification reference subject to the operator-referent policy.
LEGAL_NAME_PATTERNS=(
    'Ryan[[:space:]]+Kleeberger'
    'Ryan[[:space:]]+Lee[[:space:]]+Kleeberger'
)

# Whitelisted paths — leaks here are not flagged. Match by glob.
# Legal name is allowed in:
#   - axioms/contracts/, profiles/  — formal data the operator-
#     referent policy explicitly carves out
#   - .github/CODEOWNERS            — github usernames, not legal names
#   - .zenodo.json                  — Zenodo creator field requires
#     formal name per V5 publication-bus `requires_legal_name=True`
#   - docs/governance/operator-*    — explicit policy authorship metadata
#   - This script + its tests       — must contain the patterns it scans for
WHITELIST_GLOBS=(
    '.github/CODEOWNERS'
    '.zenodo.json'
    'axioms/contracts/*'
    'docs/governance/operator-*'
    'profiles/*'
    'scripts/check-legal-name-leaks.sh'
    'tests/scripts/test_check_legal_name_leaks.py'
)

is_whitelisted() {
    local path="$1"
    for glob in "${WHITELIST_GLOBS[@]}"; do
        # shellcheck disable=SC2053 — intentional glob match
        case "$path" in
            $glob) return 0 ;;
        esac
    done
    return 1
}

# Resolve file list.
FILES=()
if [ "$#" -eq 0 ]; then
    # Default: staged files. Empty if nothing staged.
    while IFS= read -r f; do
        [ -n "$f" ] && FILES+=("$f")
    done < <(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null || true)
elif [ "$1" = "--diff" ]; then
    shift
    base_head="${1:?--diff needs <base>..<head>}"
    while IFS= read -r f; do
        [ -n "$f" ] && FILES+=("$f")
    done < <(git diff --name-only --diff-filter=ACMR "$base_head" 2>/dev/null || true)
else
    FILES=("$@")
fi

if [ "${#FILES[@]}" -eq 0 ]; then
    echo "check-legal-name-leaks: no files to scan"
    exit 0
fi

LEAKS=0
for f in "${FILES[@]}"; do
    [ -f "$f" ] || continue
    if is_whitelisted "$f"; then
        continue
    fi
    for pat in "${LEGAL_NAME_PATTERNS[@]}"; do
        # -E for ERE, -i case-insensitive, -n line numbers, -H file name.
        # Suppress non-zero exit when no match (set -e propagation).
        if matches="$(grep -EHin "$pat" "$f" 2>/dev/null || true)" && [ -n "$matches" ]; then
            echo "LEGAL-NAME LEAK in $f:" >&2
            echo "$matches" >&2
            echo "" >&2
            LEAKS=$((LEAKS + 1))
        fi
    done
done

if [ "$LEAKS" -gt 0 ]; then
    cat >&2 <<'EOF'

interpersonal_transparency violation: operator legal name appears in
file(s) outside the whitelisted set. Replace with one of the four
sanctioned non-formal referents ("The Operator" / "Oudepode" /
"Oudepode The Operator" / "OTO"), or — if formal address is genuinely
required — restrict to one of the whitelisted locations
(axioms/contracts/, profiles/, .github/CODEOWNERS).

See docs/superpowers/specs/2026-04-24-operator-referent-policy-design.md
EOF
    exit 1
fi

echo "check-legal-name-leaks: ${#FILES[@]} file(s) scanned, no leaks"
exit 0
