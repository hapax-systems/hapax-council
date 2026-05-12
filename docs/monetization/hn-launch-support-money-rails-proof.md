# HN Launch Support And Money-Rails Proof

Captured: 2026-05-12 14:47 UTC

## Verdict

- Support page: verified reachable.
- No-perk copy: verified present on the live support page.
- GitHub Sponsors: downgraded for the org surface. `ryanklee` is public;
  `hapax-systems` is not public.
- Money rails: service is active, but launch copy should claim only the running
  service and verified no-perk support surface, not all external rails as green.

## Evidence

`curl -I -L https://hapax.omg.lol/support` returned HTTP 200.

The rendered support section says support is receive-only and buys no access,
requests, priority, deliverables, or control. The page links to
`https://github.com/sponsors/ryanklee`.

GitHub GraphQL evidence:

- `organization(login: "hapax-systems")`: `hasSponsorsListing=false`,
  `sponsorsListing.isPublic=false`, no tiers.
- `user(login: "ryanklee")`: `hasSponsorsListing=true`,
  `sponsorsListing.isPublic=true`, URL `https://github.com/sponsors/ryanklee`.

Runtime evidence:

- `hapax-money-rails.service` is active and enabled.
- Active since: 2026-05-11 07:33:42 CDT.
- Recent logs include Lightning/Alby invoice polling HTTP 200.
- Recent logs also include Nostr relay connection warnings and a Liberapay
  public-payins HTTP 404, so "all payment rails active" is too strong for HN
  launch copy.

## Launch-Copy Rule

Use `https://hapax.omg.lol/support` as the public support link. Do not link HN
launch copy directly to `https://github.com/sponsors/hapax-systems` until the
org Sponsors listing is public and the no-perk tiers are verified.
