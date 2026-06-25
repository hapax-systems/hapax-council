/// <reference types="vitest" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    watch: {
      ignored: ["**/src-tauri/**"],
    },
  },
  envPrefix: ["VITE_", "TAURI_ENV_*"],
  build: {
    // Drop #30 §5.1: bump Vite transpile target from safari13 to
    // es2022. safari13 was the safe public-web default that forced
    // Vite to transpile ES2020+ syntax down to ES2015-level on every
    // build for Safari compatibility. hapax-logos runs only inside
    // Tauri 2's bundled webkit2gtk (≥2.50), which supports ES2022
    // natively. The transpilation step is dead weight — Vite spent
    // ~5-15% of build time rewriting syntax the runtime already
    // executes unchanged.
    target: "es2022",
    minify: !process.env.TAURI_ENV_DEBUG ? "esbuild" : false,
    sourcemap: !!process.env.TAURI_ENV_DEBUG,
    // Drop #30 §5.2: skip compressed-size reporting. Vite computes
    // gzip + brotli sizes for every emitted chunk to populate the
    // build-summary table printed to stdout. With 7+ chunks
    // (manualChunks vendor-* + automatic route splits), this is
    // 2-5 s of pure reporting overhead per build. The sizes don't
    // affect anything operational; they're just a human-readable
    // report nobody's reading.
    reportCompressedSize: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (/[\\/]node_modules[\\/](react|react-dom|react-router-dom)[\\/]/.test(id)) {
            return "vendor-react";
          }
          if (/[\\/]node_modules[\\/]recharts[\\/]/.test(id)) {
            return "vendor-recharts";
          }
          if (/[\\/]node_modules[\\/]@xyflow[\\/]react[\\/]/.test(id)) {
            return "vendor-xyflow";
          }
          if (/[\\/]node_modules[\\/]hls\.js[\\/]/.test(id)) {
            return "vendor-hls";
          }
          return undefined;
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test-setup.ts",
    globals: true,
  },
});
