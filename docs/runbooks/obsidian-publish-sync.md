# Obsidian Publish Sync

## Withdrawn 2026-09-05

Operator direction, verbatim, relayed by root at 2026-09-05T20:03:49Z (the bus
message carrying it bears the filename label 20260905T2013Z; that label is not
the delivery time):

> get rid of obsidian publish exposure: we need another way to make a curated research basis available. that was an early way to do so but too much exposure

> we can deal with the research curation issue later, for now, just excise obsid pub

Removed committed paths:

- `scripts/hapax-obsidian-publish-sync`
- `systemd/units/hapax-obsidian-publish-sync.service`
- `systemd/units/hapax-obsidian-publish-sync.timer`
- `config/obsidian-publish/Home.md`
- `config/obsidian-publish/publish.css`

The timer's preset enablement and the omg.lol landing page's vault route were
also removed. The public-surface registry retains the withdrawn entry as history.
Vault originals and private Sync/backups are preserved. The Publish site itself
no longer exists: root deleted it at the provider on 2026-09-05 and witnessed the
withdrawal independently of this source change (authenticated owned-site
inventory 1 → 0 after native deletion; the public site URL answers 404 on desktop
and mobile; a direct URL of the old home asset answers 401, which is not claimed
as deletion proof). No intermediate password-removal exposure occurred: the site
stayed password-protected until it was deleted. That provider withdrawal and
podium's unit stop/disable/mask are root's separate evidence; this source
retirement did not effect the deletion and does not attest to it beyond citing
that record. Research curation is a later, separate question.

### Observed withdrawal (root's readback, sanitized)

Observer report, not cryptographic proof. Account and site identifiers, token
details, private file names and counts, and browser or profile locators are
omitted on purpose.

- 2026-09-05T20:15:43Z: the native provider deletion of the site was accepted;
  the authenticated owned-site inventory changed from one to zero, as observed
  by root. No provider account was deleted and private Sync was not changed.
- The public site URL independently returned 404 ("Not found!") in fresh desktop
  and mobile browser contexts. A direct URL of an old asset returned 401, which is
  expressly not deletion proof. No claim is made about physical backup or cache
  erasure at the provider.
- 2026-09-05T20:43Z readback on both managed hosts: the Publish service and timer
  report `LoadState=masked` and `UnitFileState=masked`; on appendix both are
  inactive; on podium the timer is inactive and the service retains its old
  failed state (not active). The native site mapping is null and the Publish
  plugin is disabled, so no configured site remains.
- 2026-09-05T20:43Z installed-wrapper inventory: on both hosts the installed
  wrapper link still points at the source-activation worktree's copy of the
  wrapper, and that pre-merge target still exists (main at `cad2ec5ab`); mutable
  checkout copies also exist. The installed wrapper is therefore not absent until
  this source change is activated. The runtime masks are the mitigation in force,
  not a claim about every historical copy.

### Recheck (read-only)

None of these commands reruns the provider deletion or touches a credential.

```bash
# public slug, no credentials — expect 404
curl -sS -o /dev/null -w '%{http_code}\n' https://publish.obsidian.md/hapax/
# on EACH managed host — expect masked and no active/running unit
# (old failed residue may remain on the service)
systemctl --user show hapax-obsidian-publish-sync.service \
  hapax-obsidian-publish-sync.timer \
  --property=Id,LoadState,UnitFileState,ActiveState
# installed wrapper: pre-activation (target exists) versus post-activation (absent)
readlink -f ~/.local/bin/hapax-obsidian-publish-sync
test -e "$(readlink -f ~/.local/bin/hapax-obsidian-publish-sync)" \
  && echo target-exists || echo target-absent
# source absence only — proves nothing about installed copies or the provider
uv run pytest -q tests/test_obsidian_publish_is_excised.py
```

### Historical procedure — withdrawn; do not execute

The procedure below is retained only as history of the retired publication path.

Hapax publishes the public vault at <https://publish.obsidian.md/hapax>.
The automation is intentionally small: repo-owned assets are copied into the
vault, then `obsidian-headless` publishes files whose frontmatter includes
`publish: true`.

#### One-time setup

Install the headless client with Node.js 22 or newer:

```bash
npm install -g obsidian-headless@0.0.8
ob login
```

The local vault must already have `.obsidian/publish.json` connected to the
Hapax Publish site. The current site config is under
`~/Documents/Personal/.obsidian/publish.json`.

The wrapper reads that site ID and runs `ob publish-setup` automatically when
the headless client has not yet been connected to the local vault. If the
Obsidian account is not logged in, run `ob login` once and rerun the wrapper.

#### Manual smoke

```bash
scripts/hapax-obsidian-publish-sync --dry-run
scripts/hapax-obsidian-publish-sync
```

`--dry-run` runs the Obsidian Headless publish planner without changing the
public site. The non-dry run publishes without prompting.

#### Timer

The user timer is `hapax-obsidian-publish-sync.timer`. It runs the sync every
30 minutes, with a short randomized delay, from the canonical deploy worktree.
The service passes `--install-headless`, so a missing `ob` binary is installed
from the pinned npm package before publish.

```bash
systemctl --user enable --now hapax-obsidian-publish-sync.timer
```

<!-- end: withdrawn 2026-09-05 -->
