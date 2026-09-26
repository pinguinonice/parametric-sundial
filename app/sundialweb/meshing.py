"""Build printable meshes (dial body, two rollers, stand) from a Design."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import trimesh
from shapely.geometry import Polygon
from matplotlib.textpath import TextPath
from matplotlib.font_manager import FontProperties

from .design import Design, RollerProfile

_FONT = FontProperties(family="DejaVu Sans", weight="bold")


@dataclass
class BodyGeometry:
    """Print-related dimensions, derived from the scale radius R."""
    R: float
    rim: float = 2.5             # rim outside the reading circle
    plate_t: float = 4.0         # vertical plate thickness
    p_exp: float = 2.0           # dish profile exponent (slope at rim)
    q_hub: float = 0.12          # fraction of the half-span that stays a full dish
    q_depth: float = 0.62        # ... beyond which the wings stay at tip depth
    q_width: float = 0.95        # ... beyond which the wings stay at tip width
    d_tip: float = 0.08          # remaining dish depth at the wing tips
    t_tip: float = 0.45          # plate thickness at the tips relative to plate_t
    w_tip: float = 9.0           # radial width of the wing tips
    tip_margin_deg: float = 5.0  # crescent extends beyond the last mark
    rho_core: float = 4.0        # inner radius of the plate under the hub
    pin_r: float = 4.0           # roller / stand pin radius
    pin_len: float = 9.0
    socket_depth: float = 9.8
    clearance: float = 0.15
    neck_h: float = 5.0
    collar_h: float = 3.0
    hub_len: float = 22.0
    thread_pitch: float = 2.5    # roller screws into the hub: coarse rounded thread
    thread_depth: float = 1.0
    thread_clearance: float = 0.3
    engrave: float = 0.6
    tick_zone: float = 8.0
    text_h: float = 6.0
    stem_r: float = 10.0
    fin_t: float = 6.0
    base_t: float = 4.0

    @classmethod
    def for_radius(cls, R: float) -> "BodyGeometry":
        s = R / 75.0
        return cls(R=R,
                   rim=max(3.0, 3.5 * s),
                   plate_t=max(3.0, 4.0 * s),
                   w_tip=max(7.0, 9.0 * s),
                   tick_zone=max(6.0, 8.0 * s),
                   text_h=min(12.0, max(4.0, 6.0 * s)),
                   stem_r=max(8.0, 10.0 * s),
                   fin_t=max(5.0, 6.0 * s))

    @property
    def R_out(self):
        return self.R + self.rim


# --------------------------------------------------------------------------
# helpers

def dms(value: float, pos: str, neg: str) -> str:
    """48.7758 -> 48\u00b046\u203233\u2033 N"""
    a = abs(value)
    d = int(a)
    m = int((a - d) * 60)
    sec = int(round(((a - d) * 60 - m) * 60))
    if sec == 60:
        sec, m = 0, m + 1
    if m == 60:
        m, d = 0, d + 1
    return f"{d}\u00b0{m:02d}\u2032{sec:02d}\u2033 {pos if value >= 0 else neg}"


def location_text(lat: float, lon: float) -> str:
    return f"{dms(lat, 'N', 'S')}   {dms(lon, 'E', 'W')}"


def _smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _frame_matrix(X, Y, Z, origin):
    M = np.eye(4)
    M[:3, 0], M[:3, 1], M[:3, 2], M[:3, 3] = X, Y, Z, origin
    return M


def _text_polygons(text: str, height, scale=None):
    tp = TextPath((0, 0), text, size=1.0, prop=_FONT)
    geom = None
    for poly in tp.to_polygons():
        if len(poly) < 3:
            continue
        ring = Polygon(poly)
        if not ring.is_valid:
            ring = ring.buffer(0)
        geom = ring if geom is None else geom.symmetric_difference(ring)
    if geom is None or geom.is_empty:
        return []
    minx, miny, maxx, maxy = geom.bounds
    from shapely.affinity import translate, scale as sscale
    if scale is None:
        scale = height / max(maxy - miny, 1e-6)
        cx, cy = 0.5 * (minx + maxx), 0.5 * (miny + maxy)
    else:
        # fixed scale: centre horizontally on the glyph, vertically on the digit height
        cx, cy = 0.5 * (minx + maxx), 0.5 * _cap_height()
    geom = sscale(translate(geom, -cx, -cy), scale, scale, origin=(0, 0))
    polys = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
    return [p for p in polys if p.area > 1e-6]


def arc_text_cutters(surf, d, text: str, height: float, rho: float, psi_deg: float, depth: float):
    """Engraving cutters for `text` laid along the ring at radius rho,
    centred on psi_deg, one cutter per character with its own local frame,
    so the letters follow the dished surface instead of a flat chord."""
    scale = height / _cap_height()
    bar_l = _path_bounds(TextPath((0, 0), "|", size=1.0, prop=_FONT))[0]

    def pen(prefix):   # pen position after `prefix`, spaces included
        return _path_bounds(TextPath((0, 0), prefix + "|", size=1.0, prop=_FONT))[2] - (bar_l + _bar_w())

    total = pen(text) * scale
    cutters = []
    for i, ch in enumerate(text):
        if ch.strip() == "":
            continue
        gb = _path_bounds(TextPath((0, 0), ch, size=1.0, prop=_FONT))
        mesh = text_mesh(ch, None, depth, scale=scale)
        if mesh is None:
            continue
        x_c = (pen(text[:i]) + 0.5 * (gb[0] + gb[2])) * scale - total / 2.0   # glyph centre from the string centre
        dpsi = math.degrees(x_c / rho) * d.omega
        mesh.apply_transform(surf.local_frame(rho, psi_deg + dpsi))
        cutters.append(mesh)
    return cutters


def flat_arc_glyphs(text: str, height: float, centre, radius: float, theta_c: float = 0.0):
    """Shapely polygons of `text` laid along a circle of `radius` about
    `centre`, on its lower side (angles measured from -y towards +x), the
    string centred on theta_c, glyph tops towards the centre.  Reads left
    to right for a viewer standing on the -y side."""
    from shapely.affinity import rotate as _rot, translate as _tr
    scale = height / _cap_height()
    bar_l = _path_bounds(TextPath((0, 0), "|", size=1.0, prop=_FONT))[0]

    def pen(prefix):
        return _path_bounds(TextPath((0, 0), prefix + "|", size=1.0, prop=_FONT))[2] - (bar_l + _bar_w())

    total = pen(text) * scale
    out = []
    for i, ch in enumerate(text):
        if ch.strip() == "":
            continue
        gb = _path_bounds(TextPath((0, 0), ch, size=1.0, prop=_FONT))
        x_c = (pen(text[:i]) + 0.5 * (gb[0] + gb[2])) * scale - total / 2.0
        th = theta_c + x_c / radius
        px, py = centre[0] + radius * math.sin(th), centre[1] - radius * math.cos(th)
        for poly in _text_polygons(ch, None, scale=scale):
            out.append(_tr(_rot(poly, math.degrees(th), origin=(0, 0)), px, py))
    return out, total


def _path_bounds(tp):
    v = tp.vertices
    if len(v) == 0:
        return (0.0, 0.0, 0.0, 0.0)
    return (float(v[:, 0].min()), float(v[:, 1].min()), float(v[:, 0].max()), float(v[:, 1].max()))


def _bar_w():
    b = _path_bounds(TextPath((0, 0), "|", size=1.0, prop=_FONT))
    return b[2] - b[0]


def _cap_height():
    tp = TextPath((0, 0), "0", size=1.0, prop=_FONT)
    b = _path_bounds(tp)
    return b[3] - b[1]


def text_mesh(text: str, height, depth: float, above: float = 3.0, scale: float = None):
    """Extruded text lying in the XY plane, spanning z in [-depth, above]."""
    parts = []
    for poly in _text_polygons(text, height, scale):
        m = trimesh.creation.extrude_polygon(poly, depth + above)
        m.apply_translation([0, 0, -depth])
        parts.append(m)
    return trimesh.util.concatenate(parts) if parts else None


def _helical_thread(r_core, depth, pitch, length, fade=(1.5, 0.8), fade_to="core",
                    sections=72, per_pitch=16):
    """Screw body: a core of radius r_core carrying one rounded helical ridge
    of height `depth` (profile 0.5 (1 + cos)), z from 0 to length.  The ridge
    fades out over `fade` mm at the two ends, either into the core (a male
    thread with a soft tip) or into the crest (a female cutter whose mouth
    opens up).  Rounded flanks and the generous clearance used with it print
    without any calibration."""
    n_z = int(length / (pitch / per_pitch)) + 2
    zs = np.linspace(0.0, length, n_z)
    verts, faces = [], []
    for z in zs:
        ramp = 1.0
        if fade[0] > 0:
            ramp = min(ramp, z / fade[0])
        if fade[1] > 0:
            ramp = min(ramp, (length - z) / fade[1])
        ramp = min(max(ramp, 0.0), 1.0)
        for k in range(sections):
            th = 2 * math.pi * k / sections
            u = (z / pitch - th / (2 * math.pi)) % 1.0
            ridge = 0.5 * (1.0 + math.cos(2 * math.pi * u))
            if fade_to == "core":
                r = r_core + depth * ramp * ridge
            else:
                r = r_core + depth * (ramp * ridge + (1.0 - ramp))
            verts.append((r * math.cos(th), r * math.sin(th), z))
    for i in range(n_z - 1):
        for k in range(sections):
            a, b = i * sections + k, i * sections + (k + 1) % sections
            c, dd = a + sections, b + sections
            faces += [[a, c, dd], [a, dd, b]]
    c0 = len(verts); verts.append((0.0, 0.0, 0.0))
    c1 = len(verts); verts.append((0.0, 0.0, length))
    base = (n_z - 1) * sections
    for k in range(sections):
        faces.append([c0, (k + 1) % sections, k])
        faces.append([c1, base + k, base + (k + 1) % sections])
    m = trimesh.Trimesh(vertices=np.array(verts), faces=np.array(faces), process=True)
    trimesh.repair.fix_normals(m)
    if m.volume < 0:
        m.invert()
    return m


def _revolve(profile_rz, sections=128):
    """Closed surface of revolution from an (r, z) polyline that starts and
    ends on the axis."""
    m = trimesh.creation.revolve(np.asarray(profile_rz, dtype=float), sections=sections)
    if m.volume < 0:
        m.invert()
    return m


def _largest_body(mesh):
    """Booleans on engraved text can leave a detached sliver the size of a
    letter counter; keep the main body only."""
    parts = mesh.split(only_watertight=False)
    if len(parts) <= 1:
        return mesh
    return max(parts, key=lambda m: abs(m.volume))


def _cyl(radius, height, sections=96):
    return trimesh.creation.cylinder(radius=radius, height=height, sections=sections)


# --------------------------------------------------------------------------
# plate surface

class PlateSurface:
    """Height field of the crescent plate in the dial frame.

    The silhouette (a crescent) and the dish under the winter marks are
    styled parametrically.  Which parts of that plate may exist, and how
    deep they must be, is derived from the sun rays themselves: for every
    sunlit quarter hour of the winter half-years a ray from the reading mark
    towards the sun is traced across the dial.  The plate must lie below
    every ray (the dish) or above it (a thin blade near the scale plane), or
    it is cut away.  This reproduces the twisted wings of the original
    Bernhardt dial: dished under the winter hours, flat blades at the tips.
    """

    def __init__(self, d: Design, g: BodyGeometry, D0: float, delta_tol_deg: float = 2.5):
        self.d, self.g, self.D0 = d, g, D0
        self.psi_mid = d.psi_mid
        self.psi_half = d.psi_half + g.tip_margin_deg
        R_out = g.R_out
        self.u_R = (R_out - g.R) / R_out
        self.u_h = (R_out - self.r_hub) / R_out
        self.t_blade = g.plate_t * g.t_tip
        self.delta_tol = delta_tol_deg
        self._build_field()

    @property
    def r_hub(self):
        return hub_radius(self.g, self.d)

    # ---- styling -------------------------------------------------------
    def _rel(self, psi):
        return np.abs((np.asarray(psi, dtype=float) - self.psi_mid)) / self.psi_half

    def rho_in_design(self, psi):
        """Styled inner edge of the crescent (before the ray constraints)."""
        g = self.g
        rel = self._rel(psi)
        b = _smoothstep((rel - g.q_hub) / (g.q_width - g.q_hub)) ** 0.8
        rho = g.rho_core + (g.R_out - g.w_tip - g.rho_core) * b
        # leaf-shaped tips: over the last ~2.6 tip widths of arc the inner
        # edge sweeps out to the rim along a superellipse, so the horn ends
        # in a rounded point instead of a flat cut
        q = (g.w_tip * 2.6) / (math.radians(self.psi_half) * g.R_out)
        q = min(max(q, 0.03), 0.3)
        tip = np.clip((rel - (1.0 - q)) / q, 0.0, 1.0)
        round_w = (np.clip(1.0 - tip ** 2.4, 0.0, 1.0)) ** 0.55
        rounded = g.R_out - 2.0 - (g.w_tip - 2.0) * round_w
        return np.where(rel > 1.0 - q, np.maximum(rho, rounded), rho)

    def _S(self, u):
        return 1.0 - (1.0 - np.clip(u, 0.0, 1.0)) ** self.g.p_exp

    def dish_z(self, rho):
        """Styled full-depth dish, rotationally symmetric, 0 at the reading circle."""
        u = (self.g.R_out - np.asarray(rho, dtype=float)) / self.g.R_out
        num = self._S(u) - self._S(self.u_R)
        den = self._S(self.u_h) - self._S(self.u_R)
        return -self.D0 * num / den

    # ---- ray constraints ------------------------------------------------
    def _winter_rays(self):
        from . import solar as _solar
        from .design import _sun_at
        d, p, R = self.d, self.d.params, self.d.R
        t0 = _solar.dt_to_unix(_solar.datetime(p.year, 1, 1, tzinfo=_solar.timezone.utc))
        days = np.arange(0, 366, 1.0)
        hours = np.arange(d.hour_first, d.hour_last + 1e-9, 0.25)
        tt = (t0 + days[:, None] * 86400.0 + (hours[None, :] - p.utc_offset_h) * 3600.0).ravel()
        s_enu = _solar.sun_vector_enu(tt, p.lat, p.lon)
        s_all = _sun_at(tt, p)
        # rays from below the equatorial plane (winter half, in the dial frame)
        # sun at least 2 degrees above the horizon (lower readings are not usable)
        use = (s_enu[:, 2] > math.sin(math.radians(2.0))) & (s_all[:, 2] < 0.0)
        tt, s = tt[use], s_all[use]
        depth_deg = np.rad2deg(np.arcsin(-np.clip(s[:, 2], -1, 1)))  # angle below the plane
        T = np.mod(tt + p.utc_offset_h * 3600.0, 86400.0) / 3600.0
        psi = np.deg2rad(d.psi_of_time(T))
        mark = np.stack([R * np.sin(psi), R * np.cos(psi), np.zeros_like(psi)], -1)
        # parameter of the closest approach to the polar axis
        sxy = s[:, :2]
        lam_star = -(mark[:, :2] * sxy).sum(1) / np.maximum((sxy * sxy).sum(1), 1e-12)
        return mark, s, depth_deg, lam_star

    def _build_field(self):
        """Rasterise the winter rays and decide the plate height per cell.

        For every ray two segments matter: before it passes the polar axis
        it runs from its own reading mark across the plate, so the plate
        must stay below it ("own" floor).  After the axis it crosses the far
        wing; there the plate must be either below it (dish) or above it
        (blade).  Rays within `delta_tol` of the equatorial plane are ignored
        for the blade ceiling: a thin blade in the scale plane inevitably
        shadows those few equinox days, as on the original dials.
        """
        g, R = self.g, self.d.R
        d_rho, d_az = 0.5, 0.5
        self.rho_grid = np.arange(2.0, g.R_out + d_rho, d_rho)
        self.az_grid = np.arange(self.psi_mid - self.psi_half - 1.0,
                                 self.psi_mid + self.psi_half + 1.0 + d_az, d_az)
        n_r, n_a = len(self.rho_grid), len(self.az_grid)
        floor_own = np.full((n_r, n_a), np.inf)
        floor_cross = np.full((n_r, n_a), np.inf)
        ceil_cross = np.full((n_r, n_a), -np.inf)
        mark, s, depth, lam_star = self._winter_rays()
        if len(depth):
            lam = np.arange(3.0, 2.3 * R, 0.4)      # skip the first 3 mm at the mark
            chunk = 400
            for i0 in range(0, len(depth), chunk):
                m, sv = mark[i0:i0 + chunk], s[i0:i0 + chunk]
                dp, ls = depth[i0:i0 + chunk], lam_star[i0:i0 + chunk]
                pts = m[:, None, :] + lam[None, :, None] * sv[:, None, :]
                rho = np.hypot(pts[..., 0], pts[..., 1])
                az = np.rad2deg(np.arctan2(pts[..., 0], pts[..., 1]))
                az = self.psi_mid + ((az - self.psi_mid + 180.0) % 360.0 - 180.0)
                z = pts[..., 2]
                ir = np.rint((rho - self.rho_grid[0]) / d_rho).astype(int)
                ia = np.rint((az - self.az_grid[0]) / d_az).astype(int)
                ok = (ir >= 0) & (ir < n_r) & (ia >= 0) & (ia < n_a) & (z <= 0.0)
                own = ok & (lam[None, :] < ls[:, None])
                cross = ok & ~own
                np.minimum.at(floor_own, (ir[own], ia[own]), z[own])
                np.minimum.at(floor_cross, (ir[cross], ia[cross]), z[cross])
                strong = cross & (dp[:, None] > self.delta_tol)
                np.maximum.at(ceil_cross, (ir[strong], ia[strong]), z[strong])

        def erode(f, op):
            out = f.copy()
            for di in (-2, -1, 0, 1, 2):
                for dj in (-2, -1, 0, 1, 2):
                    out = op(out, np.roll(np.roll(f, di, axis=0), dj, axis=1))
            return out
        floor_own = erode(floor_own, np.minimum)
        floor_cross = erode(floor_cross, np.minimum)
        ceil_cross = erode(ceil_cross, np.maximum)
        has_cross = np.isfinite(floor_cross)
        RHO = self.rho_grid[:, None] * np.ones((1, n_a))
        dish = self.dish_z(RHO)
        t_b = self.t_blade

        # Both base surfaces are built smooth by construction and fitted
        # under the rays column by column, instead of cell by cell, so no
        # rasterisation texture reaches the printed part.
        need_own = floor_own - 0.3
        need = np.minimum(need_own, floor_cross - 1.0)
        n_cells_per_deg = 1.0 / d_az

        def upper_envelope_1d(v, step):
            # smallest curve >= v whose change per cell is bounded (safe: deeper)
            v = v.copy()
            for _ in range(len(v)):
                prev = v
                v = np.maximum(v, np.maximum(np.roll(v, 1) - step, np.roll(v, -1) - step))
                v[0], v[-1] = max(v[0], v[1] - step), max(v[-1], v[-2] - step)
                if np.abs(v - prev).max() < 1e-9:
                    break
            return v

        def blur_1d(v, n):
            for _ in range(n):
                v = 0.25 * np.roll(v, 1) + 0.5 * v + 0.25 * np.roll(v, -1)
            return v

        # blade: a cone per column, z = -k(az) * (R - rho), k as steep as the
        # column's own rays require, k(az) smooth along the ring
        radial = np.clip(R - RHO, 0.0, None)
        with np.errstate(divide="ignore", invalid="ignore"):
            k_cells = np.where(np.isfinite(need_own) & (radial > 1.0), -need_own / np.maximum(radial, 1.0), 0.0)
        k = np.clip(k_cells, 0.0, 2.5).max(axis=0)
        k = upper_envelope_1d(k, 0.03)
        k = blur_1d(k, 6) + 0.01
        z_blade = -k[None, :] * radial
        ceil_f = np.where(np.isfinite(ceil_cross), ceil_cross, -np.inf)
        blade_ok = ~has_cross | (z_blade - t_b >= ceil_f + 0.3)

        # dish: the styled dish scaled by a per-column factor m(az) >= 1 so
        # that it ducks under the rays; m smooth along the ring, at most 1.15
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(np.isfinite(need) & (dish < -0.5), need / dish, 1.0)
        m = np.clip(np.clip(ratio, 1.0, 1.15).max(axis=0), 1.0, 1.15)
        m = np.minimum(upper_envelope_1d(m, 0.004), 1.15)
        m = np.minimum(blur_1d(m, 6) + 0.002, 1.15)
        z_dish = np.maximum(m[None, :] * dish, -self.D0 - 2.0)
        dish_ok = (z_dish <= need + 1e-6) | ~np.isfinite(need)
        dish_ok &= z_dish >= -self.D0 - 2.0

        # per-cell bounds on the twist weight w (0 dish .. 1 blade)
        span = np.maximum(z_blade - z_dish, 1e-6)
        with np.errstate(divide="ignore", invalid="ignore"):
            w_max = np.where(has_cross, (floor_cross - 1.0 - z_dish) / span, 1.0)
            fb = z_blade - t_b
            fd = z_dish - g.plate_t
            w_min = np.where(has_cross, (ceil_f + 0.3 - fd) / np.maximum(fb - fd, 1e-6), 0.0)
        w_max = np.where(dish_ok, np.clip(w_max, -1.0, 1.0), -1.0)
        w_min = np.where(blade_ok, np.clip(w_min, 0.0, 2.0), 2.0)
        w_max = np.where(has_cross, w_max, np.where(dish_ok, 1.0, -1.0))
        w_min = np.where(has_cross, w_min, np.where(blade_ok, 0.0, 2.0))

        band_w = g.tick_zone + g.text_h + 6.0
        band = RHO >= g.R_out - band_w
        # an isolated column whose rays demand a different twist than both
        # its neighbours would notch the fold by millimetres for the sake of
        # a few days; within the band (never cut) such a constraint is
        # relaxed to what its neighbours within +-RELAX_BAND_DEG allow, and
        # the days it shadows appear in the report instead
        if RELAX_BAND_DEG > 0:
            kk = int(round(RELAX_BAND_DEG / d_az))
            hi = w_max.copy(); lo = w_min.copy()
            for sh in range(-kk, kk + 1):
                hi = np.maximum(hi, np.roll(w_max, sh, axis=1))
                lo = np.minimum(lo, np.roll(w_min, sh, axis=1))
            w_max = np.where(band, hi, w_max)
            w_min = np.where(band, lo, w_min)
        # Two-dimensional twist field w(rho, az).  Each cell allows w in
        # [0, w_max] (dish, plate under its crossing rays) or [w_min, 1]
        # (blade, plate above them).  The field is found by alternating a
        # blur, a projection onto the cell's allowed set, and a bound on the
        # rate of change (full twist over at least 24 degrees / 12 mm), so the
        # surface stays continuous.  Continuity wins over the ray rules; cells
        # that end up inside a ray are cut away unless they lie in the band.
        dish_part = w_max >= 0.0
        blade_part = w_min <= 1.0
        # seed: blade beyond the outermost cell that cannot be a dish
        w = np.zeros((n_r, n_a))
        mid = int(np.argmin(np.abs(self.az_grid - self.psi_mid)))
        col_no_dish = (~dish_part & band).any(axis=0)
        nd = np.where(col_no_dish)[0]
        if len(nd):
            left = nd[nd < mid]; right = nd[nd > mid]
            if len(left):
                w[:, :left.max() + 1] = 1.0
            if len(right):
                w[:, right.min():] = 1.0

        def project(v):
            lo_d = np.clip(v, 0.0, np.maximum(w_max, 0.0))          # nearest point of [0, w_max]
            lo_b = np.clip(v, np.minimum(w_min, 1.0), 1.0)          # nearest point of [w_min, 1]
            d_d = np.where(dish_part, np.abs(v - lo_d), np.inf)
            d_b = np.where(blade_part, np.abs(v - lo_b), np.inf)
            out = np.where(d_d <= d_b, lo_d, lo_b)
            out = np.where(dish_part | blade_part, out, v)          # unconstrained cells keep the blur
            return out

        step_az = d_az / 8.0       # max change of w per column (full twist over 8 degrees)
        step_r = d_rho / 6.0       # max change of w per row (full twist over 6 mm)

        def lower_envelope(v, sa, sr, n_iter=800):
            # largest field <= v whose change per cell is bounded (only ever
            # lowers values, so a dish can only get deeper, a blade lower);
            # iterated to convergence so no step survives anywhere
            v = v.copy()
            v[:, 0] = v[:, 1]; v[:, -1] = v[:, -2]          # no wrap-around coupling
            for _ in range(n_iter):
                prev = v
                v = np.minimum(v, np.roll(v, 1, axis=1) + sa)
                v = np.minimum(v, np.roll(v, -1, axis=1) + sa)
                v = np.minimum(v, np.roll(v, 1, axis=0) + sr)
                v = np.minimum(v, np.roll(v, -1, axis=0) + sr)
                v[0, :] = v[1, :]; v[-1, :] = v[-2, :]; v[:, 0] = v[:, 1]; v[:, -1] = v[:, -2]
                if np.abs(v - prev).max() < 1e-6:
                    break
            return v

        def blur(v):
            out = v.copy()
            out[:, 1:-1] = 0.25 * v[:, :-2] + 0.5 * v[:, 1:-1] + 0.25 * v[:, 2:]
            out[1:-1, :] = 0.25 * out[:-2, :] + 0.5 * out[1:-1, :] + 0.25 * out[2:, :]
            return out

        def monotone(v):
            # dish in the middle, blade at the tips, one fold between: the
            # twist may only grow from the noon centre towards either tip
            out = v.copy()
            out[:, :mid + 1] = np.maximum.accumulate(v[:, :mid + 1][:, ::-1], axis=1)[:, ::-1]
            out[:, mid:] = np.maximum.accumulate(v[:, mid:], axis=1)
            return out

        w = project(w)
        for _ in range(60):
            w = project(blur(w))
            if MONOTONE_TWIST:
                w = project(monotone(w))
            w = lower_envelope(w, step_az, step_r, 3)
        # continuity last: bounded rate of change everywhere, then a soft
        # blur so the fold has no creases (cells this pushes into a ray are
        # cut below, or accepted in the band)
        w = lower_envelope(w, step_az, step_r)
        if CLOSE_BAND_DEG > 0:
            # within the band a narrow dip of the fold (narrower than the
            # window) is filled: morphological closing along the azimuth,
            # then the usual rate bound; the band is never cut, the days
            # this shadows are reported
            kk = int(round(CLOSE_BAND_DEG / d_az))
            hi = w.copy()
            for sh in range(-kk, kk + 1):
                hi = np.maximum(hi, np.roll(w, sh, axis=1))
            closed = hi.copy()
            for sh in range(-kk, kk + 1):
                closed = np.minimum(closed, np.roll(hi, sh, axis=1))
            blend = _smoothstep((RHO - (g.R_out - band_w - 4.0)) / 8.0)
            w = np.maximum(w, blend * closed + (1.0 - blend) * w)
            w = lower_envelope(w, step_az, step_r)
        for _ in range(6):
            w = blur(w)
        w = np.clip(w, 0.0, 1.0)
        z_top = (1.0 - w) * z_dish + w * z_blade
        thick = (1.0 - w) * g.plate_t + w * t_b
        fits = (~has_cross | (z_top <= floor_cross - 0.9) | (z_top - thick >= ceil_f + 0.2)) \
            & (z_top <= floor_own - 0.2)
        valid = fits | band
        # around the hub the dish settles onto the hub top and the underside
        # swells into a soft boss, so plate and hub read as one form
        r_h = self.r_hub
        beta = _smoothstep((r_h + 14.0 - RHO) / 14.0)
        z_top = (1.0 - beta) * z_top + beta * (-self.D0)
        thick = thick + 5.0 * beta
        # inner edge per column: contiguous from the rim, then styled edge
        rho_in = np.full(n_a, g.R_out)
        for j in range(n_a):
            col = valid[:, j]
            k0 = n_r - 1
            while k0 > 0 and col[k0 - 1]:
                k0 -= 1
            rho_in[j] = self.rho_grid[k0]
        raw = np.maximum(rho_in, self.rho_in_design(self.az_grid))
        # the inner edge may only move outward by at most 1 mm per half
        # degree: widening a cut is always safe, so notches become sweeps
        rho_in = raw.copy()
        for _ in range(int(80 / d_az)):
            rho_in = np.maximum(rho_in, np.maximum(np.roll(rho_in, 1) - 1.0, np.roll(rho_in, -1) - 1.0))
            rho_in[0], rho_in[-1] = raw[0], raw[-1]
            rho_in = np.maximum(rho_in, raw)
        widened = rho_in.copy()
        for span in (16.0, 10.0, 6.0, 4.0):   # smoothed upper envelope: blur, then never below the cut
            kk = int(span / d_az) | 1
            for _ in range(3):
                rho_in = np.maximum(np.convolve(np.pad(rho_in, kk // 2, mode="edge"), np.ones(kk) / kk, mode="valid"), widened)
        self._rho_in = np.minimum(rho_in, g.R_out - 2.0)
        self._z_top = z_top
        self._thick = thick
        self._w = w

    # ---- evaluation -----------------------------------------------------
    def _interp(self, field, rho, psi):
        rho = np.asarray(rho, dtype=float)
        psi = np.asarray(psi, dtype=float)
        az = self.psi_mid + ((psi - self.psi_mid + 180.0) % 360.0 - 180.0)
        fr = np.clip((rho - self.rho_grid[0]) / (self.rho_grid[1] - self.rho_grid[0]), 0, len(self.rho_grid) - 1.001)
        fa = np.clip((az - self.az_grid[0]) / (self.az_grid[1] - self.az_grid[0]), 0, len(self.az_grid) - 1.001)
        i0, j0 = np.floor(fr).astype(int), np.floor(fa).astype(int)
        tr, ta = fr - i0, fa - j0
        f = field
        return ((1 - tr) * (1 - ta) * f[i0, j0] + tr * (1 - ta) * f[i0 + 1, j0]
                + (1 - tr) * ta * f[i0, j0 + 1] + tr * ta * f[i0 + 1, j0 + 1])

    def rho_in(self, psi):
        psi = np.asarray(psi, dtype=float)
        az = self.psi_mid + ((psi - self.psi_mid + 180.0) % 360.0 - 180.0)
        return np.interp(az, self.az_grid, self._rho_in)

    def z_top(self, rho, psi):
        return self._interp(self._z_top, rho, psi)

    def thickness(self, rho, psi):
        return self._interp(self._thick, rho, psi)

    def twist(self, rho, psi):
        return self._interp(self._w, rho, psi)

    def normal(self, rho, psi):
        """Upward unit normal of the top surface at (rho, psi[deg])."""
        eps_r, eps_p = 0.25, 0.25
        dzdr = (self.z_top(rho + eps_r, psi) - self.z_top(rho - eps_r, psi)) / (2 * eps_r)
        dzdp = (self.z_top(rho, psi + eps_p) - self.z_top(rho, psi - eps_p)) / (2 * math.radians(eps_p))
        pr = np.deg2rad(psi)
        e_rho = np.array([np.sin(pr), np.cos(pr)])
        e_psi = np.array([np.cos(pr), -np.sin(pr)])
        grad = dzdr * e_rho + (dzdp / max(rho, 1e-6)) * e_psi
        n = np.array([-grad[0], -grad[1], 1.0])
        return n / np.linalg.norm(n)

    def local_frame(self, rho, psi):
        """4x4 matrix: local x = clockwise tangent, y = radially outward
        (projected onto the surface), z = surface normal, at the surface point."""
        pr = math.radians(psi)
        Z = self.normal(rho, psi)
        e_psi = np.array([math.cos(pr), -math.sin(pr), 0.0]) * self.d.omega
        X = e_psi - np.dot(e_psi, Z) * Z
        X /= np.linalg.norm(X)
        Y = np.cross(Z, X)
        origin = np.array([rho * math.sin(pr), rho * math.cos(pr), float(self.z_top(rho, psi))])
        return _frame_matrix(X, Y, Z, origin)

    def normals(self, rho, psi):
        """Upward unit normals for arrays of rho at one azimuth (deg)."""
        rho = np.asarray(rho, dtype=float)
        eps_r, eps_p = 0.25, 0.25
        dzdr = (self.z_top(rho + eps_r, psi) - self.z_top(rho - eps_r, psi)) / (2 * eps_r)
        dzdp = (self.z_top(rho, psi + eps_p) - self.z_top(rho, psi - eps_p)) / (2 * math.radians(eps_p))
        pr = math.radians(psi)
        gx = dzdr * math.sin(pr) + (dzdp / np.maximum(rho, 1e-6)) * math.cos(pr)
        gy = dzdr * math.cos(pr) - (dzdp / np.maximum(rho, 1e-6)) * math.sin(pr)
        n = np.stack([-gx, -gy, np.ones_like(rho)], -1)
        return n / np.linalg.norm(n, axis=-1, keepdims=True)

    def section(self, psi, n_v=41, n_round=9):
        """Closed cross-section loop of the plate at azimuth psi: top surface
        from the rim inward, a half-round around the inner edge, the
        underside back out, a half-round around the rim.  Thickness is
        measured along the surface normal, so the edges are true rounds."""
        g = self.g
        pr = math.radians(psi)
        e_rho = np.array([math.sin(pr), math.cos(pr), 0.0])
        rho_in = float(self.rho_in(psi))
        t_out = float(self.thickness(g.R_out - 1.0, psi))
        t_in = float(self.thickness(rho_in + 1.0, psi))
        t_in = float(self.thickness(rho_in + t_in / 2.0, psi))
        a, b = g.R_out - t_out / 2.0, rho_in + t_in / 2.0
        if b > a - 0.3:
            b = a - 0.3
        # denser towards the inner edge, where the underside swells into the hub
        u = np.linspace(0.0, 1.0, n_v)
        rho = a + (b - a) * (u * (2.0 - u) * 0.6 + u * 0.4)
        z = self.z_top(rho, psi)
        top = np.stack([rho * math.sin(pr), rho * math.cos(pr), z], -1)
        n = self.normals(rho, psi)
        t = np.clip(self.thickness(rho, psi), 1.2, None)
        bot = top - t[:, None] * n
        # in-surface outward radial direction at both edges
        def e_r(k):
            v = e_rho - np.dot(e_rho, n[k]) * n[k]
            return v / np.linalg.norm(v)
        theta = np.linspace(math.pi / 2, -math.pi / 2, n_round + 2)[1:-1]
        # the inner edge runs obliquely across the azimuth planes near the
        # hub, so its round is built perpendicular to the edge curve itself
        # (not in the azimuth plane), otherwise the rounds terrace
        def edge_pt(p):
            r = float(self.rho_in(p)); q = math.radians(p)
            return np.array([r * math.sin(q), r * math.cos(q), float(self.z_top(r, p))])
        T = edge_pt(psi + 0.25) - edge_pt(psi - 0.25)
        T -= np.dot(T, n[-1]) * n[-1]
        if np.linalg.norm(T) < 1e-9:
            m_in = e_r(-1)
        else:
            T /= np.linalg.norm(T)
            m_in = np.cross(T, n[-1])
            m_in /= np.linalg.norm(m_in)
            if np.dot(m_in, e_rho) < 0:
                m_in = -m_in
        c_in = top[-1] - (t[-1] / 2.0) * n[-1]
        rnd_in = np.array([c_in + (t[-1] / 2.0) * (math.cos(th) * (-m_in) + math.sin(th) * n[-1]) for th in theta])
        c_out = top[0] - (t[0] / 2.0) * n[0]
        rnd_out = np.array([c_out + (t[0] / 2.0) * (math.cos(th) * e_r(0) + math.sin(th) * n[0]) for th in theta[::-1]])
        return np.vstack([top, rnd_in, bot[::-1], rnd_out])

    def mesh(self, n_psi=541, n_v=61):
        psi = np.linspace(self.psi_mid - self.psi_half, self.psi_mid + self.psi_half, n_psi)
        loops = [self.section(p, n_v=n_v) for p in psi]
        N = loops[0].shape[0]
        verts = np.vstack(loops)
        faces = []
        for i in range(n_psi - 1):
            o0, o1 = i * N, (i + 1) * N
            for j in range(N):
                k = (j + 1) % N
                faces += [[o0 + j, o1 + j, o1 + k], [o0 + j, o1 + k, o0 + k]]
        # end caps: fan around the loop centroid
        for i, rev in ((0, True), (n_psi - 1, False)):
            c = len(verts); verts = np.vstack([verts, loops[i].mean(axis=0, keepdims=True)])
            o = i * N
            for j in range(N):
                k = (j + 1) % N
                faces.append([c, o + k, o + j] if rev else [c, o + j, o + k])
        m = trimesh.Trimesh(vertices=verts, faces=np.asarray(faces), process=True)
        m.merge_vertices()
        trimesh.repair.fix_normals(m)
        if m.volume < 0:
            m.invert()
        return m


def sun_blocking_report(d: Design, g: BodyGeometry, surf: "PlateSurface", day_step=2, hour_step=1.0):
    """Rays from every mark towards the sun, for every sunlit hour of the
    year, checked analytically against the plate and hub solids.  Returns the
    list of (unix_time, zone_hour) samples whose ray is blocked."""
    from . import solar as _solar
    from .design import _sun_at
    p = d.params
    R = d.R
    t0 = _solar.dt_to_unix(_solar.datetime(p.year, 1, 1, tzinfo=_solar.timezone.utc))
    r_hub = hub_radius(g, d)
    z_hub_top = -surf.D0 + HUB_CUP_H
    z_hub_bot = z_hub_top - HUB_CUP_H - g.hub_len
    blocked = []
    days = np.arange(0, 365, day_step)
    hours = np.arange(d.hour_first, d.hour_last + 1e-9, hour_step)
    for day in days:
        t = t0 + day * 86400.0 + (hours - p.utc_offset_h) * 3600.0
        s_enu = _solar.sun_vector_enu(t, p.lat, p.lon)
        up = s_enu[:, 2] > math.sin(math.radians(2.0))
        if not up.any():
            continue
        s = _sun_at(t[up], p)
        hh = hours[up]
        psi = np.deg2rad(d.psi_of_time(hh))
        mark = np.stack([R * np.sin(psi), R * np.cos(psi), np.zeros_like(psi)], -1)
        lam = np.linspace(0.6, 2.3 * R, 500)
        pts = mark[:, None, :] + lam[None, :, None] * s[:, None, :]
        rho = np.hypot(pts[..., 0], pts[..., 1])
        az = np.rad2deg(np.arctan2(pts[..., 0], pts[..., 1]))
        z = pts[..., 2]
        rel = np.abs(((az - surf.psi_mid) + 180.0) % 360.0 - 180.0) / surf.psi_half
        in_dom = (rel <= 1.0) & (rho <= g.R_out) & (rho >= surf.rho_in(az))
        zt = surf.z_top(rho, az)
        zb = zt - surf.thickness(rho, az)
        in_plate = in_dom & (z <= zt) & (z >= zb)
        in_hub = (rho <= r_hub) & (z <= z_hub_top) & (z >= z_hub_bot)
        hit = np.any(in_plate | in_hub, axis=1)
        for k in np.where(hit)[0]:
            blocked.append((float(t[up][k]), float(hh[k])))
    return blocked


# --------------------------------------------------------------------------
# dimensions shared by the parts

def roller_bottom(d: Design):
    return float(min(rp.z.min() for rp in d.rollers))


def collar_radius(g: BodyGeometry, d: Design):
    r_lo = float(min(rp.r.min() for rp in d.rollers))
    return max(r_lo, g.pin_r) + 3.0


def hub_radius(g: BodyGeometry, d: Design):
    return max(collar_radius(g, d) + 4.0, 12.0)


def hub_top_z(g: BodyGeometry, d: Design):
    return roller_bottom(d) - g.neck_h - g.collar_h


def dish_depth(g: BodyGeometry, d: Design):
    return -hub_top_z(g, d)


# --------------------------------------------------------------------------
# parts

def build_roller(d: Design, g: BodyGeometry, rp: RollerProfile, grooves: int):
    """Roller in its own print frame: axis = z, pin bottom at z = 0."""
    z_lo = float(rp.z.min())
    r_lo = float(rp.r[0])
    r_hi = float(rp.r[-1])
    z_hi = float(rp.z.max())
    cr = collar_radius(g, d)
    z_collar_top = z_lo - g.neck_h
    z_collar_bot = z_collar_top - g.collar_h
    z_pin_bot = z_collar_bot - g.pin_len
    prof = [(0.0, z_pin_bot), (g.pin_r, z_pin_bot), (g.pin_r, z_collar_bot)]
    # the foot: a short seat of radius cr inside the hub's cup, then one
    # continuous flare (smoothstep) up into the computed profile, so collar,
    # neck and body are a single curve; the identification grooves are
    # shallow rounded coves on the flare (one = winter roller, two = summer)
    seat = HUB_CUP_H
    z_flare0 = z_collar_bot + seat
    span = z_lo - z_flare0
    for z in np.arange(z_collar_bot, z_lo - 1e-9, 0.1):
        t = min(max((z - z_flare0) / span, 0.0), 1.0)
        r = cr + (r_lo - cr) * (t * t * (3.0 - 2.0 * t))
        for k in range(grooves):
            zc = z_flare0 + 1.4 + k * 1.7
            u = (z - zc) / 0.6
            if abs(u) < 1.0:
                r -= 0.45 * 0.5 * (1.0 + math.cos(math.pi * u))
        prof.append((float(r), float(z)))
    prof += [(float(r), float(z)) for r, z in zip(rp.r, rp.z)]
    # rounded cap above the last (solstice) point
    cap_h = 0.55 * r_hi
    for a in np.linspace(0.0, math.pi / 2, 12)[1:]:
        prof.append((r_hi * math.cos(a), z_hi + cap_h * math.sin(a)))
    prof.append((0.0, z_hi + cap_h))
    m = _revolve(prof, sections=160)
    m.apply_translation([0, 0, -z_pin_bot])
    # the pin carries a coarse rounded thread and screws into the hub; the
    # collar seats on the hub top, so the thread only holds and never sets the height
    thread = _helical_thread(g.pin_r - 0.1, g.thread_depth + 0.1, g.thread_pitch, g.pin_len - 0.2,
                             fade=(1.5, 0.8), fade_to="core")
    m = trimesh.boolean.union([m, thread], engine="manifold")
    return m, {"pin_bottom_z_dial": z_pin_bot, "length": z_hi + cap_h - z_pin_bot,
               "thread": {"pitch": g.thread_pitch, "depth": g.thread_depth, "clearance": g.thread_clearance,
                          "turns": round((g.pin_len - 0.2) / g.thread_pitch, 1)}}


def build_dial(d: Design, g: BodyGeometry, engrave: bool = True):
    """Dial body in the dial frame (z = polar axis, reading circle at z=0)."""
    D0 = dish_depth(g, d)
    surf = PlateSurface(d, g, D0)
    plate = surf.mesh()
    r_hub = hub_radius(g, d)
    z_top = -D0
    z_bot = z_top - g.hub_len
    # hub: flared neck under the plate, straight waist, rounded foot
    prof = [(0.0, z_bot)]
    for a in np.linspace(-math.pi / 2, 0.0, 8):
        prof.append(((r_hub - 5.0) + 5.0 * math.cos(a), (z_bot + 5.0) + 5.0 * math.sin(a)))
    prof.append((r_hub, z_bot + 9.0))
    for k in np.linspace(0.0, 1.0, 8)[1:]:
        prof.append((r_hub + 4.0 * k * k, (z_bot + 9.0) + (z_top - 3.5 - (z_bot + 9.0)) * k))
    f = 3.5   # rounded top edge
    for a in np.linspace(0.0, math.pi / 2, 9)[1:]:
        prof.append(((r_hub + 4.0 - f) + f * math.cos(a), (z_top - f) + f * math.sin(a)))
    # the top rises around the roller's seat in a concave fillet (a cup of
    # height HUB_CUP_H), so hub and roller read as one continuous form
    cr = collar_radius(g, d) + g.clearance + 0.15
    rho_c = HUB_CUP_H
    prof.append((cr + rho_c, z_top))
    for a in np.linspace(0.0, math.pi / 2, 10)[1:]:
        # quarter circle centred on (cr + rho_c, z_top + rho_c): from the flat top to the seat wall
        prof.append(((cr + rho_c) - rho_c * math.sin(a), (z_top + rho_c) - rho_c * math.cos(a)))
    prof += [(cr, z_top), (0.0, z_top)]
    hub = _revolve(prof, sections=128)
    body = trimesh.boolean.union([plate, hub], engine="manifold")

    cutters = []
    # roller socket from the top: the female of the roller's thread, with a
    # radial clearance all round and a mouth that opens to the crest
    sock = _helical_thread(g.pin_r + g.thread_clearance, g.thread_depth, g.thread_pitch, g.socket_depth + 0.01,
                           fade=(0.0, 1.0), fade_to="crest")
    sock.apply_translation([0, 0, z_top - g.socket_depth])
    cutters.append(sock)
    # stand socket (D-shaped) from the bottom
    dsock = _cyl(g.pin_r + g.clearance, g.socket_depth + 0.01)
    dsock.apply_translation([0, 0, z_bot + g.socket_depth / 2 - 0.005])
    flat = pin_flat_offset(g)
    cut = trimesh.creation.box((4 * g.pin_r, 4 * g.pin_r, g.socket_depth + 1))
    cut.apply_translation([0, -(flat + g.clearance) - 2 * g.pin_r, z_bot + g.socket_depth / 2])
    dsock = trimesh.boolean.difference([dsock, cut], engine="manifold")
    cutters.append(dsock)

    if engrave:
        cutters += engraving_cutters(d, g, surf)

    cutter = trimesh.boolean.union(cutters, engine="manifold")
    dial = _largest_body(trimesh.boolean.difference([body, cutter], engine="manifold"))
    info = {"dish_depth": D0, "hub_radius": r_hub, "hub_top_z": z_top, "hub_bottom_z": z_bot,
            "psi_mid": surf.psi_mid, "psi_half": surf.psi_half, "surface": surf}
    return dial, info


def pin_flat_offset(g: BodyGeometry):
    return g.pin_r - 1.3


def engraving_cutters(d: Design, g: BodyGeometry, surf: PlateSurface):
    R = g.R
    cutters = []
    minute_spacing = R * math.pi / 720.0
    with_minutes = minute_spacing >= 0.7
    h0, h1 = d.hour_first, d.hour_last
    total_min = (h1 - h0) * 60
    depth = g.engrave
    for k in range(total_min + 1):
        t = h0 + k / 60.0
        if k % 60 == 0:
            L, w = g.tick_zone * 0.9, 0.9
        elif k % 15 == 0:
            L, w = g.tick_zone * 0.62, 0.6
        elif k % 5 == 0:
            L, w = g.tick_zone * 0.4, 0.5
        elif with_minutes:
            L, w = g.tick_zone * 0.22, 0.4
        else:
            continue
        psi = float(d.psi_of_time(t))
        rho_c = R - L / 2.0
        box = trimesh.creation.box((w, L, depth + 3.0))
        box.apply_translation([0, 0, (3.0 - depth) / 2.0])
        box.apply_transform(surf.local_frame(rho_c, psi))
        cutters.append(box)
    # hour numerals, "up" pointing outward, centred under the tick zone
    rho_txt = R - g.tick_zone - 1.5 - g.text_h / 2.0
    for h in range(h0, h1 + 1):
        cutters += arc_text_cutters(surf, d, str(h), g.text_h, rho_txt, float(d.psi_of_time(h)), depth)
    small = max(3.0, g.text_h * 0.55)
    summer = d.params.summer_label.strip()
    if summer:
        # where the place keeps summer time: a second, smaller row of numerals
        # one hour ahead inside the standard row, as on the Stuttgart dial,
        # with the two zone names between 12 and 13 on their rows
        h_s = g.text_h * 0.72
        rho_s = rho_txt - g.text_h / 2.0 - 1.2 - h_s / 2.0
        for h in range(h0, h1 + 1):
            cutters += arc_text_cutters(surf, d, str(h + 1), h_s, rho_s, float(d.psi_of_time(h)), depth)
        std = (d.params.zone_label.split() or [""])[0]
        psi_lab = float(d.psi_of_time(12.5))
        if std:
            cutters += arc_text_cutters(surf, d, std, small * 0.9, rho_txt, psi_lab, depth)
        cutters += arc_text_cutters(surf, d, summer, small * 0.9, rho_s, psi_lab, depth)
        rho_l = rho_s - h_s / 2.0 - 2.5 - small / 2.0
        lines = [ln for ln in [d.params.zone_label, location_text(d.params.lat, d.params.lon)] if ln]
    else:
        rho_l = rho_txt - g.text_h / 2.0 - 2.5 - small / 2.0
        lines = [ln for ln in [d.params.zone_label, location_text(d.params.lat, d.params.lon)] if ln]
    # zone label and coordinates below the 12 mark
    psi12 = float(d.psi_of_time(12))
    for ln in lines:
        if rho_l - small / 2.0 > hub_radius(g, d) + 4.0:
            cutters += arc_text_cutters(surf, d, ln, small, rho_l, psi12, depth)
        rho_l -= small + 2.0
    return cutters


def _tube(path, radii, sections=48):
    """Watertight tube along a 3D polyline with a radius per point, capped."""
    path = np.asarray(path, dtype=float)
    n = len(path)
    tang = np.gradient(path, axis=0)
    tang /= np.linalg.norm(tang, axis=1, keepdims=True)
    # planar path (x = 0): a constant binormal keeps the frames stable
    B = np.array([1.0, 0.0, 0.0])
    verts, faces = [], []
    for i in range(n):
        N = np.cross(B, tang[i]); N /= np.linalg.norm(N)
        for k in range(sections):
            a = 2 * math.pi * k / sections
            verts.append(path[i] + radii[i] * (math.cos(a) * B + math.sin(a) * N))
    for i in range(n - 1):
        for k in range(sections):
            a, b = i * sections + k, i * sections + (k + 1) % sections
            c, dd = a + sections, b + sections
            faces += [[a, c, dd], [a, dd, b]]
    c0 = len(verts); verts.append(path[0]); c1 = len(verts); verts.append(path[-1])
    for k in range(sections):
        faces.append([c0, (k + 1) % sections, k])
        base = (n - 1) * sections
        faces.append([c1, base + k, base + (k + 1) % sections])
    m = trimesh.Trimesh(vertices=np.array(verts), faces=np.array(faces), process=True)
    trimesh.repair.fix_normals(m)
    if m.volume < 0:
        m.invert()
    return m


HUB_CUP_H = 2.0              # the hub top rises this far around the roller's seat
MONOTONE_TWIST = True
RELAX_BAND_DEG = 2.0
CLOSE_BAND_DEG = 3.0
TIP_ANGLE_REQ_DEG = 22.0     # the whole assembly may be tilted this far before it tips


def _dial_to_stand(d: Design):
    """Rotation taking dial-frame vectors into the stand frame."""
    from . import solar as _solar
    lat = d.params.lat
    sgn = 1.0 if lat >= 0 else -1.0
    frame = _solar.dial_frame(lat)          # rows = dial axes in ENU
    stand_rot = np.diag([sgn, sgn, 1.0])    # stand -> ENU (its own inverse)
    return stand_rot @ frame.T


def _stand_layout(d: Design, g: BodyGeometry):
    """Where the dial sits over the foot of the stem (stand frame: foot at
    the origin, +y towards the elevated pole).  The stem rises vertically
    by h_v, then bends into the polar axis and runs L_a along it to the pin
    base; hub and dish continue along the axis to the dial centre.  The
    run along the axis is capped, so at low latitudes the dial is lifted
    instead of pushed out on a long cantilever."""
    phi = math.radians(abs(d.params.lat))
    phi = max(phi, math.radians(8.0))
    a = np.array([0.0, math.cos(phi), math.sin(phi)])
    D0 = dish_depth(g, d)
    R_out = g.R_out
    z_rim = R_out * math.cos(phi) + 18.0          # dial centre height for 18 mm of rim clearance
    L_hub = g.hub_len + D0
    L_a = float(min(max((z_rim - 30.0 * math.sin(phi)) / math.sin(phi) - L_hub, 0.55 * R_out), 0.6 * R_out))
    h_v = max(0.0, z_rim - (L_a + L_hub) * math.sin(phi))
    top = np.array([0.0, 0.0, h_v]) + L_a * a      # pin base
    centre = top + L_hub * a
    return phi, a, top, centre, h_v


def load_masses(d: Design, g: BodyGeometry, dial, rollers, dial_info):
    """Volumes and centres of mass (stand frame) of what the stand carries:
    the dial and the heavier of the two rollers, screwed in."""
    phi, a, top, centre, h_v = _stand_layout(d, g)
    Rd = _dial_to_stand(d)
    loads = []
    c = dial.center_mass
    loads.append((float(dial.volume), centre + Rd @ c))
    best = None
    for name, m, inf in rollers:
        z_off = dial_info["hub_top_z"] - g.pin_len
        cm = m.center_mass + np.array([0.0, 0.0, z_off])
        if best is None or m.volume > best[0]:
            best = (float(m.volume), centre + Rd @ cm)
    if best:
        loads.append(best)
    return loads


def noon_analemma(d: Design, n_days=366):
    """The place's noon analemma in the sun's own angles: x = the sun's
    hour angle at 12:00 zone time (the equation of time plus the longitude
    offset within the zone), y = its distance from the zenith towards the
    elevated pole, both in degrees, in the stand frame (+y towards the
    pole, +x to the reader's right).  Returns (points[n, 2], month-start
    indices)."""
    from . import solar as _solar
    from datetime import date
    p = d.params
    sgn = 1.0 if p.lat >= 0 else -1.0
    t0 = _solar.zone_time_to_unix(p.year, 1, 1, 12.0, p.utc_offset_h)
    t = t0 + np.arange(n_days, dtype=float) * 86400.0
    decl, _ = _solar.sun_geometry(t)
    H = _solar.hour_angle(t, p.lon)
    H = (H + 180.0) % 360.0 - 180.0
    pts = np.stack([sgn * H, sgn * (p.lat - decl)], -1)
    month_idx = [(date(p.year, m, 1) - date(p.year, 1, 1)).days for m in range(1, 13)]
    return pts, month_idx


def _resample_ring(poly, n, start_at_max_y=True):
    """n points along the exterior of a shapely polygon by arc length,
    counter-clockwise, starting nearest the topmost (+y) point."""
    from shapely.geometry import LinearRing
    ring = LinearRing(poly.exterior.coords)
    if not ring.is_ccw:
        ring = LinearRing(list(ring.coords)[::-1])
    L = ring.length
    coords = np.asarray(ring.coords)
    k = int(np.argmax(coords[:, 1]))
    s0 = ring.project(__import__("shapely.geometry", fromlist=["Point"]).Point(coords[k]))
    out = np.array([ring.interpolate((s0 + L * i / n) % L).coords[0] for i in range(n)])
    return out


def retriangulate_plane(mesh, z_plane: float, max_area: float = 30.0, tol: float = 1e-5):
    """Booleans leave a flat face as a fan of long slivers; along a
    tangent fillet their tilted vertex normals then streak across the
    whole face when shaded.  Re-mesh every upward face lying on z_plane
    with quality triangles (Steiner points inside, the boundary kept), so
    the shading of the flat top is even."""
    import triangle as _tri
    import shapely
    from shapely.geometry import LineString
    v, f = mesh.vertices, mesh.faces
    on = np.all(np.abs(v[f][:, :, 2] - z_plane) < tol, axis=1) & (mesh.face_normals[:, 2] > 0.5)
    if on.sum() < 10:
        return mesh
    sel = f[on]
    edges = np.sort(np.vstack([sel[:, [0, 1]], sel[:, [1, 2]], sel[:, [2, 0]]]), axis=1)
    uniq, counts = np.unique(edges, axis=0, return_counts=True)
    bnd = uniq[counts == 1]
    # planar straight-line graph for Triangle
    idx = np.unique(bnd)
    remap = {int(k): i for i, k in enumerate(idx)}
    pts2 = v[idx][:, :2]
    segs = np.array([[remap[int(a)], remap[int(b)]] for a, b in bnd])
    # the region the flat faces actually cover (with its holes: foot, grooves, letters);
    # Triangle fills the convex hull, 'YY' keeps every boundary segment intact,
    # and the triangles outside the region are dropped afterwards
    from shapely.geometry import Polygon as _P
    region = shapely.unary_union([_P(v[t][:, :2]) for t in sel])
    B = _tri.triangulate({"vertices": pts2, "segments": segs}, f"pq28a{max_area:.1f}YYQ")
    new_pts = B["vertices"]; new_tri = B["triangles"]
    n_old = len(idx)
    extra = np.column_stack([new_pts[n_old:], np.full(len(new_pts) - n_old, z_plane)])
    verts = np.vstack([v, extra])
    lut = np.concatenate([idx, np.arange(len(extra)) + len(v)])
    faces_new = lut[new_tri]
    cen = new_pts[new_tri].mean(axis=1)
    inside = shapely.contains_xy(region, cen[:, 0], cen[:, 1])
    faces_new = faces_new[inside]
    # winding: upward
    a = verts[faces_new[:, 1], :2] - verts[faces_new[:, 0], :2]; b = verts[faces_new[:, 2], :2] - verts[faces_new[:, 0], :2]
    cw = (a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) < 0
    faces_new[cw] = faces_new[cw][:, [0, 2, 1]]
    out = trimesh.Trimesh(vertices=verts, faces=np.vstack([f[~on], faces_new]), process=False)
    out.merge_vertices()
    return out if out.is_watertight else mesh


def flat_path_glyphs(text: str, height: float, path, s_centre: float):
    """Shapely polygons of `text` laid along a shapely LineString `path`
    (glyph tops to the left of the direction of travel), centred at arc
    length s_centre."""
    from shapely.affinity import rotate as _rot, translate as _tr
    scale = height / _cap_height()
    bar_l = _path_bounds(TextPath((0, 0), "|", size=1.0, prop=_FONT))[0]

    def pen(prefix):
        return _path_bounds(TextPath((0, 0), prefix + "|", size=1.0, prop=_FONT))[2] - (bar_l + _bar_w())

    total = pen(text) * scale
    out = []
    for i, ch in enumerate(text):
        if ch.strip() == "":
            continue
        gb = _path_bounds(TextPath((0, 0), ch, size=1.0, prop=_FONT))
        x_c = (pen(text[:i]) + 0.5 * (gb[0] + gb[2])) * scale - total / 2.0
        sp = s_centre + x_c
        if sp < 0 or sp > path.length:
            return [], total
        p0 = np.asarray(path.interpolate(sp).coords[0]); p1 = np.asarray(path.interpolate(min(sp + 0.5, path.length)).coords[0])
        pm = np.asarray(path.interpolate(max(sp - 0.5, 0.0)).coords[0])
        tg = p1 - pm; ang = math.degrees(math.atan2(tg[1], tg[0]))
        for poly in _text_polygons(ch, None, scale=scale):
            out.append(_tr(_rot(poly, ang, origin=(0, 0)), p0[0], p0[1]))
    return out, total


def build_stand(d: Design, g: BodyGeometry, loads=None):
    """Stand in its own frame: plate on z=0, foot of the stem at the origin,
    +y towards the elevated pole.  The base is the place's own noon
    analemma, fattened into a flat plate: the stem stands inside the loop
    on the reader's side, the other loop lies under the dial.  The analemma with its months, the
    location and the zone are engraved on top.  The edge is flat on the
    ground and rounds over from the top.

    The analemma is scaled so the foot fits inside its loop and, if that
    is not enough, until the whole assembly can be tilted by
    TIP_ANGLE_REQ_DEG in any direction before it tips over."""
    import shapely
    from shapely.geometry import LineString, Polygon as _Poly, Point as _Pt
    from shapely.affinity import translate as _stranslate
    phi, a, top, centre, h_v = _stand_layout(d, g)
    up_side = np.array([0.0, -math.sin(phi), math.cos(phi)])  # = -y_dial
    loads = list(loads or [])
    r0 = g.stem_r
    t_p = 5.0                              # plate thickness
    f = 3.5                                # foot round
    r_foot = 1.0 * r0
    r_meet = r_foot + f                    # radius of the foot on the plate
    z_meet = t_p - 0.15
    tan_req = math.tan(math.radians(TIP_ANGLE_REQ_DEG))
    S = 96

    # --- stem: straight up through the foot round and the vertical rise, then a cubic bend
    Pv = np.array([0.0, 0.0, z_meet + f + 1.0 + h_v])
    H = float(np.linalg.norm(top - Pv))
    P1 = Pv + np.array([0.0, 0.0, 0.42 * H])
    P2 = top - a * (0.42 * H)
    ts = np.linspace(0.0, 1.0, 70)
    bend = np.array([(1 - t) ** 3 * Pv + 3 * (1 - t) ** 2 * t * P1 + 3 * (1 - t) * t * t * P2 + t ** 3 * top for t in ts])
    z0 = 0.5
    n_up = max(int((Pv[2] - z0) / 0.6), 8)
    straight = np.array([[0.0, 0.0, z0 + (Pv[2] - z0) * t] for t in np.linspace(0.0, 1.0, n_up, endpoint=False)])
    path = np.vstack([straight, bend])
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    tt = np.concatenate([[0.0], np.cumsum(seg)]); tt /= tt[-1]
    radii = r0 * (1.0 - 0.16 * tt + 0.31 * tt * tt)     # r at the foot, a slight waist, 1.15 r at the top
    s_up = path[:, 2] - z_meet
    u = np.clip(f - s_up, 0.0, f)
    flare = np.where(s_up < 0.0, f, f - np.sqrt(np.clip(f * f - u * u, 0.0, None)))
    stem = _tube(path, radii + flare, sections=S)
    stem_vol, stem_com = float(stem.volume), np.asarray(stem.center_mass)

    # --- the analemma and its two loops
    pts_u, month_idx = noon_analemma(d)

    def noded(pts):
        loop = np.vstack([pts, pts[:1]])
        return shapely.unary_union([LineString(loop[i:i + 2]) for i in range(len(loop) - 1)])

    lobes = list(shapely.polygonize([noded(pts_u[::2])]).geoms)
    # the figure is the shadow trace of a vertical gnomon and always lies on
    # the pole side of its foot, under the dial: the stem takes the loop on
    # the reader's side (the small June loop north of the tropics; south of
    # the equator the December sun stands nearly overhead, so there the big
    # loop wraps around the foot) and the other loop lies under the dial
    near = min(lobes, key=lambda q: q.centroid.y)
    bx = near.bounds
    kx = float(min(max((bx[3] - bx[1]) / max(bx[2] - bx[0], 1e-6), 1.0), 8.0))  # make that loop roughly round
    x_ref = float(near.centroid.x)

    def stretched(pts, sc):
        return np.stack([(x_ref + (pts[:, 0] - x_ref) * kx) * sc, pts[:, 1] * sc], -1)

    near_k = _Poly(stretched(np.asarray(near.exterior.coords), 1.0))
    c_ins, r_ins = shapely.maximum_inscribed_circle(near_k, tolerance=0.01).coords[0], None
    c_ins = np.asarray(c_ins)
    r_ins = float(near_k.exterior.distance(_Pt(c_ins)))
    sc = (r_meet + 3.0) / max(r_ins, 1e-6)                # the foot fits inside the loop with 3 mm to spare

    def make_plate(sc, w):
        """Plate: the stretched analemma, foot at the origin, buffered by
        w; flat bottom, quarter-round edge of radius t_p from the top."""
        pts = stretched(pts_u, sc) - c_ins * sc
        curve = noded(pts[::3])
        base = curve.buffer(w - t_p, join_style=1, cap_style=1)         # the flat top
        if base.geom_type != "Polygon":
            base = max(base.geoms, key=lambda q: q.area)
        base = _Poly(base.exterior.coords)
        rings, zs = [], []
        specs = [(w - 2.5, 0.0)]                                        # inset bottom ring (cap)
        specs += [(w - t_p + t_p * math.cos(th), t_p * math.sin(th)) for th in np.linspace(0.0, math.pi / 2, 13)]
        specs += [(w - t_p - 2.5, t_p)]                                 # inset top ring (cap)
        for off_k, z_k in specs:
            rel = off_k - (w - t_p)
            poly = base if abs(rel) < 1e-9 else base.buffer(rel, join_style=1)
            if poly.geom_type != "Polygon":
                poly = max(poly.geoms, key=lambda q: q.area)
            poly = _Poly(poly.exterior.coords)
            rings.append(_resample_ring(poly, 4 * S)); zs.append(z_k)
        n_r = len(rings); N = 4 * S
        verts = np.vstack([np.column_stack([r, np.full(N, z)]) for r, z in zip(rings, zs)])
        faces = []
        for i in range(n_r - 1):
            o0, o1 = i * N, (i + 1) * N
            for k in range(N):
                k1 = (k + 1) % N
                faces += [[o0 + k, o1 + k, o1 + k1], [o0 + k, o1 + k1, o0 + k1]]
        _, tri = trimesh.creation.triangulate_polygon(_Poly(rings[0]), engine="earcut")
        for t in tri:
            faces.append([t[0], t[2], t[1]])
        _, tri2 = trimesh.creation.triangulate_polygon(_Poly(rings[-1]), engine="earcut")
        top_o = (n_r - 1) * N
        for t in tri2:
            faces.append([top_o + t[0], top_o + t[1], top_o + t[2]])
        m = trimesh.Trimesh(vertices=verts, faces=np.asarray(faces), process=True)
        trimesh.repair.fix_normals(m)
        if m.volume < 0:
            m.invert()
        return m, base, curve, pts

    # --- size for stability
    w = 20.0
    for _ in range(4):
        plate, flat_top, curve, pts = make_plate(sc, w)
        parts = loads + [(stem_vol, stem_com), (float(plate.volume), np.asarray(plate.center_mass))]
        V = sum(v for v, _ in parts)
        com = sum(v * np.asarray(c) for v, c in parts) / V
        need = float(com[2]) * tan_req + 6.0
        c2 = _Pt(float(com[0]), float(com[1]))
        outline = flat_top.buffer(t_p, join_style=1)
        margin = float(outline.exterior.distance(c2)) if outline.contains(c2) else -float(outline.exterior.distance(c2))
        if margin >= need:
            break
        sc *= 1.0 + 0.6 * (need - margin) / max(margin, 5.0)
    outline = flat_top.buffer(t_p, join_style=1)
    report = {"com": [float(x) for x in com], "margin_mm": margin,
              "tip_angle_deg": float(math.degrees(math.atan2(margin, max(float(com[2]), 1e-6)))),
              "plate_bounds": [float(v) for v in outline.bounds], "plate_thickness": t_p,
              "required_tip_angle_deg": TIP_ANGLE_REQ_DEG}

    rot = trimesh.geometry.align_vectors([0, 0, 1.0], a)
    pin = _cyl(g.pin_r, g.pin_len)
    pin.apply_transform(rot)
    pin.apply_translation(top + (g.pin_len / 2.0 - 0.01) * a)
    flat = pin_flat_offset(g)
    cutbox = trimesh.creation.box((4 * g.pin_r, 4 * g.pin_r, g.pin_len + 2))
    cutbox.apply_transform(rot)
    cutbox.apply_translation(top + (g.pin_len / 2.0) * a + up_side * (flat + 2 * g.pin_r))
    pin = trimesh.boolean.difference([pin, cutbox], engine="manifold")
    body = trimesh.boolean.union([plate, stem, pin], engine="manifold")

    # --- engraving: the analemma with month ticks and initials, location and zone
    cutters = []
    foot = _Pt(0.0, 0.0).buffer(r_meet + 1.5)
    inner = flat_top.buffer(-2.0)

    def engrave(poly):
        if poly is None or poly.is_empty:
            return
        for q in (poly.geoms if hasattr(poly, "geoms") else [poly]):
            q = q.buffer(0)
            if q.is_empty or q.area < 0.05:
                continue
            for qq in (q.geoms if hasattr(q, "geoms") else [q]):
                m = trimesh.creation.extrude_polygon(qq, g.engrave + 1.0)
                if not m.is_volume:
                    continue
                m.apply_translation([0, 0, t_p - g.engrave])
                cutters.append(m)

    full = noded(pts)
    groove = full.buffer(0.75, join_style=1).difference(foot)
    loop = np.vstack([pts, pts[:1]])
    tang = np.gradient(loop, axis=0)[:-1]
    tang /= np.linalg.norm(tang, axis=1, keepdims=True)
    lobes_k = list(shapely.polygonize([full]).geoms)
    letters = "JFMAMJJASOND"
    for m_i, k in enumerate(month_idx):
        pnt = pts[k]; tg = tang[k]; nrm = np.array([-tg[1], tg[0]])
        probe = _Pt(pnt[0] + nrm[0] * 1.5, pnt[1] + nrm[1] * 1.5)
        if any(lb.contains(probe) for lb in lobes_k):      # point outwards, away from the loops
            nrm = -nrm
        tick = LineString([pnt + nrm * 1.1, pnt + nrm * 3.6]).buffer(0.4)
        engrave(tick.difference(foot))
        cx, cy = pnt + nrm * 6.2
        for poly in _text_polygons(letters[m_i], 3.8):
            gl = _stranslate(poly, cx, cy)
            if inner.contains(gl) and not foot.intersects(gl):
                engrave(gl)
    engrave(groove)
    # location on the right flank of the far loop, zone on the left, along the plate
    far = max(lobes_k, key=lambda q: q.centroid.y)
    band = full.buffer(w - t_p - 4.4, join_style=1)
    ring = band.exterior if band.geom_type == "Polygon" else max(band.geoms, key=lambda q: q.area).exterior
    rc = np.asarray(ring.coords)
    fy0, fy1 = far.bounds[1], far.bounds[3]
    for text, h, side in [(location_text(d.params.lat, d.params.lon), 4.0, +1), (d.params.zone_label, 3.2, -1)]:
        if not text:
            continue
        sel = (np.sign(rc[:, 0]) == side) & (rc[:, 1] > fy0 + 0.15 * (fy1 - fy0)) & (rc[:, 1] < fy1 - 0.1 * (fy1 - fy0))
        seg_pts = rc[sel]
        if len(seg_pts) < 4:
            continue
        seg_pts = seg_pts[np.argsort(seg_pts[:, 1] * side)]     # right side reads towards the pole, left side back
        pth = LineString(seg_pts)
        for h_try in (h, 0.85 * h, 0.7 * h):
            glyphs, total = flat_path_glyphs(text, h_try, pth, pth.length / 2.0)
            if glyphs and all(inner.contains(gp) and not foot.intersects(gp) for gp in glyphs):
                for gp in glyphs:
                    engrave(gp)
                break
    stand = body if not cutters else _largest_body(trimesh.boolean.difference([body, trimesh.boolean.union(cutters, engine="manifold")], engine="manifold"))
    stand = retriangulate_plane(stand, t_p)
    minx, miny, maxx, maxy = outline.bounds
    info = {"stem_length": float(np.sum(seg)), "dial_centre": centre.tolist(), "axis": a.tolist(),
            "base_radius": float(0.5 * max(maxx - minx, maxy - miny)),
            "plate_bounds": [float(minx), float(miny), float(maxx), float(maxy)], "plate_thickness": t_p,
            "base_centre_y": float(0.5 * (miny + maxy)), "base_height": t_p,
            "tilt_deg": math.degrees(phi), "stability": report}
    return stand, info


def build_all(d: Design, g: BodyGeometry | None = None, engrave: bool = True):
    g = g or BodyGeometry.for_radius(d.R)
    dial, dial_info = build_dial(d, g, engrave=engrave)
    rollers = []
    for k, rp in enumerate(d.rollers):
        m, inf = build_roller(d, g, rp, grooves=k + 1)
        rollers.append((rp.name, m, inf))
    stand, stand_info = build_stand(d, g, loads=load_masses(d, g, dial, rollers, dial_info))
    return {"dial": dial, "rollers": rollers, "stand": stand,
            "geometry": g, "dial_info": dial_info, "stand_info": stand_info}


def shadowed_days_report(d: Design, g: BodyGeometry, surf: "PlateSurface"):
    """Days on which some reading hour is shadowed by the dial body itself,
    grouped into ranges with the affected hours."""
    from datetime import datetime, timezone
    blocked = sun_blocking_report(d, g, surf, day_step=1, hour_step=0.5)
    if not blocked:
        return []
    by_day = {}
    for t, h in blocked:
        day = datetime.fromtimestamp(t, timezone.utc).date()
        by_day.setdefault(day, set()).add(h)
    days = sorted(by_day)
    groups = [[days[0]]]
    for a, b in zip(days, days[1:]):
        if (b - a).days <= 3:
            groups[-1].append(b)
        else:
            groups.append([b])
    def fmt(h):
        return f"{int(h):02d}:{int(round((h % 1) * 60)):02d}"

    out = []
    for grp in groups:
        hours = sorted(set().union(*[by_day[x] for x in grp]))
        runs = [[hours[0]]]
        for a, b in zip(hours, hours[1:]):
            if b - a <= 0.5 + 1e-9:
                runs[-1].append(b)
            else:
                runs.append([b])
        label = ", ".join(f"{fmt(r[0])}-{fmt(r[-1])}" if len(r) > 1 else fmt(r[0]) for r in runs)
        out.append({"from": grp[0].strftime("%d %b"), "to": grp[-1].strftime("%d %b"),
                    "days": len(grp), "hours": label})
    return out


def continuity_report(parts: dict):
    """Proof that every part is one continuous solid: watertight, a single
    connected component, and (for the dial) a bounded height step between
    neighbouring surface samples of the plate field."""
    out = {}
    for name, mesh in [("dial", parts["dial"]), ("stand", parts["stand"])] + [(n, m) for n, m, _ in parts["rollers"]]:
        comps = mesh.split(only_watertight=False)
        out[name] = {"watertight": bool(mesh.is_watertight), "components": int(len(comps)),
                     "volume_mm3": float(mesh.volume), "faces": int(len(mesh.faces))}
    surf = parts["dial_info"]["surface"]
    z = surf._z_top
    keep = surf.rho_grid[:, None] >= surf._rho_in[None, :]
    dz_az = np.abs(np.diff(z, axis=1)); dz_r = np.abs(np.diff(z, axis=0))
    m_az = keep[:, 1:] & keep[:, :-1]; m_r = keep[1:, :] & keep[:-1, :]
    out["dial"]["max_step_mm_per_half_degree"] = float(dz_az[m_az].max()) if m_az.any() else 0.0
    out["dial"]["max_step_mm_per_half_mm"] = float(dz_r[m_r].max()) if m_r.any() else 0.0
    out["dial"]["max_inner_edge_step_mm"] = float(np.abs(np.diff(surf._rho_in)).max())
    # roughness: second difference of the height field (a crease or dimple
    # shows up here even when every single step is small)
    d2a = np.abs(z[:, 2:] - 2 * z[:, 1:-1] + z[:, :-2]); ma = keep[:, 2:] & keep[:, 1:-1] & keep[:, :-2]
    d2r = np.abs(z[2:, :] - 2 * z[1:-1, :] + z[:-2, :]); mr2 = keep[2:, :] & keep[1:-1, :] & keep[:-2, :]
    out["dial"]["max_curvature_mm"] = float(max(d2a[ma].max() if ma.any() else 0.0, d2r[mr2].max() if mr2.any() else 0.0))
    return out
