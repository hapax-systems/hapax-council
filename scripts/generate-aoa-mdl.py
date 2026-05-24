#!/usr/bin/env python3
"""Generate a Sierpinski tetrahedron as a Quake MDL file.

Depth 2 = 16 tetrahedra, 64 vertices, 64 triangles. Depth 2 chosen over
depth 3 because the Quake MDL format packs vertices as 8-bit integers —
depth 3's 256 sub-tetrahedra are too small to survive quantization.

Each sub-tetrahedron is generated with its own 4 vertices to avoid
shared-vertex ambiguity in the MDL format's flat shading model.
"""

import math
import struct
from pathlib import Path

DEPTH = 2
SCALE = 80

# Quake's 162-entry anorms table (subset — full table from r_shared.c)
ANORMS = [
    (-0.525731, 0.000000, 0.850651),
    (-0.442863, 0.238856, 0.864188),
    (-0.295242, 0.000000, 0.955423),
    (-0.309017, 0.500000, 0.809017),
    (-0.162460, 0.262866, 0.951056),
    (0.000000, 0.000000, 1.000000),
    (0.000000, 0.850651, 0.525731),
    (-0.147621, 0.716567, 0.681718),
    (0.147621, 0.716567, 0.681718),
    (0.000000, 0.525731, 0.850651),
    (0.309017, 0.500000, 0.809017),
    (0.525731, 0.000000, 0.850651),
    (0.295242, 0.000000, 0.955423),
    (0.442863, 0.238856, 0.864188),
    (0.162460, 0.262866, 0.951056),
    (-0.681718, 0.147621, 0.716567),
    (-0.809017, 0.309017, 0.500000),
    (-0.587785, 0.425325, 0.688191),
    (-0.850651, 0.525731, 0.000000),
    (-0.864188, 0.442863, 0.238856),
    (-0.716567, 0.681718, 0.147621),
    (-0.688191, 0.587785, 0.425325),
    (-0.500000, 0.809017, 0.309017),
    (-0.238856, 0.864188, 0.442863),
    (-0.425325, 0.688191, 0.587785),
    (-0.716567, 0.681718, -0.147621),
    (-0.500000, 0.809017, -0.309017),
    (-0.525731, 0.850651, 0.000000),
    (0.000000, 0.850651, -0.525731),
    (-0.238856, 0.864188, -0.442863),
    (0.000000, 0.955423, -0.295242),
    (-0.262866, 0.951056, -0.162460),
    (0.000000, 1.000000, 0.000000),
    (0.000000, 0.955423, 0.295242),
    (-0.262866, 0.951056, 0.162460),
    (0.238856, 0.864188, 0.442863),
    (0.262866, 0.951056, 0.162460),
    (0.500000, 0.809017, 0.309017),
    (0.238856, 0.864188, -0.442863),
    (0.262866, 0.951056, -0.162460),
    (0.500000, 0.809017, -0.309017),
    (0.850651, 0.525731, 0.000000),
    (0.716567, 0.681718, 0.147621),
    (0.716567, 0.681718, -0.147621),
    (0.525731, 0.850651, 0.000000),
    (0.425325, 0.688191, 0.587785),
    (0.864188, 0.442863, 0.238856),
    (0.688191, 0.587785, 0.425325),
    (0.809017, 0.309017, 0.500000),
    (0.681718, 0.147621, 0.716567),
    (0.587785, 0.425325, 0.688191),
    (0.955423, 0.295242, 0.000000),
    (1.000000, 0.000000, 0.000000),
    (0.951056, 0.162460, 0.262866),
    (0.850651, -0.525731, 0.000000),
    (0.955423, -0.295242, 0.000000),
    (0.864188, -0.442863, 0.238856),
    (0.951056, -0.162460, 0.262866),
    (0.809017, -0.309017, 0.500000),
    (0.681718, -0.147621, 0.716567),
    (0.850651, 0.000000, 0.525731),
    (0.864188, 0.442863, -0.238856),
    (0.809017, 0.309017, -0.500000),
    (0.951056, 0.162460, -0.262866),
    (0.525731, 0.000000, -0.850651),
    (0.681718, 0.147621, -0.716567),
    (0.809017, -0.309017, -0.500000),
    (0.864188, -0.442863, -0.238856),
    (0.951056, -0.162460, -0.262866),
    (0.147621, 0.716567, -0.681718),
    (0.309017, 0.500000, -0.809017),
    (0.425325, 0.688191, -0.587785),
    (0.442863, 0.238856, -0.864188),
    (0.587785, 0.425325, -0.688191),
    (0.688191, 0.587785, -0.425325),
    (-0.147621, 0.716567, -0.681718),
    (-0.309017, 0.500000, -0.809017),
    (0.000000, 0.525731, -0.850651),
    (-0.525731, 0.000000, -0.850651),
    (-0.442863, 0.238856, -0.864188),
    (-0.295242, 0.000000, -0.955423),
    (-0.162460, 0.262866, -0.951056),
    (0.000000, 0.000000, -1.000000),
    (0.295242, 0.000000, -0.955423),
    (0.162460, 0.262866, -0.951056),
    (-0.442863, -0.238856, -0.864188),
    (-0.309017, -0.500000, -0.809017),
    (-0.162460, -0.262866, -0.951056),
    (0.000000, -0.850651, -0.525731),
    (-0.147621, -0.716567, -0.681718),
    (0.147621, -0.716567, -0.681718),
    (0.000000, -0.525731, -0.850651),
    (0.309017, -0.500000, -0.809017),
    (0.442863, -0.238856, -0.864188),
    (0.162460, -0.262866, -0.951056),
    (0.238856, -0.864188, -0.442863),
    (0.500000, -0.809017, -0.309017),
    (0.262866, -0.951056, -0.162460),
    (0.000000, -1.000000, 0.000000),
    (0.000000, -0.955423, -0.295242),
    (-0.262866, -0.951056, -0.162460),
    (0.000000, -0.955423, 0.295242),
    (-0.262866, -0.951056, 0.162460),
    (-0.500000, -0.809017, 0.309017),
    (-0.238856, -0.864188, 0.442863),
    (-0.262866, -0.951056, 0.162460),
    (-0.500000, -0.809017, -0.309017),
    (-0.238856, -0.864188, -0.442863),
    (-0.850651, -0.525731, 0.000000),
    (-0.716567, -0.681718, 0.147621),
    (-0.716567, -0.681718, -0.147621),
    (-0.525731, -0.850651, 0.000000),
    (-0.688191, -0.587785, -0.425325),
    (-0.587785, -0.425325, -0.688191),
    (-0.425325, -0.688191, -0.587785),
    (-0.864188, -0.442863, -0.238856),
    (-0.809017, -0.309017, -0.500000),
    (-0.681718, -0.147621, -0.716567),
    (-0.955423, -0.295242, 0.000000),
    (-1.000000, 0.000000, 0.000000),
    (-0.951056, -0.162460, -0.262866),
    (-0.809017, -0.309017, 0.500000),
    (-0.864188, -0.442863, 0.238856),
    (-0.951056, -0.162460, 0.262866),
    (-0.681718, -0.147621, 0.716567),
    (-0.850651, 0.000000, 0.525731),
    (-0.955423, 0.295242, 0.000000),
    (-0.951056, 0.162460, 0.262866),
    (-0.864188, 0.442863, -0.238856),
    (-0.951056, 0.162460, -0.262866),
    (-0.809017, 0.309017, -0.500000),
    (-0.681718, 0.147621, -0.716567),
    (-0.850651, 0.000000, -0.525731),
    (-0.688191, 0.587785, -0.425325),
    (-0.587785, 0.425325, -0.688191),
    (-0.425325, 0.688191, -0.587785),
    (-0.587785, -0.425325, 0.688191),
    (-0.688191, -0.587785, 0.425325),
    (-0.425325, -0.688191, 0.587785),
    (0.147621, -0.716567, 0.681718),
    (0.309017, -0.500000, 0.809017),
    (0.442863, -0.238856, 0.864188),
    (0.162460, -0.262866, 0.951056),
    (0.238856, -0.864188, 0.442863),
    (0.500000, -0.809017, 0.309017),
    (0.716567, -0.681718, 0.147621),
    (0.525731, -0.850651, 0.000000),
    (0.262866, -0.951056, 0.162460),
    (0.688191, -0.587785, 0.425325),
    (0.587785, -0.425325, 0.688191),
    (0.425325, -0.688191, 0.587785),
    (-0.147621, -0.716567, 0.681718),
    (-0.309017, -0.500000, 0.809017),
    (0.000000, -0.525731, 0.850651),
    (0.000000, -0.850651, 0.525731),
    (0.716567, -0.681718, -0.147621),
    (0.688191, -0.587785, -0.425325),
    (0.587785, -0.425325, -0.688191),
    (0.425325, -0.688191, -0.587785),
    (0.525731, 0.000000, 0.850651),
    (0.681718, -0.147621, -0.716567),
]


def find_normal_index(nx: float, ny: float, nz: float) -> int:
    best_dot = -2.0
    best_idx = 0
    for i, (ax, ay, az) in enumerate(ANORMS):
        d = nx * ax + ny * ay + nz * az
        if d > best_dot:
            best_dot = d
            best_idx = i
    return best_idx


def sierpinski_tetrahedron(depth: int):
    # Regular tetrahedron vertices (unit sphere inscribed)
    s = 1.0
    v0 = [0, s, 0]
    v1 = [s * 0.9428, -s * 0.3333, 0]
    v2 = [-s * 0.4714, -s * 0.3333, s * 0.8165]
    v3 = [-s * 0.4714, -s * 0.3333, -s * 0.8165]

    if depth == 0:
        return [
            ([list(v0), list(v1), list(v2), list(v3)], [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)])
        ]

    result = []
    corners = [v0, v1, v2, v3]
    for corner in corners:
        sub = sierpinski_tetrahedron(depth - 1)
        for verts, faces in sub:
            scaled = []
            for v in verts:
                scaled.append([(v[i] + corner[i]) / 2.0 for i in range(3)])
            result.append((scaled, faces))
    return result


def flatten_mesh(parts):
    all_verts = []
    all_faces = []
    offset = 0
    for verts, faces in parts:
        all_verts.extend(verts)
        for f in faces:
            all_faces.append((f[0] + offset, f[1] + offset, f[2] + offset))
        offset += len(verts)
    return all_verts, all_faces


def face_normal(v0, v1, v2):
    e1 = [v1[i] - v0[i] for i in range(3)]
    e2 = [v2[i] - v0[i] for i in range(3)]
    nx = e1[1] * e2[2] - e1[2] * e2[1]
    ny = e1[2] * e2[0] - e1[0] * e2[2]
    nz = e1[0] * e2[1] - e1[1] * e2[0]
    ln = math.sqrt(nx * nx + ny * ny + nz * nz)
    if ln > 0:
        return nx / ln, ny / ln, nz / ln
    return 0.0, 0.0, 1.0


def write_mdl(verts, faces, output_path: Path, scale: float):
    num_verts = len(verts)
    num_tris = len(faces)

    mins = [min(v[i] for v in verts) for i in range(3)]
    maxs = [max(v[i] for v in verts) for i in range(3)]

    mdl_scale = [
        (maxs[i] - mins[i]) / 254.0 * scale if maxs[i] != mins[i] else 0.01 for i in range(3)
    ]
    mdl_origin = [mins[i] * scale for i in range(3)]

    # Per-vertex normal: average face normals for each vertex
    vert_normals = [[0.0, 0.0, 0.0] for _ in range(num_verts)]
    for f in faces:
        fn = face_normal(verts[f[0]], verts[f[1]], verts[f[2]])
        for vi in f:
            for i in range(3):
                vert_normals[vi][i] += fn[i]

    normal_indices = []
    for vn in vert_normals:
        ln = math.sqrt(sum(x * x for x in vn))
        if ln > 0:
            vn = [x / ln for x in vn]
        normal_indices.append(find_normal_index(vn[0], vn[1], vn[2]))

    packed_verts = []
    for v in verts:
        pv = []
        for i in range(3):
            if maxs[i] != mins[i]:
                byte_val = int((v[i] - mins[i]) / (maxs[i] - mins[i]) * 254) + 1
            else:
                byte_val = 128
            pv.append(max(1, min(254, byte_val)))
        packed_verts.append(pv)

    skin_w, skin_h = 16, 16

    with open(output_path, "wb") as f:
        f.write(b"IDPO")
        f.write(struct.pack("<i", 6))
        f.write(struct.pack("<fff", *mdl_scale))
        f.write(struct.pack("<fff", *mdl_origin))
        f.write(struct.pack("<f", scale * 1.2))
        f.write(struct.pack("<fff", 0, 0, 0))
        f.write(struct.pack("<i", 1))
        f.write(struct.pack("<i", skin_w))
        f.write(struct.pack("<i", skin_h))
        f.write(struct.pack("<i", num_verts))
        f.write(struct.pack("<i", num_tris))
        f.write(struct.pack("<i", 1))
        f.write(struct.pack("<i", 0))
        f.write(struct.pack("<i", 0))
        f.write(struct.pack("<f", scale))

        f.write(struct.pack("<i", 0))
        # 16x16 warm gold skin
        for y in range(skin_h):
            for x in range(skin_w):
                bright = 200 + ((x + y) % 3) * 18
                f.write(bytes([min(255, bright)]))

        for _ in range(num_verts):
            f.write(struct.pack("<i", 1))
            f.write(struct.pack("<i", 0))
            f.write(struct.pack("<i", 0))

        for face in faces:
            f.write(struct.pack("<i", 1))
            f.write(struct.pack("<iii", face[0], face[1], face[2]))

        f.write(struct.pack("<i", 0))
        min_packed = [1, 1, 1]
        f.write(struct.pack("<BBBB", *min_packed, 0))
        max_packed = [254, 254, 254]
        f.write(struct.pack("<BBBB", *max_packed, 0))
        name = b"aoa\x00" + b"\x00" * 12
        f.write(name)

        for i, pv in enumerate(packed_verts):
            f.write(struct.pack("<BBBB", pv[0], pv[1], pv[2], normal_indices[i]))


def main():
    parts = sierpinski_tetrahedron(DEPTH)
    verts, faces = flatten_mesh(parts)
    print(f"Sierpinski depth {DEPTH}: {len(verts)} vertices, {len(faces)} triangles")

    output_dir = Path(__file__).parent.parent / "assets" / "quake" / "models"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "aoa.mdl"
    write_mdl(verts, faces, output_path, SCALE)
    print(f"Written {output_path} ({output_path.stat().st_size} bytes)")

    dp_dir = Path.home() / ".darkplaces" / "screwm" / "progs"
    dp_dir.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copy2(output_path, dp_dir / "aoa.mdl")
    print(f"Deployed to {dp_dir / 'aoa.mdl'}")


if __name__ == "__main__":
    main()
