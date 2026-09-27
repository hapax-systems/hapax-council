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
# `<GivenName>`. Blank lines and `#` comments are ignored. An entry that is not
# a plain name (letters, apostrophe, hyphen; 2-40 characters) is skipped, never
# compiled as a pattern. Opaque IDs are never emitted as names.
#
# Callers must never print a returned name: report file and line only.

principal_name_map_path() {
    printf '%s\n' "${HAPAX_PRINCIPAL_NAME_MAP:-$HOME/.config/hapax/principal-name-map.yaml}"
}

# Prints each registered given name on its own line. Returns 0 when the map is
# absent (no names) or was read; returns 2 when it exists but cannot be read, so
# the caller fails closed.
principal_names() {
    local map line name
    map="$(principal_name_map_path)"
    [ -e "$map" ] || return 0
    if [ ! -f "$map" ] || [ ! -r "$map" ]; then
        return 2
    fi
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%%#*}"
        name="${line#*:}"
        name="$(printf '%s' "$name" | tr -d '[:space:]"')"
        [[ "$name" =~ ^[A-Za-z][A-Za-z\'-]{1,39}$ ]] || continue
        [[ "$name" =~ ^principal- ]] && continue
        printf '%s\n' "$name"
    done < "$map"
}
