# Management Context

## Safety Boundary
LLMs prepare, humans deliver. The system never generates feedback language,
coaching recommendations, or suggestions for what to say to team members.

## Team Data
- Person notes live in Obsidian vault at `10-work/people/`
- Coaching, feedback, meeting notes are subdirectories per person
- All team state is computed deterministically (zero LLM calls)
- Cognitive load is operator self-reported (1-5 scale)

## Data Policies
- No team member behavioral data is stored outside the vault
- Profile dimensions reflect the OPERATOR's management patterns, never team members
- Staleness thresholds: weekly 1:1 >10d, biweekly >18d, monthly >40d
