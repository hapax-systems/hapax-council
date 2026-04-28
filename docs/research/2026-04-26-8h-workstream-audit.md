# 8-Hour Workstream Audit — 2026-04-26 01:30Z–09:30Z

> **Source**: gamma session research drop. 6 independent audit agents partitioned the 8h merge corpus into coherent clusters and applied a 4×3 audit matrix (spec / claude-conversation-history / intention / research × completion-consistency-correctness / robustness-edge-cases / missed-opportunities). Output shaped for beta consumption.

## TL;DR
- 50 PRs shipped across 6 coherent clusters in an 8-hour window; the V5 pub-bus surfaces (deposit publishers, citation-graph, verification timers) account for 18 of them and are the load-bearing arc.
- Most concerning: axiom-enforcer flipped to default-ON (#1537) without runbook kill-switch, while in parallel 4 V5 timers shipped DORMANT with no systemd preset — same binder ("features-on-by-default") interpreted oppositely by adjacent clusters in the same window.
- Broadcast safety regressed: #1575 reverts the role.assistant tap-isolation hardening from #1530, leaving operator privacy enforced by daimonion classifier alone with no regression test pinning the invariant. `voice-broadcast-role-split` is deferred without a claim.
- Mail-monitor ingress is orphaned: classifier/dispatcher/processors are code-complete (#1547–#1568) but task 006 (Pub/Sub webhook receiver) is unblocked since 2026-04-22 and unclaimed — there is currently no message source.
- Beta should look first at: (1) cluster-1 broadcast-safety regression test + voice-broadcast-role-split claim, (2) cluster-2 task 006 webhook (~2h, unblocks the entire mail cascade), (3) cluster-6 axiom-enforcer kill-switch runbook + transition test, (4) cluster-4 systemd preset to honor features-on-by-default.

## Scope
- **Window**: 2026-04-26 01:30Z–09:30Z (8 hours)
- **PR count**: 50 PRs across 6 clusters
  - Cluster 1 (audio / broadcast-safety + incident remediation): 8 PRs — #1527, #1530, #1532, #1534, #1540, #1566, #1572, #1575
  - Cluster 2 (mail-monitor cascade): 8 PRs — #1547, #1549, #1550, #1552, #1557, #1558, #1564, #1568
  - Cluster 3 (V5 deposit publishers): 8 PRs — #1525, #1531, #1533, #1544, #1546, #1548, #1551, #1556
  - Cluster 4 (V5 citation-graph + verification + timers): 10 PRs — #1528, #1529, #1535, #1536, #1538, #1539, #1541, #1542, #1543, #1553
  - Cluster 5 (refusal corpus expansion): 13 PRs — #1554, #1555, #1560, #1562, #1563, #1565, #1567, #1569, #1570, #1571, #1573, #1574, #1576
  - Cluster 6 (cross-cutting infra): 3 PRs — #1526, #1537, #1545
- **Audit dimensions**: regression-test coverage, runbook/documentation completeness, feature-flag adherence to features-on-by-default binder, phase dependency tracking, cross-lane integration, architectural papercut detection, taxonomy/classification drift, incident remediation completeness, Phase 2 readiness.
- **Lenses applied**: features-on-by-default (operator binder, 2026-04-25), refusal-as-data (operator binder, 2026-04-25), no-stale-branches, scientific-register, infrastructure-as-argument, broadcast invariant (L-12 = livestream).

## Cross-cluster patterns

These themes recur across two or more cluster audits. Each is named, explained, and pointed at evidence so beta can decide which of them deserve their own cc-task vs. being absorbed into a per-cluster claim.

### 1. Test/regression coverage gaps are universal
Every cluster surfaced at least one missing-test finding. The pattern is not "cluster X under-tested" — it is "the workstream as a whole shipped surfaces faster than invariant tests."
- Cluster 1: no regression test pinning the #1575 revert (role.assistant→hapax-voice-fx-capture + LIVESTREAM destination).
- Cluster 2: spec §5.3, §5.5 scope-control tests absent — `test_no_bare_list.py`, `test_revocation_drill.py`, `scripts/check-mail-monitor-no-bare-list.py`, `test_redaction.py` all missing.
- Cluster 3: no cross-publisher invariant test iterating `auto_surfaces()` and verifying allowlist + legal-name guard + counter on each.
- Cluster 4: no timer-firing integration tests; syntax errors / schedule conflicts surface only in production.
- Cluster 5: no CI test for surface-registry ↔ refusal-brief one-to-one correspondence (`test_all_refused_surfaces_have_briefs()`).
- Cluster 6: no axiom-enforcer OFF→ON transition test exercising briefing.py + digest.py + a seeded T0 violation.

This is a workstream-wide hygiene problem, not a cluster-local one.

### 2. Features-on-by-default binder applied inconsistently
The 2026-04-25T20:55Z operator binder requires opt-in flags default ON.
- Cluster 6 honors it: #1537 flips axiom-enforcer ON.
- Cluster 4 violates it: 4 timers (orcid-verifier, self-federate-rss, datacite-snapshot, datacite-mirror) shipped without `systemd/user-preset.d/hapax.preset`, requiring manual `systemctl --user enable --now`.
- Cluster 5 reveals the cost of inconsistency: with axiom-enforcer ON (#1537), refusal-brief rendering is at risk of blocking Phase 2 narrative composition because briefs naming non-operator persons trip the enforcer.

The binder needs a single enforcement surface (preset file + CI check) so adjacent merges cannot interpret it oppositely.

### 3. Documentation/runbook gaps cluster around new enforcement surfaces
Three clusters shipped enforcement or capability surfaces without operator-facing docs.
- Cluster 6: axiom-enforcer kill-switch undocumented — production recourse is "grep source for `AXIOM_ENFORCE_BLOCK=0`, edit systemd unit, restart."
- Cluster 3: V5 publisher credential bootstrap undocumented — each publisher defers to operator queue without a consolidated bootstrap runbook listing missing creds with actionable `pass insert` guidance.
- Cluster 5: refusal classification taxonomy undocumented — corpus exhibits 11+ ad-hoc labels against a 5-axis spec, no canonical registry.
- Cluster 1: LUFS panic-cap (#1534) referenced "researcher report a09d834c" but no `docs/research/` file exists.

The shared shape: enforcement/capability without operator-facing runbook = risk of an outage where the operator must read source to recover.

### 4. Phase 2 dependencies ride on tribal memory
Clusters 3, 4, 5 all ship Phase 1 surfaces with Phase 2 work pending — but the Phase 2 obligations are recorded only in PR descriptions and operator-action-queue items.
- Cluster 3: 6 deposit publishers + RefusalBriefPublisher Phase 2 daemon wiring.
- Cluster 4: DataCite snapshot main() is a no-op pending Phase 2 source-list wiring; cold-contact candidate registry empty pending Phase 2 seeding (37 names).
- Cluster 5: refusal-lifecycle re-evaluation daemon designed but not implemented.

If beta does not lift these into an explicit Phase 2 milestone with its own cc-task tree, they will be forgotten when this 8h window scrolls off the operator's working set.

### 5. Cross-lane integration gaps shipped uncaught
Multiple surfaces are code-complete on their own lane but fail at the seam with adjacent lanes.
- Cluster 2 ↔ cold-contact: task 008 SUPPRESS processor appends to `contact-suppression-list.yaml`, but cold-contact daemon callsite NOT updated to use `is_suppressed_by_email_domain()`.
- Cluster 2 ↔ ingress: task 006 webhook unblocked since 2026-04-22 but unclaimed — classifier/dispatcher/processors orphaned.
- Cluster 4 ↔ delta: awareness-stream consumers for Phase 3 DataCite mirror unprepared.
- Cluster 5 ↔ cluster 6: refusal-brief composition risks blocking under axiom-enforcer ON without explicit allow-list or renderer bypass.

The pattern: each lane tested its own surface; nobody tested the seam.

### 6. Architectural papercuts surface as oscillating fixes
Cluster 1 contains the cleanest example. #1530 hardened role.assistant routing; #1575 reverted it. The underlying gap (wireplumber policy cannot express daimonion-level media-role split) was not closed — quick fixes oscillated around it. Cluster 1 also shows dual-root-cause voice silence patched as #1566 + #1572 over ~1h with operator silenced — symptoms fixed, architecture untouched. The takeaway for beta: when an incident produces 2+ sequential fixes within an hour, the architectural gap is the actual cc-task, not the symptom-fixes.

### 7. Inflection-driven priority outpaces proactive audit
Three of cluster 6's three PRs and several of cluster 1 and cluster 2's PRs are inflection-driven:
- SHA1 inflection → #1564 (bandit silence)
- Idempotency-flake inflection → #1526
- Voice silence inflection → #1566 + #1572
- Bandit/scope inflection → various

This is fine, but the operator's "exhaust research before solutioning" binder is being honored mostly retrospectively. The scheduled compositor-metrics-style invariant tests that would have surfaced these proactively are exactly the tests cluster-1/2/3/4/5/6 are also missing. Pattern 1 (test gaps) and Pattern 7 (reactive priority) are causally coupled.

### 8. Category/taxonomy drift in refusal corpus and elsewhere
Cluster 5 shows the most explicit drift: spec enumerates 5 axes, corpus exhibits 11+ labels including novel "double constitutional barrier", "documentary — path closed", "compounding refusal". Cluster 4's "11-surface coverage" claim in CLAUDE.md is similarly fuzzy (likely refers to feature lanes, not Publisher subclasses). Without canonical registries, future programmatic queries become impossible — this is the silent failure mode behind the "infrastructure-as-argument" stance, where the artifacts being argued *with* lose query-ability.

## Global findings ranked by severity

### HIGH

- **Broadcast safety regression unguarded** — Cluster 1, #1575 reverts #1530 without regression test pinning role.assistant→hapax-voice-fx-capture + LIVESTREAM destination invariant. Operator privacy enforced by daimonion classifier alone. **Action**: Land regression test before any further audio routing edits; claim `voice-broadcast-role-split` cc-task.

- **Axiom-enforcer flipped to default-ON without kill-switch runbook** — Cluster 6, #1537. Production false-positive recourse is "grep source, edit systemd, restart." **Action**: Ship kill-switch runbook + OFF→ON transition test before next merge that touches enforcer.

- **Mail-monitor ingress orphaned** — Cluster 2, task 006 unblocked since 2026-04-22, ~2h work, sole ingress path for primary Pub/Sub flow. Classifier/dispatcher/processors are dead code without it. **Action**: Claim and ship task 006 immediately.

- **Mail-monitor scope-control tests absent** — Cluster 2, spec §5.3 / §5.5 / redaction tests missing. Privacy-guarantee regressions ship uncaught. **Action**: Land `test_no_bare_list.py`, `test_revocation_drill.py`, `test_redaction.py`, `scripts/check-mail-monitor-no-bare-list.py`.

- **Cold-contact ↔ mail-monitor task 008 integration unverified** — Cluster 2. SUPPRESS processor appends to `contact-suppression-list.yaml`; cold-contact daemon does not call `is_suppressed_by_email_domain()`. Risk: operator opts out, cold-contact still emails them. **Action**: Audit cold-contact callsite, wire suppression check, add integration test.

- **V5 timers shipped dormant — features-on-by-default binder violated** — Cluster 4. orcid-verifier, self-federate-rss, datacite-snapshot, datacite-mirror lack `systemd/user-preset.d/hapax.preset`. **Action**: Add preset file; treat as blocker for Phase 2b.

- **Refusal corpus taxonomy drift** — Cluster 5. 5-axis spec, 11+ label corpus, no canonical registry. **Action**: Author `docs/refusal-briefs/_registry.yaml`; add CI check enforcing label set.

- **Refusal-as-data publisher wiring inconsistent** — Cluster 5. Only 1 of 5 REFUSED publishers has daemon path (RefusalBriefPublisher). Bandcamp, Discogs, RYM, Crossref REFUSED subclasses inert. **Action**: Decide policy (wire all or document why not), ship missing daemon paths.

- **Surface-registry ↔ refusal-brief correspondence untested** — Cluster 5. **Action**: Add `test_all_refused_surfaces_have_briefs()` CI test.

- **Path-based axiom guards bypassable via subprocess / dynamic import** — Cluster 5. `importlib.import_module()`, `subprocess.run` evade the guard. **Action**: Extend with AST-based dynamic-import + subprocess detection.

- **Axiom-enforcer pattern coverage gap** — Cluster 6. `interpersonal_transparency` and `corporate_boundary` have ZERO T0 patterns; PR description does not surface gap. **Action**: Document intentionally-unenforced axioms in patterns YAML; if enforcement intended, author patterns.

- **Idempotency-flake follow-up sweep deferred** — Cluster 6, #1526 fixes only `omg_pastebin_publisher`. `omg_now_sync`, `omg_credits_publisher` likely share root cause. **Action**: Sweep all compiled-content systems.

- **Cold-contact candidate registry seed empty** — Cluster 4. Graph-touch nonfunctional until Phase 2 seeding (37 names). **Action**: Track Phase 2 seeding as explicit cc-task; do not let it slide into tribal memory.

- **ORCID iD dual-sourcing risk** — Cluster 4. `orcid_verifier.py` uses `HAPAX_OPERATOR_ORCID` env; `shared/orcid.py` reads `pass show orcid/orcid`. Divergence risk. **Action**: Document canonical sourcing convention; prefer single SoT.

### MEDIUM

- **Voice-silence dual-root-cause incident lacks post-mortem** — Cluster 1, #1566 + #1572 shipped sequentially over ~1h with operator silenced. No post-incident review document. **Action**: Author `docs/research/2026-04-26-incident-review-daimonion-voice-silence.md`.

- **TTS loopback (#1572) deployment untested** — Cluster 1. Pipewire config + restart with no automated verification. **Action**: Add health-check for TTS loopback attachment.

- **LUFS panic-cap research doc missing** — Cluster 1, #1534. **Action**: Publish referenced research doc.

- **Feedback detector thresholds empirically tuned, not grounded** — Cluster 1. 12 dB / 4 windows / 200 Hz floor un-researched. **Action**: Schedule 2-week validation; escalate to LOG-only if FP rate >0/hour.

- **Cross-publisher invariant tests missing** — Cluster 3. **Action**: Iterate `auto_surfaces()`, verify each has registered Publisher with allowlist + legal-name guard + counter.

- **No timer-firing integration tests** — Cluster 4. **Action**: Land integration test invoking each timer's main() under a fast clock; assert artifact creation.

- **Pub/Sub watch-renewal concurrency untested under late-renewal/network-partition** — Cluster 2. **Action**: Add concurrency test.

- **Mastodon/Bluesky cred wiring (#1562) lacks refusal-collision test** — Cluster 5. Currently not refused, but future refusal addition without disabling poster makes surface live + refused simultaneously. **Action**: Add regression test that every refused-publisher subclass refuses correctly.

- **AlphaXivComments two-axis refusal, single-axis enforcement** — Cluster 5, #1555 uses import-based guard, not dynamic. **Action**: Upgrade to AST-based guard (couples to cluster 5 dynamic-import finding).

- **Quota-observability 0.0.0.0 bind without firewall enforcement** — Cluster 6, #1545. Comment claims "single-user host, firewalled LAN" but no iptables/ufw/socket enforcement. **Action**: Document or enforce; network-reconfiguration could expose.

- **RSS validator hardcoded URL** — Cluster 4. `https://hapax.weblog.lol/rss` not parameterized. **Action**: Parameterize; monitor for silent DOI-extraction failures on dynamic feeds.

- **Tasks 009 + 010 deferred without end-to-end test** — Cluster 2. No Zenodo verification email → DOI extraction → deposit corroboration test. **Action**: Add integration test once webhook ingress lands.

- **Quota exporter metrics not in dashboard schema** — Cluster 6. Documented only in docstring. **Action**: Add to Grafana dashboard or Prometheus config.

- **`destination_channel.py` log misleading post-#1575** — Cluster 1. Promised follow-up in #1530 deferred. **Action**: cc-task `fix-destination-channel-default-and-semantics`.

- **Refusal-lifecycle re-evaluation pipeline designed not implemented** — Cluster 5. Research doc exists; no Phase 2 daemon. **Action**: Schedule Phase 2 cc-task.

- **Idempotency band-aid not architectural** — Cluster 6, #1526. Better long-term design separates published content from metadata. **Action**: Schedule architectural cc-task post-sweep.

### LOW

- **SHA-1 collision risk accepted** — Cluster 2, #1564 silences bandit. 2^61 collision space. Acceptable; revisit if mail volume spikes.
- **Task 003 superseded cleanly** — Cluster 2. Refusal record + spec amendment in good order.
- **Label/filter bootstrap doesn't test removal-and-recreate** — Cluster 2.
- **Awareness-stream consumer (DataCite mirror Phase 3) deferred to delta lane** — Cluster 4. Appropriate handoff.
- **CLAUDE.md "11-surface coverage" claim fuzzy** — Cluster 4. Likely feature lanes, not Publisher subclasses. Resolve via taxonomy registry (couples to Cluster 5 finding).
- **#1554 Bridgy POSSE audit lacks Phase 2 daemon scheduler** — Cluster 5.
- **Feature-flip tests don't validate full feature surface** — Cluster 1.
- **Cold-contact cadence log writer undefined Phase 1** — Cluster 4. Phase 2 Zenodo deposit_builder must wire.

## Per-cluster compact summaries

### Cluster 1: audio / broadcast-safety + incident remediation
**PRs**: #1527, #1530, #1532, #1534, #1540, #1566, #1572, #1575
**State**: Shipped but architecturally unresolved. Symptom-level fixes complete; root-cause (wireplumber cannot express daimonion-level role split) deferred without claim.
**Top 3 findings**:
1. #1575 reverts #1530's privacy hardening; no regression test on the new invariant.
2. Dual-root-cause incident (#1566 + #1572) lacks post-mortem.
3. Empirical thresholds (LUFS panic-cap, feedback detector) un-grounded by research docs.
**Top recommendation**: Land the regression test FIRST, then claim `voice-broadcast-role-split`. Do not edit audio routing again until both are in place.

### Cluster 2: mail-monitor cascade
**PRs**: #1547, #1549, #1550, #1552, #1557, #1558, #1564, #1568
**State**: Code-complete but ORPHANED. Classifier/dispatcher/processors have no message source.
**Top 3 findings**:
1. Task 006 webhook receiver unblocked since 2026-04-22, ~2h work, unclaimed.
2. Spec §5.3 / §5.5 / redaction scope-control tests absent.
3. Cold-contact daemon does not call task 008's `is_suppressed_by_email_domain()`.
**Top recommendation**: UNBLOCK TASK 006 IMMEDIATELY. Without it, cluster 2's ~8 PRs ship dormant.

### Cluster 3: V5 pub-bus deposit publishers
**PRs**: #1525, #1531, #1533, #1544, #1546, #1548, #1551, #1556
**State**: Cleanest cluster of the window. Phase 1 self-contained, no blockers.
**Top 3 findings**:
1. No cross-publisher invariant test iterating `auto_surfaces()`.
2. Phase 2 cred bootstrap gate not yet wired (acceptable; daemon-era work).
3. Rate-limit recovery absent on Zenodo + IA (HTTP 429 → generic transport error).
**Top recommendation**: Defensive cross-publisher invariant test now; cred bootstrap gate as Phase 2 prerequisite.

### Cluster 4: V5 pub-bus citation-graph + verification + timers
**PRs**: #1528, #1529, #1535, #1536, #1538, #1539, #1541, #1542, #1543, #1553
**State**: Largest cluster, partially live. 4 timers shipped DORMANT.
**Top 3 findings**:
1. systemd preset file missing → features-on-by-default binder violated.
2. DataCite snapshot main() is a Phase 1 no-op; source-list wiring deferred.
3. Cold-contact candidate registry seed empty.
**Top recommendation**: Land `systemd/user-preset.d/hapax.preset` immediately; treat as blocker for Phase 2b.

### Cluster 5: refusal corpus expansion
**PRs**: #1554, #1555, #1560, #1562, #1563, #1565, #1567, #1569, #1570, #1571, #1573, #1574, #1576
**State**: 13 PRs of corpus drift. Surface count grew faster than taxonomy and tests.
**Top 3 findings**:
1. Taxonomy drift: 5-axis spec, 11+ label corpus, no canonical registry.
2. Refusal-as-data publisher wiring inconsistent — 4 of 5 REFUSED subclasses inert.
3. Path-based axiom guards bypassable via subprocess / dynamic import.
**Top recommendation**: Author `docs/refusal-briefs/_registry.yaml` and CI check before adding more refusal records. Decide refusal-as-data publisher policy.

### Cluster 6: cross-cutting infra (axiom, quota, idempotency)
**PRs**: #1526, #1537, #1545
**State**: 3 PRs but disproportionately load-bearing. Default-ON axiom enforcer changes the whole system's failure mode.
**Top 3 findings**:
1. Axiom-enforcer kill-switch runbook missing.
2. `interpersonal_transparency` and `corporate_boundary` axioms have ZERO T0 patterns.
3. Idempotency fix (#1526) covers only `omg_pastebin_publisher` — sweep needed.
**Top recommendation**: Ship kill-switch runbook + OFF→ON transition test BEFORE next merge that touches enforcer. Then sweep idempotency.

## Recommended cc-tasks for beta

WSJF estimates use rough cost-of-delay / job-size ratios on a 1–10 scale.

| slug | scope (1 line) | lane | WSJF (rough) | depends_on |
|------|----------------|------|--------------|------------|
| `voice-broadcast-role-split-regression-test` | Regression test pinning role.assistant→hapax-voice-fx-capture + LIVESTREAM=hapax-livestream-tap invariant | beta | 9 | — |
| `voice-broadcast-role-split-architectural-fix` | Close wireplumber-level gap revealed by #1530↔#1575 oscillation | beta | 7 | voice-broadcast-role-split-regression-test |
| `mail-monitor-task-006-webhook-receiver` | Pub/Sub `/webhook/gmail` push endpoint — sole ingress for primary flow | beta | 10 | — |
| `mail-monitor-scope-control-tests` | Land §5.3, §5.5, redaction tests + `scripts/check-mail-monitor-no-bare-list.py` | beta | 8 | — |
| `cold-contact-suppression-callsite-wire` | Wire cold-contact daemon to `is_suppressed_by_email_domain()` + integration test | beta | 8 | mail-monitor-task-006-webhook-receiver |
| `axiom-enforcer-killswitch-runbook` | Operator-facing runbook for AXIOM_ENFORCE_BLOCK=0 path; happy-path kill-switch | beta | 9 | — |
| `axiom-enforcer-transition-test` | OFF→ON state-transition test across briefing.py + digest.py + seeded T0 violation | beta | 7 | axiom-enforcer-killswitch-runbook |
| `axiom-enforcer-coverage-doc` | Document intentionally-unenforced axioms (interpersonal_transparency, corporate_boundary) in patterns YAML | beta | 5 | — |
| `axiom-guard-ast-upgrade` | Extend path-based axiom guards with AST-based dynamic-import + subprocess detection | beta | 6 | — |
| `v5-systemd-preset-features-on` | Author `systemd/user-preset.d/hapax.preset` enabling 4 V5 timers; CI check enforcing preset coverage | beta | 8 | — |
| `v5-cred-bootstrap-gate` | Startup check listing missing publisher creds with `pass insert` guidance | beta | 6 | — |
| `v5-cross-publisher-invariant-test` | Iterate `auto_surfaces()`; assert allowlist + legal-name guard + counter on each Publisher | beta | 6 | — |
| `v5-rate-limit-recovery-zenodo-ia` | 60s exponential backoff (max 5 retries) for Zenodo + IA on HTTP 429 | beta | 5 | — |
| `v5-timer-firing-integration-test` | Fast-clock integration test for each timer's main(); assert artifact creation | beta | 6 | v5-systemd-preset-features-on |
| `v5-datacite-snapshot-source-list` | Phase 2 source-list wiring (recent-concept-dois.txt + swhids.yaml + HAPAX_OPERATOR_ORCID) | beta | 6 | v5-cred-bootstrap-gate |
| `v5-orcid-sourcing-runbook` | Document canonical ORCID iD sourcing (env vs. pass); converge on single SoT | beta | 4 | — |
| `cold-contact-candidate-registry-seed` | Phase 2 seeding of 37-name candidate registry (operator + Hapax review) | beta | 5 | mail-monitor-task-006-webhook-receiver |
| `refusal-brief-registry-yaml` | `docs/refusal-briefs/_registry.yaml` canonical taxonomy mapping slug → axiom-tag → classification | beta | 8 | — |
| `refusal-brief-coherence-ci` | CI test `test_all_refused_surfaces_have_briefs()` enforcing surface-registry ↔ brief 1:1 | beta | 7 | refusal-brief-registry-yaml |
| `refusal-as-data-publisher-policy` | Decide wiring policy for Bandcamp/Discogs/RYM/Crossref REFUSED subclasses; ship daemon paths or document why not | beta | 6 | — |
| `refusal-publisher-regression-suite` | Test that every refused-publisher subclass refuses correctly across cred-present and cred-absent states | beta | 6 | — |
| `axiom-enforcer-refusal-brief-allowlist` | Allow-list or renderer bypass for refusal-brief Phase 2 narrative composition | beta | 7 | refusal-brief-registry-yaml |
| `idempotency-flake-sweep` | Sweep `omg_now_sync`, `omg_credits_publisher`, other compiled-content systems for #1526 root cause | beta | 6 | — |
| `idempotency-architectural-redesign` | Long-term: separate published content from metadata to retire band-aid | beta | 4 | idempotency-flake-sweep |
| `quota-observability-firewall-doc-or-enforce` | Document or enforce 0.0.0.0 bind isolation for quota exporter | beta | 5 | — |
| `quota-metrics-dashboard-schema` | Add quota exporter metrics to Grafana dashboard / Prometheus config | beta | 3 | — |
| `incident-review-daimonion-voice-silence` | Post-mortem doc `docs/research/2026-04-26-incident-review-daimonion-voice-silence.md` | beta | 5 | — |
| `lufs-panic-cap-research-doc` | Publish research doc grounding 12 dB / 4 windows / 200 Hz floor thresholds | beta | 4 | — |
| `tts-loopback-healthcheck` | Health-check for TTS loopback attachment post-#1572 | beta | 5 | — |
| `feedback-detector-validation-schedule` | 2-week FP-rate validation; escalate to LOG-only if FP rate >0/hour | beta | 4 | — |
| `destination-channel-default-and-semantics` | Resolve #1530 follow-up deferred by #1575 revert | beta | 5 | voice-broadcast-role-split-regression-test |
| `refusal-lifecycle-reevaluation-daemon` | Phase 2 daemon implementing existing research-doc design | beta | 5 | refusal-brief-registry-yaml |
| `pubsub-watch-renewal-concurrency-test` | Test renewal under late-renewal + network-partition | beta | 4 | mail-monitor-task-006-webhook-receiver |
| `mail-monitor-end-to-end-zenodo` | Verification email → DOI extraction → deposit corroboration integration test | beta | 5 | mail-monitor-task-006-webhook-receiver |
| `claude-md-surface-coverage-claim-resolve` | Reconcile "11-surface coverage" claim with Publisher subclass count | beta | 3 | refusal-brief-registry-yaml |

## Audit methodology

The 8-hour window was partitioned by *coherent intent* — each cluster represents a logical arc of work that one or two operators could plausibly have shipped end-to-end, not a chronological slice. Cluster 1 (audio) was identified by file-path and incident-narrative coupling; clusters 3 and 4 (V5) were partitioned by V5 sub-system (deposit publishers vs. citation/verification/timers) to keep audit surface tractable; cluster 2 (mail-monitor) tracked a single spec; cluster 5 (refusal corpus) tracked PRs touching `docs/refusal-briefs/` or refusal-record fixtures; cluster 6 (cross-cutting) collected the small infrastructure PRs that did not fit the others. Six independent gamma-session audit agents each took one cluster with a shared prompt covering: regression-test coverage, runbook completeness, features-on-by-default adherence, Phase 2 dependency tracking, cross-lane integration, taxonomy drift, and architectural-papercut detection. Each agent surfaced HIGH/MEDIUM/LOW findings with PR + file evidence. Synthesis collapsed cross-cluster patterns from the union of findings, ranked severity globally rather than per-cluster, and produced cc-task recommendations with rough WSJF.

## What gamma observed about the workstream as a whole

The 8-hour window had two distinct rhythms running concurrently. The first rhythm was incident-driven (clusters 1 and 6) — sharp, inflection-paced fixes with short PR descriptions, hour-scale sequencing, and a tendency to ship symptom-level patches faster than the architectural gap underneath could be characterized. The second rhythm was V5-arc-driven (clusters 3, 4, 5) — broader, plan-derived merges with larger PR descriptions, aligned to the pub-bus surface buildout, and operating under Phase 1/Phase 2 framing. Cluster 2 (mail-monitor) sits between the two rhythms: spec-derived like the V5 work, but with critical-path dependencies (task 006) that make it incident-shaped if it fails.

The two rhythms produced opposite failure modes. The incident-driven rhythm produced *under-tested* surfaces (no regression test for the #1575 revert; no transition test for axiom-enforcer ON; no idempotency-sweep). The V5 rhythm produced *under-wired* surfaces (timers without preset; publishers without cred bootstrap; refusal subclasses without daemon paths). Both rhythms inherit the same root pattern from the workstream: surfaces ship faster than the invariants protecting them. Beta should claim the test-and-runbook scaffolding cc-tasks first (regression tests, kill-switch runbook, registry YAML, preset file) before claiming any new surface work — this is the load-bearing leverage point for the next 8h window.

The third observation is taxonomy. The refusal corpus drift in cluster 5 is the most visible instance, but the same drift is latent in cluster 4's "11-surface coverage" claim and in cluster 3's missing cross-publisher invariant. The operator's "infrastructure-as-argument" stance (refusal-as-data, full-automation-or-no-engagement) lives or dies by the query-ability of the artifacts being argued *with*. If the corpus loses canonical taxonomy now, the constitutional thesis loses its public surface within ~30 days. The `refusal-brief-registry-yaml` cc-task is therefore higher leverage than its WSJF-8 ranking suggests — its absence compounds across every future cluster-5-shaped merge. Beta should consider promoting it before any further refusal-corpus PRs land.
