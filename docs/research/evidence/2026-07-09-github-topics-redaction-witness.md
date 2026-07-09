# GitHub Topics Redaction Witness

Scope: `hapax-systems/hapax-council` live public repository topics.

Readback time: 2026-07-09 11:23 CDT.

Authenticated `gh api repos/hapax-systems/hapax-council/topics` was unavailable
because the admin token was rate-limited, so this witness uses the public REST
topics endpoint:

```bash
curl -fsSL -H 'Accept: application/vnd.github+json' \
  https://api.github.com/repos/hapax-systems/hapax-council/topics
```

Observed response:

```json
{
  "names": [
    "single-operator",
    "research-software",
    "claim-authority",
    "governed-sdlc",
    "publication-egress",
    "refusal-systems"
  ]
}
```

Conclusion: the live public topic list no longer contains the prior
diagnosis/neurotype topic term.
