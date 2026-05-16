#!/usr/bin/env bash
# compositor-paired-frame-audit.sh — paired pre-FX/final evidence for visual incidents
#
# Captures the 3D scene proof frame and final livestream frame together, then
# writes an absolute-difference image and simple region metrics. This is stricter
# than a single screenshot: it shows whether final effects are perceptually
# present across the full surface or only obvious inside bright source quads.

set -euo pipefail

DEFAULT_PRE_SOURCE="/dev/shm/hapax-imagination/3d-proof/frame.jpg"
DEFAULT_FINAL_SOURCE="/dev/shm/hapax-visual/frame.jpg"
DEFAULT_STATE_SOURCE="/dev/shm/hapax-visual/effect-drift-state.json"
DEFAULT_DURATION_S=3
DEFAULT_INTERVAL_MS=500
OUTPUT_ROOT="${HOME}/.cache/hapax/screenshots/paired-fx-audit"

usage() {
    cat <<'EOF' >&2
usage: compositor-paired-frame-audit.sh <label> [options]

Options:
  --duration SECONDS   total capture window (default: 3)
  --interval-ms MS     snapshot interval inside the window (default: 500)
  --pre-source PATH    pre-FX/proof frame path
  --final-source PATH  final output frame path
  --state-source PATH  effect-state JSON path copied with each sample
  --output-root PATH   output root directory

Writes:
  <output-root>/<label>/<utc>/pre_fx-NN.jpg
  <output-root>/<label>/<utc>/final-NN.jpg
  <output-root>/<label>/<utc>/diff-NN.jpg
  <output-root>/<label>/<utc>/transition_diff-NN.jpg, for NN > 01
  <output-root>/<label>/<utc>/effect_state-NN.json, if readable
  <output-root>/<label>/<utc>/capture_times.tsv
  <output-root>/<label>/<utc>/metrics.tsv
  <output-root>/<label>/<utc>/transition_metrics.tsv
EOF
    exit 2
}

if [[ $# -lt 1 ]]; then
    usage
fi

label="$1"
shift
duration_s="${DEFAULT_DURATION_S}"
interval_ms="${DEFAULT_INTERVAL_MS}"
pre_source="${DEFAULT_PRE_SOURCE}"
final_source="${DEFAULT_FINAL_SOURCE}"
state_source="${DEFAULT_STATE_SOURCE}"
output_root="${OUTPUT_ROOT}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --duration)
            duration_s="$2"
            shift 2
            ;;
        --interval-ms)
            interval_ms="$2"
            shift 2
            ;;
        --pre-source)
            pre_source="$2"
            shift 2
            ;;
        --final-source)
            final_source="$2"
            shift 2
            ;;
        --state-source)
            state_source="$2"
            shift 2
            ;;
        --output-root)
            output_root="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "compositor-paired-frame-audit: unknown argument: $1" >&2
            usage
            ;;
    esac
done

if ! command -v magick >/dev/null 2>&1; then
    echo "compositor-paired-frame-audit: ImageMagick 'magick' is required" >&2
    exit 1
fi

for source in "$pre_source" "$final_source"; do
    if [[ ! -r "$source" ]]; then
        echo "compositor-paired-frame-audit: source frame not readable: $source" >&2
        exit 1
    fi
done

if ! [[ "$duration_s" =~ ^[0-9]+(\.[0-9]+)?$ ]] || ! [[ "$interval_ms" =~ ^[0-9]+$ ]]; then
    echo "compositor-paired-frame-audit: --duration must be a number, --interval-ms an integer" >&2
    exit 2
fi

if (( interval_ms <= 0 )); then
    echo "compositor-paired-frame-audit: --interval-ms must be > 0" >&2
    exit 2
fi

ts_utc="$(date -u +%Y%m%dT%H%M%SZ)"
out_dir="${output_root}/${label}/${ts_utc}"
mkdir -p "$out_dir"

frame_count="$(awk -v d="$duration_s" -v i="$interval_ms" 'BEGIN { n = int((d * 1000) / i); if (n < 1) n = 1; print n }')"
sleep_s="$(awk -v i="$interval_ms" 'BEGIN { printf "%.3f", i / 1000.0 }')"
metrics="${out_dir}/metrics.tsv"
transition_metrics="${out_dir}/transition_metrics.tsv"
capture_times="${out_dir}/capture_times.tsv"

printf 'sample\tscope\tdiff_mean\tdiff_max\tdiff_sd\tpre_mean\tfinal_mean\n' >"$metrics"
printf 'sample\tscope\tfinal_delta_mean\tfinal_delta_max\tfinal_delta_sd\tprev_final_mean\tfinal_mean\n' >"$transition_metrics"
printf 'sample\tcaptured_at_utc\n' >"$capture_times"

metric_triplet() {
    local image="$1"
    magick "$image" -colorspace Gray -format '%[fx:mean] %[fx:maxima] %[fx:standard_deviation]' info:
}

image_mean() {
    local image="$1"
    magick "$image" -format '%[fx:mean]' info:
}

append_scope_metrics() {
    local sample="$1"
    local scope="$2"
    local diff_image="$3"
    local pre_image="$4"
    local final_image="$5"
    local crop="${6:-}"
    local tmp_dir="$out_dir/.tmp"
    mkdir -p "$tmp_dir"

    local diff_for_stats="$diff_image"
    local pre_for_stats="$pre_image"
    local final_for_stats="$final_image"
    if [[ -n "$crop" ]]; then
        diff_for_stats="${tmp_dir}/diff-${sample}-${scope}.png"
        pre_for_stats="${tmp_dir}/pre-${sample}-${scope}.png"
        final_for_stats="${tmp_dir}/final-${sample}-${scope}.png"
        magick "$diff_image" -crop "$crop" +repage "$diff_for_stats"
        magick "$pre_image" -crop "$crop" +repage "$pre_for_stats"
        magick "$final_image" -crop "$crop" +repage "$final_for_stats"
    fi

    local diff_mean diff_max diff_sd pre_mean final_mean
    read -r diff_mean diff_max diff_sd <<<"$(metric_triplet "$diff_for_stats")"
    pre_mean="$(image_mean "$pre_for_stats")"
    final_mean="$(image_mean "$final_for_stats")"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$sample" "$scope" "$diff_mean" "$diff_max" "$diff_sd" "$pre_mean" "$final_mean" >>"$metrics"
}

append_transition_metrics() {
    local sample="$1"
    local scope="$2"
    local transition_image="$3"
    local prev_final_image="$4"
    local final_image="$5"
    local crop="${6:-}"
    local tmp_dir="$out_dir/.tmp"
    mkdir -p "$tmp_dir"

    local transition_for_stats="$transition_image"
    local prev_for_stats="$prev_final_image"
    local final_for_stats="$final_image"
    if [[ -n "$crop" ]]; then
        transition_for_stats="${tmp_dir}/transition-${sample}-${scope}.png"
        prev_for_stats="${tmp_dir}/prev-final-${sample}-${scope}.png"
        final_for_stats="${tmp_dir}/transition-final-${sample}-${scope}.png"
        magick "$transition_image" -crop "$crop" +repage "$transition_for_stats"
        magick "$prev_final_image" -crop "$crop" +repage "$prev_for_stats"
        magick "$final_image" -crop "$crop" +repage "$final_for_stats"
    fi

    local delta_mean delta_max delta_sd prev_mean final_mean
    read -r delta_mean delta_max delta_sd <<<"$(metric_triplet "$transition_for_stats")"
    prev_mean="$(image_mean "$prev_for_stats")"
    final_mean="$(image_mean "$final_for_stats")"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$sample" "$scope" "$delta_mean" "$delta_max" "$delta_sd" "$prev_mean" "$final_mean" >>"$transition_metrics"
}

for ((n = 1; n <= frame_count; n++)); do
    sample="$(printf '%02d' "$n")"
    pre_frame="${out_dir}/pre_fx-${sample}.jpg"
    final_frame="${out_dir}/final-${sample}.jpg"
    state_frame="${out_dir}/effect_state-${sample}.json"

    cp -f "$pre_source" "$pre_frame"
    cp -f "$final_source" "$final_frame"
    if [[ -r "$state_source" ]]; then
        cp -f "$state_source" "$state_frame"
    fi
    printf '%s\t%s\n' "$sample" "$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" >>"$capture_times"

    if (( n < frame_count )); then
        sleep "$sleep_s"
    fi
done

previous_final_frame=""

for ((n = 1; n <= frame_count; n++)); do
    sample="$(printf '%02d' "$n")"
    pre_frame="${out_dir}/pre_fx-${sample}.jpg"
    final_frame="${out_dir}/final-${sample}.jpg"
    diff_frame="${out_dir}/diff-${sample}.jpg"
    transition_frame="${out_dir}/transition_diff-${sample}.jpg"

    magick "$pre_frame" "$final_frame" -compose difference -composite "$diff_frame"

    append_scope_metrics "$sample" "global" "$diff_frame" "$pre_frame" "$final_frame"
    append_scope_metrics "$sample" "left_top" "$diff_frame" "$pre_frame" "$final_frame" "640x360+0+0"
    append_scope_metrics "$sample" "right_top" "$diff_frame" "$pre_frame" "$final_frame" "640x360+640+0"
    append_scope_metrics "$sample" "left_bottom" "$diff_frame" "$pre_frame" "$final_frame" "640x360+0+360"
    append_scope_metrics "$sample" "right_bottom" "$diff_frame" "$pre_frame" "$final_frame" "640x360+640+360"
    append_scope_metrics "$sample" "center" "$diff_frame" "$pre_frame" "$final_frame" "426x240+427+240"

    if [[ -n "$previous_final_frame" ]]; then
        magick "$previous_final_frame" "$final_frame" -compose difference -composite "$transition_frame"
        append_transition_metrics "$sample" "global" "$transition_frame" "$previous_final_frame" "$final_frame"
        append_transition_metrics "$sample" "left_top" "$transition_frame" "$previous_final_frame" "$final_frame" "640x360+0+0"
        append_transition_metrics "$sample" "right_top" "$transition_frame" "$previous_final_frame" "$final_frame" "640x360+640+0"
        append_transition_metrics "$sample" "left_bottom" "$transition_frame" "$previous_final_frame" "$final_frame" "640x360+0+360"
        append_transition_metrics "$sample" "right_bottom" "$transition_frame" "$previous_final_frame" "$final_frame" "640x360+640+360"
        append_transition_metrics "$sample" "center" "$transition_frame" "$previous_final_frame" "$final_frame" "426x240+427+240"
    fi
    previous_final_frame="$final_frame"
done

rm -rf "${out_dir}/.tmp"

cat >"${out_dir}/README.md" <<EOF
# Paired Compositor Frame Audit

- label: \`${label}\`
- captured_at_utc: \`${ts_utc}\`
- duration: ${duration_s}s
- interval_ms: ${interval_ms}
- pre_source: \`${pre_source}\`
- final_source: \`${final_source}\`
- state_source: \`${state_source}\`
- capture_times: \`${capture_times}\`
- metrics: \`${metrics}\`
- transition_metrics: \`${transition_metrics}\`

Each sample contains a pre-FX proof frame, final output frame, and absolute
difference image. Use the region rows in \`metrics.tsv\` to catch effects that
are mathematically global but perceptually visible only in selected regions.

\`transition_metrics.tsv\` compares each final frame with the previous final
frame. Use it to catch hard cuts, sudden whole-frame pumping, and effect-chain
reload discontinuities.
EOF

echo "compositor-paired-frame-audit: ${frame_count} paired sample(s) → ${out_dir}" >&2
echo "  pre:   ${pre_source}" >&2
echo "  final: ${final_source}" >&2
echo "  state: ${state_source}" >&2

cat <<EOF

### paired compositor evidence — \`${label}\`

| artifact | path |
|---|---|
| directory | \`${out_dir}\` |
| capture_times | \`${capture_times}\` |
| metrics | \`${metrics}\` |
| transition_metrics | \`${transition_metrics}\` |
| readme | \`${out_dir}/README.md\` |

_Captured ${ts_utc} over ${duration_s}s @ ${interval_ms}ms intervals._
EOF
