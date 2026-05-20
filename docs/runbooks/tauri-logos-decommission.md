# Tauri Logos Decommission Runbook

The production livestream surface is `logos-api :8051` plus
`studio-compositor` feeding OBS/V4L2 (`/dev/video42`) and HLS/MediaMTX where
enabled. The Tauri/WebKit `hapax-logos` preview is retired from production and
must not be started by boot, visual-stack restart, deploy, rebuild, Stream Deck,
or KDEConnect paths.

## Security Dependency Disposition

Status as of 2026-05-20: the native Tauri shell is a release blocker, not a
shippable runtime. Current released Tauri 2.11.2 still resolves Linux through
GTK3/WebKit2GTK and `glib 0.18.5`, which is inside GitHub advisory
`GHSA-wrw7-89jp-8q8g` (`glib >=0.15.0, <0.20.0`; patched floor `0.20.0`).
Cargo cannot force `glib 0.20.0` into that graph because `gtk 0.18.2` requires
`glib ^0.18`.

The active repository mitigation is to remove the retired Tauri runtime from
the active Cargo lockfile. `hapax-logos/src-tauri` remains only as a small
fail-closed Rust stub that exits with the decommission message; generated Tauri
schemas are not part of the active build surface.

Upstream blockers to recheck before any native-shell revival:

- Tauri GTK4 migration: https://github.com/tauri-apps/tauri/issues/7335
- `tauri-runtime` GTK4 migration: https://github.com/tauri-apps/tauri/issues/12562
- `tauri` GTK4 migration: https://github.com/tauri-apps/tauri/issues/12563
- Wry GTK4/WebKitGTK 6 migration: https://github.com/tauri-apps/wry/issues/1474
- Open but not releasable migration PRs as of 2026-05-20:
  https://github.com/tauri-apps/tauri/pull/14684,
  https://github.com/tauri-apps/wry/pull/1530,
  https://github.com/tauri-apps/tao/pull/1104,
  https://github.com/tauri-apps/muda/pull/341.

Recheck cadence: monthly, next on 2026-06-20, or sooner if Dependabot reports a
patched released Tauri/wry/tao/muda path. Revival requires all of:

- crates.io releases that move Linux to GTK4/WebKitGTK 6 or otherwise resolve
  `glib >=0.20.0`;
- `cargo tree -i glib@0.18.5 --locked` from `hapax-logos/src-tauri` returns no
  package match;
- `cargo check --locked` passes from `hapax-logos/src-tauri`;
- the release-blocker note above is replaced with a dated validation entry.

## Retired Runtime

These user units are decommissioned:

- `hapax-logos.service`
- `hapax-build-reload.path`
- `hapax-build-reload.service`
- `logos-dev.service`

`systemd/scripts/install-units.sh` removes stale symlinks for these units and
masks them. `hapax-visual-stack.target` does not want or require any of them.

## Replacement Surfaces

- Command/control: supported operator intents route through
  `shared.logos_control_dispatch`, which targets `logos-api :8051`, the
  compositor UDS command server, or an explicit local handler such as the vinyl
  rate file writer. Unsupported old frontend-only commands fail closed until
  given a production route.
- Visual frame exposure: old Tauri frame/FX ports `:8053` and `:8054` are
  retired. Production inspection uses `logos-api` studio endpoints,
  `/dev/shm/hapax-compositor/fx-snapshot.jpg`, OBS, `/dev/video42`, or HLS.
- Operator intervention: use Obsidian task/relay notes, Stream Deck/KDEConnect
  through central dispatch, `logos-api :8051`, `systemctl --user` for service
  state, and the studio compositor command socket. None require the Tauri
  preview.
- Legacy `/api/logos/directive` UI/browser directives return `410 Gone` with
  replacement guidance. They no longer write `/dev/shm/hapax-logos/*`.

## Post-Restart Validation

After pulling a decommission commit on the primary worktree:

```bash
systemd/scripts/install-units.sh
systemctl --user daemon-reload
systemctl --user restart hapax-visual-stack.target
```

Then validate:

```bash
systemctl --user list-dependencies hapax-visual-stack.target \
  | grep -E 'hapax-logos|hapax-build-reload|logos-dev' && exit 1 || true

systemctl --user is-enabled \
  hapax-logos.service hapax-build-reload.path logos-dev.service

systemctl --user is-active \
  hapax-logos.service hapax-build-reload.path logos-dev.service

ss -ltnp | grep -E ':(8052|8053|8054|5173)\b' && exit 1 || true
ss -ltnp | grep ':8051 '

pgrep -af 'hapax-logos|WebKitWebProcess|pnpm dev|vite' && exit 1 || true
test -e /dev/video42
```

`scripts/visual-audit.sh` wraps the same production checks and also probes the
Logos API studio camera and egress endpoints.
