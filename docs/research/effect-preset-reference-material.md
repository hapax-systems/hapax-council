# Effect Preset Reference Material

Canonical source material for all 28 compositor shader presets. Each effect has 4 defining visual characteristics verified against authentic reference works. These are the A+ standard — every preset must satisfy all 4 characteristics for its type.

## Spatial Effects

### VHS
**Reference:** Nam June Paik *TV Garden* (1974); Boards of Canada *Music Has the Right to Children* (1998)
1. Horizontal scan-line banding with uneven luminance across alternating lines
2. Chroma bleed — red/blue channels offset horizontally 2-4px, green anchored
3. Head-switching noise: distorted, horizontally displaced pixels at bottom 5-8% of frame
4. Tracking artifacts: horizontal bands of static that roll vertically at irregular intervals

**Bad:** Uniform CRT scanlines with no color separation or tracking noise. Darkening every other row is CRT, not VHS tape.

### Halftone
**Reference:** Roy Lichtenstein *Whaam!* (1963); Andy Warhol *Marilyn Diptych* (1962)
1. Discrete circular dots on visible grid — dot size varies with source luminance
2. Each color channel uses different screen angle producing rosette pattern
3. Visible white substrate between dots in highlight regions
4. Moire interference patterns where screen angles interact

**Bad:** Uniform dot size (stipple) or single-angle dots that look like grid overlay.

### Nightvision
**Reference:** CNN Gulf War Baghdad coverage (1991); Kathryn Bigelow *Zero Dark Thirty* (2012)
1. Monochrome phosphor-green (P43 ~545nm) with yellow-green tint in highlights
2. Bright-source blooming: point lights produce soft radial halo 3-5x actual area
3. Intensifier tube grain: high-frequency scintillation noise fixed to sensor, not scene
4. Circular vignette with hard black falloff at ~85% radius

**Bad:** Green tint with film grain. Missing bloom, fixed-pattern scintillation, circular hard vignette.

### Thermal
**Reference:** FLIR Systems thermography; John McTiernan *Predator* (1987)
1. False-color palette: iron bow (black-blue-magenta-orange-yellow-white) or rainbow
2. Body heat brightest; ambient mid-range; sky/glass dark
3. No texture detail in uniform-temperature regions — flat color bands
4. Sharp thermal edges at material boundaries differing from visual edges

**Bad:** Color LUT on normal brightness image. Real thermal has completely different contrast relationships.

### Pixsort
**Reference:** Kim Asendorf *Mountain* pixel sorting (2010-2012); Rosa Menkman *Vernacular of File Formats* (2010)
1. Contiguous streaks of pixels reordered by brightness along scan rows/columns
2. Sharp threshold boundaries: sorted regions begin/end abruptly at brightness threshold
3. Directional coherence: all streaks run parallel
4. Original image preserved in unsorted regions, creating legible-to-abstract gradient

**Bad:** Random pixel displacement. Pixsort is deterministic and direction-locked, not scatter.

### ASCII
**Reference:** Vuk Cosic *Deep ASCII* (1998); aalib/libcaca (1997+)
1. Fixed-width character grid, character selected by luminance density (space-dot-colon-o-8-@-#)
2. Visible monospaced grid with uniform cell aspect ratio (~2:1 height:width)
3. Limited tonal range: 8-12 discrete brightness levels
4. Dramatically lower spatial resolution — only large shapes survive

**Bad:** Overlaying ASCII text on normal image. Real ASCII replaces pixels entirely.

### Sculpture (Rutt-Etra)
**Reference:** Bill Rutt & Steve Etra *Rutt/Etra Video Synthesizer* (1973); Steina & Woody Vasulka
1. Horizontal scan lines separated in space, displaced vertically by source brightness
2. Bright regions push lines up; dark pull down — height-field topographic appearance
3. Perspective foreshortening: lines closer together toward top
4. Wire-frame: single-pixel strokes on black, no fill between lines

**Bad:** Horizontal line overlay without brightness displacement. Filling between lines destroys wire-frame character.

### Silhouette
**Reference:** Saul Bass *Anatomy of a Murder* titles (1959); Kara Walker installations
1. Binary black-on-white with no intermediate gray — hard threshold
2. Recognizable figure outline preserved by contour alone
3. All interior detail eliminated — no texture, no shading within figure
4. Optional 1-2px bright edge-detect contour tracing figure boundary

**Bad:** High-contrast posterization retaining interior gradients. Any internal detail breaks the silhouette.

### Dither (Retro)
**Reference:** Original Apple Macintosh (1984); Bill Atkinson dithering; Floyd-Steinberg (1976)
1. Strictly 1-bit output: every pixel is black or white only
2. Visible repeating Bayer matrix pattern (ordered) or organic noise-like distribution (error diffusion)
3. Smooth gradients become dot-density gradients — tone from spatial frequency
4. Hard edges produce clean boundaries; soft edges produce dissolving fringe

**Bad:** Adding random monochrome noise. Dithering is structured error distribution. More than 2 colors defeats the constraint.

### Glitch Blocks
**Reference:** Rosa Menkman *Vernacular of File Formats* (2010); JPEG/MPEG compression artifacts
1. Rectangular macro-block artifacts on 8x8 or 16x16 grid
2. Some blocks freeze, show wrong region, or smear; neighbors intact
3. Color channel divergence in corrupted blocks: shifted hue, single-channel blowout
4. I-frame vs P-frame distinction: static corruption vs motion-drag

**Bad:** Random pixel noise or uniform static. Real corruption is block-structured and grid-aligned.

### Neon
**Reference:** Steven Lisberger *Tron* (1982); Kavinsky *OutRun* (2013)
1. Edge-detection: only contours visible as bright lines on pure black
2. Bloom/glow: soft gaussian (8-20px radius) fadeout from each edge
3. High-saturation limited palette (cyan, magenta) with white-hot core
4. No interior fill: surfaces between edges are black

**Bad:** Colored edges without glow. Missing white core with colored bloom falloff.

### Kaleidoscope
**Reference:** Jordan Belson *Allures* (1961); Joshua White *Joshua Light Show* (1968-70)
1. Radial symmetry: frame divided into N equal angular wedges mirrored around center
2. One wedge contains source; others are reflections producing bilateral symmetry
3. Mandala-like patterns at center where wedge tips converge
4. Seamless mirror boundaries — no visible seams

**Bad:** Tiling without mirroring (pinwheel, not kaleidoscope). Visible seams.

### Tunnel Vision
**Reference:** Kubrick/Trumbull *2001: A Space Odyssey* stargate (1968); Hitchcock *Vertigo* dolly zoom (1958)
1. Strong radial vignette: clear center to near-black edges
2. Radial zoom-blur streaks from center outward, intensifying at edges
3. Center sharp, periphery stretches radially
4. Optional concentric barrel distortion

**Bad:** Simple circular vignette without radial motion blur. Dark border alone is just a vignette.

### Mirror/Rorschach
**Reference:** Hermann Rorschach *Psychodiagnostik* inkblots (1921); Warhol *Double Elvis* (1963)
1. Perfect bilateral symmetry across vertical center axis
2. Seamless mirror axis — no visible line or gap
3. Source from one half flipped to generate other
4. Pareidolic forms emerge (faces, creatures) from bilateral symmetry

**Bad:** Two copies without flipping (duplication, not mirroring). Visible center seam.

### Fisheye
**Reference:** Nikon 6mm f/2.8; skateboard video culture; Hype Williams
1. Radial barrel distortion — straight lines bow outward, curvature increases toward edges
2. Center undistorted; magnification decreases radially
3. Circular vignette or hard crop at extreme FOV
4. Chromatic aberration at extreme edges

**Bad:** Uniform magnification (just zoom). Pincushion distortion (opposite).

### Voronoi Crystal
**Reference:** Voronoi in nature (giraffe skin, mudflat cracks); Casey Reas *Process* (2004-2010)
1. Each cell contains single sampled color from seed point
2. Cell edges equidistant between seeds — visible as thin lines
3. Legible cell count (50-500); too few = posterization, too many = invisible
4. Seed points drift slowly, reshaping cells organically

**Bad:** Regular grid (pixelation). Cells averaging color instead of sampling seed.

## Temporal Effects

### Ghost/Echo
**Reference:** Bill Viola *The Greeting* (1995); Gary Hill *Tall Ships* (1992)
1. Semi-transparent prior-frame copies (30-60% opacity) visible with current frame
2. Trailing edges show smooth opacity gradient — newest brightest, oldest faintest
3. Static areas remain sharp and opaque; only motion produces echoes
4. Echo color desaturates toward cooler tones as it ages

**Bad:** Uniform opacity across all echoes. Ghosting on static background.

### Trails
**Reference:** Nam June Paik *Electronic Superhighway* (1995); Golan Levin *Messa di Voce* (2003)
1. Brightness accumulates additively — overlapping trails blow out to white
2. Trail length proportional to movement speed
3. Colors shift toward white/warm as trails overlap (additive mixing)
4. Trails fade over 0.5-2 seconds

**Bad:** Trails that darken (alpha blend instead of additive). Uniform trail length.

### Feedback
**Reference:** Nam June Paik *TV Buddha* (1974); Vasulka *Noisefields* (1974)
1. Nested self-similar tunneling — image within image (infinite regress)
2. Slight zoom (1.01-1.05x per iteration) creates spiral convergence
3. Color saturation intensifies with recursion, collapsing to dominant hue
4. Rotational drift (0.5deg/frame) creates visible spiral geometry

**Bad:** No zoom or rotation (that's echo). Clips to white after 2 frames.

### Datamosh
**Reference:** Takeshi Murata *Monster Movie* (2005); Chairlift *Evident Utensil* (2009)
1. Motion vectors from one context applied to pixel data from another
2. Block-grid structure visible (8x8 or 16x16 macroblocks)
3. I-frame removal causes content to bloom into wrong motion field
4. Color banding in flat areas from quantization artifacts

**Bad:** Random noise (that's bitcrushing). Uniform distortion (real datamosh follows motion vectors).

### Diff/Motion Detection
**Reference:** Rybczynski *Tango* (1980); MIT Eulerian Video Magnification (2012)
1. Static background renders black; only moving pixels illuminated
2. Leading and trailing edges of motion appear as bright outlines
3. Low-level noise speckle from sensor noise
4. Bidirectional: both brightening and darkening produce positive values

**Bad:** No threshold (noise lights entire frame). Only luminance diff when channels shift independently.

### Slitscan
**Reference:** Douglas Trumbull *2001* stargate (1968); Golan Levin *Yellowtail* (1998)
1. One spatial axis maps to time — vertical stripe per frame assembles panoramic time-image
2. Stationary objects = horizontal streaks; moving objects = warped diagonals
3. Speed determines width (fast = thin, slow = wide)
4. Temporal discontinuity at scan boundary

**Bad:** Uniform horizontal stretch (scaling, not slitscan). No visible temporal axis.

### Stutter/Screwed
**Reference:** DJ Screw *Chapter 8* (1994); Ryoji Ikeda *dataplex* (2005)
1. Frame freezes for irregular durations (2-8 frames), then jumps
2. Playback rate < real-time (0.5-0.7x) creating drag
3. Repeated micro-segments: same 3-5 frames loop 2-4x before advancing
4. Temporal gaps — some frames skipped, creating jump cuts in continuous motion

**Bad:** Metronomic stutter (lacks human DJ feel). Simply slowing playback.

### Heartbeat
**Reference:** Rafael Lozano-Hemmer *Pulse Room* (2006); Christian Marclay *The Clock* (2010)
1. Rhythmic scale oscillation (1-3%) at 50-100 BPM
2. Sharp systolic attack, slower diastolic decay (not sinusoidal)
3. Brightness/saturation peaks on beat
4. Amplitude varies with emotional state

**Bad:** Sinusoidal oscillation. Constant amplitude. >120 BPM reads as vibration.

## Combination/Atmosphere Presets

### Ambient
**Reference:** James Turrell *Aten Reign* (2013); Olafur Eliasson *The Weather Project* (2003)
1. Global color temperature shift without destroying image structure
2. Reduced contrast: shadows lift, highlights compress (fog-like)
3. Subtle edge softening (1-2px Gaussian)
4. Glacially slow transitions (10-30s minimum crossfade)

**Bad:** Solid color overlay obscuring content. Harsh or rapid transitions.

### Trap
**Reference:** Ryan Trecartin *I-Be Area* (2007); HEALTH *USA Boys* (2009)
1. Multiple simultaneous glitch techniques layered
2. High contrast / oversaturated — blacks crushed, highlights clipped
3. Rapid unpredictable mode switching (sub-second)
4. Partial coherence — original remains partially legible

**Bad:** Single technique uniformly applied. All-white or all-noise.

### Bloom (component)
**Reference:** Ridley Scott *Blade Runner* (1982); Terrence Malick / Emmanuel Lubezki
1. Bright pixels bleed into dark surroundings — radius proportional to brightness
2. Threshold-based: only bright pixels bloom; shadows unaffected
3. Soft Gaussian falloff from source
4. Slight desaturation in bloom region (shift toward white)

**Bad:** Uniform blur (bloom requires brightness threshold). Bloom on dark areas.
