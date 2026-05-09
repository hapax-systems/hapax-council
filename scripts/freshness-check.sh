#!/usr/bin/env bash
# Unified freshness check — detects staleness across ALL vectors.
# Run by: rebuild timer, service startup, manual, smoke test.
# Exit code: 0 = fresh, 1 = stale (with details on stdout).
#
# This script is the SINGLE answer to "are my changes in the running system?"
set -uo pipefail

STALE=0
WARNINGS=()

warn() { WARNINGS+=("$1"); printf "  STALE: %s\n" "$1"; ((STALE++)); }
ok()   { printf "  fresh: %s\n" "$1"; }

REPO="${HAPAX_COUNCIL_DIR:-$HOME/projects/hapax-council}"
HEAD=$(git -C "$REPO" rev-parse --short=9 HEAD 2>/dev/null || echo "unknown")

echo "=== Freshness Check (HEAD: $HEAD) ==="

# 1. Binary provenance
echo "[Binary]"
IMAG_BIN="$HOME/.local/bin/hapax-imagination"
if [[ -f "$IMAG_BIN" ]]; then
    bin_sha=$(strings "$IMAG_BIN" 2>/dev/null | grep -oP 'VERGEN_GIT_SHA.\K[a-f0-9]{9}' | head -1)
    if [[ -z "$bin_sha" ]]; then
        bin_age=$(( $(date +%s) - $(stat -c %Y "$IMAG_BIN") ))
        if [[ "$bin_age" -gt 3600 ]]; then
            warn "imagination binary >1h old (${bin_age}s), SHA unextractable"
        else
            ok "imagination binary ${bin_age}s old (SHA unextractable)"
        fi
    elif [[ "$bin_sha" == "${HEAD:0:9}" ]]; then
        ok "imagination binary matches HEAD ($bin_sha)"
    else
        warn "imagination binary ($bin_sha) != HEAD ($HEAD)"
    fi
else
    warn "imagination binary not installed"
fi

# 2. Service running state matches binary
echo "[Services]"
for svc in hapax-imagination logos-api; do
    if systemctl --user is-active "$svc" &>/dev/null; then
        # Check if the binary backing this service is newer than the service start
        svc_start=$(systemctl --user show "$svc" --property=ActiveEnterTimestamp --value 2>/dev/null)
        if [[ -n "$svc_start" ]]; then
            svc_epoch=$(date -d "$svc_start" +%s 2>/dev/null || echo 0)
            case "$svc" in
                hapax-imagination) bin_path="$IMAG_BIN" ;;
                logos-api) bin_path="" ;; # Python, check code dir
            esac
            if [[ -n "$bin_path" && -f "$bin_path" ]]; then
                bin_epoch=$(stat -c %Y "$bin_path")
                if [[ "$bin_epoch" -gt "$svc_epoch" ]]; then
                    warn "$svc running older binary (binary newer by $((bin_epoch - svc_epoch))s)"
                else
                    ok "$svc running current binary"
                fi
            else
                ok "$svc active"
            fi
        fi
    else
        ok "$svc not running (will use latest on next start)"
    fi
done

# 3. Systemd unit drift
echo "[Units]"
for unit in hapax-imagination.service; do
    repo_file=""
    if [[ -f "$REPO/systemd/units/$unit" ]]; then
        repo_file="$REPO/systemd/units/$unit"
    elif [[ -f "$REPO/systemd/$unit" ]]; then
        repo_file="$REPO/systemd/$unit"
    fi
    deployed="$HOME/.config/systemd/user/$unit"
    if [[ -n "$repo_file" && -f "$deployed" ]]; then
        if ! diff -q "$repo_file" "$deployed" &>/dev/null; then
            warn "$unit deployed differs from repo"
        else
            ok "$unit deployed matches repo"
        fi
    fi
done

# Decommissioned Tauri/WebKit units (hapax-logos.service, hapax-build-reload.path,
# logos-dev.service) are validated by scripts/smoke-test.sh and verified
# masked/absent by systemd/scripts/install-units.sh DECOMMISSIONED_UNITS.

# 4. Shader freshness
echo "[Shaders]"
if [[ -d /dev/shm/hapax-imagination/pipeline ]]; then
    stale_shaders=0
    for wgsl in /dev/shm/hapax-imagination/pipeline/*.wgsl; do
        [[ -f "$wgsl" ]] || continue
        name=$(basename "$wgsl")
        src="$REPO/agents/shaders/nodes/$name"
        if [[ -f "$src" ]]; then
            if ! diff -q "$src" "$wgsl" &>/dev/null; then
                ((stale_shaders++))
            fi
        fi
    done
    if [[ "$stale_shaders" -gt 0 ]]; then
        warn "$stale_shaders deployed shader(s) differ from source"
    else
        ok "all deployed shaders match source"
    fi
fi

# 5. Git state
echo "[Git]"
ahead=$(git -C "$REPO" rev-list origin/main..HEAD --count 2>/dev/null || echo "?")
if [[ "$ahead" == "0" ]]; then
    ok "HEAD matches origin/main"
elif [[ "$ahead" != "?" ]]; then
    warn "HEAD is $ahead commit(s) ahead of origin/main (unpushed work)"
fi

dirty=$(git -C "$REPO" status --porcelain 2>/dev/null | head -5 | wc -l)
if [[ "$dirty" -gt 0 ]]; then
    warn "working tree has $dirty uncommitted change(s)"
fi

# Summary
echo ""
if [[ "$STALE" -eq 0 ]]; then
    echo "ALL FRESH ($HEAD)"
    exit 0
else
    echo "$STALE STALE ITEM(S):"
    for w in "${WARNINGS[@]}"; do
        echo "  - $w"
    done
    exit 1
fi
