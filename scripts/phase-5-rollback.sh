#!/usr/bin/env bash
# LRR Phase 5 rollback — full Qwen3.5-9B rollback from Hermes 3 70B.
#
# Implements the Phase 5 spec §6.2 full Qwen rollback procedure.
#
# AMENDMENT 2026-04-15 (drop #62 Option C): this script was drafted
# against the 70B substrate SWAP assumption (now Phase 5b, deferred
# behind a hardware envelope gate). Under Phase 5a (Hermes 3 8B parallel
# pivot, the primary path), this full-Qwen-restore script is NOT the
# rollback path.
#
# 5a rollback is structurally simpler because 5a is additive, not a
# swap: Qwen never leaves TabbyAPI, it runs alongside Hermes 3 8B on a
# separate slot with separate LiteLLM routes. The 5a rollback is:
#
#   1. conversation_pipeline.py: flip active_model_family default from
#      "hermes_8b" back to "qwen" (one config line or env var)
#   2. litellm/config.yaml: disable local-fast-hermes / coding-hermes /
#      reasoning-hermes routes (comment out or remove — Qwen routes
#      unaffected)
#   3. hapax-daimonion: no restart needed (dispatch is per-turn)
#   4. TabbyAPI: no restart needed (the Hermes 8B slot can stay loaded
#      and idle, or be unloaded on next restart to free VRAM)
#
# At Phase 5a execution time, alpha either (a) rewrites this script in
# place with --variant 5a plumbing, or (b) leaves this as the 5b
# reference and writes a sibling phase-5a-rollback.sh for the dispatch
# flip above. Neither decision needs to be made at pre-stage time.
#
# See the Phase 5 spec §0.5 and DEVIATION-037 amendment for the full
# 5a/5b split.
#
# Use this when:
#
#   - The 3.0 bpw directive compliance benchmark fails AND the 3.5 bpw
#     fallback also fails (or is not available)
#   - The consent revocation drill envelope regresses by > 500ms
#   - The speech continuity test shows dropped audio frames
#   - Any other Phase 5 exit criterion becomes unmeetable
#
# For the 3.5 bpw fallback procedure (preferred intermediate rollback
# that stays inside Phase 5), see Phase 5 spec §6.1 — that path is
# simpler and does not require this script.
#
# SAFETY:
#
#   - DRY RUN is the default. Pass --live to actually mutate state.
#   - Requires operator confirmation before --live. The prompt is
#     hardcoded to "type 'ROLLBACK' to continue"; automated callers
#     must pass --yes AFTER --live.
#   - Always preserves the pre-swap Qwen config.yml backup at
#     ~/projects/tabbyAPI/config.yml.qwen-backup. If no backup exists,
#     the script aborts — full Qwen rollback without the backup is
#     not possible.
#
# Procedure (per Phase 5 spec §6.2):
#
#   1. Stop tabbyapi + hapax-daimonion
#   2. Revert ~/projects/tabbyAPI/config.yml to the Qwen backup
#   3. Remove the Hermes 3 drop-in (tabbyapi.service.d/gpu-pin.conf)
#      reverting Option γ → Option α
#   4. Keep hapax-daimonion.service.d/gpu-pin.conf (GPU-0 pin is
#      compatible with both partitions)
#   5. daemon-reload + start tabbyapi
#   6. Verify Qwen load
#   7. Start hapax-daimonion
#   8. Close the Hermes condition with status: rolled_back_to_qwen
#   9. Open a new post-rollback Qwen condition
#  10. Print the path to DEVIATION-037-rollback.md template the
#      operator fills in
#
# Exit codes:
#
#    0  rollback completed (live) or dry-run produced the plan
#    1  argparse / safety-prompt error
#    2  Qwen backup missing (cannot proceed)
#    3  systemctl stop failed
#    4  config revert failed
#    5  systemctl start failed post-revert
#    6  research-registry command failed

set -u

DRY_RUN=1
YES=0
HERMES_CONDITION=""
NEW_QWEN_CONDITION=""
TABBYAPI_DIR="${TABBYAPI_DIR:-$HOME/projects/tabbyAPI}"
UNIT_DIR="${UNIT_DIR:-$HOME/.config/systemd/user}"

usage() {
  cat <<EOF
Usage: phase-5-rollback.sh [options]

Options:
  --live                Actually perform the rollback (default: dry-run)
  --yes                 Skip the confirmation prompt (requires --live)
  --hermes-condition ID Condition ID of the Hermes 3 run to close (REQUIRED if --live)
  --new-condition ID    New Qwen condition_id to open (REQUIRED if --live)
  --tabbyapi-dir PATH   TabbyAPI clone root (default: \$TABBYAPI_DIR or ~/projects/tabbyAPI)
  --help                Show this help

Examples:

  # Dry-run — see what would happen without mutating anything
  phase-5-rollback.sh

  # Live rollback with explicit condition IDs + confirmation
  phase-5-rollback.sh --live \\
    --hermes-condition cond-phase-a-prime-hermes-002 \\
    --new-condition cond-phase-a-post-rollback-qwen-003

  # Fully unattended (CI or scripted recovery)
  phase-5-rollback.sh --live --yes \\
    --hermes-condition cond-phase-a-prime-hermes-002 \\
    --new-condition cond-phase-a-post-rollback-qwen-003
EOF
}

log() {
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "[DRY-RUN] $*"
  else
    echo "[LIVE]    $*"
  fi
}

die() {
  echo "ERROR: $*" >&2
  exit "${2:-1}"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --live)       DRY_RUN=0 ;;
    --yes)        YES=1 ;;
    --hermes-condition) HERMES_CONDITION="${2:-}"; shift ;;
    --new-condition)    NEW_QWEN_CONDITION="${2:-}"; shift ;;
    --tabbyapi-dir)     TABBYAPI_DIR="${2:-}"; shift ;;
    --help|-h)    usage; exit 0 ;;
    *)            die "unknown option: $1" 1 ;;
  esac
  shift
done

# Validation
if [ "$DRY_RUN" -eq 0 ]; then
  [ -n "$HERMES_CONDITION" ] || die "--live requires --hermes-condition" 1
  [ -n "$NEW_QWEN_CONDITION" ] || die "--live requires --new-condition" 1
fi

# Check Qwen backup exists — non-negotiable prerequisite
QWEN_BACKUP="$TABBYAPI_DIR/config.yml.qwen-backup"
if [ "$DRY_RUN" -eq 0 ] && [ ! -f "$QWEN_BACKUP" ]; then
  die "Qwen backup missing at $QWEN_BACKUP — full rollback not possible" 2
fi

echo "=============================================================="
echo "LRR Phase 5 FULL QWEN ROLLBACK"
if [ "$DRY_RUN" -eq 1 ]; then
  echo "Mode: DRY RUN (no state mutations)"
else
  echo "Mode: LIVE"
fi
echo "TabbyAPI dir: $TABBYAPI_DIR"
if [ -n "$HERMES_CONDITION" ]; then
  echo "Hermes condition to close: $HERMES_CONDITION"
fi
if [ -n "$NEW_QWEN_CONDITION" ]; then
  echo "New Qwen condition to open: $NEW_QWEN_CONDITION"
fi
echo "=============================================================="

# Safety prompt
if [ "$DRY_RUN" -eq 0 ] && [ "$YES" -eq 0 ]; then
  echo ""
  echo "This will:"
  echo "  - Stop tabbyapi + hapax-daimonion"
  echo "  - Revert config.yml to the Qwen backup"
  echo "  - Remove the Option γ drop-in on tabbyapi"
  echo "  - daemon-reload + start services"
  echo "  - Close the Hermes condition in the research registry"
  echo "  - Open a new Qwen post-rollback condition"
  echo ""
  echo "Condition A data for both conditions (Qwen baseline + Hermes attempt) is"
  echo "PRESERVED via the append-only research registry. This rollback does NOT"
  echo "destroy data."
  echo ""
  read -r -p "Type 'ROLLBACK' to continue: " confirm
  if [ "$confirm" != "ROLLBACK" ]; then
    die "rollback cancelled by operator" 1
  fi
fi

# Step 1: stop services
log "systemctl --user stop tabbyapi"
if [ "$DRY_RUN" -eq 0 ]; then
  systemctl --user stop tabbyapi || die "tabbyapi stop failed" 3
fi

log "systemctl --user stop hapax-daimonion"
if [ "$DRY_RUN" -eq 0 ]; then
  systemctl --user stop hapax-daimonion || die "hapax-daimonion stop failed" 3
fi

# Step 2: revert config
log "cp $QWEN_BACKUP $TABBYAPI_DIR/config.yml"
if [ "$DRY_RUN" -eq 0 ]; then
  cp "$QWEN_BACKUP" "$TABBYAPI_DIR/config.yml" || die "config revert failed" 4
fi

# Step 3: remove tabbyapi Option γ drop-in
TABBY_DROPIN="$UNIT_DIR/tabbyapi.service.d/gpu-pin.conf"
if [ -L "$TABBY_DROPIN" ] || [ -f "$TABBY_DROPIN" ]; then
  log "rm $TABBY_DROPIN"
  if [ "$DRY_RUN" -eq 0 ]; then
    rm -f "$TABBY_DROPIN" || die "drop-in removal failed" 4
  fi
else
  log "tabbyapi drop-in already absent at $TABBY_DROPIN (no-op)"
fi

# Step 4: KEEP hapax-daimonion GPU-0 pin (compatible with Option α)
log "KEEPING hapax-daimonion.service.d/gpu-pin.conf (GPU-0 pin is compatible with both partitions)"

# Step 5: daemon-reload + start tabbyapi
log "systemctl --user daemon-reload"
if [ "$DRY_RUN" -eq 0 ]; then
  systemctl --user daemon-reload || die "daemon-reload failed" 5
fi

log "systemctl --user start tabbyapi"
if [ "$DRY_RUN" -eq 0 ]; then
  systemctl --user start tabbyapi || die "tabbyapi start failed" 5
fi

# Step 6: verify Qwen load
if [ "$DRY_RUN" -eq 0 ]; then
  log "Waiting 30s for Qwen model load..."
  sleep 30
  log "curl http://localhost:5000/v1/models"
  if command -v curl >/dev/null 2>&1; then
    curl -s http://localhost:5000/v1/models | grep -i qwen || \
      die "Qwen model not reported by tabbyapi /v1/models" 5
  else
    log "curl not available — skipping /v1/models verification"
  fi
else
  log "sleep 30 && curl http://localhost:5000/v1/models | grep -i qwen"
fi

# Step 7: start hapax-daimonion
log "systemctl --user start hapax-daimonion"
if [ "$DRY_RUN" -eq 0 ]; then
  systemctl --user start hapax-daimonion || die "hapax-daimonion start failed" 5
fi

# Step 8: close Hermes condition via research-registry
if [ -n "$HERMES_CONDITION" ]; then
  log "scripts/research-registry.py close $HERMES_CONDITION (status: rolled_back_to_qwen)"
  if [ "$DRY_RUN" -eq 0 ]; then
    # Note: research-registry.py does not currently accept --status kwarg in close;
    # the close metadata is recorded in the condition.yaml manually.
    scripts/research-registry.py close "$HERMES_CONDITION" || \
      die "research-registry close failed" 6
    log "NOTE: manually edit ~/hapax-state/research-registry/$HERMES_CONDITION/condition.yaml"
    log "      to add: status: rolled_back_to_qwen"
  fi
fi

# Step 9: open new Qwen post-rollback condition
if [ -n "$NEW_QWEN_CONDITION" ]; then
  # Extract the slug from the condition ID (everything after "cond-")
  SLUG="${NEW_QWEN_CONDITION#cond-}"
  log "scripts/research-registry.py open (slug derived from $NEW_QWEN_CONDITION)"
  if [ "$DRY_RUN" -eq 0 ]; then
    scripts/research-registry.py open "$SLUG" || \
      die "research-registry open failed" 6
  fi
fi

# Step 10: print DEVIATION-037-rollback.md template path
log ""
log "=============================================================="
log "ROLLBACK COMPLETE"
if [ "$DRY_RUN" -eq 0 ]; then
  log "Manual follow-up:"
  log "  1. Verify Qwen responses via curl http://localhost:5000/v1/chat/completions"
  log "  2. Run 1 voice utterance smoke test end-to-end"
  log "  3. File research/protocols/deviations/DEVIATION-037-rollback.md"
  log "     explaining the rollback reason (which exit criterion failed)"
  log "  4. Update agents/hapax_daimonion/proofs/RESEARCH-STATE.md with"
  log "     the Phase 5 rollback event"
  log "  5. Update ~/.cache/hapax/relay/*.yaml status files"
else
  log "This was a DRY RUN. To execute, re-run with --live plus the required IDs:"
  log "  phase-5-rollback.sh --live \\"
  log "    --hermes-condition cond-phase-a-prime-hermes-NNN \\"
  log "    --new-condition cond-phase-a-post-rollback-qwen-NNN+1"
fi
log "=============================================================="

exit 0
