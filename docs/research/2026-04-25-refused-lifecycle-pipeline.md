---
type: research-drop
date: 2026-04-25
title: REFUSED-State Re-Evaluation Pipeline Design
agent_id: refused-lifecycle-shaper
status: shaping-in-progress
---

# REFUSED-State Re-Evaluation Pipeline Design

## §0 — Problem statement

The `~/Documents/Personal/20-projects/hapax-cc-tasks/active/` cc-task surface
holds REFUSED items as append-only nodes with `automation_status: REFUSED`,
`wsjf: 0.0`, and a verbatim `refusal_reason`. There is no automated
re-evaluation: a Bandcamp upload API ships, a TOS amendment lands, an axiom
flips — and the REFUSED node sits stale until the operator manually revisits
it. That is HITL by inertia. Per the post-2026-04-25 envelope
(`feedback_full_automation_or_no_engagement`,
`feedback_no_operator_approval_waits`,
`feedback_never_stall_revert_acceptable`) the substrate must re-evaluate
itself, surface state transitions through the canonical refusal log, and
preserve historical refusals as constitutional artifacts.

## §1 — State machine

Six transitions across four states. Refusals never delete; transitions append
to history. The substrate biases conservative — REFUSED stays REFUSED unless
the probe demonstrates the refusal-condition no longer holds.

```
                     +----- re-affirm (probe still fails) -----+
                     v                                          |
                  REFUSED <----- regression (rare; see §1.4) -- ACCEPTED
                  /  |  \
                 /   |   \
   probe-clears /    |    \  obsoleted (successor task ships)
               /     |     \
              v      |      v
          ACCEPTED   |   REMOVED
                     |      ^
                     |      | superseded / no-longer-relevant
                     +------+
```

| From → To | Trigger | Schema mutation |
|-----------|---------|-----------------|
| REFUSED → REFUSED (re-affirm) | probe still indicates refusal-condition holds | `last_evaluated_at` ← now; `next_evaluation_at` ← now+cadence; append `refusal_history` row |
| REFUSED → ACCEPTED | probe shows refusal-condition no longer holds AND probe evidence sufficient | `automation_status: OFFERED`; `wsjf` ← recomputed per task notes; `acceptance_evidence` populated; refusal-history retained verbatim |
| REFUSED → REMOVED | task obsoleted by another (successor ships) OR refusal-condition replaced by a new constitutional axiom that forecloses the surface entirely | `automation_status: REMOVED`; `removed_reason` populated; optional `superseded_by: <slug>` |
| ACCEPTED → REFUSED (regression) | upstream surface revoked the API / TOS reverted / axiom amended | append new `refusal_history` row; `automation_status: REFUSED` |
| ACCEPTED → REMOVED | task completed, shipped, or closed | standard cc-task close (move to `closed/`) |

### §1.1 — `refusal_history` is mandatory

The schema MUST track `refusal_history: list[{date, reason, evidence_url?, transition}]`.
Every transition (including re-affirmations) appends a row. Constitutional
load-bearing: the *act of revisitation* is itself data per
`feedback_co_publishing_auto_only_unsettled_contribution` and Refusal Brief
§2 ("the refusal is itself a measurement"). When a REFUSED item flips to
ACCEPTED, the prior refusal entries are NOT deleted — they become part of
the historical record that downstream refusal-brief publication depends on.

### §1.2 — Conservative default

When the probe is ambiguous (HTTP 5xx, malformed response, partial change,
network error) the substrate defaults to REFUSED → REFUSED (re-affirm) and
schedules a re-probe at the next cadence. The substrate NEVER auto-flips a
refusal on weak evidence.

### §1.3 — No operator-approval gate

Per `feedback_no_operator_approval_waits`: NO transition requires operator
review. Daemons decide; if a decision is wrong, operator-correction events
flow through the existing Qdrant `operator_corrections` collection. A
REFUSED → ACCEPTED transition becomes a refusal-brief log row; if the
operator disagrees, they amend the refusal manually and the next probe
re-confirms.

### §1.4 — ACCEPTED → REFUSED is rare but mandatory

The pipeline is bidirectional. If a task moves REFUSED → ACCEPTED on the
basis of a Bandcamp API release, and Bandcamp later revokes the API, the
substrate MUST re-detect the regression and flip back to REFUSED. The
probe runs forever; ACCEPTED is not a terminal state until REMOVED.

## §2 — Trigger taxonomy (3 categories)

### §2.A — Structural refusals (external API gap)

Refusal grounded in *the absence or active prohibition of a daemon-tractable
API*. Re-evaluation = polling the relevant API documentation / TOS pages /
release notes via HTTP-conditional-GET (ETag, Last-Modified). Cadence:
**weekly** baseline; degrades to **monthly** after 12 consecutive
re-affirmations (no API change in 12 weeks indicates a stable institutional
posture, per Refusal Brief §6 "tier-migration on major-policy-event"); resets
to weekly on any probe-content change (even if the change doesn't lift the
refusal).

Probe shape:

```python
def probe_structural(target: StructuralProbe) -> ProbeResult:
    headers = {"If-None-Match": target.last_etag, "If-Modified-Since": target.last_lm}
    resp = httpx.get(target.url, headers=headers, timeout=10)
    if resp.status_code == 304:
        return ProbeResult(changed=False, evidence=None)
    new_content = resp.text
    if has_keyword_signal(new_content, target.lift_keywords):
        return ProbeResult(changed=True, evidence=resp.url, snippet=...)
    return ProbeResult(changed=False, evidence=None)
```

Targets (the 6 structural refusals on the workstream as of 2026-04-25):

| Slug | Probe URL | `lift_keywords` |
|------|-----------|-----------------|
| `pub-bus-bandcamp-upload-REFUSED` | `https://bandcamp.com/developer` + `https://bandcamp.com/help/aiusage` | `upload`, `POST`, `submit`, `automated`, `bot`, deprecation of "Keeping Bandcamp Human" |
| `pub-bus-discogs-submission-REFUSED` | `https://www.discogs.com/developers/` (TOS section on automated submissions) | `submission API`, `automated`, `release`, removal of TOS prohibition |
| `pub-bus-rym-submission-REFUSED` | `https://rateyourmusic.com/development` (currently absent — look for any developer page emerging) | new `/api/`, `submission endpoint`, `developer` |
| `pub-bus-crossref-event-data-REFUSED` | `https://www.crossref.org/services/event-data/` (sunset notice) + `https://api.eventdata.crossref.org/v1/events` (revival) | `available`, `restored`, successor service |
| `cold-contact-alphaxiv-comments` | `https://www.alphaxiv.org/community-guidelines` (or equivalent guidelines page) | removal of LLM-comment prohibition; explicit allow language |
| (future) `pub-bus-zenodo-community-auto-accept` | `https://help.zenodo.org/docs/communities/manage-community-settings/` | `auto-accept`, `automatic curation`, community admin policy |

### §2.B — Constitutional refusals (operator-policy-driven)

Refusal grounded in a Hapax constitutional axiom or operator directive
(`feedback_full_automation_or_no_engagement`, single-operator, no_HITL,
anti-anthropomorphization). Re-evaluation = inotify on the canonical
constitutional surfaces; the trigger fires when the underlying axiom or
feedback rule changes, NOT on a clock.

Watched surfaces (read-only by re-evaluator; never mutates):

- `~/projects/hapax-constitution/axioms/registry.yaml` — axiom
  add/remove/weight-change events
- `~/Documents/Personal/30-areas/hapax/manifesto.md` — manifesto
  amendments (esp. §IV "Auto-publish or not at all" + future §IV.5)
- `~/Documents/Personal/30-areas/hapax/refusal-brief.md` — Tier-3 audit
  table changes; surface migration events
- `~/.claude/projects/-home-hapax-projects/memory/MEMORY.md` — feedback
  rules (`feedback_full_automation_or_no_engagement`, etc.) explicitly
  tagged as constitutional

Cadence: **inotify-only** (no periodic poll). On any modify/move/delete
event, the constitutional watcher walks all type-B refusals and re-evaluates
each. If no axiom-change, no probe runs. This is the right cadence: B-class
refusals are stable until the substrate's constitution changes, at which
point ALL of them must be re-checked atomically.

Affected slugs (10 awareness-refused-* + cold-contact-* + repo-pres-*):

- 10 awareness-refused-* (acknowledge-mark-read, calendar-reminder,
  email-digest-with-links, ntfy-action-buttons, operator-curated-filters,
  pending-review-inboxes, public-marketing-dashboards,
  scheduled-summary-cadence, slack-discord-dm-bots, tile-tap-action)
- `cold-contact-email-last-resort` (operator-approval gate; full-automation)
- `cold-contact-public-archive-listserv` (operator-mediated reply)
- `cold-contact-alphaxiv-comments` ALSO type-A (TOS-conditional) — see §2.D
- `repo-pres-code-of-conduct-REFUSED` (single-operator axiom)

Probe shape (simpler than A — no HTTP):

```python
def probe_constitutional(target: ConstitutionalProbe) -> ProbeResult:
    state = read_axiom_or_feedback(target.constitutional_path)
    if state.fingerprint == target.last_fingerprint:
        return ProbeResult(changed=False, evidence=None)
    if axiom_now_permits(state, target.refusal_basis):
        return ProbeResult(changed=True, evidence=state.path, snippet=...)
    return ProbeResult(changed=False, evidence=state.path)  # still refused, but log the policy-touch
```

### §2.C — Conditional refusals (upstream dependency)

Refusal grounded in another task or external dependency that, if shipped /
deployed / amended, would lift the refusal. Trigger = dependency-completion
event (a `depends_on` task transitions to closed/shipped). The probe re-runs
the tractability check.

Examples currently surfaced:

- A speculative `pub-bus-zenodo-community-auto-accept-REFUSED` would
  depend on Zenodo community-policy + `pub-bus-orcid-auto-update`
- Awareness anti-patterns whose underlying Hapax-internal architecture
  could shift (e.g., if a future Endsley-aligned ack-pattern is published,
  the related anti-pattern would re-evaluate against the new constraint)

Probe shape: re-runs the type-A probe OR the type-B probe (or both) when
the dependency-graph tells it to.

### §2.D — Multi-classification

Some refusals are *both* A and B. `cold-contact-alphaxiv-comments` is
TOS-prohibited (A) AND operator-policy-prohibited (B). The pipeline runs
*both* probes; the refusal stays REFUSED until *both* lift, and any single
probe surfacing a state-change still appends to refusal-history. The
schema field `evaluation_trigger` accepts a list `[structural, constitutional]`
in this case.

## §3 — Schema additions

New required frontmatter on every REFUSED task (also applied retroactively
to existing 13 via the migration task):

```yaml
last_evaluated_at: 2026-MM-DDTHH:MM:SSZ
next_evaluation_at: 2026-MM-DDTHH:MM:SSZ
evaluation_trigger: structural | constitutional | conditional | [structural, constitutional]
evaluation_probe:
  url: https://...           # for type-A
  conditional_path: ...      # for type-B
  depends_on_slug: ...       # for type-C
  lift_keywords: [..., ...]  # what content shift lifts the refusal
  last_etag: null            # populated post-probe
  last_lm: null              # If-Modified-Since
  last_fingerprint: null     # SHA256 of last-fetched content (fallback when no ETag)
refusal_history:
  - date: 2026-04-25T11:00:00Z
    transition: created
    reason: <verbatim from refusal_reason>
  - date: 2026-05-02T08:00:00Z
    transition: re-affirmed
    reason: probe-content-unchanged
    evidence_url: null
superseded_by: null          # slug, populated on REMOVED
acceptance_evidence:         # populated on transition to ACCEPTED
  date: null
  url: null
  snippet: null
```

The `refusal_reason` field is preserved verbatim as the *initial* refusal
record; new evidence appends to `refusal_history`, never overwrites
`refusal_reason`.

## §4 — Re-evaluation execution flow

```
┌──────────────────────────────────────────────────────────────┐
│ refused-lifecycle/runner.py (systemd timer; daemon-resident) │
└──────────────────────────────────────────────────────────────┘
        │
        │ tick (weekly for type-A; inotify for type-B)
        ▼
┌─────────────────────────────────────────────┐
│ enumerate(active/*-REFUSED.md, *.md w/      │
│   automation_status: REFUSED)               │
└─────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────┐
│ for each task:                               │
│   read frontmatter                           │
│   skip if next_evaluation_at > now           │
│   evaluator.probe(task)                      │
│     ├─ type-A: HTTP conditional GET          │
│     ├─ type-B: read constitutional surface   │
│     └─ type-C: check depends_on closed       │
│   if probe.changed and probe.evidence_strong:│
│     state.transition(task, ACCEPTED, evidence)│
│     refusal_brief.append(transition_event)   │
│   else:                                      │
│     state.reaffirm(task, probe)              │
│     refusal_brief.append(reaffirm_event)     │
└──────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────┐
│ atomic write task frontmatter (tmp+rename)   │
│ append /dev/shm/hapax-refusals/log.jsonl     │
│ metric: hapax_refused_lifecycle_*            │
└──────────────────────────────────────────────┘
```

Conservative-default rules:

- HTTP 5xx / network error → re-affirm (never auto-flip on flaky probe)
- Probe returns ambiguous content (lift-keyword present but in a "no, this
  is still prohibited" context) → re-affirm; NLP-classification gating not
  load-bearing here
- Multi-trigger refusals require ALL probes to indicate lift before
  transitioning to ACCEPTED
- Acceptance never happens without `acceptance_evidence.url` + a verbatim
  `acceptance_evidence.snippet` (≤500 chars) capturing the relevant policy
  text

## §5 — Integration with `awareness-refusal-brief-writer`

Re-evaluation events become first-class refusal-brief log entries. The
RefusalEvent Pydantic model gains a new field:

```python
class RefusalEvent(BaseModel):
    timestamp: datetime
    axiom: str
    surface: str
    reason: str
    public: bool = False
    refusal_brief_link: str | None = None
    # NEW
    transition: Literal["created", "re-affirmed", "accepted", "removed", "regressed"] = "created"
    evidence_url: str | None = None  # populated on accepted/removed
    cc_task_slug: str | None = None  # links log row → cc-task file
```

Five transition kinds map to log rows:

- `created` (existing) — initial refusal write
- `re-affirmed` — probe indicates condition still holds; cadence touch
- `accepted` — REFUSED → ACCEPTED transition
- `removed` — REFUSED → REMOVED OR ACCEPTED → REMOVED
- `regressed` — ACCEPTED → REFUSED (rare; see §1.4)

This makes the Refusal Brief publication (Locus 2 web essay at
`hapax.omg.lol/refusal`) constitutionally complete: it can include not only
the *current* tier classification but also the *history of revisitations*.
Per Refusal Brief §3 "the audit re-audits on a 4-cluster cadence at any
major publisher-policy event" — this pipeline is precisely that mechanism,
materialized.

The waybar `refusals-1h` count and Logos refusal-brief sidebar surface ALL
five transition kinds; consumers do not filter or hide re-affirmations
(per `awareness-refused-operator-curated-filters`). The signal-density of
"7 re-affirmations + 1 acceptance + 1 removal in the last 24h" is itself
load-bearing data — it shows the substrate is alive and revisiting.

## §6 — Classification of 13 currently-REFUSED tasks

| # | Slug | Trigger | Cadence | Notes |
|---|------|---------|---------|-------|
| 1 | `pub-bus-bandcamp-upload-REFUSED` | A | weekly | bandcamp.com/developer + AI-policy page |
| 2 | `pub-bus-discogs-submission-REFUSED` | A | weekly | TOS prohibition lift |
| 3 | `pub-bus-rym-submission-REFUSED` | A | weekly | API-emergence watch (currently no dev page) |
| 4 | `pub-bus-crossref-event-data-REFUSED` | A | monthly | Service-revival watch |
| 5 | `repo-pres-code-of-conduct-REFUSED` | B | inotify | single-operator axiom amendment (in `axioms/registry.yaml`) |
| 6 | `cold-contact-email-last-resort` | B | inotify | full-automation directive amendment |
| 7 | `cold-contact-public-archive-listserv` | B | inotify | full-automation directive amendment |
| 8 | `cold-contact-alphaxiv-comments` | A+B | weekly+inotify | TOS lift (A) AND axiom amendment (B); both must lift |
| 9 | `awareness-refused-acknowledge-mark-read-affordances` | B | inotify | no_HITL axiom |
| 10 | `awareness-refused-calendar-reminder-injection` | B | inotify | full-automation directive |
| 11 | `awareness-refused-email-digest-with-links` | B | inotify | full-automation directive |
| 12 | `awareness-refused-ntfy-action-buttons` | B | inotify | full-automation directive |
| 13 | `awareness-refused-operator-curated-filters` | B | inotify | full-automation directive |
| 14 | `awareness-refused-pending-review-inboxes` | B | inotify | `feedback_no_operator_approval_waits` |
| 15 | `awareness-refused-public-marketing-dashboards` | B | inotify | `project_academic_spectacle_strategy` + full-automation |
| 16 | `awareness-refused-scheduled-summary-cadence` | B | inotify | mode-shift-trigger axiom |
| 17 | `awareness-refused-slack-discord-dm-bots` | B | inotify | full-automation directive |
| 18 | `awareness-refused-tile-tap-action` | B | inotify | full-automation directive |

(Operator-stated count was "13" but actual census shows 18 active REFUSED
tasks: 4 type-A, 13 type-B, 1 type-A+B. Difference traced to the 10
awareness-refused-* anti-pattern items being counted as a single bundle by
the operator question; classification is per-file.)

## §7 — Anti-patterns to avoid (recapped from spec)

- **Re-evaluation that quietly mutates the workstream without surfacing
  the change** → every transition publishes to refusal-brief log; waybar
  + Logos surfaces show counts.
- **Re-evaluation that requires operator review** → forbidden;
  conservative auto-decisions only.
- **Polling cadences that hammer external APIs** → ETag + If-Modified-Since
  mandatory; weekly-baseline + monthly after 12 stable re-affirms.
- **Auto-acceptance with insufficient evidence** → conservative default
  REFUSED → REFUSED unless probe surfaces explicit lift-keyword in
  policy-affirmative context.
- **Forgetting that ACCEPTED can revert to REFUSED** → bidirectional state
  machine; ACCEPTED is not terminal.
- **Aggregating re-affirmations into "1 event"** → forbidden; every probe
  produces one log row (Refusal Brief §6 "the audit is the running
  classification").

## §8 — cc-task plan (refused-lifecycle-* slug family)

Seven shaped tasks; see Phase 2 of the shaping artifact. Slug prefix
`refused-lifecycle-` reserved for collision avoidance with concurrent
update agent (a8aec3e3fb9a2fcd6).

1. `refused-lifecycle-state-machine` — substrate package, 5.0
2. `refused-lifecycle-schema-extension` — frontmatter migration, 3.5
3. `refused-lifecycle-structural-watcher` — type-A daemon, 4.0
4. `refused-lifecycle-constitutional-watcher` — type-B inotify, 3.5
5. `refused-lifecycle-conditional-watcher` — type-C dependency hook, 3.0
6. `refused-lifecycle-refusal-brief-integration` — log-writer wire, 3.0
7. `refused-lifecycle-classification-pass` — initial migration, 3.5

Total ~22h sequenced effort; substrate (#1) blocks the rest; #2 blocks #7;
the three watchers (#3-#5) parallelize after #1.

## §9 — Open questions resolved autonomously

| Question | Resolution | Rationale |
|----------|-----------|-----------|
| Track `refusal_history` on re-affirmations? | Yes (mandatory) | Refusal Brief §2 "the act of revisitation is itself data" |
| Cadence for type-A? | Weekly baseline; degrade to monthly after 12 stable re-affirms; reset to weekly on any probe-content change | Matches Refusal Brief §6 "tier-migration on policy-event"; respects HTTP cache headers |
| Cadence for type-B? | inotify-only, no clock | Constitutional changes are rare and atomic; clock-poll would be wasted I/O |
| Multi-trigger refusal handling? | All probes must lift; any single probe's content-touch logs as event | Conservative; preserves Refusal Brief audit-record fidelity |
| Operator-approval gate before transition? | None (auto-decide) | `feedback_no_operator_approval_waits`; correction flows via existing operator-correction Qdrant collection |
| ACCEPTED → REFUSED supported? | Yes (regression path) | `feedback_never_stall_revert_acceptable`; ACCEPTED not terminal |
| `removed_reason` distinct from `refusal_reason`? | Yes | Removal can be obsoletion (different cause from original refusal); operator must distinguish |
| Where does the daemon live? | `agents/refused_lifecycle/` (council repo) | Pattern matches `agents/operator_awareness/` and `agents/refusal_brief.py` |
| Operator-physical-irreversible action gate? | None apply (no destructive writes) | All transitions are append-only or schema-mutations on cc-task files; reverts trivially |
| Concurrent update-agent slug collision? | Slug prefix `refused-lifecycle-` mandatory | Per spec |

## §10 — Timeline + dependencies

```
refused-lifecycle-state-machine (5.0)
    └── refused-lifecycle-schema-extension (3.5)
            └── refused-lifecycle-classification-pass (3.5)
    └── refused-lifecycle-structural-watcher (4.0)        ─┐
    └── refused-lifecycle-constitutional-watcher (3.5)    ─┤  parallel after substrate
    └── refused-lifecycle-conditional-watcher (3.0)       ─┘

awareness-refusal-brief-writer (8.5; not in this slug family)
    └── refused-lifecycle-refusal-brief-integration (3.0)
```

Dependencies on existing tasks: `awareness-refusal-brief-writer` provides
the `refusal_brief.append()` API. The integration task #6 wires transition
events through that API; it depends on both #1 (state-machine emits
transitions) and `awareness-refusal-brief-writer`.

## §11 — Delivery shape

- Three Python modules in new `agents/refused_lifecycle/` package
- Two daemons (structural watcher + constitutional watcher) registered as
  systemd user units
- One conditional-watcher hook fired by cc-task close events
- A one-time migration script populating new schema fields on the 18
  currently-REFUSED tasks
- Six new metrics:
  `hapax_refused_lifecycle_probes_total{trigger, slug}`,
  `hapax_refused_lifecycle_transitions_total{from, to, slug}`,
  `hapax_refused_lifecycle_probe_failures_total{trigger, slug, reason}`,
  `hapax_refused_lifecycle_evaluation_age_seconds{slug}`,
  `hapax_refused_lifecycle_acceptance_rate_30d`,
  `hapax_refused_lifecycle_regression_count_30d`
- Refusal-brief log integration extending RefusalEvent with `transition`
  + `evidence_url` + `cc_task_slug` fields

End design.
