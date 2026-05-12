#!/usr/bin/env bash
# batch_prep_segments.sh - run segment prep in small Command-R-only batches.
#
# This wrapper never restarts TabbyAPI and never changes the loaded model.
# It fails closed unless TabbyAPI is already serving the resident prep model.

set -euo pipefail

TOTAL="${1:-10}"
BATCH_SIZE="${HAPAX_SEGMENT_PREP_BATCH_SIZE:-3}"
TABBY_CHAT_URL="${HAPAX_TABBY_URL:-http://localhost:5000/v1/chat/completions}"
TABBY_MODEL_URL="${TABBY_CHAT_URL%/chat/completions}/model"
PROJECT_DIR="/home/hapax/projects/hapax-council"
PREP_BASE="${HAPAX_SEGMENT_PREP_DIR:-${HOME}/.cache/hapax/segment-prep}"
PREP_DIR="${PREP_BASE}/$(date +%Y-%m-%d)"
RESIDENT_PREP_MODEL="command-r-08-2024-exl3-5.0bpw"
EXPECTED_MODEL="${HAPAX_SEGMENT_PREP_MODEL:-$RESIDENT_PREP_MODEL}"

if [[ "$EXPECTED_MODEL" != "$RESIDENT_PREP_MODEL" ]]; then
    echo "[fatal] segment prep requires ${RESIDENT_PREP_MODEL}; got ${EXPECTED_MODEL}" >&2
    exit 2
fi

loaded_model() {
    curl -fsS "$TABBY_MODEL_URL" \
        --connect-timeout 3 \
        --max-time 10 | \
        python3 -c 'import json,sys; data=json.load(sys.stdin); print(data.get("id") or data.get("model_name") or "")'
}

verify_resident_model() {
    local current
    current="$(loaded_model || true)"
    if [[ "$current" != "$RESIDENT_PREP_MODEL" ]]; then
        echo "[fatal] TabbyAPI must already be serving ${RESIDENT_PREP_MODEL}; current=${current:-unknown}" >&2
        exit 3
    fi
}

check_prep_authority() {
    (
        cd "$PROJECT_DIR"
        uv run python -m shared.segment_prep_pause --check --activity pool_generation
    )
}

check_next_nine_canary() {
    if [[ "$TOTAL" -le 1 ]]; then
        return 0
    fi
    (
        cd "$PROJECT_DIR"
        uv run python -c 'from shared.segment_iteration_review import assert_next_nine_canary_ready; assert_next_nine_canary_ready()'
    )
}

count_existing() {
    if [[ -f "$PREP_DIR/manifest.json" ]]; then
        (
            cd "$PROJECT_DIR"
            HAPAX_SEGMENT_PREP_MODEL="${RESIDENT_PREP_MODEL}" \
            uv run python -c 'import sys; from pathlib import Path; from agents.hapax_daimonion.daily_segment_prep import load_prepped_programmes; print(len(load_prepped_programmes(Path(sys.argv[1]), require_selected=False)))' "$PREP_BASE"
        )
    else
        echo 0
    fi
}

list_existing() {
    if [[ -f "$PREP_DIR/manifest.json" ]]; then
        python3 -c 'import json,sys; from pathlib import Path; p=Path(sys.argv[1])/"manifest.json"; data=json.loads(p.read_text()); print("\n".join(data.get("programmes") or []))' "$PREP_DIR"
    else
        echo "No accepted segments found"
    fi
}

echo "=== Batch Segment Prep ==="
echo "Target: ${TOTAL} segments"
echo "Batch size: ${BATCH_SIZE}"
echo "Model: ${RESIDENT_PREP_MODEL}"
echo "Existing: $(count_existing) segments"
echo ""

if ! check_prep_authority; then
    echo "[fatal] segment prep authority gate blocked pool_generation" >&2
    exit 4
fi
if ! check_next_nine_canary; then
    echo "[fatal] next-nine generation requires a passing one-segment canary review receipt" >&2
    exit 5
fi
verify_resident_model

generated="$(count_existing)"
batch=0
max_failures=3
failures=0

while [[ "$generated" -lt "$TOTAL" && "$failures" -lt "$max_failures" ]]; do
    batch=$((batch + 1))
    remaining=$((TOTAL - generated))
    this_batch=$((remaining < BATCH_SIZE ? remaining : BATCH_SIZE))

    echo ""
    echo "[batch ${batch}] Generating ${this_batch} more segments (have ${generated}/${TOTAL})..."
    if ! check_prep_authority; then
        echo "[fatal] segment prep authority gate blocked pool_generation" >&2
        exit 4
    fi
    if ! check_next_nine_canary; then
        echo "[fatal] next-nine generation requires a passing one-segment canary review receipt" >&2
        exit 5
    fi
    verify_resident_model

    cd "$PROJECT_DIR"
    HAPAX_SEGMENT_PREP_MAX="$this_batch" \
    HAPAX_SEGMENT_PREP_BUDGET_S="${HAPAX_SEGMENT_PREP_BUDGET_S:-1800}" \
    HAPAX_SEGMENT_PREP_DIR="${PREP_BASE}" \
    HAPAX_TABBY_URL="${TABBY_CHAT_URL}" \
    HAPAX_SEGMENT_PREP_MODEL="${RESIDENT_PREP_MODEL}" \
    uv run python -m agents.hapax_daimonion.daily_segment_prep --prep-dir "${PREP_BASE}"

    verify_resident_model

    new_count="$(count_existing)"
    new_this_batch=$((new_count - generated))
    echo "[batch ${batch}] Generated ${new_this_batch} new segments (total on disk: ${new_count})"

    if [[ "$new_this_batch" -eq 0 ]]; then
        failures=$((failures + 1))
        echo "[batch ${batch}] No new segments - failure ${failures}/${max_failures}"
    else
        failures=0
    fi

    generated="$new_count"
done

echo ""
echo "=== DONE: ${generated} segments in ${PREP_DIR} ==="
list_existing
