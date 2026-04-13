#!/usr/bin/env bash
# Smoke tests for scripts/check-vscode-sister-extensions.sh.
#
# Run from the council repo root:  bash tests/test_check_vscode_sister_extensions.sh
#
# Tests cover:
#   1. Identical files → exit 0
#   2. Port-only diff (8050 vs 8051) → exit 0
#   3. Repo-name diff (hapax-council vs hapax-officium) → exit 0
#   4. Combined allowed-axis diff → exit 0
#   5. Unrelated drift → exit 1
#   6. Missing file → exit 2

set -uo pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/scripts/check-vscode-sister-extensions.sh"
[[ -x "$SCRIPT" ]] || { echo "FAIL: script not executable: $SCRIPT"; exit 1; }

passes=0
fails=0
tmproot=$(mktemp -d)
trap 'rm -rf "$tmproot"' EXIT

assert() {
    local name=$1 expected=$2 actual=$3
    if [[ "$expected" == "$actual" ]]; then
        printf 'PASS: %s\n' "$name"
        passes=$((passes + 1))
    else
        printf 'FAIL: %s — expected %s, got %s\n' "$name" "$expected" "$actual"
        fails=$((fails + 1))
    fi
}

run() {
    "$SCRIPT" "$1" "$2" >/dev/null 2>&1
    echo $?
}

# Helper: write a minimal vscode-style CLAUDE.md fixture.
make_fixture() {
    local file=$1 port=$2 repo=$3
    cat > "$file" <<EOF
# CLAUDE.md

VS Code extension for the Hapax system. Targets ${repo} Logos API on port ${port}.
EOF
}

# --- fixture 1: identical files ---
a=$(mktemp -p "$tmproot" CLAUDE.md.a.XXXXXX)
b=$(mktemp -p "$tmproot" CLAUDE.md.b.XXXXXX)
make_fixture "$a" 8051 hapax-council
cp "$a" "$b"
assert "identical files exit 0" 0 "$(run "$a" "$b")"

# --- fixture 2: port-only diff ---
a=$(mktemp -p "$tmproot" CLAUDE.md.a.XXXXXX)
b=$(mktemp -p "$tmproot" CLAUDE.md.b.XXXXXX)
make_fixture "$a" 8051 hapax-council
make_fixture "$b" 8050 hapax-council
assert "port-only diff exits 0" 0 "$(run "$a" "$b")"

# --- fixture 3: repo-name diff (hapax-council vs hapax-officium) ---
a=$(mktemp -p "$tmproot" CLAUDE.md.a.XXXXXX)
b=$(mktemp -p "$tmproot" CLAUDE.md.b.XXXXXX)
make_fixture "$a" 8051 hapax-council
make_fixture "$b" 8051 hapax-officium
assert "repo-name diff exits 0" 0 "$(run "$a" "$b")"

# --- fixture 4: combined allowed-axis diff (port AND repo name) ---
a=$(mktemp -p "$tmproot" CLAUDE.md.a.XXXXXX)
b=$(mktemp -p "$tmproot" CLAUDE.md.b.XXXXXX)
make_fixture "$a" 8051 hapax-council
make_fixture "$b" 8050 hapax-officium
assert "combined allowed diff exits 0" 0 "$(run "$a" "$b")"

# --- fixture 5: unrelated drift — flagged ---
a=$(mktemp -p "$tmproot" CLAUDE.md.a.XXXXXX)
b=$(mktemp -p "$tmproot" CLAUDE.md.b.XXXXXX)
cat > "$a" <<'EOF'
# CLAUDE.md

VS Code extension for the Hapax system. Targets council Logos API on port 8051.

## Sister surface
hapax-mcp exposes the same Logos API to Claude Code via MCP tools.
EOF
cat > "$b" <<'EOF'
# CLAUDE.md

VS Code extension for the Hapax system. Targets officium Logos API on port 8050.
EOF
assert "unrelated drift exits 1" 1 "$(run "$a" "$b")"

# --- fixture 6: missing target file ---
assert "missing file exits 2" 2 "$(run "$tmproot/no-such" "$tmproot/file")"

# --- summary ---
echo
printf 'tests: %d passed, %d failed\n' "$passes" "$fails"
[[ $fails -eq 0 ]]
