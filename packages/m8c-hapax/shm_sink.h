/* shm_sink.h — opaque interface for the SHM RGBA + sidecar bridges.
 *
 * Display bridge (the original purpose):
 *   shm_sink_init()      — open the SHM file, ensure the directory.
 *                          Call once after main_texture exists.
 *   shm_sink_publish()   — read main_texture into a buffer + write to
 *                          the SHM file + atomically update sidecar.
 *                          Call after every successful SDL_RenderPresent.
 *   shm_sink_shutdown()  — close the file (also unlinks the sidecar
 *                          JSON files for buttons + info so consumers
 *                          can detect M8 disconnection by file absence).
 *
 * Sidecar bridges (added 2026-05-02 for M8 capability expansion):
 *   shm_sink_publish_buttons() — write 0xFB joypad-keypressed-state to
 *                                /dev/shm/hapax-sources/m8-buttons.json
 *                                (M8 perception: operator-engagement signal)
 *   shm_sink_publish_info()    — write 0xFF system_info to
 *                                /dev/shm/hapax-sources/m8-info.json
 *                                (cockpit: firmware drift surface)
 *   shm_sink_publish_oscilloscope() — write 0xFC waveform samples to
 *                                /dev/shm/hapax-sources/m8-osc.bin
 *                                (audience-scale Cairo ward + zero-latency
 *                                M8-amplitude perception backend)
 *
 * If USE_SHM_SINK is not defined at build time, all calls are silent
 * no-ops (compiled into the stock m8c binary harmlessly).
 *
 * Output format matches the studio compositor's external_rgba source
 * pattern (same shape as Reverie):
 *   /dev/shm/hapax-sources/m8-display.rgba       — raw 320x240 BGRA bytes
 *   /dev/shm/hapax-sources/m8-display.rgba.json  — sidecar metadata
 *   /dev/shm/hapax-sources/m8-buttons.json       — operator button state
 *   /dev/shm/hapax-sources/m8-info.json          — M8 hardware + firmware
 *   /dev/shm/hapax-sources/m8-osc.bin            — oscilloscope waveform ring
 */

#ifndef HAPAX_M8C_SHM_SINK_H
#define HAPAX_M8C_SHM_SINK_H

#include <stdint.h>

int shm_sink_init(void);
void shm_sink_publish(void *renderer, void *texture);
void shm_sink_publish_buttons(uint8_t mask, uint8_t indicator);
void shm_sink_publish_info(uint8_t hardware_id,
                           uint8_t major,
                           uint8_t minor,
                           uint8_t patch,
                           uint8_t font_mode);
void shm_sink_publish_oscilloscope(uint8_t color,
                                   const uint8_t *samples,
                                   uint16_t sample_count);
void shm_sink_shutdown(void);

#endif /* HAPAX_M8C_SHM_SINK_H */
