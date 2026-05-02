/* shm_sink.c — write SDL_RenderReadPixels output to a /dev/shm RGBA file.
 *
 * Carry-fork patch for laamaa/m8c. Hooks into render.c so every frame
 * the M8 LCD draws (320x240 ARGB) is published to the studio
 * compositor's external_rgba source pattern (same shape as Reverie):
 *
 *   /dev/shm/hapax-sources/m8-display.rgba       — raw BGRA frame bytes
 *   /dev/shm/hapax-sources/m8-display.rgba.json  — sidecar metadata
 *                                                   {"frame_id":N,"w":320,"h":240,"stride":1280}
 *
 * Compositor side: ShmRgbaReader at agents/studio_compositor/shm_rgba_reader.py
 * cycles on sidecar frame_id changes.
 *
 * Build with -DUSE_SHM_SINK; otherwise this file no-ops via the
 * function-stubs guard below.
 *
 * Constitutional binders:
 *   - feedback_l12_equals_livestream_invariant (vacuous; no L-12 contact)
 *   - never drop operator speech (no audio path)
 *   - anti-anthropomorphization (instrument LCD, not personified)
 *
 * Why a separate file (not inline in render.c): keeps the patch
 * surface small enough to rebase trivially when upstream m8c moves.
 */

#include "shm_sink.h"

#ifdef USE_SHM_SINK

#include <SDL3/SDL.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

/* M8 LCD native resolution (pre-window-scaling). main_texture in
 * render.c is created at this exact size. */
#define SHM_SINK_WIDTH 320
#define SHM_SINK_HEIGHT 240
#define SHM_SINK_BYTES_PER_PIXEL 4 /* BGRA on little-endian (SDL ARGB8888) */
#define SHM_SINK_STRIDE (SHM_SINK_WIDTH * SHM_SINK_BYTES_PER_PIXEL)
#define SHM_SINK_FRAME_BYTES (SHM_SINK_STRIDE * SHM_SINK_HEIGHT)
#define SHM_SINK_DEFAULT_DIR "/dev/shm/hapax-sources"
#define SHM_SINK_DEFAULT_PATH SHM_SINK_DEFAULT_DIR "/m8-display.rgba"

static int sink_fd = -1;
static char sink_path[256];
static char sidecar_path[260];
static char sidecar_tmp_path[268];
static uint64_t frame_id;
static uint8_t sink_buffer[SHM_SINK_FRAME_BYTES];

static const char *resolve_path(void) {
  const char *override = getenv("M8C_SHM_SINK_PATH");
  return (override && override[0] != '\0') ? override : SHM_SINK_DEFAULT_PATH;
}

int shm_sink_init(void) {
  if (sink_fd >= 0) {
    return 1; /* already open */
  }

  /* Ensure parent dir exists. /dev/shm is tmpfs so mkdir is cheap. */
  mkdir(SHM_SINK_DEFAULT_DIR, 0755);

  const char *path = resolve_path();
  size_t pathlen = strlen(path);
  if (pathlen + 5 >= sizeof(sidecar_path)) {
    SDL_LogWarn(SDL_LOG_CATEGORY_APPLICATION,
                "shm_sink: configured path too long; bridge disabled");
    return 0;
  }
  snprintf(sink_path, sizeof(sink_path), "%s", path);
  snprintf(sidecar_path, sizeof(sidecar_path), "%s.json", path);
  snprintf(sidecar_tmp_path, sizeof(sidecar_tmp_path), "%s.json.tmp", path);

  sink_fd = open(sink_path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
  if (sink_fd < 0) {
    SDL_LogWarn(SDL_LOG_CATEGORY_APPLICATION,
                "shm_sink: open(%s) failed (errno=%d)", sink_path, errno);
    return 0;
  }

  /* Pre-size the file so consumers see a well-formed buffer on first
   * open even before the first frame writes. */
  if (ftruncate(sink_fd, SHM_SINK_FRAME_BYTES) < 0) {
    SDL_LogWarn(SDL_LOG_CATEGORY_APPLICATION,
                "shm_sink: ftruncate failed (errno=%d); proceeding anyway",
                errno);
  }

  frame_id = 0;
  SDL_Log("shm_sink: publishing 320x240 BGRA frames to %s", sink_path);
  return 1;
}

static void write_sidecar(void) {
  /* Atomic update via tmp + rename so consumers never see a torn
   * sidecar during write. */
  FILE *f = fopen(sidecar_tmp_path, "w");
  if (!f) {
    return;
  }
  fprintf(f,
          "{\"frame_id\":%llu,\"w\":%d,\"h\":%d,\"stride\":%d}\n",
          (unsigned long long)frame_id,
          SHM_SINK_WIDTH,
          SHM_SINK_HEIGHT,
          SHM_SINK_STRIDE);
  fclose(f);
  rename(sidecar_tmp_path, sidecar_path);
}

void shm_sink_publish(void *renderer, void *texture) {
  if (sink_fd < 0) {
    return; /* not initialised, or init failed; render hot path is no-op */
  }

  SDL_Renderer *rend = (SDL_Renderer *)renderer;
  SDL_Texture *tex = (SDL_Texture *)texture;

  SDL_Texture *previous_target = SDL_GetRenderTarget(rend);
  if (!SDL_SetRenderTarget(rend, tex)) {
    return; /* couldn't bind target; skip this frame */
  }

  SDL_Rect rect = {.x = 0, .y = 0, .w = SHM_SINK_WIDTH, .h = SHM_SINK_HEIGHT};
  SDL_Surface *surface = SDL_RenderReadPixels(rend, &rect);
  /* Restore caller's render target before any early return. */
  SDL_SetRenderTarget(rend, previous_target);
  if (!surface) {
    return;
  }

  if (surface->pitch == SHM_SINK_STRIDE) {
    memcpy(sink_buffer, surface->pixels, SHM_SINK_FRAME_BYTES);
  } else {
    /* Pitch-mismatch path: copy row-by-row. */
    const uint8_t *src = (const uint8_t *)surface->pixels;
    for (int y = 0; y < SHM_SINK_HEIGHT; y++) {
      memcpy(&sink_buffer[y * SHM_SINK_STRIDE],
             &src[y * surface->pitch],
             SHM_SINK_STRIDE);
    }
  }
  SDL_DestroySurface(surface);

  /* Seek to start + write the whole buffer. Consumers tolerate a
   * partial-write race because they look at the sidecar frame_id to
   * detect new frames; readers that beat the sidecar update will
   * just see the previous frame. */
  if (lseek(sink_fd, 0, SEEK_SET) < 0) {
    return;
  }
  ssize_t written = write(sink_fd, sink_buffer, SHM_SINK_FRAME_BYTES);
  if (written != SHM_SINK_FRAME_BYTES) {
    SDL_LogWarn(SDL_LOG_CATEGORY_APPLICATION,
                "shm_sink: short write (%zd/%d, errno=%d); dropping frame",
                written, SHM_SINK_FRAME_BYTES, errno);
    return;
  }

  frame_id++;
  write_sidecar();
}

/* Hardware id → human-readable model name (m8c command.c lookup table). */
static const char *hardware_name_for(uint8_t hardware_id) {
  switch (hardware_id) {
  case 0:
    return "Headless";
  case 1:
    return "Beta M8";
  case 2:
    return "Production M8";
  case 3:
    return "Production M8 Model:02";
  default:
    return "Unknown";
  }
}

/* Atomic JSON sidecar write helper. tmp + rename so consumers always
 * see a complete document. */
static void write_json_sidecar(const char *path, const char *json_body) {
  char tmp_path[280];
  int written = snprintf(tmp_path, sizeof(tmp_path), "%s.tmp", path);
  if (written <= 0 || (size_t)written >= sizeof(tmp_path)) {
    return;
  }
  FILE *fp = fopen(tmp_path, "w");
  if (!fp) {
    return;
  }
  fputs(json_body, fp);
  fclose(fp);
  rename(tmp_path, path);
}

/* ISO-8601 UTC timestamp into out (assumed >= 25 bytes). */
static void iso8601_now(char *out, size_t out_size) {
  time_t now = time(NULL);
  struct tm tm_utc;
  gmtime_r(&now, &tm_utc);
  strftime(out, out_size, "%Y-%m-%dT%H:%M:%SZ", &tm_utc);
}

void shm_sink_publish_buttons(uint8_t mask, uint8_t indicator) {
  /* M8 0xFB joypad-keypressed-state — operator-engagement signal.
   * Spec: agents/hapax_daimonion/backends/m8_buttons.py ingests this. */
  mkdir(SHM_SINK_DEFAULT_DIR, 0755);
  char ts[32];
  iso8601_now(ts, sizeof(ts));
  char body[256];
  int n = snprintf(body, sizeof(body),
                   "{\"mask\":%u,\"indicator\":%u,\"ts\":\"%s\"}\n",
                   (unsigned)mask, (unsigned)indicator, ts);
  if (n <= 0 || (size_t)n >= sizeof(body)) {
    return;
  }
  write_json_sidecar(SHM_SINK_DEFAULT_DIR "/m8-buttons.json", body);
}

void shm_sink_publish_info(uint8_t hardware_id,
                           uint8_t major,
                           uint8_t minor,
                           uint8_t patch,
                           uint8_t font_mode) {
  /* M8 0xFF system_info — cockpit firmware-drift surface.
   * Consumed by agents/health_monitor/checks/m8_firmware.py. */
  mkdir(SHM_SINK_DEFAULT_DIR, 0755);
  char ts[32];
  iso8601_now(ts, sizeof(ts));
  char body[384];
  int n = snprintf(body, sizeof(body),
                   "{\"hardware_id\":%u,\"hardware_name\":\"%s\","
                   "\"firmware\":\"%u.%u.%u\",\"font_mode\":%u,"
                   "\"ts\":\"%s\"}\n",
                   (unsigned)hardware_id, hardware_name_for(hardware_id),
                   (unsigned)major, (unsigned)minor, (unsigned)patch,
                   (unsigned)font_mode, ts);
  if (n <= 0 || (size_t)n >= sizeof(body)) {
    return;
  }
  write_json_sidecar(SHM_SINK_DEFAULT_DIR "/m8-info.json", body);
}

void shm_sink_shutdown(void) {
  if (sink_fd >= 0) {
    close(sink_fd);
    sink_fd = -1;
  }
  /* Unlink sidecar JSONs so consumers detect M8 disconnect by file
   * absence (see m8_buttons.py + m8_firmware.py). The display .rgba
   * file is intentionally NOT unlinked — its mtime is the disconnect
   * signal there, matching the existing Reverie external_rgba
   * pattern. */
  unlink(SHM_SINK_DEFAULT_DIR "/m8-buttons.json");
  unlink(SHM_SINK_DEFAULT_DIR "/m8-info.json");
}

#else /* !USE_SHM_SINK */

int shm_sink_init(void) { return 0; }
void shm_sink_publish(void *renderer, void *texture) {
  (void)renderer;
  (void)texture;
}
void shm_sink_publish_buttons(uint8_t mask, uint8_t indicator) {
  (void)mask;
  (void)indicator;
}
void shm_sink_publish_info(uint8_t hardware_id,
                           uint8_t major,
                           uint8_t minor,
                           uint8_t patch,
                           uint8_t font_mode) {
  (void)hardware_id;
  (void)major;
  (void)minor;
  (void)patch;
  (void)font_mode;
}
void shm_sink_shutdown(void) {}

#endif /* USE_SHM_SINK */
