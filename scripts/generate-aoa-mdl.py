#!/usr/bin/env python3
"""Generate the current AoA/tetrix anchor as a Quake MDL file.

The source authority is the authored 3D AoA in hapax-visual, not the older
flat Sierpinski overlay. The model keeps a recursive tetrix core and adds the
attendant sphere as physical ring geometry so the anchor reads as the newer
contained AoA object inside DarkPlaces.

Each sub-tetrahedron is generated with its own 4 vertices to avoid
shared-vertex ambiguity in the MDL format's flat shading model.
"""

import math
import struct
from pathlib import Path

AOA_GEOMETRY_REVISION = "aoa-tetrix-v2"
DEPTH = 3
SCALE = 92
ATTENDANT_SPHERE_RADIUS = 1.10
ATTENDANT_SPHERE_RING_WIDTH = 0.026
ATTENDANT_SPHERE_SEGMENTS = 72

# Mirrors hapax-logos/crates/hapax-visual/src/aoa_panes.rs::AOA_ROOT_MODEL_VERTICES.
AOA_ROOT_MODEL_VERTICES = [
    [-0.58, -0.44, 0.34],
    [0.58, -0.44, 0.34],
    [0.0, 0.60, 0.34],
    [0.0, -0.095, -0.62],
]

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


def midpoint(a, b):
    return [(a[i] + b[i]) * 0.5 for i in range(3)]


def tetrix_tetrahedra(depth: int, corners=None):
    """Recursive AoA tetrix core using the current authored root vertices."""
    if corners is None:
        corners = [list(v) for v in AOA_ROOT_MODEL_VERTICES]

    if depth == 0:
        v0, v1, v2, v3 = corners
        return [
            (
                [list(v0), list(v1), list(v2), list(v3)],
                [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)],
            )
        ]

    result = []
    for idx, corner in enumerate(corners):
        child_corners = [midpoint(corner, other) for other in corners]
        child_corners[idx] = list(corner)
        result.extend(tetrix_tetrahedra(depth - 1, child_corners))
    return result


def sphere_ring(axis: str, radius: float, width: float, segments: int):
    """Return a broad ring strip for the AoA attendant sphere."""
    verts = []
    faces = []

    for i in range(segments):
        theta = 2.0 * math.pi * i / segments
        c = math.cos(theta)
        s = math.sin(theta)
        if axis == "xy":
            center = [radius * c, radius * s, 0.0]
            outward = [c, s, 0.0]
        elif axis == "xz":
            center = [radius * c, 0.0, radius * s]
            outward = [c, 0.0, s]
        elif axis == "yz":
            center = [0.0, radius * c, radius * s]
            outward = [0.0, c, s]
        else:
            raise ValueError(f"unknown sphere ring axis: {axis}")
        verts.append([center[j] + outward[j] * width for j in range(3)])
        verts.append([center[j] - outward[j] * width for j in range(3)])

    for i in range(segments):
        a = i * 2
        b = ((i + 1) % segments) * 2
        faces.append((a, b, a + 1))
        faces.append((a + 1, b, b + 1))

    return verts, faces


def compose_aoa_parts(depth: int):
    """Tetrix core plus three great-circle sphere rings."""
    parts = tetrix_tetrahedra(depth)
    for axis in ("xy", "xz", "yz"):
        parts.append(
            sphere_ring(
                axis,
                ATTENDANT_SPHERE_RADIUS,
                ATTENDANT_SPHERE_RING_WIDTH,
                ATTENDANT_SPHERE_SEGMENTS,
            )
        )
    return parts


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
    parts = compose_aoa_parts(DEPTH)
    verts, faces = flatten_mesh(parts)
    print(
        f"{AOA_GEOMETRY_REVISION} depth {DEPTH} + attendant sphere: "
        f"{len(verts)} vertices, {len(faces)} triangles"
    )

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
