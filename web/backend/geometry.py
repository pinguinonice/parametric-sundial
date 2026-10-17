"""Thin wrapper around the original parametric-sundial script.

The heavy lifting (sun ephemeris + ray/gnomon geometry) lives in
``sundial/src/sundial/sundial.py``.  This module makes it importable, reshapes
the flat output arrays into something a web client can consume, and adds a small
helper for the live sun position used by the preview.
"""

from __future__ import annotations

import datetime as dt
import functools
import sys
from pathlib import Path

import numpy as np
from dateutil import tz as _tz
from timezonefinder import TimezoneFinder

_TF = TimezoneFinder()

# --- make the original module importable -------------------------------------
_SD_DIR = Path(__file__).resolve().parents[2] / "sundial" / "src" / "sundial"
if str(_SD_DIR) not in sys.path:
    sys.path.insert(0, str(_SD_DIR))

import sundial as _sd  # noqa: E402  (sundial/src/sundial/sundial.py)

# generateSundial() builds its date list as 24 hour-slots, each swept over 183
# days of the half-year.  So P has 24 * 183 rows, hour-major.
N_HOURS = 24
N_SEASON = 183
SEASONS = ("spring", "fall")


def _round(a: np.ndarray, nd: int = 6) -> list:
    return np.round(np.asarray(a, dtype=float), nd).tolist()


@functools.lru_cache(maxsize=64)
def _generate_cached(lat, lon, alt, radius, noon_offset, season):
    minScale, hourScale, P0, P1, P, noonTick = _sd.generateSundial(
        lat, lon, alt, radius, noon_offset, season
    )
    P = np.asarray(P, dtype=float)
    # Reshape the gnomon point cloud into a (hours, season, 3) surface grid.
    grid = None
    if P.shape[0] == N_HOURS * N_SEASON:
        grid = P.reshape(N_HOURS, N_SEASON, 3)
    return {
        "minScale": np.asarray(minScale, dtype=float),
        "hourScale": np.asarray(hourScale, dtype=float),
        "P0": np.asarray(P0, dtype=float),
        "P1": np.asarray(P1, dtype=float),
        "P": P,
        "grid": grid,
        "noonTick": np.asarray(noonTick, dtype=float),
    }


def generate(lat: float, lon: float, alt: float, radius: float,
             noon_offset: float, season: str) -> dict:
    """Run the model.  Returns raw numpy arrays (see ``_generate_cached``)."""
    if season not in SEASONS:
        raise ValueError(f"season must be one of {SEASONS}, got {season!r}")
    # round the cache key so tiny GPS jitter still hits the cache
    return _generate_cached(
        round(float(lat), 5), round(float(lon), 5), round(float(alt), 1),
        round(float(radius), 6), round(float(noon_offset), 4), season,
    )


def to_payload(lat, lon, alt, radius, noon_offset, season) -> dict:
    """JSON-serialisable version of :func:`generate` for the frontend."""
    g = generate(lat, lon, alt, radius, noon_offset, season)
    grid = g["grid"]
    return {
        "params": {
            "lat": lat, "lon": lon, "alt": alt, "radius": radius,
            "noonOffset": noon_offset, "season": season,
        },
        "minScale": _round(g["minScale"]),
        "hourScale": _round(g["hourScale"]),
        "noonTick": _round(g["noonTick"]),
        "gnomonAxis": [_round(g["P0"][0]), _round(g["P1"][0])],
        # (hours, season, 3) or null if the model bailed out early
        "gnomonGrid": None if grid is None else _round(grid),
        "grid": {"hours": N_HOURS, "season": N_SEASON},
    }


def sun_enu(lat: float, lon: float, alt: float,
            when: dt.datetime | None = None) -> dict:
    """Unit vector to the sun in local East-North-Up, plus elevation/azimuth."""
    if when is None:
        when = dt.datetime.now(dt.timezone.utc)
    elif when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    _, _, _, e, n, u = _sd.zero2sun(lat, lon, alt, [when])
    v = np.array([float(e[0]), float(n[0]), float(u[0])])
    norm = float(np.linalg.norm(v)) or 1.0
    unit = v / norm
    elev = float(np.degrees(np.arcsin(np.clip(unit[2], -1, 1))))
    azi = float((np.degrees(np.arctan2(unit[0], unit[1]))) % 360.0)
    return {
        "time": when.astimezone(dt.timezone.utc).isoformat(),
        "enu": unit.tolist(),
        "elevation": elev,
        "azimuth": azi,
        "up": elev > 0,
    }


def utc_offset_min(lat: float, lon: float, on: dt.date) -> int:
    """Standard/DST UTC offset (minutes) for a location on a given date."""
    name = _TF.timezone_at(lng=lon, lat=lat) or _TF.closest_timezone_at(lng=lon, lat=lat)
    if not name:
        return 0
    z = _tz.gettz(name)
    noon = dt.datetime(on.year, on.month, on.day, 12, tzinfo=z)
    off = noon.utcoffset()
    return int(off.total_seconds() // 60) if off else 0


def sun_path(lat: float, lon: float, alt: float, date: dt.date,
             step_min: int = 5) -> dict:
    """Sun track across one calendar day (UTC), sampled every ``step_min``."""
    base = dt.datetime(date.year, date.month, date.day, tzinfo=dt.timezone.utc)
    times = [base + dt.timedelta(minutes=m)
             for m in range(0, 24 * 60, step_min)]
    _, _, _, e, n, u = _sd.zero2sun(lat, lon, alt, times)
    e, n, u = np.asarray(e), np.asarray(n), np.asarray(u)
    norm = np.linalg.norm(np.stack([e, n, u], axis=1), axis=1)
    norm[norm == 0] = 1.0
    samples = []
    for i, t in enumerate(times):
        unit = [float(e[i] / norm[i]), float(n[i] / norm[i]), float(u[i] / norm[i])]
        samples.append({
            "minute": i * step_min,
            "iso": t.isoformat(),
            "enu": [round(c, 6) for c in unit],
            "elevation": round(float(np.degrees(np.arcsin(np.clip(unit[2], -1, 1)))), 3),
        })
    return {
        "date": date.isoformat(),
        "stepMin": step_min,
        "utcOffsetMin": utc_offset_min(lat, lon, date),
        "samples": samples,
    }
