#!/usr/bin/env python3
"""Generate the current AoA/tetrix anchor as Quake MDL files.

The source authority is the authored 3D AoA in hapax-visual, not the older
flat Sierpinski overlay. The lattice and media sphere are separate models:
Quake/DarkPlaces owns their spatial placement, while the Hapax live texture
hook updates the sphere skin from the YouTube/media producer.

Each sub-tetrahedron is generated with its own 4 vertices to avoid
shared-vertex ambiguity in the MDL format's flat shading model.
"""

import math
import struct
from pathlib import Path

AOA_GEOMETRY_REVISION = "aoa-regular-tetrix-v5-iteration-scale-perfect-fit-oarb"
DEPTH = 4
AOA_LEAF_FACE_EDGE_UNITS = 48
AOA_ITERATION_SCALE_MULTIPLIER = 1.3
BASE_SCALE = AOA_LEAF_FACE_EDGE_UNITS * (2**DEPTH)
SCALE = BASE_SCALE * AOA_ITERATION_SCALE_MULTIPLIER
ATTENDANT_SPHERE_RADIUS = math.sqrt(6.0) / 12.0
AOA_SPHERE_MODEL_SCALE = 1.0
ATTENDANT_SPHERE_CLEARANCE_RATIO = 1.0
MEDIA_SPHERE_SEGMENTS = 64
MEDIA_SPHERE_RINGS = 32
AOA_FACE_ATLAS_COLUMNS = 32
AOA_FACE_ATLAS_CELL_SIZE = 64
AOA_SKIN_W = AOA_FACE_ATLAS_COLUMNS * AOA_FACE_ATLAS_CELL_SIZE
AOA_SKIN_H = AOA_FACE_ATLAS_COLUMNS * AOA_FACE_ATLAS_CELL_SIZE
MEDIA_SPHERE_SKIN_W = 2048
MEDIA_SPHERE_SKIN_H = 1024

AOA_INNER_VOID_EDGE_PAIRS = [
    (0, 1),
    (0, 2),
    (0, 3),
    (1, 2),
    (1, 3),
    (2, 3),
]

# Convex-hull faces of the central octahedral void, indexed into the six
# edge-midpoint vertices above. This is the volume that must contain the OARB.
AOA_INNER_VOID_FACES = [
    (0, 3, 1),
    (5, 1, 3),
    (2, 1, 0),
    (2, 5, 1),
    (4, 3, 5),
    (4, 0, 3),
    (4, 5, 2),
    (4, 2, 0),
]

ROOT_EDGE = 1.0
ROOT_INRADIUS = ROOT_EDGE * math.sqrt(6.0) / 12.0
ROOT_BASE_RADIUS = ROOT_EDGE / math.sqrt(3.0)

# Regular tetrahedron in Quake axes, centered on its incenter. This is the
# exact pyramid used for the finite Sierpinski/tetrix approximation.
AOA_ROOT_MODEL_VERTICES = [
    [-0.5, -ROOT_BASE_RADIUS / 2.0, -ROOT_INRADIUS],
    [0.5, -ROOT_BASE_RADIUS / 2.0, -ROOT_INRADIUS],
    [0.0, ROOT_BASE_RADIUS, -ROOT_INRADIUS],
    [0.0, 0.0, ROOT_INRADIUS * 3.0],
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


def source_to_quake(v):
    """Return Quake-space coordinates for the authored regular tetrix root."""
    return list(v)


def triangle_area(a, b, c):
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    cross = [
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0],
    ]
    return 0.5 * math.sqrt(sum(component * component for component in cross))


def tetrahedron_incenter(corners):
    """Return the incenter of a tetrahedron.

    The OARB is the AoA's inner object of attention, so the lattice origin is
    the incenter rather than an arbitrary model centroid. This lets the media
    sphere remain perfectly inscribed in the first central octahedral void.
    """
    weights = []
    for idx in range(4):
        opposite = [corner for corner_idx, corner in enumerate(corners) if corner_idx != idx]
        weights.append(triangle_area(*opposite))

    total = sum(weights)
    if total <= 0:
        return [0.0, 0.0, 0.0]
    return [sum(weights[idx] * corners[idx][axis] for idx in range(4)) / total for axis in range(3)]


def aoa_root_quake_vertices():
    return [source_to_quake(v) for v in AOA_ROOT_MODEL_VERTICES]


def aoa_inner_center():
    return tetrahedron_incenter(aoa_root_quake_vertices())


def transform_vertices(verts):
    center = aoa_inner_center()
    transformed = []
    for v in verts:
        q = source_to_quake(v)
        transformed.append([q[i] - center[i] for i in range(3)])
    return transformed


def media_sphere_mesh(radius: float, segments: int, rings: int):
    """Return a UV sphere using equirectangular media coordinates."""
    verts = []
    uvs = []
    faces = []

    for lat in range(rings + 1):
        v = lat / rings
        phi = math.pi * v
        sin_phi = math.sin(phi)
        cos_phi = math.cos(phi)
        for lon in range(segments + 1):
            u = lon / segments
            theta = 2.0 * math.pi * u
            # Source coordinates follow the AoA convention above: X lateral,
            # Y room depth, source -Z upward. The texture center (u=.5, v=.5)
            # faces negative Quake Y, which is the default review approach.
            x = radius * sin_phi * math.sin(theta)
            y = radius * sin_phi * math.cos(theta)
            z = -radius * cos_phi
            verts.append([x, y, z])
            uvs.append((u, v))

    stride = segments + 1
    for lat in range(rings):
        for lon in range(segments):
            a = lat * stride + lon
            b = a + 1
            c = a + stride
            d = c + 1
            if lat > 0:
                faces.append((a, c, b))
            if lat < rings - 1:
                faces.append((b, c, d))

    return [source_to_quake(v) for v in verts], faces, uvs


def compose_aoa_parts(depth: int):
    """Tetrix core only; the solid live-media sphere is a separate model."""
    return tetrix_tetrahedra(depth)


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


def aoa_face_count(depth: int = DEPTH) -> int:
    return 4 * (4**depth)


def aoa_face_atlas_rows(face_count: int) -> int:
    return math.ceil(face_count / AOA_FACE_ATLAS_COLUMNS)


def aoa_face_cell_uvs(face_index: int):
    col = face_index % AOA_FACE_ATLAS_COLUMNS
    row = face_index // AOA_FACE_ATLAS_COLUMNS
    pad = 0.18
    return [
        ((col + 0.50) / AOA_FACE_ATLAS_COLUMNS, (row + pad) / AOA_FACE_ATLAS_COLUMNS),
        ((col + pad) / AOA_FACE_ATLAS_COLUMNS, (row + 1.0 - pad) / AOA_FACE_ATLAS_COLUMNS),
        (
            (col + 1.0 - pad) / AOA_FACE_ATLAS_COLUMNS,
            (row + 1.0 - pad) / AOA_FACE_ATLAS_COLUMNS,
        ),
    ]


def flatten_aoa_surface_mesh(parts):
    """Duplicate vertices per face so every fractal face owns an atlas cell."""
    all_verts = []
    all_faces = []
    all_uvs = []
    face_index = 0
    for verts, faces in parts:
        for face in faces:
            offset = len(all_verts)
            all_verts.extend([list(verts[face[0]]), list(verts[face[1]]), list(verts[face[2]])])
            all_faces.append((offset, offset + 1, offset + 2))
            all_uvs.extend(aoa_face_cell_uvs(face_index))
            face_index += 1
    return all_verts, all_faces, all_uvs


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


def aoa_inner_void_vertices():
    root = transform_vertices(AOA_ROOT_MODEL_VERTICES)
    return [midpoint(root[start], root[end]) for start, end in AOA_INNER_VOID_EDGE_PAIRS]


def distance_from_point_to_face(point, face, verts):
    n = face_normal(verts[face[0]], verts[face[1]], verts[face[2]])
    origin = verts[face[0]]
    return abs(sum(n[axis] * (point[axis] - origin[axis]) for axis in range(3)))


def aoa_inner_void_inradius():
    """Minimum distance from the centered OARB origin to the tetrix void."""
    verts = aoa_inner_void_vertices()
    center = [0.0, 0.0, 0.0]
    return min(distance_from_point_to_face(center, face, verts) for face in AOA_INNER_VOID_FACES)


def derived_aoa_model_scale():
    """AoA scale required to fit the OARB inside the central void."""
    return (
        ATTENDANT_SPHERE_RADIUS
        * AOA_SPHERE_MODEL_SCALE
        * ATTENDANT_SPHERE_CLEARANCE_RATIO
        / aoa_inner_void_inradius()
    )


def aoa_skin_pixels(width: int, height: int) -> bytes:
    if width != AOA_SKIN_W or height != AOA_SKIN_H:
        raise ValueError("AoA skin dimensions must match the per-face atlas contract")

    pixels = bytearray()
    face_count = aoa_face_count()
    rows = aoa_face_atlas_rows(face_count)
    for y in range(height):
        for x in range(width):
            col = x // AOA_FACE_ATLAS_CELL_SIZE
            row = y // AOA_FACE_ATLAS_CELL_SIZE
            face_index = row * AOA_FACE_ATLAS_COLUMNS + col
            local_x = x % AOA_FACE_ATLAS_CELL_SIZE
            local_y = y % AOA_FACE_ATLAS_CELL_SIZE
            edge = local_x in (0, AOA_FACE_ATLAS_CELL_SIZE - 1) or local_y in (
                0,
                AOA_FACE_ATLAS_CELL_SIZE - 1,
            )
            bary_line = (
                abs(local_x - AOA_FACE_ATLAS_CELL_SIZE // 2) < 2
                or abs(local_y - AOA_FACE_ATLAS_CELL_SIZE + local_x) < 2
                or abs(local_y - local_x) < 2
            )
            if face_index >= face_count or row >= rows:
                bright = 0
            elif edge or bary_line:
                bright = 238
            else:
                bright = 168 + ((face_index * 13 + local_x * 3 + local_y * 5) % 62)
            pixels.append(min(255, bright))
    return bytes(pixels)


def media_sphere_skin_pixels(width: int, height: int) -> bytes:
    """Placeholder only; live BGRA upload replaces this skin at runtime."""
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            equator = abs(y - height * 0.5) < 2
            meridian = x % max(1, width // 16) < 2
            if x < 2 or y < 2 or x >= width - 2 or y >= height - 2:
                pixels.append(245)
            elif equator or meridian:
                pixels.append(236)
            elif (x * 7 + y * 11) % 29 < 5:
                pixels.append(198)
            else:
                pixels.append(74 + ((x * 5 + y * 3) % 62))
    return bytes(pixels)


def write_mdl(
    verts,
    faces,
    output_path: Path,
    scale: float,
    *,
    skin_width: int,
    skin_height: int,
    skin_pixels: bytes,
    uvs=None,
):
    num_verts = len(verts)
    num_tris = len(faces)
    if len(skin_pixels) != skin_width * skin_height:
        raise ValueError("skin pixel buffer does not match skin dimensions")
    if uvs is None:
        uvs = [(0.0, 0.0)] * num_verts
    if len(uvs) != num_verts:
        raise ValueError("uv count does not match vertex count")

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

    with open(output_path, "wb") as f:
        f.write(b"IDPO")
        f.write(struct.pack("<i", 6))
        f.write(struct.pack("<fff", *mdl_scale))
        f.write(struct.pack("<fff", *mdl_origin))
        f.write(struct.pack("<f", scale * 1.2))
        f.write(struct.pack("<fff", 0, 0, 0))
        f.write(struct.pack("<i", 1))
        f.write(struct.pack("<i", skin_width))
        f.write(struct.pack("<i", skin_height))
        f.write(struct.pack("<i", num_verts))
        f.write(struct.pack("<i", num_tris))
        f.write(struct.pack("<i", 1))
        f.write(struct.pack("<i", 0))
        f.write(struct.pack("<i", 0))
        f.write(struct.pack("<f", scale))

        f.write(struct.pack("<i", 0))
        f.write(skin_pixels)

        for u, v in uvs:
            s = int(max(0, min(skin_width - 1, round(u * (skin_width - 1)))))
            t = int(max(0, min(skin_height - 1, round(v * (skin_height - 1)))))
            f.write(struct.pack("<i", 1))
            f.write(struct.pack("<i", s))
            f.write(struct.pack("<i", t))

        for face in faces:
            f.write(struct.pack("<i", 1))
            f.write(struct.pack("<iii", face[0], face[1], face[2]))

        f.write(struct.pack("<i", 0))
        min_packed = [1, 1, 1]
        f.write(struct.pack("<BBBB", *min_packed, 0))
        max_packed = [254, 254, 254]
        f.write(struct.pack("<BBBB", *max_packed, 0))
        frame_name = output_path.stem.encode("ascii")[:15].ljust(16, b"\x00")
        f.write(frame_name)

        for i, pv in enumerate(packed_verts):
            f.write(struct.pack("<BBBB", pv[0], pv[1], pv[2], normal_indices[i]))


def main():
    parts = compose_aoa_parts(DEPTH)
    verts, faces, uvs = flatten_aoa_surface_mesh(parts)
    verts = transform_vertices(verts)
    sphere_verts, sphere_faces, sphere_uvs = media_sphere_mesh(
        ATTENDANT_SPHERE_RADIUS,
        MEDIA_SPHERE_SEGMENTS,
        MEDIA_SPHERE_RINGS,
    )
    print(
        f"{AOA_GEOMETRY_REVISION} depth {DEPTH}: "
        f"lattice {len(verts)} vertices/{len(faces)} triangles; "
        f"media sphere {len(sphere_verts)} vertices/{len(sphere_faces)} triangles"
    )

    output_dir = Path(__file__).parent.parent / "assets" / "quake" / "models"
    output_dir.mkdir(parents=True, exist_ok=True)
    aoa_path = output_dir / "aoa.mdl"
    sphere_path = output_dir / "aoa_sphere.mdl"
    write_mdl(
        verts,
        faces,
        aoa_path,
        SCALE,
        skin_width=AOA_SKIN_W,
        skin_height=AOA_SKIN_H,
        skin_pixels=aoa_skin_pixels(AOA_SKIN_W, AOA_SKIN_H),
        uvs=uvs,
    )
    write_mdl(
        sphere_verts,
        sphere_faces,
        sphere_path,
        SCALE,
        skin_width=MEDIA_SPHERE_SKIN_W,
        skin_height=MEDIA_SPHERE_SKIN_H,
        skin_pixels=media_sphere_skin_pixels(MEDIA_SPHERE_SKIN_W, MEDIA_SPHERE_SKIN_H),
        uvs=sphere_uvs,
    )
    print(f"Written {aoa_path} ({aoa_path.stat().st_size} bytes)")
    print(f"Written {sphere_path} ({sphere_path.stat().st_size} bytes)")

    dp_dir = Path.home() / ".darkplaces" / "screwm" / "progs"
    dp_dir.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copy2(aoa_path, dp_dir / "aoa.mdl")
    shutil.copy2(sphere_path, dp_dir / "aoa_sphere.mdl")
    print(f"Deployed to {dp_dir / 'aoa.mdl'}")
    print(f"Deployed to {dp_dir / 'aoa_sphere.mdl'}")


if __name__ == "__main__":
    main()
