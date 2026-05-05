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

/* Oscilloscope ring file layout (binary, little-endian, fixed 484 bytes):
 *   bytes  0..7   uint64 frame_id    — monotonically increasing per packet
 *   byte   8      uint8  color       — M8's sender-supplied waveform color
 *                                      (Hapax-side renderer ignores; ward uses
 *                                      palette tokens, not M8 color)
 *   byte   9      uint8  reserved    — pad to 10-byte header
 *   bytes 10..11  uint16 sample_count (LE) — number of valid sample bytes
 *                                            in [12 .. 12+sample_count)
 *   bytes 12..491 uint8[480] samples  — waveform samples, 0..count-1 valid;
 *                                       remainder is stale (consumer must
 *                                       respect sample_count).
 *
 * Total: 492 bytes. M8 0xFC packet caps at 480 samples; we round the
 * file to a fixed 492-byte size so consumers can mmap or read(492) without
 * branching on a variable-length payload. */
#define SHM_SINK_OSC_PATH SHM_SINK_DEFAULT_DIR "/m8-osc.bin"
#define SHM_SINK_OSC_TMP_PATH SHM_SINK_DEFAULT_DIR "/m8-osc.bin.tmp"
#define SHM_SINK_OSC_HEADER_SIZE 12
#define SHM_SINK_OSC_MAX_SAMPLES 480
#define SHM_SINK_OSC_FILE_SIZE (SHM_SINK_OSC_HEADER_SIZE + SHM_SINK_OSC_MAX_SAMPLES)

static int osc_fd = -1;
static uint64_t osc_frame_id;
static uint8_t osc_buffer[SHM_SINK_OSC_FILE_SIZE];

static void osc_open_lazy(void) {
  if (osc_fd >= 0) {
    return;
  }
  mkdir(SHM_SINK_DEFAULT_DIR, 0755);
  osc_fd = open(SHM_SINK_OSC_PATH, O_WRONLY | O_CREAT | O_TRUNC, 0644);
  if (osc_fd < 0) {
    return;
  }
  if (ftruncate(osc_fd, SHM_SINK_OSC_FILE_SIZE) < 0) {
    /* Non-fatal — pre-sized for first read but write loop below still works. */
  }
  osc_frame_id = 0;
}

void shm_sink_publish_oscilloscope(uint8_t color,
                                   const uint8_t *samples,
                                   uint16_t sample_count) {
  /* M8 0xFC oscilloscope packet — color byte + up to 480 8-bit waveform
   * samples per packet at the M8's draw rate (~60 Hz). Fixed-size ring
   * file so the audience-scale Cairo ward + perception amplitude backend
   * can mmap/read without branching on variable-length payloads.
   *
   * Lazy-open avoids creating an empty file on builds where the ward is
   * never recruited; first 0xFC packet seen triggers init. */
  osc_open_lazy();
  if (osc_fd < 0) {
    return;
  }
  if (sample_count > SHM_SINK_OSC_MAX_SAMPLES) {
    sample_count = SHM_SINK_OSC_MAX_SAMPLES;
  }

  osc_frame_id++;
  /* Header (little-endian by repo convention; same as the m8-display
   * sidecar JSON shape). */
  for (int i = 0; i < 8; i++) {
    osc_buffer[i] = (uint8_t)((osc_frame_id >> (i * 8)) & 0xFF);
  }
  osc_buffer[8] = color;
  osc_buffer[9] = 0; /* reserved */
  osc_buffer[10] = (uint8_t)(sample_count & 0xFF);
  osc_buffer[11] = (uint8_t)((sample_count >> 8) & 0xFF);
  if (sample_count > 0 && samples != NULL) {
    memcpy(&osc_buffer[SHM_SINK_OSC_HEADER_SIZE], samples, sample_count);
  }
  /* Zero the unused tail so a consumer that ignores sample_count and
   * reads the whole buffer does not see stale samples from the previous
   * frame's longer payload. */
  if (sample_count < SHM_SINK_OSC_MAX_SAMPLES) {
    memset(&osc_buffer[SHM_SINK_OSC_HEADER_SIZE + sample_count], 0,
           SHM_SINK_OSC_MAX_SAMPLES - sample_count);
  }

  if (lseek(osc_fd, 0, SEEK_SET) < 0) {
    return;
  }
  ssize_t written = write(osc_fd, osc_buffer, SHM_SINK_OSC_FILE_SIZE);
  if (written != SHM_SINK_OSC_FILE_SIZE) {
    /* Same posture as the display path: partial write is rare, dropping
     * one frame is fine because the next 0xFC packet (~16 ms) will rewrite. */
    return;
  }
}

void shm_sink_shutdown(void) {
  if (sink_fd >= 0) {
    close(sink_fd);
    sink_fd = -1;
  }
  if (osc_fd >= 0) {
    close(osc_fd);
    osc_fd = -1;
  }
  /* Unlink sidecar JSONs so consumers detect M8 disconnect by file
   * absence (see m8_buttons.py + m8_firmware.py). The display .rgba
   * file is intentionally NOT unlinked — its mtime is the disconnect
   * signal there, matching the existing Reverie external_rgba
   * pattern. The oscilloscope ring's mtime serves the same role for
   * the ward's silence-detection (>1 s no update → fade). */
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
void shm_sink_publish_oscilloscope(uint8_t color,
                                   const uint8_t *samples,
                                   uint16_t sample_count) {
  (void)color;
  (void)samples;
  (void)sample_count;
}
void shm_sink_shutdown(void) {}

#endif /* USE_SHM_SINK */
