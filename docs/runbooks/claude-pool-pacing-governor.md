# Claude pool pacing governor

`scripts/hapax-claude-pool-pace` smooths the Claude 7-day pool to a linear line
(`2 % + 0.6 %/h` from the open window's start, capped at 100 %). It reads the windows the
account-live probe already mints — no second probe, no provider call — and holds new Claude lane
launches while the pool is over that line.

## Commands

| command | what it does |
|---|---|
| `record` | appends one pacing reading to the `claude-pool` sink (exit 4 if it cannot ledger) |
| `check` | the rule: 0 allow, 3 over pace, 4 no / stale / unledgered reading |
| `status` | the same evaluation as machine JSON |
| `activate` | writes the activation marker create-once (the seat's act; arming) |
| `deactivate` | archives the marker create-once with `--reason` and `--by`, then retires it |
| `release-plan` | read-only ordered list of held work; releasing is the seat's act |

## Cadence

The probe mints a reading every ten minutes (`PROBE_CADENCE`); `record` runs on its own slower
timer. Two consequences, both fixed in the same change:

- a reading is admissible when its OWN ledger row exists, with one cadence of tolerance on capture
  lag, so the slower tick no longer refuses a reading the governor has just measured (the measured
  10:04Z-refuse / 10:06Z-allow lag);
- the **probe ledgers its own reading** through `hapax-claude-pool-pace`'s payload builder, so no
  lane waits on the pace tick at all.

The check binds to the reading's IDENTITY: the ledger row must name this very reading, so an earlier probe's row
cannot admit a later probe's mint. The cadence is only the tolerance on capture lag. A row naming a different reading,
a row past that tolerance, or no row at all still refuses; a failed ledger append admits nothing, and the
probe exits nonzero without minting.

The governor also READS its own ledger (`ledger_readings`), so a reading the probe ledgered is a reading `check`
evaluates. Without that, a held governor could not see the pool recover: while the gate holds the probe's admission
mint there is no new receipt, and receipts plus headless traces were the only sources.

Recheck the claims above:

```bash
uv run --no-project --with pytest==9.0.2 --with pyyaml --with pydantic --with prometheus-client --with httpx \
  pytest tests/scripts/test_hapax_claude_pool_pace.py tests/scripts/test_hapax_claude_account_live_observe.py
scripts/hapax-claude-pool-pace deactivate --reason "<why>" --by seat   # archive is create-once, marker retired
scripts/hapax-claude-pool-pace status --json                          # armed + decision consistent with the line
```

## Disarming, and the interim drop-in

Disarming is the marker's removal, which the armed gate refuses through a shell `mv`. Use the
governed verb:

```bash
scripts/hapax-claude-pool-pace deactivate --reason "<why>" --by seat
```

It writes `<marker>.deactivated-<UTC>` carrying the marker's fields plus `deactivated_at`, `by` and
`reason`, then unlinks the live marker; create-once per instant, so an existing archive is never
overwritten. The seat's hand-made archive from 2026-09-26T15:05Z has the same shape.

The interim runtime drop-in `~/.config/systemd/user/hapax-claude-account-live-observe.service.d/pace-follow.conf`
(seat, 2026-09-26T10:1xZ) existed to run `record` after each successful probe. The probe now ledgers
its own reading, so the drop-in is redundant: retire it with

```bash
rm ~/.config/systemd/user/hapax-claude-account-live-observe.service.d/pace-follow.conf
systemctl --user daemon-reload
```

Merge is inert for the unit (it ships parked); the seat activates, and the seat may re-arm after any
deactivation with `activate --reason <why> --by seat`.
