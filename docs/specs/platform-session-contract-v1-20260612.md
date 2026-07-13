# Platform Session Contract v1

Authority: `CASE-TRAINYARD-EXEMPLARY-20260612`, parent spec
`~/Documents/Personal/30-areas/hapax/trainyard-exemplary-design-2026-06-12.md` section 9.

## Scope

The trainyard speaks this contract only. Claude, Codex, and later Gemini/Vibe/Antigrav
differences stay below adapter boundaries. A platform is supported when its adapter passes
the conformance fixtures for spawn/announce, event vocabulary, and control roundtrip.

Non-scope: changing launcher behavior or making the yard parse platform-native streams.

## Lifecycle

Lifecycle states are closed:
`spawn`, `announce`, `identify`, `claim`, `work`, `yield`, `park`, `resume`, `close`.

Lifecycle is emitted as contract `status` events whose payload contains
`lifecycle_state`. `announce` means the birth artifacts exist: session identity, claim
surface, lane-state/ledger event when available, and a visible coordination-plane train.

## Event Stream

The adapter output stream is newline-delimited JSON:

```json
{"ts":"2026-06-12T06:00:00Z","session_id":"cx-red","kind":"status","payload":{"lifecycle_state":"announce"}}
```

The closed `kind` enum is:
`tool_call`, `file_write`, `claim`, `push`, `dossier_write`, `task_mention`, `status`,
`error`, `heartbeat`.

The yard must not consume Claude stream-json, Codex JSONL, tmux transcripts, or launcher
logs directly. Adapter output is the boundary.

## Control Channel

The common control message is `{ts, session_id, verb, payload}`. Closed verbs:
`context_inject`, `interrupt`, `ack`, `take_controls`, `release_controls`.

Adapters render the envelope natively:

| Adapter | Native transport | Shim |
|---|---|---|
| `adapter-claude` | FIFO carrying Claude stdin-json | Wrap the control envelope as a Claude stream-json user message. |
| `adapter-codex` | Codex tmux-buffer text for interactive sessions; `codex exec` prompt or file-bus inbox fallback for headless sessions | Prefix a marked JSON envelope so `hapax-codex-send` or the fallback inbox can carry it verbatim. |

## MCP Surface

The trainyard MCP surface is platform-neutral and remains above this adapter layer:
`map.focus`, `card.open`, `card.pin`, `dossier.show`, `intent.mint`, `focus.read`,
`yard.query`.

MCP calls are reflected into this event stream as `tool_call` events with the tool name and
adapter-normalized argument metadata in payload.

## Adapter Shims

`adapter-claude` covers the current `hapax-claude-headless` artifact shape:
`~/.cache/hapax/claude-headless/<role>/output.jsonl`, `/run/user/<uid>/hapax-claude/<role>.stdin`,
`cc-active-task-<role>`, `cc-claim-epoch-<role>`, Claude stream-json input and output.

`adapter-codex` covers Codex interactive and headless shapes:
`tmux:hapax-codex-<cx-session>`, `~/.cache/hapax/codex-headless/<cx-session>/output.jsonl`,
`cc-active-task-<cx-session>`, `cc-claim-epoch-<cx-session>`, Codex `--json` output when
headless, and session projection events when interactive.

Claim-cache writers must write the matching epoch sidecar before exposing a
`cc-active-task-*` cache. The sidecar format is `<epoch> <task_id>` and is
task-bound: terminal checks ignore a sidecar whose task id does not match the
claim cache. Session-keyed claim files use matching session-keyed sidecars, for
example `cc-active-task-<role>-<session_id>` plus
`cc-claim-epoch-<role>-<session_id>`.

Known Codex divergences are mapped to shims:

| Divergence | Native difference | Contract shim |
|---|---|---|
| control transport | FIFO carrying Claude stdin-json vs Codex tmux-buffer text / exec prompt | `ControlMessage` renders to each native input surface and parses back losslessly. |
| role resolution | Claude role is the lane; Codex has `cx-*` session plus Greek slot | `SessionIdentity` keeps `session_name`, `session_id`, `slot`, and `claim_key` distinct. |
| dispatch flags | Claude stream-json flags differ from Codex `exec --json --cd` flags | Flags are declared on the adapter contract; the yard never branches on them. |
| output formats | Claude stream-json differs from Codex JSONL/session projection events | Normalizers emit only the closed event kind enum. |
| relay-exclusion visibility | Historical Codex interactive sessions could be invisible to relay/map consumers | The conformance fixture requires announce + identify + claim projection identical to Claude. |

## Conformance Fixtures

The reusable Python suite lives in `shared.platform_session_contract` and is pinned by:

- `tests/shared/test_platform_session_contract.py`
- `tests/fixtures/platform_session_contract/claude-headless-output.jsonl`
- `tests/fixtures/platform_session_contract/codex-interactive-output.jsonl`

The Claude fixture remains the native stream-json shape emitted below
`~/.cache/hapax/claude-headless/<role>/output.jsonl`; `artifact_projection_rows(...)`
projects launcher birth and claim-file evidence from the adapter artifact contract before
the conformance gate runs. Launcher-layout tests pin the artifact paths, claim-file
surfaces, and transports for both Claude and Codex.
`artifact_projection_rows(...)` refuses unobserved evidence: an output stream, control
endpoint, and claim file must exist before emitting spawn/announce/claim evidence. For
`tmux:` endpoints, the runner must first verify the tmux session and pass that observed
endpoint into the projection helper.

The suite checks:

1. `spawn/announce/identify/claim` projection exists in adapter-supplied artifact or stream rows.
2. Every adapter event validates against the closed event kind enum.
3. Control messages roundtrip through the adapter native transport.
4. A Codex interactive fixture appears on the coordination plane with the same claim and
   file-write facts as the Claude fixture.
5. Task mentions remain separate from claim facts; a mention alone is not a claim.

## Honest Rejection

Off-vocabulary adapter output is refused with code `off_vocabulary_event`. It is not
silently dropped or coerced to `status`. Unknown native events below the adapter may become
contract `error` events with `code=native_event_unmapped`, but once an adapter emits a
contract-shaped event, `kind` must be one of the closed enum values.
