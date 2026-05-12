---
title: "Public Weblog And OMG Landing-Page Claim Inventory"
date: 2026-05-12
authority_case: REQ-20260512-public-weblog-and-omg-claim-hardening
cc_task: public-surface-claim-inventory-and-risk-classification
status: receipt
mutation_surface: vault_docs
---

# Public Weblog And OMG Landing-Page Claim Inventory

This receipt inventories the public `hapax.omg.lol` landing page and the
`hapax` omg.lol weblog archive before the downstream claim-hardening tasks edit
copy. It is an inventory and risk classifier, not an approval receipt.

Capture time: 2026-05-12 18:44-18:46 UTC.

## Capture Basis

- `OmgLolClient.get_web("hapax")` returned HTTP 200 content for the landing
  page. Live content hash: `d033b24a49c50fd3cbd251824820f465aa9aa24a1d5b0cf8593e15a26c4a3421`.
- `agents/omg_web_builder/static/index.html` is the local landing-page source
  candidate. Local hash:
  `08a78d519c1a7f7b2dd607f0aada672b5bcc3578f925d95dc04dcd25f735f82b`.
  The live page and local source do not byte-match; the differences are
  structural wrapper/link formatting, not the main claim block.
- `OmgLolClient.list_entries("hapax")` returned 24 weblog entries.
- `https://hapax.weblog.lol/rss.xml` returned HTTP 200 and 22 RSS items.
- `https://hapax.weblog.lol/support` returned HTTP 200.
- `https://hapax.omg.lol/support` returned the landing page, not the support
  weblog page. Any public link using the omg host for `/support` needs route
  repair or target correction.

## Source Inventory

### Landing Page

Primary source and publisher:

- `agents/omg_web_builder/static/index.html`
- `agents/omg_web_builder/publisher.py`
- `config/omg-lol.yaml`
- `shared/omg_lol_client.py`

Related public metrics receipt:

- `docs/repo-pres/2026-05-12-hn-launch-public-metrics-receipt.md`

### Weblog Production And Transport

Pipeline/source files:

- `agents/omg_weblog_composer/composer.py`
- `agents/omg_weblog_publisher/publisher.py`
- `agents/publication_bus/omg_weblog_publisher.py`
- `agents/publication_bus/surface_registry.py`
- `shared/preprint_artifact.py`
- `shared/omg_lol_client.py`
- `systemd/units/hapax-omg-weblog-composer.service`
- `systemd/units/hapax-omg-weblog-composer.timer`
- `systemd/units/hapax-omg-lol-fanout.service`
- `systemd/units/hapax-omg-lol-fanout.timer`
- `systemd/units/hapax-weblog-publish-public-event-producer.service`
- `agents/weblog_publish_public_event_producer.py`

State/source locations observed:

- `~/hapax-state/publish/draft/*.json`
- `~/hapax-state/publish/published/*.json`
- `~/hapax-state/publish/failed/*.json`
- `~/hapax-state/publish/log/*.json`
- `~/projects/hapax-research/weblog/*.md`
- `~/projects/hapax-research/lab-journals/entry-006-may-10-11.md`
- `~/projects/hapax-research/foundations/token-economic-theory-gaps-2026-05-11.md`
- `~/projects/hapax-research/ledgers/segment-prep-framework-prediction-ledger.md`
- `docs/publication-drafts/2026-05-10-show-hn-governance-that-ships.md`
- `docs/research/2026-04-25-soundcloud-cohort-disparity.md`
- `docs/refusal-briefs/*.md`

Source gaps found:

- Several live weblog entries have no matching artifact in
  `~/hapax-state/publish/{draft,published,failed}` or committed council docs:
  `support`, `6a007201aba57`, `may-8-9-lab-journal`,
  `sdlc-for-ai-agents-2026-05-09`, and `velocity-report-2026-05-09`.
- Some live entries have local pipeline receipts that say `failed`, `denied`,
  or `operator_hold`. The live archive must not be treated as already hardened
  just because a post is public.

## Claim-Risk Families

- `runtime/empirical`: live counts, PR totals, timers, devices, tests, latency,
  model timings, service status, and "current" operational claims.
- `legal/accounting`: LLC, grants, payment rails, support, tax, registration, or
  money-receipt claims.
- `market/value`: support value propositions, token-capital economics,
  publication strategy, novelty, or external value claims.
- `personal/operator`: operator biography, neurodivergence, family/dayjob, local
  paths, or identity/privacy details.
- `theoretical`: proposed conceptual frameworks, interpretation, or research
  hypotheses.
- `governance/implementation`: hooks, axioms, agent fleet, publication bus,
  consent, refusal, SDLC, and mechanical-enforcement claims.
- `publication strategy`: HN launch, CHI targeting, support conversion, public
  egress, and cross-surface narrative claims.

## Live Artifact Classification

| Artifact | Source status | Risk families | Evidence requirement | Hardening action |
|---|---|---|---|---|
| `https://hapax.omg.lol/` landing page | Local source exists but live hash differs | runtime/empirical, governance/implementation, legal/accounting, publication strategy | Use `docs/repo-pres/2026-05-12-hn-launch-public-metrics-receipt.md` for PR/hook/refusal counts; runtime check for YouTube/OBS gate; route check for support link | Patch `/support` link target; keep corrected `3,041` / `2,871` metrics only while receipt remains current |
| `show-hn-governance-that-ships` | Source in `docs/publication-drafts/2026-05-10-show-hn-governance-that-ships.md` | runtime/empirical, governance/implementation, publication strategy | Public metrics receipt; GitHub API receipt for counts; claim ceiling for "incapable" and "trust" language | Citation repair and harden "constitutionally incapable" phrasing to hook-scoped failure modes |
| `command-r-planning-exceeds-prep-timeout` | `~/hapax-state/publish/draft`, `approval: withheld`, review `operator_hold`; source in `~/projects/hapax-research/weblog/` | runtime/empirical, governance/implementation | Systemd journal/status receipt and review pass with parseable claims | Immediate quarantine or patch: public entry exists despite held review |
| `refusal-brief-why-our-ai-documents-what-it-wont-do` | `~/hapax-state/publish/draft`, `approval: withheld`, review `operator_hold`; source in `~/projects/hapax-research/weblog/` | governance/implementation, publication strategy | Refusal corpus count receipt; distinguish 47 markdown briefs from 48 registry-inclusive files | Citation repair; do not use unqualified count language |
| `entry-006-may-10-11` | `~/hapax-state/publish/draft`, review `operator_hold`; source in `~/projects/hapax-research/lab-journals/` | runtime/empirical, legal/accounting, personal/operator, publication strategy | Cross-provider review must pass; entity attribution check; private-detail screen | Immediate patch/quarantine: review log flags known entity misattribution, "Codex attributed to Anthropic; actual OpenAI" |
| `gaps-in-token-economic-theory-toward-a-theory-of-token-capital` | `~/hapax-state/publish/failed`; weblog log result `denied`; source in `~/projects/hapax-research/foundations/` | theoretical, market/value, external factual claims | Literature citations, novelty ceiling, hypothesis framing, RAG-quality caveat | Immediate quarantine or demote to hypothesis; do not leave denied artifact as public proof |
| `filesystem-as-message-bus` | `~/hapax-state/publish/failed`; weblog log result `denied`; source in `~/projects/hapax-research/weblog/` | runtime/empirical, governance/implementation | Runtime inventory receipt for agent/module/timer counts; PR-count receipt; freshness check | Patch or quarantine; "3,000+ merged PRs" requires a merged-PR receipt, not opened-PR receipt |
| `6a007201aba57` / May 10 LLC-grants-visibility post | No matching publish artifact found | legal/accounting, runtime/empirical, personal/operator, publication strategy | Legal-entity/private-record receipt; grant submission receipt; PR/commit receipt; privacy screen | Immediate citation repair; keep LLC/grant/tax/payment-rail claims below public-record evidence |
| `support` (`https://hapax.weblog.lol/support`) | Live API source only; no publish artifact found | legal/accounting, market/value, governance/implementation | Public metrics receipt and money-rail proof; no-perk/support invariant receipt | Immediate patch: live copy says `3,034 pull requests` and `zero governance failures`, both disallowed by the public metrics receipt |
| `may-8-9-lab-journal` | No matching publish artifact found | runtime/empirical, governance/implementation, personal/operator | Device/assertion/PR-count receipts and privacy screen | Citation repair; verify `145 devices`, `3000 assertions`, `108 PRs`, and personal details |
| `sdlc-for-ai-agents-2026-05-09` | No matching publish artifact found | governance/implementation, runtime/empirical | PR/claim/merge receipts; hook behavior receipts | Citation repair; soften "actually works" unless tied to precise acceptance evidence |
| `velocity-report-2026-05-09` | No matching publish artifact found | runtime/empirical, governance/implementation | GitHub API and method receipt | Citation repair; reconcile with May 12 metrics receipt |
| `start-here-hapax-ai-safety-research-artifact` | `~/hapax-state/publish/published`, grounding gate `pass` | theoretical, governance/implementation, publication strategy | Existing grounding refs plus freshness check | Review for current claim ceiling; no immediate quarantine found |
| `formal-method-value-braid-operator-surfaces-may-8-lab-journal-part-1` | `~/hapax-state/publish/published`; source in `~/projects/hapax-research/weblog/` | theoretical, governance/implementation, personal/operator | Archive framing and claim ceiling | Low immediate risk; keep as public archive, not proof |
| `grounded-agent-communication-may-7-lab-journal` | `~/hapax-state/publish/published`; source in `~/projects/hapax-research/weblog/` | theoretical, governance/implementation, personal/operator | Privacy/local-path screen; archive framing | Patch local filesystem path exposure and "private cognitive lab journal" wording if kept public |
| `segment-prep-framework-prediction-ledger` | Both `published` artifact and `failed`/`denied` logs exist; source in `~/projects/hapax-research/ledgers/` | runtime/empirical, theoretical, governance/implementation | Resolve state/log conflict; test receipt for runtime claims | Patch state conflict before treating as hardened |
| `forms-generated-authority-gated` | `~/hapax-state/publish/published`; source in `~/projects/hapax-research/weblog/` | governance/implementation, theoretical | Implementation/test receipt for authority gate claims | Citation repair and freshness check |
| `segment-prep-control-loops-closed` | `~/hapax-state/publish/published`; source in `~/projects/hapax-research/weblog/` | governance/implementation, runtime/empirical | Implementation/test receipt and current-state freshness check | Citation repair if still current; otherwise historical framing |
| `systems-control-theory-reorientation` | `~/hapax-state/publish/published`; source in `~/projects/hapax-research/weblog/` | theoretical, governance/implementation | Hypothesis framing and source bibliography | Low immediate risk if framed as design journal |
| `non-anthropomorphic-segment-prep-lab-journal` | `~/hapax-state/publish/published`; duplicate failed artifact variants exist | theoretical, governance/implementation | Resolve duplicate slug/state; archive framing | Dedupe state and ensure one canonical public entry |
| `2026-05-03-velocity-report-followup` | Source in `~/projects/hapax-research/weblog/`; live entry exists | runtime/empirical | GitHub API receipt and correction note | Citation repair; preserve limitations/reconciliation language |
| `velocity-report-2026-04-25` | `~/hapax-state/publish/published`; related research docs exist | runtime/empirical | Evidence-baseline correction and GitHub API receipt | Keep correction note prominent; no stronger claims without receipts |
| `cohort-disparity-disclosure` | `~/hapax-state/publish/published`; source basis in `docs/research/2026-04-25-soundcloud-cohort-disparity.md` | runtime/empirical, market/value, personal/operator | SoundCloud snapshot receipt and no-causality claim ceiling | Verify snapshot availability; retain "does not claim" section |
| `page_template` | Live API entry type `Template`; public dated URL returned 404 during this capture | publication hygiene | API delete/quarantine receipt | Remove/quarantine from live entries list if it is not intended public content |
| `refusal-brief` | `~/hapax-state/publish/published`; docs in `docs/refusal-briefs/` | governance/implementation, publication strategy | Refusal corpus count receipt and surface-registry citation | Citation repair for counts and surface-list freshness |

## Immediate High-Risk Queue

1. Patch or quarantine `support`: stale `3,034` metric and unsupported
   `zero governance failures` contradict
   `docs/repo-pres/2026-05-12-hn-launch-public-metrics-receipt.md`.
2. Patch the landing-page support link. `https://hapax.omg.lol/support`
   currently serves the landing page; the live support page is under
   `https://hapax.weblog.lol/support`.
3. Quarantine or repair the three public entries with `operator_hold` review
   logs: `command-r-planning-exceeds-prep-timeout`,
   `refusal-brief-why-our-ai-documents-what-it-wont-do`, and
   `entry-006-may-10-11`.
4. Quarantine or repair public entries whose local publish logs say `denied` or
   `failed`: especially `gaps-in-token-economic-theory...`,
   `filesystem-as-message-bus`, and `segment-prep-framework-prediction-ledger`.
5. Patch `entry-006-may-10-11` for the known entity error in the review log:
   Codex is OpenAI, not Anthropic.
6. Repair all legal/accounting and money-rail claims in the May 10 lab-journal
   post and support page against private legal records and public-safe receipts.
7. Remove/quarantine `page_template` if it is only a template artifact.

## Execution Status After Live Patch

Executed on 2026-05-12 after this capture:

- Landing page source and live page were patched to scope governance, privacy,
  and persistence claims to governed paths. The support link now targets
  `https://hapax.weblog.lol/support` rather than the non-weblog omg host.
- Show HN source and live post were patched to remove absolute impossibility
  claims. The live feed no longer contains `physically cannot`,
  `No test results, no push`, `constitutionally incapable`, or the all-surface
  production claim.
- `gaps-in-token-economic-theory-toward-a-theory-of-token-capital` was replaced
  with a supersession notice because the public copy conflicted with the
  Token Capital audits and RAG utilization blocker.
- `entry-006-may-10-11` was replaced with a supersession notice because the
  public copy predated the lab-journal claim repair pass.
- `support` was patched from stale `3,034` / failure-free governance language
  to the 2026-05-12 public metrics receipt: `3,041` opened PRs, `2,871` merged
  PRs, five revert-titled PRs, and an explicit activity/review-surface claim
  ceiling.
- Weblog identity was repaired after `shared/omg_lol_client.py` was fixed to
  submit weblog configuration as the raw text body expected by the API.
  `feed.json` now reports `Hapax Weblog` and `Hapax`.

Remaining archive-pass work:

- Patch or quarantine `command-r-planning-exceeds-prep-timeout` and
  `refusal-brief-why-our-ai-documents-what-it-wont-do`, which still have
  `operator_hold` review state in local publish logs.
- Patch or quarantine `filesystem-as-message-bus` and
  `segment-prep-framework-prediction-ledger`, whose local state/logs conflict
  with live publication.
- Run the full weblog archive pass over every feed item in the table above.

## Downstream Gate Requirements

The scrutiny gate should block future public publication when any of these are
true:

- A matching `~/hapax-state/publish/log/*.json` result is `denied`, `failed`,
  `operator_hold`, `no_credentials`, or has parse-failed review issues.
- The post contains public launch metrics not present in an attached receipt.
- The post contains `zero governance failures` without a separate root-cause
  audit receipt.
- The post contains legal/accounting, grant, payment, or tax claims without an
  operator-approved public-safe evidence receipt.
- The live API entry has no source artifact in either the publish state tree,
  the council repo, or `~/projects/hapax-research/`.
- The post's public URL differs from the linked URL used by landing-page or
  README copy.

## Deterministic Gate Added

Run the public-surface claim gate before publishing weblog or landing-page
copy:

```bash
uv run python scripts/check-public-surface-claims.py
```

Use `--warnings-fail` for Token Capital, value, novelty, or CHI-positioning
claims.

## Verification Commands

```bash
uv run python - <<'PY'
from shared.omg_lol_client import OmgLolClient
c = OmgLolClient()
print(len((c.list_entries("hapax") or {}).get("response", {}).get("entries", [])))
print((c.get_web("hapax") or {}).get("request", {}).get("status_code"))
PY

curl -fsSL https://hapax.weblog.lol/rss.xml | \
  python3 -c 'import sys, xml.etree.ElementTree as ET; root=ET.fromstring(sys.stdin.buffer.read()); print(len(root.findall("./channel/item")))'

curl -fsSL https://hapax.weblog.lol/support | \
  python3 -c 'import sys; text=sys.stdin.read(); print("3,034" in text, "zero governance failures" in text)'

for f in ~/hapax-state/publish/log/*.json; do
  jq -r '[input_filename, (.slug // ""), (.surface // ""), (.result // ""), ((.flagged_issues // []) | join(";"))] | @tsv' "$f"
done
```
