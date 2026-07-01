# YouTube Lane Bounded-Outbound Pattern

Status: implementation template only. This document does not authorize or wire a live YouTube API mutation.

## Contract

The YouTube public-egress lane uses the bounded outbound executor through `shared.outbound_lane_pattern`. A valid act must satisfy all of these gates before any provider adapter can be wired later:

- Scoped token: the account federation registry must point at `pass:google/token-youtube-streaming`, and the lane token must cover `youtube_video_insert`.
- Rate limit: the lane must bind a fixed-window `OutboundRateLimit`; a second act within an exhausted window produces a refusal receipt. The template limiter is intentionally in-memory and is not sufficient live-provider quota enforcement across process restart or lane reconstruction. A future live adapter must inject durable/shared limiter evidence or fail closed before provider execution authority is considered.
- Per-act receipt: every admitted or refused act returns an `OutboundLaneActReceipt`.
- Kill switch: the lane constructor requires an explicit kill-switch boolean and passes it to `OutboundExecutor`.
- Public gate: the template uses `AuthorityCeiling.PUBLIC_GATE_REQUIRED`, so public egress needs a bound `public-gate:` receipt.
- Money separation: the template sets `money_movement_authorized=False` and refuses any positive amount or money-movement request before the outbound executor is reached.

Recheck:

```bash
uv run pytest tests/shared/test_outbound_lane_pattern.py -q
git diff --name-only origin/main...HEAD | sort
python3 - <<'PY'
import re
import subprocess

for path in subprocess.check_output(
    ["git", "diff", "--name-only", "origin/main...HEAD"],
    text=True,
).splitlines():
    if re.match(
        r"^(agents/auto_clip/platform_dispatch\.py|shared/google_auth\.py|scripts/youtube-auth\.py|.*\.service$)",
        path,
    ):
        raise SystemExit(f"live provider wiring path changed: {path}")
PY
uv run ruff check shared/outbound_lane_pattern.py tests/shared/test_outbound_lane_pattern.py
uv run ruff format --check shared/outbound_lane_pattern.py tests/shared/test_outbound_lane_pattern.py
uv run pre-commit run --files shared/outbound_lane_pattern.py tests/shared/test_outbound_lane_pattern.py docs/monetization/youtube-lane-bounded-outbound-pattern.md
```

## Non-Authority

This pattern deliberately does not patch `agents/auto_clip/platform_dispatch.py`, `shared/google_auth.py`, systemd units, credentials, or any live YouTube service. It provides the shape a future provider adapter must satisfy before live execution authority is considered.

## Template Constants

- Scope: `youtube_video_insert`
- Venue: `youtube:public-upload-template`
- Token reference: `pass:google/token-youtube-streaming`
- Provider execution flag in receipts: `provider_execution_wired: false`

## Required Future Adapter Evidence

A later source task that wires a real YouTube adapter must add fresh acceptance evidence for the provider boundary:

- Proof that the scoped token is not a default Google token.
- Proof that public egress receipts bind the exact artifact being uploaded.
- Proof that rate-limit receipts survive process restart or are backed by a durable limiter.
- Proof that money rails cannot be reached from the public-egress lane.
