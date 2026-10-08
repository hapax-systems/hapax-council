# Source carrier rendering

`EnvelopeDeclaration` remains the scrub envelope's single record. Admission must now
supply `unit=UnitSection(memory_high=..., memory_max=..., memory_swap_max=...,
runtime_max_sec=...)`, with integer bytes and seconds. No host-derived limits or
unbounded default is supplied. OOM policy is `kill`; restart is `no`.

`render(declaration, run_root=fresh_path, carrier="t1" | "t2" | "t3")` constructs:

- T1: `systemd-run --user --wait --pipe --collect` with the unit properties around
  the existing bubblewrap command. `KillMode=control-group` also bounds timeout cleanup.
- T2: the scrub carrier, now with a private network namespace and read-only generated
  home and directory masks. `unit_properties` accompanies it; bare T2 does not enforce
  cgroup ceilings. The existing `execute` function still only accepts T2.
- T3: an OCI 1.2.1 `config.json` and fresh `rootfs`, using the same allowlisted runtime
  files and masked checkout. Specify target-node `oci_uid`, `oci_gid` (subordinate IDs),
  and `oci_launcher_uid`, `oci_launcher_gid` explicitly. The job runs as in-container
  UID/GID 1, without capabilities. ID-range admission and mount ownership belong to
  node enrolment. The required outer unit is returned as `unit_properties`; there is
  no competing OCI cgroup, runtime invocation or image builder here.

Existing typed imports, credentials, binaries, workdir and spool are still fields of
that record. `channels` adds `DeclaredChannel(name=..., kind="mount", source=...)`
for read-only projections at `/channels/<name>`, or `kind="unix"` for a named Unix
socket endpoint at that location. No host resolver socket is mounted implicitly.
Network endpoint declarations refuse until the separate egress gate supplies an
enforceable binding. No annotation is treated as a network filter.

`check_conformance(declaration, rendered)` independently expands the declaration,
including the fixed Linux scaffold, and reads the emitted carrier's mounts, access
modes, namespace and endpoint bindings. It compares normalized JSON **bytes**;
`channel_bytes` and its hash are derived evidence, never a second input declaration.
Every required isolation flag and namespace is checked, including uniqueness and
private namespace bindings. T3 also rejects added rootfs files, hooks, root replacement
and identity changes. The generated home is inventoried exactly against generated
config and admitted empty mountpoints. Descriptor-relative no-follow reads reject
extra files/directories, symlinks, missing entries and byte changes, and detect entry
or content replacement during readback. These checks observe render/pre-dispatch
state; exclusive bundle custody after the check remains an activation obligation.
Config is published only after this check. The emitted argv/config hashes describe
the final carrier, not its intermediate bubblewrap representation.

The renderer refuses every unqualified subscription execution shape before artifact
creation, including `--bare`, unknown flags, config-based overrides, shell wrappers
and a trivial executable path. Route `auth_surface` and model/effort identity receipts
do not qualify the complete argv/config/env/credential shape. The existing harness
onboarding owner must supply that qualification through execution admission before
subscription launch can be supported. API declarations permit source rendering only;
they do not authorize spend or a fallback. No subscription declaration is rewritten.
Synthetic source/runtime fixtures declare API explicitly and never call a provider.
Credential values remain file bindings, never environment or renderer evidence.

Source checks: `uv run python tests/capability_envelope/run_source_checks.py`.
This deliberately does not run containment, cgroup, provider or real-harness probes.
The existing CI C10 job remains the runtime witness. Source tests do not establish
C1–C10, image/enrolment readiness, launch-record integration or independent acceptance.

`DispatchLaunchRequest.envelope` carries the existing declaration through
`WorkerAdapter.launch(..., rendered_envelope=...)`. Normalization detaches caller
data, binds the declaration hash, and rejects subsequent nested mutation. The
existing launch events carry that same hash, and replay refuses another identity.
The old callback is used only when both declaration and rendered carrier are absent.
An envelope-declared T2 launch uses the existing `execute` function, with the declared
timeout; the actual command/environment and channel surface are checked before MQ
consumption. T1/T3 execution refuses because no admitted executor is implemented here.
An artifact or declaration is never treated as evidence of runtime containment.

The [OCI 1.2.1 mount contract](https://github.com/opencontainers/runtime-spec/blob/v1.2.1/config.md#linux-mount-options)
backs the `rro` option on read-only bind mounts. Target runtime support and actual
recursive read-only enforcement remain runtime qualification obligations.
