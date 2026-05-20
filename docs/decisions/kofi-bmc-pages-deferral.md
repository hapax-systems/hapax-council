# Decision: Ko-fi and Buy Me a Coffee Pages Deferred

**Date:** 2026-05-20
**Authority:** CASE-20260510-HACKERNEWS-
**Decision:** Defer to post-launch operator action
**Reason:** Account creation and page setup require operator-physical action

## Ko-fi

Creating a Ko-fi page requires:
1. Operator signs up at ko-fi.com with personal/business email
2. Connects PayPal or Stripe account
3. Configures donation page text and goals
4. Links from README/support pages

This is operator-only work. The revenue platform W-9/payout matrix
(`config/revenue-platform-w9-payout-matrix.yaml`) already tracks Ko-fi
as a target platform with setup steps.

## Buy Me a Coffee

Creating a BMC page requires the same operator-physical steps.
Not tracked in the current W-9 matrix — can be added when the operator
decides to proceed.

## HN Launch Impact

Neither page blocks HN submission. GitHub Sponsors (already configured)
provides the primary support surface for launch.
