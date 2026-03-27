# Effect Graph System — Frontend Smoke Test Plan (Playwright + Logos API)

Systematic test plan exercising all effects, presets, layers, camera control,
and command registry through the Logos frontend via Playwright.

**Primary automation path**: `window.__logos.execute()` / `window.__logos.query()`
— the command registry is the most reliable automation surface (no focus/timing issues).

**Screenshot method**: JPEG at 1280x720 to avoid context crashes.

**Prerequisites**: Vite dev server on `:5173`, logos-api on `:8051`, compositor running.

---

## Setup

```javascript
// Navigate and wait for load
await page.goto('http://localhost:5173/terrain');
await page.waitForTimeout(4000);

// Verify command registry is available
const ready = await page.evaluate('() => typeof window.__logos?.execute === "function"');
assert(ready === true, 'Command registry not available');
```

---

## Layer 1: Navigation & Region Control

```javascript
// 1.1 Focus ground region
await page.evaluate('() => window.__logos.execute("terrain.focus", {region: "ground"})');
const focused = await page.evaluate('() => window.__logos.query("terrain.focusedRegion")');
// Expected: "ground"

// 1.2 Set ground to core depth
await page.evaluate('() => window.__logos.execute("terrain.depth.set", {region: "ground", depth: "core"})');
const depths = await page.evaluate('() => window.__logos.query("terrain.depths")');
// Expected: depths.ground === "core"

// 1.3 Open split pane (shows StudioDetailPane)
await page.evaluate('() => window.__logos.execute("split.open", {region: "ground"})');
const splitRegion = await page.evaluate('() => window.__logos.query("split.region")');
// Expected: "ground"

// Take screenshot to verify layout
await page.screenshot({path: 'smoke-01-layout.jpg', type: 'jpeg', quality: 90});
```

- [ ] Ground region focused
- [ ] Core depth active
- [ ] Split pane open with StudioDetailPane
- [ ] Camera hero visible with feed

---

## Layer 2: Preset Listing & Activation (all 28 presets)

```javascript
// 2.1 Fetch all presets from API
const presets = await page.evaluate('() => fetch("/api/studio/presets").then(r => r.json())');
// Expected: presets.presets.length >= 28

// 2.2 Activate each preset, take screenshot, verify
const presetNames = presets.presets.map(p => p.name);
for (const name of presetNames) {
    await page.evaluate(`(n) => window.__logos.execute("studio.preset.activate", {name: n})`, name);
    await page.waitForTimeout(2000); // Let effect render

    const active = await page.evaluate('() => window.__logos.query("studio.activePreset")');
    // Expected: active === name

    await page.screenshot({path: `smoke-preset-${name}.jpg`, type: 'jpeg', quality: 90});
}
```

### All 28 presets to verify:

| # | Preset | Key Visual Characteristic |
|---|--------|--------------------------|
| 1 | ambient | Soft blurred color wash, near-abstract |
| 2 | ascii_preset | Character grid, green-on-black terminal |
| 3 | clean | Near-passthrough, subtle vignette |
| 4 | datamosh | Color-shifted XOR patterns, block artifacts |
| 5 | datamosh_heavy | Heavier block corruption + displacement |
| 6 | diff_preset | Monochrome edge detection, static=black |
| 7 | dither_retro | Posterized/dithered retro look |
| 8 | feedback_preset | Recursive color cycling, zoom accumulation |
| 9 | fisheye_pulse | Barrel distortion pulsing with beat |
| 10 | ghost | Dim additive echoes, phosphor afterglow |
| 11 | glitch_blocks_preset | Rectangular block corruption, RGB split |
| 12 | halftone_preset | CMYK dot grid, print aesthetic |
| 13 | heartbeat | Pulsing breathing rhythm |
| 14 | kaleidodream | Kaleidoscope segments, rotation |
| 15 | mirror_rorschach | Mirrored halves, Rorschach pattern |
| 16 | neon | High saturation, bloom, hue cycling |
| 17 | nightvision | Green phosphor, noise, circular mask |
| 18 | pixsort_preset | Luminance-sorted directional streaks |
| 19 | screwed | Purple/violet, slow, syrupy, blurred |
| 20 | sculpture | Sculptural relief effect |
| 21 | silhouette | High-contrast binary, edge light |
| 22 | slitscan_preset | Temporal displacement, banding |
| 23 | thermal_preset | Ironbow false color, low-res, bloom |
| 24 | trails | Vivid additive motion trails |
| 25 | trap | Dark, heavy vignette, multiply blend |
| 26 | tunnelvision | Tunnel zoom convergence |
| 27 | vhs_preset | Cool tape degradation, scanlines, dropout |
| 28 | voronoi_crystal | Voronoi cell pattern overlay |

- [ ] All 28 presets activate without error
- [ ] Each produces visually distinct output
- [ ] Active preset query returns correct name after activation

---

## Layer 3: Preset Cycling

```javascript
// 3.1 Cycle forward through 5 presets
for (let i = 0; i < 5; i++) {
    await page.evaluate('() => window.__logos.execute("studio.preset.cycle", {direction: "next"})');
    await page.waitForTimeout(500);
}
const afterForward = await page.evaluate('() => window.__logos.query("studio.activePreset")');

// 3.2 Cycle backward
await page.evaluate('() => window.__logos.execute("studio.preset.cycle", {direction: "prev"})');
const afterBack = await page.evaluate('() => window.__logos.query("studio.activePreset")');
// Expected: different from afterForward
```

- [ ] Forward cycling advances through preset list
- [ ] Backward cycling reverses direction
- [ ] Cycling wraps around at list boundaries

---

## Layer 4: HLS / Smooth Mode Toggle

```javascript
// 4.1 Enable smooth mode
await page.evaluate('() => window.__logos.execute("studio.smooth.enable")');
const smooth1 = await page.evaluate('() => window.__logos.query("studio.smoothMode")');
// Expected: true
await page.screenshot({path: 'smoke-hls-on.jpg', type: 'jpeg', quality: 90});

// 4.2 Disable smooth mode
await page.evaluate('() => window.__logos.execute("studio.smooth.disable")');
const smooth2 = await page.evaluate('() => window.__logos.query("studio.smoothMode")');
// Expected: false

// 4.3 Toggle
await page.evaluate('() => window.__logos.execute("studio.smooth.toggle")');
const smooth3 = await page.evaluate('() => window.__logos.query("studio.smoothMode")');
// Expected: true (toggled from false)

// Clean up
await page.evaluate('() => window.__logos.execute("studio.smooth.disable")');
```

- [ ] Enable sets smoothMode true
- [ ] Disable sets smoothMode false
- [ ] Toggle flips current state

---

## Layer 5: Camera Selection

```javascript
// 5.1 Get available cameras from API
const cams = await page.evaluate('() => fetch("/api/studio/cameras").then(r => r.json())');
// Expected: cams.cameras contains 6 roles

// 5.2 Switch hero camera via API
const roles = Object.keys(cams.cameras);
for (const role of roles.slice(0, 3)) { // Test first 3
    await page.evaluate(`(r) => fetch("/api/studio/camera/select", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({role: r})
    })`, role);
    await page.waitForTimeout(1500);
    await page.screenshot({path: `smoke-camera-${role}.jpg`, type: 'jpeg', quality: 90});
}
```

- [ ] Camera list returns 6 cameras
- [ ] Hero switches to each selected camera
- [ ] Feed updates in hero view

---

## Layer 6: Layer Palette Control

```javascript
// 6.1 Set live layer palette (warm)
await page.evaluate('() => fetch("/api/studio/layer/live/palette", {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({saturation: 0.5, brightness: 1.2, contrast: 1.1, sepia: 0.3, hue_rotate: 15})})');
await page.waitForTimeout(500);
await page.screenshot({path: 'smoke-palette-warm.jpg', type: 'jpeg', quality: 90});

// 6.2 Reset to neutral
await page.evaluate('() => fetch("/api/studio/layer/live/palette", {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({saturation: 1.0, brightness: 1.0, contrast: 1.0, sepia: 0.0, hue_rotate: 0.0})})');

// 6.3 Verify layer status
const layers = await page.evaluate('() => fetch("/api/studio/layer/status").then(r => r.json())');
// Expected: layers.layers has live, smooth, hls keys
```

- [ ] Palette change affects visual output
- [ ] Reset returns to neutral
- [ ] Layer status reports all three layers

---

## Layer 7: Layer Enable/Disable

```javascript
// 7.1 Enable smooth layer
await page.evaluate('() => fetch("/api/studio/layer/smooth/enabled", {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({enabled: true})})');

// 7.2 Set smooth delay
await page.evaluate('() => fetch("/api/studio/layer/smooth/delay", {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({delay_seconds: 3.0})})');

// 7.3 Disable smooth layer
await page.evaluate('() => fetch("/api/studio/layer/smooth/enabled", {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({enabled: false})})');

// 7.4 Verify flag files
// (checked via backend — /dev/shm/hapax-compositor/layer-smooth-enabled.txt)
```

- [ ] Enable writes flag file
- [ ] Delay sets temporal offset
- [ ] Disable clears flag

---

## Layer 8: Graph Management via API

```javascript
// 8.1 Get current graph
const graph1 = await page.evaluate('() => fetch("/api/studio/effect/graph").then(r => r.json())');

// 8.2 Load ghost preset
await page.evaluate('() => fetch("/api/studio/presets/ghost/activate", {method: "POST"})');
const graph2 = await page.evaluate('() => fetch("/api/studio/effect/graph").then(r => r.json())');
// Expected: graph2.graph.name === "Ghost"

// 8.3 Patch node params
await page.evaluate('() => fetch("/api/studio/effect/graph/node/trail/params", {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({fade: 0.005, opacity: 0.8})})');
const graph3 = await page.evaluate('() => fetch("/api/studio/effect/graph").then(r => r.json())');
// Expected: graph3.graph.nodes.trail.params.fade === 0.005

// 8.4 Get modulations
const mods = await page.evaluate('() => fetch("/api/studio/effect/graph/modulations").then(r => r.json())');
// Expected: mods.bindings is array
```

- [ ] Graph state readable
- [ ] Preset activation updates graph state
- [ ] Param patching updates node params
- [ ] Modulations readable

---

## Layer 9: Node Registry Discovery

```javascript
// 9.1 List all node types
const nodes = await page.evaluate('() => fetch("/api/studio/effect/nodes").then(r => r.json())');
// Expected: Object.keys(nodes.nodes).length === 54

// 9.2 Get specific node schema
const cg = await page.evaluate('() => fetch("/api/studio/effect/nodes/colorgrade").then(r => r.json())');
// Expected: cg.node_type === "colorgrade", cg.params has saturation/brightness/contrast/sepia/hue_rotate

// 9.3 Get temporal node
const trail = await page.evaluate('() => fetch("/api/studio/effect/nodes/trail").then(r => r.json())');
// Expected: trail.temporal === true
```

- [ ] 54 node types returned
- [ ] Schema includes inputs, outputs, params
- [ ] Temporal nodes flagged correctly

---

## Layer 10: Preset CRUD

```javascript
// 10.1 Save user preset
const testGraph = {name:"playwright-test", description:"smoke", transition_ms:500, nodes:{cg:{type:"colorgrade",params:{saturation:2.0}},out:{type:"output",params:{}}}, edges:[["@live","cg"],["cg","out"]], modulations:[], layer_palettes:{}};
await page.evaluate(`(g) => fetch("/api/studio/presets/playwright_test", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(g)})`, testGraph);

// 10.2 Verify in list
const list = await page.evaluate('() => fetch("/api/studio/presets").then(r => r.json())');
const found = list.presets.some(p => p.name === 'playwright_test');
// Expected: true

// 10.3 Activate user preset
await page.evaluate('() => fetch("/api/studio/presets/playwright_test/activate", {method: "POST"})');
await page.waitForTimeout(1000);
await page.screenshot({path: 'smoke-user-preset.jpg', type: 'jpeg', quality: 90});

// 10.4 Delete user preset
await page.evaluate('() => fetch("/api/studio/presets/playwright_test", {method: "DELETE"})');

// 10.5 Delete builtin → 403
const delBuiltin = await page.evaluate('() => fetch("/api/studio/presets/ghost", {method: "DELETE"}).then(r => r.status)');
// Expected: 403
```

- [ ] User preset saved
- [ ] Appears in list
- [ ] Activates successfully
- [ ] Deleted cleanly
- [ ] Builtin deletion blocked (403)

---

## Layer 11: Detection Tier Control

```javascript
// 11.1 Set detection tier
await page.evaluate('() => window.__logos.execute("detection.tier.set", {tier: 2})');
const tier = await page.evaluate('() => window.__logos.query("detection.tier")');
// Expected: 2

// 11.2 Cycle tier
await page.evaluate('() => window.__logos.execute("detection.tier.cycle")');
const tier2 = await page.evaluate('() => window.__logos.query("detection.tier")');
// Expected: 3

// 11.3 Toggle visibility
await page.evaluate('() => window.__logos.execute("detection.visibility.toggle")');
const vis = await page.evaluate('() => window.__logos.query("detection.visible")');
```

- [ ] Tier set works (1/2/3)
- [ ] Tier cycle advances
- [ ] Visibility toggles

---

## Layer 12: Command Sequences

```javascript
// 12.1 Studio enter sequence (focus ground → core → smooth)
await page.evaluate('() => window.__logos.execute("terrain.collapse")');
await page.waitForTimeout(500);
await page.evaluate('() => window.__logos.execute("studio.enter")');
await page.waitForTimeout(1000);
const afterEnter = {
    focused: await page.evaluate('() => window.__logos.query("terrain.focusedRegion")'),
    depths: await page.evaluate('() => window.__logos.query("terrain.depths")'),
    smooth: await page.evaluate('() => window.__logos.query("studio.smoothMode")'),
};
// Expected: focused === "ground", depths.ground === "core", smooth === true

// 12.2 Studio exit sequence
await page.evaluate('() => window.__logos.execute("studio.exit")');
await page.waitForTimeout(500);
const afterExit = {
    smooth: await page.evaluate('() => window.__logos.query("studio.smoothMode")'),
    focused: await page.evaluate('() => window.__logos.query("terrain.focusedRegion")'),
};
// Expected: smooth === false, focused === null

// 12.3 Escape sequence
await page.evaluate('() => window.__logos.execute("split.open", {region: "ground"})');
await page.evaluate('() => window.__logos.execute("escape")');
const afterEscape = await page.evaluate('() => window.__logos.query("split.region")');
// Expected: null
```

- [ ] studio.enter focuses ground at core with smooth
- [ ] studio.exit disables smooth and collapses
- [ ] escape dismisses active overlay/split

---

## Layer 13: Rapid Preset Stress Test

```javascript
// Cycle through all 28 presets rapidly (200ms each)
const allPresets = await page.evaluate('() => fetch("/api/studio/presets").then(r => r.json())');
for (const p of allPresets.presets) {
    await page.evaluate(`(n) => window.__logos.execute("studio.preset.activate", {name: n})`, p.name);
    await page.waitForTimeout(200);
}
// Verify no crash
const finalPreset = await page.evaluate('() => window.__logos.query("studio.activePreset")');
// Expected: last preset name

await page.screenshot({path: 'smoke-stress-final.jpg', type: 'jpeg', quality: 90});
```

- [ ] All 28 presets activated in 5.6 seconds without crash
- [ ] Final state queryable
- [ ] UI responsive after rapid cycling

---

## Layer 14: Combined Flow — Effect + Layer + Camera

```javascript
// Full integration: activate preset, set palette, switch camera, enable smooth
await page.evaluate('() => window.__logos.execute("studio.preset.activate", {name: "neon"})');
await page.waitForTimeout(1000);

await page.evaluate('() => fetch("/api/studio/layer/live/palette", {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({saturation: 1.5, hue_rotate: 30})})');

await page.evaluate('() => fetch("/api/studio/camera/select", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({role: "c920-room"})})');
await page.waitForTimeout(1000);

await page.evaluate('() => window.__logos.execute("studio.smooth.enable")');
await page.waitForTimeout(1000);

await page.screenshot({path: 'smoke-combined.jpg', type: 'jpeg', quality: 90});

// Verify all state
const combined = {
    preset: await page.evaluate('() => window.__logos.query("studio.activePreset")'),
    smooth: await page.evaluate('() => window.__logos.query("studio.smoothMode")'),
    layers: await page.evaluate('() => fetch("/api/studio/layer/status").then(r => r.json())'),
};
// Expected: preset === "neon", smooth === true, layers has modified palette

// Clean up
await page.evaluate('() => window.__logos.execute("studio.smooth.disable")');
await page.evaluate('() => fetch("/api/studio/layer/live/palette", {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({saturation: 1.0, brightness: 1.0, contrast: 1.0, sepia: 0.0, hue_rotate: 0.0})})');
```

- [ ] Preset + palette + camera + smooth all active simultaneously
- [ ] State queries return correct combined state
- [ ] Clean teardown works

---

## Execution Summary

| Layer | Tests | Method | What |
|-------|-------|--------|------|
| 1. Navigation | 4 | window.__logos | Region focus, depth, split |
| 2. All 28 presets | 28 | window.__logos + screenshot | Visual verification |
| 3. Preset cycling | 3 | window.__logos | Forward, backward, wrap |
| 4. HLS/smooth mode | 4 | window.__logos | Enable, disable, toggle |
| 5. Camera selection | 6+ | API fetch | Switch hero, verify feed |
| 6. Layer palettes | 3 | API fetch | Warm, reset, status |
| 7. Layer enable/disable | 4 | API fetch | Smooth enable/delay/disable |
| 8. Graph management | 4 | API fetch | Load, patch, modulations |
| 9. Node registry | 3 | API fetch | 54 types, schema, temporal |
| 10. Preset CRUD | 5 | API fetch | Save, list, activate, delete, 403 |
| 11. Detection tiers | 3 | window.__logos | Set, cycle, visibility |
| 12. Command sequences | 3 | window.__logos | Enter, exit, escape |
| 13. Stress test | 28 | window.__logos | Rapid 28-preset cycling |
| 14. Combined flow | 5 | window.__logos + API | All systems simultaneously |
| **Total** | **~103** | | |
