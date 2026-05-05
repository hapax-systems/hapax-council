# Audio yaml ↔ conf consistency gate

cc-task: `audio-audit-F-precommit-yaml-conf-gate` (Auditor F).

Regression pin for finding #11 (audio-yaml-conf drift surfaced as
silent live-graph breakage) and the broader class of
"configured-a-chain-forgot-the-conf" mismatches.

## What it checks

`scripts/check-audio-conf-consistency.py` walks two surfaces:

1. **`config/audio-topology.yaml`** — every `filter_chain` node with
   `chain_kind ∈ {loudnorm, duck, usb-bias}` should have a matching
   `config/pipewire/hapax-<chain-id>.conf` on disk. Stream-routing
   chains (`chain_kind=None`) carry their config inline in the yaml's
   `params:` block and don't need a conf.

2. **`config/pipewire/*.conf`** — every conf on disk should either
   match a yaml-declared chain or be present in the orphan allowlist.

Drift in either direction fails the gate.

## Allowlist

`config/audio-conf-allowlist.yaml` documents two acceptable drift
classes:

* **`orphans`** — confs on disk with no yaml backing. Legitimate
  cases include global PipeWire knobs (`hapax-quantum.conf`), legacy
  rollback confs (`hapax-l6-evilpet-capture.conf`), and voice-fx
  variants the yaml doesn't model yet
  (`hapax-voice-fx-loudnorm.conf`).

* **`known_missing`** — confs the yaml declares but disk lacks. These
  represent open audit follow-on tasks; the gate accepts them so it
  ships clean, but the underlying findings remain unresolved.

Each entry SHOULD carry a trailing comment explaining why the
allowlist entry is acceptable (or which task tracks fixing it).

## Wiring

* **Pre-commit** — `.pre-commit-config.yaml` runs the gate when any
  audio-related yaml or conf changes (`config/audio-topology.yaml`,
  `config/audio-conf-allowlist.yaml`,
  `config/pipewire/*.conf`).

* **CI** — `.github/workflows/ci.yml` runs the gate as part of the
  `lint` job so every PR that drifts the yaml ↔ conf mapping fails
  before merge.

## Test

`tests/scripts/test_check_audio_conf_consistency.py` covers:

* `expected_confs_from_yaml` — only typed `chain_kind` chains count;
  non-`filter_chain` nodes skipped.
* `confs_on_disk` — only `*.conf`; missing dir → empty.
* `load_allowlist` — both `orphans` and `known_missing` sections;
  missing file → empty pair.
* `check` — clean state passes; missing conf fires; orphan fires
  unless allowlisted; `known_missing` short-circuits the missing
  flag.
* **Live regression pin** — the shipped state of the repo passes
  the gate. A future commit that introduces drift without updating
  the allowlist trips this test.
* CLI rc=0 happy path; rc=1 on drift; useful error message in stderr.
