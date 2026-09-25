#!/usr/bin/env bash
# check-claude-md-rot — scan AGENTS.md and CLAUDE.md for content that decays into noise.
#
# Operationalizes the rotation policy from
# docs/superpowers/specs/2026-04-13-claude-md-excellence-design.md.
#
# Forbidden patterns (matched outside pointer contexts):
#   - "fixed YYYY-MM-DD"               (commit-message content)
#   - "(PR #NNN)" / "(<role> PR #NNN)" (PR fingerprints)
#   - "currently (non-functional|broken|disabled)"
#   - "(not yet|TODO|FIXME|XXX)"       (in-flight admissions)
#   - "migration pending" / "temporary workaround"
#
# Usage:
#   scripts/check-claude-md-rot.sh                 # discover both instruction names under cwd
#   scripts/check-claude-md-rot.sh path/to/file …  # scan explicit file(s)
#   scripts/check-claude-md-rot.sh --quiet …       # exit code only, no output on success
#   scripts/check-claude-md-rot.sh --strict …      # also fail on TODO/FIXME/XXX patterns
#
# Exits non-zero on any match. Auto-discovery skips .git/, node_modules/, .venv/, target/.

set -euo pipefail

quiet=0
strict=0
explicit_targets=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --quiet) quiet=1; shift ;;
        --strict) strict=1; shift ;;
        --help|-h)
            sed -n '2,20p' "$0"
            exit 0
            ;;
        --) shift; explicit_targets+=("$@"); break ;;
        -*) echo "unknown flag: $1" >&2; exit 2 ;;
        *)  explicit_targets+=("$1"); shift ;;
    esac
done

if [[ ${#explicit_targets[@]} -gt 0 ]]; then
    targets=("${explicit_targets[@]}")
    # Validate explicit targets exist — typo guard.
    missing=()
    for t in "${targets[@]}"; do
        [[ -f "$t" ]] || missing+=("$t")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        printf 'check-claude-md-rot: missing target(s):\n' >&2
        printf '  %s\n' "${missing[@]}" >&2
        exit 2
    fi
else
    # Auto-discover. find -prune to skip vendored/build dirs.
    mapfile -t targets < <(
        find . \
            \( -path './.git' -o -path './node_modules' -o -path './.venv' -o -path './target' -o -path './build' \) -prune \
            -o \( -name AGENTS.md -o -name CLAUDE.md -o -path "*/config/agent-instructions/native/*.md" -o -path "*/docs/runbooks/council-domain-context.md" \) -type f -print \
            | sort
    )
fi

if [[ ${#targets[@]} -eq 0 ]]; then
    [[ $quiet -eq 0 ]] && echo "check-claude-md-rot: no AGENTS.md or CLAUDE.md files found" >&2
    exit 0
fi

found=0
report() {
    local file=$1 pattern=$2 label=$3
    local matches
    if matches=$(grep -nIE "$pattern" "$file" 2>/dev/null); then
        if [[ $quiet -eq 0 ]]; then
            while IFS= read -r line; do
                printf '%s: [%s] %s\n' "$file" "$label" "$line"
            done <<<"$matches"
        fi
        found=1
    fi
}

for target in "${targets[@]}"; do
    report "$target" 'fixed 20[0-9]{2}-[0-9]{2}-[0-9]{2}' fix-date
    report "$target" '\((alpha |beta |delta |gamma )?PR #[0-9]+' pr-fingerprint
    report "$target" 'currently (non-functional|broken|disabled)' broken-claim
    report "$target" '(not yet (captured|implemented|wired|landed)|migration pending|temporary workaround)' in-flight
    if [[ $strict -eq 1 ]]; then
        report "$target" '(^|[^[:alnum:]])(TODO|FIXME|XXX)([^[:alnum:]]|$)' todo-marker
    fi
done

if [[ $found -ne 0 ]]; then
    if [[ $quiet -eq 0 ]]; then
        echo
        echo "Agent instruction rotation policy violations found." >&2
        echo "See docs/superpowers/specs/2026-04-13-claude-md-excellence-design.md" >&2
    fi
    exit 1
fi

if [[ $quiet -eq 0 ]]; then
    printf 'check-claude-md-rot: %d file(s) scanned, no rot found.\n' "${#targets[@]}"
fi
