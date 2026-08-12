# shellcheck shell=bash
# Frontier model/effort selection for every governed Codex launcher.
#
# WHY THIS IS A SHARED FILE AND NOT A COPIED BLOCK. Both launchers previously carried
# `model="gpt-5.5"` / `model_reasoning_effort="xhigh"` as bare literals inside CODEX_ARGS,
# under a comment reading "shared contract — keep in sync". That comment is human
# discipline, which is the bottom of the mechanism ladder, and it had already failed:
# hapax-codex grew a selection guard on 2026-08-10 and hapax-codex-headless did not.
# Two call sites, one hazard, so one definition.
#
# WHAT IT ENFORCES. Selecting anything other than the frontier pair requires a stated
# reason, recorded. Refusing without one is the point: the failure this exists to prevent
# is an UNSTATED downgrade, and a warning would be ignored. Measured across 2026-08-09/10,
# 29 of 33 codex sessions ran at `low` and none ran at the frontier effort — so the defect
# is real, live, and larger than the launchers themselves. Ad-hoc `codex exec` invocations
# bypass this file entirely; the receipt-path posture check is what sees those.
#
# The defaults are the frontier pair as of 2026-08-10, both verified from a measured
# rollout head rather than a launcher self-report. Changing them is a one-line operator
# act, and the spinal calculi later inherit a decision point rather than a constant.
#
# Callers may set CODEX_LAUNCHER before sourcing; it appears only in messages.

HAPAX_CODEX_FRONTIER_MODEL="${HAPAX_CODEX_FRONTIER_MODEL:-gpt-5.6-sol}"
HAPAX_CODEX_FRONTIER_EFFORT="${HAPAX_CODEX_FRONTIER_EFFORT:-ultra}"
CODEX_MODEL="${HAPAX_CODEX_MODEL:-$HAPAX_CODEX_FRONTIER_MODEL}"
CODEX_EFFORT="${HAPAX_CODEX_EFFORT:-$HAPAX_CODEX_FRONTIER_EFFORT}"
CODEX_MODEL_REASON="${HAPAX_CODEX_MODEL_REASON:-}"

# PASSTHROUGH IS PART OF THE SELECTION, so it must be part of what is checked.
#
# Both launchers append "${CODEX_EXTRA[@]}" AFTER their own `-c model=...`, and codex takes the
# last `-c` for a key. So `hapax-codex -- -c 'model="gpt-5.5"'` used to override a selection this
# file had already validated, with no reason required and nothing recorded. The registry's Spark
# launcher already uses exactly that form, so the hole was live rather than theoretical.
#
# That is the same defect this file was written to fix, one layer out: a real check whose INPUT
# SET excluded the deciding state. The fix is not a second guard next to the first -- two
# mitigations for one hazard is the smell -- it is to give the existing predicate the effective
# values. Passthrough overrides are folded in here, and the single check below then sees what
# codex will actually run with.
#
# Callers must therefore populate CODEX_EXTRA BEFORE sourcing this file. Both launchers do, and
# `test_codex_frontier_selection.py` pins that ordering so a future edit cannot quietly undo it.
if [ "${#CODEX_EXTRA[@]}" -gt 0 ] 2>/dev/null; then
  _cfs_expect_config=0
  for _cfs_arg in "${CODEX_EXTRA[@]}"; do
    _cfs_assign=""
    if [ "$_cfs_expect_config" -eq 1 ]; then
      _cfs_assign="$_cfs_arg"
      _cfs_expect_config=0
    else
      case "$_cfs_arg" in
        -c|--config) _cfs_expect_config=1; continue ;;
        -c*=*)       _cfs_assign="${_cfs_arg#-c}" ;;
        --config=*)  _cfs_assign="${_cfs_arg#--config=}" ;;
      esac
    fi
    [ -n "$_cfs_assign" ] || continue
    _cfs_key="${_cfs_assign%%=*}"
    _cfs_val="${_cfs_assign#*=}"
    # codex config values are commonly quoted; the quotes are syntax, not value.
    _cfs_val="${_cfs_val%\"}"; _cfs_val="${_cfs_val#\"}"
    _cfs_val="${_cfs_val%\'}"; _cfs_val="${_cfs_val#\'}"
    case "$_cfs_key" in
      model)                  CODEX_MODEL="$_cfs_val" ;;
      model_reasoning_effort) CODEX_EFFORT="$_cfs_val" ;;
    esac
  done
  unset _cfs_expect_config _cfs_arg _cfs_assign _cfs_key _cfs_val
fi

if [ "$CODEX_MODEL" != "$HAPAX_CODEX_FRONTIER_MODEL" ] ||
  [ "$CODEX_EFFORT" != "$HAPAX_CODEX_FRONTIER_EFFORT" ]; then
  if [ -z "$CODEX_MODEL_REASON" ]; then
    echo "${CODEX_LAUNCHER:-hapax-codex}: REFUSING a below-frontier selection with no stated reason." >&2
    echo "  requested: model=$CODEX_MODEL effort=$CODEX_EFFORT" >&2
    echo "  frontier:  model=$HAPAX_CODEX_FRONTIER_MODEL effort=$HAPAX_CODEX_FRONTIER_EFFORT" >&2
    echo "  Routing is the spine's to own; until it does, a downgrade is an operator act that" >&2
    echo "  must say why. Next: re-run with HAPAX_CODEX_MODEL_REASON='<why>'." >&2
    exit 6
  fi
  # Recorded, not merely permitted: the reason is the artifact, and a lane that cannot
  # explain its own downgrade should not have taken one.
  MODEL_DECISION_LOG="${XDG_CACHE_HOME:-$HOME/.cache}/hapax/routing/model-decisions.jsonl"
  mkdir -p "$(dirname "$MODEL_DECISION_LOG")" 2>/dev/null || true
  printf '{"at":"%s","launcher":"%s","lane":"%s","model":"%s","effort":"%s","frontier_model":"%s","frontier_effort":"%s","reason":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${CODEX_LAUNCHER:-hapax-codex}" "${ROLE:-unknown}" \
    "$CODEX_MODEL" "$CODEX_EFFORT" \
    "$HAPAX_CODEX_FRONTIER_MODEL" "$HAPAX_CODEX_FRONTIER_EFFORT" \
    "$(printf '%s' "$CODEX_MODEL_REASON" | tr -d '"\\')" \
    >>"$MODEL_DECISION_LOG" 2>/dev/null || true
  echo "${CODEX_LAUNCHER:-hapax-codex}: below-frontier selection recorded: model=$CODEX_MODEL effort=$CODEX_EFFORT" >&2
fi
