# Escape grants

An escape grant is a signed, scoped, time-boxed file the irreversible-harm gates read directly.
It converts a refusal into an allow and writes a ledger line each time it is honoured. Mint one
with `scripts/coord-grant-mint`.

## Scope is exact, and the gates run in a chain

`--scope <gate>` covers exactly one gate. The production PreToolUse chain runs `cc-task-gate`
**before** `authorization-packet-validator`, so on a real push with no claim:

- a grant scoped to `authorization-packet-validator` alone never reaches that gate — the write
  gate refuses first;
- a grant scoped to `cc-task-gate` alone lifts the write gate and then the validator refuses.

**For a no-claim push or release, mint scope `*`:**

```
scripts/coord-grant-mint --scope '*' --grantor hapax --ttl 21600 --reason "<why>"
```

Both gates honour it, each ledgers its own `escape_grant_honored` line, and the grant expires on
its own. `tests/test_authorization_packet_validator.py::TestEscapeGrant` pins both halves of the
chain.

## The grant binds to the minting session

A grant releases only the session it was minted for
(`escape-grants-bind-to-the-minting-session-20261011`). Pass `--session` on mint and on verify.
An unbound (legacy-shaped) grant verifies for nobody, and a grant minted for a different session
is refused the same way — the verify CLI exits nonzero and prints
`NEXT_ACTION: re-mint with your session`, so the repair is a fresh mint bound to *your* session,
never a widening.

```
scripts/coord-grant-mint --scope '*' --grantor hapax --ttl 21600 \
    --session "<session-id>" --reason "<why>"
uv run python -m shared.governance.coord_capabilities verify-grant \
    --file <grant-path> --gate cc-task-gate --key-file <key> --session "<session-id>"
```

`--session` omitted on mint resolves through the session env chain the gates mirror from
`hooks/scripts/agent-role.sh` `hapax_session_id()` — first set wins among `HAPAX_SESSION_ID`,
`CLAUDE_CODE_SESSION_ID`, `CODEX_SESSION`, `CODEX_THREAD_ID`, `CODEX_THREAD_NAME`. With none set
the mint **refuses** rather than writing an unbound grant. The INV-3/4/5 auto-mint binds through
the same chain and falls back to the deterministic `sdlc-evaluator` identity, so the
never-freeze response always produces a grant some session can verify.
