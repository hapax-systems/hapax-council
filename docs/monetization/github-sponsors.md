# GitHub Sponsors Activation

Status: repo-side activation ready, but HN-launch public copy is downgraded as
of 2026-05-12. The personal `ryanklee` Sponsors listing is public; the
`hapax-systems` org Sponsors listing is not public yet. Launch copy must route
through `https://hapax.omg.lol/support` until the org listing is verified public
with no-perk tiers.

Live org profile publication requires a GitHub token with `admin:org` or `user`
scope.

## Repo Surface

- Planned org Sponsor URL: `https://github.com/sponsors/hapax-systems`
- HN-launch support URL: `https://hapax.omg.lol/support`
- Funding file: `.github/FUNDING.yml`
- Current funding target: `ryanklee` only, because the org listing is not public.
- Public entry points: root `README.md` support badge and `hapax.omg.lol` support link.

## 2026-05-12 Verification Receipt

- `curl -I -L https://hapax.omg.lol/support` returned HTTP 200.
- The live support page says support is receive-only and buys no access,
  requests, priority, deliverables, or control.
- `gh api graphql` for `organization(login: "hapax-systems")` returned
  `hasSponsorsListing=false`, `sponsorsListing.isPublic=false`, and no tiers.
- `https://github.com/sponsors/hapax-systems` redirected to the org profile,
  not a public Sponsors page.
- `gh api graphql` for `user(login: "ryanklee")` returned
  `hasSponsorsListing=true`, `sponsorsListing.isPublic=true`, and
  `https://github.com/sponsors/ryanklee`.
- `systemctl --user status hapax-money-rails.service` reported the service active since
  2026-05-11 07:33:42 CDT. Logs showed Lightning/Alby polling HTTP 200, plus
  Nostr relay warnings and a Liberapay public-payins HTTP 404; launch copy may
  claim the money-rails service is running, but not that every external rail is
  end-to-end green.

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

After the `hapax-systems` Sponsors profile is public, restore `hapax-systems`
to `.github/FUNDING.yml` and route the README/support-page public entry points
to the org listing.
