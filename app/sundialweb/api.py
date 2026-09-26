"""FastAPI application: JSON API plus the static frontend."""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import solar
from .design import DesignParams, build_design, sun_table, accuracy_report
from .meshing import BodyGeometry, build_all, dish_depth, shadowed_days_report, continuity_report

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"
CACHE_DIR = Path(os.environ.get("SUNDIAL_CACHE", os.path.join(tempfile.gettempdir(), "sundial-web")))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_VERSION = "10"  # bump when the geometry changes so cached results are rebuilt

app = FastAPI(title="Bernhardt sundial generator", version="1.0")


class GenerateRequest(BaseModel):
    lat: float = Field(..., ge=-89.9, le=89.9)
    lon: float = Field(..., ge=-180.0, le=180.0)
    utc_offset_h: float = Field(..., ge=-14.0, le=14.0)
    zone_label: str = ""
    summer_label: str = ""
    year: int = Field(default_factory=lambda: datetime.now(timezone.utc).year, ge=1900, le=2200)
    scale_radius: float = Field(75.0, ge=30.0, le=250.0)
    min_roller_radius: float = Field(4.0, ge=2.0, le=15.0)
    hour_first: Optional[int] = Field(None, ge=1, le=11)
    hour_last: Optional[int] = Field(None, ge=13, le=23)
    engrave: bool = True


def _timezone_info(lat: float, lon: float):
    """Standard (non-DST) offset of the time zone at a location."""
    try:
        from timezonefinder import TimezoneFinder
        from zoneinfo import ZoneInfo
        name = TimezoneFinder().timezone_at(lat=lat, lng=lon)
    except Exception:  # pragma: no cover - optional dependency
        name = None
    if not name:
        off = round(lon / 15.0)
        return {"tz": None, "utc_offset_h": float(off), "label": f"UTC{off:+d}", "dst": False}
    from zoneinfo import ZoneInfo
    z = ZoneInfo(name)
    year = datetime.now(timezone.utc).year
    jan = datetime(year, 1, 15, 12, tzinfo=z)
    jul = datetime(year, 7, 15, 12, tzinfo=z)
    o_jan = jan.utcoffset().total_seconds() / 3600.0
    o_jul = jul.utcoffset().total_seconds() / 3600.0
    std = min(o_jan, o_jul)
    std_dt = jan if o_jan <= o_jul else jul
    dst_dt = jul if o_jan <= o_jul else jan
    abbr = std_dt.tzname() or ""
    if abbr.startswith(("+", "-")) or not abbr:
        abbr = ""
    summer = ""
    if o_jan != o_jul:
        summer = dst_dt.tzname() or ""
        if summer.startswith(("+", "-")) or not summer:
            o = max(o_jan, o_jul); hs = int(abs(o)); ms = int(round((abs(o) - hs) * 60))
            summer = f"UTC{'+' if o >= 0 else '-'}{hs}" + (f":{ms:02d}" if ms else "")
    sign = "+" if std >= 0 else "-"
    h = int(abs(std)); m = int(round((abs(std) - h) * 60))
    utc = f"UTC{sign}{h}" + (f":{m:02d}" if m else "")
    label = f"{abbr}  {utc}" if abbr else utc
    return {"tz": name, "utc_offset_h": std, "label": label, "dst": o_jan != o_jul, "abbr": abbr, "utc": utc, "summer_label": summer}


@app.get("/api/timezone")
def api_timezone(lat: float, lon: float):
    return _timezone_info(lat, lon)


@app.get("/api/sun")
def api_sun(lat: float, lon: float, utc_offset_h: float, year: int, month: int, day: int, step_min: int = 5):
    p = DesignParams(lat=lat, lon=lon, utc_offset_h=utc_offset_h, year=year)
    hours, v = sun_table(build_design_light(p), month, day, step_min)
    return {"hours": hours.tolist(), "enu": np.round(v, 5).tolist()}


def build_design_light(p: DesignParams):
    # sun_table only needs the params, avoid the full design
    class _D:  # minimal duck type
        params = p
    return _D()


def _matrix_rows(M):
    return [[float(x) for x in row] for row in np.asarray(M)]


def _assembly(d, parts):
    lat = d.params.lat
    s = 1.0 if lat >= 0 else -1.0
    frame = solar.dial_frame(lat)          # rows = dial axes in ENU
    stand_rot = np.diag([s, s, 1.0])
    centre_stand = np.array(parts["stand_info"]["dial_centre"])
    centre_enu = stand_rot @ centre_stand
    dial_to_world = np.eye(4)
    dial_to_world[:3, :3] = frame.T
    dial_to_world[:3, 3] = centre_enu
    stand_to_world = np.eye(4)
    stand_to_world[:3, :3] = stand_rot
    rollers = {}
    g = parts["geometry"]
    hub_top = parts["dial_info"]["hub_top_z"]
    for name, mesh, inf in parts["rollers"]:
        r2d = np.eye(4)
        r2d[2, 3] = hub_top - g.pin_len
        rollers[name] = _matrix_rows(dial_to_world @ r2d)
    return {"dial_to_world": _matrix_rows(dial_to_world),
            "stand_to_world": _matrix_rows(stand_to_world),
            "rollers_to_world": rollers,
            "dial_centre_enu": centre_enu.tolist()}


def generate(req: GenerateRequest):
    key = hashlib.sha1((CACHE_VERSION + json.dumps(req.model_dump(), sort_keys=True)).encode()).hexdigest()[:16]
    out = CACHE_DIR / key
    meta_path = out / "info.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text())
    out.mkdir(parents=True, exist_ok=True)

    p = DesignParams(lat=req.lat, lon=req.lon, utc_offset_h=req.utc_offset_h, year=req.year, summer_label=req.summer_label,
                     scale_radius=req.scale_radius, min_roller_radius=req.min_roller_radius,
                     hour_first=req.hour_first, hour_last=req.hour_last,
                     zone_label=req.zone_label.strip())
    d = build_design(p)
    parts = build_all(d, engrave=req.engrave)
    g: BodyGeometry = parts["geometry"]

    files = {}
    stl_names = {}
    parts["dial"].export(out / "dial.stl")
    stl_names["dial"] = "dial.stl"
    for name, mesh, inf in parts["rollers"]:
        mesh.export(out / f"{name}.stl")
        stl_names[name] = f"{name}.stl"
    parts["stand"].export(out / "stand.stl")
    stl_names["stand"] = "stand.stl"
    for k, fn in stl_names.items():
        files[k] = f"/api/files/{key}/{fn}"

    bounds = {k: parts[k].bounds.tolist() for k in ("dial", "stand")}
    for name, mesh, inf in parts["rollers"]:
        bounds[name] = mesh.bounds.tolist()

    warnings = []
    if abs(req.lat) < 27:
        warnings.append("Below about 27 degrees latitude the winter sun no longer stays on the open side of the crescent, so winter readings get shadowed by the dial body. The design is meant for 27 to 66 degrees.")
    elif abs(req.lat) < 35:
        warnings.append("Low latitude: the stand is tall and the early/late hours are shadowed for a few weeks around the equinoxes.")
    if abs(req.lat) > 66:
        warnings.append("Inside the polar circle the hour range is clamped to 3 to 21.")
    if req.scale_radius < 60:
        warnings.append("Small dial: the equation-of-time bulge on the roller is only a few millimetres, expect about 5 minute accuracy.")
    if d.params.hour_first is not None and (d.params.hour_first > math.floor(d.sunrise_earliest) or d.params.hour_last < math.ceil(d.sunset_latest)):
        warnings.append("Manual hour range is narrower than the summer day at this location.")

    info = {
        "id": key,
        "files": files,
        "zip": f"/api/files/{key}/sundial.zip",
        "params": req.model_dump(),
        "design": {
            "omega": d.omega,
            "psi_noon_deg": d.psi_noon,
            "hour_first": d.hour_first,
            "hour_last": d.hour_last,
            "sunrise_earliest": d.sunrise_earliest,
            "sunset_latest": d.sunset_latest,
            "roller_r_min": d.min_roller_r,
            "roller_r_max": d.max_roller_r,
            "roller_z_min": float(min(r.z.min() for r in d.rollers)),
            "roller_z_max": float(max(r.z.max() for r in d.rollers)),
            "rollers": [{"name": r.name, "label": r.label} for r in d.rollers],
            "dish_depth": dish_depth(g, d),
            "scale_radius": d.R,
            "outer_radius": g.R_out,
            "tilt_deg": parts["stand_info"]["tilt_deg"],
            "stem_length": parts["stand_info"]["stem_length"],
            "base_radius": parts["stand_info"]["base_radius"],
            "plate_bounds": parts["stand_info"]["plate_bounds"],
            "plate_thickness": parts["stand_info"]["plate_thickness"],
            "base_centre_y": parts["stand_info"]["base_centre_y"],
            "thread": parts["rollers"][0][2]["thread"],
            "minute_ticks": d.R * math.pi / 720.0 >= 0.7,
        },
        "stability": parts["stand_info"]["stability"],
        "bounds": bounds,
        "assembly": _assembly(d, parts),
        "accuracy": accuracy_report(d, 1.0),
        "profiles": {rp.name: {"z": np.round(np.interp(np.linspace(0, 1, 120), np.linspace(0, 1, len(rp.z)), rp.z), 3).tolist(),
                               "r": np.round(np.interp(np.linspace(0, 1, 120), np.linspace(0, 1, len(rp.r)), rp.r), 3).tolist()}
                     for rp in d.rollers},
        "shadowed": shadowed_days_report(d, g, parts["dial_info"]["surface"]),
        "continuity": continuity_report(parts),
        "warnings": warnings,
    }
    # README for the zip
    readme = _readme(info)
    (out / "README.txt").write_text(readme)
    with zipfile.ZipFile(out / "sundial.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for fn in list(stl_names.values()) + ["README.txt"]:
            zf.write(out / fn, arcname=fn)
    meta_path.write_text(json.dumps(info))
    return info


def _readme(info):
    d = info["design"]; p = info["params"]
    acc = "\n".join(f"    {a['from']} - {a['to']}: up to {abs(a['max_error_min']):.1f} min {a['sign']}"
                    for a in info["accuracy"]) or "    none"
    sh = "\n".join(f"    {x['from']} - {x['to']} ({x['hours']})" for x in info["shadowed"]) or "    none"
    zone = p["zone_label"] or "UTC%+g" % p["utc_offset_h"]
    stab = info["stability"]; thr = d["thread"]
    pb = d["plate_bounds"]; pw, pl = pb[2] - pb[0], pb[3] - pb[1]
    summer_note = (f"  The outer row of numerals is standard time ({zone}); the inner row is summer\n  time ({p['summer_label']})."
                   if p.get("summer_label") else "  The scale shows standard time; this zone keeps no summer time.")
    pole = "north" if p["lat"] >= 0 else "south"
    return f"""Bernhardt precision sundial, generated for
  latitude {p['lat']:.4f}, longitude {p['lon']:.4f}, zone {zone}
  reading circle radius {d['scale_radius']:.1f} mm, hours {d['hour_first']} to {d['hour_last']}

Parts
  dial.stl      crescent dial with hub. Print scale side up, tree supports under the wings.
  roller_1.stl  gnomon for 21 December to 21 June (one groove on the collar).
  roller_2.stl  gnomon for 21 June to 21 December (two grooves).
  stand.stl     base plate in the shape of your noon analemma (the figure the sun traces
                at twelve o'clock over a year, engraved with its months), with the stem
                rising from one loop and bending into the polar axis ({d['tilt_deg']:.1f} degrees),
                keyed pin, and the location in degrees, minutes and seconds. The plate is
                {pw:.0f} x {pl:.0f} mm and sized so the assembled dial can be tilted
                {stab['required_tip_angle_deg']:.0f} degrees before it tips (this one: {stab['tip_angle_deg']:.0f} degrees,
                {stab['margin_mm']:.0f} mm of footprint beyond the centre of mass).

Assembly
  Put the dial on the stand pin (the flat on the pin keys the orientation).
  Level the plate, point its long axis exactly towards {pole} (true, not magnetic).
  Screw in the roller for the current half year until its collar seats on the hub: the
  thread is a coarse rounded one ({thr['pitch']:.1f} mm pitch, {thr['clearance']:.1f} mm clearance)
  that prints without calibration; the collar, not the thread, sets the height.
  Read the time at the LEADING edge of the roller's shadow on the outer ring, where it
  crosses the tick ends.
{summer_note}
  Swap the roller at each solstice.

Accuracy
  Within a few tenths of a minute, except near the solstices where the equation of
  time changes while the sun's declination stalls; no roller can then be tangent to
  every ray (Glaeser & Hofmann 2004):
{acc}
  Around the equinoxes the low sun skims the wing tips for a few days, shadowing the
  first and last hour of the day:
{sh}
"""


@app.post("/api/generate")
def api_generate(req: GenerateRequest):
    try:
        return generate(req)
    except Exception as exc:  # surface the reason to the UI
        raise HTTPException(status_code=500, detail=f"generation failed: {exc}")


@app.get("/api/files/{key}/{name}")
def api_file(key: str, name: str):
    if not (key.isalnum() and name.replace(".", "").replace("_", "").isalnum()):
        raise HTTPException(404)
    path = CACHE_DIR / key / name
    if not path.exists():
        raise HTTPException(404)
    media = "application/zip" if name.endswith(".zip") else "model/stl"
    return FileResponse(path, media_type=media, filename=name)


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
