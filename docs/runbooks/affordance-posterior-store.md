# Affordance Posterior Store

The canonical recruitment-learning posterior remains:

```text
~/.cache/hapax/affordance-activation-state.json
```

Reverie is the owner/writer. Reader daemons queue updates through:

```text
~/.cache/hapax/affordance-activation-state-updates.jsonl
```

Both files use persistent `.lock` sidecars for advisory `flock` coordination.
The lock files are expected to remain on disk. `flock` ownership is tied to the
open file descriptor and is released by the OS when a process exits, so do not
delete lock files as the first response to contention.

Reader appends hold only the update-journal lock. Owner drains lock the journal
first, then the posterior file, and truncate the journal only after the updated
posterior has been written. This keeps queued updates durable if the owner cannot
complete the state write.

## Knobs

- `HAPAX_AFFORDANCE_POSTERIOR_UPDATE_LOCK_TIMEOUT_S`: reader-update lock wait in seconds. Default `0.0` means readers fail fast and count/drop the update on contention.
- `HAPAX_AFFORDANCE_POSTERIOR_OWNER_DRAIN_LOCK_TIMEOUT_S`: owner-drain wait for the update journal. Default `1.0` gives Reverie a bounded wait for brief reader appends.
- `HAPAX_AFFORDANCE_POSTERIOR_UPDATE_LOG_MAX_BYTES`: journal cap before reader appends are rejected. Default `5242880`.

## Rechecks

```bash
ls -lh ~/.cache/hapax/affordance-activation-state*.json*
uv run pytest tests/test_affordance_posterior_single_writer.py -q
```

If the update journal exceeds the cap, confirm Reverie is running and draining:

```bash
systemctl --user status hapax-reverie.service
```
