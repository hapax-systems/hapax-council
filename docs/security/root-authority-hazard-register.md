# Root Authority Hazard Register

This register preserves the adversarial evidence gathered while evaluating the
discarded caller-authenticated root-install protocol from PR #4551. It is not a
design for that protocol. The source-only OOM policy change deliberately has no
production mutation or authoritative live-verification path.

Any future root broker must start from an independently trusted launcher and a
host-root-held trust anchor. Same-UID files, processes, environment variables,
memfds, Git objects, receipts, logs, and loopback services are inputs, not
authority.

The source package retires the `hapax-oom-score-enforce` mutation path, but a
source-only cutoff does not stop or replace previously installed root mutators.
The historical service, timer, trigger, and sudoers grant therefore remain part
of this register until a separately authorized cutover attests their removal or
replacement. Source conformance is not evidence that cutover occurred.

| Hazard | Counterexample | Required boundary |
|---|---|---|
| Same-UID receipt forgery | Any Hapax process can reproduce another UID 1000 process's receipt bytes, ownership, mode, and directory layout. | Verify a per-request signature rooted in a host-root-held key; bind request ID, exact package SHA, generation, effects, and result. |
| Replay without freshness | A previously valid installation or canary receipt can be copied back after source or live state changes. | Include monotonic generation and freshness in signed request and result records; reject consumed and superseded generations. |
| Caller-selected finalizer | A sealed same-UID executable containing only successful exit can replace the intended final verifier. | Never execute caller-selected completion code; the broker owns its verifier and pins its executable descriptors before request parsing. |
| Caller-selected production mode | An environment variable or argument can exempt the caller from the production refusal it is meant to enforce. | Refuse production as the first entrypoint action unless invocation arrived through an independently authenticated broker channel. |
| Namespace-local PID 1 | In a nested PID and mount namespace with fresh procfs, `/proc/self/mountinfo` and `/proc/1/mountinfo` describe the same attacker-created namespace. | Obtain trusted host namespace and root descriptors from the launcher; do not use namespace-local PID 1 as a host anchor. |
| Effective-capability-only check | A process with `CapEff=0` and nonzero permitted, inheritable, or ambient sets can regain privilege. | Clear all capability sets, establish `NoNewPrivs`, and reject set-ID and file-capability executables before parsing untrusted input. |
| Set-ID or file-capability re-entry | A selected helper can restore privilege at `execve` even after the checking process appears unprivileged. | Broker pins approved executables by descriptor and rejects set-ID bits, `security.capability`, unsafe ownership, modes, and aliases. |
| Ancestor bind alias | A source tree can resolve to expected text paths while an ancestor is bind-mounted from a different object. | Walk from trusted root descriptors with `openat2` constraints and bind each component's mount ID, device, inode, owner, mode, and link count. |
| Time-of-check path replacement | A validated file, lock, directory, or symlink target can be exchanged before a later open or publication. | Operate through pinned descriptors; compare before/open/after identity and reject rename, growth, replacement, or mount changes. |
| Mutable Git history execution | A historical Git blob can contain a privileged helper even when the checked-out head does not. | Treat Git content as data; never execute current or historical repository code with elevated authority. |
| Environment injection | `BASH_ENV`, exported functions, `PYTHONPATH`, `DOCKER_HOST`, contexts, TLS variables, or a hostile `PATH` can redirect execution. | Enter a broker-owned empty environment and use pinned descriptors for every executable and endpoint. |
| Tool-spoofed live verification | Caller-selected `systemctl`, `docker`, `visudo`, `busctl`, or `apcaccess` can return expected values for copied live artifacts. | Authoritative verification runs inside the broker and signs current-generation observations from pinned tools and endpoints. |
| Mutable Docker name | Name-based stop, remove, or inspect can target a replacement container after a rename race. | Capture and validate one immutable full container ID, act only on that ID, and re-enumerate names after the operation. |
| Mutable image or model | A tag or writable model path can change between canary and durable launch. | Bind immutable image digest and content-addressed model digest, size, protected ancestors, and mount identity into the signed request. |
| Docker endpoint substitution | Ambient Docker context or host variables can make preflight and durable launch inspect different daemons. | Pin the local daemon endpoint and private config in an empty environment for every Docker operation. |
| False-green retirement state | Matching source sentinels can pass while the historical recurring enforcer timer or NOPASSWD grant remains live. Blocking login sessions alone is insufficient because linger or on-demand activation can restart `user@1000.service`. | Runtime cutover stops/disables the timer first, replaces helper/trigger/sudoers bytes, temporarily applies a root-owned mask to `user@1000.service`, and stops that complete delegated subtree to a root-observed empty-cgroup boundary before unmasking it. A score scan remains observational only. |
| False-green container responder | A port or health response may come from a foreign process or container with the expected name. | Bind health evidence to the immutable container ID, image digest, model digest, cgroup limits, and launch generation. |
| Partial durable publication | A crash or hostile umask can publish permissive or truncated receipt state after mutation and before deferral drain. | Create mode-0600 same-directory temporaries with `O_EXCL|O_NOFOLLOW`, complete write and fsync, atomic replace, directory fsync, and readback. |
| Lock-path replacement | Participants can hold different inodes under the same lock pathname, defeating serialization. | Every participant binds the same physical parent and basename inode before and after acquisition and across child execution. |
| State-generation split | Desired, installed, drain, and audit records can describe different package generations while each looks individually valid. | Publish and verify one signed generation transaction; never infer completion from caller-owned files or absence of pending state. |
| Dependency bootstrap substitution | A time-varying or writable package installer and dependency root can execute before validation, including under `sudo`. | Pin and verify the bootstrap binary independently; install a hash-complete closure under a root-owned non-writable ancestor chain. |
| Refusal after setup | A production refusal can exist but be reached only after NSS, path, source, lock, or tool lookup. | Test ordering with poisoned pre-refusal dependencies and prove the refusal occurs before any lookup or side effect. |
| Unreachable source convergence | Deleting or hardening a source unit does not stop an enabled historical installed unit. | Ship an always-reachable retirement transaction that stops, disables/masks, removes artifacts, and reconciles external processes by immutable identity. |
| False recovery promise | Timers or incident writers can persist a next action that the current source revision has disabled. | Treat recovery-string scans as an exit criterion and point only to an actually reachable, separately authorized successor. |
| Unbounded diagnostic input | Git, journal, command, or receipt diagnostics can stream attacker-controlled output into logs or memory. | Bound every diagnostic read and preserve a stable actionable cause without interpreting payload content. |
| Stale installed mutator | Source removes production installation while an older root-owned auditor, enforcer, trigger, timer, or sudoers grant remains active. | Staging must say that it does not reconcile installed bytes; a separately authorized cutover must identify, stop, replace, reload, and attest every retained runtime surface. |
| Privilege-drop session amplification | A recurring root timer invokes `runuser` or another PAM path for each user-unit query, registering thousands of logind sessions and wedging login I/O. | Do not retain a recurring root-to-user score bridge. Any future broker must avoid PAM/session creation and operate only within its root-owned authority boundary. |
| UID-owned manager as authority | `systemctl --user` reports values from a manager and bus controlled by the same UID receiving the root-only attribute; cached loaded unit bytes may differ from restored on-disk bytes. | Treat user-manager output as observation only. It cannot authorize a root grant. Workloads requiring negative scores must run in root-owned, non-delegated system units. |
| Cgroup basename or membership ambiguity | UID 1000 controls `cgroup.procs` below delegated `user@1000.service` and can create nested same-name paths or move same-UID processes around point-in-time checks. | Never grant a root-only process attribute on the basis of membership anywhere in the delegated subtree. Exact names, ancestry, and pre/post checks do not create durable confinement. |
| Fork/exec inheritance escape | A legitimately scored process forks after the final check; its child inherits the negative `oom_score_adj`, moves to a writable sibling cgroup, and execs arbitrary code. | Disable all root negative writes in delegated user cgroups. If required, let PID 1 configure the score in a root-owned, non-delegated system unit with `User=hapax`. |
| Rollback after point-in-time validation | Restoring one pinned process after a detected move cannot recover a child forked before rollback, a move after the last check, or a previously escaped descendant. A post-cutover child can inherit from an old parent and outlive it, so start-time checks alone are insufficient. | Do not treat rollback or repeated scanning as confinement. Runtime retirement must block reactivation and terminate the complete delegated `user@1000.service` subtree to an empty-cgroup boundary after the grant path is gone. Root-owned non-delegated system units with `User=hapax` are outside that boundary. |
| Privileged test-selector admission | `HAPAX_*_TEST_MODE`, fake procfs/cgroup roots, or substituted tools survive `sudo` and redirect a root write. | Retired sentinels perform no writes or tool lookup. Any future privileged broker uses an empty environment, rejects caller selectors, and pins every executable and endpoint before parsing input. |

The counterexamples above remain mandatory review input even though the code
that exposed them was reverted. Reintroducing production root mutation or
authoritative verification requires a separate runtime-authorized task and a
fresh threat model against this complete register.
