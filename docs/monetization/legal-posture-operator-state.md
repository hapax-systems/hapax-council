---
title: "Legal-Posture Registry - Operator State Input"
type: legal-research
created: 2026-06-30
authority_case: CASE-SDLC-REFORM-001
parent_request: REQ-20260628-mdlc-tax-legal-posture-registry
parent_spec: hapax-council/docs/superpowers/specs/2026-05-30-sdlc-frictionless-self-direction-design.md
cc_task: 20260628-registry-phase1-operator-state-of-residence-confirmation
tags: [legal-registry, g2, operator-state, prediction-market, monetization]
status: active
---

# Legal-Posture Registry - Operator State Input

This note records the phase 1 operator-state input for the prediction-market
legal posture rows. It is not legal advice and does not clear trading.

## Input

The operator state of residence for current MonDLC planning is Minnesota,
confirmed on 2026-06-28 in
`REQ-20260628-arbitrage-struck-and-blocked-register`.

The registry preserves this as a dated input row rather than a mutable profile
field. If residence changes later, add a new dated row and rerun dependent
prediction-market posture analysis.

## Source Witness

REQ-20260628-arbitrage-struck-and-blocked-register records the operator state
input as: `Operator state of residence: Minnesota (confirmed 2026-06-28)`.

The same struck/blocked register records the current trading consequence as:
`Prediction-market TRADING` is blocked because the operator state is Minnesota
and Minnesota bans prediction markets, so the current posture is RED for
trading. Only non-trading manipulation-detection/readiness feeds remain outside
that trading block.

## Minnesota Prediction-Market Posture

The current planning result is DARK for Minnesota prediction-market trading.
The fail-closed posture rests on:

- Minn. Stat. 609.755: making a bet is a misdemeanor unless otherwise
  authorized.
- Minn. Stat. 609.75 subd. 2: a bet covers a bargain for gain or loss of money,
  property, or benefit dependent on chance, even with some skill.
- Minnesota House Research H.F. 4437 summary, Mar. 30, 2026: prediction-market
  shares were described as a target of Minnesota legislation; the summary says
  the bill would exclude those shares from the securities/commodities carveout
  and treat them as illegal gambling.

The registry therefore blocks prediction-market wagers or event-contract
participation by the Minnesota operator until a separate counsel/operator
upgrade changes the row. This does not block non-trading feeds such as
manipulation detection or readiness intelligence when they do not place
positions, accept wagers, advertise markets, or receive trading value.

## Recheck Command

```bash
uv run python - <<'PY'
from pathlib import Path
from urllib.request import Request, urlopen
import yaml

registry = Path("docs/monetization/legal-posture-registry.yaml")
note = Path("docs/monetization/legal-posture-operator-state.md").read_text()
data = yaml.safe_load(registry.read_text())
rows = data["rows"]
keys = {(row["surface"], row["venue"], row["instrument"]): row for row in rows}

operator_key = (
    "prediction_market",
    "US-MN",
    "operator_state_residence_confirmed_20260628",
)
trading_key = (
    "prediction_market",
    "US-MN",
    "event_contract_or_prediction_market_wager",
)
assert operator_key in keys
assert trading_key in keys
operator_row = keys[operator_key]
trading_row = keys[trading_key]
assert operator_row["g2_verdict"] == "DARK"
assert trading_row["g2_verdict"] == "DARK"
assert operator_row["authority_basis"] == "operator_judgment"
assert trading_row["authority_basis"] == "statute"
assert "REQ-20260628-arbitrage-struck-and-blocked-register" in operator_row["citation"]
assert "Minnesota" in operator_row["citation"]
assert "2026-06-28" in operator_row["citation"]
assert "Confidence: high" in operator_row["notes"]
assert "Future residence changes require a new dated row" in operator_row["notes"]
assert "609.755" in trading_row["citation"]
assert "609.75" in trading_row["citation"]
assert "HF4437.pdf" in trading_row["citation"]
assert "20260628-registry-phase2-prediction-market-subtree" in operator_row["blocks_surfaces"]
assert len(keys) == len(rows), "duplicate registry tuple"
assert "REQ-20260628-arbitrage-struck-and-blocked-register records" in note
assert "Operator state of residence: Minnesota (confirmed 2026-06-28)" in note
assert "Prediction-market TRADING" in note
assert "Minnesota bans prediction markets" in note
assert "non-trading manipulation-detection/readiness feeds" in note
source_urls = [
    "https://www.revisor.mn.gov/statutes/cite/609.755",
    "https://www.revisor.mn.gov/statutes/cite/609.75",
    "https://www.house.mn.gov/hrd/bs/94/HF4437.pdf",
]
for url in source_urls:
    request = Request(url, method="HEAD", headers={"User-Agent": "hapax-validation/1.0"})
    try:
        with urlopen(request, timeout=20) as response:
            status = response.status
    except Exception:
        request = Request(url, headers={"User-Agent": "hapax-validation/1.0"})
        with urlopen(request, timeout=20) as response:
            status = response.status
    assert status == 200, (url, status)
print("operator-state registry recheck OK: US-MN DARK prediction-market rows present")
PY
```
