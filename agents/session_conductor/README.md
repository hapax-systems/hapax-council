# Conductor process and projection ownership

A sidecar follows an observed native process, while turn events only summarize
work. A process identity is a PID plus its kernel start ticks. Missing,
unreadable, replaced, or zombie owners end the sidecar; observation failure
never selects a different parent. The role lock covers the daemon's entire
lifetime, including final writes and PID/socket cleanup. Concurrent start
attempts leave the incumbent untouched.

For Codex, `conductor-start.sh` observes the nearest `codex` executable in its
procfs ancestry before launching through systemd/uv. This supports intervening
hook shells without mistaking them or the daemon's systemd/uv wrapper for the
lane. No observed native ancestor means no launch. Renamed executables are an
explicit unsupported boundary. The launcher owns `HAPAX_SESSION_ID`; the hook
passes it as the lane identity and retains the hook's native session ID
separately. Direct CLI starts without a session ID label the generated ID as
the conductor's. Codex CLI starts must supply the observed owner pair.

PR #5133 owns clean launcher environment and explicit session UUID delivery.
This repair consumes that delivery and observes ancestry; it does not alter
either launcher or add an inherited owner-PID variable. The identity values
and their provenance remain distinct from liveness evidence.
Kimi delegates to the same adapter; non-Codex callers retain their existing
Stop dispatch. The source gate manifest declares Codex's turn-only chain.

Conductor projections are `relay/conductor/<role>.yaml`, written atomically
by the daemon holding that role lock. They carry `producer`, `session_id_kind`,
native/lane identity, conductor and owner PIDs, owner start ticks, and UTC
timestamps. `event_type: shutdown` describes the conductor. It is not a
lane's session-status declaration. Root lane files are never adopted,
overwritten, retired, or migrated by the conductor.

The source inventory for the namespace choice is:

| Consumer or owner | Root lane files | Conductor projection |
| --- | --- | --- |
| Lane/seat writers; `hapax-codex` launcher contract | `<session>.yaml`; historical seat handoffs also use `<role>-status.yaml` | Never written here |
| `RelayRule.check_peer_conflicts` | Reads root YAML `in_flight_files`, excluding its own role | Reads `conductor/*.yaml`; ignores shutdown projections |
| `hapax-relay-retire`, `shared/relay_lifecycle.py` | Exact `<role>.yaml` and `<role>-status.yaml` retirement paths | Excluded by directory |
| `cc-hygiene-sweeper.py` | Exact known-role paths and nonrecursive `cx-*.yaml`; canonical payload session check | Excluded by directory |
| `team-metadata-probe` | Exact `<lane>-status.yaml` / `.json` | Excluded by directory |
| `hapax-codex-health` | Exact `<session>.yaml` | Excluded by directory |
| `shared/relay_mq.py` | Nonrecursive `*.yaml` broadcast recipient discovery | Excluded by directory; no phantom conductor recipient |
| `cc-task-pr-link.sh`, `relay-coordination-check.sh` | Existing root lane records and path claims | No new writer |

This is a source-only repair. Tests use temporary homes, procfs fixtures,
stubbed systemd launches, and a real fixture daemon with temporary socket,
PID, state, and relay paths. They do not constitute a live lane witness.
Installed activation, the parent runtime witness, and the create-once
predecessor freeze remain separate prerequisites. Existing root relay bytes
are preserved; their historical ambiguity is not silently repaired here.
