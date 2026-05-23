#!/usr/bin/env python3
"""Generate a Sierpinski tetrahedron as a Quake MDL file.

The MDL format stores vertex-animated models. We generate a single-frame
static model of a depth-3 Sierpinski tetrahedron (64 small tetrahedra).

Quake MDL format (IDPO):
  Header: magic, version, scale, origin, radius, eye_pos, num_skins,
          skin_width, skin_height, num_verts, num_tris, num_frames,
          sync_type, flags, size
  Skins: flat color (1x1 pixel skin)
  ST coords: texture coordinates per vertex
  Triangles: vertex indices + facesfront flag
  Frames: simple frame with vertex positions (packed as bytes)
"""

import math
import struct
from pathlib import Path

DEPTH = 3
SCALE = 64  # Quake units, ~2 meters


def sierpinski_tetrahedron(depth: int) -> list[tuple[list, list]]:
    """Generate Sierpinski tetrahedron vertices and faces at given depth."""
    # Unit tetrahedron vertices
    v0 = [1, 1, 1]
    v1 = [1, -1, -1]
    v2 = [-1, 1, -1]
    v3 = [-1, -1, 1]

    base_verts = [v0, v1, v2, v3]
    base_faces = [
        (0, 1, 2),
        (0, 1, 3),
        (0, 2, 3),
        (1, 2, 3),
    ]

    if depth == 0:
        return [(base_verts, base_faces)]

    result = []
    mid = lambda a, b: [(a[i] + b[i]) / 2 for i in range(3)]

    centers = [
        v0,
        v1,
        v2,
        v3,
    ]

    for center in centers:
        sub = sierpinski_tetrahedron(depth - 1)
        for verts, faces in sub:
            scaled = []
            for v in verts:
                scaled.append([(v[i] + center[i]) / 2 for i in range(3)])
            result.append((scaled, faces))

    return result


def flatten_mesh(parts: list[tuple[list, list]]) -> tuple[list, list]:
    """Combine all tetrahedra into a single mesh."""
    all_verts = []
    all_faces = []
    offset = 0

    for verts, faces in parts:
        all_verts.extend(verts)
        for f in faces:
            all_faces.append((f[0] + offset, f[1] + offset, f[2] + offset))
        offset += len(verts)

    return all_verts, all_faces


def compute_normals(verts, faces):
    """Compute per-vertex normals (average of face normals)."""
    normals = [[0, 0, 0] for _ in verts]

    for f in faces:
        v0 = verts[f[0]]
        v1 = verts[f[1]]
        v2 = verts[f[2]]
        e1 = [v1[i] - v0[i] for i in range(3)]
        e2 = [v2[i] - v0[i] for i in range(3)]
        n = [
            e1[1] * e2[2] - e1[2] * e2[1],
            e1[2] * e2[0] - e1[0] * e2[2],
            e1[0] * e2[1] - e1[1] * e2[0],
        ]
        for vi in f:
            for i in range(3):
                normals[vi][i] += n[i]

    for i, n in enumerate(normals):
        length = math.sqrt(sum(x * x for x in n))
        if length > 0:
            normals[i] = [x / length for x in n]
        else:
            normals[i] = [0, 0, 1]

    return normals


# Quake's 162 normal table — index 0 is a reasonable default
ANORMS_TABLE = [
    (-0.525731, 0.000000, 0.850651),
    (-0.442863, 0.238856, 0.864188),
    (-0.295242, 0.000000, 0.955423),
]


def find_normal_index(normal):
    """Find closest Quake normal index (simplified — use index 0)."""
    return 0


def write_mdl(verts, faces, normals, output_path: Path, scale: float):
    """Write a Quake MDL file."""
    num_verts = len(verts)
    num_tris = len(faces)

    # Compute bounding box
    mins = [min(v[i] for v in verts) for i in range(3)]
    maxs = [max(v[i] for v in verts) for i in range(3)]

    # Scale and origin for packing vertices into bytes (0-255)
    mdl_scale = [
        (maxs[i] - mins[i]) / 255.0 if maxs[i] != mins[i] else 1.0 / 255.0 for i in range(3)
    ]
    mdl_origin = [mins[i] * scale for i in range(3)]
    mdl_scale_scaled = [s * scale for s in mdl_scale]

    # Pack vertices as bytes
    packed_verts = []
    for v in verts:
        pv = []
        for i in range(3):
            if maxs[i] != mins[i]:
                byte_val = int((v[i] - mins[i]) / (maxs[i] - mins[i]) * 255)
            else:
                byte_val = 128
            pv.append(max(0, min(255, byte_val)))
        packed_verts.append(pv)

    with open(output_path, "wb") as f:
        # Header
        f.write(b"IDPO")  # magic
        f.write(struct.pack("<i", 6))  # version
        f.write(struct.pack("<fff", *mdl_scale_scaled))  # scale
        f.write(struct.pack("<fff", *mdl_origin))  # origin
        f.write(struct.pack("<f", scale * 1.5))  # bounding radius
        f.write(struct.pack("<fff", 0, 0, 0))  # eye position
        f.write(struct.pack("<i", 1))  # num_skins
        f.write(struct.pack("<i", 4))  # skin_width
        f.write(struct.pack("<i", 4))  # skin_height
        f.write(struct.pack("<i", num_verts))  # num_verts
        f.write(struct.pack("<i", num_tris))  # num_tris
        f.write(struct.pack("<i", 1))  # num_frames
        f.write(struct.pack("<i", 0))  # sync_type
        f.write(struct.pack("<i", 0))  # flags
        f.write(struct.pack("<f", scale))  # size

        # Skin data (4x4 flat grey)
        f.write(struct.pack("<i", 0))  # skin type (single)
        f.write(bytes([128] * 16))  # 4x4 grey pixels

        # ST coordinates (all zeros — no real texture)
        for _ in range(num_verts):
            f.write(struct.pack("<i", 1))  # onseam
            f.write(struct.pack("<i", 0))  # s
            f.write(struct.pack("<i", 0))  # t

        # Triangles
        for face in faces:
            f.write(struct.pack("<i", 1))  # facesfront
            f.write(struct.pack("<iii", face[0], face[1], face[2]))

        # Frame (single frame)
        f.write(struct.pack("<i", 0))  # frame type (simple)

        # Bounding box min vertex
        min_packed = [0, 0, 0]
        f.write(struct.pack("<BBBB", *min_packed, 0))

        # Bounding box max vertex
        max_packed = [255, 255, 255]
        f.write(struct.pack("<BBBB", *max_packed, 0))

        # Frame name (16 bytes, null-padded)
        name = b"aoa\x00" + b"\x00" * 12
        f.write(name)

        # Vertex data
        for i, pv in enumerate(packed_verts):
            ni = find_normal_index(normals[i])
            f.write(struct.pack("<BBBB", pv[0], pv[1], pv[2], ni))


def main():
    parts = sierpinski_tetrahedron(DEPTH)
    verts, faces = flatten_mesh(parts)
    normals = compute_normals(verts, faces)

    print(f"Sierpinski tetrahedron depth {DEPTH}: {len(verts)} vertices, {len(faces)} triangles")

    output_dir = Path(__file__).parent.parent / "assets" / "quake" / "models"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "aoa.mdl"
    write_mdl(verts, faces, normals, output_path, SCALE)
    print(f"Written {output_path} ({output_path.stat().st_size} bytes)")

    # Also copy to DarkPlaces game directory
    dp_dir = Path.home() / ".darkplaces" / "screwm" / "progs"
    dp_dir.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copy2(output_path, dp_dir / "aoa.mdl")
    print(f"Copied to {dp_dir / 'aoa.mdl'}")


if __name__ == "__main__":
    main()
