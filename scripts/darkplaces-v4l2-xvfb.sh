#!/usr/bin/env bash
# Run DarkPlaces headlessly under Xvfb and publish frames to v4l2loopback.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/darkplaces-runtime-guard.sh
source "$REPO_DIR/scripts/darkplaces-runtime-guard.sh"

DEVICE="${HAPAX_DARKPLACES_V4L2_DEVICE:-${DARKPLACES_V4L2_DEVICE:-/dev/video52}}"
V4L2_ENABLE="${HAPAX_DARKPLACES_V4L2_ENABLE:-1}"
WIDTH="${DARKPLACES_WIDTH:-1920}"
HEIGHT="${DARKPLACES_HEIGHT:-1080}"
FPS="${DARKPLACES_FPS:-60}"
DISPLAY_NUM="${HAPAX_DARKPLACES_DISPLAY:-:82}"
PORT="${DARKPLACES_PORT:-26001}"
JOY_INDEX="${HAPAX_DARKPLACES_JOY_INDEX:-1}"
DARKPLACES_BIN="${HAPAX_DARKPLACES_BIN:-}"
PROBE_ONLY=0

usage() {
    cat <<'EOF'
Usage: scripts/darkplaces-v4l2-xvfb.sh [--probe-only]

Starts an Xvfb display, validates the DarkPlaces GL renderer on that display,
then launches DarkPlaces and x11grab -> v4l2. This fallback avoids root Xorg
and desktop DRM hotplug churn. It is not the GPU-pinned production route.

Set HAPAX_DARKPLACES_V4L2_ENABLE=0 to run only the DarkPlaces renderer on Xvfb.
This is the OBS-media path: OBS consumes the display through
hapax-darkplaces-obs-media-stream.service, and a broken v4l2 producer must not
kill the renderer.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --probe-only)
            PROBE_ONLY=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "darkplaces-v4l2-xvfb: unknown argument: $1" >&2
            usage >&2
            exit 64
            ;;
    esac
    shift
done

need_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "darkplaces-v4l2-xvfb: missing required command: $1" >&2
        exit 69
    fi
}

resolve_darkplaces_bin() {
    if [ -n "$DARKPLACES_BIN" ]; then
        printf '%s\n' "$DARKPLACES_BIN"
        return
    fi
    "$REPO_DIR/scripts/ensure-darkplaces-live-texture-build.sh"
}

DARKPLACES_BIN="$(resolve_darkplaces_bin)"

need_cmd Xvfb
need_cmd "$DARKPLACES_BIN"
if [ "$V4L2_ENABLE" = "1" ]; then
    need_cmd gst-launch-1.0
    need_cmd v4l2-ctl
fi
if [ -n "${NOTIFY_SOCKET:-}" ]; then
    need_cmd systemd-notify
fi

if [ "$PROBE_ONLY" -ne 1 ] && [ "$V4L2_ENABLE" = "1" ] && [ ! -e "$DEVICE" ]; then
    echo "DarkPlaces v4l2loopback device not found: $DEVICE" >&2
    exit 1
fi

xvfb_pid=""
darkplaces_pid=""
producer_pid=""
watchdog_pid=""

notify_systemd() {
    if [ -n "${NOTIFY_SOCKET:-}" ] && command -v systemd-notify >/dev/null 2>&1; then
        systemd-notify "$@" >/dev/null 2>&1 || true
    fi
}

start_systemd_watchdog() {
    if [ -z "${NOTIFY_SOCKET:-}" ] || ! command -v systemd-notify >/dev/null 2>&1; then
        return
    fi
    (
        while true; do
            sleep "${HAPAX_DARKPLACES_WATCHDOG_INTERVAL_SECONDS:-10}"
            producer_ok=1
            if [ "$V4L2_ENABLE" = "1" ]; then
                producer_ok=0
                if [ -n "$producer_pid" ] && kill -0 "$producer_pid" 2>/dev/null; then
                    producer_ok=1
                fi
            fi
            if [ -n "$darkplaces_pid" ] && kill -0 "$darkplaces_pid" 2>/dev/null &&
                [ "$producer_ok" = "1" ]; then
                if [ "$V4L2_ENABLE" = "1" ]; then
                    status="DarkPlaces v4l2 feed alive: ${DISPLAY_NUM}.0 -> ${DEVICE}"
                else
                    status="DarkPlaces renderer alive: ${DISPLAY_NUM}.0 (v4l2 disabled)"
                fi
                systemd-notify \
                    "WATCHDOG=1" \
                    "STATUS=$status" \
                    >/dev/null 2>&1 || true
            else
                break
            fi
        done
    ) &
    watchdog_pid="$!"
}

cleanup() {
    for pid in "$watchdog_pid" "$producer_pid" "$darkplaces_pid" "$xvfb_pid"; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
}
trap cleanup EXIT INT TERM

Xvfb "$DISPLAY_NUM" -screen 0 "${WIDTH}x${HEIGHT}x24" -nolisten tcp -s 0 -dpms &
xvfb_pid="$!"
sleep 1

if [ -z "${HAPAX_DARKPLACES_EXPECTED_GL_RENDERER:-}" ] &&
    [ -z "${HAPAX_DARKPLACES_EXPECTED_GPU_INDEX:-}" ]; then
    export HAPAX_DARKPLACES_EXPECTED_GPU_INDEX=0
fi
DISPLAY="$DISPLAY_NUM" "$REPO_DIR/scripts/darkplaces-gl-preflight.sh"

if [ "$PROBE_ONLY" -eq 1 ]; then
    echo "darkplaces-v4l2-xvfb: probe-only complete" >&2
    exit 0
fi

"$REPO_DIR/scripts/install-darkplaces-screwm-assets.sh"

DISPLAY="$DISPLAY_NUM" SDL_VIDEODRIVER=x11 "$DARKPLACES_BIN" \
    -nosound \
    -game screwm \
    -window \
    -width "$WIDTH" \
    -height "$HEIGHT" \
    +map screwm \
    +port "$PORT" \
    +crosshair 0 \
    +r_drawviewmodel 0 \
    +viewsize 120 \
    +scr_viewsize 120 \
    +cl_bob 0 \
    +scr_centertime 0 \
    +scr_sbaralpha 0 \
    +sbar_alpha_bg 0 \
    +sbar_alpha_fg 0 \
    +sbar_hudselector 0 \
    +sbar_x 10000 \
    +sbar_y 10000 \
    +scr_infobar_height 0 \
    +scr_infobartime_off 0 \
    +scr_showbrand 0 \
    +sv_cheats 1 \
    +gl_texturemode GL_NEAREST \
    +r_fog 1 \
    +cl_maxfps "$FPS" \
    +showfps 0 \
    +cl_showfps 0 \
    +cl_showtime 0 \
    +cl_showdate 0 \
    +cl_showspeed 0 \
    +cl_shownet 0 \
    +scr_showturtle 0 \
    +joy_enable 1 \
    +joy_index "$JOY_INDEX" \
    +joy_axisforward 1 \
    +joy_axisside 0 \
    +joy_axisyaw 3 \
    +joy_axispitch 4 \
    +joy_axisup -1 \
    +joy_sensitivityforward -1 \
    +joy_sensitivityside 1 \
    +joy_sensitivityyaw 1.15 \
    +joy_sensitivitypitch 0.90 \
    +joy_deadzoneforward 0.12 \
    +joy_deadzoneside 0.12 \
    +joy_deadzoneyaw 0.14 \
    +joy_deadzonepitch 0.14 \
    +cl_forwardspeed 360 \
    +cl_backspeed 360 \
    +cl_sidespeed 360 \
    +cl_upspeed 240 \
    +hapax_live_texture_enable 1 \
    +hapax_live_texture_name progs/aoa_sphere.mdl_0 \
    +hapax_live_texture_path /dev/shm/hapax-compositor/quake-live-yt.bgra \
    +hapax_live_texture_width 2048 \
    +hapax_live_texture_height 1024 \
    +hapax_live_texture2_enable 1 \
    +hapax_live_texture2_name cam_bop \
    +hapax_live_texture2_path /dev/shm/hapax-compositor/quake-live-cam-brio-operator.bgra \
    +hapax_live_texture2_width 1280 \
    +hapax_live_texture2_height 720 \
    +hapax_live_texture3_enable 1 \
    +hapax_live_texture3_name cam_brm \
    +hapax_live_texture3_path /dev/shm/hapax-compositor/quake-live-cam-brio-room.bgra \
    +hapax_live_texture3_width 1280 \
    +hapax_live_texture3_height 720 \
    +hapax_live_texture4_enable 1 \
    +hapax_live_texture4_name cam_bsy \
    +hapax_live_texture4_path /dev/shm/hapax-compositor/quake-live-cam-brio-synths.bgra \
    +hapax_live_texture4_width 1280 \
    +hapax_live_texture4_height 720 \
    +hapax_live_texture5_enable 1 \
    +hapax_live_texture5_name cam_cdk \
    +hapax_live_texture5_path /dev/shm/hapax-compositor/quake-live-cam-c920-desk.bgra \
    +hapax_live_texture5_width 1280 \
    +hapax_live_texture5_height 720 \
    +hapax_live_texture6_enable 1 \
    +hapax_live_texture6_name cam_crm \
    +hapax_live_texture6_path /dev/shm/hapax-compositor/quake-live-cam-c920-room.bgra \
    +hapax_live_texture6_width 1280 \
    +hapax_live_texture6_height 720 \
    +hapax_live_texture7_enable 1 \
    +hapax_live_texture7_name cam_cov \
    +hapax_live_texture7_path /dev/shm/hapax-compositor/quake-live-cam-c920-overhead.bgra \
    +hapax_live_texture7_width 1280 \
    +hapax_live_texture7_height 720 \
    +hapax_live_texture8_enable 1 \
    +hapax_live_texture8_name ward_atlas \
    +hapax_live_texture8_path /dev/shm/hapax-compositor/quake-live-ward-atlas.bgra \
    +hapax_live_texture8_width 2048 \
    +hapax_live_texture8_height 2304 \
    +hapax_live_texture9_enable 1 \
    +hapax_live_texture9_name w09 \
    +hapax_live_texture9_path /dev/shm/hapax-compositor/quake-live-ticker-grounding.bgra \
    +hapax_live_texture9_width 1344 \
    +hapax_live_texture9_height 176 \
    +hapax_live_texture10_enable 1 \
    +hapax_live_texture10_name w22 \
    +hapax_live_texture10_path /dev/shm/hapax-compositor/quake-live-ticker-precedent.bgra \
    +hapax_live_texture10_width 1344 \
    +hapax_live_texture10_height 176 \
    +hapax_live_texture11_enable 1 \
    +hapax_live_texture11_name w27 \
    +hapax_live_texture11_path /dev/shm/hapax-compositor/quake-live-ticker-chronicle.bgra \
    +hapax_live_texture11_width 1344 \
    +hapax_live_texture11_height 176 \
    +hapax_live_texture12_enable 1 \
    +hapax_live_texture12_name w05 \
    +hapax_live_texture12_path /dev/shm/hapax-compositor/quake-live-reverie.bgra \
    +hapax_live_texture12_width 960 \
    +hapax_live_texture12_height 540 \
    +hapax_live_texture13_enable 1 \
    +hapax_live_texture13_name speech_wave \
    +hapax_live_texture13_path /dev/shm/hapax-compositor/quake-live-speech-wave.bgra \
    +hapax_live_texture13_width 512 \
    +hapax_live_texture13_height 128 \
    +hapax_live_texture14_enable 1 \
    +hapax_live_texture14_name progs/aoa.mdl_0 \
    +hapax_live_texture14_path /dev/shm/hapax-compositor/quake-live-aoa-atlas.bgra \
    +hapax_live_texture14_width 2048 \
    +hapax_live_texture14_height 2048 \
    +hapax_live_texture15_enable 1 \
    +hapax_live_texture15_name w18 \
    +hapax_live_texture15_path /dev/shm/hapax-compositor/quake-live-ir-brio-operator.bgra \
    +hapax_live_texture15_width 340 \
    +hapax_live_texture15_height 340 \
    +hapax_live_texture16_enable 1 \
    +hapax_live_texture16_name w19 \
    +hapax_live_texture16_path /dev/shm/hapax-compositor/quake-live-ir-brio-room.bgra \
    +hapax_live_texture16_width 340 \
    +hapax_live_texture16_height 340 \
    +hapax_live_texture17_enable 1 \
    +hapax_live_texture17_name w35 \
    +hapax_live_texture17_path /dev/shm/hapax-compositor/quake-live-ir-brio-synths.bgra \
    +hapax_live_texture17_width 340 \
    +hapax_live_texture17_height 340 \
    +r_glsl_postprocess 0 \
    +r_glsl_postprocess_ruttetra_enable 0 \
    +r_glsl_postprocess_uservec1 "0 0 0 0" \
    +r_glsl_postprocess_uservec2 "0 0 0 0" \
    +r_glsl_postprocess_uservec3 "0 0 0 0" \
    +r_glsl_postprocess_uservec4 "0 0 0 0" \
    +set screwm_qc_screen_postprocess 1 &
darkplaces_pid="$!"

sleep 3

if [ "$V4L2_ENABLE" = "1" ]; then
    v4l2-ctl -d "$DEVICE" --set-fmt-video="width=${WIDTH},height=${HEIGHT},pixelformat=YUYV" \
        >/dev/null 2>&1 || true
    v4l2-ctl -d "$DEVICE" --set-parm="$FPS" >/dev/null 2>&1 || true

    gst-launch-1.0 -q \
        ximagesrc display-name="$DISPLAY_NUM" use-damage=0 show-pointer=false \
        ! "video/x-raw,framerate=${FPS}/1,width=${WIDTH},height=${HEIGHT}" \
        ! videoconvert \
        ! "video/x-raw,format=YUY2" \
        ! v4l2sink device="$DEVICE" sync=false &
    producer_pid="$!"

    notify_systemd --ready --status="DarkPlaces v4l2 feed running: ${DISPLAY_NUM}.0 -> ${DEVICE}"
else
    notify_systemd --ready --status="DarkPlaces renderer running: ${DISPLAY_NUM}.0 (v4l2 disabled)"
fi
start_systemd_watchdog

if [ "$V4L2_ENABLE" = "1" ]; then
    wait -n "$darkplaces_pid" "$producer_pid"
else
    wait "$darkplaces_pid"
fi
