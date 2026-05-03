# Add audio source — runbook

cc-task: `audio-audit-F-source-spec-emitter`.

One-command "add a new audio source" workflow. The
`agents.audio_codegen.spec_emitter` CLI generates three artifacts
(conf + service + yaml fragment) into a workspace-local staging dir;
the operator reviews, then merges / installs.

## Quick path

```
uv run python -m agents.audio_codegen.spec_emitter \
    --source-id new-mic-loudnorm \
    --chain-kind loudnorm \
    --description "New mic loudnorm chain"
```

Defaults:
* `--staging-dir` → `~/.cache/hapax/audio-codegen-staging/`
* `--pipewire-name` → `hapax-<source-id>` (matches the conf-naming
  convention enforced by the F-precommit gate)
* `--limit-db` / `--release-s` / `--input-gain-db` → align with
  `shared/audio_loudness.py` defaults

The CLI:

1. Emits `<source-id>.conf`, `<source-id>.service`, `<source-id>.yaml`
   into the staging dir.
2. Validates that the yaml fragment merges into the live
   `config/audio-topology.yaml` cleanly (parses + re-validates the
   merged document via `TopologyDescriptor.from_yaml`). Pass
   `--skip-validate` to suppress this for fast smoke runs.

The emitter never touches the live tree. Operator-confirm-before-
install is the contract.

## chain_kind selection

| chain_kind | Use for | Notes |
|---|---|---|
| `loudnorm` | sources that need EBU-R128 loudness normalization | bakes in `fast_lookahead_limiter_1913` |
| `duck` | sources that need sidechain-driven gain control | paired-mono builtin mixer |
| `usb-bias` | sources that need pre-routing input gain (USB-IN line driver pattern) | LADSPA-clamped `Input gain (dB)` |
| `none` | stream-routing chains (no LADSPA stage) | just routes audio between sinks |

When in doubt, start with `loudnorm` and adjust the conf parameters
manually before install.

## Install (after operator review)

```
# 1) Move the conf into the live PipeWire dir.
cp ~/.cache/hapax/audio-codegen-staging/<source-id>.conf \
   ~/projects/hapax-council/config/pipewire/

# 2) Merge the yaml fragment into config/audio-topology.yaml.
#    The fragment is shaped to insert directly under the `nodes:` array:
#
#        nodes:
#          - id: l12-capture
#            ...
#          - id: <source-id>          # ← pasted from the fragment
#            kind: filter_chain
#            ...

# 3) Verify the F-precommit gate passes.
uv run python ~/projects/hapax-council/scripts/check-audio-conf-consistency.py

# 4) Verify the source matrix shows the new source.
uv run python -m agents.audio_codegen.caps | grep <source-id>

# 5) Install the systemd unit (operator-side, requires sudo if
#    moving to /etc/systemd/system/, or just symlink into
#    ~/.config/systemd/user/ for user-scope).
```

## Discard (after operator review rejects)

```
rm -rf ~/.cache/hapax/audio-codegen-staging/<source-id>*
```

The staging dir is ephemeral — nothing in the live tree is touched.

## Verifying the install

After installing, the F-precommit gate (`audio-conf-consistency`)
should pass with the new source counted in the "yaml chains" total
rather than appearing in the orphans / known_missing lists. The
source-capability matrix CLI (`audio-audit-F-source-capability-matrix-cli`)
should display the new source with its `chain_kind` populated.
