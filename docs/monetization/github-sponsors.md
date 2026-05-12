# GitHub Sponsors Activation

Status: repo-side activation ready; live org profile publication requires a GitHub token
with `admin:org` or `user` scope.

## Repo Surface

- Sponsor URL: `https://github.com/sponsors/hapax-systems`
- Funding file: `.github/FUNDING.yml`
- Funding targets: `hapax-systems`, with `ryanklee` retained as the existing personal fallback.
- Public entry points: root `README.md` sponsor badge and `hapax.omg.lol` elsewhere link.

## Profile Copy

Use this text for the GitHub Sponsors profile:

> Hapax is public research infrastructure for single-operator AI governance,
> refusal-as-data, and multimodal operating environments. Sponsorships support
> compute, archive storage, rights-safe production, and publication plumbing.
> Sponsorship does not buy access, requests, private advice, priority,
> shoutouts, guarantees, client service, deliverables, or control. Work
> continues regardless of support.

## No-Perk Tiers

| Amount | Cadence | Description |
|---:|---|---|
| $1 | Monthly | Monthly support for public Hapax research infrastructure. No perks, access, requests, priority, deliverables, or control. |
| $5 | Monthly | Monthly support for public Hapax research infrastructure. No perks, access, requests, priority, deliverables, or control. |
| $10 | Monthly | Monthly support for public Hapax research infrastructure. No perks, access, requests, priority, deliverables, or control. |
| $25 | Monthly | Monthly support for public Hapax research infrastructure. No perks, access, requests, priority, deliverables, or control. |

## CLI Apply Notes

GitHub exposes Sponsors profile and tier mutations through GraphQL. The current
local `gh` token can read the org and repo but cannot apply Sponsors mutations;
GitHub rejects `createSponsorsListing` without `admin:org` or `user`.

After refreshing scopes:

```bash
gh auth refresh -h github.com -s admin:org
```

Then create or update the org profile in the Sponsors dashboard:

```bash
description='Hapax is public research infrastructure for single-operator AI governance, refusal-as-data, and multimodal operating environments. Sponsorships support compute, archive storage, rights-safe production, and publication plumbing. Sponsorship does not buy access, requests, private advice, priority, shoutouts, guarantees, client service, deliverables, or control. Work continues regardless of support.'
gh api graphql \
  -f query='mutation($login:String!, $description:String!){ createSponsorsListing(input:{sponsorableLogin:$login, fullDescription:$description}){ sponsorsListing { id url dashboardUrl isPublic } } }' \
  -F login=hapax-systems \
  -F description="$description"
```

Create each tier with `publish:true`:

```bash
for amount in 1 5 10 25; do
  gh api graphql \
    -f query='mutation($login:String!, $amount:Int!, $description:String!){ createSponsorsTier(input:{sponsorableLogin:$login, amount:$amount, isRecurring:true, description:$description, publish:true}){ sponsorsTier { id name monthlyPriceInDollars isOneTime description adminInfo { isPublished isDraft isRetired } } } }' \
    -F login=hapax-systems \
    -F amount="$amount" \
    -F description='Monthly support for public Hapax research infrastructure. No perks, access, requests, priority, deliverables, or control.'
done
```

Verify:

```bash
gh api graphql \
  -f query='query($login:String!){ organization(login:$login){ hasSponsorsListing sponsorsListing { isPublic url tiers(first:20){ nodes { monthlyPriceInDollars isOneTime description adminInfo { isPublished isDraft isRetired } } } } } }' \
  -F login=hapax-systems
```

The repository Sponsor button becomes durable after this branch merges to
`main` and the `hapax-systems` Sponsors profile is public.
