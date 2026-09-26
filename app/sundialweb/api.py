"""FastAPI application: JSON API plus the static frontend."""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import queue
import re
import statistics
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import solar
from .design import DesignParams, build_design, sun_table, accuracy_report
from .meshing import BodyGeometry, build_all, dish_depth, shadowed_days_report, continuity_report

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"
CACHE_DIR = Path(os.environ.get("SUNDIAL_CACHE", os.path.join(tempfile.gettempdir(), "sundial-web")))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_VERSION = "13"  # bump when the geometry changes so cached results are rebuilt

app = FastAPI(title="Bernhardt sundial generator", version="1.0")
app.add_middleware(GZipMiddleware, minimum_size=1000)

VIEWER_FACES = {"dial": 60000, "roller_1": 24000, "roller_2": 24000, "stand": 24000}


def viewer_glb(meshes: dict) -> bytes:
    """One small GLB with all four parts for the browser: the print meshes
    decimated to a few tens of thousands of faces each (2 MB instead of
    28 MB of STL), vertex data untouched in orientation."""
    import trimesh
    slim = {}
    for name, m in meshes.items():
        target = VIEWER_FACES.get(name, 30000)
        try:
            slim[name] = m.simplify_quadric_decimation(face_count=target) if len(m.faces) > target else m
        except Exception:   # decimation library missing: ship the full mesh
            slim[name] = m
    return trimesh.Scene(slim).export(file_type="glb")


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
    place_name: str = Field("", max_length=120)   # for the zip name and the readme, not engraved
    tz_name: str = Field("", max_length=64)       # IANA zone, so the viewer can show "now" with summer time


def _slug(text: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").lower()
    return t[:40] or "sundial"


PLA_DENSITY = 1.24   # g/cm3
BEDS_MM = (180, 220, 250, 300, 350, 400)


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


_design_cache: dict = {}
_design_lock = threading.Lock()


@app.get("/api/design")
def api_design(lat: float, lon: float, utc_offset_h: float, year: int = 2026, scale_radius: float = 75.0,
               min_roller_radius: float = 4.0, hour_first: Optional[int] = None, hour_last: Optional[int] = None):
    """The dial's facts without any meshing: hour range, longest day, roller
    radii, accuracy.  Takes a few seconds, cached in memory."""
    key = json.dumps([round(lat, 4), round(lon, 4), utc_offset_h, year, scale_radius, min_roller_radius, hour_first, hour_last])
    with _design_lock:
        hit = _design_cache.get(key)
    if hit:
        return hit
    p = DesignParams(lat=lat, lon=lon, utc_offset_h=utc_offset_h, year=year, scale_radius=scale_radius,
                     min_roller_radius=min_roller_radius, hour_first=hour_first, hour_last=hour_last)
    d = build_design(p)
    out = {
        "hour_first": d.hour_first, "hour_last": d.hour_last,
        "sunrise_earliest": d.sunrise_earliest, "sunset_latest": d.sunset_latest,
        "roller_r_min": d.min_roller_r, "roller_r_max": d.max_roller_r,
        "roller_z_min": float(min(r.z.min() for r in d.rollers)), "roller_z_max": float(max(r.z.max() for r in d.rollers)),
        "tilt_deg": abs(lat), "minute_ticks": d.R * math.pi / 720.0 >= 0.7,
        "accuracy": accuracy_report(d, 1.0),
        "profiles": _profiles(d),
        "warnings": _warnings(lat, scale_radius, d),
    }
    with _design_lock:
        if len(_design_cache) > 200:
            _design_cache.clear()
        _design_cache[key] = out
    return out


def _profiles(d):
    return {rp.name: {"z": np.round(np.interp(np.linspace(0, 1, 120), np.linspace(0, 1, len(rp.z)), rp.z), 3).tolist(),
                      "r": np.round(np.interp(np.linspace(0, 1, 120), np.linspace(0, 1, len(rp.r)), rp.r), 3).tolist()}
            for rp in d.rollers}


def _warnings(lat, scale_radius, d):
    warnings = []
    if abs(lat) < 27:
        warnings.append("Below about 27 degrees latitude the winter sun no longer stays on the open side of the crescent, so winter readings get shadowed by the dial body. The design is meant for 27 to 66 degrees.")
    elif abs(lat) < 35:
        warnings.append("Low latitude: the stand is tall and the early/late hours are shadowed for a few weeks around the equinoxes.")
    if abs(lat) > 66:
        warnings.append("Inside the polar circle the hour range is clamped to 3 to 21.")
    if scale_radius < 60:
        warnings.append("Small dial: the equation-of-time bulge on the roller is only a few millimetres, expect about 5 minute accuracy.")
    if d.params.hour_first is not None and (d.params.hour_first > math.floor(d.sunrise_earliest) or d.params.hour_last < math.ceil(d.sunset_latest)):
        warnings.append("Manual hour range is narrower than the summer day at this location.")
    return warnings


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


def _cache_key(req: GenerateRequest) -> str:
    geo = req.model_dump(exclude={"place_name", "tz_name"})   # names change no geometry
    return hashlib.sha1((CACHE_VERSION + json.dumps(geo, sort_keys=True)).encode()).hexdigest()[:16]


def _cached(req: GenerateRequest):
    meta_path = CACHE_DIR / _cache_key(req) / "info.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text())
    return None


STAGES = ("design", "dial", "roller_1", "roller_2", "stand", "export")


def generate(req: GenerateRequest, progress=None):
    key = _cache_key(req)
    out = CACHE_DIR / key
    meta_path = out / "info.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text())
    out.mkdir(parents=True, exist_ok=True)
    tell = progress or (lambda stage: None)
    tell("design")

    p = DesignParams(lat=req.lat, lon=req.lon, utc_offset_h=req.utc_offset_h, year=req.year, summer_label=req.summer_label,
                     scale_radius=req.scale_radius, min_roller_radius=req.min_roller_radius,
                     hour_first=req.hour_first, hour_last=req.hour_last,
                     zone_label=req.zone_label.strip())
    d = build_design(p)
    parts = build_all(d, engrave=req.engrave, progress=tell)
    g: BodyGeometry = parts["geometry"]
    tell("export")

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

    meshes = {"dial": parts["dial"], "stand": parts["stand"], **{name: mesh for name, mesh, inf in parts["rollers"]}}
    (out / "viewer.glb").write_bytes(viewer_glb(meshes))
    files["glb"] = f"/api/files/{key}/viewer.glb"
    bounds = {k: m.bounds.tolist() for k, m in meshes.items()}
    # print facts per part: the meshes are already in print orientation
    # (dial scale side up, rollers pin down, stand plate down)
    part_facts = {}
    for k, m in meshes.items():
        ext = (m.bounds[1] - m.bounds[0]).tolist()
        vol = float(abs(m.volume)) / 1000.0
        part_facts[k] = {"size_mm": [round(x, 1) for x in ext], "volume_cm3": round(vol, 1),
                         "weight_g": round(vol * PLA_DENSITY), "footprint_mm": round(max(ext[0], ext[1]), 1)}
    largest = max(f["footprint_mm"] for f in part_facts.values())
    bed_mm = next((b for b in BEDS_MM if b >= largest + 10), BEDS_MM[-1])
    warnings = _warnings(req.lat, req.scale_radius, d)
    zip_name = f"sundial-{_slug(req.place_name) if req.place_name else _slug(location_text_short(req.lat, req.lon))}-{int(round(2 * d.R))}mm.zip"

    info = {
        "id": key,
        "files": files,
        "zip": f"/api/files/{key}/sundial.zip",
        "zip_name": zip_name,
        "parts": part_facts,
        "bed_mm": bed_mm,
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
        "profiles": _profiles(d),
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
    info["zip_bytes"] = (out / "sundial.zip").stat().st_size
    meta_path.write_text(json.dumps(info))
    return info


def site_notes(lang: str = "en") -> dict:
    """Print notes and setup steps from the site's own strings (web/i18n.js),
    so the README and the page never drift apart."""
    out = {"print": [], "steps": []}
    try:
        src = (WEB_DIR / "i18n.js").read_text()
        m = re.search(r"^S\.%s = \{\n(.*?)\n\};" % re.escape(lang), src, re.S | re.M)
        block = m.group(1) if m else ""
        def get(key):
            mm = re.search(r"(?<![A-Za-z0-9_])%s: '((?:[^'\\]|\\.)*)'" % key, block)
            return mm.group(1).replace("\\'", "'") if mm else ""
        out["print"] = [get(f"pn{i}") for i in range(1, 6) if get(f"pn{i}")]
        out["steps"] = [(get(f"s{i}h"), get(f"s{i}p")) for i in range(1, 5) if get(f"s{i}h")]
    except Exception:
        pass
    return out


@app.get("/api/notes")
def api_notes(lang: str = "en"):
    return site_notes(lang if re.fullmatch(r"[a-z]{2}", lang or "") else "en")


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
    notes = site_notes("en")
    place = (p.get("place_name") or "").strip()
    return f"""Bernhardt precision sundial, generated for
  {place + chr(10) + "  " if place else ""}latitude {p['lat']:.4f}, longitude {p['lon']:.4f}, zone {zone}
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

Printing
{chr(10).join("  " + n for n in notes["print"])}

Setting it up
{chr(10).join(f"  {i + 1}. {h}: {t}" for i, (h, t) in enumerate(notes["steps"]))}

Assembly
  Put the dial on the stand pin (the flat on the pin keys the orientation).
  Level the plate, point its long axis exactly towards {pole} (true, not magnetic).
  Screw in the roller for the current half year until its bell seats on the hub: the
  thread is a coarse rounded one ({thr['pitch']:.1f} mm pitch, {thr['clearance']:.1f} mm clearance)
  that prints without calibration; the collar, not the thread, sets the height.
  Stand on the {pole} side, where the dial's face tilts towards you: the numerals have their
  tops towards the hub and the hours run from right to left. Read the time at the LEADING
  edge of the roller's shadow on the outer ring, where it crosses the tick ends.
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


def location_text_short(lat, lon):
    return f"{abs(lat):.2f}{'N' if lat >= 0 else 'S'}-{abs(lon):.2f}{'E' if lon >= 0 else 'W'}"


# ---------------------------------------------------------------- jobs
# One worker thread builds dials in order; the browser follows a job by
# server-sent events.  Stage durations of the last builds give the estimate
# the progress bar moves on between events.

_jobs: dict = {}
_job_queue: "queue.Queue[str]" = queue.Queue()
_jobs_lock = threading.Lock()
_worker_started = False
MAX_QUEUE = int(os.environ.get("SUNDIAL_MAX_QUEUE", "12"))        # dials waiting at once
MAX_PER_CLIENT = int(os.environ.get("SUNDIAL_MAX_PER_CLIENT", "2"))  # pending dials per address


def _latest_path():
    return CACHE_DIR / "latest.json"


def _log_path():
    return CACHE_DIR / "creations.jsonl"


def _log_creation(req: GenerateRequest, session: str, client: str, cached: bool):
    """Internal log of every dial asked for: one JSON line each.  The session
    and client are hashed; the log never leaves the server as is."""
    rec = {"t": round(time.time(), 1), "lat": round(req.lat, 4), "lon": round(req.lon, 4), "place": req.place_name[:80],
           "mm": int(round(2 * req.scale_radius)), "year": req.year, "cached": cached,
           "session": hashlib.sha1(("s:" + session).encode()).hexdigest()[:12] if session else "",
           "client": hashlib.sha1(("c:" + client).encode()).hexdigest()[:12] if client else ""}
    try:
        with _log_path().open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


HISTORY_MIN_GAP_S = 60.0   # on the public map a session places at most one dial per minute


@app.get("/api/history")
def api_history(limit: int = 500):
    """Where dials have been made so far, for the map: coordinates rounded
    to a tenth of a degree, no identities, at most one entry per session
    per minute."""
    rows = []
    try:
        for line in _log_path().read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        rows = []
    last_by_session = {}
    out = []
    for r in rows:
        sid = r.get("session") or r.get("client") or ""
        if sid and r["t"] - last_by_session.get(sid, -1e12) < HISTORY_MIN_GAP_S:
            continue
        if sid:
            last_by_session[sid] = r["t"]
        out.append({"lat": round(r["lat"], 1), "lon": round(r["lon"], 1), "place": r.get("place", ""), "mm": r.get("mm"), "t": int(r["t"])})
    places = {(p["lat"], p["lon"]) for p in out}
    return {"count": len(out), "places": len(places), "items": out[-limit:]}


def _note_latest(info):
    """Remember the dial most recently asked for, so newcomers see a real one."""
    try:
        _latest_path().write_text(json.dumps({"id": info["id"], "made_at": time.time()}))
    except Exception:
        pass


@app.get("/api/latest")
def api_latest():
    """The last dial anyone generated (or fetched), with its age in seconds."""
    try:
        rec = json.loads(_latest_path().read_text())
        info = json.loads((CACHE_DIR / rec["id"] / "info.json").read_text())
    except Exception:
        raise HTTPException(404, "nothing made yet")
    return {"age_s": round(time.time() - rec["made_at"]), "info": info}


def _timings_path():
    return CACHE_DIR / "timings.json"


def _load_timings():
    try:
        return json.loads(_timings_path().read_text())
    except Exception:
        return []


def stage_estimates():
    """Median seconds per stage over the last ten builds, with defaults for
    a fresh server."""
    est = {"design": 4.0, "dial": 25.0, "roller_1": 6.0, "roller_2": 6.0, "stand": 20.0, "export": 2.0}
    runs = _load_timings()[-10:]
    for st in STAGES:
        vals = [r[st] for r in runs if st in r]
        if vals:
            est[st] = round(statistics.median(vals), 1)
    return est


def _record_timings(marks):
    """marks: list of (stage, t_start); the last stage ends at now."""
    durs = {}
    for i, (st, t0) in enumerate(marks):
        t1 = marks[i + 1][1] if i + 1 < len(marks) else time.time()
        durs[st] = round(t1 - t0, 2)
    runs = _load_timings()[-19:] + [durs]
    try:
        _timings_path().write_text(json.dumps(runs))
    except Exception:
        pass


def _worker():
    while True:
        jid = _job_queue.get()
        with _jobs_lock:
            job = _jobs.get(jid)
        if not job:
            continue
        marks = []

        def progress(stage):
            marks.append((stage, time.time()))
            with _jobs_lock:
                job["stage"] = stage
                job["stage_started"] = time.time()
                job["done_stages"] = [m[0] for m in marks[:-1]]
        with _jobs_lock:
            job["status"] = "running"; job["started"] = time.time()
        try:
            info = generate(job["req"], progress)
            _record_timings(marks)
            _note_latest(info)
            if job.get("session") or job.get("client"):   # the warm-up dial is not a creation
                _log_creation(job["req"], job.get("session", ""), job.get("client", ""), cached=False)
            with _jobs_lock:
                job["status"] = "done"; job["info"] = info; job["done_stages"] = list(STAGES); job["stage"] = None
        except Exception as exc:
            with _jobs_lock:
                job["status"] = "failed"; job["error"] = f"generation failed: {exc}"
        finally:
            with _jobs_lock:
                job["finished"] = time.time()


def _ensure_worker():
    global _worker_started
    with _jobs_lock:
        if _worker_started:
            return
        _worker_started = True
    threading.Thread(target=_worker, name="sundial-builder", daemon=True).start()


def _job_view(jid):
    with _jobs_lock:
        job = _jobs.get(jid)
        if not job:
            return None
        ahead = 0
        if job["status"] == "queued":
            ahead = sum(1 for j in _jobs.values() if j["status"] == "queued" and j["created"] < job["created"])
            ahead += sum(1 for j in _jobs.values() if j["status"] == "running")
        view = {"job": jid, "status": job["status"], "stage": job.get("stage"), "done_stages": job.get("done_stages", []),
                "ahead": ahead, "stage_elapsed": round(time.time() - job["stage_started"], 1) if job.get("stage_started") else 0.0,
                "error": job.get("error")}
        if job["status"] == "done":
            view["info"] = job["info"]
        return view


def _prune_jobs():
    now = time.time()
    with _jobs_lock:
        for jid in [j for j, job in _jobs.items() if job.get("finished") and now - job["finished"] > 1800]:
            del _jobs[jid]


@app.post("/api/generate")
def api_generate(req: GenerateRequest, request: Request):
    """Start (or find) a build.  Cached results come back at once as
    {"cached": true, "info": ...}; otherwise {"cached": false, "job": id,
    "estimates": {...}} and the job is followed on /api/jobs/{id}."""
    client = (request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "")) if request else ""
    session = request.headers.get("x-sundial-session", "")[:64] if request else ""
    hit = _cached(req)
    if hit:
        _note_latest(hit)
        _log_creation(req, session, client, cached=True)
        return {"cached": True, "info": hit}
    return _start_job(req, client, session)


def _start_job(req: GenerateRequest, client: str = "", session: str = ""):
    _prune_jobs()
    _ensure_worker()
    with _jobs_lock:
        for jid, job in _jobs.items():   # same dial already queued or building: join it
            if job["status"] in ("queued", "running") and job["key"] == _cache_key(req):
                return {"cached": False, "job": jid, "estimates": stage_estimates(), "stages": STAGES}
        pending = [j for j in _jobs.values() if j["status"] in ("queued", "running")]
        if client and sum(1 for j in pending if j.get("client") == client) >= MAX_PER_CLIENT:
            raise HTTPException(429, "you already have dials in the queue; let them finish first")
        if len(pending) >= MAX_QUEUE:
            raise HTTPException(429, "the workshop is full right now; try again in a few minutes")
        jid = uuid.uuid4().hex[:12]
        _jobs[jid] = {"req": req, "key": _cache_key(req), "status": "queued", "created": time.time(), "done_stages": [], "client": client, "session": session}
    _job_queue.put(jid)
    return {"cached": False, "job": jid, "estimates": stage_estimates(), "stages": STAGES}


@app.on_event("startup")
def _warm_up():
    """A fresh server has nothing to show; make one dial so the first
    visitor sees a real one (skipped under tests and when disabled)."""
    if os.environ.get("SUNDIAL_NO_WARMUP") or "PYTEST_CURRENT_TEST" in os.environ:
        return
    if _latest_path().exists():
        return
    req = GenerateRequest(lat=48.7758, lon=9.1829, utc_offset_h=1.0, zone_label="CET  UTC+1", summer_label="CEST",
                          place_name="Stuttgart, Germany", tz_name="Europe/Berlin")
    if _cached(req):
        _note_latest(_cached(req))
        return
    threading.Thread(target=lambda: _start_job(req), daemon=True).start()


@app.get("/api/jobs/{jid}")
def api_job(jid: str):
    view = _job_view(jid)
    if not view:
        raise HTTPException(404, "no such job")
    return view


@app.get("/api/jobs/{jid}/events")
def api_job_events(jid: str):
    """Server-sent events: one JSON status per line whenever it changes,
    a heartbeat every two seconds, and the final status with the info."""
    if not _job_view(jid):
        raise HTTPException(404, "no such job")

    def stream():
        last = None
        t_beat = time.time()
        while True:
            view = _job_view(jid)
            if not view:
                yield "event: gone\ndata: {}\n\n"
                return
            sig = (view["status"], view["stage"], view["ahead"])
            if sig != last or time.time() - t_beat > 2.0:
                last = sig; t_beat = time.time()
                yield "data: " + json.dumps(view) + "\n\n"
            if view["status"] in ("done", "failed"):
                return
            time.sleep(0.4)
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.api_route("/api/files/{key}/{name}", methods=["GET", "HEAD"])
def api_file(key: str, name: str, download_name: str = ""):
    if not (key.isalnum() and name.replace(".", "").replace("_", "").isalnum()):
        raise HTTPException(404)
    path = CACHE_DIR / key / name
    if not path.exists():
        raise HTTPException(404)
    media = "application/zip" if name.endswith(".zip") else "model/gltf-binary" if name.endswith(".glb") else "model/stl"
    fname = _slug(download_name.rsplit(".", 1)[0]) + "." + name.rsplit(".", 1)[1] if download_name else name
    headers = {"Cache-Control": "public, max-age=31536000, immutable"}   # the key names the content
    if name.endswith(".glb"):
        return FileResponse(path, media_type=media, headers=headers)
    return FileResponse(path, media_type=media, filename=fname, headers=headers)


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
