# Hapax GitHub Repo Standards

Hapax repositories live under `hapax-systems`. Do not create new Hapax repos
under `ryanklee`, and do not point live automation at `ryanklee/<hapax-repo>`.

## Creation

Use the wrapper instead of `gh repo create` directly:

```bash
scripts/hapax-github-repo-create hapax-example --private --description "..."
```

The wrapper refuses `ryanklee/<name>` and any owner other than
`hapax-systems`.

Organization members must not have direct repository creation enabled in GitHub
settings. Owners can still create repositories, so the wrapper and audit remain
mandatory for Hapax work.

## Organization Enforcement

The `hapax-systems` organization is part of the baseline:

- member repository creation is disabled for public, private, and internal
  repositories.
- GitHub Actions is enabled for all repos, but allowed actions are restricted to
  GitHub-owned actions plus the explicit Hapax allowlist.
- default workflow token permissions are read-only, and Actions cannot approve
  pull request reviews.
- the `hapax-default-branch-ci-cd` organization ruleset protects default
  branches, blocks deletion and force push, requires PR updates, and requires
  the stable `all-green` status check.
- org-level `CODECOV_TOKEN` and `SEMGREP_APP_TOKEN` exist for newly created
  repos; coverage uploads should prefer Codecov OIDC.
- public repos inherit GitHub's recommended code-security config.
- private/internal repos inherit `Hapax dependency baseline`, which enables
  dependency graph and Dependabot coverage without activating paid GitHub Code
  Security or Secret Protection.

## Required Baseline

Every Hapax repo needs:

- `AGENTS.md` with the `hapax-systems` ownership rule and advisory external
  review guidance.
- `.github/workflows/ci.yml` with a stable `all-green` aggregate when the repo
  has runnable code or data validation.
- `.github/workflows/semgrep.yml` using `SEMGREP_APP_TOKEN`.
- `.coderabbit.yaml` with `request_changes_workflow: false`.
- `codecov.yml`; add a Codecov OIDC upload when the repo produces coverage.
- `.github/dependabot.yml` for GitHub Actions and each package ecosystem with a
  manifest in the repo.
- `CODECOV_TOKEN` and `SEMGREP_APP_TOKEN` as org or repo secrets.

Run the audit after bootstrapping or transferring a repo:

```bash
scripts/hapax-github-repo-standards-audit.py --repo hapax-systems/hapax-example
```

Run the full organization audit after changing org settings or transferring a
batch:

```bash
scripts/hapax-github-repo-standards-audit.py
```

External CodeRabbit, Claude, Codex, Codecov, and Semgrep output is advisory
unless a governed Hapax task explicitly promotes a stable aggregate check to a
branch-protection gate.

## Known Boundaries

Do not enable `sha_pinning_required` until all workflow `uses:` refs have been
pinned to full-length SHAs and the selected-actions allowlist has been updated
accordingly.

Do not enable GitHub Code Security or Secret Protection for private/internal
repos without an explicit billing/security decision. Semgrep, Gitleaks, and
CodeQL public-repo coverage remain the active no-surprise baseline.
