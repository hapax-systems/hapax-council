# Self-Hosted Runner Experiment

This is a bounded experiment, not a CI migration. The default required CI
surface stays on GitHub-hosted runners until the gate below is explicitly
adopted.

## Scope

The experiment may run only through
`.github/workflows/self-hosted-runner-experiment.yml` using manual
`workflow_dispatch`. It is for PR-safe, non-secret jobs that can be rerun on a
trusted branch without granting the runner production authority.

The runner must advertise all of these labels before the workflow can start:

- `self-hosted`
- `linux`
- `x64`
- `hapax-council-ci`
- `pr-safe`
- `no-secrets`
- `ephemeral-preferred`

No existing `pull_request`, `push`, scheduled, release, deploy, Claude, SDLC,
secret-scan, or production workflow is moved to the self-hosted runner by this
slice.

## Security Boundary

The runner is expected to run as `github-runner-hapax-ci` with no operator
session access and no `pass`, audio, camera, broadcast, Daimonion, tmux, or
private service access. A rootless or `systemd-nspawn` boundary is preferred
before any adoption decision.

The experiment workflow has `contents: read` permissions and must not reference
`${{ secrets.* }}`. If a job needs a secret, deployment token, production
service, private transcript, operator media path, or privileged host group, it
is outside this experiment and must stay on hosted CI or be rejected.

Allowed network egress is limited to GitHub and Python/uv package retrieval for
the selected non-secret test slice. The runner must not be enrolled in
repository branch protection or default PR checks while this decision is
`defer`.

## Cache And Work Roots

Provision the cache and work roots for the runner service user before dispatch:

```bash
sudo install -d -m 0700 -o github-runner-hapax-ci -g github-runner-hapax-ci \
  /var/cache/hapax/github-actions/self-hosted-runner-experiment/uv \
  /var/cache/hapax/github-actions/self-hosted-runner-experiment/xdg \
  /var/cache/hapax/github-actions/self-hosted-runner-experiment/work \
  /var/cache/hapax/github-actions/self-hosted-runner-experiment/metrics \
  /var/lib/hapax/github-actions/self-hosted-runner-experiment
```

The experiment treats unwritable cache roots as a failed boundary check. Cache
retention is seven days or ten GiB total, whichever is smaller.

## Teardown

The experiment is reversible. Teardown means:

```bash
sudo systemctl disable --now github-runner-hapax-ci.service
sudo rm -rf /var/lib/hapax/github-actions/self-hosted-runner-experiment
sudo rm -rf /var/cache/hapax/github-actions/self-hosted-runner-experiment
sudo userdel github-runner-hapax-ci
```

Also remove the self-hosted runner registration and labels from repository
settings. If the experiment is dismissed, retire the manual workflow or leave it
disabled with this document updated to `dismiss`.

## Metrics

Record every manual dispatch against the hosted baseline from
`docs/research/2026-04-26-cicd-speedup-pr3-5-priorities.md`:

- hosted `test` reference: 225 seconds
- hosted `typecheck` reference: 83 seconds
- hosted `secrets-scan` reference: 6 seconds

For the non-secret static slice, capture wall time, queue time, runner label
set, selected suite, cache hit/miss notes, and any parity difference versus
hosted CI.

## Adopt, Defer, Or Dismiss

Current decision: **defer**.

Adopt only after three consecutive manually dispatched runs are green, the
non-secret static slice is at least three times faster than the hosted baseline,
environment parity holds, teardown is verified, and security review confirms no
secret-bearing or unsafe jobs are enrolled.

Defer if the runner is unavailable, insufficiently isolated, slower than the
threshold, or too costly to operate.

Dismiss if the experiment would require secrets, default PR execution, privileged
host access, production service access, unbounded caches, or environment drift
that would make hosted CI and self-hosted CI disagree.

## Policy

The machine-readable contract lives in
`config/ci/self-hosted-runner-experiment.yaml`. Static tests in
`tests/ci/test_self_hosted_runner_experiment.py` pin the manual-only workflow,
read-only permissions, label boundary, cache roots, and default hosted CI
posture.
