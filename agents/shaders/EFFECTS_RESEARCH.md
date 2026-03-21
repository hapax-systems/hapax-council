# GPU Video Effects Research — 7 New Effects for GStreamer Compositor

Research document for implementing production-quality GPU-accelerated video effects.
Each effect analyzed for: origin, practitioners, algorithm, parameters, GStreamer integration,
and what makes it unique vs. merely interesting.

---

## Pipeline Context

Existing infrastructure:
- **GStreamer pipeline** with `glupload ! glshader ! gldownload` pattern
- **Custom Rust `temporalfx` element** — GLFilter subclass with FBO ping-pong accumulation texture
- **GLSL version 100** (GLES2 compatible), `varying vec2 v_texcoord`, `uniform sampler2D tex`
- **Existing shaders**: `color_grade.frag`, `slice_warp.frag`, `vhs.frag`, `post_process.frag`, `ambient_fbm.frag`
- **Existing presets**: ghost, trails, screwed, datamosh, vhs, neon, trap, diff, clean, ambient

New effects that need implementation: pixsort, slitscan, thermal, feedback, halftone, glitchblocks, ascii.
Frontend already registered in `effectSources.ts`.

---

## 1. PIXSORT (Pixel Sorting)

### Origin
Invented by German artist **Kim Asendorf** in 2010. Released as the open-source Processing sketch
**ASDFPixelSort** (2012). The technique sorts pixels along rows or columns by luminosity, hue,
or saturation within threshold-defined intervals, creating characteristic streaked distortions.
Rooted in the glitch art movement — treating data manipulation as aesthetic practice.

### Key Practitioners
- **Kim Asendorf** — originator, released Processing code
- **ciphrd** — pioneered GPU-friendly pseudo-pixel-sorting via vector fields in GLSL
- **Takeshi Murata** — broader glitch art context (Monster Movie, 2005)

### What Makes It UNIQUE
1. **Threshold-gated intervals**: Unlike any blur or distortion, sorting only occurs within
   contiguous runs of pixels that fall between brightness thresholds. Dark regions stay anchored
   while bright regions streak. This creates organic, content-aware boundaries that no other
   effect produces — the image's own luminance structure defines where chaos begins.
2. **Directional coherence with value ordering**: The streaks are not random — they are
   mathematically sorted. Brighter pixels migrate to one end, darker to the other. This produces
   gradients-within-streaks that look like molten paint being pulled by gravity, distinct from
   any motion blur or smear.

### What Makes It INTERESTING
1. **Sort-axis control** (horizontal vs vertical vs diagonal) dramatically changes character —
   horizontal reads as wind/speed, vertical reads as rain/melting, diagonal reads as shear.
2. **Mode switching** (sort by brightness, hue, or saturation) produces wildly different aesthetics
   from the same input — hue sorting creates rainbow banding, saturation sorting isolates
   colored vs. gray regions.

### Algorithm

**True pixel sorting on GPU** is expensive — parallel sorting requires multi-pass feedback.
Two viable approaches:

**A. Pseudo pixel sorting (recommended for real-time, single-pass)**
- For each pixel, sample N neighbors along the sort direction
- If current pixel's luminance is within threshold [low, high], accumulate a directional
  weighted average that mimics the visual result of sorting
- The "smear" length is controlled by step count; threshold controls which pixels participate
- This is what Godot Shaders, ciphrd, and most real-time implementations use

**B. True bitonic/odd-even sort (multi-pass with feedback)**
- Requires ping-pong FBOs like `temporalfx` already has
- Each pass: compare pixel at index with neighbor at specific offset, swap if out of order
- O(log^2 N) passes for N pixels wide — at 1920px, ~121 passes (not practical without compute shaders)

**Pseudo-sort GLSL core logic:**
```glsl
uniform float u_threshold_low;   // 0.0-1.0 brightness gate
uniform float u_threshold_high;  // 0.0-1.0 brightness gate
uniform float u_sort_length;     // max pixels to smear (10-100)
uniform float u_direction;       // 0=horizontal, 1=vertical, 0.5=diagonal

void main() {
    vec2 uv = v_texcoord;
    float lum = dot(texture2D(tex, uv).rgb, vec3(0.299, 0.587, 0.114));

    // Only sort pixels within threshold window
    if (lum < u_threshold_low || lum > u_threshold_high) {
        gl_FragColor = texture2D(tex, uv);
        return;
    }

    // Directional smear — sample along sort axis, accumulate
    vec2 dir = normalize(vec2(cos(u_direction * 3.14159), sin(u_direction * 3.14159)));
    vec2 texel = vec2(1.0 / u_width, 1.0 / u_height);
    vec3 accum = vec3(0.0);
    float weight = 0.0;

    for (float i = 0.0; i < 64.0; i += 1.0) {
        if (i >= u_sort_length) break;
        vec2 sampleUV = uv + dir * texel * i;
        vec4 s = texture2D(tex, sampleUV);
        float sLum = dot(s.rgb, vec3(0.299, 0.587, 0.114));
        if (sLum < u_threshold_low || sLum > u_threshold_high) break;
        float w = 1.0 - (i / u_sort_length);
        accum += s.rgb * w;
        weight += w;
    }
    gl_FragColor = vec4(accum / weight, 1.0);
}
```

### Parameters
| Parameter | Range | Effect |
|-----------|-------|--------|
| `threshold_low` | 0.0-1.0 | Lower brightness gate — pixels below are anchored |
| `threshold_high` | 0.0-1.0 | Upper brightness gate — pixels above are anchored |
| `sort_length` | 5-200 | Maximum streak length in pixels |
| `direction` | 0.0-1.0 | Sort direction (0=horiz, 0.5=diag, 1.0=vert) |
| `intensity` | 0.0-1.0 | Mix with original (for subtlety control) |

### GStreamer Integration
Single-pass `glshader` element. No feedback needed. Add as new `.frag` file.
```
glupload ! glshader fragment="pixsort.frag" ! ...
```

---

## 2. SLIT-SCAN

### Origin
Photographic technique from the 1800s — a slit mask moved across film during exposure,
capturing different parts of the scene at different times. Famously used by **Douglas Trumbull**
for the "Star Gate" sequence in **2001: A Space Odyssey** (1968) — one frame at a time,
camera advancing toward a slit with moving backlit artwork behind it.

### Key Practitioners
- **Douglas Trumbull** — invented the film slit-scan machine for Kubrick
- **Golan Levin** — compiled an extensive catalogue of slit-scan artworks; his interactive
  installations use temporal displacement as a core technique
- **Daito Manabe / Rhizomatiks** — live performance slit-scan visuals

### What Makes It UNIQUE
1. **Temporal displacement per scanline**: Each horizontal line of the output comes from a
   *different moment in time*. The top might show 2 seconds ago while the bottom shows now.
   No other effect creates this specific kind of temporal smearing — it is literally a spatial
   map of time, not a spatial filter.
2. **Motion reveals time structure**: A person walking across frame leaves a diagonal streak
   whose angle encodes their speed. Fast motion = steep angle, slow = shallow. The image
   becomes a chronophotograph — readable as both picture and timeline simultaneously.

### What Makes It INTERESTING
1. **Tunnel/wormhole geometry**: When mapped radially (center = present, edges = past),
   the effect creates the infinite-tunnel look from 2001 — depth encodes time, creating
   natural parallax-like depth from a flat 2D camera.
2. **Musical synchronization**: The displacement map can be driven by audio amplitude,
   making the temporal warping pulse with the beat — past/present boundaries dance.

### Algorithm

**Core requirement**: A circular buffer of N recent frames (frame history).

For each output pixel at position (x, y):
1. Compute a time offset from a displacement map: `t_offset = displacement(x, y) * max_delay`
2. Sample the frame from `t_offset` frames ago at position (x, y)
3. Output that pixel

**Displacement maps**:
- **Horizontal gradient** (classic slit-scan): left=present, right=past
- **Vertical gradient**: top=present, bottom=past
- **Radial gradient**: center=present, edges=past (tunnel effect)
- **Custom**: any grayscale image maps time

**Memory requirement**: At 1920x1080 RGBA, each frame = ~8MB. 60 frames of history = ~500MB VRAM.
Can reduce by using quarter-res history or fewer frames.

### Parameters
| Parameter | Range | Effect |
|-----------|-------|--------|
| `max_displacement` | 1-120 | Maximum frames of temporal offset |
| `displacement_mode` | enum | horizontal/vertical/radial/custom |
| `time_resolution` | 1-60 | Frames stored per second of history |
| `slit_width` | 1-100 | Width of the sampling slit in pixels |
| `direction` | 0.0-1.0 | Which end of the gradient is "now" |

### GStreamer Integration
**Cannot use basic `glshader`** — needs frame history buffer.
Must extend the Rust `temporalfx` element or create a new `slitscanfx` GLFilter:
- Allocate a ring buffer of GL textures (frame history)
- Each frame: push current frame into ring buffer
- In the shader: bind all history textures (or a 3D texture / texture array)
- Fragment shader samples from the appropriate history frame per-pixel

Alternative: Use `glshader` with a single accumulated "time texture" that scrolls one
column/row per frame — simpler but only supports 1D slit-scan (classic horizontal).

---

## 3. THERMAL

### Origin
Infrared/thermal imaging dates to the 1940s (military FLIR — Forward Looking InfraRed).
The visual language — false-color palettes mapping temperature to color — became cultural
shorthand for "surveillance" and "predator vision" through films like **Predator** (1987)
and military/police footage. The Predator thermal vision shader by Geeks3D is the canonical
game-dev reference implementation.

### Key Practitioners
- **John McTiernan** (Predator, 1987) — defined the pop-culture thermal look
- **Geeks3D Shader Library** — canonical GLSL implementation of Predator thermal vision
- **FLIR Systems** — real thermal cameras whose palette choices (White Hot, Ironbow, Rainbow)
  define the visual vocabulary

### What Makes It UNIQUE
1. **Luminance-to-palette remapping**: The effect is not a color filter — it completely
   replaces the image's color space with a false-color palette indexed by brightness. A
   sunset and a fluorescent office, equalized to the same luminance, produce identical output.
   This total color replacement is fundamentally different from any tint/grade/LUT.
2. **Edge glow from Sobel + bloom**: Real thermal cameras show heat radiation bleeding at
   object boundaries. The shader computes edge detection (Sobel) and adds a glow specifically
   at edges, making silhouettes "radiate." No other effect combines edge detection with
   additive bloom in this specific way.

### What Makes It INTERESTING
1. **Multiple authentic palettes** (White Hot, Black Hot, Ironbow, Rainbow) each tell a
   different visual story from the same input — switchable via uniform.
2. **Noise characteristics**: Real thermal has distinctive low-frequency noise (not film
   grain — more like slowly drifting thermal patterns), which adds organic texture.

### Algorithm

```glsl
uniform int u_palette_mode;       // 0=white-hot, 1=ironbow, 2=rainbow, 3=predator
uniform float u_edge_glow;        // edge detection strength (0-1)
uniform float u_noise_amount;     // thermal noise (0-0.3)

// Ironbow palette: black -> blue -> magenta -> orange -> yellow -> white
vec3 ironbow(float t) {
    if (t < 0.2) return mix(vec3(0.0), vec3(0.0, 0.0, 0.5), t / 0.2);
    if (t < 0.4) return mix(vec3(0.0, 0.0, 0.5), vec3(0.7, 0.0, 0.7), (t - 0.2) / 0.2);
    if (t < 0.6) return mix(vec3(0.7, 0.0, 0.7), vec3(1.0, 0.5, 0.0), (t - 0.4) / 0.2);
    if (t < 0.8) return mix(vec3(1.0, 0.5, 0.0), vec3(1.0, 1.0, 0.0), (t - 0.6) / 0.2);
    return mix(vec3(1.0, 1.0, 0.0), vec3(1.0, 1.0, 1.0), (t - 0.8) / 0.2);
}

// White hot: simple grayscale (already "thermal" feeling)
vec3 whitehot(float t) { return vec3(t); }

// Predator: green-dominant with edge glow
vec3 predator(float t) {
    return vec3(t * 0.2, t, t * 0.1);
}

void main() {
    vec2 uv = v_texcoord;
    vec2 texel = vec2(1.0 / u_width, 1.0 / u_height);

    // Compute luminance
    float lum = dot(texture2D(tex, uv).rgb, vec3(0.299, 0.587, 0.114));

    // Sobel edge detection
    float tl = dot(texture2D(tex, uv + vec2(-texel.x, texel.y)).rgb, vec3(0.299, 0.587, 0.114));
    float t  = dot(texture2D(tex, uv + vec2(0.0, texel.y)).rgb, vec3(0.299, 0.587, 0.114));
    float tr = dot(texture2D(tex, uv + vec2(texel.x, texel.y)).rgb, vec3(0.299, 0.587, 0.114));
    float ml = dot(texture2D(tex, uv + vec2(-texel.x, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float mr = dot(texture2D(tex, uv + vec2(texel.x, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float bl = dot(texture2D(tex, uv + vec2(-texel.x, -texel.y)).rgb, vec3(0.299, 0.587, 0.114));
    float b  = dot(texture2D(tex, uv + vec2(0.0, -texel.y)).rgb, vec3(0.299, 0.587, 0.114));
    float br = dot(texture2D(tex, uv + vec2(texel.x, -texel.y)).rgb, vec3(0.299, 0.587, 0.114));

    float gx = -tl - 2.0*ml - bl + tr + 2.0*mr + br;
    float gy = -tl - 2.0*t - tr + bl + 2.0*b + br;
    float edge = sqrt(gx*gx + gy*gy);

    // Apply palette
    vec3 color;
    if (u_palette_mode == 0) color = whitehot(lum);
    else if (u_palette_mode == 1) color = ironbow(lum);
    else if (u_palette_mode == 3) color = predator(lum);
    // ... rainbow, etc.

    // Add edge glow
    color += edge * u_edge_glow * vec3(1.0, 0.8, 0.2);

    // Thermal noise (low frequency)
    float noise = fract(sin(dot(uv * 50.0 + u_time * 0.5, vec2(12.9898, 78.233))) * 43758.5453);
    noise = (noise - 0.5) * u_noise_amount;
    color += noise;

    gl_FragColor = vec4(clamp(color, 0.0, 1.0), 1.0);
}
```

### Parameters
| Parameter | Range | Effect |
|-----------|-------|--------|
| `palette_mode` | 0-3 | White-hot / Ironbow / Rainbow / Predator |
| `edge_glow` | 0.0-2.0 | Sobel edge brightness boost |
| `noise_amount` | 0.0-0.3 | Low-frequency thermal noise |
| `blur_radius` | 0-5 | Pre-blur to simulate lower thermal resolution |
| `contrast` | 0.5-3.0 | Luminance contrast before palette mapping |

### GStreamer Integration
Single-pass `glshader`. No feedback or history needed. Straightforward fragment shader.

---

## 4. FEEDBACK

### Origin
Analog video feedback — pointing a camera at its own monitor output — discovered in the
1960s. **Nam June Paik** displayed video feedback at the Greenwich Cafe (NYC, mid-1960s).
**Steina and Woody Vasulka** founded The Kitchen (1971) and systematically explored feedback
as a medium, connecting audio synthesizers to video to create images from sound.

The mathematical basis: each frame applies a transformation (zoom, rotate, color shift) to
the previous frame and composites with the live input. The patterns that emerge are **attractors
of the dynamical system** — stable geometric structures from iterated function systems, closely
related to fractal geometry.

### Key Practitioners
- **Nam June Paik** — pioneer of video art, early feedback experiments
- **Steina & Woody Vasulka** — systematic exploration of video feedback + audio-reactive
- **Fractal Foundation** — documented the mathematical connection between feedback and fractals

### What Makes It UNIQUE
1. **Self-referential recursion with transformation**: The output feeds back as input with
   a geometric transform (zoom + rotate). This creates infinitely nested copies of the image
   that spiral inward or outward. No other effect creates this recursive nesting — it is
   the video equivalent of standing between two mirrors, but with each reflection rotated
   and color-shifted.
2. **Emergent complexity from simple rules**: The visual patterns are not designed — they
   emerge from the interaction of zoom ratio, rotation angle, and color decay. Tiny parameter
   changes produce qualitatively different structures (spirals, mandalas, fractal trees).
   The effect is a dynamical system, not a filter.

### What Makes It INTERESTING
1. **Color cycling through hue-shifted decay**: As pixels recede into recursion, their hue
   shifts, creating rainbow spirals and color gradients that would be impossible to design manually.
2. **Audio reactivity potential**: Zoom and rotation can be driven by audio amplitude/frequency,
   making the fractal patterns breathe and pulse with music — a natural synesthetic mapping.

### Algorithm

The existing `temporalfx` element already implements the core feedback loop (FBO ping-pong
with accumulation texture). The **Feedback** effect extends this by adding **spatial
transformation** to the feedback path:

```glsl
// In the feedback shader — applied to the accumulation texture before mixing
uniform float u_fb_zoom;         // zoom per frame (1.02 = slow zoom in)
uniform float u_fb_rotation;     // rotation per frame in radians
uniform float u_fb_hue_shift;    // hue rotation per recursion
uniform float u_fb_decay;        // overall brightness decay (0.9-0.99)
uniform float u_fb_mix;          // how much live input vs feedback (0.1-0.5)

void main() {
    vec2 uv = v_texcoord;

    // Transform UV for feedback sampling (zoom + rotate around center)
    vec2 centered = uv - 0.5;
    float c = cos(u_fb_rotation);
    float s = sin(u_fb_rotation);
    centered = mat2(c, -s, s, c) * centered;
    centered /= u_fb_zoom;
    vec2 fbUV = centered + 0.5;

    // Sample feedback with transform
    vec4 fb = texture2D(tex_accum, fbUV);
    fb.rgb *= u_fb_decay;

    // Hue shift the feedback
    vec3 hsv = rgb2hsv(fb.rgb);
    hsv.x = fract(hsv.x + u_fb_hue_shift / 360.0);
    fb.rgb = hsv2rgb(hsv);

    // Mix with live input
    vec4 live = texture2D(tex, uv);
    gl_FragColor = vec4(mix(fb.rgb, live.rgb, u_fb_mix), 1.0);
}
```

### Parameters
| Parameter | Range | Effect |
|-----------|-------|--------|
| `fb_zoom` | 0.95-1.1 | Zoom per recursion (>1 = zoom in, <1 = zoom out) |
| `fb_rotation` | -0.1-0.1 | Rotation per frame in radians |
| `fb_hue_shift` | 0-60 | Hue rotation per recursion (degrees) |
| `fb_decay` | 0.85-0.99 | Brightness decay per recursion |
| `fb_mix` | 0.05-0.5 | Live input mix ratio |
| `fb_translate_x/y` | -0.05-0.05 | Translation offset per recursion |

### GStreamer Integration
**Extend `temporalfx`** — the feedback loop already exists. Need to add:
1. UV transformation (zoom/rotate/translate) when sampling the accumulation texture
2. New properties for zoom, rotation, translate, hue_shift
3. The existing `feedback_amount` maps to `fb_mix`

This is the most natural extension of existing infrastructure.

---

## 5. HALFTONE

### Origin
**Halftone printing** dates to the 1850s. The Ben-Day dot process was patented in **1879**
by Benjamin Henry Day Jr. as a cost-saving innovation for commercial printing. Became the
visual language of comic books, newspapers, and Pop Art.

**Roy Lichtenstein** (from 1961) made Ben-Day dots the signature of Pop Art by hand-painting
what appeared to be mechanical printing artifacts at massive scale. **Andy Warhol** used
actual silkscreen halftone in his prints, embracing mechanical reproduction.

### Key Practitioners
- **Roy Lichtenstein** — hand-painted Ben-Day dots as fine art (Whaam!, 1963)
- **Andy Warhol** — silkscreen halftone as art medium
- **Stefan Gustavson** — canonical GLSL halftone shader implementation (WebGL tutorial)
- **Maxime Heckel** — "Shades of Halftone" deep-dive on shader implementation

### What Makes It UNIQUE
1. **Continuous tone from discrete dots**: The effect converts smooth gradients into a grid of
   circles whose **radius encodes brightness**. Dark = big dots, light = small dots. This is
   fundamentally different from pixelation (which uses squares of uniform color) — halftone
   preserves tonal range through geometry, not color.
2. **CMYK angle separation**: Authentic halftone uses four dot grids at specific angles
   (C=105deg, M=75deg, K=45deg, Y=0deg) to create **rosette patterns** where the overlapping
   dots produce full-color images. The moire rosette is itself a signature visual artifact
   that no other technique produces.

### What Makes It INTERESTING
1. **Shape vocabulary**: Dots are just the default — lines, diamonds, crosses, and custom
   shapes all create valid halftone patterns with dramatically different visual character.
2. **Scale as expression**: At coarse screen frequency (low LPI), the dots become a visible
   design element (Pop Art). At fine frequency, they disappear into apparent continuous tone.
   The frequency parameter controls whether the effect reads as "stylized" or "printed."

### Algorithm

```glsl
uniform float u_dot_size;        // cell size in pixels (4-40)
uniform float u_dot_shape;       // 0=circle, 1=diamond, 2=line
uniform float u_cmyk_mode;       // 0=mono, 1=full CMYK separation
uniform float u_angle;           // base screen angle in degrees (for mono)

void main() {
    vec2 uv = v_texcoord;
    vec4 color = texture2D(tex, uv);

    if (u_cmyk_mode < 0.5) {
        // Monochrome halftone
        float lum = dot(color.rgb, vec3(0.299, 0.587, 0.114));
        float angle_rad = u_angle * 3.14159 / 180.0;
        float ca = cos(angle_rad), sa = sin(angle_rad);

        vec2 pixel = gl_FragCoord.xy;
        vec2 rotated = vec2(ca * pixel.x + sa * pixel.y,
                           -sa * pixel.x + ca * pixel.y);
        vec2 cell = mod(rotated, u_dot_size) / u_dot_size - 0.5;

        float dist;
        if (u_dot_shape < 0.5)
            dist = length(cell);          // circle
        else if (u_dot_shape < 1.5)
            dist = abs(cell.x) + abs(cell.y);  // diamond
        else
            dist = abs(cell.y);           // line

        float radius = (1.0 - lum) * 0.7;  // darker = bigger dot
        float dot_val = step(dist, radius);
        gl_FragColor = vec4(vec3(dot_val), 1.0);
    } else {
        // CMYK separation — four passes at different angles
        // Convert RGB to CMY
        float c_val = 1.0 - color.r;
        float m_val = 1.0 - color.g;
        float y_val = 1.0 - color.b;
        float k_val = min(c_val, min(m_val, y_val));

        // Standard halftone angles
        float angles[4]; // C=105, M=75, K=45, Y=0
        float values[4]; // c, m, y, k channel values

        // (compute each channel's dot pattern at its angle, composite)
        // ... see full implementation in shader file
    }
}
```

### Parameters
| Parameter | Range | Effect |
|-----------|-------|--------|
| `dot_size` | 4-40 | Halftone cell size in pixels |
| `dot_shape` | 0-2 | Circle / Diamond / Line |
| `cmyk_mode` | 0-1 | Mono vs CMYK color separation |
| `angle` | 0-180 | Screen angle (mono mode) |
| `contrast` | 0.5-2.0 | Pre-contrast before halftone conversion |
| `color_tint` | vec3 | Ink color for mono mode (default black on white) |

### GStreamer Integration
Single-pass `glshader`. No feedback or history needed. Potentially the simplest new effect.

---

## 6. GLITCH BLOCKS

### Origin
Digital compression artifacts from JPEG/MPEG codecs. The **Discrete Cosine Transform (DCT)**
processes images in 8x8 pixel blocks; when data is corrupted, individual blocks display wrong
content, shift position, or freeze while surrounding blocks update normally. This visual
language of digital failure became deliberately cultivated as **glitch art**.

**Rosa Menkman** wrote the **Glitch Studies Manifesto** (2010) and **A Vernacular of File Formats**,
establishing glitch art as a recognized genre. **Takeshi Murata** pioneered datamoshing with
**Monster Movie** (2005) — now in the Smithsonian's permanent collection.

### Key Practitioners
- **Rosa Menkman** — theorist, Glitch Studies Manifesto, "Vernacular of File Formats"
- **Takeshi Murata** — Monster Movie (2005), pioneer of artistic datamoshing
- **Kanye West / Bob Weisz** — "Welcome to Heartbreak" (2009), mainstream datamosh

### What Makes It UNIQUE
1. **Block-level independence**: Unlike pixel-level effects, glitch blocks operate on
   rectangular regions (typically 8x8 or 16x16) that each behave independently — one block
   freezes, its neighbor shifts, another gets wrong color. This grid-aligned discontinuity
   is the fingerprint of DCT-based compression and cannot be mistaken for any analog effect.
2. **Temporal desynchronization per block**: Different blocks can show content from different
   moments in time — some frozen on frame N-30, others showing the current frame, others
   displaced. This creates a visual mosaic of time, distinct from slit-scan's smooth gradient.

### What Makes It INTERESTING
1. **RGB channel splitting with block displacement**: Shifting R, G, B channels by different
   amounts per block creates prismatic fringing that looks like a GPU dying — visceral and
   immediately recognizable as "digital malfunction."
2. **Probabilistic triggering**: Blocks corrupt stochastically — the effect feels alive and
   unpredictable, with corruption cascading and resolving in waves. Controllable randomness.

### Algorithm

```glsl
uniform float u_block_size;       // block size in pixels (8, 16, 32)
uniform float u_corrupt_chance;   // probability a block is corrupted (0-0.5)
uniform float u_max_shift;        // maximum block displacement in pixels
uniform float u_rgb_split;        // chromatic aberration amount
uniform float u_freeze_chance;    // chance a block shows stale content

// Per-block random hash
float blockHash(vec2 blockID, float seed) {
    return fract(sin(dot(blockID + seed, vec2(12.9898, 78.233))) * 43758.5453);
}

void main() {
    vec2 uv = v_texcoord;
    vec2 pixel = gl_FragCoord.xy;
    vec2 blockID = floor(pixel / u_block_size);
    float timeSlot = floor(u_time * 4.0);  // change corruption pattern 4x/sec

    float h = blockHash(blockID, timeSlot);

    if (h < u_corrupt_chance) {
        // This block is corrupted
        float shiftX = (blockHash(blockID, timeSlot + 1.0) - 0.5) * u_max_shift / u_width;
        float shiftY = (blockHash(blockID, timeSlot + 2.0) - 0.5) * u_max_shift / u_height;
        vec2 displaced = uv + vec2(shiftX, shiftY);

        // RGB split per block
        float rShift = blockHash(blockID, timeSlot + 3.0) * u_rgb_split / u_width;
        float r = texture2D(tex, displaced + vec2(rShift, 0.0)).r;
        float g = texture2D(tex, displaced).g;
        float b = texture2D(tex, displaced - vec2(rShift, 0.0)).b;

        gl_FragColor = vec4(r, g, b, 1.0);
    } else {
        gl_FragColor = texture2D(tex, uv);
    }
}
```

### Parameters
| Parameter | Range | Effect |
|-----------|-------|--------|
| `block_size` | 4-64 | Corruption block size in pixels |
| `corrupt_chance` | 0.0-0.5 | Per-block corruption probability |
| `max_shift` | 0-100 | Maximum block displacement (pixels) |
| `rgb_split` | 0-20 | Chromatic aberration per block |
| `change_rate` | 1-30 | How often corruption pattern changes (Hz) |
| `scanline_jitter` | 0-10 | Per-scanline horizontal jitter |

### GStreamer Integration
Single-pass `glshader`. The randomness is time-seeded so no feedback needed.
For extra authenticity, could freeze blocks using `temporalfx` accumulation texture
(sample from accum for "frozen" blocks, current for "live" blocks).

---

## 7. ASCII

### Origin
ASCII art dates to **typewriter art** of the 1890s and computer art of the 1960s.
**Vuk Cosic** (Slovenian net.art pioneer) created **Deep ASCII** (1998) — the first
full-length film converted to ASCII characters, along with **ASCII History of Moving Images**
— converting Lumiere, Eisenstein, Hitchcock, and others to text. The aesthetic connects
to **Teletext** (late 1970s), early BBS culture, and the demoscene.

### Key Practitioners
- **Vuk Cosic** — Deep ASCII (1998), ASCII History of Moving Images
- **Ian Parberry** — "ASCII Art on a Pixel Shader" academic reference
- **Alex Harri** — "ASCII characters are not pixels" deep-dive on character matching
- **humanbydefinition** — p5.js ASCII renderer with GLSL shader backend

### What Makes It UNIQUE
1. **Dimensional reduction to a character grid**: The image is quantized into cells (typically
   8x8 or 8x16), and each cell is replaced by a single ASCII character chosen to match the
   cell's average luminance. This is not pixelation — it maps continuous brightness to a
   discrete set of glyphs with inherent visual texture. The character "@" has more ink than "."
   but also a specific shape that interacts with the content.
2. **Information layer duality**: The output simultaneously functions as an image (at viewing
   distance) and as readable text (up close). No other video effect creates output that exists
   in two fundamentally different media spaces at once.

### What Makes It INTERESTING
1. **Character set as aesthetic parameter**: Switching from standard ASCII to katakana, box
   drawing characters, or Braille patterns completely changes the texture and cultural
   reference of the output — same algorithm, wildly different feeling.
2. **Color preservation**: The characters can be rendered in the color of the original pixel
   region (not just green-on-black), creating a surprisingly faithful color image made of text.

### Algorithm

Two approaches for GPU:

**A. Texture Atlas Lookup (recommended)**
- Pre-render all ASCII characters (32-126) into a texture atlas
- Sort characters by visual density (fill percentage)
- In shader: compute cell luminance, map to character index, sample from atlas

**B. Procedural Bit-Pattern (no atlas needed)**
- Encode each character as a 5x5 bit pattern packed into a single int
- The shader unpacks bits based on sub-cell position
- Limited character quality but zero texture dependencies

```glsl
uniform sampler2D tex;
uniform sampler2D u_font_atlas;    // character atlas texture
uniform float u_cell_width;        // cell width in pixels (8)
uniform float u_cell_height;       // cell height in pixels (16)
uniform float u_char_count;        // number of characters in atlas
uniform float u_colored;           // 0=mono green, 1=source colors

void main() {
    vec2 pixel = gl_FragCoord.xy;

    // Which cell are we in?
    vec2 cellID = floor(pixel / vec2(u_cell_width, u_cell_height));
    vec2 cellUV = cellID * vec2(u_cell_width, u_cell_height);

    // Sample center of cell from source texture for average luminance
    vec2 cellCenter = (cellID + 0.5) * vec2(u_cell_width, u_cell_height);
    vec2 srcUV = cellCenter / vec2(u_width, u_height);
    vec4 srcColor = texture2D(tex, srcUV);
    float lum = dot(srcColor.rgb, vec3(0.299, 0.587, 0.114));

    // Map luminance to character index
    float charIndex = floor(lum * (u_char_count - 1.0));

    // Position within cell (for sampling character from atlas)
    vec2 inCell = mod(pixel, vec2(u_cell_width, u_cell_height))
                  / vec2(u_cell_width, u_cell_height);

    // Sample from atlas (characters arranged horizontally)
    vec2 atlasUV = vec2((charIndex + inCell.x) / u_char_count, inCell.y);
    float charAlpha = texture2D(u_font_atlas, atlasUV).r;

    // Output
    vec3 bgColor = vec3(0.0);
    vec3 fgColor = u_colored > 0.5 ? srcColor.rgb : vec3(0.0, 1.0, 0.3);  // green terminal
    gl_FragColor = vec4(mix(bgColor, fgColor, charAlpha), 1.0);
}
```

### Parameters
| Parameter | Range | Effect |
|-----------|-------|--------|
| `cell_width` | 4-16 | Character cell width in pixels |
| `cell_height` | 8-24 | Character cell height in pixels |
| `colored` | 0-1 | Monochrome terminal vs. source-colored |
| `fg_color` | vec3 | Foreground color (mono mode) |
| `bg_color` | vec3 | Background color |
| `char_set` | enum | ASCII / Katakana / Braille / Block |
| `contrast` | 0.5-2.0 | Pre-contrast before character mapping |

### GStreamer Integration
Needs a **font atlas texture** passed as a second sampler uniform. Options:
1. Generate atlas at startup, upload as GL texture, bind via custom element property
2. Use the procedural bit-pattern approach to avoid external texture dependency
3. Extend `temporalfx` to support an auxiliary texture input (font atlas)

For maximum quality, option 1 (atlas texture) is best. The atlas can be generated once
from a TTF font at pipeline init time and bound as a static texture.

---

## Cross-Pollination: Techniques That Could Improve Existing Effects

### For GHOST
- **Thermal edge glow**: Add subtle Sobel edge detection to the ghost trail — silhouettes
  radiate faintly, making ghosting feel more like heat signature than just motion blur.
- **Halftone decay**: As ghost trails fade, they could dissolve into halftone dots rather
  than just dimming — matter decomposing into print artifacts.

### For TRAILS
- **Pixel sort on trail direction**: Apply pseudo-pixel-sorting along the trail drift vector,
  making trails streak into sorted bands rather than smooth blurs. Trails become chromatic.
- **Slit-scan temporal offset**: Instead of uniform trail delay, apply different temporal
  offsets per scanline — trails undulate with time structure.

### For SCREWED
- **Feedback zoom breathing**: Add subtle recursive feedback zoom (from the Feedback effect)
  at the screwed breathing rate — the purple tunnel gains infinite depth.
- **ASCII degradation**: In the deepest shadows of screwed, transition to ASCII characters —
  reality dissolving into text as consciousness fades.

### For DATAMOSH
- **Block-level corruption from Glitch Blocks**: Currently uses difference blending for
  datamosh look. Adding actual block-grid displacement (8x8 blocks shifting independently)
  would add the DCT-authentic compression-failure aesthetic.
- **Pixel sort in corruption zones**: Where datamosh creates high-contrast edges, apply
  pixel sorting — the boundary between corrupted and clean regions streaks into sorted bands.

### For VHS
- **Halftone scanlines**: Replace simple scanline darkening with actual halftone-style dot
  pattern for the phosphor grid — more authentic to CRT display physics.
- **Thermal palette on tracking errors**: When VHS tracking bands appear, briefly flash
  them in thermal palette colors — mimics the color-burst desync of real VHS.

### For NEON
- **Feedback glow recursion**: Neon highlights could feed back with slight zoom, creating
  glow that blooms recursively — light sources develop halos with rainbow edges.
- **Slit-scan on glow trails**: Apply temporal offset to the glow component only — bright
  areas leave time-smeared light trails while dark areas stay sharp.

### For TRAP
- **ASCII shadow zone**: The darkest regions of trap's multiply-blend shadows could
  transition to ASCII/block characters — darkness becomes texture, not just absence.
- **Thermal palette in highlights**: The few bright spots that survive trap's darkness
  could render in thermal false-color — surveillance aesthetic crossover.

### For DIFF
- **Pixel sort on difference edges**: The high-contrast edges from difference blending
  are perfect input for pixel sorting — edges explode into sorted streaks.
- **Halftone quantization**: Apply halftone dot pattern to the diff output — motion
  detection rendered as print, like a security camera from a newspaper.

### For CLEAN
- **Subtle halftone at edges**: Very fine halftone pattern (high LPI) visible only at
  edges and in shadows — gives "clean" a hint of printed/processed quality without
  being overtly stylized. Differentiates it from truly raw camera.

---

## Implementation Priority Order

Based on complexity (simple first) and impact:

1. **Thermal** — single-pass, no dependencies, strong visual identity, reuses Sobel from nothing new
2. **Halftone** — single-pass, pure math, immediately recognizable
3. **Glitch Blocks** — single-pass, random hash only, dramatic visual
4. **Pixsort** — single-pass pseudo-sort, threshold logic
5. **ASCII** — needs font atlas texture (one-time generation), otherwise single-pass
6. **Feedback** — extends existing `temporalfx` with UV transform, moderate Rust changes
7. **Slit-scan** — needs frame history buffer, significant new infrastructure

---

## Sources

- [ciphrd - Pixel sorting on shader using vector fields, GLSL](https://ciphrd.com/2020/04/08/pixel-sorting-on-shader-using-well-crafted-sorting-filters-glsl/)
- [Kim Asendorf - ASDFPixelSort (GitHub)](https://github.com/kimasendorf/ASDFPixelSort)
- [Pseudo Pixel Sorting - Godot Shaders](https://godotshaders.com/shader/pseudo-pixel-sorting/)
- [GPU Sorting - Alan Zucconi](https://www.alanzucconi.com/2017/12/13/gpu-sorting-1/)
- [Bitonic Pixel Sorter (GitHub)](https://github.com/ruccho/BitonicPixelSorter)
- [Shadertoy - Pixel Sorting](https://www.shadertoy.com/view/XdcGWf)
- [Douglas Trumbull - SFX on 2001 A Space Odyssey](https://mediartinnovation.com/2014/08/05/doug-trumbull-special-effects-on-2001-a-space-odyssey/)
- [Roy's Blog - Recreating the Doctor Who Time Tunnel in GLSL](http://roy.red/posts/slitscan/)
- [Golan Levin - Informal Catalogue of Slit-Scan Video Artworks](http://www.flong.com/archive/texts/lists/slit_scan/index.html)
- [Keijiro Takahashi - KinoSlitscan (GitHub)](https://github.com/keijiro/KinoSlitscan)
- [Slit-scanning on the GPU - Observable](https://observablehq.com/@jobleonard/slit-scanning-on-the-gpu)
- [Geeks3D - Predator's Thermal Vision GLSL Shader](https://www.geeks3d.com/20101123/shader-library-predators-thermal-vision-post-processing-filter-glsl/)
- [IR.Tools - Thermal Color Palette Breakdown](https://ir.tools/breaking-down-the-thermal-color-palette-so-even-your-kids-understand/)
- [AGM - Types of Thermal Palettes](https://www.agmglobalvision.com/Types-of-Thermal-Pallets)
- [Video Feedback - Wikipedia](https://en.wikipedia.org/wiki/Video_feedback)
- [Glitchology - Video Feedback](https://glitchology.com/video-feedback/)
- [Nature - Fractals in pixellated video feedback](https://www.nature.com/articles/414864a)
- [VDMX - Zooming Feedback Effect](https://vdmx.vidvox.net/tutorials/zooming-feedback-effect)
- [Maxime Heckel - Shades of Halftone](https://blog.maximeheckel.com/posts/shades-of-halftone/)
- [glslify/glsl-halftone (GitHub)](https://github.com/glslify/glsl-halftone)
- [Stefan Gustavson - WebGL Halftone Shader Tutorial](https://itn-web.it.liu.se/~stegu76/webglshadertutorial/shadertutorial.html)
- [Halftone - Wikipedia](https://en.wikipedia.org/wiki/Halftone)
- [Paper.design - CMYK Halftone Shader](https://paper.design/blog/retro-print-cmyk-halftone-shader)
- [Ben-Day Dots - Public Delivery](https://publicdelivery.org/what-is/ben-day-dots/)
- [Roy Lichtenstein - Guy Hepner](https://guyhepner.com/news/312-roy-lichtenstein-deconstructing-culture-redefining-art-connecting-the-dots/)
- [Rosa Menkman - Glitch Studies Manifesto](https://beyondresolution.info/Glitch-Studies-Manifesto)
- [Keijiro Takahashi - KinoDatamosh (GitHub)](https://github.com/keijiro/KinoDatamosh)
- [Compression artifact - Wikipedia](https://en.wikipedia.org/wiki/Compression_artifact)
- [Agate Dragon Games - Glitch shader effect using blocks](https://agatedragon.blog/2023/12/21/glitch-shader-effect-using-blocks-part-2/)
- [Halisavakis - Glitch image effect shader](https://halisavakis.com/my-take-on-shaders-glitch-image-effect/)
- [Vuk Cosic - Wikipedia](https://en.wikipedia.org/wiki/Vuk_%C4%86osi%C4%87)
- [BAMPFA - Vuk Cosic: ASCII History of Moving Images](https://bampfa.org/program/vuk-%C4%87osi%C4%87-ascii-history-moving-images)
- [Alex Harri - ASCII characters are not pixels](https://alexharri.com/blog/ascii-rendering)
- [Codrops - Creating an ASCII Shader Using OGL](https://tympanus.net/codrops/2024/11/13/creating-an-ascii-shader-using-ogl/)
- [Ian Parberry - ASCII Art on a Pixel Shader](https://ianparberry.com/art/ascii/shader/)
- [Shadertoy - ASCII Art](https://www.shadertoy.com/view/lssGDj)
- [GStreamer - glshader documentation](https://gstreamer.freedesktop.org/documentation/opengl/glshader.html)
- [Cat-in-136 - Porting GLSL Sandbox effect to GStreamer glshader](https://cat-in-136.github.io/2020/05/port-glsl-sandbox-effect-to-gstreamer-glshader.html)
- [gst-shadertoy scripts (GitHub)](https://github.com/jolivain/gst-shadertoy)
- [GStreamer - GstGLFilter documentation](https://gstreamer.freedesktop.org/documentation/gl/gstglfilter.html)
- [Sorting pixels with WebGL - Tim Severien](https://tsev.dev/posts/2017-08-17-sorting-pixels-with-webgl/)
- [haxademic pseudo-pixel-sorting shader (GitHub)](https://github.com/cacheflowe/haxademic/blob/master/data/haxademic/shaders/filters/glitch-pseudo-pixel-sorting.glsl)
