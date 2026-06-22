#!/usr/bin/env python3
"""screwm-cns-witness — thorough, duration-sensitive, multi-POV witness for Hapax' CNS.

Why this exists: numpy sims of shader math prove bounds but have no reverie input, no mtime, no wall
clock — they CANNOT exhibit or catch a temporal-still failure. The change-gate freeze (drift spatially
varied but temporally STILL, "no changes in the livestream all day") was invisible to them. This is the
AVSDLC visual witness: it captures the real substrate + OBS POV OVER DURATION and computes SPATIAL vs
TEMPORAL variance separately — a freeze is HIGH spatial + ZERO temporal, which any single-frame or
whole-frame metric conflates and passes.

Run via the activated venv python (has obsws_python):
  ~/.cache/hapax/source-activation/worktree/.venv/bin/python scripts/screwm-cns-witness.py --label after
DEFAULT --no-drive: observe-only, zero game-data writes, zero camera moves — LIVE-SAFE.
Exit 2 on any freeze / stale-producer / named-culprit causality break.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

# Make ``shared`` importable when run directly (script lives at <repo>/scripts/).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Substrate taps (exists()-guarded; corrected paths per the witness-procedure audit).
SHM = Path("/dev/shm")
ARTIFACTS = {
    "reverie": (SHM / "hapax-sources/reverie.rgba", (540, 960, 4)),
    "drift_field": (SHM / "hapax-compositor/quake-drift-field.bgra", (256, 256, 4)),
    "drift_currency": (SHM / "hapax-compositor/quake-drift-currency.bgra", (256, 256, 4)),
    "reverie_frame": (SHM / "hapax-visual/frame.jpg", None),  # jpg, bytes-only liveness
}
# Causality edges: downstream must advance IFF upstream advances.
EDGES = [("reverie", "drift_field"), ("reverie", "drift_currency")]
OBS_CFG = Path.home() / ".config/obs-studio/plugin_config/obs-websocket/config.json"
OUT_ROOT = Path.home() / ".cache/hapax/screenshots/screwm-cns-witness"


def _read(path: Path):
    try:
        return path.read_bytes(), path.stat().st_mtime
    except OSError:
        return None, None


def _zones_temporal_std(series: list[np.ndarray], shape, zy=8, zx=8) -> float:
    """Per-zone temporal std: tile each frame into zy×zx, track each zone's mean over time, return the
    fraction of zones whose temporal std exceeds a small floor. 0.0 ⇒ every zone temporally still."""
    if len(series) < 3 or shape is None:
        return -1.0
    h, w, c = shape
    chan = [f.reshape(h, w, c)[:, :, min(2, c - 1)].astype(np.float64) for f in series]
    bh, bw = max(1, h // zy), max(1, w // zx)
    moving = 0
    total = 0
    for j in range(zy):
        for i in range(zx):
            zt = [fr[j * bh : (j + 1) * bh, i * bw : (i + 1) * bw].mean() for fr in chan]
            total += 1
            if float(np.std(zt)) >= 0.4:  # luma8 floor
                moving += 1
    return moving / total if total else 0.0


def sample_substrate(window_s: float, poll_s: float) -> dict:
    deadline = time.monotonic() + window_s
    raw: dict[str, list] = {k: [] for k in ARTIFACTS}
    while time.monotonic() < deadline:
        for name, (path, _shape) in ARTIFACTS.items():
            b, mt = _read(path)
            if b is not None:
                # md5 is a change-detection digest here, not a security primitive
                raw[name].append((hashlib.md5(b, usedforsecurity=False).hexdigest(), mt, b))
        time.sleep(poll_s)

    results = {}
    for name, (_path, shape) in ARTIFACTS.items():
        samples = raw[name]
        if not samples:
            results[name] = {"verdict": "ABSENT", "present": False}
            continue
        hashes = [s[0] for s in samples]
        mtimes = [s[1] for s in samples]
        distinct = len(set(hashes))
        age_max = time.time() - min(mtimes)
        age_min = time.time() - max(mtimes)
        spatial_var = temporal_zone_frac = -1.0
        byte_mad = -1.0
        if shape is not None:
            try:
                arrs = [
                    np.frombuffer(s[2], dtype=np.uint8)
                    for s in samples
                    if len(s[2]) == int(np.prod(shape))
                ]
                if len(arrs) >= 2:
                    byte_mad = float(
                        np.mean(
                            [
                                np.mean(np.abs(arrs[i + 1].astype(np.float64) - arrs[i]))
                                for i in range(len(arrs) - 1)
                            ]
                        )
                    )
                    spatial_var = float(np.std(arrs[-1].astype(np.float64)))
                    temporal_zone_frac = _zones_temporal_std(arrs, shape)
            except Exception:
                pass
        results[name] = {
            "present": True,
            "distinct_md5": distinct,
            "samples": len(samples),
            "byte_mad": round(byte_mad, 3),
            "spatial_var": round(spatial_var, 2),
            "temporal_zone_moving_frac": round(temporal_zone_frac, 3),
            "mtime_age_min_s": round(age_min, 2),
            "mtime_age_max_s": round(age_max, 2),
        }
        # Verdict: FROZEN = high spatial + ~zero temporal (the canonical freeze). STALE = producer stopped.
        if name == "drift_currency":
            # per-zone temporal-variance only (whole-frame byte-MAD false-fires via hash-dedup)
            results[name]["verdict"] = (
                "MOVING"
                if temporal_zone_frac >= 0.25
                else ("LEGIT-CALM" if distinct >= 2 else "FROZEN")
            )
        elif shape is not None:
            if age_min > 5.0:
                results[name]["verdict"] = "STALE-PRODUCER"
            elif distinct >= 3 and (byte_mad >= 0.05 or temporal_zone_frac >= 0.1):
                results[name]["verdict"] = "MOVING"
            elif spatial_var > 5.0 and temporal_zone_frac == 0.0:
                results[name]["verdict"] = "FROZEN"
            else:
                results[name]["verdict"] = "LEGIT-CALM" if distinct >= 2 else "FROZEN"
        else:  # jpg liveness by hash
            results[name]["verdict"] = (
                "MOVING" if distinct >= 3 else ("STALE-PRODUCER" if age_min > 5 else "FROZEN")
            )
    return results


def causality(results: dict) -> list[dict]:
    ledger = []
    for up, down in EDGES:
        u, d = results.get(up, {}), results.get(down, {})
        if not (u.get("present") and d.get("present")):
            continue
        u_alive = u.get("distinct_md5", 0) >= 3
        d_alive = d.get("verdict") in ("MOVING", "LEGIT-CALM")
        broken = u_alive and not d_alive and d.get("verdict") == "FROZEN"
        ledger.append(
            {
                "edge": f"{up}->{down}",
                "upstream_distinct": u.get("distinct_md5"),
                "downstream_verdict": d.get("verdict"),
                "culprit": f"{up} ALIVE but {down} FROZEN -> stall at the {down} producer"
                if broken
                else None,
            }
        )
    return ledger


def capture_obs(out: Path, source: str, scene: str, hold_s: float, interval_s: float) -> dict:
    try:
        cfg = json.loads(OBS_CFG.read_text())
        import obsws_python

        client = obsws_python.ReqClient(
            host="localhost",
            port=cfg.get("server_port", 4455),
            password=cfg.get("server_password"),
            timeout=4,
        )
    except Exception as e:
        return {"error": f"obs connect failed: {e}", "verdict": "OBS-UNAVAILABLE"}
    res = {}
    for target, kind in ((source, "source"), (scene, "scene")):
        frames, hashes, grays = [], [], []
        n = max(2, int(hold_s / interval_s))
        ok = True
        for i in range(n):
            try:
                r = client.get_source_screenshot(target, "png", 960, 540, 80)
                data = getattr(r, "image_data", None) or getattr(r, "imageData", None)
                png = base64.b64decode(data.split(",", 1)[1] if data and "," in data else data)
            except Exception as e:
                res[kind] = {"target": target, "error": str(e), "verdict": "CAPTURE-FAILED"}
                ok = False
                break
            p = out / f"obs-{kind}-{i:02d}.png"
            p.write_bytes(png)
            frames.append(p)
            hashes.append(hashlib.sha256(png).hexdigest()[:12])
            from PIL import Image

            grays.append(np.asarray(Image.open(p).convert("L"), dtype=np.float64))
            if i < n - 1:
                time.sleep(interval_s)
        if not ok:
            continue
        deltas = [float(np.mean(np.abs(grays[i + 1] - grays[i]))) for i in range(len(grays) - 1)]
        from PIL import Image

        sheet = np.concatenate(
            [np.asarray(Image.open(p).convert("RGB").resize((320, 180))) for p in frames], axis=1
        )
        Image.fromarray(sheet).save(out / f"obs-{kind}-contact-sheet.png")
        res[kind] = {
            "target": target,
            "frames": len(frames),
            "distinct": len(set(hashes)),
            "mean_consecutive_delta": round(float(np.mean(deltas)) if deltas else 0.0, 2),
            "max_consecutive_delta": round(float(np.max(deltas)) if deltas else 0.0, 2),
            # NOTE: composite delta includes camera/scene motion — NOT drift-isolated. Phase B fixed-POV
            # stations + per-region floors isolate the drift; this is the chain-reaches-YouTube proof.
            "verdict": "MOVING"
            if (deltas and np.mean(deltas) > 0.4 and len(set(hashes)) > 1)
            else "FROZEN",
        }
    return res


def _emit_witness_receipt(args: argparse.Namespace, manifest: dict) -> None:
    """Mint + write a signed AVWitnessReceipt bound to the deployed gamedir bytes.

    Best-effort: a receipt-emission failure must NEVER break the witness's
    primary observe role (the daemon reads the exit code, not the receipt)."""
    try:
        from shared.avsdlc_witness import emit_receipt

        key = Path(args.key_file).read_bytes()
        gamedir = args.gamedir or os.environ.get("HAPAX_AVSDLC_GAMEDIR") or ""
        if not gamedir:
            root = os.environ.get("DARKPLACES_GAME_ROOT", "")
            gamedir = str(Path(root) / "screwm") if root else ""
        receipt = emit_receipt(
            gamedir=gamedir,
            current_json=args.current_json,
            manifest=manifest,
            out_path=args.receipt_out,
            key=key,
            ttl_s=args.receipt_ttl,
            now=time.time(),
        )
        print(
            f"  receipt {receipt.status} obs_moving={receipt.obs_moving} "
            f"hash={receipt.content_hash[:12] or 'ABSENT'} -> {args.receipt_out}"
        )
    except Exception as e:  # noqa: BLE001 — observe path must be unaffected.
        print(f"  receipt-emit FAILED (observe unaffected): {e}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="witness")
    ap.add_argument("--no-drive", action="store_true", default=True)
    ap.add_argument("--substrate-window-s", type=float, default=14.0)
    ap.add_argument("--substrate-poll-s", type=float, default=0.5)
    ap.add_argument("--obs-source", default="DarkPlaces Screwm Media")
    ap.add_argument("--obs-scene", default="Scene")
    ap.add_argument("--hold-s", type=float, default=12.0)
    ap.add_argument("--hold-interval-s", type=float, default=2.0)
    ap.add_argument("--skip-obs", action="store_true")
    ap.add_argument(
        "--emit-receipt",
        action="store_true",
        help="Mint + write a signed AVWitnessReceipt bound to the deployed gamedir bytes.",
    )
    ap.add_argument(
        "--receipt-out",
        default=str(Path.home() / ".cache/hapax/avsdlc/runtime-witness-receipt.json"),
    )
    ap.add_argument("--receipt-ttl", type=float, default=1800.0)
    ap.add_argument(
        "--gamedir",
        default=None,
        help="Deployed gamedir root to content-hash (default: $DARKPLACES_GAME_ROOT/screwm).",
    )
    ap.add_argument(
        "--current-json",
        default=str(Path.home() / ".cache/hapax/source-activation/current.json"),
    )
    ap.add_argument(
        "--key-file",
        default=os.environ.get("HAPAX_COORD_KEY_FILE")
        or str(Path.home() / ".cache/hapax/coord/grant-key"),
    )
    args = ap.parse_args()

    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out = OUT_ROOT / args.label / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out.mkdir(parents=True, exist_ok=True)

    substrate = sample_substrate(args.substrate_window_s, args.substrate_poll_s)
    edges = causality(substrate)
    obs = (
        {}
        if args.skip_obs
        else capture_obs(out, args.obs_source, args.obs_scene, args.hold_s, args.hold_interval_s)
    )

    frozen = [k for k, v in substrate.items() if v.get("verdict") == "FROZEN"]
    stale = [k for k, v in substrate.items() if v.get("verdict") == "STALE-PRODUCER"]
    culprits = [e["culprit"] for e in edges if e.get("culprit")]
    overall = "PASS" if not (frozen or stale or culprits) else "FAIL"

    manifest = {
        "started_at_utc": started,
        "label": args.label,
        "no_drive": args.no_drive,
        "obs_capture_target": args.obs_source,
        "substrate": substrate,
        "causality": edges,
        "obs": obs,
        "frozen": frozen,
        "stale": stale,
        "culprits": culprits,
        "overall": overall,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))

    if args.emit_receipt:
        _emit_witness_receipt(args, manifest)

    print(f"== CNS WITNESS [{args.label}] {overall} ==  -> {out}")
    for k, v in substrate.items():
        if v.get("present"):
            print(
                f"  {k:16s} {v['verdict']:14s} distinct={v.get('distinct_md5')} "
                f"spatial_var={v.get('spatial_var')} temporal_moving_frac={v.get('temporal_zone_moving_frac')} "
                f"age={v.get('mtime_age_min_s')}s"
            )
        else:
            print(f"  {k:16s} {v['verdict']}")
    for e in edges:
        print(
            f"  edge {e['edge']:24s} {e['downstream_verdict']}"
            + (f"  CULPRIT: {e['culprit']}" if e.get("culprit") else "")
        )
    for kind, v in (obs or {}).items():
        if isinstance(v, dict):
            print(
                f"  obs:{kind:7s} {v.get('verdict', '?'):14s} distinct={v.get('distinct')} mean_delta={v.get('mean_consecutive_delta')}"
            )
    if culprits:
        print("  !! CAUSALITY:", "; ".join(culprits))
    return 2 if overall == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
