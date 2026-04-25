---
type: research-drop
date: 2026-04-25
title: Ambient Operator Awareness — Informed, Not In-Loop
agent_id: a58e30486e2eb8deb
status: shaping-in-progress
---

# Hapax Operator Awareness — "Informed, Not In-Loop"

## Verdict

Achievable. The highest-leverage move is **promoting the existing `vault_context_writer.py` daily-note path into a cross-surface canonical state stream** — an SSE-fed `/api/awareness` endpoint backed by `/dev/shm/hapax-awareness/state.json` that *all* surfaces consume read-only. Hapax authors; operator reads. Push is the last resort.

The constitutional trap is not "is the operator informed" but **"do any surfaces secretly extract operator labor"** — every dashboard with a `Mark as read` / `Acknowledge` / `Triage` affordance is already a HITL surface in disguise (Endsley & Sarter "automation surprise" canon: surfaces that demand a response *change the operator's mental model* and put them in-loop). The Cockpit / NOC / calm-tech literatures all converge on: **the surface must keep working unattended.**

## (1) Information density × cadence × surface matrix

| # | Category | Cadence | Aggregation | Primary | Backup | Refusal? |
|---|---|---|---|---|---|---|
| 1 | Marketing/outreach | per-event + 6h roll-up | counts → daily prose | Obsidian daily-note `## Outreach` | omg.lol statuslog | YES (suppression-list deltas) |
| 2 | Research dispatches | per-event | live count + last-completed | OrientationPanel research domain | Obsidian | NO |
| 3 | Music/SoundCloud | hourly | rolling 24h % deltas | waybar `custom/oudepode` (NEW) | weekly digest | YES (skip-rate flagged) |
| 4 | Publishing pipeline | per-event | inbox count + last-error | waybar `custom/publishing` (NEW) | ntfy on hard-fail only | YES (DOI-mint refusals) |
| 5 | Health/system | 30s | golden-signal pill | `custom/hapax-status` (already deployed) | Grafana TV | NO |
| 6 | Daimonion/voice | live | stance + last-utterance | OrientationPanel + AOD tile | Obsidian transcript | YES (refusal-gate hits) |
| 7 | Stream | 1s while live, 1m offline | running-or-not + posteriors | waybar `custom/stream` | dedicated kiosk | YES |
| 8 | Cross-account health | 5m | per-surface up/down dot grid | Grafana Hapax-Constellation panel | weekly digest | NO |
| 9 | Governance | per-violation | severity-bucketed | Logos refusal-brief view | ntfy at T0 only | YES (axiom violations) |
| 10 | Content programmes | event | active-list | OrientationPanel | daily-note | YES |
| 11 | Hardware (cameras / Pi / watch / phone) | 60s heartbeat | colored dot per device | waybar `custom/fleet` (NEW) | sentinel Pi-4 | NO |
| 12 | Time/sprint | hourly | progress %, gates open | OrientationPanel | weekly review | NO |
| 13 | Refusal-as-data | per-event | full list, NEVER aggregated to "0" | dedicated `Refusal Brief` view | weekly digest | (constitutive) |

Cadence respects Mankoff/McCrickard's IRC framework (Interruption / Reaction / Comprehension): everything in the table is **low-I, low-R, high-C** by design.

## (2) Five concrete surfaces to build/extend

**A. `briefing.daily.md` ambient log section** (extend `vault_context_writer.py`).
- Attendance moment: morning + arbitrary glances throughout day (`/api/orientation` already feeds Logos).
- Cadence: append every 15min; daily-note rotates at midnight; weekly review aggregates.
- Content: state-deltas only (not flat dumps). Refusals as `## Refused` block with timestamps + reasons.
- Fail-safe: `vault_canvas_writer.py` peer-checks recent edits; ntfy only if 3 consecutive intervals fail.

**B. `/api/awareness` SSE stream + `/dev/shm/hapax-awareness/state.json`** (NEW canonical spine).
- One file all surfaces read; SSE is push channel; readers never write.
- FastAPI EventSourceResponse pattern. Tauri SSE-bridge in `commands/streaming.rs` already exists.
- Fail-safe: stale-state TTL 90s; surfaces dim when stale.

**C. New waybar custom modules**.
- `custom/oudepode` (SC plays last 1h), `custom/publishing` (queue depth + last-error glyph), `custom/fleet` (3-NoIR-Pi + watch + phone dots), `custom/stream` (live indicator), `custom/refusals-1h` (count of explicit refusals).
- Each = JSON-emitting bash/python script with `interval`.

**D. `Refusal Brief` panel inside hapax-logos** (new sidebar widget).
- Reads `/api/refusals` (NEW endpoint), shows last 50 refusals with axiom-tag, surface, reason. NO "review" button — refusals are first-class displayed elements, never archived.

**E. Wear OS Tile + Live Updates / Min Mode tile on phone** (extend hapax-watch and hapax-phone).
- Watch tile: stance glyph, presence-engine posterior decile, voice idle/active dot. Wear OS 6 Tile API supports glanceable read-only tiles natively.
- Phone: Android 16 Live Updates already supports read-only progress on AOD; Android 17 Min Mode (dev preview late-2025) lets a full-screen low-power surface render Hapax status canvas without waking screen.

## (3) Anti-patterns (look constitutional, are HITL)

1. Dashboards with `Acknowledge` / `Mark read` — operator labor.
2. ntfy with action buttons — tap-to-act is in-loop. Text-only ntfy is fine.
3. "Pending review" inboxes — even existence of queue creates obligation; canonical Refusal Brief is *append-only with no terminal action*.
4. Slack / Discord / DM-routed bot summaries — operator-mediated reply expected by medium itself.
5. Email digests with embedded "see more" links — clicking is action.
6. Operator-curated dashboard filters / sort — labor leak. Hapax decides ordering.
7. Public dashboards as marketing — academic-spectacle directive precludes.
8. Scheduled summary expecting response — cadence implies obligation.
9. Tiles with on-tap "expand for action" — Hapax tiles stay glance-only.
10. Calendar/Reminder injections — weaponizes operator's planning surface. Vault-only.

## (4) The Hapax canonical operator surface

**Recommendation: Obsidian daily-note `~/Documents/Personal/40-calendar/{YYYY-MM-DD}.md`, with `## Awareness` section authored by extended `vault_context_writer`.**

Rationale:
- Already deployed via Obsidian Local REST API at `:27124`.
- Mobile syncs natively via Obsidian Sync.
- Append-only by design — no "read receipt" semantic.
- Is *Hapax's daily writing*, satisfying "Hapax authors everything".
- Operator already reads it; zero behavioral change required.
- Fail-safe is structural: if writer dies, missing daily section is itself a signal observable from any surface comparing "today's note size" to 7-day mean.

Workstation Logos OrientationPanel and waybar are *renderings* of the same canonical state stream — they read `/api/awareness` SSE generated from the same data the daily-note writer consumes. **One source of truth, multiple presentation surfaces.**

## (5) Implementation sketch (concrete files)

NEW agent `agents/operator_awareness/`:
- `state.py` — Pydantic 13-category model
- `aggregator.py` — pulls from health_monitor, vault_context_writer feeds, /dev/shm/hapax-stimmung, /dev/shm/hapax-sprint, /dev/shm/hapax-fleet, refusal-gate logs
- `runner.py` — 30s tick. Atomic write `/dev/shm/hapax-awareness/state.json` (tmp+rename)

EXTEND `agents/vault_context_writer.py`: add `## Awareness` and `## Refused` sections; consume from /dev/shm rather than recomputing.

NEW FastAPI route `agents/logos_api/routes/awareness.py`:
- `GET /api/awareness` (snapshot, JSON)
- `GET /api/awareness/stream` (SSE, EventSourceResponse)
- `GET /api/refusals?since=…` (refusal-brief tail)

NEW `hapax-logos/src/components/sidebar/RefusalBrief.tsx` — subscribes via existing Tauri SSE bridge.

WAYBAR additions: 5 new `custom/*` modules in `~/.config/waybar/config.jsonc`. Scripts under `~/.local/bin/hapax-waybar-*`.

NEW systemd: `hapax-operator-awareness.service` + `.timer` (30s).

NEW `agents/refusal_brief.py` — appends to /dev/shm/hapax-refusals/log.jsonl on every refusal-gate fire (axiom violation, suppression-list add, content-resolver decline, consent-gate filter, refusal-gate stream rejection).

WEAR OS: extend hapax-watch with `TileService` polling `https://100.117.1.83:8051/api/awareness/watch-summary` every 60s.

ANDROID PHONE: extend hapax-phone with Live Update widget; opt into Android 17 Min Mode rendering when API ships.

## (6) Cross-surface coherence

Single-stream principle: `/dev/shm/hapax-awareness/state.json` is the on-disk canon, `/api/awareness/stream` is the push channel. Every surface (waybar, Logos, watch, phone, vault writer, Grafana panel, omg.lol publisher) is a *pure subscriber* — none mutate.

Each surface implements **contextual elision** declaratively in its own renderer:
- Watch: top 3 categories by salience score
- Phone AOD: top 5
- waybar: per-module fixed slice
- Logos sidebar: full panel
- Vault: full prose form
- omg.lol weblog: only public-safe categories (filtered server-side by `public: bool` flag)

Matches autonomic-computing MAPE-K Knowledge layer pattern — one knowledge store, many readers, no read-back loops.

## (7) Three "fresh" patterns beyond NOC playbook

1. **Voice-digest at mode-shift, not on schedule.** Daimonion reads the day's condensed `## Awareness` section *only when* `working_mode` flips (research↔rnd) or stimmung crosses regulation threshold. Mode-shift is already an operator-context-shift moment, so the read is ambient by definition (no interruption cost).

2. **Obsidian daily-note as ops log — explicitly weaponized for ambient memory.** The note is the operator's natural scan target every morning. Co-locating Hapax's state under `## Log` / `## Awareness` / `## Refused` makes the operator's *existing* read habit the awareness mechanism. Cockburn's information-radiator thesis — passive transmission, no active push.

3. **Refusal-as-first-class-displayed-element with NO aggregation.** Every other category compresses to summary prose; the Refusal Brief lists individual refusals raw. This is constitutionally load-bearing — operator must *see* what Hapax declined to do, *as a list*, because aggregation would obscure the philosophical work refusals are doing. The Refusal Brief is the only surface where "0 refusals today" is a *suspicious* signal, not a clean one.

## Sources

- Autonomic computing — Wikipedia
- Vision of Autonomic Computing — Kephart & Chess (IEEE Computer 2003)
- Breaking the Loop: AWARE is the New MAPE-K (FSE 2025)
- Calm Technology — Wikipedia + Calm Tech Institute 2024
- Principles of Calm Technology — Amber Case
- Automation surprise — Sarter & Woods (CHI 2015 / 1995 NASA)
- CASA Human Factors Resource 10 — Design / Automation
- Endsley situation-awareness three-level model (1995)
- Information Radiators — Agile Alliance / Cockburn
- Heuristic evaluation of ambient displays — Mankoff et al. (CHI 2003)
- Defining peripheral displays — McCrickard / Stasko
- Tiles | Wear OS — Android Developers
- Building experiences for Wear OS (Aug 2025)
- Android 17 Min Mode AOD live activities (Oct 2025)
- Waybar custom modules
- Status bars — Hyprland Wiki
- ntfy.sh self-hosted push
- Server-Sent Events — FastAPI docs
- omg.lol Statuslog + /now Page
- microblog.pub — single-user ActivityPub
- Cognition — Devin 2.0 operator collaboration patterns
- Cursor 2.0 background agents observability
- Human-on-the-loop vs human-in-the-loop
- Alert fatigue solutions for DevOps teams 2025 — incident.io
- Situational awareness with Grafana — GrafanaCon 2025
- E-ink dashboards for home server status — XDA Developers
- Obsidian Daily Notes; olog command-line logging
