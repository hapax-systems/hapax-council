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

## Required Baseline

Every Hapax repo needs:

- `AGENTS.md` with the `hapax-systems` ownership rule and advisory external
  review guidance.
- `.github/workflows/ci.yml` with a stable `all-green` aggregate when the repo
  has runnable code or data validation.
- `.github/workflows/semgrep.yml` using `SEMGREP_APP_TOKEN`.
- `.coderabbit.yaml` with `request_changes_workflow: false`.
- `codecov.yml`; add a Codecov upload when the repo produces coverage.
- `CODECOV_TOKEN` and `SEMGREP_APP_TOKEN` as repo or org secrets.

Run the audit after bootstrapping or transferring a repo:

```bash
scripts/hapax-github-repo-standards-audit.py --repo hapax-systems/hapax-example
```

External CodeRabbit, Claude, Codex, Codecov, and Semgrep output is advisory
unless a governed Hapax task explicitly promotes a stable aggregate check to a
branch-protection gate.
