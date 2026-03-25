# Visual Effects: Authentic Source Material and Defining Characteristics

Research compiled from authoritative sources, practitioners, and technical references.
Each effect includes origin, 4+ defining visual characteristics, and authenticity criteria.

---

## 1. Ghost (Transparent Echo / Afterimage)

**Origin:** Analog video processing, 1970s. CRT phosphor persistence creates natural
afterimages as excited phosphors decay exponentially. Hardware video processors like the
Abekas DVE and Pinnacle systems offered "trails" or "echo" modes that accumulated frames
in a buffer with controllable decay. The effect also occurs as an analog broadcast artifact
when signal reflections create leading or lagging duplicates of the primary image.

**Defining Visual Characteristics:**

1. **Exponential opacity decay** -- Each successive echo frame is progressively more
   transparent, following the phosphor persistence curve. Not linear fade; the newest
   echo is brightest, older ones fall off rapidly.
2. **Temporal offset with spatial coherence** -- Echoes are displaced in time but
   maintain the spatial structure of the original frame. Motion creates visible
   separation between ghost layers.
3. **Additive luminance accumulation** -- Ghost layers add light, never subtract.
   Bright regions bloom and saturate; dark regions remain relatively clean. The
   overall image trends brighter with more echoes.
4. **Color channel smearing** -- In analog systems, chroma and luma decay at different
   rates. Ghost trails can shift hue slightly, with color bleeding ahead of or behind
   the luminance echo.
5. **Soft edge dissolution** -- Ghost copies lose sharpness progressively. Fine detail
   disappears first; only broad shapes persist in the oldest echoes.

**Right vs Wrong:** Right: echoes feel like phosphor afterglow -- bright, additive,
soft-edged, with natural exponential falloff. Wrong: uniform opacity across all echoes
(looks like simple duplicate layers), hard-edged copies, or ghosts that darken the image.

---

## 2. Trails (Bright Additive Motion Trails)

**Origin:** Nam June Paik and Shuya Abe, Paik-Abe Video Synthesizer (1969-1972),
built at WGBH-TV Boston. The synthesizer could receive external camera sources and
manipulate color and shape in real time, producing "vibrant nervous color" unique to
video. Used in "Global Groove" (1973), pioneering morphing and collaging of moving
images. The synthesizer was made available to the public -- Paik encouraged visitors
to play with their own footage.

**Defining Visual Characteristics:**

1. **Saturated, luminous, additive color** -- Paik's synthesizer produced highly
   saturated phosphor-projected color that "caresses the viewer." Trails are not
   muted or transparent; they glow with full chroma intensity.
2. **Continuous smear, not discrete copies** -- Unlike ghost (discrete echo frames),
   trails produce a continuous painterly smear along the motion path. Movement leaves
   an unbroken ribbon of color.
3. **Bright-on-dark bias** -- Trails are additive: they accumulate light. Dark
   backgrounds let trails bloom freely; bright backgrounds flatten the effect. The
   canonical look is vivid trails against black.
4. **No decay within the trail body** -- The trail itself is uniformly bright along
   its length while active, fading only at the oldest tail end. This distinguishes
   it from ghost's progressive transparency.
5. **Motion-dependent thickness** -- Faster motion produces wider, more stretched
   trails. Slow or stationary elements show minimal effect. The trail width encodes
   velocity.

**Right vs Wrong:** Right: vivid, hot, continuous ribbons of color that make movement
visible as a physical trace -- think light painting with a body. Wrong: faint transparent
copies (that is ghost, not trails), trails that subtract light or desaturate, or discrete
stepped frames instead of continuous smear.

---

## 3. Datamosh (Glitch Codec Artifacts)

**Origin:** Takeshi Murata, circa 2003, sparked by a failed video download. His 2005
work "Monster Movie" is in the Smithsonian permanent collection. The technique exploits
video compression (H.264/MPEG) by manipulating I-frames (complete reference images) and
P-frames (motion-prediction delta frames). Two primary methods: I-frame removal (delete
keyframes so P-frames apply motion vectors to wrong base image) and P-frame duplication
(replicate predictive frames to create bloom/trailing).

**Defining Visual Characteristics:**

1. **Pixel bleeding across scene boundaries** -- Colors and shapes from one scene
   "melt" into the next as P-frames apply motion vectors to the wrong reference.
   Recognizable subject matter dissolves into abstract color flows.
2. **Block-structured distortion** -- Artifacts follow the codec's macroblock grid
   (typically 16x16 or 8x8 pixel blocks). Distortion is not random noise; it has
   visible rectangular structure.
3. **Motion vector hallucination** -- Regions of the image slide, stretch, and warp
   according to motion vectors that no longer correspond to actual movement. Creates
   organic "flowing" distortion that tracks phantom motion.
4. **Color smearing with palette preservation** -- The palette of the source frames
   persists even as shapes dissolve. You see the right colors in the wrong places,
   creating a stained-glass or watercolor quality.
5. **Temporal instability** -- The effect is not static; it evolves frame to frame as
   each P-frame compounds errors from the previous. The image is in constant flux.

**Right vs Wrong:** Right: organic, flowing, almost liquid distortion that follows
macroblock structure and motion vectors -- it looks like the codec is dreaming. Wrong:
random noise overlay, uniform blur, or static distortion that does not evolve over time.
Real datamosh has visible block structure and directional flow.

---

## 4. VHS (Lo-Fi Tape Aesthetic)

**Origin:** JVC Video Home System, 1976. Consumer videotape format with ~240 lines of
horizontal resolution and ~40 lines of color resolution. Artifacts arise from the
helical-scan drum, analog signal path, and magnetic tape degradation over time.

**Defining Visual Characteristics:**

1. **Head-switching noise** -- Horizontal distortion bar at the bottom ~10-15 lines of
   the frame, caused by the interval when video heads switch during playback. Appears
   as a jagged, displaced band. Always at the bottom; it was hidden by CRT overscan
   but visible in digital captures.
2. **Tracking misalignment** -- Horizontal bands of noise, displacement, and tearing
   that drift vertically through the frame. Caused by tape path misalignment between
   recording and playback VCRs. The bars are wavy, not perfectly horizontal.
3. **Chroma bleed and low color resolution** -- Only ~40 lines of color resolution
   means colors bleed heavily into adjacent areas. Reds oversaturate and smear.
   Overall palette shifts toward washed-out blue or green tint. Skin tones drift.
4. **Dropout and oxide shedding** -- Momentary white or black horizontal streaks caused
   by missing magnetic oxide particles on the tape surface. More frequent on old,
   worn, or cheap tapes. Appear as brief horizontal flashes.
5. **Tape noise and luminance instability** -- Visible noise grain throughout, with
   luminance fluctuating slightly frame to frame. Horizontal time-base errors cause
   the image to jitter or wobble subtly.
6. **Scan lines** -- Visible interlaced scan line structure, especially on paused or
   slow-motion footage where interlace combing artifacts appear.

**Right vs Wrong:** Right: the artifacts are analog and horizontal -- tracking bars,
head-switching noise, chroma bleed all run horizontally because that is how the signal
is scanned. The color is washed out with a characteristic tint, not just desaturated.
Wrong: digital noise (random pixel static), vertical glitches, overly clean/sharp image
with a filter overlay, or uniform grain that does not vary with signal content.

---

## 5. Neon (Color-Cycling Glow Bloom)

**Origin:** Neon signage (Georges Claude, 1910s) and CRT phosphor glow. The visual
effect combines the physics of gas-discharge tubes (sharp spectral emission lines creating
pure, saturated color) with optical bloom from camera lenses (bright sources scatter light
through lens elements, creating halos and chromatic aberration fringes). CRT bloom occurs
when the electron beam overdrives phosphors, causing light to scatter within the glass
faceplate (halation).

**Defining Visual Characteristics:**

1. **Core-to-edge luminance gradient** -- The brightest center (near white/saturated
   color) bleeds outward into a soft halo. The core is overexposed; the glow extends
   well beyond the source geometry. This is bloom, not a uniform tint.
2. **Chromatic aberration fringing** -- Lens optics bend different wavelengths
   differently, producing colored fringes (typically cyan/magenta or red/blue) at the
   edges of bright elements. Especially visible against dark backgrounds.
3. **Color cycling / hue rotation** -- Colors shift through the spectrum over time,
   emulating the look of animated neon or color-organ effects. The cycling is smooth
   and continuous, not stepped.
4. **High saturation against deep black** -- Neon glow reads correctly only against
   darkness. The contrast between saturated, luminous color and near-black surroundings
   is essential. Muted backgrounds kill the effect.
5. **Phosphor persistence trails** -- Moving neon elements leave brief afterglow trails
   due to phosphor decay, creating a softer version of the trails effect specific to
   the glowing regions.

**Right vs Wrong:** Right: bright cores with soft, physically-motivated bloom falloff;
chromatic fringing at edges; deep black surroundings; colors feel like they emit light.
Wrong: uniform colored overlay, glow that does not fall off with distance from source,
no chromatic aberration, or neon on a bright background (kills the luminous contrast).

---

## 6. Screwed (Houston Chopped and Screwed Visual Aesthetic)

**Origin:** DJ Screw (Robert Earl Davis Jr.), Houston TX, 1990s. Musical technique:
slowing tempo to 60-70 BPM, reducing pitch, chopping/repeating phrases, layering
freestyles. Culturally inseparable from Houston slab culture (customized cars, candy
paint, swangas) and the codeine/promethazine ("purple drank") experience. The 2019
"Slowed and Throwed" exhibition at Contemporary Arts Museum Houston established the
visual vocabulary: artists "appropriating, mashing up, collaging, and mutating
photographic inputs, in addition to slowing time" -- parallel to DJ Screw's musical
methods.

**Defining Visual Characteristics:**

1. **Temporal drag / slowed time** -- Everything moves at reduced speed, creating a
   viscous, syrupy quality. Not just slow-motion; the deceleration should feel heavy
   and weighted, like moving through liquid. Frame interpolation artifacts are
   acceptable and even desirable.
2. **Purple/violet color cast** -- The signature color of codeine syrup pervades the
   palette. Deep purples, violets, and magentas tint the entire image. Not a subtle
   wash -- it is an overt chromatic identity.
3. **Chopped repetition / stutter** -- Visual equivalent of DJ Screw's chopping: brief
   segments repeat or stutter, creating a rhythmic hiccup in the temporal flow. Not
   random glitch; it is rhythmically placed.
4. **Low-fi degradation and blur** -- Image quality is deliberately degraded: soft
   focus, video noise, reduced resolution. Reflects the DIY aesthetic of Screwston
   culture -- self-filmed, lo-fi, bedroom production. Clarity is antithetical to the
   aesthetic.
5. **Dream-like spatial distortion** -- Wavy, floating quality where geometry is not
   rigid. Subtle warping or swimming of the image field, evoking the dissociative
   perceptual state the music soundtrack induces.

**Right vs Wrong:** Right: the visual should feel narcotic -- heavy, slow, purple-tinted,
hazy, with rhythmic stutters that mirror the musical chopping. It evokes a specific
cultural and pharmacological experience rooted in Houston. Wrong: generic slow-motion
without the purple cast or degradation; clean, high-resolution footage that happens to
be purple; or random glitch without rhythmic intent.

---

## 7. Trap (Dark Underground Oppressive Visual)

**Origin:** Atlanta trap music scene (T.I., Gucci Mane, Jeezy, 2000s), evolved through
trap metal (Ghostemane, Scarlxrd), phonk, and necrotrap subgenres. The visual aesthetic
draws from urban environments, surveillance culture, and deliberately degraded image
processing. The Aesthetics Wiki documents distinct sub-aesthetics: trap metal (gothic
imagery, inverted crosses), necrotrap (deliberately degraded processing), and trillwave
(neon accents against darkness).

**Defining Visual Characteristics:**

1. **Dominant black with selective accent color** -- Deep blacks, dark blues, and
   purples form 70%+ of the palette. Accent colors (neon red, electric blue, toxic
   green) appear sparingly and at high contrast. The darkness is structural, not
   incidental.
2. **Heavy vignette** -- Aggressive edge darkening focuses attention inward and creates
   a claustrophobic, tunneled field of view. The vignette is not subtle -- it
   aggressively eats the frame edges.
3. **Strobe / flash synchronization** -- Brief, intense white or colored flashes
   synchronized to beat hits. Creates a stroboscopic, disorienting rhythm. The
   flashes are harsh and abrupt, not smooth fades.
4. **Grain, noise, and deliberate degradation** -- The image is intentionally degraded
   with heavy grain, sharpening artifacts, and crushed blacks. Necrotrap pushes this
   further with stretching and distortion. The degradation signals underground
   authenticity.
5. **Urban environmental signifiers** -- Dimly lit streets, concrete, graffiti,
   smoke/haze. Even when abstracted, the environmental feel is enclosed, nocturnal,
   and industrial.

**Right vs Wrong:** Right: oppressive, claustrophobic, and rhythmically aggressive. The
darkness is not absence but presence -- it presses in. Accents cut through like warning
signals. Wrong: evenly lit dark scene (darkness must have spatial structure via vignette),
clean/polished image (must be degraded), or colorful palette (color is the exception,
not the rule).

---

## 8. Diff (Motion Detection / Frame Differencing)

**Origin:** Computer vision technique, foundational to video surveillance and motion
analysis. The method subtracts consecutive frames to isolate moving elements.
Mathematically: diff(x,y) = |frame_n(x,y) - frame_n-1(x,y)|. Used extensively in
interactive art (Processing, openFrameworks communities) and surveillance systems.
Kasper Kamperman's computer vision tutorials document the technique's application in
creative coding.

**Defining Visual Characteristics:**

1. **Black background with bright motion edges** -- Static regions produce zero
   difference (black). Only pixels that changed between frames appear as bright areas.
   The background disappears entirely.
2. **Double-edge outlining** -- Moving objects show bright edges at both their previous
   position (where they left) and current position (where they arrived), creating a
   characteristic double-contour effect.
3. **Brightness proportional to velocity** -- Faster movement creates larger pixel
   differences and thus brighter output. Slow movement produces dim traces; fast
   movement produces bright flashes.
4. **Noise floor visibility** -- Camera sensor noise creates a faint, shimmering grain
   across the entire frame even in static scenes. This "alive" quality distinguishes
   real frame differencing from a simple mask.
5. **Ghostly, skeletal appearance** -- Only the boundaries of motion are visible, not
   filled shapes. A walking person appears as a moving outline, not a solid
   silhouette. Internal texture only appears when it moves relative to itself.

**Right vs Wrong:** Right: black field with bright, jittery motion edges that shimmer
with sensor noise. Static objects are invisible. Movement is revealed as luminous traces.
Wrong: full-color image with highlighted motion areas (that is motion masking, not
differencing), clean black background without noise floor, or filled bright regions
instead of edge-only response.

---

## 9. Pixsort (Pixel Sorting)

**Origin:** Kim Asendorf, 2010, Processing sketch released as open source in 2012.
The ASDF Pixel Sort algorithm sorts pixels within rows or columns based on luminosity,
hue, or brightness thresholds. Asendorf described it as "meeting chaos half-way" --
imposing partial order on image data. No actual glitch occurs; it is a generative
mechanism with precision. The technique became synonymous with glitch art as a whole,
spawning an entire recognizable style.

**Defining Visual Characteristics:**

1. **Directional streaking along sort axis** -- Pixels rain down (vertical sort) or
   streak sideways (horizontal sort) in semi-orderly clusters. The streaks follow the
   sort direction strictly -- this directionality is the signature.
2. **Threshold-bounded intervals** -- Sorting only occurs within intervals defined by
   brightness thresholds. Regions too dark or too bright remain untouched. This creates
   alternating bands of sorted chaos and pristine image.
3. **Color gradient within streaks** -- Sorted pixel runs create smooth gradients from
   dark to light (or by hue) within each streak. The gradients are precise, not noisy,
   because they result from actual sorting.
4. **Preserved recognizability** -- Unlike total image destruction, pixel sorting
   preserves enough structure that the source image remains partially recognizable.
   Faces, shapes, and compositional structure persist beneath the sorting. This tension
   between order and chaos is the aesthetic core.
5. **Textural rhythm** -- The sorted regions create a rhythmic fuzz or rain-like
   texture that "tickles the optic nerve." The texture is regular because sorting
   produces consistent gradients, not random noise.

**Right vs Wrong:** Right: crisp, directional streaks with smooth color gradients within
sorted regions, preserving source image recognizability. Wrong: random noise or blur
(sorting is precise, not random), bidirectional streaking (sorting has one axis), or
complete image destruction (the source must remain partially legible).

---

## 10. Slit-Scan (Temporal Displacement)

**Origin:** Slit-scan photography dates to the 1800s (moving slit over photographic
plate). Douglas Trumbull created the iconic Stargate sequence in "2001: A Space Odyssey"
(1968) at age 25: a 6ft metal sheet with a narrow slit placed before a 12ft backlit
glass panel, with ~1 minute exposures per frame on 65mm Mitchell camera. The camera ran
36 hours continuously per take. Trumbull said the Stargate represented "a transit into
another dimension -- something completely abstract."

**Defining Visual Characteristics:**

1. **Temporal stratification** -- Different spatial positions in the image correspond
   to different moments in time. The top of the frame may show "second 1" while the
   bottom shows "second 15." The image is not a record of spatial relationships but
   of temporal relationships.
2. **Motion-dependent stretching** -- Moving subjects are stretched or compressed along
   the scan axis based on their velocity relative to the scan direction. Faster
   movement produces more extreme distortion.
3. **Infinite corridor / tunnel convergence** -- When applied to Trumbull's
   configuration (slit moving toward camera), the result is an apparent infinite
   corridor of light converging on a vanishing point, creating an overwhelming sense
   of speed and depth.
4. **Scan-line interlace artifacts** -- When implemented digitally (each scanline from
   a different frame), visible banding or stepping occurs between adjacent time-
   displaced lines. More scanlines reduce this but cannot eliminate it entirely.
5. **Fluid, elastic spatial warping** -- Stationary elements remain coherent while
   moving elements warp fluidly, creating a rubber-sheet quality where the image
   appears to be made of a stretchy temporal material.

**Right vs Wrong:** Right: the image itself encodes time -- you can see temporal
displacement as spatial distortion. Movement causes stretching along the scan axis.
Static elements remain stable. Wrong: uniform motion blur (that is temporal averaging,
not displacement), spatial-only distortion without temporal component, or random warping
without scan-axis directionality.

---

## 11. Thermal (Thermal / IR Camera Look)

**Origin:** Forward-looking infrared (FLIR) imaging, developed for military
applications, now used in building inspection, surveillance, and search-and-rescue.
Thermal cameras detect infrared radiation (heat) and map temperature values to color
palettes. Key palettes: White Hot (grayscale, warm=white), Black Hot (inverted),
Ironbow (purple-black cold to white-yellow hot), Rainbow (blue cold to red hot).

**Defining Visual Characteristics:**

1. **Temperature-mapped false color** -- Every pixel represents a temperature value
   mapped to a palette. The canonical Ironbow palette: cold regions are dark
   purple/black, warm regions progress through blue, red, orange, yellow to white.
   Color is data, not aesthetics.
2. **No texture detail, only thermal contours** -- Thermal imaging shows heat
   boundaries, not surface texture. A face appears as a heat blob, not a
   recognizable portrait. Material differences (metal vs skin vs fabric) appear
   based on emissivity and temperature, not visual appearance.
3. **Hot-source blooming and halo** -- Intense heat sources (people, engines, exhaust)
   bloom outward with a bright halo, caused by sensor saturation and optical scatter
   in the germanium lens. The bloom is smooth and radial.
4. **Cool-edge vignette** -- Thermal cameras exhibit non-uniformity with cooler
   readings at edges and corners of the sensor, creating a subtle natural vignette
   in the thermal data.
5. **Low spatial resolution with smooth gradients** -- Thermal sensors have far fewer
   pixels than visible cameras (typically 320x240 or 640x480). Images appear soft
   with smooth temperature gradients between regions, lacking the sharpness of
   visible-light imaging.

**Right vs Wrong:** Right: the image should look like data -- false color mapped from
temperature, with smooth gradients, hot-source bloom, and no visible-light texture
detail. People are bright heat shapes, not recognizable faces. Wrong: color-tinted
normal camera footage (thermal sees heat, not light), sharp texture detail, or random
color assignment not following a thermal palette gradient.

---

## 12. Feedback (Video Feedback Recursion)

**Origin:** Steina and Woody Vasulka, from 1969 onward, at The Kitchen in lower
Manhattan. Created by pointing a camera at the monitor displaying its own output. The
Vasulkas explored feedback loops interpolating both image and sound signals, enabling
live interaction with "intrinsic electronic faculties comparable to synaesthesia."
Steina: "I do not think of images as stills, but always in motion. My video images
primarily hinge upon an undefined sense of time with no earth gravity." They introduced
static, error, delay, and noise to open video to "unstable states."

**Defining Visual Characteristics:**

1. **Infinite recursive tunnel** -- The camera-to-monitor loop creates a picture within
   a picture within a picture, converging on a central vanishing point. This infinite
   regression is the foundational structure.
2. **Fractal self-similarity** -- The recursive structure exhibits mathematical
   properties of iterated function systems (same math as Mandelbrot sets). Patterns
   at different scales resemble each other. The system finds visual attractors.
3. **Extreme sensitivity to physical parameters** -- Tiny changes in camera angle,
   zoom, or position produce dramatically different patterns: centered alignment
   produces symmetric tunnels, horizontal tilt creates spiraling vortices (direction
   matches tilt direction), vertical tilt generates cascading waterfall patterns.
4. **Time-delay evolution** -- Unlike static recursion (Droste effect), video feedback
   includes temporal delay. Each frame transforms the previous frame before feeding
   it back, causing patterns to evolve, pulse, breathe, and migrate over time.
5. **Luminance accumulation and color shift** -- Each recursion pass slightly alters
   brightness and color. Bright areas accumulate toward white; dark areas deepen.
   Color channels shift independently across recursions, producing unexpected hue
   rotations.

**Right vs Wrong:** Right: self-similar recursive structure that breathes and evolves
in real time, with organic sensitivity to parameters. The patterns are emergent, not
designed. Wrong: static zoom effect or simple picture-in-picture (must have temporal
evolution), symmetrical mandala without recursive depth, or artificially generated
fractals that lack the organic quality of analog feedback.

---

## 13. Halftone (Print Dot Grid)

**Origin:** Ben Day process, invented by Benjamin Henry Day Jr. in 1879 for commercial
printing. Uses uniformly sized, evenly spaced colored dots (CMYK) to create shading and
color through optical mixing. Roy Lichtenstein (1961 onward) appropriated the technique
for Pop Art, initially painting dots by hand, later using perforated metal stencils
(from 1962). Halftone printing (variable-size dots for continuous tone) is the related
but distinct photomechanical process.

**Defining Visual Characteristics:**

1. **Uniform dot grid on visible inspection** -- Dots are arranged in a regular grid
   pattern. Ben-Day dots are equal-sized and evenly spaced; halftone dots vary in size
   for tonal gradation. The grid structure must be visible -- it is the aesthetic point.
2. **CMYK color through optical mixing** -- Colors are produced by overlapping dot
   grids in cyan, magenta, yellow, and black at different screen angles. At distance,
   dots merge perceptually into continuous color. Up close, individual dot colors are
   visible.
3. **Screen angle moire potential** -- Each color's dot grid is rotated to a different
   angle (typically C:15, M:75, Y:0, K:45 degrees) to minimize moire patterns. When
   angles are imperfect, visible moire rosette patterns emerge -- a characteristic
   artifact.
4. **Hard dot edges, no anti-aliasing** -- Each dot has a crisp, circular boundary.
   There is no gradual falloff or soft edge. This mechanical crispness distinguishes
   the effect from digital blur or smoothing.
5. **Tonal steps, not continuous gradation** -- Tone is quantized by dot spacing/size.
   Smooth gradients in the source become visible steps between different dot densities,
   especially in midtones.

**Right vs Wrong:** Right: visible, regular dot pattern with crisp edges; CMYK color
separation visible on close inspection; Lichtenstein-scale dots that are part of the
composition, not hidden. Wrong: random dot noise (dots must be on a grid), soft or
blurred dots, full-color pixels (halftone is ink on paper, not RGB), or dots too small
to see (the visibility is the point).

---

## 14. Glitch (Digital Block Corruption)

**Origin:** Glitch art movement, emerging 2000s. Techniques include databending
(opening image files in text/audio editors and corrupting data), generational loss
(repeated compression cycles), and hex editing. Rosa Menkman's "Glitch Moment/um"
(2011) and the GLI.TC/H conferences established theoretical frameworks. Distinct from
datamosh: glitch targets the file/data layer; datamosh targets the codec/compression
layer.

**Defining Visual Characteristics:**

1. **Macroblock fragmentation** -- The image breaks into visible rectangular blocks
   (8x8 or 16x16 pixels) that display wrong color, wrong position, or corrupted data.
   The block grid structure of JPEG/MPEG compression becomes the visible skeleton.
2. **Color banding and posterization** -- Compression quantization becomes visible as
   hard color steps instead of smooth gradients. Colors jump between discrete values,
   creating banded regions.
3. **Horizontal displacement / scan offset** -- Corrupted data causes rows of pixels
   to shift horizontally, creating a characteristic offset or tearing where the image
   appears to slide sideways at certain scan lines.
4. **Data visualization bleed** -- Raw data values become visible as nonsensical color
   patterns, gray noise blocks, or repeated pixel patterns. The underlying data
   structure of the file leaks through the image representation.
5. **Abrupt, discontinuous boundaries** -- Glitch corruption creates hard edges between
   corrupted and uncorrupted regions. There is no gradient or transition -- the image
   switches instantly between normal and destroyed.

**Right vs Wrong:** Right: the corruption follows digital structure -- blocks, scan
lines, compression artifacts. The errors are systematic, not random. You can see the
data format in the corruption pattern. Wrong: analog-style noise (VHS grain, scan lines),
smooth distortion (that is datamosh), or random RGB pixel noise (real glitch follows
block structure).

---

## 15. ASCII (ASCII Art Rendering)

**Origin:** Vuk Cosic, 1996-2001, developed his own software to convert still and
moving images into ASCII characters. His 1998 "ASCII History of Moving Images" converted
classic cinema (Lumiere brothers, Eisenstein's Battleship Potemkin, Psycho, Star Trek)
into ASCII text. Part of the net.art movement. The ASCII Art Ensemble (formed 1998)
developed image-to-text conversion software. Tradition extends back to typewriter art
of the 1960s and early terminal-based image display.

**Defining Visual Characteristics:**

1. **Character-cell grid resolution** -- The image is quantized to a grid of fixed-width
   character cells. Each cell maps to one ASCII character. Resolution is determined by
   character count, not pixel count -- typically much coarser than the source.
2. **Luminance-to-density mapping** -- Characters are selected based on their visual
   density (how much ink/pixels they occupy). Dense characters (@, #, M) represent
   dark areas; sparse characters (., :, `) represent light areas. The mapping must be
   perceptually correct for the effect to read as an image.
3. **Monochrome green-on-black (canonical)** -- Cosic's signature rendering: green
   ASCII characters on a black background, emulating early computer terminals. The
   monochrome constraint forces all tonal information through character density alone.
4. **Loss of smooth contour** -- Curved edges in the source become jagged staircase
   approximations dictated by the character grid. Diagonal lines show visible stepping.
   This coarseness is the aesthetic signature.
5. **Readable as both image and text** -- At distance, the characters merge into a
   recognizable image. Up close, they are legible text characters. This dual-reading
   quality is essential to the concept -- it is language and image simultaneously.

**Right vs Wrong:** Right: characters are chosen for visual density, creating recognizable
images when viewed at distance. The grid structure is visible. Terminal aesthetic (green
on black or white on black). Wrong: colored characters that use color to cheat the
luminance mapping, anti-aliased or variable-width fonts (must be monospace), or characters
chosen for semantic meaning rather than visual density.

---

## 16. Night Vision (Green Phosphor Surveillance)

**Origin:** Generation III image intensifier tubes, developed 1980s, using gallium
arsenide photocathodes and microchannel plates. P-43 phosphor output screen produces
the signature yellow-green image (chosen because human eyes discriminate more shades of
green than any other color and adapt back to darkness faster after green exposure).
L3Harris and Photonis are primary manufacturers. Used in military night vision goggles
(PVS-14, GPNVG-18).

**Defining Visual Characteristics:**

1. **Monochrome green phosphor palette** -- Everything is rendered in shades of
   yellow-green (P-43 phosphor, peak ~545nm). No color information whatsoever. The
   green is not a tint over a color image; it is the only color the phosphor emits.
2. **Scintillation noise** -- Faint, random sparkling effect across the entire image,
   caused by microchannel plate electron multiplication statistics. More pronounced
   in low light. Creates a characteristic "crawling grain" that is alive and
   shimmering, distinct from static film grain.
3. **Bright-source blooming / halo** -- Point light sources (streetlights, muzzle
   flash) produce intense halos and bloom that can wash out surrounding areas. The
   tube's automatic brightness control cannot fully suppress overload from bright
   sources.
4. **Circular field of view with hard edge** -- The image intensifier tube produces a
   circular image, often with a visible dark border. When viewed through binocular
   NVGs, the characteristic figure-8 or circular viewport shape is visible.
5. **Fixed-pattern noise (blemishes)** -- Small bright or dark spots fixed in position,
   caused by imperfections in the microchannel plate film. These cosmetic blemishes
   are unique to each tube and do not move with the image.

**Right vs Wrong:** Right: monochrome green with scintillation grain that shimmers and
crawls, halo blooming around bright sources, circular viewport. The noise is alive.
Wrong: green-tinted color image (NV has no color data), static grain (scintillation
sparkles, it does not sit still), clean image with just a green overlay, or rectangular
field of view without the characteristic round tube shape.

---

## 17. Silhouette (High Contrast Shape-Only)

**Origin:** Backlit cinematography and shadow puppet traditions. In cinema, silhouette
lighting traces through film noir (1940s-50s) and German Expressionism. The technique
places the light source behind the subject and exposes for the background, reducing the
subject to a pure dark shape with a luminous edge. Chiaroscuro lighting (Caravaggio,
Rembrandt) establishes the art-historical precedent of extreme light/dark contrast for
dramatic effect.

**Defining Visual Characteristics:**

1. **Binary tonal reduction** -- The image is reduced to two values: subject (black)
   and background (bright). Internal detail of the subject is completely eliminated.
   No texture, no color, no features within the silhouette -- only shape.
2. **Luminous rim/edge light** -- A thin bright edge outlines the silhouette where
   backlight wraps around the subject's contour. This rim light is what separates
   silhouette from simple black shape on black -- it defines the form.
3. **Shape becomes the sole information carrier** -- With all other visual information
   removed, the pose, gesture, and outline of the subject carry 100% of the
   communicative content. A silhouette must be readable by shape alone.
4. **High-key background** -- The background is uniformly bright or simply luminous
   (sunset, window, backlight). The background-to-subject contrast ratio is extreme,
   typically 10:1 or greater.
5. **No midtones** -- The transition from black subject to bright background is abrupt.
   There may be a narrow gradient at the rim, but the overall image has no midtone
   range. Histogram shows extreme bimodal distribution.

**Right vs Wrong:** Right: pure shape language -- the subject is completely dark with
a luminous edge and bright background. You recognize the subject by outline alone.
Wrong: low-contrast dark image where some detail is still visible (that is underexposure,
not silhouette), colored or textured fill within the shape, or missing rim light
(without the edge, it is just a black blob).

---

## 18. Ambient (Atmospheric Minimal Presence)

**Origin:** Brian Eno, who coined "ambient music" with "Ambient 1: Music for Airports"
(1978) and extended the concept to visual art through decades of video installation and
generative software. His "77 Million Paintings" (2006) generates slowly evolving
light-paintings with ever-changing ambient sound. Eno's principle: ambient art "must be
as easy to ignore as it is to notice" -- it rewards attention with interest but never
demands it. Jim Bizzocchi's "Re:Cycle" research further formalized ambient video as a
medium.

**Defining Visual Characteristics:**

1. **Glacial rate of change** -- Visual evolution is extremely slow, operating on a
   timescale of seconds to minutes per perceptible shift. Changes are continuous and
   gradual, never abrupt. The viewer should not be able to pinpoint exactly when a
   change occurred.
2. **Soft color fields with dissolving boundaries** -- Large areas of soft, blended
   color without hard edges. Reminiscent of Rothko or Mondrian (as Eno explicitly
   referenced). Shapes merge and separate through slow dissolves, not cuts.
3. **Low information density** -- Minimal detail, minimal complexity at any single
   moment. The image carries just enough variation to reward a glance but not enough
   to demand sustained focus. Negative space dominates.
4. **Generative non-repetition** -- The visual is not a loop; it is generated by a
   system that produces infinite variation. No exact state repeats, enabling continuous
   ambient play without the viewer recognizing a cycle.
5. **Environmental integration** -- The visual functions as a light source and spatial
   modifier rather than as a framed image demanding attention. It colors the room,
   creates atmosphere, and facilitates "cognitive drift" rather than demanding cognitive
   engagement.

**Right vs Wrong:** Right: slow, soft, minimal, and genuinely ignorable -- it enriches
the background without ever interrupting foreground activity. Watching it should feel like
watching clouds or water. Wrong: anything that demands attention (sudden changes, high
contrast, fast movement), recognizable looping (breaks the generative spell), high
information density, or visual complexity that pulls focus.

---

## Cross-Reference: Common Failure Modes

| Effect | Most Common Mistake |
|--------|-------------------|
| Ghost | Uniform opacity across echoes (should decay exponentially) |
| Trails | Discrete stepped frames instead of continuous smear |
| Datamosh | Random noise instead of macroblock-structured flow |
| VHS | Digital noise instead of horizontal analog artifacts |
| Neon | Glow without bloom falloff gradient |
| Screwed | Clean slow-motion without purple cast or degradation |
| Trap | Evenly dark without spatial vignette structure |
| Diff | Filled bright regions instead of edge-only response |
| Pixsort | Random noise instead of directional sorted gradients |
| Slit-scan | Uniform motion blur instead of temporal displacement |
| Thermal | Color-tinted camera footage instead of temperature-mapped data |
| Feedback | Static zoom instead of temporally evolving recursion |
| Halftone | Random dot noise instead of regular grid pattern |
| Glitch | Analog noise instead of digital block structure |
| ASCII | Variable-width colored text instead of monospace density mapping |
| Night Vision | Green-tinted color image instead of monochrome phosphor |
| Silhouette | Underexposed image with visible detail instead of pure shape |
| Ambient | Screensaver with recognizable loops instead of generative drift |
