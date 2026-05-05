---
date: 2026-05-03
updated: 2026-05-05
author: cx-blue (Codex)
audience: operator + council maintainers
register: engineering / feasibility-spike
status: research + prototype
task_id: jr-tauri-comeback-slint-feasibility-spike
related:
  - experiments/slint-logos-spike/
  - docs/research/2026-04-20-tauri-decommission-freed-resources.md
  - gemini-jr-team packet 20260502T214425Z-jr-currentness-scout-tauri-3-release-status-2026-05-02
---

# Slint Logos Feasibility Spike

## Decision

Slint is a credible comeback path for a small Logos control surface only
when the launcher pins `SLINT_BACKEND=winit-software`.

That configuration measured below the task gate on this workstation:

| Mode | RSS after warmup | Idle CPU | First visible window | Fetch proof | Verdict |
|---|---:|---:|---:|---|---|
| `SLINT_BACKEND=winit-software` | 26,320 kB (25.7 MB) | 0.968 % of one core over 3.099 s | 78.0 ms Hyprland map / 60 ms Slint event-loop proxy | `HEALTH_FETCH_STATUS=200 OK BODY_BYTES=187` | Pass |
| default backend selector | 99,236 kB (96.9 MB) | 0.000 % over 3.019 s | 653 ms Slint event-loop proxy | `HEALTH_FETCH_STATUS=200 OK BODY_BYTES=187` | Fails RSS gate |

The pass is therefore backend-specific. Do not generalize it to a full
Slint migration without preserving the backend pin and remeasuring once
real widgets, streams, and command surfaces are present.

## Prototype

The spike lives at `experiments/slint-logos-spike/` and is a standalone
Cargo binary:

- Slint `1.16.1` for the window and declarative UI.
- `reqwest` `0.13.3` with default features disabled. The prototype hits
  plain localhost HTTP only and intentionally avoids TLS dependency
  weight.
- `tokio` `1.52.2` with `rt`, `time`, and `net` for the reqwest path.
- A single screen renders `http://127.0.0.1:8051/api/health` by default.

The implementation follows the current Slint Rust docs pattern:
`build.rs` runs `slint_build::compile(...)`, Rust includes generated UI
modules with `slint::include_modules!()`, and the app runs an
`AppWindow`. Context7 was used on 2026-05-05 to verify current Slint,
Tauri, and reqwest documentation before selecting the crate versions and
HTTP pattern.

## Baseline

The task note names `hapax-logos/DECOMMISSIONED.md`, but that file is
not present in this worktree. The equivalent in-repo decommission
baseline is `docs/research/2026-04-20-tauri-decommission-freed-resources.md`.

The relevant Tauri shell envelope from that decommission note:

| Resource | Tauri shell baseline |
|---|---:|
| Process CPU | about 60 % of one core |
| Process GPU | about 5-10 % |
| Process RSS | about 629 MB |
| Vite/dev server when active | about 150 MB |
| cgroup ceiling | 4 GB |

The JR packet from 2026-05-02 also found no public Tauri 3 release
roadmap and characterized the likely Linux path as GTK4/WebKitGTK 6.0
while still retaining a webview architecture. Current Tauri 2 Linux docs
still require WebKitGTK system packages. That makes Tauri a poor fit for
the original resource-reclaim goal even if Tauri 3 eventually reduces
some GTK overhead.

## Measurement

Environment:

- `rustc 1.94.0`
- `cargo 1.94.0`
- `WAYLAND_DISPLAY=wayland-1`, `DISPLAY=:0`
- Logos health endpoint reachable at `http://127.0.0.1:8051/api/health`

Release build:

```bash
cargo build --release --manifest-path experiments/slint-logos-spike/Cargo.toml
```

Software-backend measurement:

```bash
SLINT_BACKEND=winit-software \
LOGOS_API_URL=http://127.0.0.1:8051/api/health \
experiments/slint-logos-spike/target/release/slint-logos-spike
```

Observed output:

```text
TTFP_PROXY_MS=58
HEALTH_FETCH_STATUS=200 OK BODY_BYTES=187
```

Idle sample after a 2-second warmup:

```text
rss_warm_kb  rss_after_kb  idle_cpu_pct_one_core  interval_s
26320        26320         0.968                  3.099
```

Hyprland window-map probe:

```text
HYPRLAND_WINDOW_MAPPED_MS=78.0
TTFP_PROXY_MS=60
HEALTH_FETCH_STATUS=200 OK BODY_BYTES=187
```

Default-backend comparison:

```text
rss_warm_kb  rss_after_kb  idle_cpu_pct_one_core  interval_s
99268        99236         0.000                  3.019

TTFP_PROXY_MS=653
HEALTH_FETCH_STATUS=200 OK BODY_BYTES=187
```

`TTFP_PROXY_MS` is an application-side proxy, not a graphics-driver
paint callback. The Hyprland map probe is the stronger "visible to the
compositor" measurement for this spike.

## Recommendation

Proceed with a narrow Slint migration path for a read-only or
low-interaction Logos control surface. Do not resurrect the old Tauri
shell and do not move camera or compositor preview back into a UI
process.

Roadmap:

1. Keep the current Tauri shell decommissioned. Treat Slint as a new
   native control client, not a port of the WebKit/React preview path.
2. Ship a launcher or future systemd user unit with
   `SLINT_BACKEND=winit-software` pinned, then remeasure on every
   feature tranche.
3. Start with read-only health, orientation, and lightweight status
   panels served from existing `logos-api` JSON endpoints.
4. Add commands as explicit HTTP calls against existing Logos API
   surfaces. Avoid rebuilding the old Tauri IPC registry.
5. Add streams only after the static panels remain under 30 MB RSS and
   1 % idle CPU. Prefer bounded polling first; use SSE only for surfaces
   that actually need liveness.
6. Keep preview video out of the Slint client. The decommission
   recommendation remains `mpv` or OBS/v4l2 for visual preview.
7. Before any production adoption, run a 10-minute idle sample and an
   active operator-flow sample while studio-compositor, Reverie,
   daimonion, and streaming are live.

Fallbacks if the software backend becomes unacceptable:

- Native GTK4 is the strongest fallback when the surface needs desktop
  integration and can tolerate a somewhat larger but already-resident
  toolkit stack.
- `egui` is viable only for custom controls with repaint strictly
  throttled to input/data changes. Do not accept a continuous redraw loop
  on the livestream workstation.
