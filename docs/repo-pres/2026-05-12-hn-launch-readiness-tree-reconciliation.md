# HN Launch Readiness Tree Reconciliation

Date: 2026-05-12
Task: `hn-launch-readiness-tree-reconciliation`
Decision: **NO-GO** for HN submission.

This receipt reconciles the HN launch request, cc-task tree, merged PRs, public
surfaces, and live readiness evidence. It is not a launch authorization.

## Current Gate

Latest local checker run:

```bash
uv run python scripts/hn-launch-systems-readiness --json
```

Result: `fail`; `ready=false`.

Hard failures in the latest 2026-05-12T15:45Z verification sample:

- `compositor_visual_surface`: layout mode is `forcefield`, not Sierpinski.
- `daimonion_voice_segments`: no completed playback is recorded in
  `voice-output-witness`.
- `youtube_livestream`: livestream video id is missing, empty, or stale.
- `obs_clean_feed`: `hapax-obs-livestream` is inactive; public claim is not
  allowed; RTMP, MediaMTX HLS, and audio-floor evidence are failing.

Warning:

- `logos_api`: API overall status is `failed`.

Current passes include thin programme segment freshness, reverie/imagination
freshness, GitHub README, omg.lol weblog reachability, and systemd
timer/failed-unit budget. Programme freshness is not enough to close
`hn-launch-programme-e2e-readiness`. A scratch current-API programme smoke
receipt now proves the runner/layout command path, but live segment-prep history
and soak-citable programme evidence remain unresolved.
The gate has been volatile across samples, and the latest sample is still
NO-GO.

The 2026-05-12T15:45Z run still reports `ready=false`, `status=fail`; failures:
`compositor_visual_surface`, `daimonion_voice_segments`, `youtube_livestream`,
and `obs_clean_feed`; warning: `logos_api`.

## Claim Classification

| Claim | Classification | Evidence | Launch implication |
|---|---|---|---|
| HN systems readiness is complete | false | `hn-launch-systems-readiness` is active/blocked; latest checker still fails compositor layout mode, voice, YouTube, and OBS. | Blocks soak and HN post. |
| PR #3149 makes HN ready | false | PR #3149 merged 2026-05-12T14:21:18Z as a warning-budget/support fix. It does not clear hard readiness failures. | Must not auto-close systems readiness. |
| Compositor visual surface is live | partial/stale | Earlier reconciliation sample reported pass; final pre-PR sample reports `compositor_visual_surface: fail` because layout mode is not Sierpinski. | Requires fresh stable pass before soak. |
| Programme segments are launch-ready | partial | Latest checker sees a fresh populated active segment. Repaired scratch harness receipt `/tmp/hapax-hn-programme-delivery-smoke-20260512T162123Z/programme-delivery-smoke-receipt.json` proves current runner/layout command acceptance, but live segment-prep receipt/history and soak-citable evidence are still missing. | Requires `hn-launch-programme-e2e-readiness`. |
| Daimonion voice is speaking launch segments | false | Latest checker reports `daimonion_voice_segments: fail`. | Requires operator/hardware route unblock. |
| Reverie/imagination surface is fresh | partial | Checker pass is freshness evidence, not correlated response proof. | May enter passive observation only after hard failures clear. |
| Logos API is healthy | partial | Service/SHM evidence can be ready, but API overall status is `failed`. | `hn-launch-logos-health-unblock` must resolve warning semantics. |
| README has launch support/trust positioning | verified | README has DOI, Sponsor badge, support URL, pending-Sponsors caveat, trust/governance framing, and agentgov link. Checker reports `github_readme: pass`. | README leaf is green. |
| omg.lol HN weblog post is public | verified for weblog publication; partial for blog task | The live Show HN URL and RSS item are public; article was republished 2026-05-12 with receipt-backed metrics and passes local hardening. | Blog task remains blocked on cross-post decision/evidence. |
| YouTube livestream is active | false | Latest checker reports `youtube_livestream: fail`. | Blocks systems readiness. |
| OBS clean feed is public-claim safe | false | Latest checker reports `obs_clean_feed: fail`; `hapax-obs-livestream` inactive. | Blocks systems readiness. |
| Timer/failed-unit budget is within threshold | verified | Latest checker reports `systemd_timer_failed_unit_budget: pass`. | One checklist item green. |
| GitHub topics are complete | verified | Closed task `hn-launch-github-topics`, PR #3035, and receipt `docs/repo-pres/2026-05-10-hn-launch-github-topics.md`. | Complete leaf. |
| Zenodo DOI is minted | verified | Closed task `hn-launch-zenodo-doi`, PR #3043, README badge, DOI `10.5281/zenodo.20113515`. | Complete nice-to-have leaf. |
| agentgov launch artifact is complete | verified | `hapax-systems/agentgov` is public/MIT; README has examples; PyPI `hapax-agentgov==0.3.0` installs; `agentgov init/check/report` work in a clean venv. `hn-launch-agentgov-cli-extraction` is closed. | Artifact leaf is green under the shipped distribution name `hapax-agentgov`. |
| Public Show HN metrics are receipt-backed | verified | Receipt `docs/repo-pres/2026-05-12-hn-launch-public-metrics-receipt.md` backs the source Show HN draft metrics: `3,041` opened, `2,871` merged, five revert-titled PRs, `42` council shell hooks, five portable `agentgov` checks, and `47` markdown refusal briefs. The live weblog, landing page, and HN first-comment draft now match or soften unsupported claims. | Metrics leaf is green. |
| Weblog/social syndication is live | partial/stale | Final weblog URL and public event exist. Idempotency files include the event ID, but Mastodon public checks did not show a Show HN post with link and Bluesky public feed shows metadata-refusal posts without links. | Blocks post-submission. |
| Support page is reachable | verified | `https://hapax.omg.lol/support` returns 200 and says support buys no access, requests, priority, deliverables, or control. | Support copy is usable. |
| Payment/support rail claims are reconciled | verified with caveat | `hapax-money-rails.service` is active and polls Alby successfully, but logs include Nostr relay failures and a Liberapay 404. | Launch copy may route through support page and claim service running, not every external rail green. |
| GitHub Sponsors are approved/active | downgraded | Personal `ryanklee` Sponsors listing is public; `hapax-systems` org Sponsors listing is not public. | Do not claim org Sponsors active. |

## WSJF Readiness Tree

| WSJF | Task | Current state | Evidence standard before launch |
|---:|---|---|---|
| 24.0 | `hn-launch-readiness-tree-reconciliation` | in progress in this PR | This receipt merged and task closed. |
| 23.0 | `hn-launch-daimonion-voice-playback-unblock` | blocked/operator | Exact private monitor target present and completed playback witness recorded. |
| 22.0 | `hn-launch-vault-and-relay-claim-audit` | done in task note | Vault/relay false-green claims classified. |
| 21.0 | `hn-launch-pr-and-source-claim-audit` | done/closed | Merged PR/source claims classified against tests and deployment evidence. |
| 20.0 | `hn-launch-runtime-evidence-audit` | done/closed | Ten-surface runtime table captured. |
| 19.0 | `hn-launch-public-metrics-proof` | done | Repo receipt exists; live weblog, landing page, and HN first-comment draft corrected/verified. |
| 19.0 | `hn-launch-programme-e2e-readiness` | blocked | Live segment-prep history reconciled plus programme evidence that the final soak can re-sample and cite. |
| 18.9 | `hn-launch-segment-prep-live-output-unblock` | in progress | Fresh controlled segment-prep run produces loadable programmes with non-empty layout/action intents. |
| 18.8 | `hn-launch-programme-e2e-smoke-harness-repair` | done | Current-API scratch-only E2E harness repaired; receipt generated. |
| 18.5 | `hn-launch-compositor-sierpinski-proof` | blocked | Fresh Sierpinski layout-mode proof plus nonblank frame evidence. |
| 18.0 | `hn-launch-agentgov-cli-extraction` | done | Public repo/package/CLI install/README/license/CI acceptance checked. |
| 18.0 | `hn-launch-livestream-evidence-intake` | blocked | Current YouTube id, OBS service, RTMP, MediaMTX HLS, and audio-floor proof. |
| 18.0 | `hn-launch-30min-soak-receipt` | blocked | Green checker before start plus 30 minutes with no failed samples. |
| 17.0 | `hn-launch-social-syndication-live-proof` | blocked | Final weblog event observed on intended social surfaces. |
| 16.0 | `hn-launch-blog-post` | blocked | Public/lint-clean and metrics-correct; cross-post decision/evidence remains. |
| 16.0 | `hn-launch-logos-health-unblock` | done | Logos WARN classified under explicit service/SHM carve-out. |
| 15.0 | `hn-launch-systems-readiness` | blocked | Launch-critical failures zero; no thin probe substituted for full acceptance. |
| 15.0 | `hn-launch-post-submission` | offered/operator | Manual HN submission only after all blockers close. |
| 14.0 | `hn-launch-support-money-rails-proof` | done | Support/Sponsors/payment-rail claims verified or downgraded. |

## Corrections

- `hn-launch-systems-readiness` is the pre-soak systems-green gate. It stays
  active/blocked until launch-critical checker failures are zero; the
  downstream `hn-launch-30min-soak-receipt` task owns the final soak.
- `hn-launch-post-submission` should depend on live syndication proof, not the
  superseded `hn-launch-syndication-unblock` task.
- Historical closed fanout tasks are superseded/partial only:
  `hn-launch-weblog-producer-deploy` had unchecked fanout acceptance, and
  `hn-launch-syndication-unblock` does not prove public Mastodon/Bluesky URLs.
- Merged PRs are treated as implementation evidence only. They are not launch
  evidence unless the task acceptance and live/deployed checks also pass.
- The current HN launch request is a no-go while compositor layout mode,
  programme end-to-end proof, voice, YouTube, OBS, and social syndication proof
  remain unresolved.
- Programme E2E harness repair is complete in this PR. Focused tests passed:
  `uv run pytest tests/studio_compositor/test_director_segment_runner.py tests/hapax_daimonion/test_programme_delivery_smoke.py -q`
  -> `5 passed, 1 warning`; scratch run returned `ok=true` at
  `/tmp/hapax-hn-programme-delivery-smoke-20260512T162123Z/programme-delivery-smoke-receipt.json`.
- Live segment-prep output remains a blocker. The latest live sample has
  `completed_no_programmes`, `saved_count=0`, `segmented_count=0`, empty
  active-segment layout/action intents, and a segment-layout refusal
  `missing_current_beat_layout_intents`.
- This PR now includes a bounded planner prompt/retry fix for the zero-output
  root cause: concrete segmented-content examples, mandatory lecture
  `role_contract` guidance, and retry text for missing lecture fields and
  `narrative_beat_template` leaks. Focused tests passed:
  `uv run pytest tests/programme_manager/test_planner.py -q` -> `41 passed,
  1 warning`; adjacent contract tests passed -> `90 passed, 1 warning`.
