---
name: profile
description: Inspect the operator profile. Use when the user asks about their profile, dimensions, facts, or runs /profile.
---

Show the operator profile summary and dimension breakdown.

**Default (no args):** Read the distilled manifest and show a summary:

```bash
cd ~/projects/ai-agents && jq '{
  name: .operator.name,
  goals: [.goals.primary[] | {name, status}],
  patterns: (.patterns | keys),
  constraints: (.constraints | length),
  neurocognitive: (.neurocognitive | length)
}' profiles/operator.json
```

Then read the full profile and show per-dimension fact counts:

```bash
cd ~/projects/ai-agents && uv run python -c "
import json
p = json.load(open('profiles/operator-profile.json'))
for dim, facts in sorted(p.get('dimensions', {}).items()):
    count = len(facts) if isinstance(facts, list) else len(facts) if isinstance(facts, dict) else 0
    print(f'  {dim}: {count} facts')
"
```

**With dimension arg** (e.g., `/profile neurocognitive`): Show the facts for that specific dimension from `profiles/operator-profile.json`.

**With `--refresh` flag:** Run the profiler to update:

```bash
cd ~/projects/ai-agents && eval "$(<.envrc)" && uv run python -m agents.profiler --auto
```
