# DHCP reservations — Hapax Pi fleet

Keep these locked on the LAN router's DHCP reservation table so Pis don't wander on reboot. Pi-6 wandered from .74 to .81 in early April 2026 and silently broke `/etc/hosts`-based scripts for ~6 days until epsilon caught it on 2026-04-15.

## Current reservations (verify these exist, lock them if not)

| Hostname (new) | Legacy | IP | MAC | Status |
|---|---|---|---|---|
| hapax-ir-desk | hapax-pi1 | 192.168.68.78 | (check router) | Lock — was stable |
| hapax-ir-room | hapax-pi2 | 192.168.68.52 | (check router) | Lock — was stable |
| hapax-hub | hapax-pi6 | **192.168.68.81** | (check router) | **WANDERED — lock immediately** at .81 |
| hapax-sentinel | hapax-pi4 | 192.168.68.53 | (check router) | Lock — was stable |
| hapax-rag | hapax-pi5 (Pi 4 hw) | 192.168.68.72 | (check router) | Lock — was stable |

## New reservation to add

| Hostname | IP | MAC | Note |
|---|---|---|---|
| **hapax-ai** | **192.168.68.79** | TBD Thursday at unboxing | Next available between sentinel .53 and rag .72; skip .79 is currently unused per `nmap -sn 192.168.68.0/24` run 2026-04-15 |

## Router instructions (specific to your router model — adjust)

If the router is a Google Nest Wifi or similar:

1. Open Google Home app → Wi-Fi → Devices
2. Find the device by MAC (unbox the Pi 5, check the ethernet jack sticker, or `arp -a` from the workstation after first connection)
3. Set reservation to 192.168.68.79

If the router is UniFi / EdgeRouter / OPNsense:

1. Services → DHCP Server → Static Mappings
2. Add: MAC + IP 192.168.68.79 + hostname `hapax-ai`
3. Apply, restart DHCP service

## Verification after reservation

From the workstation:

```bash
# Once Pi 5 has been plugged in and powered up on Thursday:
ping -c1 192.168.68.79                         # should reach the Pi
ssh hapax@hapax-ai.local                       # avahi path
ssh hapax@192.168.68.79                        # IP path
getent hosts hapax-ai                          # should return .79 (already in /etc/hosts)
```

## Also check — lock pi-6

Pi-6 is currently at .81 but was supposed to be at .74. The move happened without a DHCP reservation lock. Before next reboot, **lock pi-6 to .81**, or pick a different canonical IP and update both the router AND `/etc/hosts`. Don't let it wander again.
