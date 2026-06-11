# Public Canonical URL Smoke - 2026-06-11

Authority: `hapax-public-canonical-url-smoke-repair-20260611`

This receipt records the first legibility repair for public weblog URLs whose
short paths return HTTP 200 while serving the weblog root/latest-post body. It
does not authorize new claims and it does not publish new weblog entries.

## Dispatch Constraint

The governed mutable dispatch route refused `mutation_surface: public` for both
Codex and Claude routes with `route_not_mutable_for_public`. This task therefore
landed the safe docs-side repair: stop citing smoke-failing short paths as
canonical, point repo-facing docs at smoke-proven live URLs, and mark the
Manifesto short path untrusted until it is actually published.

## Before Smoke

Collected with `curl -sSL -D ... --max-time 20` from cx-alpha on
2026-06-11.

| URL | HTTP | Title | Body SHA-256 | Verdict |
| --- | --- | --- | --- | --- |
| `https://hapax.weblog.lol/hapax-manifesto-v0` | 200 | `Hapax Weblog · Backlinking Is Anemic RAG` | `880ede827f1f1b4e90d1b0bfd2cb1ec757fc8a7b3a2cd7b45c1d96d363f5be45` | Noncanonical fallback |
| `https://hapax.weblog.lol/refusal-brief` | 200 | `Hapax Weblog · Backlinking Is Anemic RAG` | `880ede827f1f1b4e90d1b0bfd2cb1ec757fc8a7b3a2cd7b45c1d96d363f5be45` | Noncanonical fallback |
| `https://hapax.weblog.lol/` | 200 | `Hapax Weblog · Backlinking Is Anemic RAG` | `880ede827f1f1b4e90d1b0bfd2cb1ec757fc8a7b3a2cd7b45c1d96d363f5be45` | Weblog root/latest-post identity |
| `https://hapax.weblog.lol/velocity-report-2026-04-25` | 200 | `Hapax Weblog · Backlinking Is Anemic RAG` | `880ede827f1f1b4e90d1b0bfd2cb1ec757fc8a7b3a2cd7b45c1d96d363f5be45` | Noncanonical fallback |
| `https://hapax.weblog.lol/cohort-disparity-disclosure` | 200 | `Hapax Weblog · Backlinking Is Anemic RAG` | `880ede827f1f1b4e90d1b0bfd2cb1ec757fc8a7b3a2cd7b45c1d96d363f5be45` | Noncanonical fallback |

The identical hash across short paths and root is the defect. HTTP 200 is not
sufficient public evidence for these routes.

## Weblog API State

Authenticated read-only `OmgLolClient` checks on the `hapax` address found:

- `get_entry("hapax-manifesto-v0")`: HTTP 404, no entry.
- `get_entry("refusal-brief")`: live entry, public location
  `/2026/04/refusal-brief-an-automation-tractability-disclosure`.
- `get_entry("velocity-report-2026-04-25")`: live entry, public location
  `/2026/04/hapax-velocity-report-2026-04-25`.
- Cohort Disparity Disclosure: live entry, public location
  `/2026/04/cohort-disparity-disclosure-soundcloud-first-hours-distribution`.

## Current Canonical Decisions

| Artifact | Canonical public status |
| --- | --- |
| Manifesto | Public short path is noncanonical/untrusted. Do not cite `https://hapax.weblog.lol/hapax-manifesto-v0` until a fresh publish creates a smoke-proven Manifesto location. |
| Refusal Brief | Canonical public URL is `https://hapax.weblog.lol/2026/04/refusal-brief-an-automation-tractability-disclosure`. |
| Velocity evidence baseline | Canonical public URL is `https://hapax.weblog.lol/2026/04/hapax-velocity-report-2026-04-25`. |
| Cohort Disparity Disclosure | Canonical public URL is `https://hapax.weblog.lol/2026/04/cohort-disparity-disclosure-soundcloud-first-hours-distribution`. |

## After Smoke

| URL | HTTP | Title | Body SHA-256 | Verdict |
| --- | --- | --- | --- | --- |
| `https://hapax.weblog.lol/2026/04/refusal-brief-an-automation-tractability-disclosure` | 200 | `Hapax Weblog · Refusal Brief — An Automation-Tractability Disclosure` | `544899f0974ab34a07551547fcf617524231e8410de5c6aa0a63bd27521e4484` | Canonical Refusal Brief |
| `https://hapax.weblog.lol/2026/04/hapax-velocity-report-2026-04-25` | 200 | `Hapax Weblog · Hapax Velocity Report — 2026-04-25` | `27d0e3f70e24709015cad0cad25d033b16f620f4ae48db36c8b4266610cdad65` | Canonical Velocity baseline |
| `https://hapax.weblog.lol/2026/04/cohort-disparity-disclosure-soundcloud-first-hours-distribution` | 200 | `Hapax Weblog · Cohort Disparity Disclosure — SoundCloud First-Hours Distribution` | `df445f97b350cba5ac65759e563111a725542c8e4b9226da6402cead36e0eab4` | Canonical Cohort Disclosure |
| `https://hapax.weblog.lol/support` | 200 | `Hapax Weblog · Support` | `4ddb602ed9928ca67d060b624d047c92384247fcc1af4987686953153fd10b9f` | Existing support page remains valid |

## Follow-Up Needed

`NOTICE.md` is generated from `hapax-constitution/sdlc/render/`; this PR repairs
the rendered council copy, but the renderer constants should be updated in the
constitution repo so future renders preserve these canonical decisions.
