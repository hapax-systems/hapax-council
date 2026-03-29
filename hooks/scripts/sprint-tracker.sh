#!/usr/bin/env bash
# sprint-tracker.sh — PostToolUse hook for R&D sprint measure completion detection.
#
# Fires after Bash, Write, Edit tool calls. Matches output files against
# active measure output_files patterns to detect completion signals.
# Writes signals to /dev/shm/hapax-sprint/completed.jsonl for the
# sprint_tracker agent to consume.

set -euo pipefail

INPUT="$(cat)"
TOOL="$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)"
[ -z "$TOOL" ] && exit 0

SHM_DIR="/dev/shm/hapax-sprint"
COMPLETED="$SHM_DIR/completed.jsonl"
STATE="$SHM_DIR/state.json"
MEASURES_DIR="$HOME/Documents/Personal/20 Projects/hapax-research/sprint/measures"

# Only process relevant tools
case "$TOOL" in
    Bash|Write|Edit) ;;
    *) exit 0 ;;
esac

# Ensure shm dir exists
mkdir -p "$SHM_DIR"

# Check if measures directory exists (sprint engine bootstrapped?)
[ -d "$MEASURES_DIR" ] || exit 0

# Extract the file path(s) touched by this tool call
TOUCHED_FILES=""

case "$TOOL" in
    Write|Edit)
        FILE_PATH="$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)"
        [ -n "$FILE_PATH" ] && TOUCHED_FILES="$FILE_PATH"
        ;;
    Bash)
        CMD="$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)"
        OUTPUT="$(echo "$INPUT" | jq -r '.tool_output // empty' 2>/dev/null)"

        # git commit: extract committed files from output
        if echo "$CMD" | grep -qE '^\s*git\s+commit'; then
            # Output typically includes file list
            TOUCHED_FILES="$(echo "$OUTPUT" | grep -oP '(?:create mode|modify|delete) \d+ (.+)' | awk '{print $NF}' || true)"
            if [ -z "$TOUCHED_FILES" ]; then
                # Try simpler pattern from short commit output
                TOUCHED_FILES="$(echo "$OUTPUT" | grep -oP '\d+ files? changed' || true)"
            fi
        fi

        # Check for research doc creation
        if echo "$OUTPUT" | grep -qP 'docs/research/.*\.md'; then
            DOC_PATHS="$(echo "$OUTPUT" | grep -oP 'docs/research/[^\s"]+\.md' || true)"
            TOUCHED_FILES="$TOUCHED_FILES $DOC_PATHS"
        fi
        ;;
esac

[ -z "$TOUCHED_FILES" ] && exit 0

# Match touched files against measure output_files patterns
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

for measure_file in "$MEASURES_DIR"/*.md; do
    [ -f "$measure_file" ] || continue

    # Extract frontmatter fields with awk (avoid yaml dependency)
    MEASURE_ID="$(awk '/^---$/{n++; next} n==1 && /^id:/{gsub(/["'"'"' ]/, "", $2); print $2; exit}' "$measure_file")"
    STATUS="$(awk '/^---$/{n++; next} n==1 && /^status:/{print $2; exit}' "$measure_file")"

    # Validate extraction
    [ -z "$MEASURE_ID" ] && continue

    # Only match pending or in_progress measures
    case "$STATUS" in
        pending|in_progress) ;;
        *) continue ;;
    esac

    # Read output_files and output_docs lists from frontmatter.
    # State: 0=scanning, 1=in output_files, 2=in output_docs
    SECTION=0
    while IFS= read -r line; do
        # Frontmatter boundary resets state
        [ "$line" = "---" ] && { SECTION=0; continue; }

        # Detect section starts (takes priority over list-item check)
        case "$line" in
            output_files:*) SECTION=1; continue ;;
            output_docs:*)  SECTION=2; continue ;;
        esac

        # If inside a list section, process items or detect end
        if [ "$SECTION" -gt 0 ]; then
            if echo "$line" | grep -qP '^\s*-\s+'; then
                PATTERN="$(echo "$line" | sed 's/^\s*-\s*//' | tr -d '"')"
                [ "$PATTERN" = "null" ] && continue
                [ -z "$PATTERN" ] && continue

                for touched in $TOUCHED_FILES; do
                    if echo "$touched" | grep -qF "$PATTERN" 2>/dev/null; then
                        SIGNAL="{\"measure_id\":\"$MEASURE_ID\",\"timestamp\":\"$NOW\",\"trigger\":\"$TOOL\",\"files\":[\"$touched\"]}"
                        echo "$SIGNAL" >> "$COMPLETED"
                        echo "Sprint: measure $MEASURE_ID matched ($touched)" >&2
                        break 2  # One signal per tool call
                    fi
                done
            elif echo "$line" | grep -qP '^[a-zA-Z_]'; then
                # New YAML key started (letter/underscore, not dash) — exit list
                SECTION=0
            fi
        fi
    done < "$measure_file"
done

exit 0
