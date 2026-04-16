# Rig Migration Runbook (CPU + RAM + Mobo swap)

**Scope:** Replace CPU, RAM, and motherboard. **Keep:** both GPUs (RTX 3090 + RTX 5060 Ti), all storage devices (`/data`, `/store`, `~`), USB peripherals, OS install (CachyOS), NVIDIA driver (590.48.01, pinned).

Operator 2026-04-16 clarification: this is the minimal scope; anything beyond CPU/RAM/mobo becomes a bigger project, not this migration.

**Expected downtime:** ~2-3 hours (physical swap + BIOS + verification).

---

## Pre-migration checklist (while the old rig still boots)

Run `scripts/rig-migration-preflight.sh` OR walk the list below by hand.

- [ ] **Commit + push all local work** in every worktree. Uncommitted changes vanish if a drive is handled roughly.

  ```bash
  for d in ~/projects/hapax-council ~/projects/hapax-council--beta ~/projects/hapax-council--q310-deps; do
      ( cd "$d" && git status --short -b )
  done
  ```

- [ ] **Snapshot running service state** — which units were active before the swap.

  ```bash
  systemctl --user list-units --state=running --no-pager \
      > ~/rig-migration-running-snapshot.txt
  ```

- [ ] **Record nvidia driver version + module params** so you can confirm they survive the swap.

  ```bash
  nvidia-smi --query-gpu=name,driver_version --format=csv > ~/rig-migration-nvidia.txt
  lspci | grep -i vga >> ~/rig-migration-nvidia.txt
  modinfo -F version nvidia >> ~/rig-migration-nvidia.txt
  ```

- [ ] **Snapshot BIOS-independent UEFI entries** so you don't lose boot order.

  ```bash
  sudo efibootmgr -v > ~/rig-migration-efi.txt
  ```

- [ ] **Record the LUKS/ZFS/LVM layout** if encrypted — new mobo may need re-binding. Print the UUIDs.

  ```bash
  lsblk -o NAME,UUID,MOUNTPOINT,FSTYPE,SIZE,LABEL > ~/rig-migration-disks.txt
  ```

- [ ] **Power down cleanly** via `systemctl poweroff`. Don't yank power — Postgres, ClickHouse, and MinIO all need clean shutdown for WAL integrity.

- [ ] **Label the cables you unplug** if any are ambiguous (USB peripheral positions, PCIe slot ordering).

## During migration

- [ ] Swap CPU, RAM, mobo.
- [ ] Re-seat both GPUs in their original PCIe slots (RTX 3090 in the 16x slot for inference; RTX 5060 Ti in the faster PCIe slot per operator's migration motivation).
- [ ] Verify CPU-socket thermal paste, RAM DIMMs clicked in fully, 24-pin + CPU EPS power connected.
- [ ] Connect existing storage devices to the same SATA/M.2 slots as before (or record new mapping if moved).
- [ ] Reconnect USB peripherals (Studio 24c, Cortado contact mic, Stream Deck MK.2, cameras, Blue Yeti).

## First boot

### BIOS setup

- [ ] Memory training: enable XMP/EXPO for rated speeds. Save and reboot (first boot after memory training often takes 30-60s).
- [ ] PCIe gen: verify 5060 Ti gets the generation operator was after (Gen 5 if mobo supports).
- [ ] Disable CSM/Legacy boot (UEFI only) to match prior install.
- [ ] Secure Boot: match prior state (likely off for NVIDIA driver compat).
- [ ] Boot order: restore first-entry = CachyOS-loader per `~/rig-migration-efi.txt` snapshot.

### Verification sequence

1. **System comes up** — Hyprland loads, greetd autologin fires.

2. **NVIDIA drivers bind both GPUs:**

   ```bash
   nvidia-smi
   # Expected: 2 GPUs listed (3090 + 5060 Ti), driver 590.48.01
   ```

3. **Storage mounts correctly:**

   ```bash
   df -h /data /store ~/
   # Expected: all three mounted
   ls /data/minio /store/clickhouse /store/qdrant
   # Expected: dirs exist with pre-swap contents
   ```

4. **USB peripherals enumerate:**

   ```bash
   lsusb | grep -iE "blue|elgato|presonus|c920|brio"
   # Expected: Blue Yeti, Elgato Stream Deck MK.2, PreSonus Studio 24c,
   #           all BRIO + C920 cameras
   ```

5. **Docker stack comes up:**

   ```bash
   cd ~/llm-stack && docker compose ps
   # All 13 containers should eventually show "healthy"; Postgres +
   # ClickHouse may take 30-60s for WAL replay after unclean shutdown.
   ```

6. **Systemd user units come up:**

   ```bash
   systemctl --user --failed --no-pager
   # Expected: 0 failed. Known-bad units from before migration
   # (rag-ingest's .venv-ingest issue) will still be failed; cross-
   # check against ~/rig-migration-running-snapshot.txt.
   ```

7. **TabbyAPI + TabbyAPI-olmo:**

   ```bash
   systemctl --user status tabbyapi tabbyapi-olmo --no-pager
   # Both should be active; they pin to GPU 1 (3090) and GPU 1 (3090)
   # respectively. Verify port listening: ss -ltnp | grep -E ':(5000|5001)'
   ```

8. **LiteLLM smoke test:**

   ```bash
   MASTER_KEY=$(grep -oP '^LITELLM_MASTER_KEY=\K.*' ~/llm-stack/.env)
   curl -s -X POST http://localhost:4000/v1/chat/completions \
     -H "Authorization: Bearer $MASTER_KEY" \
     -H "Content-Type: application/json" \
     -d '{"model":"local-fast","messages":[{"role":"user","content":"ok?"}],"max_tokens":4}' \
     | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['choices'][0]['message']['content'])"
   ```

9. **Compositor + imagination:**

   ```bash
   systemctl --user is-active studio-compositor hapax-imagination
   curl -s http://localhost:9482/metrics | grep -c "studio_camera_frames_total"
   # Expected: both active; metric count > 0.
   ```

10. **Langfuse + observability stack:**

    ```bash
    curl -s http://localhost:3000/api/public/health   # Langfuse
    curl -s http://localhost:9090/-/healthy            # Prometheus
    curl -s http://localhost:3001/api/health            # Grafana
    ```

## Post-migration hardening

- [ ] **Update HAPAX_REBUILD_LOAD_MAX** in systemd drop-in if new rig has materially more cores. Current default 3.0 is tuned for 16-core pre-migration rig. If new rig is 24-core+, raise to 4.0 or 5.0.

- [ ] **Rerun the rebuild-services cycle** once to confirm the pressure guard passes on the new rig:

  ```bash
  systemctl --user start hapax-rebuild-services.service
  journalctl --user -u hapax-rebuild-services -n 20 --no-pager
  # Expected: no "SKIPPED under pressure" messages
  ```

- [ ] **Verify stream-mode axis + transition-gate** still works end-to-end:

  ```bash
  hapax-stream-mode             # show current
  hapax-stream-mode private     # should accept
  # If you want to test public: requires a broadcast consent contract
  # or --force. Do NOT --force without one.
  ```

- [ ] **Check Phase 6 §6 gate still reads presence-metrics.json:**

  ```bash
  python3 -c "
  import sys; sys.path.insert(0, '$HOME/projects/hapax-council')
  from shared.stream_transition_gate import read_presence_probability
  print('presence posterior:', read_presence_probability())
  "
  # Expected: > 0.0 with operator at desk; 0.0 away.
  ```

- [ ] **Claim-shaikh cycle 2 kickoff** (optional, if deferred) once substrate + stream are green.

## Troubleshooting

### Nvidia doesn't bind after swap

- New mobo may use different PCIe ACS grouping. `dmesg | grep -i nvidia` for bind errors.
- If kernel refuses, confirm driver version pinned in `/etc/pacman.conf` matches what's installed.
- Fallback: `sudo mkinitcpio -P && reboot`.

### Docker containers won't start

- Postgres WAL recovery from unclean shutdown: look for "recovered from WAL" in `docker logs postgres`. Takes up to 2 min.
- ClickHouse re-replication: up to 60s on first query.
- MinIO: `mc ready local` to confirm.

### Failed systemd user units

- `hapax-logos` on NVIDIA Wayland: ensure `__NV_DISABLE_EXPLICIT_SYNC=1` still in `.envrc` and systemd drop-in. The webkit2gtk syncobj bug is hardware-independent.
- `rag-ingest`: known-bad pre-migration (`.venv-ingest` missing); same post-migration.

### BIOS boot order wrong

- `sudo efibootmgr -o XXXX,YYYY,ZZZZ` restores the order from `~/rig-migration-efi.txt`.
- If CachyOS entry missing: boot USB install media, chroot, re-run bootloader install.

### Load average higher than expected after migration

- The pressure guard (scripts/rebuild-service.sh) defaults to `HAPAX_REBUILD_LOAD_MAX=3.0`. New rig with more cores → raise ceiling via `systemctl --user edit hapax-rebuild-services.service` drop-in:

  ```
  [Service]
  Environment=HAPAX_REBUILD_LOAD_MAX=5.0
  ```

## Not in scope for this migration

Operator 2026-04-16: only CPU / RAM / mobo change. These are **explicitly NOT part of this migration** and should NOT be touched:

- Data volumes (`/data` MinIO blobs, `/store` qdrant / clickhouse / postgres)
- Home dir (repos, worktrees, state, vault, caches)
- OS install (CachyOS stays)
- NVIDIA drivers (590.48.01 stays pinned)
- Network (Tailscale identity, ufw rules, Pi fleet IPs)
- Audio stack (PipeWire config, voice-fx presets)
- Model weights (TabbyAPI + TabbyAPI-olmo EXL3 files)
- Secrets (pass store, gnupg, direnv, OAuth tokens)

If anything here needs touching, it's a separate operation — stop, flag, and plan before proceeding.

## Reference

- Memory pointer: `~/.claude/projects/-home-hapax-projects/memory/project_rig_migration.md`
- LRR Phase 6 §0.5.2 — 70B reactivation guard (new CPU envelope does NOT automatically re-authorize 70B substrate; the constitutional drill-then-authorize protocol still applies)
- Pre-migration pressure guard: `scripts/rebuild-service.sh` — thresholds documented in the script header

— initial draft beta → delta takeover 2026-04-16
