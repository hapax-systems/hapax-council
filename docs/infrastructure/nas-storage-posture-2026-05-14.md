# NAS Storage Posture — 2026-05-14

## Hardware

- **Device**: Synology DS425+ at 192.168.68.71
- **Volume**: volume1 (11T total, 564G used, 10T available, 6%)
- **Protocol**: NFS v4.1, hard mount, noatime

## Shares

| Mount | NFS Path | Use |
|-------|----------|-----|
| `/mnt/nas/backups` | `volume1/hapax-backups` | Tier 1 restic repo + Qdrant snapshots |
| `/mnt/nas/archive` | `volume1/hapax-archive` | Long-term archive |
| `/mnt/nas/models` | `volume1/hapax-models` | LLM model storage |

All three shares appear to be on the same volume (identical size/used/avail).

## Storage Breakdown

| Component | Size | Notes |
|-----------|------|-------|
| Qdrant snapshots | 315G | 11 collections, daily via hapax-backup-local |
| Restic repo (Tier 1) | 3.4G | Daily incremental, deduplicated |
| Total backups | 319G | 3% of available NAS space |

## Redundancy Assessment

The DS425+ supports 4 drive bays. Volume1 reports 11T total, which implies
either:
- **2x 8TB in SHR-1** (~8TB usable, matches 11T raw) — single-drive fault tolerance
- **3x 4TB in SHR-1** (~8TB usable) — single-drive fault tolerance
- **Single 12TB drive** — NO fault tolerance

> **ACTION REQUIRED**: Log into DSM at http://192.168.68.71:5000 and check
> Storage Manager > Volume 1 > Drive Information to confirm RAID type and
> drive count. Document the result here.

## Risk Acceptance

Regardless of RAID configuration, the NAS is a **single device** on the local
network. B2 (Tier 2) is the true disaster recovery copy. The NAS provides:
- Fast local restore (NFS, ~100MB/s)
- Point-in-time Qdrant snapshots not in Tier 2 (gap documented in DR plan)
- Model storage for offline operation

**Accepted risk**: NAS failure loses daily Qdrant snapshot granularity and
forces Tier 2 (B2) restore for all other data. Recovery time increases from
minutes (NAS) to hours (B2 download). This is acceptable given the weekly B2
backup cadence.

## References

- DR Plan: REQ-20260512-disaster-recovery-plan.md
- Storage Strategy: distro-work/storage-strategy-2026-05-12.md
- Backup Watchdog: PR #3261
