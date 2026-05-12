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

Hard failures:

- `compositor_visual_surface`: layout mode is not Sierpinski.
- `programme_segments`: active programme segment is stale, incomplete, or empty.
- `daimonion_voice_segments`: no completed playback is recorded in
  `voice-output-witness`.
- `youtube_livestream`: livestream video id is missing, empty, or stale.
- `obs_clean_feed`: `hapax-obs-livestream` is inactive; public claim is not
  allowed; RTMP, MediaMTX HLS, and audio-floor evidence are failing.

Warning:

- `logos_api`: API overall status is `failed`.

Current passes are reverie/imagination freshness, GitHub README, omg.lol weblog
reachability, and systemd timer/failed-unit budget. Earlier samples had
compositor and programme freshness green, but the final pre-PR sample did not;
that volatility is itself no-go evidence.

## Claim Classification

| Claim | Classification | Evidence | Launch implication |
|---|---|---|---|
| HN systems readiness is complete | false | `hn-launch-systems-readiness` is active/blocked; latest checker still fails compositor, programme segment freshness, voice, YouTube, and OBS. | Blocks soak and HN post. |
| PR #3149 makes HN ready | false | PR #3149 merged 2026-05-12T14:21:18Z as a warning-budget/support fix. It does not clear hard readiness failures. | Must not auto-close systems readiness. |
| Compositor visual surface is live | partial/stale | Earlier reconciliation sample reported pass; final pre-PR sample reports `compositor_visual_surface: fail` because layout mode is not Sierpinski. | Requires fresh stable pass before soak. |
| Programme segments are launch-ready | false in latest sample; partial historically | Earlier checker saw a fresh populated active segment, but final pre-PR sample reports stale/incomplete/empty and runtime audit found end-to-end receipts stale/held/refused. | Requires `hn-launch-programme-e2e-readiness`. |
| Daimonion voice is speaking launch segments | false | Latest checker reports `daimonion_voice_segments: fail`. | Requires operator/hardware route unblock. |
| Reverie/imagination surface is fresh | partial | Checker pass is freshness evidence, not correlated response proof. | May enter passive observation only after hard failures clear. |
| Logos API is healthy | partial | Service/SHM evidence can be ready, but API overall status is `failed`. | `hn-launch-logos-health-unblock` must resolve warning semantics. |
| README has launch support/trust positioning | verified | README has DOI, Sponsor badge, support URL, pending-Sponsors caveat, trust/governance framing, and agentgov link. Checker reports `github_readme: pass`. | README leaf is green. |
| omg.lol HN weblog post is public | verified for weblog publication; partial for blog task | `https://hapax.weblog.lol/rss.xml` and `/feed/` return the Show HN post. `hn-launch-blog-post` still has cross-post and hardening acceptance unchecked. | Blog task remains open until POSSE/hardening evidence is reconciled. |
| YouTube livestream is active | false | Latest checker reports `youtube_livestream: fail`. | Blocks systems readiness. |
| OBS clean feed is public-claim safe | false | Latest checker reports `obs_clean_feed: fail`; `hapax-obs-livestream` inactive. | Blocks systems readiness. |
| Timer/failed-unit budget is within threshold | verified | Latest checker reports `systemd_timer_failed_unit_budget: pass`. | One checklist item green. |
| GitHub topics are complete | verified | Closed task `hn-launch-github-topics`, PR #3035, and receipt `docs/repo-pres/2026-05-10-hn-launch-github-topics.md`. | Complete leaf. |
| Zenodo DOI is minted | verified | Closed task `hn-launch-zenodo-doi`, PR #3043, README badge, DOI `10.5281/zenodo.20113515`. | Complete nice-to-have leaf. |
| agentgov launch artifact is complete | partial | `hapax-systems/agentgov` is public, MIT licensed, has CLI docs, and PyPI `hapax-agentgov==0.3.0` exists. PyPI `agentgov` returns 404, no latest GitHub release is present, and `hn-launch-agentgov-cli-extraction` acceptance is unchecked. | Blocks blog/post until package-name and acceptance are reconciled. |
| Weblog/social syndication is live | partial/stale | PR #3038 and #3039 merged code/tooling, but closed tasks have unchecked fanout acceptance and `hn-launch-social-syndication-live-proof` is blocked on final URL/fanout proof. | Blocks post-submission. |
| Support page is reachable | verified for page reachability; partial for rails | `https://hapax.omg.lol/support` returns 200 and says support buys no access, requests, priority, deliverables, or control. | Support copy is usable; rails still need proof. |
| All money rails are active | partial | `hapax-money-rails.service` is active and polls Alby successfully, but current logs include Nostr relay failures and a Liberapay 404. | Keep `hn-launch-support-money-rails-proof` open. |
| GitHub Sponsors are approved/active | false as a must-have claim | README says Sponsors approval is pending; parent request says pending. Support page links Sponsors, but approval is not verified. | Must be downgraded or explicitly resolved before launch copy claims it. |

## WSJF Readiness Tree

| WSJF | Task | Current state | Evidence standard before launch |
|---:|---|---|---|
| 24.0 | `hn-launch-readiness-tree-reconciliation` | in progress in this PR | This receipt merged and task closed. |
| 23.0 | `hn-launch-daimonion-voice-playback-unblock` | blocked/operator | Exact private monitor target present and completed playback witness recorded. |
| 22.0 | `hn-launch-vault-and-relay-claim-audit` | done in task note | Vault/relay false-green claims classified. |
| 21.0 | `hn-launch-pr-and-source-claim-audit` | claimed; no lane output attached at this receipt time | Merged PR/source claims classified against tests and deployment evidence. |
| 20.0 | `hn-launch-runtime-evidence-audit` | done/closed | Ten-surface runtime table captured. |
| 19.0 | `hn-launch-programme-e2e-readiness` | blocked | Active segment, director receipt, layout/action satisfaction, and soak-survivable proof. |
| 18.0 | `hn-launch-agentgov-cli-extraction` | in progress | Public repo/package/CLI install/README/license/CI acceptance checked. |
| 18.0 | `hn-launch-livestream-evidence-intake` | blocked | Current YouTube id, OBS service, RTMP, MediaMTX HLS, and audio-floor proof. |
| 18.0 | `hn-launch-30min-soak-receipt` | blocked | Green checker before start plus 30 minutes with no failed samples. |
| 17.0 | `hn-launch-social-syndication-live-proof` | blocked | Final weblog event observed on intended social surfaces. |
| 16.0 | `hn-launch-blog-post` | in progress | Public post, cross-post decision/evidence, hardening receipt, readiness-safe wording. |
| 16.0 | `hn-launch-logos-health-unblock` | claimed | Exact health failure classified or cleared. |
| 15.0 | `hn-launch-systems-readiness` | blocked | Launch-critical failures zero; no thin probe substituted for full acceptance. |
| 15.0 | `hn-launch-post-submission` | offered/operator | Manual HN submission only after all blockers close. |
| 14.0 | `hn-launch-support-money-rails-proof` | offered | Support/Sponsors/payment-rail claims verified or downgraded. |

## Corrections

- `hn-launch-systems-readiness` stays active/blocked until launch-critical
  checker failures are zero and the 30-minute soak passes.
- `hn-launch-post-submission` should depend on live syndication proof, not the
  superseded `hn-launch-syndication-unblock` task.
- Merged PRs are treated as implementation evidence only. They are not launch
  evidence unless the task acceptance and live/deployed checks also pass.
- The current HN launch request is a no-go while compositor layout mode,
  programme segment freshness/end-to-end proof, voice, YouTube, OBS, social
  syndication proof, agentgov package acceptance, and support/money-rail proof
  remain unresolved.
