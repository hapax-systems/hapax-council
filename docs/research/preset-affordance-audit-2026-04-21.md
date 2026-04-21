# Preset affordance audit

- families: 5
- disk presets: 30
- thin families (<3 members): 0
- family entries missing on disk: 0
- disk presets orphaned: 3

## A. Thin families (<3 members)

(none — every family meets the variety floor)

## B. FAMILY_PRESETS entries missing on disk

(none)

## C. Disk presets not in any FAMILY_PRESETS

- `clean.json`
- `reverie_vocabulary.json`
- `shader_intensity_bounds.json`

## D. Qdrant `fx.family.*` drift

- qdrant entries: 4
- in `FAMILY_PRESETS` but not in Qdrant:
  - `fx.family.neutral-ambient`
