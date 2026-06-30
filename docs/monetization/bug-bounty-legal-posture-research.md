---
title: "Bug-Bounty Legal Posture Research"
type: research
created: 2026-06-30
authority_case: CASE-SDLC-REFORM-001
parent_request: REQ-20260628-mdlc-tax-legal-posture-registry
parent_spec: hapax-council/docs/superpowers/specs/2026-05-30-sdlc-frictionless-self-direction-design.md
cc_task: 20260628-registry-phase3-bug-bounty-subtree
tags: [research, legal-registry, bug-bounty, g2, mdlc]
status: active
---

# Bug-Bounty Legal Posture Research

Reviewed on 2026-06-30. This note supports the rows appended to
`docs/monetization/legal-posture-registry.yaml` for the direct AI red-team /
bug-bounty subtree. It is a registry input, not legal advice.

## Boundary

The surviving route is direct invited lab work: submit a bounded model-safety
finding to the lab that invited that class of finding, through that lab's own
program channel, under its current scope and confidentiality terms.

The brokered vulnerability resale route is not a gated variant of the direct
route. It is struck in `REQ-20260628-arbitrage-struck-and-blocked-register`
because it routes weaponizable vulnerabilities to undisclosed downstream buyers.
The registry records this as DARK so later planning cannot silently fall back
to brokered resale when a direct lab program is unavailable.

## Source Findings

- Anthropic's current Model Safety Bug Bounty Program is run through HackerOne,
  accepts selected participants, provides an authorized free model alias for
  red-teaming, requires confidentiality, and offers up to $35,000 for qualifying
  novel universal jailbreaks. Source:
  https://support.claude.com/en/articles/12119250-model-safety-bug-bounty-program.
- OpenAI's GPT-5.5 Bio Bug Bounty is an application/invite-gated program for a
  universal jailbreak against a five-question bio safety challenge in GPT-5.5
  Codex Desktop, with NDA-covered findings and a $25,000 first-success reward.
  Source: https://openai.com/index/gpt-5-5-bio-bug-bounty/.
- 15 CFR 734.13 treats release or transfer of technology or source code to a
  foreign person in the United States as a deemed export. 15 CFR 734.15 defines
  release to include visual inspection revealing technology/source code and oral
  or written exchanges. Sources:
  https://www.ecfr.gov/current/title-15/subtitle-B/chapter-VII/subchapter-C/part-734/section-734.13
  and
  https://www.ecfr.gov/current/title-15/subtitle-B/chapter-VII/subchapter-C/part-734/section-734.15.
- License Exception ACE, 15 CFR 740.22, authorizes some exports, reexports,
  transfers, and deemed exports/reexports of cybersecurity items, but has
  destination, end-user, and end-use restrictions. Source:
  https://www.ecfr.gov/current/title-15/subtitle-B/chapter-VII/subchapter-C/part-740/section-740.22.
- ECCN 4D004 is listed as a cybersecurity item in 15 CFR 740.22(b)(1), and 15
  CFR 772.1 defines intrusion software. Text prompts and ordinary written
  reports are separated from software/tool export; any agentic harness or
  exploit tooling needs classification before clearance. Source:
  https://www.ecfr.gov/current/title-15/subtitle-B/chapter-VII/subchapter-C/part-772/section-772.1.
- 17 USC 1201(a) prohibits circumvention of technological measures, while 17 USC
  1201(j) addresses security testing with owner/operator authorization and
  direct security-promoting use or disclosure. Source:
  https://uscode.house.gov/view.xhtml?req=%28title%3A17+section%3A1201+edition%3Aprelim%29.
- 26 USC 183 limits deductions for activities not engaged in for profit. IRS
  guidance asks whether the activity is conducted like a business, with records,
  profit intent, expertise, and businesslike operation; IRS Publication 525
  covers taxable prizes and awards. Sources:
  https://uscode.house.gov/view.xhtml?edition=prelim&num=0&req=granuleid%3AUSC-prelim-title26-section183,
  https://www.irs.gov/newsroom/know-the-difference-between-a-hobby-and-a-business,
  and https://www.irs.gov/publications/p525.

## Registry Disposition

- Direct Anthropic model-safety jailbreak bounty: DARK. The row preserves a
  candidate direct-lab path, but it needs actual program acceptance, NDA
  compliance, scope control, and operator signature before the g2 gate can pass.
- Direct OpenAI GPT-5.5 bio bounty: DARK. The public page reviewed on
  2026-06-30 shows the application deadline was 2026-06-22 and testing runs
  through 2026-07-27, so the route needs existing acceptance or a later
  reopened/accepted cohort before it can be upgraded.
- Brokered vulnerability resale: DARK. This is struck governance posture, not an
  unresolved legal research question.
- ACE/deemed-export and ECCN 4D004 tooling: DARK until item classification,
  recipient/destination/end-use screening, and export-control review are
  complete. Direct text-only submissions should be kept text-only to avoid
  importing this risk into the first play.
- DMCA 1201 direct authorized security testing: DARK until authorization, scope,
  and direct developer disclosure constraints are documented and signed. Pure
  text-prompt model-safety testing may not involve a technological protection
  measure, but the registry does not claim clearance yet.
- Tax/hobby-loss: DARK until payout receipt handling, recordkeeping, expense
  treatment, and operator tax posture are documented.

## Operating Rule

For the first bug-bounty play, the lowest-risk legal posture is:

1. Apply to or use only an accepted direct lab program.
2. Keep the candidate and repro package text-only unless separate export review
   clears tooling.
3. Do not share prompts, code, or findings outside the lab's authorized program
   channel.
4. Record payout and expenses in the durable receipt sink before scoring M.
5. Treat brokered resale as unavailable, not as a fallback.
