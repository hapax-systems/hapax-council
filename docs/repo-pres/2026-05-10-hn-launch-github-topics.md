# HN Launch GitHub Topics Receipt

Date: 2026-05-10
Repository: `hapax-systems/hapax-council`
Task: `hn-launch-github-topics`

## Topic Set

The live GitHub repository topics were replaced through the GitHub REST topics
endpoint with this 17-topic launch set:

- `ai-research`
- `cognitive-architecture`
- `personal-ai`
- `autonomous-agents`
- `constitutional-ai`
- `ai-governance`
- `pydantic-ai`
- `gstreamer`
- `wgpu`
- `single-operator`
- `multi-agent`
- `livestream`
- `pipewire`
- `systemd`
- `neurodivergent`
- `consent-governance`
- `information-flow-control`

## Command Shape

GitHub's repository topics endpoint replaces the full topic list, so the launch
set was submitted as the complete `names[]` array:

```bash
gh api -X PUT repos/hapax-systems/hapax-council/topics \
  -H 'Accept: application/vnd.github+json' \
  -H 'X-GitHub-Api-Version: 2022-11-28' \
  -f 'names[]=ai-research' \
  -f 'names[]=cognitive-architecture' \
  -f 'names[]=personal-ai' \
  -f 'names[]=autonomous-agents' \
  -f 'names[]=constitutional-ai' \
  -f 'names[]=ai-governance' \
  -f 'names[]=pydantic-ai' \
  -f 'names[]=gstreamer' \
  -f 'names[]=wgpu' \
  -f 'names[]=single-operator' \
  -f 'names[]=multi-agent' \
  -f 'names[]=livestream' \
  -f 'names[]=pipewire' \
  -f 'names[]=systemd' \
  -f 'names[]=neurodivergent' \
  -f 'names[]=consent-governance' \
  -f 'names[]=information-flow-control'
```

## Verification

- `gh api repos/hapax-systems/hapax-council/topics ...` returned `count: 17`.
- `gh repo view hapax-systems/hapax-council --json repositoryTopics,url`
  returned the same 17 topics.
- The public repository page HTML includes topic links such as
  `/topics/cognitive-architecture`, `/topics/information-flow-control`,
  `/topics/ai-research`, and `/topics/consent-governance`.
