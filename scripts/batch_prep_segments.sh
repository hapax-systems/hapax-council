#!/usr/bin/env bash
# batch_prep_segments.sh - run segment prep in small Command-R-only batches.
#
# This wrapper never restarts TabbyAPI and never changes the loaded model.
# It fails closed unless TabbyAPI is already serving the resident prep model.

set -euo pipefail

ACCEPTED_LIMIT="${1:-0}"
BATCH_SIZE="${HAPAX_SEGMENT_PREP_BATCH_SIZE:-3}"
QUALITY_FIRST="${HAPAX_SEGMENT_PREP_QUALITY_FIRST:-1}"
PREP_BUDGET_S="${HAPAX_SEGMENT_PREP_BUDGET_S:-3600}"
TABBY_CHAT_URL="${HAPAX_TABBY_URL:-http://localhost:5000/v1/chat/completions}"
TABBY_MODEL_URL="${TABBY_CHAT_URL%/chat/completions}/model"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${HAPAX_SEGMENT_PREP_PROJECT_DIR:-$(cd -- "${SCRIPT_DIR}/.." && pwd)}"
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

count_existing() {
    if [[ -f "$PREP_DIR/manifest.json" ]]; then
        (
            cd "$PROJECT_DIR"
            HAPAX_SEGMENT_PREP_MODEL="${RESIDENT_PREP_MODEL}" \
            uv run python -c 'import sys; from pathlib import Path; from agents.hapax_daimonion.daily_segment_prep import load_prepped_programmes; print(len(load_prepped_programmes(Path(sys.argv[1]))))' "$PREP_BASE"
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
if [[ "$ACCEPTED_LIMIT" -gt 0 ]]; then
    echo "Optional accepted cap: ${ACCEPTED_LIMIT} segments"
else
    echo "Accepted cap: none (budget-first)"
fi
echo "Batch size: ${BATCH_SIZE}"
echo "Budget: ${PREP_BUDGET_S}s"
echo "Quality-first: ${QUALITY_FIRST}"
echo "Model: ${RESIDENT_PREP_MODEL}"
echo "Existing: $(count_existing) segments"
echo ""

verify_resident_model

(
    cd "$PROJECT_DIR"
    uv run python -c 'from pathlib import Path; import agents.hapax_daimonion.daily_segment_prep as prep; root=Path.cwd().resolve(); path=Path(prep.__file__).resolve(); assert root in path.parents, f"daily_segment_prep imported from {path}, expected under {root}"; print(f"[ok] prep module: {path}")'
)

accepted="$(count_existing)"
batch=0
max_failures=3
failures=0
started_at="$(date +%s)"

while true; do
    now="$(date +%s)"
    elapsed=$((now - started_at))
    if [[ "$elapsed" -ge "$PREP_BUDGET_S" ]]; then
        echo "[budget] prep window exhausted after ${elapsed}s"
        break
    fi
    if [[ "$ACCEPTED_LIMIT" -gt 0 && "$accepted" -ge "$ACCEPTED_LIMIT" ]]; then
        echo "[cap] accepted segment cap reached (${accepted}/${ACCEPTED_LIMIT})"
        break
    fi
    if [[ "$QUALITY_FIRST" != "1" && "$failures" -ge "$max_failures" ]]; then
        break
    fi

    batch=$((batch + 1))
    if [[ "$ACCEPTED_LIMIT" -gt 0 ]]; then
        remaining=$((ACCEPTED_LIMIT - accepted))
        this_batch=$((remaining < BATCH_SIZE ? remaining : BATCH_SIZE))
    else
        this_batch="$BATCH_SIZE"
    fi

    echo ""
    if [[ "$ACCEPTED_LIMIT" -gt 0 ]]; then
        echo "[batch ${batch}] Trying up to ${this_batch} candidates (accepted ${accepted}/${ACCEPTED_LIMIT}, elapsed ${elapsed}s)..."
    else
        echo "[batch ${batch}] Trying up to ${this_batch} candidates (accepted ${accepted}, elapsed ${elapsed}s)..."
    fi
    verify_resident_model

    cd "$PROJECT_DIR"
    HAPAX_SEGMENT_PREP_MAX="$this_batch" \
    HAPAX_SEGMENT_PREP_SEQUENTIAL_BEATS="${HAPAX_SEGMENT_PREP_SEQUENTIAL_BEATS:-1}" \
    HAPAX_SEGMENT_PREP_BUDGET_S="${PREP_BUDGET_S}" \
    HAPAX_SEGMENT_PREP_DIR="${PREP_BASE}" \
    HAPAX_TABBY_URL="${TABBY_CHAT_URL}" \
    HAPAX_SEGMENT_PREP_MODEL="${RESIDENT_PREP_MODEL}" \
    uv run python -m agents.hapax_daimonion.daily_segment_prep --prep-dir "${PREP_BASE}"

    verify_resident_model

    new_accepted_count="$(count_existing)"
    new_accepted_this_batch=$((new_accepted_count - accepted))
    echo "[batch ${batch}] Accepted ${new_accepted_this_batch} new segments (total on disk: ${new_accepted_count})"

    if [[ "$new_accepted_this_batch" -eq 0 ]]; then
        failures=$((failures + 1))
        if [[ "$QUALITY_FIRST" == "1" ]]; then
            echo "[batch ${batch}] No accepted segments; continuing until budget expires"
        else
            echo "[batch ${batch}] No new segments - failure ${failures}/${max_failures}"
        fi
    else
        failures=0
    fi

    accepted="$new_accepted_count"
done

echo ""
if [[ "$ACCEPTED_LIMIT" -gt 0 ]]; then
    echo "=== DONE: ${accepted}/${ACCEPTED_LIMIT} accepted segments before optional cap in ${PREP_DIR} ==="
else
    echo "=== DONE: ${accepted} accepted segments in ${PREP_DIR} ==="
fi
list_existing
