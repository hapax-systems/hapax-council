/**
 * Runtime URL configuration for browser-mandated HTTP endpoints.
 *
 * These URLs cannot go through Tauri IPC because they're consumed by
 * browser APIs (<img src>, <video poster>, hls.js) that require URLs.
 */

/** Logos API base — used for img.src, HLS, and batch snapshot polling. */
export const LOGOS_API_URL =
  import.meta.env.VITE_LOGOS_API_URL || "http://127.0.0.1:8051/api";

/** Visual frame server — Axum HTTP server inside Tauri process. */
export const FRAME_SERVER_URL =
  import.meta.env.VITE_FRAME_SERVER_URL || "http://127.0.0.1:8053";
