---
title: "Prediction-Market Legal Posture Research"
type: legal-research
created: 2026-06-30
authority_case: CASE-SDLC-REFORM-001
parent_request: REQ-20260628-mdlc-tax-legal-posture-registry
parent_spec: hapax-council/docs/superpowers/specs/2026-05-30-sdlc-frictionless-self-direction-design.md
cc_task: 20260628-registry-phase2-prediction-market-subtree
tags: [legal-registry, prediction-market, minnesota, cftc, tax, ndcvb]
status: active
---

# Prediction-Market Legal Posture Research

This is non-attorney registry research, not legal advice. The registry rows stay
`DARK`; no operator trading route is cleared.

## Method

- Started from the phase-1 Minnesota residence row and the struck/blocked
  register. Operator state for current planning is Minnesota, confirmed
  2026-06-28.
- Used official sources where available: Minnesota session law/statutes, CFTC
  materials, U.S. Code, IRS guidance, and the CFTC Polymarket order.
- Encoded new rows in `docs/monetization/legal-posture-registry.yaml`.
- Treated federal/state preemption, tax classification, platform access, and
  feed resale as unresolved until operator/counsel signs a narrower row.

## Recheck

Run from the repository root:

```bash
uv run python - <<'PY'
from pathlib import Path
import yaml

data = yaml.safe_load(Path("docs/monetization/legal-posture-registry.yaml").read_text())
rows = data["rows"]
keys = [(row["surface"], row["venue"], row["instrument"]) for row in rows]
assert len(keys) == len(set(keys)), "duplicate registry tuple"

phase2 = [
    row for row in rows
    if row.get("source_task") == "20260628-registry-phase2-prediction-market-subtree"
]
assert len(phase2) == 6
assert all(row["surface"] == "prediction_market" for row in phase2)
assert all(row["g2_verdict"] == "DARK" for row in phase2)
assert all(row["operator_signed"] is False for row in phase2)
assert all(row["review_date"] == "2026-06-30" for row in phase2)

phase2_keys = {(row["venue"], row["instrument"]): row for row in phase2}
required = {
    ("US-MN", "operator_prediction_market_trading"),
    ("US-CFTC", "regulated_event_contract_trading"),
    ("US-IRS", "section_1256_event_contract_tax_position"),
    ("US-IRS", "obbba_165d_wagering_loss_cap"),
    ("polymarket_global", "us_person_event_contract_trading"),
    ("US-MN", "ndcvb_manipulation_detection_feed_non_trading"),
}
assert set(phase2_keys) == required

mn = phase2_keys[("US-MN", "operator_prediction_market_trading")]
assert "Standing Minnesota strike" in mn["notes"]
assert "609.7615" in mn["citation"]
assert "Minnesota" in mn["citation"]

tax_1256 = phase2_keys[("US-IRS", "section_1256_event_contract_tax_position")]
assert "§1256" in tax_1256["notes"]
assert "mark-to-market" in tax_1256["citation"]

obbba = phase2_keys[("US-IRS", "obbba_165d_wagering_loss_cap")]
assert "90 percent" in obbba["citation"]
assert "OBBBA" in obbba["citation"]

ndcvb = phase2_keys[("US-MN", "ndcvb_manipulation_detection_feed_non_trading")]
assert "not a wager" in ndcvb["notes"]
assert "not automated trading" in ndcvb["notes"]
assert "must not be sold directly to a prediction market" in ndcvb["notes"]
assert "REQ-ndcvb-as-a-service" in ndcvb["blocks_surfaces"]

print("prediction-market phase2 registry recheck OK")
PY
```

## Source Findings

### Minnesota: Standing Strike For Operator Trading

Minnesota is the operator state input. The current row remains RED/DARK for
operator trading. Minnesota Laws 2026, Chapter 97, Article 8 creates a
prediction-market offense effective August 1, 2026, amends the securities and
commodities carveout in the gambling definitions, and includes data/support
service prohibitions tied to allowing or settling prohibited wagers. Existing
Minn. Stat. 609.755 also makes making a bet a misdemeanor.

Registry effect: `US-MN / operator_prediction_market_trading` remains `DARK`.

Sources:
- Minnesota Laws 2026, Chapter 97, Article 8:
  https://www.revisor.mn.gov/laws/2026/0/Session%2BLaw/Chapter/97/
- Minn. Stat. 609.755:
  https://www.revisor.mn.gov/statutes/cite/609.755
- Minn. Stat. 609.75:
  https://www.revisor.mn.gov/statutes/cite/609.75

### CFTC Event-Contract Posture

CFTC materials describe prediction-market event contracts as typically swaps and
state that regulated markets carry DCM/SEF, core-principle, surveillance, and
market-integrity obligations. The June 2026 proposed rulemaking frames the
Special Rule analysis for event contracts involving gaming or activity unlawful
under state or federal law. CFTC Staff Advisory 25-36 records that some
sports-related contracts were self-certified rather than affirmatively approved
under the approval path, and notes conflicting state-preemption litigation.

Registry effect: `US-CFTC / regulated_event_contract_trading` remains `DARK`.

Sources:
- CFTC Learn & Protect, Understanding Prediction Markets and Event Contracts:
  https://www.cftc.gov/LearnandProtect/PredictionMarkets
- CFTC, Prediction Markets; Public Interest Determinations, 91 Fed. Reg. 35806
  (June 12, 2026):
  https://www.federalregister.gov/documents/2026/06/12/2026-11854/prediction-markets-public-interest-determinations
- CFTC Staff Advisory No. 25-36:
  https://www.cftc.gov/csl/25-36/download

### State Preemption Split

The Maryland federal district court denied Kalshi preliminary relief against
state gaming enforcement and found Kalshi had not shown likely CEA preemption.
The Third Circuit reached the opposite preliminary-injunction result for New
Jersey, concluding Kalshi had a reasonable chance of success on CEA preemption.
This split is enough to keep non-Minnesota rows DARK absent a venue-specific
final authority and counsel/operator sign-off.

Registry effect: no state venue receives LIT/PARTIAL from this task.

Sources:
- KalshiEX LLC v. Martin, No. 1:25-cv-1283 (D. Md. Aug. 1, 2025):
  https://law.justia.com/cases/federal/district-courts/maryland/mddce/1%3A2025cv01283/581016/70/
- KalshiEX LLC v. Flaherty, No. 25-1922 (3d Cir. Apr. 6, 2026):
  https://www2.ca3.uscourts.gov/opinarch/251922p.pdf

### Section 1256 And Wagering Tax Treatment

Section 1256 gives mark-to-market treatment to covered contracts. The task did
not find an official IRS ruling that prediction-market event contracts are
Hapax-cleared section 1256 contracts. That classification remains too important
to infer from CFTC registration alone.

Registry effect: `US-IRS / section_1256_event_contract_tax_position` remains
`DARK`.

Sources:
- 26 USC §1256:
  https://uscode.house.gov/view.xhtml?edition=prelim&num=0&req=granuleid%3AUSC-prelim-title26-section1256
- IRS Form 6781:
  https://www.irs.gov/forms-pubs/about-form-6781

### OBBBA / Section 165(d) Wagering-Loss Cap

If event-contract activity is treated as wagering, OBBBA changed the wagering
loss deduction floor. Current 26 USC §165(d) and IRS IRB 2026-19 state the
deduction is limited to 90 percent of wagering losses and only to the extent of
wagering gains for taxable years beginning after 2025.

Registry effect: `US-IRS / obbba_165d_wagering_loss_cap` remains `DARK`.

Sources:
- 26 USC §165(d):
  https://uscode.house.gov/view.xhtml?edition=prelim&num=0&req=granuleid%3AUSC-prelim-title26-section165
- IRS IRB 2026-19:
  https://www.irs.gov/irb/2026-19_IRB

### Polymarket Global / U.S. Person Trading

The CFTC's 2022 Polymarket order found event-based binary options were offered
without required registration/designation and required noncompliant market
access to cease unless compliant with the CEA and CFTC regulations. This row is
limited to the offshore/global venue; it does not decide any separate
CFTC-registered U.S. venue.

Registry effect: `polymarket_global / us_person_event_contract_trading` remains
`DARK`.

Source:
- CFTC Order, In re Blockratize, Inc. d/b/a Polymarket.com, Docket No. 22-09:
  https://www.cftc.gov/media/6891/enfblockratizeorder010322/download

### NDCVB Manipulation-Detection Feed

The struck/blocked register preserves the NDCVB manipulation-detection feed as
different from prediction-market trading because the feed does not place
positions. Phase 2 keeps that distinction, but does not clear a commercial feed.
Minnesota Chapter 97 is especially important: direct data, information, or
verification services to a prediction market can be prohibited when known to
allow or settle prohibited wagers. A safe candidate, if any, must be non-trading,
public/authorized-data-based, not buyer-used for pricing/settlement/wager
facilitation, and operator-signed.

Registry effect: `US-MN / ndcvb_manipulation_detection_feed_non_trading` remains
`DARK`, but is not classified as placing positions.

Sources:
- REQ-20260628-arbitrage-struck-and-blocked-register
- Minnesota Laws 2026, Chapter 97, Article 8:
  https://www.revisor.mn.gov/laws/2026/0/Session%2BLaw/Chapter/97/
- CFTC Learn & Protect, market integrity/surveillance discussion:
  https://www.cftc.gov/LearnandProtect/PredictionMarkets
