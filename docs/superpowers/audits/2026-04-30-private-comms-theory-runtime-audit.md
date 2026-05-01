# Private Communications Theory/Runtime Audit

Date: 2026-04-30
Lane: `cx-rose`
Task: `private-comms-theory-runtime-audit`

## Scope

This audit checks whether private operator communication can reach public
surfaces without the explicit public-route contract required by the unified
self-grounding spine. The target boundary is: private ingress and private
reasoning may propose a public act, but public speech requires explicit
broadcast intent, fresh programme authorization, safe broadcast audio, a
witnessed public route, and public-claim grounding.

## Runtime Map

| Surface | Runtime path | Current posture |
| --- | --- | --- |
| Blue Yeti/private voice ingress | `agents/hapax_daimonion/conversation_pipeline.py` to private conversation handling | Private by default after STT acceptance gates; not a broadcast route by itself. |
| Operator sidechat ingress | `shared/operator_sidechat.py`, consumed by `agents/hapax_daimonion/run_loops_aux.py` | Local `/dev/shm` queue, routed as `operator.sidechat` and private by default. |
| Autonomous narration | `agents/hapax_daimonion/autonomous_narrative/emit.py` | Emits private unless a separate bridge/public contract is supplied. |
| Private/public bridge | `shared/private_to_public_bridge.py` | Only public proposal path; now emits structured programme authorization metadata for the playback gate. |
| Voice destination gate | `agents/hapax_daimonion/cpal/destination_channel.py` | Broadcast playback requires explicit intent, structured fresh programme authorization, audio-safe state, and broadcast media role. |
| Semantic voice router | `shared/voice_output_router.py` | Rejects raw high-level targets and has no default public fallback. |
| Captions | `agents/live_captions/routing.py`, `agents/live_captions/daimonion_bridge.py` | Production config is allowlisted, but caption events still need the future public speech witness index for complete auditability. |
| YouTube shared link staging | `agents/studio_compositor/yt_shared_links.py` via sidechat `link` command | Explicit command stages only the URL for sync; not general private text egress. |
| Text overlay commands | `agents/studio_compositor/text_repo_commands.py` via sidechat `add-text`/`rotate-text` | Explicit operator command can stage public overlay text; should be governed by the downstream bridge governor task before broader private-to-public automation. |

## Findings

1. Fixed: the bridge formatted `programme_authorization` as a string while the
   CPAL playback gate required a structured object with a fresh timestamp.
   That made authorized bridge proposals fail closed at playback. The bridge
   result still carries the reference string, and the emitted impingement
   content now carries the destination-compatible authorization object.

2. Fixed: the self-grounding envelope now retains programme authorization
   timing and blocks public speech when a fresh authorization state lacks an
   ID or timestamp. This keeps handoff metadata aligned with the playback
   freshness gate.

3. Downstream: autonomous narration remains private by default. Wiring it to
   public speech should stay blocked behind the existing route-claim envelope
   and private-to-public bridge governor tasks.

4. Downstream: sidechat command subpaths (`link`, `add-text`, `point-at-hardm`)
   are explicit operator commands that can stage public-surface candidates.
   They are not evidence of general private-chat leakage, but they should be
   folded into the bridge/governor witness model before expanding automation.

5. Downstream: captions are governed by allowlisted routing, but no durable
   public speech event witness index yet records every accepted, blocked, or
   private-only speech decision. The public witness index remains the right
   owner for that audit trail.

## Verification

Focused verification for this audit should cover:

- `tests/shared/test_self_grounding_envelope.py`
- `tests/shared/test_private_to_public_bridge.py`
- `tests/hapax_daimonion/test_destination_channel.py`
- Existing sidechat and caption routing tests when changing those surfaces.
