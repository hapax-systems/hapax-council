#!/usr/bin/env python3
"""screwm-meet-video-in — capture the Google Meet participant <video> via Chrome
CDP and write it into a CNS ward live-texture slot (clean BSP 32-bit path).

Grabs the largest playing <video> in the Meet tab (the remote participant), fits
it letterboxed into the ward's 1280x720 BGRA buffer at ~FPS. Repurposes a camera
ward slot for the duration of the call.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import sys
import urllib.request

import numpy as np
import websockets
from PIL import Image

CDP = "http://127.0.0.1:9222"
OUT = os.environ.get(
    "MEET_VIDEO_OUT", "/dev/shm/hapax-compositor/quake-live-cam-c920-overhead.bgra"
)
W, H = 1280, 720
FPS = float(os.environ.get("MEET_VIDEO_FPS", "12"))

JS = r"""
(function(){
  // Exclude the self-view (the operator's own camera = the CNS/DarkPlaces feed) by
  // track label; the remote participant's track label is a peer UUID. Avoids the loop.
  const isLocal=l=>/darkplaces|youtube0|logitech|c920|brio|hd pro|webcam|ultralite|m8 |yeti|respeaker/i.test(l||'');
  let vids=[...document.querySelectorAll('video')].filter(v=>{
    if(!(v.videoWidth>0 && v.videoHeight>0 && !v.paused && v.readyState>=2)) return false;
    const tr=(v.srcObject&&v.srcObject.getVideoTracks&&v.srcObject.getVideoTracks()[0])||{};
    return !isLocal(tr.label);
  });
  if(!vids.length) return "";
  vids.sort((a,b)=>{const ra=a.getBoundingClientRect(),rb=b.getBoundingClientRect();
    return (rb.width*rb.height)-(ra.width*ra.height);});
  const v=vids[0];
  const c=document.createElement('canvas');c.width=1280;c.height=720;
  const x=c.getContext('2d');x.fillStyle='#000';x.fillRect(0,0,1280,720);
  const ar=v.videoWidth/v.videoHeight, car=1280/720; let w,h;
  if(ar>car){w=1280;h=1280/ar;}else{h=720;w=720*ar;}
  x.drawImage(v,(1280-w)/2,(720-h)/2,w,h);
  return c.toDataURL('image/jpeg',0.6);
})()
"""


def find_ws():
    tabs = json.load(urllib.request.urlopen(CDP + "/json", timeout=5))
    for t in tabs:
        if t.get("type") == "page" and "meet.google.com" in (t.get("url") or ""):
            return t["webSocketDebuggerUrl"]
    return None


def write_bgra(data_url: str) -> None:
    if not data_url or not data_url.startswith("data:image"):
        return
    raw = base64.b64decode(data_url.split(",", 1)[1])
    im = Image.open(io.BytesIO(raw)).convert("RGB").resize((W, H))
    a = np.asarray(im, dtype=np.uint8)
    bgra = np.dstack([a[:, :, 2], a[:, :, 1], a[:, :, 0], np.full((H, W), 255, np.uint8)])
    tmp = OUT + ".tmp"
    bgra.tofile(tmp)
    os.replace(tmp, OUT)


async def run():
    ws_url = find_ws()
    if not ws_url:
        print("no Meet tab found", file=sys.stderr)
        return
    print(f"capturing Meet participant -> {OUT} @ {FPS}fps", file=sys.stderr)
    async with websockets.connect(ws_url, max_size=None) as ws:
        mid = 0
        await ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
        interval = 1.0 / FPS
        frames = 0
        while True:
            mid += 1
            await ws.send(
                json.dumps(
                    {
                        "id": mid + 100,
                        "method": "Runtime.evaluate",
                        "params": {"expression": JS, "returnByValue": True},
                    }
                )
            )
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == mid + 100:
                    val = (msg.get("result", {}).get("result", {}) or {}).get("value")
                    if val:
                        write_bgra(val)
                        frames += 1
                        if frames % 60 == 0:
                            print(f"  {frames} frames", file=sys.stderr)
                    break
            await asyncio.sleep(interval)


if __name__ == "__main__":
    while True:
        try:
            asyncio.run(run())
        except Exception as e:  # reconnect on tab nav / drop
            print(f"reconnect after: {e}", file=sys.stderr)
        import time

        time.sleep(2)
