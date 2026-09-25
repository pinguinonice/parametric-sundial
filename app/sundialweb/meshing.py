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
                   rim=max(2.0, 2.5 * s),
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


def _text_polygons(text: str, height: float):
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
    scale = height / max(maxy - miny, 1e-6)
    cx, cy = 0.5 * (minx + maxx), 0.5 * (miny + maxy)
    from shapely.affinity import translate, scale as sscale
    geom = sscale(translate(geom, -cx, -cy), scale, scale, origin=(0, 0))
    polys = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
    return [p for p in polys if p.area > 1e-6]


def text_mesh(text: str, height: float, depth: float, above: float = 3.0):
    """Extruded text lying in the XY plane, spanning z in [-depth, above]."""
    parts = []
    for poly in _text_polygons(text, height):
        m = trimesh.creation.extrude_polygon(poly, depth + above)
        m.apply_translation([0, 0, -depth])
        parts.append(m)
    return trimesh.util.concatenate(parts) if parts else None


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
        q = (g.w_tip * 1.6) / (math.radians(self.psi_half) * g.R_out)
        q = min(max(q, 0.02), 0.25)
        tip = np.clip((rel - (1.0 - q)) / q, 0.0, 1.0)
        round_w = np.sqrt(np.clip(1.0 - tip * tip, 0.0, 1.0))
        rounded = g.R_out - 0.4 - (g.w_tip - 0.4) * round_w
        return np.where(rel > 1.0 - q, np.minimum(rho, rounded), rho)

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

        w = project(w)
        for _ in range(60):
            w = project(blur(w))
            w = lower_envelope(w, step_az, step_r, 3)
        # continuity last: bounded rate of change everywhere, then a soft
        # blur so the fold has no creases (cells this pushes into a ray are
        # cut below, or accepted in the band)
        w = lower_envelope(w, step_az, step_r)
        for _ in range(6):
            w = blur(w)
        w = np.clip(w, 0.0, 1.0)
        z_top = (1.0 - w) * z_dish + w * z_blade
        thick = (1.0 - w) * g.plate_t + w * t_b
        fits = (~has_cross | (z_top <= floor_cross - 0.9) | (z_top - thick >= ceil_f + 0.2)) \
            & (z_top <= floor_own - 0.2)
        valid = fits | band
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
        kk = int(6.0 / d_az) | 1
        rho_in = np.maximum(np.convolve(np.pad(rho_in, kk // 2, mode="edge"), np.ones(kk) / kk, mode="valid"), rho_in)
        self._rho_in = np.minimum(rho_in, g.R_out - 0.4)
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

    def mesh(self, n_psi=541, n_v=57):
        g = self.g
        psi = np.linspace(self.psi_mid - self.psi_half, self.psi_mid + self.psi_half, n_psi)
        v = np.linspace(0.0, 1.0, n_v)
        P, V = np.meshgrid(psi, v, indexing="ij")
        rho = g.R_out + (self.rho_in(P) - g.R_out) * V
        pr = np.deg2rad(P)
        x, y = rho * np.sin(pr), rho * np.cos(pr)
        zt = self.z_top(rho, P)
        zb = zt - self.thickness(rho, P)
        top = np.stack([x, y, zt], -1).reshape(-1, 3)
        bot = np.stack([x, y, zb], -1).reshape(-1, 3)
        verts = np.vstack([top, bot])
        nt = top.shape[0]

        def idx(i, j, bottom=False):
            return i * n_v + j + (nt if bottom else 0)

        faces = []
        for i in range(n_psi - 1):
            for j in range(n_v - 1):
                a, b, c, dd = idx(i, j), idx(i + 1, j), idx(i + 1, j + 1), idx(i, j + 1)
                faces += [[a, b, c], [a, c, dd]]
                a, b, c, dd = idx(i, j, 1), idx(i + 1, j, 1), idx(i + 1, j + 1, 1), idx(i, j + 1, 1)
                faces += [[a, c, b], [a, dd, c]]
        for i in range(n_psi - 1):
            a, b = idx(i, 0), idx(i + 1, 0)
            a2, b2 = idx(i, 0, 1), idx(i + 1, 0, 1)
            faces += [[a, a2, b2], [a, b2, b]]
            j = n_v - 1
            a, b = idx(i, j), idx(i + 1, j)
            a2, b2 = idx(i, j, 1), idx(i + 1, j, 1)
            faces += [[a, b2, a2], [a, b, b2]]
        for j in range(n_v - 1):
            a, b = idx(0, j), idx(0, j + 1)
            a2, b2 = idx(0, j, 1), idx(0, j + 1, 1)
            faces += [[a, b2, a2], [a, b, b2]]
            i = n_psi - 1
            a, b = idx(i, j), idx(i, j + 1)
            a2, b2 = idx(i, j, 1), idx(i, j + 1, 1)
            faces += [[a, a2, b2], [a, b2, b]]
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
    z_hub_top = -surf.D0
    z_hub_bot = z_hub_top - g.hub_len
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
    prof = [(0.0, z_pin_bot), (g.pin_r, z_pin_bot), (g.pin_r, z_collar_bot), (cr, z_collar_bot)]
    # identification grooves on the collar
    gw, gd = 0.8, 0.6
    zc = z_collar_bot
    for k in range(grooves):
        z0 = z_collar_bot + 0.6 + k * (gw + 0.6)
        prof += [(cr, z0), (cr - gd, z0), (cr - gd, z0 + gw), (cr, z0 + gw)]
    prof += [(cr, z_collar_top), (r_lo, z_collar_top)]
    # a short straight neck, then the computed profile
    prof += [(float(r), float(z)) for r, z in zip(rp.r, rp.z)]
    # rounded cap above the last (solstice) point
    cap_h = 0.55 * r_hi
    for a in np.linspace(0.0, math.pi / 2, 12)[1:]:
        prof.append((r_hi * math.cos(a), z_hi + cap_h * math.sin(a)))
    prof.append((0.0, z_hi + cap_h))
    m = _revolve(prof, sections=160)
    m.apply_translation([0, 0, -z_pin_bot])
    return m, {"pin_bottom_z_dial": z_pin_bot, "length": z_hi + cap_h - z_pin_bot}


def build_dial(d: Design, g: BodyGeometry, engrave: bool = True):
    """Dial body in the dial frame (z = polar axis, reading circle at z=0)."""
    D0 = dish_depth(g, d)
    surf = PlateSurface(d, g, D0)
    plate = surf.mesh()
    r_hub = hub_radius(g, d)
    z_top = -D0
    hub = _cyl(r_hub, g.hub_len)
    hub.apply_translation([0, 0, z_top - g.hub_len / 2])
    # chamfer-like dome under the hub: a shallow cone ring
    body = trimesh.boolean.union([plate, hub], engine="manifold")

    cutters = []
    # roller socket (round) from the top
    sock = _cyl(g.pin_r + g.clearance, g.socket_depth + 0.01)
    sock.apply_translation([0, 0, z_top - g.socket_depth / 2 + 0.005])
    cutters.append(sock)
    # stand socket (D-shaped) from the bottom
    z_bot = z_top - g.hub_len
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
        psi = float(d.psi_of_time(h))
        tm = text_mesh(str(h), g.text_h, depth)
        if tm is None:
            continue
        tm.apply_transform(surf.local_frame(rho_txt, psi))
        cutters.append(tm)
    # zone label below the 12 mark, two lines
    small = max(3.0, g.text_h * 0.55)
    lines = [ln for ln in [d.params.zone_label, "SUMMER TIME +1 H", location_text(d.params.lat, d.params.lon)] if ln]
    rho_l = rho_txt - g.text_h / 2.0 - 2.5 - small / 2.0
    psi12 = float(d.psi_of_time(12))
    for ln in lines:
        tm = text_mesh(ln, small, depth)
        if tm is not None and rho_l - small / 2.0 > hub_radius(g, d) + 4.0:
            tm.apply_transform(surf.local_frame(rho_l, psi12))
            cutters.append(tm)
        rho_l -= small + 2.0
    return cutters


def build_stand(d: Design, g: BodyGeometry):
    """Stand in its own frame: base on z=0, +y towards the elevated pole."""
    phi = math.radians(abs(d.params.lat))
    phi = max(phi, math.radians(8.0))
    a = np.array([0.0, math.cos(phi), math.sin(phi)])
    up_side = np.array([0.0, -math.sin(phi), math.cos(phi)])  # = -y_dial
    D0 = dish_depth(g, d)
    R_out = g.R_out
    clearance = 6.0
    L_needed = (R_out * math.cos(phi) + clearance + g.base_t) / math.sin(phi) - g.hub_len - D0
    L_stem = float(min(max(L_needed, 15.0), 160.0))
    # dial centre (reading circle centre) in the stand frame
    centre = (L_stem + g.hub_len + D0) * a + np.array([0, 0, 0])
    y_c = float(centre[1])
    base_r = max(0.75 * R_out, 45.0, y_c / 2.0 + 14.0)
    base_c = np.array([0.0, y_c / 2.0, 0.0])

    base = _cyl(base_r, g.base_t)
    base.apply_translation([0, y_c / 2.0, g.base_t / 2.0])

    rot = trimesh.geometry.align_vectors([0, 0, 1.0], a)
    stem_len = L_stem + 3.0
    stem = _cyl(g.stem_r, stem_len)
    stem.apply_transform(rot)
    stem.apply_translation((L_stem - stem_len / 2.0) * a)
    # foot: cut everything below the base top
    pin = _cyl(g.pin_r, g.pin_len)
    pin.apply_transform(rot)
    pin.apply_translation((L_stem + g.pin_len / 2.0 - 0.01) * a)
    flat = pin_flat_offset(g)
    cutbox = trimesh.creation.box((4 * g.pin_r, 4 * g.pin_r, g.pin_len + 2))
    cutbox.apply_transform(rot)
    cutbox.apply_translation((L_stem + g.pin_len / 2.0) * a + up_side * (flat + 2 * g.pin_r))
    pin = trimesh.boolean.difference([pin, cutbox], engine="manifold")

    # gusset fin under the stem, in the meridian plane
    Lc, Ls = L_stem * math.cos(phi), L_stem * math.sin(phi)
    back = -g.stem_r / math.sin(phi) * 0.9
    fin_poly = Polygon([(back, 0.0), (Lc + g.stem_r * math.sin(phi) * 0.5, 0.0),
                        (Lc + g.stem_r * math.sin(phi) * 0.5, Ls - g.stem_r * math.cos(phi) * 0.5)])
    fin = trimesh.creation.extrude_polygon(fin_poly, g.fin_t)
    # polygon (u=y, v=z) extruded along w -> map (u, v, w) to (w, u, v)
    Mf = np.array([[0, 0, 1, -g.fin_t / 2.0], [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=float)
    fin.apply_transform(Mf)

    body = trimesh.boolean.union([base, stem, fin, pin], engine="manifold")
    below = trimesh.creation.box((4 * base_r, 4 * base_r, 40.0))
    below.apply_translation([0, y_c / 2.0, -20.0])
    cutters = [below]
    # location and zone on the base, in front of the fin where the reader stands
    y_edge = y_c / 2.0 - base_r                 # equator-side rim of the disc
    y_free = min(back, 0.0) - 3.0               # back of the fin
    room = y_free - y_edge
    h1 = min(4.5, max(3.0, room * 0.28))
    h2 = h1 * 0.72
    y1 = y_free - 2.0 - h1 / 2.0
    y2 = y1 - h1 / 2.0 - 2.0 - h2 / 2.0
    for text, h, y in [(location_text(d.params.lat, d.params.lon), h1, y1), (d.params.zone_label, h2, y2)]:
        if not text or y - h / 2.0 < y_edge + 2.0:
            continue
        tm = text_mesh(text, h, g.engrave)
        if tm is not None:
            tm.apply_translation([0, y, g.base_t])
            cutters.append(tm)
    stand = _largest_body(trimesh.boolean.difference([body, trimesh.boolean.union(cutters, engine="manifold")], engine="manifold"))
    info = {"stem_length": L_stem, "dial_centre": centre.tolist(), "axis": a.tolist(),
            "base_radius": base_r, "base_centre_y": y_c / 2.0, "tilt_deg": math.degrees(phi)}
    return stand, info


def build_all(d: Design, g: BodyGeometry | None = None, engrave: bool = True):
    g = g or BodyGeometry.for_radius(d.R)
    dial, dial_info = build_dial(d, g, engrave=engrave)
    rollers = []
    for k, rp in enumerate(d.rollers):
        m, inf = build_roller(d, g, rp, grooves=k + 1)
        rollers.append((rp.name, m, inf))
    stand, stand_info = build_stand(d, g)
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
