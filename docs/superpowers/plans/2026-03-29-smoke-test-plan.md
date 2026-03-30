# End-to-End Smoke Test Plan — Hapax Logos + Reverie

> Run after any major deployment. Takes ~15 minutes. Checks every subsystem.
> 52 tests across 8 phases covering infrastructure, rendering, cameras, UI, anatomy, DMN, peripherals, and build.

## Prerequisites

All services running:
```bash
for s in hapax-imagination hapax-daimonion hapax-dmn studio-compositor visual-layer-aggregator logos-api; do
    printf "%-30s %s\n" "$s" "$(systemctl --user is-active $s.service 2>/dev/null)"
done
```

---

## Phase 1: Infrastructure (7 tests)

- [ ] **1.1 API health** — `curl -s http://localhost:8051/api/health | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['overall_status'], d['healthy'])"` → healthy/degraded, count > 0
- [ ] **1.2 GPU** — `nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader` → used < 80% of total
- [ ] **1.3 Stimmung** — `python3 -c "import json; d=json.load(open('/dev/shm/hapax-stimmung/state.json')); print(d['overall_stance'])"` → nominal/cautious/degraded
- [ ] **1.4 Docker** — `docker ps --format '{{.Names}}' | wc -l` → ≥ 10
- [ ] **1.5 LiteLLM** — `curl -s http://localhost:4000/health/liveliness` → "I'm alive!"
- [ ] **1.6 Build version** — `~/.local/bin/hapax-imagination --version` → SHA + timestamp
- [ ] **1.7 Working mode** — `cat ~/.cache/hapax/working-mode` → "research" or "rnd"

## Phase 2: Reverie Visual Surface (9 tests)

- [ ] **2.1 Frame timing** — `journalctl --user -u hapax-imagination.service -n 1 --no-pager | grep frame_time` → < 50ms
- [ ] **2.2 SHM frame fresh** — `echo $(($(date +%s) - $(stat -c %Y /dev/shm/hapax-visual/frame.jpg)))` → < 3s
- [ ] **2.3 Frame not half-black** — `stat -c %s /dev/shm/hapax-visual/frame.jpg` → > 30000 bytes
- [ ] **2.4 Preset switch** — `uv run python scripts/write_test_plan.py thermal_preset && sleep 4` → `journalctl --user -u hapax-imagination -n 3 | grep loaded`
- [ ] **2.5 Hot-reload** — `uv run python scripts/write_test_plan.py ambient && sleep 3` → "loaded N passes" in journal
- [ ] **2.6 Pipeline plan** — `python3 -c "import json; print(len(json.load(open('/dev/shm/hapax-imagination/pipeline/plan.json'))['passes']))"` → ≥ 4
- [ ] **2.7 Content textures** — `ls /dev/shm/hapax-imagination/content/active/ 2>/dev/null` → slots.json exists
- [ ] **2.8 UDS socket** — `ls /run/user/1000/hapax-imagination.sock` → exists
- [ ] **2.9 Uniforms** — `cat /dev/shm/hapax-imagination/pipeline/uniforms.json` → non-empty JSON

## Phase 3: Camera & Studio (7 tests)

- [ ] **3.1 Compositor active** — `systemctl --user is-active studio-compositor.service` → active
- [ ] **3.2 Snapshots fresh** — `for f in /dev/shm/hapax-compositor/c920-*.jpg; do echo "$(basename $f): $(($(date +%s) - $(stat -c %Y $f)))s"; done` → all < 5s
- [ ] **3.3 Batch API** — `curl -s -o /dev/null -w "%{http_code} %{size_download}" "http://localhost:8051/api/studio/stream/cameras/batch?roles=c920-desk"` → 200, > 50000
- [ ] **3.4 HLS available** — `curl -s http://localhost:8051/api/studio/stream/info | python3 -c "import json,sys; print(json.load(sys.stdin)['hls_enabled'])"` → true
- [ ] **3.5 Active cameras** — `python3 -c "import json; d=json.load(open('$HOME/.cache/hapax-compositor/status.json')); print(f'active={d[\"active_cameras\"]}')"` → ≥ 2
- [ ] **3.6 Presets** — `curl -s http://localhost:8051/api/studio/presets | python3 -c "import json,sys; print(len(json.load(sys.stdin)['presets']))"` → 28
- [ ] **3.7 Recording toggle** — `curl -s http://localhost:8051/api/studio/consent | python3 -c "import json,sys; print(json.load(sys.stdin))"` → consent state (recording endpoint removed; use consent API)

## Phase 4: Logos Tauri App (12 tests)

- [ ] **4.1 Launch** — `mod+Q` → window appears, no "Connection refused"
- [ ] **4.2 Imagination co-launch** — Reverie window visible (or was already running)
- [ ] **4.3 Camera grid** — Click inside window, press `g` → 4-6 camera tiles, live feeds
- [ ] **4.4 Hero camera** — Click tile → expands to hero with HLS
- [ ] **4.5 Terrain nav** — `h`, `f`, `g`, `w`, `b` → each region focuses
- [ ] **4.6 Depth cycling** — Press `g` 3x → surface → stratum → core
- [ ] **4.7 Detection tier** — Press `d` → tier cycles (1→2→3)
- [ ] **4.8 Preset cycle** — In ground, press `]` → preset changes in panel
- [ ] **4.9 Split panel** — Press `s` → detail pane toggles
- [ ] **4.10 Escape** — Press `Esc` → everything resets
- [ ] **4.11 No failure banners** — Wait 30s, no red "Service Failed" banners
- [ ] **4.12 Frame server** — `curl -s -o /dev/null -w "%{http_code} %{size_download}" http://localhost:8053/frame` → 200, > 10000

## Phase 5: System Anatomy (4 tests)

- [ ] **5.1 Flow API** — `curl -s http://localhost:8051/api/flow/state | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{len(d[\"nodes\"])} nodes, {len(d[\"edges\"])} edges')"` → ≥ 10 nodes
- [ ] **5.2 New nodes present** — Response includes `dmn`, `imagination_resolver`, `visual_surface`
- [ ] **5.3 Edge types** — Edges have `edge_type` field (confirmed/emergent/dormant)
- [ ] **5.4 FlowPage renders** — Navigate to `/flow` → dagre graph with animated edges

## Phase 6: DMN & Imagination Content (4 tests)

- [ ] **6.1 DMN LLM calls** — `journalctl --user -u hapax-dmn.service --since "1 min ago" --no-pager | grep "200 OK"` → recent successful calls
- [ ] **6.2 Fragment fresh** — `python3 -c "import json,time; f=json.load(open('/dev/shm/hapax-imagination/current.json')); print(f'age={int(time.time()-f.get(\"timestamp\",0))}s')"` → < 120s
- [ ] **6.3 Stimmung → stance** — `python3 -c "import json; print(json.load(open('/dev/shm/hapax-stimmung/state.json'))['overall_stance'])"` → matches Logos display
- [ ] **6.4 VLA writing** — `echo $(($(date +%s) - $(stat -c %Y /dev/shm/hapax-compositor/visual-layer-state.json)))` → < 10s

## Phase 7: Peripheral Systems (6 tests)

- [ ] **7.1 Waybar** — Custom modules visible (health icon, working mode badge)
- [ ] **7.2 Reactive engine** — `curl -s http://localhost:8051/api/engine/status | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'uptime={d.get(\"uptime_s\",0):.0f}s')"` → uptime > 0
- [ ] **7.3 Command relay** — `curl -s -o /dev/null -w "%{http_code}" http://localhost:8052/` → port responding (or 400/101)
- [ ] **7.4 Ntfy** — `curl -s http://localhost:8090/hapax-build/json?poll=1&since=1h | head -1` → accessible
- [ ] **7.5 IR perception** — `ls -la ~/hapax-state/pi-noir/*.json 2>/dev/null | wc -l` → ≥ 1 Pi state file
- [ ] **7.6 Rebuild timer** — `systemctl --user is-active hapax-rebuild-logos.timer` → active

## Phase 8: Build & Rollback (3 tests)

- [ ] **8.1 just version** — `cd hapax-logos && just version` → SHA for both binaries
- [ ] **8.2 just check** — `just check` → "OK: <commit>"
- [ ] **8.3 Rollback available** — `ls ~/.local/bin/hapax-imagination.prev 2>/dev/null` → exists

---

## Summary

| Phase | Tests | Time | Focus |
|-------|-------|------|-------|
| 1. Infrastructure | 7 | 2 min | APIs, GPU, secrets, Docker |
| 2. Reverie | 9 | 3 min | Rendering, presets, hot-reload, content |
| 3. Camera/Studio | 7 | 3 min | Compositor, HLS, snapshots |
| 4. Logos Tauri | 12 | 3 min | UI, keyboard, cameras, regions |
| 5. System Anatomy | 4 | 2 min | Dynamic nodes, edges, dagre |
| 6. DMN/Imagination | 4 | 2 min | LLM ticking, fragments, stimmung |
| 7. Peripheral | 6 | 2 min | Waybar, engine, WS, ntfy, IR |
| 8. Build | 3 | 1 min | Version, preflight, rollback |
| **Total** | **52** | **~18 min** | |
