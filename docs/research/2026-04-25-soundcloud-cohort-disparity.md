---
type: research-drop
date: 2026-04-25
title: SoundCloud Cohort Disparity Analysis — oudepode First-Hours
agent_id: first-sc-research
status: actioned
artifact_published: https://hapax.weblog.lol/cohort-disparity-disclosure
---

# SoundCloud Cohort Disparity Analysis — oudepode First-Hours

## Verdict

MIXED, leaning ANOMALOUS-INFLATED. Numbers 5–30× above organic baseline for zero-follower account. The 13-vs-151 cohort disparity is the loudest single signal — diagnostic of selective traffic (bot or external link) rather than even algorithmic distribution.

## Observed distribution (2026-04-25, ~2hrs after public)

| Track | Plays | Likes |
|---|---|---|
| visage best | 151 | 1 |
| dump disciple | 151 | 1 |
| alekhine batteries | 143 | 0 |
| BIOSCOPE | 129 | 0 |
| UNKNOWNTRON | 36 | 0 |
| PLUMPCORP | 13 | 0 |

Aggregate: 623 plays / 3 likes — like:play ratio **0.48%** (organic baseline 2–8%).

## Calibration bands

- Organic free account, 0 followers: 0–5 plays/hr
- Next Pro First Fans (Amplify) push: 10–30 plays/hr
- Bot/click-farm traffic: 100–1000+ plays/hr in bursts

oudepode at 36–151 plays in 2hrs sits in the bot or top-of-Amplify-with-bot-stack band.

## Diagnostic signals

1. **Cohort variance.** Six tracks released simultaneously; organic algorithm distributes evenly. The PLUMPCORP-vs-others gap is selective-traffic signature.
2. **Like:play ratio.** 0.48% aggregate is below the organic floor (2%) and inside the bot band (<1%).
3. **"7 days" badge.** Active SoundCloud Next Pro First Fans Amplify push, NOT just UI freshness. Engagement-gated; kills promotion at day 7 if metrics stay low.

## Leverage actions

1. **Auto-attestation publisher** — Hapax cron generates daily SC metrics page at hapax.weblog.lol with retention% + like:play ratios, NOT raw plays. Pure constitutional-disclosure.
2. **First-Fans audit script** — Hapax pulls SC Insights API daily; auto-flags <20% retention or <1% like-ratio as algorithmically-rejected.
3. **Cohort-disparity disclosure post** — auto-publish the 13-vs-151 anomaly as constitutional-thesis content. SHIPPED 2026-04-25 at hapax.weblog.lol/cohort-disparity-disclosure.
4. **Bandcamp auto-mirror** — REFUSED (no Bandcamp upload API; cross-account research confirms Internet Archive `ias3` is the only daemon-tractable music path).
5. **72h wait-and-watch gate** — defer further leverage 72hrs; if like-ratio stays <1.5% and retention <40%, treat as inflated and pivot to refusal-disclosure track only.

## Sources

- SoundCloud Next Pro First Fans (Amplify) program docs
- Columbia/Barracuda IMC 2025: AI-driven spam now >50%
- DataDome / AWS bot-detection partnership
- 2025 organic-vs-inflated like-ratio comparison studies
