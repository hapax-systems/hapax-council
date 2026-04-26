# Refusal Brief: Tutorial Videos (YouTube / Vimeo)

**Slug:** `leverage-REFUSED-tutorial-videos`
**Axiom tag:** `feedback_full_automation_or_no_engagement`, `single_user`
**Refusal classification:** Operator-physical content production
**Status:** REFUSED — no `agents/tutorial_publisher/`, no Vimeo Pro, no YouTube tutorial channel.
**Date:** 2026-04-26
**Related cc-task:** `leverage-REFUSED-tutorial-videos`
**Related project memory:** `project_livestream_is_research`
**CI guard:** `tests/test_forbidden_social_media_imports.py` (`FORBIDDEN_PACKAGE_PATHS`)

## What was refused

- YouTube channel for tutorials / how-tos
- Vimeo Pro account for tutorial hosting
- `agents/tutorial_publisher/`, `agents/tutorial_videos/`,
  `agents/youtube_tutorials/`, `agents/educational_content/` packages
- Pre-recorded operator-voiced narration tracks
- On-camera operator-presence content production

## Why this is refused

### Operator-physical content production

Tutorial videos imply one of:

- **Operator on-camera** — face / hands / setup visible. Each take
  requires operator-physical presence.
- **Operator-voiced narration** — voiceover recording, take-by-take
  retake decisions, vocal-quality maintenance.
- **Operator-edited timeline** — cut decisions, b-roll selection,
  caption authoring (the kind that requires technical-content
  judgment, not LLM auto-caption).

Each of these is operator-physical. There is no daemon-tractable
pathway through tutorial-video production — quality bar requires
operator iteration on takes + edits.

### Constitutional incompatibility

Per `feedback_full_automation_or_no_engagement` (operator
constitutional directive 2026-04-25T16:55Z): the operator refuses
research / engagement surfaces not fully Hapax-automated. Tutorial
videos would create a content layer that requires sustained
operator-mediated upkeep (edit decisions, channel comment
moderation, retake cycles).

### Livestream IS the research instrument

Per the operator's project memory `project_livestream_is_research`:
all R&D happens via the livestream; no separate voice / recording
sessions exist. Tutorials would create a parallel content track that
duplicates the livestream's role as the singular research-instrument
surface.

The livestream is daemon-tractable end-to-end (compositor +
director + reverie + cameras), with operator-physical presence
folded into the constitutive performance, not into separate
post-production. Tutorials would re-introduce post-production as
an operator-physical step.

## Daemon-tractable boundary

The authorized video surface is the livestream. The livestream
covers educational use cases organically:

- Live demonstration of Hapax components / workflows
- Real-time narration during the constitutive performance
- VOD archives via existing studio-compositor + RTMP infrastructure
  that surface organically through the broadcast feed

Cohort discovery on YouTube happens via livestream archives indexed
by YouTube, not via separately-produced tutorials. The YouTube
algorithm signal arrives through livestream watch-time, not through
tutorial completion rates.

## Existing infrastructure (NOT refused)

The following are livestream infrastructure and remain permitted:

- `agents/video_capture/` — camera capture for the livestream
- `agents/video_processor/` — VOD processing for livestream archives
- `agents/demo_pipeline/video.py` — demo video generation (research
  artefact, not tutorial)
- `agents/studio_compositor/` — GStreamer-based livestream pipeline

The CI guard's `FORBIDDEN_PACKAGE_PATHS` list specifically targets
tutorial-shaped naming (`tutorial_*`, `youtube_tutorials`,
`educational_content`); it does NOT block the legitimate livestream
infrastructure.

## CI guard

`tests/test_forbidden_social_media_imports.py` enforces a path-based
guard. Forbidden paths added:

- `agents/tutorial_publisher/`
- `agents/tutorial_videos/`
- `agents/youtube_tutorials/`
- `agents/educational_content/`

CI fails if any of these directories are introduced.

## Lift conditions

This is a constitutional refusal grounded in the full-automation
envelope + livestream-as-research-instrument stance. Lift requires
either:

- `feedback_full_automation_or_no_engagement` retirement (probe path:
  `~/.claude/projects/-home-hapax-projects/memory/MEMORY.md`)
- `project_livestream_is_research` retirement (replacing the
  singular-research-instrument framing with a multi-track content
  model)

The `refused-lifecycle-constitutional-watcher` daemon (when shipped)
will check both probes per its cadence policy.

## Cross-references

- cc-task vault note: `leverage-REFUSED-tutorial-videos.md`
- Project memory: `project_livestream_is_research`
- CI guard: `tests/test_forbidden_social_media_imports.py`
- Permitted livestream surface: `agents/studio_compositor/`,
  `agents/video_capture/`, `agents/video_processor/`
- Source research: `docs/research/2026-04-25-leverage-strategy.md`
