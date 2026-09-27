#!/usr/bin/env bash
# principal-name-map.sh — sourced by hooks/scripts/pii-guard.sh and
# scripts/check-legal-name-leaks.sh. Never executed on its own.
#
# Registered principals' given names live ONLY in a gitignored local registry
# outside version control. A public guard cannot list them without publishing
# them. The default path is ~/.config/hapax/principal-name-map.yaml; the
# HAPAX_PRINCIPAL_NAME_MAP environment variable overrides it. Provisioning the
# file is an operator act on the host. When it is absent (CI, fresh hosts), the
# guards fall back to the family surname alone.
#
# Format: one entry per line, `principal-<id>: <GivenName>` or a bare
# `<GivenName>`. Blank lines and `#` comments are ignored. Every other line must
# be a valid entry: a single given-name token of 2-40 ASCII letters, apostrophes
# or hyphens (list each token of a multi-part name on its own line). An invalid
# line fails the read closed. Silently skipping it would drop that person from
# both guards. The error names the line number, never its value. Opaque IDs are
# never emitted as names, and names are matched as fixed strings, never compiled
# as patterns.
#
# Callers must never print a returned name: report file and line only.

principal_name_map_path() {
    printf '%s\n' "${HAPAX_PRINCIPAL_NAME_MAP:-$HOME/.config/hapax/principal-name-map.yaml}"
}

# Prints each registered given name on its own line. Returns 0 when the map is
# absent (no names) or fully valid; returns 2 (after a stderr next action that
# names the path and line number, never a value) when it exists but cannot be
# read or holds an invalid line, so the caller fails closed.
principal_names() {
    local map line name lineno=0 names=()
    map="$(principal_name_map_path)"
    [ -e "$map" ] || return 0
    if [ ! -f "$map" ] || [ ! -r "$map" ]; then
        echo "principal-name-map: $map exists but is not a readable file; fix its permissions or remove it." >&2
        return 2
    fi
    while IFS= read -r line || [ -n "$line" ]; do
        lineno=$((lineno + 1))
        line="${line%%#*}"
        [[ "$line" =~ ^[[:space:]]*$ ]] && continue
        if [[ "$line" =~ ^[[:space:]]*principal-[a-z][0-9]+[[:space:]]*:[[:space:]]*(.*)$ ]]; then
            name="${BASH_REMATCH[1]}"
        else
            name="$line"
        fi
        name="${name#"${name%%[![:space:]]*}"}"
        name="${name%"${name##*[![:space:]]}"}"
        name="${name#\"}"
        name="${name%\"}"
        if [[ ! "$name" =~ ^[A-Za-z][A-Za-z\'-]{1,39}$ ]] || [[ "$name" =~ ^principal- ]]; then
            echo "principal-name-map: line $lineno of $map is not a valid entry; write one given-name token (2-40 ASCII letters, apostrophes or hyphens) per line as 'principal-<id>: <Name>' or '<Name>', or remove the line." >&2
            return 2
        fi
        names+=("$name")
    done < "$map"
    [ "${#names[@]}" -eq 0 ] || printf '%s\n' "${names[@]}"
}
