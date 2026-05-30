#!/usr/bin/env bash
# screwm-meet-camera.sh — OUTBOUND: pipe the live Screwm render into a
# v4l2 loopback so Chrome/Meet can select Screwm itself as the camera.
#
# Mechanism (zero-interference, proven 2026-05-30): a PARALLEL second
# x11grab off the SAME running Xvfb :82 that already feeds /dev/video52
# (DarkPlaces). This does NOT touch the render, OBS, the compositor, or
# any PipeWire/broadcast audio. Teardown is just stopping the ffmpeg.
#
#   Xvfb :82  --x11grab-->  /dev/video52  (DarkPlaces; OBS holds exclusive)
#             \-x11grab-->  /dev/video50  (YouTube0; THIS -- Chrome/Meet camera)
#
# Audio stays entirely inside Chrome's own device pickers (operator mic +
# a non-broadcast sink). We never reload v4l2loopback and never pw-link.
#
# Verbs:
#   run        exec ffmpeg in the foreground (for the systemd unit)
#   start      launch ffmpeg in the background, tracked by a pidfile (manual/CLI)
#   stop       stop the background grab
#   status     report whether the grab is live and who holds the sink
#   preflight  verify Xvfb :82 is alive and the sink is free (ExecStartPre)
set -euo pipefail

DISPLAY_NUM="${SCREWM_MEET_DISPLAY:-:82}"
SINK_DEV="${SCREWM_MEET_SINK:-/dev/video50}"   # YouTube0 -- reserved for Chrome sharing
GRAB_SIZE="${SCREWM_MEET_GRAB_SIZE:-1920x1080}"
OUT_SIZE="${SCREWM_MEET_OUT_SIZE:-1280x720}"
FPS="${SCREWM_MEET_FPS:-30}"
PIDFILE="${XDG_RUNTIME_DIR:-/tmp}/hapax-screwm-meet-camera.pid"

log() { printf '[screwm-meet-camera] %s\n' "$*" >&2; }

xvfb_alive() {
  # Prefer a real X round-trip; fall back to a process check if xdpyinfo is absent.
  if command -v xdpyinfo >/dev/null 2>&1; then
    xdpyinfo -display "$DISPLAY_NUM" >/dev/null 2>&1
  else
    pgrep -f "Xvfb ${DISPLAY_NUM}([^0-9]|$)" >/dev/null 2>&1
  fi
}

# fuser exits non-zero when the device is free; swallow it so the empty
# result doesn't trip `set -e`/`pipefail` at the call site.
sink_holder() { fuser "$SINK_DEV" 2>/dev/null | tr -s ' ' || true; }

preflight() {
  if ! xvfb_alive; then
    log "ERROR: Xvfb $DISPLAY_NUM is not answering -- start the Screwm render first"
    log "  (systemctl --user start hapax-darkplaces-v4l2)"
    return 1
  fi
  if [[ ! -e "$SINK_DEV" ]]; then
    log "ERROR: $SINK_DEV does not exist (v4l2loopback YouTube0 missing)"
    return 1
  fi
  local holder; holder="$(sink_holder)"
  if [[ -n "$holder" ]]; then
    log "ERROR: $SINK_DEV already has an opener (pids:$holder) -- refusing to fight it"
    return 1
  fi
  log "preflight OK -- Xvfb $DISPLAY_NUM alive, $SINK_DEV free"
}

run_ffmpeg() {
  # YUYV is what browsers expect from a webcam; v4l2loopback passes it through.
  exec ffmpeg -hide_banner -loglevel warning \
    -f x11grab -video_size "$GRAB_SIZE" -framerate "$FPS" -i "${DISPLAY_NUM}.0+0,0" \
    -vf "format=yuyv422,scale=${OUT_SIZE/x/:}" \
    -f v4l2 "$SINK_DEV"
}

is_running() {
  [[ -f "$PIDFILE" ]] || return 1
  local pid; pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

cmd_run() {
  preflight
  log "grabbing $DISPLAY_NUM ($GRAB_SIZE) -> $SINK_DEV ($OUT_SIZE @ ${FPS}fps, YUYV)"
  run_ffmpeg
}

cmd_start() {
  if is_running; then log "already running (pid $(cat "$PIDFILE"))"; return 0; fi
  preflight
  log "starting background grab -> $SINK_DEV"
  ( run_ffmpeg ) >/dev/null 2>&1 &
  echo $! > "$PIDFILE"
  sleep 1
  if is_running; then
    log "live (pid $(cat "$PIDFILE")) -- select camera 'YouTube0' in Chrome/Meet"
  else
    log "ERROR: grab failed to stay up; check that $DISPLAY_NUM is rendering"
    rm -f "$PIDFILE"
    return 1
  fi
}

cmd_stop() {
  if ! is_running; then log "not running"; rm -f "$PIDFILE"; return 0; fi
  local pid; pid="$(cat "$PIDFILE")"
  log "stopping grab (pid $pid)"
  kill "$pid" 2>/dev/null || true
  sleep 1
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$PIDFILE"
  log "stopped -- fallback: select the normal BRIO camera in Chrome/Meet"
}

cmd_status() {
  if is_running; then
    log "RUNNING (pid $(cat "$PIDFILE")) grabbing $DISPLAY_NUM -> $SINK_DEV"
  else
    log "stopped"
  fi
  local holder; holder="$(sink_holder)"
  log "$SINK_DEV opener(s):${holder:- none}"
}

case "${1:-status}" in
  run)       cmd_run ;;
  start)     cmd_start ;;
  stop)      cmd_stop ;;
  status)    cmd_status ;;
  preflight) preflight ;;
  *) log "usage: $0 {run|start|stop|status|preflight}"; exit 2 ;;
esac
