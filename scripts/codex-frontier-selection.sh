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

# THE BASELINE A GUARD COMPARES AGAINST MAY NOT BE CHOSEN BY THE PARTY BEING GUARDED.
#
# These were plain `${VAR:-default}` overrides, which made the frontier caller-settable — and a
# caller who sets the frontier TO their downgrade is compared against themselves. Measured:
#
#   HAPAX_CODEX_FRONTIER_MODEL=gpt-5.3-codex-spark  -c model="gpt-5.3-codex-spark"  -> exit 0
#
# No obscure spelling and no edge case: the guard evaluates a tautology.
#
# The override is NOT removed, because it is deliberate — the pair is "a decision point, not a
# constant", so adopting a better model moves every launcher at once. Two requirements pulling
# opposite ways on one mechanism is the signal for a third state rather than a boolean.
#
# The third state: redefining the frontier is itself a decision and must SAY WHY — the rule
# already applied to a downgrade, applied to the larger act. This guard cannot order models, so
# it cannot tell raising from lowering; requiring a stated reason for any change is the predicate
# it CAN check, and it is the honest one.
HAPAX_CODEX_FRONTIER_MODEL_BUILTIN="gpt-5.6-sol"
HAPAX_CODEX_FRONTIER_EFFORT_BUILTIN="ultra"
HAPAX_CODEX_FRONTIER_MODEL="${HAPAX_CODEX_FRONTIER_MODEL:-$HAPAX_CODEX_FRONTIER_MODEL_BUILTIN}"
HAPAX_CODEX_FRONTIER_EFFORT="${HAPAX_CODEX_FRONTIER_EFFORT:-$HAPAX_CODEX_FRONTIER_EFFORT_BUILTIN}"
CODEX_MODEL="${HAPAX_CODEX_MODEL:-$HAPAX_CODEX_FRONTIER_MODEL}"
CODEX_EFFORT="${HAPAX_CODEX_EFFORT:-$HAPAX_CODEX_FRONTIER_EFFORT}"
CODEX_MODEL_REASON="${HAPAX_CODEX_MODEL_REASON:-}"

if [ "$HAPAX_CODEX_FRONTIER_MODEL" != "$HAPAX_CODEX_FRONTIER_MODEL_BUILTIN" ] ||
  [ "$HAPAX_CODEX_FRONTIER_EFFORT" != "$HAPAX_CODEX_FRONTIER_EFFORT_BUILTIN" ]; then
  if [ -z "$CODEX_MODEL_REASON" ]; then
    echo "${CODEX_LAUNCHER:-hapax-codex}: REFUSING a redefined frontier with no stated reason." >&2
    echo "  requested frontier: model=$HAPAX_CODEX_FRONTIER_MODEL effort=$HAPAX_CODEX_FRONTIER_EFFORT" >&2
    echo "  built-in frontier:  model=$HAPAX_CODEX_FRONTIER_MODEL_BUILTIN effort=$HAPAX_CODEX_FRONTIER_EFFORT_BUILTIN" >&2
    echo "  Moving the frontier moves every launcher's default, and setting it TO a downgrade" >&2
    echo "  makes the below-frontier check compare a value against itself." >&2
    echo "  Next: re-run with HAPAX_CODEX_MODEL_REASON='<why this frontier>'." >&2
    exit 6
  fi
fi

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
# CONFIG IS NOT THE ONLY WAY TO SAY IT. `codex --help` lists `-m, --model <MODEL>` beside
# `-c, --config <key=value>`, on the top-level command and on `exec`. The first revision of this
# scanner read only `-c`/`--config`, so `-- --model gpt-5.5` walked straight past a guard written
# to stop exactly that. Two spellings of one selection, one of them checked: the same input-set
# defect a third time, which is why the scanner now enumerates every spelling codex accepts
# rather than the one that happened to be on my mind.
#
# THE KEY IS TOML, SO IT MAY CARRY WHITESPACE. Three rounds of review found three spellings this
# scanner did not read: config-at-all, then the CLI flag, then `-c 'model = "gpt-5.5"'` with spaces
# around the `=`. Three mitigations for one hazard is the estate's own proof that the boundary is
# wrong, so before adding a fourth enumeration I measured what codex 0.146 actually honours,
# with `codex doctor` (which prints the effective config and spends nothing):
#
#   codex -c 'model="A"' -c 'model="B"' doctor        -> B      (config is LAST-wins)
#   codex --model A -c 'model="B"' doctor             -> A      (the FLAG beats a later config)
#   codex -c 'model = "spaced"' doctor                -> spaced (whitespace around = is honoured)
#   codex -c '"model" = "quoted"' doctor              -> ignored (a QUOTED key is not honoured)
#
# Those measurements decide the design, and one of them killed the redesign I intended. Emitting
# the estate's own `-c model=` LAST would have made the validated selection win structurally and
# demoted this scanner to an error-message improver — except the flag beats config regardless of
# order, so that shape does not hold and the scanner stays load-bearing. Building it on
# "last-wins covers everything" would have been a precondition asserted rather than checked.
#
# What remains is therefore normalisation, not another spelling: trim the whitespace TOML permits.
# Quoted keys are deliberately NOT handled — codex ignores them, so they cannot bypass anything,
# and refusing them would be a guard firing on a form that has no effect.
_cfs_trim() {
  _cfs_v="${_cfs_v#"${_cfs_v%%[![:space:]]*}"}"
  _cfs_v="${_cfs_v%"${_cfs_v##*[![:space:]]}"}"
}
_cfs_strip_quotes() {
  _cfs_val="${_cfs_val%\"}"; _cfs_val="${_cfs_val#\"}"
  _cfs_val="${_cfs_val%\'}"; _cfs_val="${_cfs_val#\'}"
}
# PRECEDENCE IS CODEX'S, NOT THE ARGUMENT ORDER'S.
#
# The first version of this scanner assigned straight into CODEX_MODEL as it walked, so the LAST
# spelling seen won. codex does not work that way — measured with `codex doctor`:
#
#   codex --model A -c 'model="B"' doctor   -> A      the FLAG wins
#   codex -c 'model="A"' --model B doctor   -> B      the FLAG wins
#
# The flag beats config in BOTH orders. Last-wins therefore disagreed with codex whenever the two
# spellings were mixed, and `--model gpt-5.5 -c 'model="gpt-5.6-sol"'` resolved to the frontier
# here and exited 0 while codex would have run gpt-5.5. A guard that models the wrong precedence
# is not a weaker guard — it is a guard that approves the thing it was asked to refuse.
#
# So the two channels are tracked separately and combined by codex's rule, not by iteration order.
if [ "${#CODEX_EXTRA[@]}" -gt 0 ] 2>/dev/null; then
  _cfs_expect_config=0
  _cfs_expect_model=0
  _cfs_expect_profile=0
  _cfs_profile=""
  _cfs_flag_model=""
  _cfs_config_model=""
  _cfs_config_effort=""
  for _cfs_arg in "${CODEX_EXTRA[@]}"; do
    _cfs_assign=""
    if [ "$_cfs_expect_model" -eq 1 ]; then
      _cfs_val="$_cfs_arg"; _cfs_strip_quotes; _cfs_flag_model="$_cfs_val"
      _cfs_expect_model=0
      continue
    fi
    if [ "$_cfs_expect_profile" -eq 1 ]; then
      _cfs_profile="$_cfs_arg"
      _cfs_expect_profile=0
      continue
    fi
    if [ "$_cfs_expect_config" -eq 1 ]; then
      _cfs_assign="$_cfs_arg"
      _cfs_expect_config=0
    else
      case "$_cfs_arg" in
        -c|--config)  _cfs_expect_config=1; continue ;;
        -m|--model)   _cfs_expect_model=1; continue ;;
        -p|--profile) _cfs_expect_profile=1; continue ;;
        --model=*)    _cfs_val="${_cfs_arg#--model=}"; _cfs_strip_quotes
                      _cfs_flag_model="$_cfs_val"; continue ;;
        -m?*)         _cfs_val="${_cfs_arg#-m}"; _cfs_strip_quotes
                      _cfs_flag_model="$_cfs_val"; continue ;;
        --profile=*)  _cfs_profile="${_cfs_arg#--profile=}"; continue ;;
        # GLUED SHORT FORM. `-m?*` two lines up handles the model; the profile twin was never
        # written, so `-pmyprofile` fell through every arm and the guard passed a selection it
        # cannot see. Measured: `-p prof` and `--profile=prof` exit 6; `-pprof` exited 0.
        # An asymmetry between two arms of one scanner is the easiest hole to leave, because each
        # spelling reads as handled when checked beside its own flag rather than beside its twin.
        -p?*)         _cfs_profile="${_cfs_arg#-p}"; continue ;;
        -c?*=*)       _cfs_assign="${_cfs_arg#-c}" ;;
        --config=*)   _cfs_assign="${_cfs_arg#--config=}" ;;
      esac
    fi
    [ -n "$_cfs_assign" ] || continue
    _cfs_v="${_cfs_assign%%=*}"; _cfs_trim; _cfs_key="$_cfs_v"
    _cfs_v="${_cfs_assign#*=}"; _cfs_trim; _cfs_val="$_cfs_v"
    # codex config values are commonly quoted; the quotes are syntax, not value.
    _cfs_strip_quotes
    case "$_cfs_key" in
      model)                  _cfs_config_model="$_cfs_val" ;;
      model_reasoning_effort) _cfs_config_effort="$_cfs_val" ;;
    esac
  done

  # codex's rule, applied once at the end: the flag beats config in either order. Effort has no
  # CLI flag, so config is its only passthrough channel.
  if [ -n "$_cfs_flag_model" ]; then
    CODEX_MODEL="$_cfs_flag_model"
  elif [ -n "$_cfs_config_model" ]; then
    CODEX_MODEL="$_cfs_config_model"
  fi
  [ -n "$_cfs_config_effort" ] && CODEX_EFFORT="$_cfs_config_effort"

  # A PROFILE MAKES THE SELECTION UNVERIFIABLE FROM HERE. `-p/--profile` names a block in
  # ~/.codex/config.toml that may set `model` or `model_reasoning_effort` to anything. Resolving
  # it would mean parsing a file outside the repository and reimplementing codex's precedence
  # rules, and a guard that GUESSES the effective model is worse than one that says it cannot
  # see it. So a profile must state its reason -- the fail-closed direction, and the same remedy
  # as any other downgrade.
  if [ -n "$_cfs_profile" ] && [ -z "$CODEX_MODEL_REASON" ]; then
    echo "${CODEX_LAUNCHER:-hapax-codex}: REFUSING --profile with no stated reason." >&2
    echo "  profile:  $_cfs_profile" >&2
    echo "  A profile may set model or model_reasoning_effort in ~/.codex/config.toml, so the" >&2
    echo "  effective selection cannot be verified here. This guard does not guess." >&2
    echo "  Next: re-run with HAPAX_CODEX_MODEL_REASON='<why this profile>'." >&2
    exit 6
  fi
  unset _cfs_expect_config _cfs_expect_model _cfs_expect_profile
  unset _cfs_arg _cfs_assign _cfs_key _cfs_val _cfs_profile
  unset _cfs_flag_model _cfs_config_model _cfs_config_effort
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
  #
  # RECORD-BEFORE-PROCEED IS A PREDICATE, SO IT FAILS CLOSED. The first revision wrote this
  # with `2>/dev/null || true` on both the mkdir and the append, then printed "recorded" and
  # carried on. A read-only cache, a full disk or a bad path therefore produced an UNRECORDED
  # downgrade that announced itself as recorded — the stated predicate and the behaviour
  # disagreed, and the behaviour was the permissive one. If the artifact is what makes the
  # downgrade legitimate, then no artifact means no downgrade.
  #
  # The reason is escaped for JSON rather than stripped: a newline or a control character
  # inside it would otherwise split one record into two lines and corrupt the log it exists
  # to write. `\` and `"` are escaped, and everything below 0x20 becomes a space.
  MODEL_DECISION_LOG="${XDG_CACHE_HOME:-$HOME/.cache}/hapax/routing/model-decisions.jsonl"
  _cfs_reason_json="$(printf '%s' "$CODEX_MODEL_REASON" \
    | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr -d '\000-\010\013\014\016-\037' | tr '\n\r\t' '   ')"
  if ! mkdir -p "$(dirname "$MODEL_DECISION_LOG")" 2>/dev/null; then
    echo "${CODEX_LAUNCHER:-hapax-codex}: REFUSING the downgrade -- cannot create the decision log directory." >&2
    echo "  path: $(dirname "$MODEL_DECISION_LOG")" >&2
    echo "  A below-frontier selection is legitimate only because it is recorded, so an" >&2
    echo "  unwritable record is a refusal, not a warning." >&2
    echo "  Next: make that directory writable, or set XDG_CACHE_HOME to somewhere that is." >&2
    exit 7
  fi
  if ! printf '{"at":"%s","launcher":"%s","lane":"%s","model":"%s","effort":"%s","frontier_model":"%s","frontier_effort":"%s","reason":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${CODEX_LAUNCHER:-hapax-codex}" "${ROLE:-unknown}" \
    "$CODEX_MODEL" "$CODEX_EFFORT" \
    "$HAPAX_CODEX_FRONTIER_MODEL" "$HAPAX_CODEX_FRONTIER_EFFORT" \
    "$_cfs_reason_json" \
    >>"$MODEL_DECISION_LOG" 2>/dev/null; then
    echo "${CODEX_LAUNCHER:-hapax-codex}: REFUSING the downgrade -- cannot append to the decision log." >&2
    echo "  path: $MODEL_DECISION_LOG" >&2
    echo "  Next: check permissions and free space on that path, then re-run." >&2
    exit 7
  fi
  unset _cfs_reason_json
  echo "${CODEX_LAUNCHER:-hapax-codex}: below-frontier selection recorded: model=$CODEX_MODEL effort=$CODEX_EFFORT" >&2
fi
