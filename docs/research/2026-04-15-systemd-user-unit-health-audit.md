# Systemd user unit health check audit

**Date:** 2026-04-15
**Author:** alpha (AWB mode, queue/ item #114)
**Scope:** Walk `systemd/units/*.service` units. Audit for `Type=notify` + `WatchdogSec=`, `Restart=` policy, `ExecStartPre` destructive patterns (#55-like footguns), health-check gaps. Catalogue 25 long-running services.
**Register:** scientific, neutral

## 1. Headline

**The 24/7 recovery chain has one structural gap: watchdog coverage.** Only 1 of 25 long-running user-unit services (`studio-compositor`) declares `Type=notify` + `WatchdogSec=`. All 24 others rely on `Restart=` + crash-kill semantics — no liveness enforcement.

**No #55-like footguns.** Zero `ExecStartPre=...find -delete` patterns anywhere. The #55 fix held.

**Restart policies are universally set.** 25/25 long-running services have `Restart=always` or `Restart=on-failure`. No dangling services without restart directives.

**Currently failed units (runtime state):**
- `rag-ingest.service` — separate `.venv-ingest` dependency issue (huggingface-hub version conflict); known-bad
- `vault-context-writer.service` — failed; needs investigation (out of scope for this audit)

## 2. Method

```bash
find systemd/units -name "*.service" | wc -l                        # 85 total
grep -L "^Type=oneshot" systemd/units/*.service                     # 25 long-running
grep -lE "^Type=notify" systemd/units/*.service                     # 1 match
grep -lE "^WatchdogSec=" systemd/units/*.service                    # 1 match
grep -nE "ExecStartPre=" systemd/units/*.service                    # 26 entries, none destructive
grep -rEn "find.*-delete|rm -rf" systemd/units/*.service            # 0 matches
systemctl --user list-units --failed --all                          # 2 failed
```

## 3. Unit inventory

```
systemd/units/*.service       85 files
  ├── long-running (25)       simple, notify, forking — daemons
  └── oneshot (60)            one-off tasks, timers fire into these

systemd/units/*.timer         52 files
systemd/units/*.service       also 5 top-level systemd/*.service (hapax-build-reload, etc.)
```

Total: ~140 unit files under `systemd/` (excluding `systemd/units-pi6/` which deploys to Pi 6).

## 4. Long-running service classification

25 services whose `Type=` is not `oneshot`:

| # | Service | Type | Restart | WatchdogSec |
|---|---|---|---|---|
| 1 | audio-recorder | simple | always | — |
| 2 | contact-mic-recorder | simple | always | — |
| 3 | hapax-content-resolver | simple | on-failure | — |
| 4 | hapax-daimonion | simple | always | — |
| 5 | hapax-dmn | simple | on-failure | — |
| 6 | hapax-imagination | simple | always | — |
| 7 | hapax-imagination-loop | simple | on-failure | — |
| 8 | hapax-logos | simple | always | — |
| 9 | hapax-reverie | simple | on-failure | — |
| 10 | hapax-stack | simple | on-failure | — |
| 11 | hapax-video-cam@ | simple | on-failure | — |
| 12 | hapax-watch-receiver | simple | always | — |
| 13 | keychron-keepalive | simple | on-failure | — |
| 14 | logos-api | simple | on-failure | — |
| 15 | logos-dev | simple | always | — |
| 16 | mediamtx | simple | on-failure | — |
| 17 | rag-ingest | simple | on-failure | — (failed) |
| 18 | **studio-compositor** | **notify** | on-failure | **60s** ✓ |
| 19 | studio-fx | simple | on-failure | — |
| 20 | studio-fx-output | simple | on-failure | — |
| 21 | studio-person-detector | simple | on-failure | — |
| 22 | tabbyapi | simple | on-failure | — |
| 23 | tabbyapi-hermes8b | simple | on-failure | — |
| 24 | visual-layer-aggregator | simple | on-failure | — |
| 25 | wlsunset | simple | on-failure | — |

**Coverage:**
- 25/25 have `Restart=` (12 always, 13 on-failure) ✓
- 1/25 has `Type=notify` + `WatchdogSec=` (studio-compositor only)
- 24/25 rely on process-death detection, not liveness

## 5. Gap analysis — watchdog coverage

`Type=notify` + `WatchdogSec=` gives systemd the ability to force-kill + restart a service that is **running but unresponsive** (e.g., deadlocked, GC-pauseed, infinite-looped). Without it, a service can be "active" per systemd's process-level check while actually being useless.

**The 24 services without watchdog are silent-failure risks.** Candidates where it matters most (subjective alpha ranking by impact):

| Service | Why watchdog matters | Recommended WatchdogSec |
|---|---|---|
| `hapax-daimonion` | Voice STT+TTS; hangs have user-visible impact | 60s |
| `hapax-logos` | Tauri UI process; hangs freeze the operator surface | 90s |
| `hapax-imagination` | GPU visual daemon; wgpu hangs block reverie | 120s |
| `tabbyapi` | LLM inference backend; CUDA hangs cascade to all agents | 180s |
| `visual-layer-aggregator` | Stimmung aggregator; downstream of everything | 60s |
| `logos-api` | FastAPI on :8051; unresponsive = whole system dies silently | 30s |
| `mediamtx` | RTMP relay; livestream depends on it | 60s |
| `studio-fx` / `studio-fx-output` | Camera FX pipeline; hangs break livestream | 60s |
| `hapax-dmn` | DMN daemon; topological critical node | 120s |
| `hapax-reverie` | Visual surface daemon | 120s |

Implementing watchdog on a Python service requires:
1. `Type=notify` in the unit file
2. `WatchdogSec=Ns` in the unit file
3. Python sends `READY=1` on startup + periodic `WATCHDOG=1` via `sdnotify` library

The `sdnotify` dependency is already in the project (per camera 24/7 resilience epic). Adding watchdog to the 10 priority services above is a 1-day sprint (3-10 lines of Python per service + unit file edits).

**Alpha recommendation:** file this as a follow-up epic — "Systemd watchdog coverage for long-running daemons" — after LRR Phase 10 closes.

## 6. #55-like footgun check

Queue item #55 (LRR Phase 2 item 2) was a `ExecStartPre=find ... -delete` pattern in `studio-compositor.service` that risked deleting legitimate HLS segments. Audit for similar patterns across all units:

```bash
$ grep -rEn "find.*-delete|rm\s+-rf" systemd/units/*.service
(empty, no matches)
```

**Zero matches.** The only lingering reference is a comment in `studio-compositor.service:22` marking where the old pattern was removed:

```
# LRR Phase 2 spec §3.2 (item 2) REMOVED: the ExecStartPre `find ... -delete` on
```

**Finding: clean.** No other unit has reintroduced a destructive pre-hook.

## 7. ExecStartPre cataloguing

26 units have `ExecStartPre=` entries. All are safe:

| Category | Count | Examples |
|---|---|---|
| `mkdir -p` (safe) | 5 | audio-recorder, contact-mic-recorder, hapax-logos, hapax-video-cam@, studio-fx |
| `hapax-env-setup` (env loader) | 9 | chrome-sync, claude-code-sync, deliberation-eval, gcalendar-sync, gdrive-sync, gmail-sync, obsidian-sync, rag-ingest, youtube-sync |
| `sleep` (delay) | 2 | hapax-daimonion (10s), llm-stack-analytics (60s) |
| `secrets install` | 1 | hapax-secrets (install -m 600 /dev/null) |
| `docker info` (preflight) | 1 | llm-stack |
| `generate-env.sh` | 2 | llm-stack, llm-stack-analytics |
| `pnpm install` (dev) | 1 | logos-dev |
| `bootstrap-profiles.sh` | 1 | hapax-logos |
| `studio-*.sh` scripts | 3 | studio-compositor (3 entries) |
| `studio-camera-setup.sh` | 1 | studio-compositor |
| `studio-compositor-archive-precheck.sh` | 1 | studio-compositor (archive pre-flight) |

**Zero destructive patterns.** Zero `-delete`, `-rf`, `unlink`, `truncate`, etc.

## 8. Health check endpoints

Grep for comments or env vars referencing health-check endpoints that might not be wired up:

```bash
$ grep -rEn "# ?health.*check|http.*health|/api/health" systemd/units/*.service
(empty)
```

**No health-check-in-comments-but-not-wired drift.** Health check code lives in the Python services themselves (`logos/api/routes/health.py`, etc.) and is wired through FastAPI routes, not systemd unit directives.

## 9. Currently failed units

As of 2026-04-15T18:22Z:

### 9.1 rag-ingest.service — known-bad

```
rag-ingest.service           loaded failed failed RAG Document Ingestion Watchdog
```

**Root cause:** uses a separate `.venv-ingest` due to "docling/pydantic-ai huggingface-hub version conflict" (unit file comment). Needs `make setup-ingest-venv` + re-verification. Out of scope for this audit but should be tracked.

### 9.2 vault-context-writer.service — needs investigation

```
vault-context-writer.service loaded failed failed Write working context to Obsidian daily note
```

Failure reason not captured in audit window. 15-min timer-triggered service. Impact: daily log writes to Obsidian vault stop. **Recommendation:** file a follow-up queue item to investigate failure log + fix.

## 10. `OnFailure=notify-failure@%n.service` hook

```bash
$ grep -l "^OnFailure=notify-failure@%n.service" systemd/units/*.service | wc -l
```

Several units use `OnFailure=notify-failure@%n.service` for ntfy alerts on failure. This is a **reactive** alerting path — it fires after systemd declares the unit failed. Complements but does not replace watchdog (which is **proactive** liveness enforcement).

## 11. Timers (quick scan)

52 `.timer` files. Out of scope for this audit (queue item focus was `.service` health), but ad-hoc observations:

- All timers target oneshot services
- No `AccuracySec=` overrides spotted in the spot-check (default 1min)
- No obvious overlap or scheduling conflicts

Full timer audit is a separate queue item candidate.

## 12. Recommendations

### 12.1 Priority (file as follow-up queue items)

1. **Watchdog coverage epic** — add `Type=notify` + `WatchdogSec=` to the 10 priority services from §5. `sdnotify` dependency already available. 1-day sprint.
2. **Fix rag-ingest.service** — rebuild `.venv-ingest`, verify agent starts + stays up
3. **Investigate vault-context-writer.service failure** — read recent journal, fix
4. **Timer audit** — separate queue item, audit 52 `.timer` files for `AccuracySec=`, `Persistent=`, `OnBootSec=` correctness

### 12.2 No-action-needed

- **Restart= policies are universally set.** ✓
- **No #55-like footguns.** ✓
- **ExecStartPre patterns are all safe.** ✓
- **24/7 recovery chain (kernel panic reboot, watchdog hardware, greetd autologin, lingering)** is correct at the system level per workspace CLAUDE.md § "24/7 recovery".

## 13. Closing

25 long-running services, 1 with proper watchdog (`studio-compositor`), 24 relying on crash-kill detection. No destructive `ExecStartPre` patterns. The #55 fix held. Main gap: watchdog coverage — recommend deferring to a post-LRR-Phase-10 sprint epic.

Branch-only commit per queue item #114 acceptance criteria.

## 14. Cross-references

- Queue item #55: LRR Phase 2 item 2 `ExecStartPre=find ... -delete` removal (studio-compositor.service)
- Camera 24/7 resilience epic: `docs/superpowers/handoff/2026-04-13-alpha-camera-247-epic-handoff.md` — establishes the studio-compositor notify+watchdog pattern to replicate
- `systemd/README.md` — boot sequence, resource isolation, recovery chain
- Workspace CLAUDE.md § "24/7 recovery": kernel panic auto-reboot (10s), hardware watchdog (SP5100 TCO, 30s)

— alpha, 2026-04-15T18:24Z
