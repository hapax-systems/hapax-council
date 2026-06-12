#!/usr/bin/env bash
# hapax-backup-lib.sh — per-component witness receipts + honest exit derivation.
#
# Class-closure mechanism for audit-w0-backup-integrity-20260611 (CASE-AUDIT-W0-HAZARD,
# CLASS-CLOSURE preference (a): impossible-by-construction):
#
#   A backup run CANNOT exit green unless (1) every component recorded an
#   "ok" witness AND (2) the script reached receipt_complete. The exit
#   status is derived from the witness record inside the EXIT trap — there
#   is no code path to a green exit with a failed or missing witness.
#
# Usage (sourced by scripts/hapax-backup-{local,remote}.sh):
#   receipt_init <tier>                      # arm the EXIT trap, open the record
#   component <name> <cmd...>                # soft: witness + continue (run still ends red on fail)
#   component_required <name> <cmd...>       # hard: witness + abort run on fail
#   record_component <name> <ok|fail> <detail> [seconds]
#   receipt_precommit <dest-file>            # write receipt-so-far (goes inside the snapshot)
#   receipt_complete                         # mark the run fully witnessed (last line of script)
#   backup_n8n_export <dump_dir>             # n8n component (empty store != broken export)
#   backup_dr_script_upload <src> <dest>     # DR script component (missing source = fail)
#
# Receipt: $HAPAX_BACKUP_RECEIPT_DIR/<tier>-latest.json (consumed by
# scripts/hapax-backup-watchdog check_backup_receipt). Only -latest is kept;
# run history lives in the journal (SyslogIdentifier=hapax-backup-*).

HAPAX_BACKUP_RECEIPT_DIR="${HAPAX_BACKUP_RECEIPT_DIR:-$HOME/.local/state/hapax/backup-receipts}"

if ! declare -F log >/dev/null; then
    log() { echo "[$(date -Iseconds)] $1"; }
fi

receipt_init() {
    HAPAX_RECEIPT_TIER="$1"
    HAPAX_RECEIPT_STARTED="$(date -Iseconds)"
    HAPAX_RECEIPT_COMPLETE=0
    HAPAX_RECEIPT_RECORD="$(mktemp /tmp/hapax-backup-receipt-XXXXXX.ndjson)"
    HAPAX_RECEIPT_PATH="$HAPAX_BACKUP_RECEIPT_DIR/${HAPAX_RECEIPT_TIER}-latest.json"
    mkdir -p "$HAPAX_BACKUP_RECEIPT_DIR"
    trap '_receipt_on_exit' EXIT
}

record_component() {
    local name="$1" status="$2" detail="$3" seconds="${4:-0}"
    jq -cn --arg n "$name" --arg s "$status" --arg d "$detail" --argjson sec "$seconds" \
        '{name: $n, status: $s, detail: $d, seconds: $sec}' >> "$HAPAX_RECEIPT_RECORD"
    if [[ "$status" == "fail" ]]; then
        log "FAIL component=$name: $detail"
    else
        log "OK component=$name: $detail"
    fi
}

# Run a command as a witnessed component. Output streams through to the
# journal AND is captured so failure detail lands in the receipt.
_component_run() {
    local name="$1"; shift
    local t0=$SECONDS rc=0 outf
    outf="$(mktemp /tmp/hapax-backup-comp-XXXXXX.log)"
    "$@" > >(tee "$outf") 2>&1 || rc=$?
    wait $! 2>/dev/null || true  # let tee flush
    local detail
    detail="$(tail -c 300 "$outf" | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g')"
    rm -f "$outf"
    if (( rc == 0 )); then
        record_component "$name" ok "${detail:-rc=0}" $((SECONDS - t0))
    else
        record_component "$name" fail "rc=$rc: ${detail:-no output}" $((SECONDS - t0))
    fi
    return "$rc"
}

component() {
    local name="$1"; shift
    _component_run "$name" "$@" || true
}

component_required() {
    local name="$1"; shift
    if ! _component_run "$name" "$@"; then
        log "required component $name failed — aborting run"
        exit 1
    fi
}

_receipt_json() {
    local complete_flag="$1" exit_code="$2"
    local aborted=true
    [[ "$complete_flag" == "1" ]] && aborted=false
    jq -n \
        --arg tier "$HAPAX_RECEIPT_TIER" \
        --arg host "$(hostname)" \
        --arg started "$HAPAX_RECEIPT_STARTED" \
        --arg finished "$(date -Iseconds)" \
        --argjson aborted "$aborted" \
        --argjson exit_code "$exit_code" \
        --slurpfile components "$HAPAX_RECEIPT_RECORD" \
        '{schema: 1, tier: $tier, host: $host, started_at: $started,
          finished_at: $finished, components: $components,
          failures: ([$components[] | select(.status == "fail")] | length),
          aborted: $aborted, exit_code: $exit_code}'
}

receipt_precommit() {
    local dest="$1"
    _receipt_json "$HAPAX_RECEIPT_COMPLETE" 0 \
        | jq '. + {precommit: true} | del(.exit_code)' > "$dest"
}

receipt_complete() {
    HAPAX_RECEIPT_COMPLETE=1
}

_receipt_on_exit() {
    local rc=$?
    trap - EXIT
    local failures
    failures="$(jq -s '[.[] | select(.status == "fail")] | length' "$HAPAX_RECEIPT_RECORD" 2>/dev/null || echo 0)"
    local final=$rc
    if (( rc == 0 )) && { (( failures > 0 )) || (( HAPAX_RECEIPT_COMPLETE != 1 )); }; then
        final=1
    fi
    _receipt_json "$HAPAX_RECEIPT_COMPLETE" "$final" > "$HAPAX_RECEIPT_PATH" \
        || log "receipt write failed at $HAPAX_RECEIPT_PATH"
    rm -f "$HAPAX_RECEIPT_RECORD"
    if [[ -n "${HAPAX_BACKUP_CLEANUP_DIR:-}" ]]; then
        rm -rf "$HAPAX_BACKUP_CLEANUP_DIR"
    fi
    log "receipt: tier=$HAPAX_RECEIPT_TIER failures=$failures exit=$final → $HAPAX_RECEIPT_PATH"
    exit "$final"
}

# ─── n8n export component ────────────────────────────────────────────────────
# Root cause 2026-06-11: n8n v2 `export:workflow --all` exits 1 on an EMPTY
# store ("No workflows found with specified filters") — an empty store is
# healthy, a broken CLI/DB is not. Distinguish them via list:workflow, and
# always leave the artifact in the backup set so its presence is checkable.
backup_n8n_export() {
    local dump_dir="$1"
    local artifact="$dump_dir/n8n-workflows.json"
    local list_out
    if ! list_out="$(docker exec n8n n8n list:workflow 2>&1)"; then
        record_component n8n_export fail \
            "list:workflow failed (cannot tell empty from broken): $(tail -c 200 <<<"$list_out" | tr '\n' ' ')"
        return 0
    fi
    local count
    count="$(grep -cE '^[A-Za-z0-9-]+\|' <<<"$list_out" || true)"
    if (( count == 0 )); then
        printf '[]\n' > "$artifact"
        record_component n8n_export ok "0 workflows (empty export artifact written)"
        return 0
    fi
    local out
    if out="$(docker exec n8n n8n export:workflow --all --output=/tmp/n8n-workflows.json 2>&1)" \
        && docker cp n8n:/tmp/n8n-workflows.json "$artifact" >/dev/null 2>&1 \
        && jq -e 'type == "array"' "$artifact" >/dev/null 2>&1; then
        record_component n8n_export ok "$(jq length "$artifact") workflows exported ($count listed)"
    else
        record_component n8n_export fail \
            "export failed ($count workflows listed): $(tail -c 200 <<<"$out" | tr '\n' ' ')"
    fi
}

# ─── DR script upload component ──────────────────────────────────────────────
# Root cause 2026-06-11: source path never existed on this host (script
# predated the machine generation); rclone WARNed and the run stayed green.
# A missing DR script is a backup failure, not a footnote.
backup_dr_script_upload() {
    local src="$1" dest="$2"
    if [[ ! -f "$src" ]]; then
        record_component dr_script_upload fail "DR script source missing: $src"
        return 0
    fi
    local out
    if out="$(rclone copy "$src" "$dest" 2>&1)"; then
        record_component dr_script_upload ok "uploaded $(basename "$src") to $dest"
    else
        record_component dr_script_upload fail \
            "rclone copy failed: $(tail -c 200 <<<"$out" | tr '\n' ' ')"
    fi
}
