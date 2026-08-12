#!/usr/bin/env bash
# pii-guard.sh — PreToolUse hook (Edit, Write)
#
# Blocks file writes that would introduce PII into tracked files.
# Checks for operator identity, location, family references, and
# sensitive personal data patterns.
#
# Only checks files that git would track (respects .gitignore).
# Only blocks on HIGH-confidence matches to avoid false positives.
set -euo pipefail

# Fail LOUD when jq is missing: without it tool_name parses empty, the
# case below never matches Edit/Write, and the hook exits 0 — silently
# letting PII through. A privacy gate that no-ops is worse than one that
# fails, so block instead of failing open.
if ! command -v jq >/dev/null 2>&1; then
  echo "pii-guard: BLOCKED — 'jq' is not installed; cannot parse hook input." >&2
  echo "Install jq before mutating tracked files. This gate fails closed." >&2
  exit 2
fi

# Fail LOUD when grep lacks PCRE (-P): every pattern below uses grep -P,
# which on a non-PCRE grep errors out — indistinguishable from a clean
# no-match, i.e. PII would pass undetected. Probe once, fail closed.
if ! printf 'probe' | grep -qP 'probe' 2>/dev/null; then
  echo "pii-guard: BLOCKED — 'grep -P' (PCRE) is unavailable." >&2
  echo "The PII patterns require PCRE. Install GNU grep with PCRE support." >&2
  echo "This gate fails closed rather than silently passing PII through." >&2
  exit 2
fi

input="$(cat)"
tool_name="$(printf '%s' "$input" | jq -r '.tool_name // empty')"

# Only gate file-mutating tools.
#
# `Bash` is here because a shell write (`> file`, `tee`, `sed -i`, a heredoc) mutates tracked
# files without ever being an Edit, and this gate was blind to all of it. What is scanned for a
# Bash call is the COMMAND TEXT, which is an honest partial: it catches the literal case, which
# is how the original exposure was written, and it cannot see content assembled from variables
# or read from another file. That limit is stated rather than papered over — the failure this
# whole file documents is a guard reporting coverage it did not have.
#
# NOTE: code alone is not coverage. The hook must also be REGISTERED for Bash PreToolUse in
# `~/.claude/settings.json`, exactly as `unguarded-cd-guard.sh` is. Until it is, this arm is
# unreachable and the shell path stays unguarded.
case "$tool_name" in
  Edit|Write|MultiEdit|NotebookEdit|Bash) ;;
  *) exit 0 ;;
esac

# ONE CHECK SET, NOT TWO. The first Bash arm ran its own pair of patterns — operator name and
# prose age — while the Edit path ran five, including the registered-name list and `Name (NN)`.
# Two guards for one hazard is the smell this file keeps re-teaching, and DIVERGENT guards are
# worse than one: a registered household name in `echo "..." > file` passed while the same string
# through Edit blocked, so which tool a caller reached for decided whether a child's name was
# protected. That is not a gap in coverage, it is a coin flip.
#
# A Bash call therefore becomes (no path, command text) and falls through to the SAME battery
# below. Every check the Edit path gains, the shell path gains with it — by construction, not by
# somebody remembering to add it twice.
is_bash_tool=0
if [ "$tool_name" = "Bash" ]; then
  is_bash_tool=1
fi

# Extract file path.
#
# `notebook_path` is NotebookEdit's spelling. It was missing, so every NotebookEdit call
# exited here with no path and therefore no scan -- the tool sat on the allowlist above and
# was silently unguarded. Same shape as the household-name hole this file exists to close:
# the gate was not bypassed, it was never asked the question.
file_path="$(printf '%s' "$input" |
  jq -r '.tool_input.file_path // .tool_input.path // .tool_input.notebook_path // empty' \
  2>/dev/null || true)"
if [ "$is_bash_tool" -eq 0 ]; then
  [ -n "$file_path" ] || exit 0

  # Skip files that aren't git-tracked or would be gitignored
  if git rev-parse --is-inside-work-tree &>/dev/null; then
    # Allow writes to gitignored files (they won't reach GitHub)
    if git check-ignore -q "$file_path" 2>/dev/null; then
      exit 0
    fi
  fi
else
  # A shell command has no single target path to gitignore-check: it may write several, or
  # compute them. Skipping the path-shaped exits is the fail-closed choice — the command text
  # is still scanned, and a caller cannot opt a shell write out of the guard by aiming it at
  # something gitignored.
  file_path="(shell command)"
fi

# Extract the new content being written.
#
# MultiEdit carries its payload in `edits[].new_string` and NotebookEdit in `new_source`.
# Neither was read, so both tools fell through the empty-content exit below and returned 0
# for content Edit would have blocked. Reproduced by direct execution before the fix.
#
# `.tool_input.command` is the Bash spelling. Scanning the command TEXT is an honest partial: it
# catches the literal case, which is how the original exposure was written, and cannot see content
# assembled from a variable or read from another file. Stated, not papered over.
new_content="$(printf '%s' "$input" | jq -r '
  [ .tool_input.new_string?, .tool_input.content?, .tool_input.new_source?,
    .tool_input.command?,
    (.tool_input.edits? // [] | .[]? | .new_string?) ]
  | map(select(type == "string")) | join("\n")
' 2>/dev/null || true)"

# THE PATH IS SCANNED BEFORE ANY CONTENT-SHAPED EXIT, deliberately.
#
# The binary-extension skip and the empty-content exit both used to precede the filename
# check, so a registered household name could be introduced as an image filename or an empty
# file while the code claimed filenames were protected. A skip that is right about CONTENT
# must not silently also skip the PATH.
pii_names_file="${HAPAX_PII_NAMES_FILE:-$HOME/.config/hapax/pii-names.txt}"

glob_escape() {
  local s=$1
  s=${s//\\/\\\\}; s=${s//\*/\\*}; s=${s//\?/\\?}; s=${s//\[/\\[}
  printf '%s' "$s"
}

# 0 = contains a registered household name, 1 = clean or no list, 2 = the check itself broke.
# Callers treat 2 as a match: an unreadable answer is not a clean answer.
scan_for_registered_names() {
  local haystack_lc="${1,,}" exempt_lc pii_name grep_status
  [ -r "$pii_names_file" ] || return 1
  while IFS= read -r pii_line; do
    case "$pii_line" in
      '!'*) exempt_lc="${pii_line#!}"
            exempt_lc="${exempt_lc,,}"
            [ -n "$exempt_lc" ] || continue
            haystack_lc="${haystack_lc//$(glob_escape "$exempt_lc")/}" ;;
    esac
  done < "$pii_names_file"
  while IFS= read -r pii_name; do
    case "$pii_name" in ''|'#'*|'!'*) continue ;; esac
    grep_status=0
    printf '%s' "$haystack_lc" | grep -qP "(?<![A-Za-z])\\Q${pii_name,,}\\E(?![A-Za-z])" \
      || grep_status=$?
    if [ "$grep_status" -eq 0 ]; then return 0; fi
    if [ "$grep_status" -gt 1 ]; then return 2; fi
  done < "$pii_names_file"
  return 1
}

name_check_broken=0
path_name_status=0
scan_for_registered_names "$file_path" || path_name_status=$?
if [ "$path_name_status" -eq 0 ]; then
  echo "BLOCKED: PII detected in the FILENAME being written: $file_path" >&2
  echo "  - Registered household name in the path (see \$HAPAX_PII_NAMES_FILE)" >&2
  echo "  Rename the file to an opaque principal id before writing it." >&2
  exit 2
elif [ "$path_name_status" -eq 2 ]; then
  name_check_broken=1
fi

record_name_list_degradation() {
  # BEFORE THE EARLY EXITS, because those writes are degraded too.
  #
  # This warning and receipt used to sit at the bottom of the script, after the binary-extension
  # skip and the empty-content exit. A `.png` write and an empty write therefore ran with known-
  # name protection OFF and left NO record of it — and the receipt exists precisely so that
  # "was known-name protection on for that mutation?" has an answer that does not depend on who
  # was reading stderr. Silence read as "protected"; it meant "not checked, not recorded".
  #
  # An absent list is a durable configuration state, not a transient one: a permanently
  # half-disabled guard looks identical to a working one in any log.
  [ ! -r "$pii_names_file" ] || return 0
  echo "pii-guard: no household name list at $pii_names_file --" \
       "name checks are limited to structural patterns." \
       "Create it (one name per line, outside any repo) to enable them." >&2
  degraded_receipt="${XDG_STATE_HOME:-$HOME/.local/state}/hapax/pii-guard-degraded.jsonl"
  if mkdir -p "$(dirname "$degraded_receipt")" 2>/dev/null; then
    printf '{"at":"%s","degradation":"household_name_list_absent","expected_path":"%s","file":"%s"}\n' \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$pii_names_file" "$file_path" \
      >>"$degraded_receipt" 2>/dev/null || true
  fi
}

record_name_list_degradation

# Skip non-content files (binary, images, etc.) -- AFTER the path has been scanned.
case "$file_path" in
  *.png|*.jpg|*.jpeg|*.gif|*.wav|*.mp3|*.mp4|*.db|*.sqlite) exit 0 ;;
esac

[ -n "$new_content" ] || exit 0

# --- PII Pattern Checks ---
# Each pattern must be HIGH confidence (no false positives on code/docs)

blocked=()

# Operator full name (exact match only)
if echo "$new_content" | grep -qiP 'Ryan\s+Kleeberger'; then
  blocked+=("Operator full name detected")
fi

# Household given names.
#
# This guard protected exactly one name -- the operator's -- for five months while the
# given names of two children, with their ages, sat on the default branch of a PUBLIC
# repository. The guard ran green the whole time because it had no pattern for anyone but
# him. Two checks close that, and they close different holes:
#
#   1. A private name list, read from OUTSIDE the repository. It cannot live in the file:
#      a public guard that hardcodes the names it protects is itself the disclosure.
#   2. A structural age-disclosure pattern that needs no list at all, so a name nobody
#      thought to register is still caught when it appears next to an age.
#
# An absent list is a configuration state, not a violation: warn loudly and keep the
# structural checks rather than wedging every fresh clone. The warning names its remedy.
#
# The list file also carries `!phrase` lines: third-party contexts where a listed name is
# somebody else entirely (an author, a band, a cited paper). Those phrases are stripped
# before the name check, because a guard that blocks a legitimate citation gets switched
# off, and a switched-off guard is how this went unnoticed for five months.
#
# Both the names and the exemptions live in that file rather than here, so this script --
# which is public -- carries no information about who it protects.
#
# EVERY value read from that file is treated as a LITERAL, never as a program. Names go into
# PCRE inside \Q...\E; exemptions are removed by bash pattern substitution with the four glob
# metacharacters escaped. An earlier revision interpolated both raw -- a name or phrase holding
# `/`, `(`, `[` or a quantifier could then error the pattern, and `grep`'s non-zero exit reads
# as "no match", so a malformed list entry SILENTLY disabled the guard. That is the same class
# of failure as the missing pattern this whole check exists to fix, so it is closed the same
# way: literally, and with grep's error exit (>=2) distinguished from its no-match exit (1).
#
# The boundary is `(?<![A-Za-z])name(?![A-Za-z])`, NOT `\b`. Underscore and digits are word
# characters, so `\bname\b` does not match inside `name_surname` -- the exact blindness that let
# an underscored form survive in two contract files and that the commit message documents. A
# guard that reproduces the bug it reports is worse than no guard: it reports coverage it has
# not got.
# The scan itself is `scan_for_registered_names`, defined above the binary-extension skip so
# the FILENAME can be checked before any content-shaped exit. Here it runs over the body.
content_name_status=0
scan_for_registered_names "$new_content" || content_name_status=$?
if [ "$content_name_status" -eq 0 ]; then
  blocked+=("Registered household name detected (see \$HAPAX_PII_NAMES_FILE)")
elif [ "$content_name_status" -eq 2 ]; then
  name_check_broken=1
fi

if [ "$name_check_broken" -eq 1 ]; then
  blocked+=("Household name check ERRORED and was treated as a match -- see remedy below")
fi

# The degradation warning and receipt now fire in `record_name_list_degradation`, called BEFORE
# the binary-extension skip and the empty-content exit. Recording them here left both of those
# writes running degraded with no record — see that function for the reasoning.

# Age disclosure: a capitalised given name followed by a parenthesised 1-2 digit number.
# Four files shipped publicly in exactly that form, naming two children and their ages.
# Name plus age is directly identifying, and this pattern catches it without anyone having
# to register the name first -- which matters, because the registered-name list is the
# thing that was missing. (No example is given here on purpose: a guard in a public repo
# must not quote the disclosure it exists to prevent.)
# The capitalised word before the number is usually a document-structure word, not a person:
# "Appendix (2)", "Chapter (3)", "Table (11)". Those are the overwhelming majority of matches in
# a corpus like this one, and a guard that cries wolf on them gets switched off -- which is
# exactly how the original exposure survived five months. So candidates are extracted first and
# the structure words filtered out, rather than writing one unreadable lookbehind.
#
# This list is a PRECISION measure, not a completeness claim. Its only failure mode is a false
# NEGATIVE, and only for someone named exactly like a document-structure word. That is the right
# direction to be wrong in for a check whose whole value is that it stays switched on.
#
# NOT A PIPELINE INTO `grep -q`. The first revision of this filter read
#   grep -oP '<candidates>' | grep -qvP "$age_structure_words"
# and was FAIL-OPEN above roughly one screen of matches. `set -o pipefail` is in force;
# `grep -q` exits on its first hit, SIGPIPEs the upstream `grep -oP`, and the pipeline status
# becomes 141, which makes the `if` false. Measured at the previous head: `Example (11)` alone
# blocked, and fifty thousand of them passed. A gate whose verdict depends on input VOLUME is
# worse than no gate, because it passes exactly the large mechanical writes most likely to
# carry a disclosure nobody read.
#
# So: capture, then filter with `grep -v` (which consumes all input and never exits early),
# then test the result for emptiness. No early-exiting consumer, no SIGPIPE, no volume
# dependence. `|| true` on each capture because grep exits 1 on no-match under `set -e`.
age_structure_words='^(?:Appendix|Chapter|Section|Figure|Fig|Table|Note|Item|Step|Part|Page|Line|Rule|Case|Tier|Level|Phase|Round|Wave|Slice|Gate|Volume|Version|Revision|Column|Row|Panel|Track|Slot|Tick|Axis|Band|Class|Group|Level|Stage)\b'
age_candidates="$(grep -oP '\b[A-Z][a-z]{2,}\s+\((?:[1-9]|[1-9][0-9])\)' <<<"$new_content" || true)"
if [ -n "$age_candidates" ]; then
  age_hits="$(grep -vP "$age_structure_words" <<<"$age_candidates" || true)"
  if [ -n "$age_hits" ]; then
    blocked+=("Possible age disclosure (Name (NN)) -- use an opaque principal id")
  fi
fi

# The SAME disclosure written in prose. The scrub that added the check above removed every
# `Name (NN)` and still shipped a child's age one line from a renamed file, because the age was
# spelled out instead of parenthesised. An age is identifying on its own once a role is known --
# which is what the surrounding prose always supplies -- so the form does not matter and neither
# does whether a name sits beside it. Bounded 1..19 deliberately: that is the range where the
# subject is a minor, and the range where a false positive on ordinary prose is least likely.
if echo "$new_content" | grep -qP '\b(?:[1-9]|1[0-9])[- ]year[- ]old\b'; then
  blocked+=("Possible age disclosure (N-year-old) -- describe the audience, not the age")
fi

# Location data
if echo "$new_content" | grep -qP 'Minneapolis[- ]St\.?\s*Paul'; then
  blocked+=("Location data (Minneapolis-St. Paul)")
fi

# Home directory absolute paths (reveals username)
if echo "$new_content" | grep -qP '/home/hapax/'; then
  # Allow in infrastructure files that legitimately reference the home directory
  case "$file_path" in
    */.gitignore|*/CLAUDE.md|*/hooks/*|*/.claude/*|*/systemd/*|*/process-compose*|*/scripts/*) ;;
    *) blocked+=("Home directory path (/home/hapax/)") ;;
  esac
fi

# Engine audit / browsing data patterns
if echo "$new_content" | grep -qP 'rag-sources/(chrome|audio)/'; then
  blocked+=("Browsing/audio data path reference")
fi

if [ ${#blocked[@]} -gt 0 ]; then
  echo "BLOCKED: PII detected in content being written to $file_path:" >&2
  for msg in "${blocked[@]}"; do
    echo "  - $msg" >&2
  done
  echo "If this is intentional (e.g., in a gitignored file), add the file to .gitignore first." >&2
  exit 2
fi
