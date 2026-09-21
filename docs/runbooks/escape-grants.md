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
