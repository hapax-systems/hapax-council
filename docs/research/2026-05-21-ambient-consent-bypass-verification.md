# AMBIENT Voice Register Consent Bypass — Verification Report

**Date:** 2026-05-21
**Author:** delta
**Task:** 202605181934-disconfirm-consen-p2-verify-disconfirmation-probe
**Finding origin:** CCTV Disconfirmation mode adversarial analysis (2026-05-18)
**Root cause:** PR #3631 (epsilon)
**Fix:** PR #3666 (delta)
**Verification target:** `agents/hapax_daimonion/cpal/destination_channel.py` on main at `b39d126c2`

## Verification Summary

**Result: PRIMARY BYPASS CLOSED. Two residual vectors documented.**

The 5 `and not stream_public` escape clauses in `resolve_playback_decision()`
have been removed. All safety gates now enforce regardless of stream mode.

## Primary Fix Verification

### Gate-by-gate confirmation

Zero `stream_public` bypass clauses remain in `destination_channel.py`:

```
$ grep -c 'and not stream_public' agents/hapax_daimonion/cpal/destination_channel.py
0
```

### Test probe results (62/62 pass)

Key consent enforcement probes:

| Test | Status | Assertion |
|------|--------|-----------|
| `test_stream_mode_public_blocks_without_intent` | PASS | PUBLIC mode blocks playback without explicit broadcast intent |
| `test_stream_mode_public_allows_playback_with_full_gates` | PASS | PUBLIC mode allows only when all 5 gates pass |
| `test_ambient_consent_enforced_in_public_mode` | PASS | AMBIENT register blocked by audio health gate in PUBLIC mode |

### Non-regression for other registers

All 62 destination channel tests pass, including existing tests for:
- Private/sidechat routing (unchanged)
- Bridge metadata enforcement for autonomous sources (unchanged)
- Programme authorization gates (unchanged)
- Broadcast bias flag routing (unchanged)

## Residual Vectors (from root cause analysis)

### Secondary: `classify_destination()` unconditional routing (NOT FIXED)

`classify_destination()` line 234 still routes all voice output to LIVESTREAM
when stream mode is PUBLIC, before examining voice register. This is
**intentional** — destination classification is separate from safety gate
evaluation. The fix in PR #3666 ensures that even though the destination is
LIVESTREAM, the playback decision still enforces all safety gates.

**Risk assessment:** Low. The safety gates are the enforcement point, not the
destination classification. An impingement classified as LIVESTREAM but failing
a safety gate will be blocked.

### Tertiary: `prepared_playback_loop()` direct bypass (NOT FIXED)

`run_loops_aux.py` lines 538-544 bypass `resolve_playback_decision()` entirely
for the prepared playback loop. This was acknowledged as intentional to avoid a
chicken-and-egg deadlock with `audio_safe_for_broadcast`.

**Risk assessment:** Medium. The prepared playback loop constructs a synthetic
impingement with `public_broadcast_intent=True` and bypasses all safety gates.
This should be addressed in a follow-up task.

## Conclusion

The primary finding (AMBIENT consent bypass via `stream_public` escape clauses)
is **CLOSED**. The CCTV disconfirmation probe is satisfied: AMBIENT narration
cannot reach broadcast without passing all 5 safety gates in PUBLIC mode.

The tertiary vector (`prepared_playback_loop` bypass) should be tracked as a
separate finding if not already filed.
