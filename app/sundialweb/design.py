"""Geometric design of a Bernhardt roller sundial for a given location.

Everything here is computed in the *dial frame* (see solar.dial_frame):
z is the polar axis, the scale circle of radius R lies in the plane z=0,
and a mark for zone time T sits at azimuth psi(T) measured clockwise from
+y when looking down the +z axis:  position = R * (sin psi, cos psi, 0).

Construction (Oliver 1892 / Bernhardt 1966, see Glaeser & Hofmann 2004):
for every instant, the ray from the correct mean-time mark towards the sun
passes the polar axis at a distance r and a height z.  Those (z, r) pairs
over half a year form the profile of a surface of revolution, the roller.
The shadow of the roller then has its leading edge exactly on the mark for
the current mean (zone) time, so the equation of time is built into the
shape.  Two rollers are needed because the sun's declination runs through
each value twice a year with different equation-of-time values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np

from . import solar


@dataclass
class DesignParams:
    lat: float
    lon: float
    utc_offset_h: float
    year: int = 2026
    scale_radius: float = 75.0        # mm, radius of the reading circle
    min_roller_radius: float = 4.0    # mm, thinnest part of the roller neck
    hour_first: int | None = None     # None -> automatic from sunrise
    hour_last: int | None = None
    zone_label: str = ""


@dataclass
class RollerProfile:
    name: str
    label: str
    z: np.ndarray            # mm, increasing (final print profile)
    r: np.ndarray            # mm
    days: np.ndarray         # unix seconds of the design samples (time order)
    z_nodus: np.ndarray = None   # nodus height per sample
    r_nodus: np.ndarray = None   # required radius per sample
    error_min: np.ndarray = None # reading error per sample in minutes (+ = dial fast)
    balance: float = 0.0


@dataclass
class Design:
    params: DesignParams
    omega: float                     # +1 or -1, direction of shadow travel in psi
    psi_noon: float                  # deg, azimuth of the 12:00 mark
    hour_first: int
    hour_last: int
    rollers: list = field(default_factory=list)
    reading_error_min: float = 0.0
    sunrise_earliest: float = 0.0
    sunset_latest: float = 0.0
    min_roller_r: float = 0.0
    max_roller_r: float = 0.0

    @property
    def R(self) -> float:
        return self.params.scale_radius

    def psi_of_time(self, t_zone_h):
        """Azimuth (deg) of the mark for zone time t (hours, decimal)."""
        return self.psi_noon + self.omega * 15.0 * (np.asarray(t_zone_h, dtype=float) - 12.0)

    def mark_xy(self, t_zone_h, radius=None):
        R = self.R if radius is None else radius
        p = np.deg2rad(self.psi_of_time(t_zone_h))
        return np.stack([R * np.sin(p), R * np.cos(p)], axis=-1)

    @property
    def psi_first(self):
        return float(self.psi_of_time(self.hour_first))

    @property
    def psi_last(self):
        return float(self.psi_of_time(self.hour_last))

    @property
    def psi_mid(self):
        return 0.5 * (self.psi_first + self.psi_last)

    @property
    def psi_half(self):
        return 0.5 * abs(self.psi_last - self.psi_first)


def _wrap(a):
    return (np.asarray(a, dtype=float) + 180.0) % 360.0 - 180.0


def _anti_sun_azimuth(sun_dial):
    """Azimuth psi (deg, clockwise from +y) of the shadow direction."""
    s = np.asarray(sun_dial)
    ax, ay = -s[..., 0], -s[..., 1]
    return np.rad2deg(np.arctan2(ax, ay))


def _sun_at(unix_s, p: DesignParams):
    return solar.enu_to_dial(solar.sun_vector_enu(unix_s, p.lat, p.lon), p.lat)


def _zone_hours(unix_s, p: DesignParams):
    return (np.mod(np.asarray(unix_s, dtype=float) + p.utc_offset_h * 3600.0, 86400.0)) / 3600.0


def closest_point_to_axis(mark_xyz, s):
    """Point on the ray mark + lambda*s nearest to the z axis: (z, r)."""
    m = np.asarray(mark_xyz)
    s = np.asarray(s)
    sxy = s[..., :2]
    mxy = m[..., :2]
    lam = -(mxy * sxy).sum(-1) / (sxy * sxy).sum(-1)
    pt = m + lam[..., None] * s
    return pt[..., 2], np.hypot(pt[..., 0], pt[..., 1])


def _auto_hours(p: DesignParams):
    """Earliest sunrise / latest sunset in zone time over the year."""
    t0 = solar.dt_to_unix(solar.datetime(p.year, 1, 1, 12, tzinfo=solar.timezone.utc))
    days = t0 + np.arange(0, 366) * 86400.0
    decl, eot = solar.sun_geometry(days)
    phi = math.radians(p.lat)
    d = np.deg2rad(decl)
    cosH0 = -np.tan(phi) * np.tan(d)
    up_all = cosH0 < -1.0       # polar day
    never = cosH0 > 1.0         # polar night
    H0 = np.rad2deg(np.arccos(np.clip(cosH0, -1.0, 1.0)))
    H0 = np.where(up_all, 180.0, H0)
    lon_zone = 15.0 * p.utc_offset_h
    t_noon = 12.0 - eot / 60.0 - (p.lon - lon_zone) / 15.0
    rise = t_noon - H0 / 15.0
    sett = t_noon + H0 / 15.0
    ok = ~never
    if not ok.any():
        return 6, 18, 6.0, 18.0
    earliest = float(rise[ok].min())
    latest = float(sett[ok].max())
    first = int(math.floor(earliest))
    last = int(math.ceil(latest))
    first = max(first, 3)
    last = min(last, 21)
    return first, last, earliest, latest


def build_design(p: DesignParams) -> Design:
    R = p.scale_radius
    dec_prev, jun, dec = solar.solstices(p.year)

    # sample the whole year every 6 hours for the ring offset
    t_year = np.arange(dec_prev, dec + 1.0, 6 * 3600.0)
    sun = _sun_at(t_year, p)
    tz_h = _zone_hours(t_year, p)
    phi_as = _anti_sun_azimuth(sun)

    # direction of travel of the shadow: sign of d(phi_as)/dt around noon
    t_probe = np.array([solar.zone_time_to_unix(p.year, 3, 21, 11.0, p.utc_offset_h),
                        solar.zone_time_to_unix(p.year, 3, 21, 13.0, p.utc_offset_h)])
    pa = _anti_sun_azimuth(_sun_at(t_probe, p))
    omega = 1.0 if _wrap(pa[1] - pa[0]) > 0 else -1.0

    # g(t) = omega * (omega*15*(T-12) - phi_as): the mark-minus-shadow angle
    # without the constant noon offset.  Choose psi_noon so that the leading
    # edge is always ahead of the shadow centre by at least alpha_min.
    g = 15.0 * (tz_h - 12.0) - omega * phi_as
    g = _wrap(g)
    alpha_min = math.degrees(math.asin(p.min_roller_radius / R))
    psi_noon = omega * (alpha_min - float(g.min()))
    psi_noon = float(_wrap(psi_noon))

    if p.hour_first is None or p.hour_last is None:
        hf, hl, earliest, latest = _auto_hours(p)
    else:
        hf, hl = int(p.hour_first), int(p.hour_last)
        _, _, earliest, latest = _auto_hours(p)
    hf = max(1, min(hf, 11))
    hl = max(13, min(hl, 23))

    d = Design(params=p, omega=omega, psi_noon=psi_noon, hour_first=hf, hour_last=hl,
               sunrise_earliest=earliest, sunset_latest=latest)

    # rollers: one per half year, sampled every 6 h between the solstices
    halves = [("roller_1", "I  21 Dec - 21 Jun", dec_prev, jun),
              ("roller_2", "II  21 Jun - 21 Dec", jun, dec)]
    for name, label, ta, tb in halves:
        d.rollers.append(_build_roller_profile(d, name, label, ta, tb))

    d.min_roller_r = float(min(rp.r.min() for rp in d.rollers))
    d.max_roller_r = float(max(rp.r.max() for rp in d.rollers))
    return d


def roller_radius_at(profile: RollerProfile, z):
    return np.interp(z, profile.z, profile.r)


def _roller_samples(d: Design, ta, tb):
    p = d.params
    R = d.R
    t = np.linspace(ta, tb, int((tb - ta) / (6 * 3600.0)) + 1)
    s = _sun_at(t, p)
    T = _zone_hours(t, p)
    psi = d.psi_of_time(T)
    mark = np.stack([R * np.sin(np.deg2rad(psi)), R * np.cos(np.deg2rad(psi)),
                     np.zeros_like(psi)], axis=-1)
    z, r = closest_point_to_axis(mark, s)
    return t, s, psi, z, r


def _ray_distance_from_axis(z_grid, z_d, r_d, s_d):
    """Distance from the axis of the ray of sample d, as a function of z.

    Rotating the ray about the axis gives a hyperboloid of revolution;
    this is its radius at height z.  Shape (n_samples, n_grid)."""
    sz = s_d[:, 2]
    sxy = np.hypot(s_d[:, 0], s_d[:, 1])
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = np.where(np.abs(sz) > 1e-9, sxy / np.abs(sz), np.inf)
    dz = z_grid[None, :] - z_d[:, None]
    horiz = dz * slope[:, None]
    return np.sqrt(r_d[:, None] ** 2 + horiz ** 2)


def _reading_errors(d: Design, s, psi, z_prof, r_prof, lo=-8.0, hi=8.0, steps=16):
    """Per-sample reading error (minutes, + = dial fast) of a given profile,
    found by bisection on the mark angle with a vectorised ray march."""
    R = d.R
    n = s.shape[0]
    z_lo, z_hi = z_prof[0] - 0.5, z_prof[-1] + 0.5
    # lambda range along each ray that covers the roller's z span
    sz = s[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        l1 = np.where(np.abs(sz) > 1e-9, z_lo / sz, 0.0)
        l2 = np.where(np.abs(sz) > 1e-9, z_hi / sz, 2.2 * R)
    lam_a = np.clip(np.minimum(l1, l2), 0.0, 2.2 * R)
    lam_b = np.clip(np.maximum(l1, l2), 0.0, 2.2 * R)
    lam_b = np.where(lam_b - lam_a < 1.0, lam_a + 2.2 * R, lam_b)
    u = np.linspace(0.0, 1.0, 700)
    lam = lam_a[:, None] + (lam_b - lam_a)[:, None] * u[None, :]

    def blocked(off_min):
        a = np.deg2rad(psi + d.omega * off_min / 4.0)
        mark = np.stack([R * np.sin(a), R * np.cos(a), np.zeros(n)], axis=-1)
        pts = mark[:, None, :] + lam[:, :, None] * s[:, None, :]
        rr = np.hypot(pts[..., 0], pts[..., 1])
        rp = np.interp(pts[..., 2], z_prof, r_prof, left=-1.0, right=-1.0)
        return np.any(rr < rp - 1e-6, axis=1)

    lo_a = np.full(n, lo); hi_a = np.full(n, hi)
    for _ in range(steps):
        mid = 0.5 * (lo_a + hi_a)
        b = blocked(mid)
        lo_a = np.where(b, mid, lo_a)
        hi_a = np.where(b, hi_a, mid)
    return 0.5 * (lo_a + hi_a)


def _build_roller_profile(d: Design, name, label, ta, tb) -> RollerProfile:
    R = d.R
    t, s, psi, z_d, r_d = _roller_samples(d, ta, tb)
    alpha = np.arcsin(np.clip(r_d / R, -1.0, 1.0))
    z_grid = np.linspace(z_d.min(), z_d.max(), 1600)

    # The roller is the envelope (pointwise minimum) of the hyperboloids swept
    # by every day's ray: the largest surface of revolution that never blocks
    # a ray.  Near the solstices the hyperboloids overlap, so some days cannot
    # be tangent and would read slow.  A few balancing iterations raise the
    # targets of the neighbouring days so the residual error is shared.
    shift = np.zeros_like(alpha)          # radians added to each day's target
    h_window = 3.5                        # mm, range of hyperboloid interaction
    order = np.argsort(z_d)
    z_sorted = z_d[order]
    err = None
    r_env = None
    for it in range(4):
        r_t = R * np.sin(alpha + shift)
        r_env = _ray_distance_from_axis(z_grid, z_d, r_t, s).min(axis=0)
        # between two samples the true (continuous) envelope is close to the
        # interpolated tangent radius; without this cap the near-vertical
        # hyperboloids around the equinox leave the gaps unconstrained
        keep = np.concatenate([[True], np.diff(z_sorted) > 1e-4])
        r_cp = np.interp(z_grid, z_sorted[keep], r_t[order][keep])
        r_env = np.minimum(r_env, r_cp)
        err = _reading_errors(d, s, psi, z_grid, r_env, steps=16)
        if it == 3:
            break
        slow = np.maximum(-err, 0.0)
        fast = np.maximum(err, 0.0)
        lo = np.searchsorted(z_sorted, z_d - h_window)
        hi = np.searchsorted(z_sorted, z_d + h_window)
        S = np.array([slow[order[a:b]].max() if b > a else 0.0 for a, b in zip(lo, hi)])
        F = np.array([fast[order[a:b]].max() if b > a else 0.0 for a, b in zip(lo, hi)])
        delta_min = 0.5 * (S - F)
        shift = shift + np.deg2rad(delta_min / 4.0)
        shift = np.maximum(shift, 0.0)
    err = _reading_errors(d, s, psi, z_grid, r_env, steps=20)
    # resample for meshing: ~360 points, denser at the ends
    n_out = 360
    w = np.linspace(0.0, 1.0, n_out)
    w = 0.5 - 0.5 * np.cos(np.pi * w)
    z_out = z_grid[0] + (z_grid[-1] - z_grid[0]) * w
    r_out = np.interp(z_out, z_grid, r_env)
    return RollerProfile(name=name, label=label, z=z_out, r=r_out, days=t,
                         z_nodus=z_d, r_nodus=r_d, error_min=err,
                         balance=float(np.rad2deg(shift.max()) * 4.0))


def accuracy_report(d: Design, threshold_min: float = 1.0):
    """Date ranges where the reading error exceeds the threshold."""
    from datetime import datetime, timezone
    out = []
    for rp in d.rollers:
        bad = np.abs(rp.error_min) > threshold_min
        if not bad.any():
            continue
        idx = np.where(bad)[0]
        # group consecutive indices
        groups = np.split(idx, np.where(np.diff(idx) > 1)[0] + 1)
        for grp in groups:
            t0 = datetime.fromtimestamp(rp.days[grp[0]], timezone.utc)
            t1 = datetime.fromtimestamp(rp.days[grp[-1]], timezone.utc)
            e = rp.error_min[grp]
            k = int(np.argmax(np.abs(e)))
            out.append({"roller": rp.name, "from": t0.strftime("%d %b"), "to": t1.strftime("%d %b"),
                        "max_error_min": float(e[k]),
                        "sign": "fast" if e[k] > 0 else "slow"})
    return out


def sun_table(d, month: int, day: int, step_min: int = 5):
    """Sun vectors in ENU over one day of zone time, for the browser shadow view."""
    p = d.params
    hours = np.arange(0.0, 24.0, step_min / 60.0)
    t = solar.zone_time_to_unix(p.year, month, day, hours, p.utc_offset_h)
    v = solar.sun_vector_enu(t, p.lat, p.lon)
    return hours, v
