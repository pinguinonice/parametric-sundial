"""Sun position without external dependencies.

Uses the NOAA / Meeus low-precision solar algorithm. Accuracy is about
0.01 deg in solar longitude and a few seconds in the equation of time for
the years 1900..2100, which is far below the one-minute resolution of the
dial.

All angles are degrees unless stated otherwise. Times are UTC.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

_J2000 = 2451545.0
_UNIX_J2000 = 946728000.0  # 2000-01-01 12:00 UTC


def unix_to_jd(unix_s):
    """Julian day from unix seconds (scalar or array)."""
    return _J2000 + (np.asarray(unix_s, dtype=float) - _UNIX_J2000) / 86400.0


def dt_to_unix(dt: datetime) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def sun_geometry(unix_s):
    """Declination (deg) and equation of time (minutes, true minus mean)."""
    jd = unix_to_jd(unix_s)
    T = (jd - _J2000) / 36525.0
    L0 = np.mod(280.46646 + T * (36000.76983 + T * 0.0003032), 360.0)
    M = np.deg2rad(357.52911 + T * (35999.05029 - 0.0001537 * T))
    e = 0.016708634 - T * (0.000042037 + 0.0000001267 * T)
    C = (np.sin(M) * (1.914602 - T * (0.004817 + 0.000014 * T))
         + np.sin(2 * M) * (0.019993 - 0.000101 * T)
         + np.sin(3 * M) * 0.000289)
    true_long = L0 + C
    omega = np.deg2rad(125.04 - 1934.136 * T)
    app_long = np.deg2rad(true_long - 0.00569 - 0.00478 * np.sin(omega))
    eps0 = 23.0 + (26.0 + (21.448 - T * (46.815 + T * (0.00059 - T * 0.001813))) / 60.0) / 60.0
    eps = np.deg2rad(eps0 + 0.00256 * np.cos(omega))
    decl = np.arcsin(np.sin(eps) * np.sin(app_long))
    y = np.tan(eps / 2.0) ** 2
    L0r = np.deg2rad(L0)
    eot = (y * np.sin(2 * L0r) - 2 * e * np.sin(M) + 4 * e * y * np.sin(M) * np.cos(2 * L0r)
           - 0.5 * y * y * np.sin(4 * L0r) - 1.25 * e * e * np.sin(2 * M))
    eot_min = 4.0 * np.rad2deg(eot)
    return np.rad2deg(decl), eot_min


def hour_angle(unix_s, lon_deg):
    """True solar hour angle (deg, 0 at local apparent noon, positive afternoon)."""
    _, eot = sun_geometry(unix_s)
    u = np.asarray(unix_s, dtype=float)
    minutes_utc = np.mod(u, 86400.0) / 60.0
    tst = minutes_utc + eot + 4.0 * lon_deg  # true solar time in minutes
    H = tst / 4.0 - 180.0
    return np.mod(H + 180.0, 360.0) - 180.0


def sun_vector_enu(unix_s, lat_deg, lon_deg):
    """Unit vector to the sun in the local East/North/Up frame. Shape (..., 3)."""
    decl, _ = sun_geometry(unix_s)
    H = np.deg2rad(hour_angle(unix_s, lon_deg))
    d = np.deg2rad(decl)
    p = np.deg2rad(lat_deg)
    east = -np.cos(d) * np.sin(H)
    north = np.sin(d) * np.cos(p) - np.cos(d) * np.cos(H) * np.sin(p)
    up = np.sin(d) * np.sin(p) + np.cos(d) * np.cos(H) * np.cos(p)
    return np.stack([east, north, up], axis=-1)


def dial_frame(lat_deg):
    """Rows: dial x, y, z axes expressed in ENU.

    z points to the elevated celestial pole, y is the shadow direction at
    true noon (pole-ward and down along the equatorial plane), x = y cross z.
    The frame is right-handed for both hemispheres.
    """
    p = np.deg2rad(lat_deg)
    s = 1.0 if lat_deg >= 0 else -1.0
    z = s * np.array([0.0, np.cos(p), np.sin(p)])
    y = np.array([0.0, np.sin(p), -np.cos(p)])
    x = np.cross(y, z)
    return np.array([x, y, z])


def enu_to_dial(v_enu, lat_deg):
    return np.asarray(v_enu) @ dial_frame(lat_deg).T


def zone_time_to_unix(year, month, day, hour_float, utc_offset_h):
    base = datetime(year, month, day, tzinfo=timezone.utc)
    return dt_to_unix(base) + (hour_float - utc_offset_h) * 3600.0


def solstices(year):
    """Unix times of the December solstice before and the June and December
    solstices of `year` (found by declination extrema)."""
    def extremum(t0, t1, sign):
        t = np.arange(t0, t1, 600.0)
        d, _ = sun_geometry(t)
        i = int(np.argmax(sign * d))
        return float(t[i])
    y0 = dt_to_unix(datetime(year - 1, 12, 1, tzinfo=timezone.utc))
    y1 = dt_to_unix(datetime(year, 1, 10, tzinfo=timezone.utc))
    dec_prev = extremum(y0, y1, -1.0)
    j0 = dt_to_unix(datetime(year, 6, 1, tzinfo=timezone.utc))
    j1 = dt_to_unix(datetime(year, 7, 10, tzinfo=timezone.utc))
    jun = extremum(j0, j1, +1.0)
    d0 = dt_to_unix(datetime(year, 12, 1, tzinfo=timezone.utc))
    d1 = dt_to_unix(datetime(year + 1, 1, 10, tzinfo=timezone.utc))
    dec = extremum(d0, d1, -1.0)
    return dec_prev, jun, dec
