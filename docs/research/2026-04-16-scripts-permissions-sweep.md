---
title: scripts/ executable permissions + shebang sweep
date: 2026-04-16
queue_item: '311'
epic: lrr
phase: substrate-scenario-2
status: catalog
---

# scripts/ — exec permissions + shebang sweep

## Summary

| Metric | Count |
|---|---|
| Total files | 100 |
| Executable bit set | 52 |
| No exec bit | 48 |

## Shebang / exec-bit consistency

| File | Exec bit | Shebang | Status |
|---|---|---|---|
| `scripts/album-identifier.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/archive-purge.py` | +x | `#!/usr/bin/env` | OK |
| `scripts/archive-reenable.py` | +x | `#!/usr/bin/env` | OK |
| `scripts/archive-search.py` | +x | `#!/usr/bin/env` | OK |
| `scripts/benchmark_prompt_compression_b6.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/bootstrap-profiles.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/build_demo_kb.py` | - | `-` | OK |
| `scripts/cache-cleanup.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/calibrate-contact-mic.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/chat-monitor.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/check-claude-md-rot.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/check-conflict-markers` | +x | `#!/usr/bin/env` | OK |
| `scripts/check-frozen-files.py` | +x | `#!/usr/bin/env` | OK |
| `scripts/check-vscode-sister-extensions.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/compositor-vram-snapshot.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/disk-space-check.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/enforcement_accuracy.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/enroll_speaker.py` | +x | `#!/usr/bin/env` | OK |
| `scripts/experiment-check.fish` | +x | `#!/usr/bin/env` | OK |
| `scripts/experiment-freeze-check` | +x | `#!/usr/bin/env` | OK |
| `scripts/extract-test-data.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/freshness-check.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/generate_codebase_map.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/generate_screen_context.py` | +x | `#!/usr/bin/env` | OK |
| `scripts/hapax-df-bridge.lua` | - | `-` | OK |
| `scripts/hapax-df-diagnostic.lua` | - | `-` | OK |
| `scripts/hapax-df-lifecycle.lua` | - | `-` | OK |
| `scripts/hapax-df-nav.lua` | - | `-` | OK |
| `scripts/hapax-mode` | +x | `#!/usr/bin/env` | OK |
| `scripts/hapax-semantic-names.lua` | - | `-` | OK |
| `scripts/hapax-whoami` | +x | `#!/usr/bin/env` | OK |
| `scripts/hapax-working-mode` | +x | `#!/usr/bin/env` | OK |
| `scripts/hls-archive-rotate.py` | +x | `#!/usr/bin/env` | OK |
| `scripts/import_langfuse_traces.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/__init__.py` | - | `-` | OK |
| `scripts/install-claude-code.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/install-compositor-layout.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/kokoro-baseline.py` | +x | `#!/usr/bin/env` | OK |
| `scripts/llm_import_graph.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/llm_metadata_gen.py` | - | `-` | OK |
| `scripts/llm_validate.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/llm_vendor.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/lrr-phase-4-integrity-check.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/lrr-phase-4-integrity-lock.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/lrr-state.py` | +x | `#!/usr/bin/env` | OK |
| `scripts/measure-brio-operator-fps.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/mediamtx-start.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/migrate_goals_to_vault.py` | - | `-` | OK |
| `scripts/migrate_profile_dimensions.py` | - | `-` | OK |
| `scripts/migrate-shader-params.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/migrate-voice-to-daimonion.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/mock-chat.py` | +x | `#!/usr/bin/env` | OK |
| `scripts/monthly-claude-md-audit.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/play_brother_demo.py` | - | `-` | OK |
| `scripts/provision_dashboards.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/psu-stress-test.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/rebuild-logos.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/rebuild-service.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/record_wake_word.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/reload-after-build.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/render_aggie_demo.py` | - | `-` | OK |
| `scripts/render_alexis_demo.py` | - | `-` | OK |
| `scripts/render_alexis_demo_v2.py` | - | `-` | OK |
| `scripts/render_alexis_demo_v3.py` | - | `-` | OK |
| `scripts/render_alexis_demo_v4.py` | - | `-` | OK |
| `scripts/render_brother_demo.py` | - | `-` | OK |
| `scripts/render_kids_demo.py` | - | `-` | OK |
| `scripts/research-registry.py` | +x | `#!/usr/bin/env` | OK |
| `scripts/retire-studio-compositor-reload-path.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/run_deliberations.py` | - | `-` | OK |
| `scripts/run_rifts_benchmark.py` | +x | `#!/usr/bin/env` | OK |
| `scripts/sdlc_axiom_judge.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/sdlc_plan.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/sdlc_review.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/sdlc_triage.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/sierpinski-cpu-baseline.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/smoke_test_daimonion.sh` | +x | `#!/bin/bash` | OK |
| `scripts/smoke_test_demo.py` | - | `-` | OK |
| `scripts/smoke_test_reverie.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/smoke-test.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/stream-terminal.sh` | - | `#!/bin/bash` | SHEBANG-NO-EXEC |
| `scripts/studio-compositor-archive-precheck.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/studio-compositor-postmortem.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/studio-install-udev-rules.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/studio-simulate-usb-disconnect.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/studio-smoke-test.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/test_wake_handoff.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/token_ledger.py` | - | `-` | OK |
| `scripts/train_wake_word.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/verify-daimonion.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/verify_reverberation_cadence.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/video-retention.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/visual-audit.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/vram-watchdog.sh` | +x | `#!/usr/bin/env` | OK |
| `scripts/webcam_timelapse.py` | - | `-` | OK |
| `scripts/window-capture.sh` | +x | `#!/bin/bash` | OK |
| `scripts/write_test_plan.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/youtube-auth.py` | - | `#!/usr/bin/env` | SHEBANG-NO-EXEC |
| `scripts/youtube-player.py` | +x | `#!/usr/bin/env` | OK |

Issues found: 25
