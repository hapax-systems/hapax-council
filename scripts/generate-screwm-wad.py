#!/usr/bin/env python3
"""Generate a Quake WAD2 file with procedural stone/metal textures.

WAD2 format:
  Header: magic "WAD2", num_entries, dir_offset
  Entry directory: 32 bytes each (offset, disksize, size, type, compression, name[16])
  Texture data: MIPTEX header + 4 mipmap levels + palette
"""

import struct
import subprocess
from pathlib import Path

TEXTURES = {
    "city4_2": {"color": (140, 110, 80), "noise": 25},
    "ground1_6": {"color": (90, 85, 75), "noise": 20},
    "sky4": {"color": (40, 35, 45), "noise": 10},
    "metal5_2": {"color": (120, 115, 110), "noise": 15},
}

TEX_SIZE = 64


def generate_pixel_data(color, noise, width, height, seed=0):
    """Generate noisy stone/metal texture with visible surface detail."""
    import random
    import math

    random.seed(seed)
    pixels = bytearray()
    palette = []

    for i in range(256):
        t = i / 255.0
        r = max(0, min(255, int(color[0] * (0.4 + t * 0.6))))
        g = max(0, min(255, int(color[1] * (0.4 + t * 0.6))))
        b = max(0, min(255, int(color[2] * (0.4 + t * 0.6))))
        palette.extend([r, g, b])

    for y in range(height):
        for x in range(width):
            # Multi-octave value noise for organic stone texture
            v = 0.5
            freq = 1.0
            amp = 0.5
            for _ in range(4):
                sx = x * freq / width * 4
                sy = y * freq / height * 4
                cell_val = math.sin(sx * 12.9898 + sy * 78.233) * 43758.5453
                cell_val = cell_val - math.floor(cell_val)
                v += (cell_val - 0.5) * amp
                freq *= 2.0
                amp *= 0.5

            # Add random grain
            v += random.uniform(-noise / 255.0, noise / 255.0)

            idx = max(10, min(245, int(v * 255)))
            pixels.append(idx)

    return bytes(pixels), bytes(palette)


def make_miptex(name, width, height, pixels, palette):
    """Create MIPTEX structure with 4 mipmap levels."""
    name_bytes = name.encode("ascii")[:15].ljust(16, b"\x00")

    mip0 = pixels
    mip1 = bytearray()
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            mip1.append(pixels[y * width + x])
    mip1 = bytes(mip1)

    mip2 = bytearray()
    for y in range(0, height, 4):
        for x in range(0, width, 4):
            mip2.append(pixels[y * width + x])
    mip2 = bytes(mip2)

    mip3 = bytearray()
    for y in range(0, height, 8):
        for x in range(0, width, 8):
            mip3.append(pixels[y * width + x])
    mip3 = bytes(mip3)

    header_size = 40
    off0 = header_size
    off1 = off0 + len(mip0)
    off2 = off1 + len(mip1)
    off3 = off2 + len(mip2)

    header = struct.pack(
        "<16sII4I",
        name_bytes,
        width,
        height,
        off0,
        off1,
        off2,
        off3,
    )

    return header + mip0 + mip1 + mip2 + mip3


def write_wad(textures_data, output_path):
    """Write WAD2 file."""
    entries = []
    data_parts = []
    data_offset = 12

    for name, (miptex, _palette) in textures_data.items():
        entries.append(
            {
                "name": name,
                "offset": data_offset,
                "size": len(miptex),
            }
        )
        data_parts.append(miptex)
        data_offset += len(miptex)

    dir_offset = data_offset

    with open(output_path, "wb") as f:
        f.write(b"WAD2")
        f.write(struct.pack("<ii", len(entries), dir_offset))

        for part in data_parts:
            f.write(part)

        for entry in entries:
            name_bytes = entry["name"].encode("ascii")[:15].ljust(16, b"\x00")
            f.write(
                struct.pack(
                    "<iiiBBh16s",
                    entry["offset"],
                    entry["size"],
                    entry["size"],
                    0x44,
                    0,
                    0,
                    name_bytes,
                )
            )


def main():
    textures_data = {}
    for name, params in TEXTURES.items():
        pixels, palette = generate_pixel_data(
            params["color"], params["noise"], TEX_SIZE, TEX_SIZE, seed=hash(name)
        )
        miptex = make_miptex(name, TEX_SIZE, TEX_SIZE, pixels, palette)
        textures_data[name] = (miptex, palette)
        print(f"  {name}: {TEX_SIZE}x{TEX_SIZE}, {len(miptex)} bytes")

    output_dir = Path(__file__).parent.parent / "assets" / "quake" / "maps"
    output_dir.mkdir(parents=True, exist_ok=True)
    wad_path = output_dir / "screwm.wad"
    write_wad(textures_data, wad_path)
    print(f"WAD: {wad_path} ({wad_path.stat().st_size} bytes)")

    dp_wad = Path.home() / ".darkplaces" / "screwm" / "screwm.wad"
    import shutil

    shutil.copy2(wad_path, dp_wad)
    print(f"Deployed to {dp_wad}")


if __name__ == "__main__":
    main()
