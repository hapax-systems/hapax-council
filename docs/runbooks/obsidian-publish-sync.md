# Obsidian Publish Sync

## Withdrawn 2026-09-05

Operator direction, verbatim, relayed by root on 2026-09-05T20:13Z:

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
Vault originals, private Sync/backups, and the site's existing password protection
are preserved. Runtime/provider withdrawal (podium's unit stop/disable/mask and
the site's withdrawal) is root's separate evidence; this source retirement does
not attest to that withdrawal. Research curation is a later, separate question.

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
