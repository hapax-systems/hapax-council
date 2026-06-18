# System Dynamics Map Viewer Audit Fix Evidence

Task: `system-dynamics-map-viewer-audit-fixes-20260618`

This note records PR-visible evidence for the non-repo acceptance receipt repair
that accompanied the system dynamics viewer audit fixes.

## Prior Receipt Repair

The prior closed task receipt at:

`$HOME/Documents/Personal/20-projects/hapax-cc-tasks/closed/system-dynamics-map-viewer-ux-hardening-20260618.acceptance.yaml`

was repaired so the YAML `artifact` value parses as a filesystem path only:

`$HOME/Documents/Personal/20-projects/hapax-cc-tasks/closed/system-dynamics-map-viewer-ux-hardening-20260618.review-dossier.yaml`

The PR URL is now stored separately as:

`artifact_url: https://github.com/hapax-systems/hapax-council/pull/4188`

This avoids YAML line folding that previously appended the PR URL to the
artifact path and made the path fail existence checks.

## Recheck Command

Run from the repository root:

```bash
test -f scripts/cc-close-acceptance-receipt-check.py
python3 scripts/cc-close-acceptance-receipt-check.py \
  "$HOME/Documents/Personal/20-projects/hapax-cc-tasks/closed/system-dynamics-map-viewer-ux-hardening-20260618.md"
```

The repository script is pre-existing at this PR head. The command is the
replayable witness; the exit code below is the observed result during this fix
pass and should be refreshed by rerunning the command if the external receipt is
edited again.

```text
exit:0
```

## Related Viewer Evidence

The same fix pass also verified:

- `docs/architecture/system-dynamics-map.package.json` and
  `docs/architecture/system-dynamics-map.lock.json` intentionally record
  `git_sha: unknown`; content hashes are the staleness key and PR history carries
  commit provenance.

- Review-team admission was hardened for the landing path: a Gemini reviewer
  process failure with `IneligibleTierError` / `UNSUPPORTED_CLIENT` and no
  model stdout is classified as `reviewer-route-unavailable`, so T1 review can
  use the same TTL-bounded degraded-review path as quota/provider outages
  without mislabeling the failure as a transient provider outage. Regression
  coverage keeps model stdout and clean exits from forging that route failure.

- `python3 scripts/system_dynamics_map_materialize.py --check`
- `uv run ruff check scripts/system_dynamics_map_materialize.py scripts/review_team.py scripts/cc-pr-review-dispatch.py tests/test_system_dynamics_map_artifacts.py tests/test_system_dynamics_map_viewer_playwright.py tests/test_review_team.py tests/test_cc_pr_review_dispatch.py`
- `uv run ruff format --check scripts/system_dynamics_map_materialize.py scripts/review_team.py scripts/cc-pr-review-dispatch.py tests/test_system_dynamics_map_artifacts.py tests/test_system_dynamics_map_viewer_playwright.py tests/test_review_team.py tests/test_cc_pr_review_dispatch.py`
- `uv run pytest tests/test_system_dynamics_map_artifacts.py -q`
- `uv run pytest tests/test_review_team.py -q`
- `uv run pytest tests/test_cc_pr_review_dispatch.py -q`
- `uv run --extra ci pytest tests/test_system_dynamics_map_viewer_playwright.py -q`
- `scripts/system-dynamics-map-gate`
- `git diff --check`
- Source-neutral wording scan:

  ```bash
  python3 - <<'PY'
  from pathlib import Path
  import subprocess

  patterns = [
      "D" + "MN-centric",
      "D" + "MN centric",
      "Decision Model and " + "Notation-centric",
      "decision-modeling-" + "centric",
      "D" + "MN is the point",
      "d" + "mm",
  ]
  globs = [
      Path("docs/architecture").glob("system-dynamics-map*"),
      Path("tests").glob("test_system_dynamics_map*"),
  ]
  paths = [str(path) for group in globs for path in group]
  paths.append("scripts/system_dynamics_map_materialize.py")
  result = subprocess.run(["rg", "-n", "|".join(patterns), *paths], check=False)
  if result.returncode == 0:
      raise SystemExit(1)
  if result.returncode == 1:
      raise SystemExit(0)
  raise SystemExit(result.returncode)
  PY
  ```

- Hardcoded hex or conditional CSS scan:

  ```bash
  command -v rg >/dev/null
  ! rg -n '#[0-9a-fA-F]{3,8}|if \(.*(color|colour|background|border|stroke|fill)' \
    docs/architecture/system-dynamics-map-viewer.html \
    tests/test_system_dynamics_map_viewer_playwright.py \
    scripts/system_dynamics_map_materialize.py
  ```
