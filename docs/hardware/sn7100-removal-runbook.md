# SN7100 Removal Runbook — restore 3090 to PCIe x16

**Goal:** remove the WD_BLACK SN7100 1 TB NVMe from the secondary M.2 slot so the primary NVMe slot (and therefore the 3090) can operate at full x16 instead of shared x8. Inference is bandwidth-insensitive at steady state, but every other GPU workload (reverie, compositor glitch passes, video encode) benefits.

## Why this is safe now

- /data (SN7100) total used: ~37 GB. Contents: `/data/docker` 14 GB, `/data/containerd` 18 GB, `/data/backups` 2.3 GB, `/data/minio` 2.1 GB, `/data/open-webui` 891 MB, `/data/n8n` 4.6 MB, `/data/ntfy` trivial.
- Root btrfs has 751 GB free. The migration back is smaller than the one we did into /data two days ago.
- Docker already runs with `live-restore: true`, so a docker-daemon restart does not kill running containers mid-flight.
- The original daemon.json and containerd config templates are still recoverable from their sibling `.bak` files written during the forward migration.

## Phase 1 — Pre-flight (operator present, 10 min)

1. Confirm all 13 containers healthy and no in-flight work that matters: `docker compose -f ~/llm-stack/compose.yaml ps`. Note anything non-green.
2. Snapshot current config files for rollback:
   ```
   sudo cp /etc/docker/daemon.json /etc/docker/daemon.json.pre-sn7100-removal
   sudo cp /etc/containerd/config.toml /etc/containerd/config.toml.pre-sn7100-removal
   ```
3. Capture container state for diffing:
   ```
   mkdir -p ~/hapax-state/sn7100-removal
   docker compose -f ~/llm-stack/compose.yaml ps --format json > ~/hapax-state/sn7100-removal/pre-state.json
   docker volume ls > ~/hapax-state/sn7100-removal/pre-volumes.txt
   ```
4. Announce quiet window (compositor + voice can stay up; they don't touch /data).

## Phase 2 — Bind-mount paths prep (no service impact, 5 min)

The llm-stack compose file has bind mounts to `/data/minio`, `/data/n8n`, `/data/ntfy`, `/data/open-webui`, `/data/backups`. Destinations on root:

```
/data/minio       → /var/lib/hapax/minio
/data/n8n         → /var/lib/hapax/n8n
/data/ntfy        → /var/lib/hapax/ntfy
/data/open-webui  → /var/lib/hapax/open-webui
/data/backups     → /var/lib/hapax/backups   (or ~/hapax-state/backups if you prefer /home)
```

Create the destinations with correct owners:
```
sudo mkdir -p /var/lib/hapax/{minio,n8n,ntfy,open-webui,backups}
sudo chown -R 1000:1000 /var/lib/hapax/{minio,n8n,ntfy,open-webui,backups}
# n8n gotcha: container runs as UID 1000 exactly — already correct here.
```

Edit `~/llm-stack/compose.yaml` to point each bind mount at the new path. Do NOT start anything yet; this is purely config.

## Phase 3 — Stop, migrate, rewire (30 min total, ~10 min of actual downtime)

1. **Stop dependents** (services running on-host that talk to Docker):
   ```
   systemctl --user stop studio-compositor hapax-daimonion hapax-imagination \
       hapax-imagination-loop hapax-reverie hapax-dmn visual-layer-aggregator
   ```
2. **Stop the compose stack**:
   ```
   docker compose -f ~/llm-stack/compose.yaml down
   ```
3. **Stop daemons**:
   ```
   sudo systemctl stop docker.socket docker containerd
   ```
4. **Migrate** (run in parallel terminals — total ~5-8 min at NVMe speeds):
   ```
   sudo rsync -aHAX --info=progress2 /data/docker/       /var/lib/docker/
   sudo rsync -aHAX --info=progress2 /data/containerd/   /var/lib/containerd/
   sudo rsync -aHAX --info=progress2 /data/minio/        /var/lib/hapax/minio/
   sudo rsync -aHAX --info=progress2 /data/n8n/          /var/lib/hapax/n8n/
   sudo rsync -aHAX --info=progress2 /data/ntfy/         /var/lib/hapax/ntfy/
   sudo rsync -aHAX --info=progress2 /data/open-webui/   /var/lib/hapax/open-webui/
   sudo rsync -aHAX --info=progress2 /data/backups/      /var/lib/hapax/backups/
   ```
   `-aHAX` preserves hard links, ACLs, xattrs — overlay2 needs all three. If any rsync warns, stop and investigate; do NOT proceed with dirty snapshots.

5. **Revert daemon configs** (use the `.bak` files from the forward migration, which still contain the pre-/data paths):
   ```
   sudo cp /etc/docker/daemon.json.bak /etc/docker/daemon.json
   sudo cp /etc/containerd/config.toml.bak /etc/containerd/config.toml   # if it exists; otherwise regenerate
   ```
   Sanity-check that `data-root` in `/etc/docker/daemon.json` is either absent or `/var/lib/docker`, and that containerd's `root` is `/var/lib/containerd`.

6. **Start daemons**:
   ```
   sudo systemctl start containerd
   sudo systemctl start docker
   ```
   Verify: `sudo docker info | grep -E 'Docker Root Dir|Storage Driver'` shows `/var/lib/docker` and `overlayfs`.

7. **Bring compose stack back**:
   ```
   docker compose -f ~/llm-stack/compose.yaml up -d
   ```
   Watch: `docker compose ... logs -f --tail=50` for 60 s. n8n is the usual suspect for EACCES on startup — if it complains, `sudo chown -R 1000:1000 /var/lib/hapax/n8n`.

8. **Restart host services**:
   ```
   systemctl --user start hapax-dmn visual-layer-aggregator
   systemctl --user start hapax-imagination hapax-imagination-loop hapax-reverie
   systemctl --user start hapax-daimonion studio-compositor
   ```

## Phase 4 — Verify (10 min)

1. All 13 compose services healthy: `docker compose -f ~/llm-stack/compose.yaml ps`.
2. Diff state: `docker compose ... ps --format json > ~/hapax-state/sn7100-removal/post-state.json && diff -u ~/hapax-state/sn7100-removal/{pre,post}-state.json`.
3. LiteLLM → TabbyAPI reachable from inside the container:
   ```
   docker exec litellm python -c "import urllib.request; print(urllib.request.urlopen('http://172.18.0.1:5000/v1/models', timeout=5).status)"
   ```
4. Langfuse / Prometheus / Grafana panels populate with fresh data.
5. Studio compositor: `journalctl --user -u studio-compositor -f` — no `_call_activity_llm` timeouts for 60 s.

## Phase 5 — Unmount and fstab cleanup (2 min)

```
sudo umount /data
sudo sed -i.bak '/UUID=6b5c3d57-277b-4e4a-b75f-651d26ed0b60/d' /etc/fstab
sudo systemctl daemon-reload
```

The old mountpoint `/data` should now be an empty directory on root; leave it in place so the runbook can be re-run if needed.

## Phase 6 — Physical (operator's hands, 10 min)

1. Graceful shutdown: `sudo systemctl poweroff`.
2. Pull power. Open case. Remove the SN7100 from the secondary M.2 slot (X870 mobo — check manual for lane-sharing behavior; some boards need a BIOS PCIe Lane Allocation setting flipped to `Auto`/`x16` after the drive is removed, others detect automatically).
3. Reassemble, power on, enter BIOS, verify: PCIe slot info should show the primary PEG slot (where the 3090 lives) at `x16 Gen4`. Save + boot.

## Phase 7 — Post-boot verification (5 min)

1. `lspci -vv | grep -A1 -i '3090'` → look for `LnkSta: Speed 16GT/s, Width x16`.
2. `sudo dmesg | grep -iE 'nvme|pcie' | tail -20` → no errors, no lane downgrades.
3. All services come back clean under normal boot sequence (hapax-secrets → logos-api → tabbyapi → compositor/daimonion/...).
4. Quick compute-bandwidth sanity check:
   ```
   python3 -c "import torch; a=torch.randn(8192,8192,device='cuda:0'); torch.cuda.synchronize(); import time; t=time.time(); [a@a for _ in range(20)]; torch.cuda.synchronize(); print(f'{(time.time()-t)*1000:.0f} ms')"
   ```
   Compare against a pre-removal baseline if you captured one in Phase 1.

## Rollback

If anything in Phase 3 misfires, the path back is:

1. `sudo systemctl stop docker containerd`
2. Restore: `sudo cp /etc/docker/daemon.json.pre-sn7100-removal /etc/docker/daemon.json` (same for containerd).
3. `sudo systemctl start containerd docker`
4. `docker compose up -d`

The `/data` volume was untouched by the forward rsyncs (read-only source), so it is still a complete, bootable state.

## Known risks / gotchas

- **btrfs snapshots**: if snapper has captured any `/var/lib/docker` state from before the forward migration, those snapshots contain stale overlayfs metadata. After step 5 starts Docker cleanly, run `sudo snapper -c root cleanup number` to prune.
- **UFW rule for TabbyAPI** (`ALLOW IN 5000 from 172.18.0.0/16`) is not affected by the daemon restart; docker bridge keeps the same 172.18/16 range.
- **Restic backups** under `/data/backups` — the repo lock file is per-path; restic should re-read cleanly from the new location, but `restic check` after the move is cheap and worth it.
- **MinIO** expects its bucket directory layout; as long as the rsync preserved mode+owner, it mounts clean. If buckets read as empty, `mc admin info` and re-check ownership.
- **X870E mobo quirk**: some BIOSes don't fully release lanes back to the PEG slot until the empty M.2 slot is set to `Disabled` in BIOS. Check after the first boot; flip if needed.
