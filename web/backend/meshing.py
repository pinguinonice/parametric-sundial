"""Turn the sundial geometry into a printable STL.

Three watertight solids are emitted into one binary STL:

* the gnomon "roller" surface  -- the 24 x 183 point grid, closed into a tube
  around the polar axis and capped at the two solstice ends;
* the gnomon axis rod          -- a thin cylinder along P0[0]..P1[0];
* the reading scale ring       -- a rectangular-section band following minScale.

Coordinates from the model are in metres (ENU); everything here is scaled to
millimetres so a radius of 0.1 m prints as a 100 mm ring.
"""

from __future__ import annotations

import io

import numpy as np
from stl import mesh as stl_mesh


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n else v


def _quad(a, b, c, d):
    """Two CCW triangles for quad a-b-c-d."""
    return [[a, b, c], [a, c, d]]


def _mesh_from_tris(tris) -> stl_mesh.Mesh:
    tris = np.asarray(tris, dtype=np.float32)
    data = np.zeros(len(tris), dtype=stl_mesh.Mesh.dtype)
    m = stl_mesh.Mesh(data, remove_empty_areas=False)
    m.vectors = tris
    return m


# --- individual solids ------------------------------------------------------

def _roller(grid_mm: np.ndarray) -> list:
    """grid_mm: (H, S, 3).  Wrap in H (24 -> full turn), cap the S ends."""
    H, S, _ = grid_mm.shape
    tris = []
    for h in range(H):
        h2 = (h + 1) % H
        for s in range(S - 1):
            tris += _quad(grid_mm[h, s], grid_mm[h2, s],
                          grid_mm[h2, s + 1], grid_mm[h, s + 1])
    # caps: fan from the ring centroid at each solstice end
    for s, flip in ((0, True), (S - 1, False)):
        ring = grid_mm[:, s, :]
        c = ring.mean(axis=0)
        for h in range(H):
            h2 = (h + 1) % H
            tri = [c, ring[h], ring[h2]]
            if flip:
                tri = [c, ring[h2], ring[h]]
            tris.append(tri)
    return tris


def _cylinder(p0, p1, radius, segments=48) -> list:
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    axis = _unit(p1 - p0)
    ref = np.array([1.0, 0.0, 0.0])
    if abs(np.dot(axis, ref)) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    u = _unit(np.cross(axis, ref))
    v = np.cross(axis, u)
    ang = np.linspace(0, 2 * np.pi, segments, endpoint=False)
    ring0 = np.array([p0 + radius * (np.cos(a) * u + np.sin(a) * v) for a in ang])
    ring1 = np.array([p1 + radius * (np.cos(a) * u + np.sin(a) * v) for a in ang])
    tris = []
    for i in range(segments):
        j = (i + 1) % segments
        tris += _quad(ring0[i], ring0[j], ring1[j], ring1[i])
    for i in range(segments):          # end caps
        j = (i + 1) % segments
        tris.append([p0, ring0[j], ring0[i]])
        tris.append([p1, ring1[i], ring1[j]])
    return tris


def _scale_ring(min_scale_mm: np.ndarray, width, thickness) -> list:
    pts = np.asarray(min_scale_mm, float)
    center = pts.mean(axis=0)
    normal = _unit(np.cross(pts[1] - pts[0], pts[len(pts) // 3] - pts[0]))
    hw, ht = width / 2.0, thickness / 2.0
    # rectangular cross-section: 4 corner loops around the whole circle
    radial = np.array([_unit(p - center) for p in pts])
    loops = [
        pts + hw * radial + ht * normal,   # outer-top
        pts + hw * radial - ht * normal,   # outer-bottom
        pts - hw * radial - ht * normal,   # inner-bottom
        pts - hw * radial + ht * normal,   # inner-top
    ]
    n = len(pts)
    tris = []
    for k in range(4):
        a, b = loops[k], loops[(k + 1) % 4]
        for i in range(n):
            j = (i + 1) % n
            tris += _quad(a[i], a[j], b[j], b[i])
    return tris


# --- public API -----------------------------------------------------------

def build_stl(geom: dict, scale_mm: float = 1000.0,
              rod_ratio: float = 0.018, ring_width_ratio: float = 0.05,
              ring_thick_ratio: float = 0.012) -> bytes:
    """geom: dict from geometry.generate().  Returns binary STL bytes."""
    grid = geom["grid"]
    if grid is None:
        raise ValueError("model did not return a full gnomon grid; "
                         "try a different latitude or season")

    s = float(scale_mm)
    grid_mm = np.asarray(grid, float) * s
    min_scale_mm = geom["minScale"] * s
    p0 = np.asarray(geom["P0"][0], float) * s
    p1 = np.asarray(geom["P1"][0], float) * s

    ring_radius = float(np.linalg.norm(geom["minScale"][0]) * s) or s
    rod_r = rod_ratio * ring_radius
    ring_w = ring_width_ratio * ring_radius
    ring_t = ring_thick_ratio * ring_radius

    parts = [
        _mesh_from_tris(_roller(grid_mm)),
        _mesh_from_tris(_cylinder(p0, p1, rod_r)),
        _mesh_from_tris(_scale_ring(min_scale_mm, ring_w, ring_t)),
    ]
    combined = stl_mesh.Mesh(np.concatenate([p.data for p in parts]))

    buf = io.BytesIO()
    combined.save("sundial.stl", fh=buf, mode=stl_mesh.stl.Mode.BINARY)
    return buf.getvalue()
