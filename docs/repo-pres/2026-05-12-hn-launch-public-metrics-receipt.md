# HN Launch Public Metrics Receipt

Date: 2026-05-12
Sampled at: 2026-05-12T15:24:01Z
Repo: `hapax-systems/hapax-council`
Task: `hn-launch-public-metrics-proof`
Decision: public launch metrics must use only the receipt-backed claims below, or be softened.

## 60-Day PR Window

Window: 2026-03-12 through 2026-05-10, inclusive. This is 60 calendar days.

```bash
python - <<'PY'
from datetime import date
start=date.fromisoformat('2026-03-12')
end=date.fromisoformat('2026-05-10')
print((end-start).days+1)
PY
```

Output:

```text
60
```

Opened PRs:

```bash
gh api -X GET search/issues \
  -f q='repo:hapax-systems/hapax-council is:pr created:2026-03-12..2026-05-10' \
  --jq '{total_count,incomplete_results}'
```

Output:

```json
{"incomplete_results":false,"total_count":3041}
```

Merged PRs:

```bash
gh api -X GET search/issues \
  -f q='repo:hapax-systems/hapax-council is:pr is:merged merged:2026-03-12..2026-05-10' \
  --jq '{total_count,incomplete_results}'
```

Output:

```json
{"incomplete_results":false,"total_count":2871}
```

Public copy may say:

- `3,041` pull requests opened in the sampled 60-day launch window.
- `2,871` pull requests merged in that same 60-day launch window.
- `3,000+ PRs` only when the sentence does not imply all were merged.

Public copy must not say:

- `3,034` total PRs.
- `2,869` merged PRs.
- `3,000+ merged PRs`.

## Revert-Titled PRs

Command:

```bash
gh api -X GET search/issues \
  -f q='repo:hapax-systems/hapax-council is:pr is:merged merged:2026-03-12..2026-05-10 revert in:title' \
  --jq '.total_count as $n | {total_count:$n,incomplete_results,items:[.items[] | {number,title,state,html_url}]}'
```

Output:

```json
{
  "incomplete_results": false,
  "items": [
    {
      "html_url": "https://github.com/hapax-systems/hapax-council/pull/1173",
      "number": 1173,
      "state": "closed",
      "title": "revert(wireplumber): remove pc-loudnorm default-sink priority rule"
    },
    {
      "html_url": "https://github.com/hapax-systems/hapax-council/pull/1575",
      "number": 1575,
      "state": "closed",
      "title": "revert(audio): role.assistant target → hapax-voice-fx-capture (voice silence)"
    },
    {
      "html_url": "https://github.com/hapax-systems/hapax-council/pull/1043",
      "number": 1043,
      "state": "closed",
      "title": "fix(logos): revert FullscreenOverlay max-width pattern (was sizing to intrinsic)"
    },
    {
      "html_url": "https://github.com/hapax-systems/hapax-council/pull/1149",
      "number": 1149,
      "state": "closed",
      "title": "revert(audio): remove hapax-broadcast-master.conf — feedback cycle recurred post-deploy"
    },
    {
      "html_url": "https://github.com/hapax-systems/hapax-council/pull/700",
      "number": 700,
      "state": "closed",
      "title": "fix(reverie): audit follow-up — revert Requires=, drop content.intensity, docs + tests"
    }
  ],
  "total_count": 5
}
```

Rate calculation:

```bash
python - <<'PY'
print(f"opened_revert_rate={5/3041:.6%}")
print(f"merged_revert_rate={5/2871:.6%}")
PY
```

Output:

```text
opened_revert_rate=0.164420%
merged_revert_rate=0.174155%
```

Public copy may say:

- `five revert-titled PRs`.
- `0.16% of opened PRs by title-search audit`.

Public copy must not say:

- `all five were audio routing changes`.
- `zero governance failures` unless a separate root-cause receipt proves that stronger claim.

## Hooks, Axioms, and Refusal Briefs

Tracked council shell hook scripts:

```bash
git ls-tree -r --name-only origin/main -- hooks/scripts | rg '\.sh$' | wc -l
```

Output:

```text
42
```

Portable `agentgov` checks:

```bash
rg -n '^def scan_' packages/agentgov/src/agentgov/hooks.py | wc -l
```

Output:

```text
5
```

Constitutional axioms:

```bash
sed -n '1,80p' axioms/registry.yaml
```

Output includes five active axiom entries: `single_user`, `executive_function`,
`management_governance`, `interpersonal_transparency`, and `corporate_boundary`.

Markdown refusal briefs:

```bash
git ls-tree -r --name-only origin/main -- docs/refusal-briefs | rg '\.md$' | rg -v '/README\.md$' | wc -l
```

Output:

```text
47
```

All entries under `docs/refusal-briefs`, including non-brief registry files:

```bash
git ls-tree -r --name-only origin/main -- docs/refusal-briefs | wc -l
```

Output:

```text
48
```

Public copy may say:

- `42 tracked council shell hook scripts`.
- `five portable agentgov checks`.
- `47 markdown refusal briefs`.

Public copy must not say:

- `44 hook scripts`.
- `48 refusal briefs`, unless explicitly saying that the count includes the registry file.

## Unsupported or Removed Launch Metrics

These claims appeared in public or near-public HN launch copy but do not have a
receipt in this file:

- `2,158` test files.
- `12` refused publication surfaces.
- `3.1%` code churn.
- `176` agent modules.
- `112` user timers.
- `9,952` lines of governance code.
- `208` consent test files.

They must be either receipt-backed in a follow-up section before launch or
removed/softened from the public weblog, landing page, and HN first comment.

## Public Surface Correction

Show HN weblog source:
`docs/publication-drafts/2026-05-10-show-hn-governance-that-ships.md`

Live Show HN weblog:
`https://hapax.weblog.lol/2026/05/show-hn-governance-that-ships`

Landing page source:
`agents/omg_web_builder/static/index.html`

Live landing page:
`https://hapax.omg.lol/`

Corrections made on 2026-05-12:

- Replaced stale `3,034` / `2,869` PR wording with `3,041` opened and
  `2,871` merged in the sampled window.
- Kept `0.16%` only as the title-search rate over opened PRs.
- Replaced unsupported `44`/`47` hook ambiguity with `42` tracked council
  shell hooks and five portable `agentgov` checks.
- Replaced `48` refusal briefs with `47` markdown refusal briefs.
- Removed unreceipted public homepage metrics: code churn, module count, timer
  count, governance-code LOC, consent-test-file count, and exact research /
  programme-type counts.
- Removed unqualified `zero governance failures` and all-audio revert wording.
- Repaired the weblog publication path through the publication bus so the
  entry source carries concrete `Location: /2026/05/show-hn-governance-that-ships`;
  `https://hapax.weblog.lol/show-hn-governance-that-ships` is not the launch URL.

Verification commands:

```bash
curl -fsSL https://hapax.weblog.lol/2026/05/show-hn-governance-that-ships |
  rg -n '3,034|2,869|44 hook|48 refusal|zero governance|all five|five were audio|0\.3%|62 days|3,000\+ merged|merged over 3,000'
```

Expected: no matches.

```bash
uv run python - <<'PY'
from shared.omg_lol_client import OmgLolClient
content = OmgLolClient().get_web('hapax')['response']['content']
for needle in ['3,034', 'zero governance', '3.1%', '176', '112', '9,952', '208', 'GitHub Sponsors']:
    print(needle, needle in content)
PY
```

Expected: all values are `False`.
