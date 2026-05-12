# GitHub profile README canonical copy

Pre-authored content for the operator account profile README. As of the
2026-05-11 live-state reconcile, the correct rendered surface is
`ryanklee/ryanklee/README.md`, not `ryanklee/.github/profile/README.md`.
The copy in `profile/README.md` is the canonical checked-in source used to
refresh that live profile surface.

## Why this copy lives here

`hapax-council` is the governed public-material source for the current project
spine. Keeping the profile README copy here lets the docs tests catch stale
repo links, missing refusal posture, and private-surface overclaims before the
external profile repo is refreshed.

## Layout

```
docs/repo-pres/dot-github-scaffold/
├── README.md            # This file
└── profile/
    └── README.md        # Copy pushed to ryanklee/ryanklee/README.md
```

## Cross-references

- cc-task: `github-readme-profile-current-project-refresh`
- Refusal-as-data substrate: `agents/publication_bus/refusal_brief_publisher.py`
- V5 publication bus: `agents/publication_bus/`
