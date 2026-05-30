# Screwm Information-Surface Texture Framework

Authority: `CASE-SCREWM-QUAKE-MIGRATION-20260523`

Status: operative supplement to
`config/screwm-quake-surface-contracts.json`.

## Principle

Textures are allowed in the Quake/DarkPlaces Screwm only when they act as
information surfaces. A texture must carry orientation, state, rhythm, signal,
provenance, liveness, or clean-room Homage grammar. It must not read first as a
real-world material, a Quake scenic texture, or decorative tiling.

## Admissible Vocabulary

- `void_substrate`: dark spatial receiver; supports depth without claiming a
  material identity.
- `alignment_lattice`: sparse linework for path, wall, and ceiling orientation.
- `path_rhythm_field`: walkable cadence and pause-node hints.
- `state_signal_panel`: bounded texture grammar for scalar/state fields.
- `terminal_glyph_field`: clean-room CP437/terminal-style information density.
- `clean_room_homage_chrome`: procedural BitchX / ACiD / Enlightenment lineage,
  never copied source pixels.
- `live_media_receiver`: deterministic mount target for camera, YouTube, ward
  atlas, ticker, or later Pango/tmux media.
- `drift_carrier`: geometry or texture that makes compositor drift spatial.
- `provenance_ticker`: operational text/state/provenance surface.
- `attention_object_skin`: OARB/AoA media surface constrained by object fit.

## Failure Predicates

Release blocks when:

- A room texture can be named as stone, wood, metal, brick, ceiling tile, or
  Quake texture before it can be named by information role.
- Repetition reads as decorative tiling rather than spatial encoding.
- A Homage texture embeds copied source pixels rather than clean-room grammar.
- A surface has no declared relation to path orientation, ward placement, source
  state, or drift/compositor behavior.
- Texture detail competes with media legibility at the intended inspection
  station.

## Implementation Consequences

Room surfaces use low-ambient DarkPlaces BSP collision/occlusion plus large-scale
Scroom WAD textures. Dynamic content enters through live texture slots, CSQC
light/state coupling, model skins, and later spatial text/quads. Static WAD
textures are fallback carriers and alignment fields, not the value layer.

For Homage, the portable framework must ship mechanisms and contracts. Specific
lineage choices, source risk, palette decisions, and distribution concerns stay
inside swappable Homage packs.

## Operative Notes From 2026-05-27 Pass

- Quake MIPTEX surfaces do not carry the generator's RGB palette as the runtime
  authority; DarkPlaces resolves texture indices through the engine palette.
  Therefore room substrates must use deliberately near-black indices and reserve
  high indices for sparse signal marks.
- Room texture scale is part of the contract. If repeated cells read as panels,
  tiles, masonry, or metal plates, the scale/grammar fails even when the source
  texture is procedural.
- Live media remains the truth layer for OARB, camera wards, ticker wards, and
  atlas-fed wards. WAD placeholders are fallback/provenance surfaces only.
- GLSL is the aggregate field: it may bind Quake and Hapax output with drift,
  chroma, scan, dust, edge light, and feedback-like veils, but it must not carry
  individual ward semantics without an explicit mask/ID/depth contract.
- OBS/direct `/dev/video52` witnesses are mandatory for each material pass. The
  release witness is the actual video route, not a theoretical map preview.
