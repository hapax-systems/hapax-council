# preset.bias heartbeat fallback

## Why

Per `/tmp/effect-cam-orchestration-audit-2026-05-02.md` (effect+cam
orchestration audit, 2026-05-02), the live livestream is exercising
**0/24 family-mapped presets** and **0/5 transition primitives** in a
representative 15-min observation window. The chain-mutation file
`/dev/shm/hapax-compositor/graph-mutation.json` does not exist — the
compositor has not changed effect chains since boot.

Root cause (audit §4 F1):

1. The director loop emits `compositional_impingement` events with
   `intent_family="preset.bias"` every ~70-110s.
2. **100%** of those impingements are flagged `UNGROUNDED` by the
   `_ensure_impingement_grounded` defense — per-impingement
   `grounding_provenance=[]`.
3. The downstream affordance pipeline's narrative→capability similarity
   search either rejects or skips these impingements; no
   `fx.family.<family>` capability gets recruited.
4. Therefore `preset.bias` never appears under
   `recent-recruitment.json["families"]`.
5. `preset_recruitment_consumer.process_preset_recruitment()` reads
   that file, finds no `preset.bias`, returns `False` every tick, never
   calls `pick_and_load_mutated`, never writes
   `graph-mutation.json` — the chain stays static.

The audit's quick-win recommendation (R2 / QW2) is a deterministic
heartbeat that writes a uniform-sampled `preset.bias` family entry to
`recent-recruitment.json` whenever the LLM-driven entry has gone stale.
This unblocks the consumer + transitions + chain mutations end-to-end.

## What this is NOT

This is a **strict fallback**, not a replacement for LLM-driven
recruitment. The heartbeat:

- Defers to any LLM-driven `preset.bias` entry younger than 60s
- Only writes when the LLM entry is missing or older than 60s
- Stamps every entry it writes with `source: "heartbeat-fallback"` so
  observability can distinguish heartbeat from LLM origin

When the upstream LLM compliance issue (audit §4 F4) is fixed and
LLM-driven recruitment becomes consistent, this agent becomes
redundant and should be disabled.

## Mechanism

Single agent: `agents.preset_bias_heartbeat`. systemd unit:
`hapax-preset-bias-heartbeat.service`.

```
every 30s:
  payload = read(/dev/shm/hapax-compositor/recent-recruitment.json)
  if payload.families["preset.bias"].last_recruited_ts is fresh (<60s):
    no-op  # LLM is alive, do not interfere
  else:
    family = uniform_sample(preset_family_selector.family_names())
    write_atomic(payload | {
      "families": payload.families | {
        "preset.bias": {
          "family": family,
          "last_recruited_ts": now,
          "ttl_s": 8.0,
          "source": "heartbeat-fallback",
        }
      },
      "updated_at": now,
    })
    log "preset.bias heartbeat fallback fired: family=X (LLM stale Ys)"
```

The family list is **always** sourced from
`preset_family_selector.family_names()` — which reads
`FAMILY_PRESETS` directly. No hardcoded family list lives in the
heartbeat module (test pin: `test_no_hardcoded_family_list_in_module`).
Operator edits to `FAMILY_PRESETS` propagate on the next tick without a
restart.

## Observability

Every entry the heartbeat writes carries `source: "heartbeat-fallback"`.
This is the load-bearing observability hook — anyone analysing the
recruitment file or querying journal logs can compute the heartbeat-vs-
LLM ratio and decide:

- **High heartbeat ratio (>50%)** — LLM compliance is broken (audit
  §4 F4 still in effect); the heartbeat is doing the work the LLM
  should be doing. Investigate the per-impingement grounding fix
  (R8 in the audit).
- **Low heartbeat ratio (<10%)** — LLM is doing its job; the heartbeat
  is a true backstop catching only rare gaps. Status quo is healthy.
- **Zero heartbeat firings for >24h** — LLM is consistent. Consider
  disabling the unit.

The agent logs every fire to journal with the chosen family + age of
the prior entry (or "no prior LLM recruitment on record" when the file
was missing entirely).

## Install + verification

```bash
# Symlink + reload
ln -sf ~/projects/hapax-council/systemd/units/hapax-preset-bias-heartbeat.service \
       ~/.config/systemd/user/hapax-preset-bias-heartbeat.service
systemctl --user daemon-reload
systemctl --user enable --now hapax-preset-bias-heartbeat

# Watch the heartbeat fire (expect a fallback fire within 60s if LLM
# recruitment is still broken; nothing if LLM is fixed)
journalctl --user -u hapax-preset-bias-heartbeat -f

# Confirm chain mutation file now exists (it didn't before)
cat /dev/shm/hapax-compositor/graph-mutation.json

# Confirm preset.bias entry now lands in recent-recruitment.json
jq '.families["preset.bias"]' /dev/shm/hapax-compositor/recent-recruitment.json
# Expected fields: family, last_recruited_ts, ttl_s, source
# When source = "heartbeat-fallback" → this agent fired
# When source is absent → LLM-driven recruitment fired (legacy path)
```

## When to disable

Disable when **both** of the following hold for a 24h+ window:

1. `preset.bias` entries with `source != "heartbeat-fallback"` are
   landing at >1/min (LLM compliance is restored).
2. The grounding fix from audit R8 / cc-task
   `per-impingement-grounding-enforcement` has shipped.

```bash
systemctl --user disable --now hapax-preset-bias-heartbeat
```

## Cross-references

- Audit: `/tmp/effect-cam-orchestration-audit-2026-05-02.md`
- Spec consumer this unblocks:
  `agents/studio_compositor/preset_recruitment_consumer.py`
- Family inventory:
  `agents/studio_compositor/preset_family_selector.py`
- Transition primitives:
  `agents/studio_compositor/transition_primitives.py`
- Atomic write contract: `agents/studio_compositor/atomic_io.py`
