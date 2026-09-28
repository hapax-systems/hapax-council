#!/usr/bin/env bash
# ci_classify_shard_exit.sh — classify one pytest run that ran under the CI wrapper.
#
# WHY THIS IS A SCRIPT AND NOT INLINE. The classification lived in two workflow
# run blocks, where no test could reach it, and the completed-test count was
# wrong in a way only a test would have caught: it anchored on "the line starts
# with a progress character", so interleaved pytest output and traceback
# continuation lines were counted as completed tests. On the specimen (CI run
# 36369340992, shard 3/4, job 108762193345) that is 10739 "markers" against
# 10512 real ones: 227 invented tests. The count is now anchored on the whole
# progress line, and a test feeds it the specimen.
#
# usage: ci_classify_shard_exit.sh <pytest-exit> <artifact-exit> <output-file>
#   <pytest-exit>    the wrapper/pytest exit code (${PIPESTATUS[0]})
#   <artifact-exit>  the duration-artifact write exit code, 0 when not applicable
#   <output-file>    the pytest output that was tee'd during the run
#
# Exit codes: 0 the suite passed; 1 for anything else. A kill is reported as a
# kill and never as a test failure; a duration-artifact failure is named only
# when it is the actual cause, because a killed run has no --durations summary
# to write and that is a consequence of the kill, not a second failure.
#
# Evidence of record: merge-group-ci-flakes-shard-selector-and-title-cards-20260902
set -uo pipefail

usage() {
  echo "usage: ci_classify_shard_exit.sh <pytest-exit> <artifact-exit> <output-file>" >&2
}

pytest_exit="${1:-}"
artifact_exit="${2:-0}"
output_file="${3:-}"

if [ -z "$pytest_exit" ] || [ -z "$output_file" ]; then
  usage
  exit 2
fi
if [ ! -f "$output_file" ]; then
  echo "ci_classify_shard_exit: no such pytest output file: $output_file" >&2
  usage
  exit 2
fi

# pytest -q prints one progress character per completed test, and a killed run
# never prints its "N passed" summary, so the progress lines are the only count
# that survives a kill. Anchored on the complete progress-line shape — markers,
# spacing, then the "[ NN%]" suffix — so a line that merely BEGINS with a marker
# character (a traceback or interleaved pytest output) is not counted. The final
# partial progress line, which carries no percentage suffix, is not counted
# either: this is a lower bound, and it says so.
count_completed_markers() {
  awk '
    /^[.FEsxX]+[ \t]+\[ *[0-9]+%\]$/ {
      run = substr($0, 1, index($0, "[") - 1)
      gsub(/[ \t]/, "", run)
      total += length(run)
    }
    END { print total + 0 }
  ' "$1"
}

last_progress() {
  grep -oE '\[ *[0-9]+%\]' "$1" | tail -1 | tr -dc '0-9' || true
}

kill_signal=""
case "$pytest_exit" in
  124) kill_signal="SIGTERM (124)" ;;
  137) kill_signal="SIGKILL (137)" ;;
esac

if [ -n "$kill_signal" ]; then
  completed_markers="$(count_completed_markers "$output_file")"
  reached="$(last_progress "$output_file")"
  echo "killed at the shard timeout after ${completed_markers} tests (lower bound from progress lines); in-flight: the tests that printed no progress marker (${reached:-no}% reached before ${kill_signal})."
  echo "This is NOT a test failure: the wrapper (timeout -s KILL) fired while the shard was still running, so no test result was withheld or lost."
  echo "Last lines before the kill — the in-flight window:"
  tail -n 5 "$output_file"
  echo "The stack dump that names those threads is owed by clause (6) of merge-group-ci-flakes-shard-selector-and-title-cards-20260902."
  if [ "$artifact_exit" != "0" ]; then
    echo "The duration artifact was not written (exit ${artifact_exit}); a killed run has no --durations summary to record, so that is a consequence of the kill, not a second failure."
  fi
  exit 1
fi

if [ "$artifact_exit" != "0" ]; then
  echo "Could not write pytest node duration artifact (exit ${artifact_exit})"
  exit 1
fi

# pytest exit codes: 0 = all passed, 1 = failures, 2/4 = usage error,
# 3 = internal error, 5 = no tests collected.
if [ "$pytest_exit" = "0" ]; then
  # Sanity: a success must have a pytest summary line.
  if grep -qE '\bpassed\b' "$output_file"; then
    echo "All tests passed (pytest exit 0)"
    exit 0
  fi
  echo "No test summary found — likely crashed or timed out"
  exit 1
fi

echo "Tests failed (pytest exit ${pytest_exit})"
exit 1
