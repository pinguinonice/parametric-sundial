"""FastAPI backend for the parametric sundial web app.

    uvicorn app:app --reload --port 8000

Serves the static frontend at ``/`` and the model at ``/api/*``.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import geometry
import meshing

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"

app = FastAPI(title="Parametric Sundial")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


class DialParams(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    alt: float = 300.0
    radius: float = Field(0.1, gt=0, le=5, description="scale radius in metres")
    noonOffset: float = 0.0
    season: str = Field("fall", pattern="^(spring|fall)$")


class SunQuery(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    alt: float = 300.0
    time: dt.datetime | None = None


class SunPathQuery(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    alt: float = 300.0
    date: dt.date | None = None
    stepMin: int = Field(5, ge=1, le=60)


class ExportQuery(DialParams):
    scaleMm: float = Field(1000.0, gt=0, description="metres -> STL units")


@app.post("/api/generate")
def api_generate(p: DialParams):
    try:
        return geometry.to_payload(
            p.lat, p.lon, p.alt, p.radius, p.noonOffset, p.season
        )
    except Exception as exc:  # noqa: BLE001 - surface model errors to the client
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/sun")
def api_sun(q: SunQuery):
    try:
        return geometry.sun_enu(q.lat, q.lon, q.alt, q.time)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/sunpath")
def api_sunpath(q: SunPathQuery):
    date = q.date or dt.datetime.now(dt.timezone.utc).date()
    try:
        return geometry.sun_path(q.lat, q.lon, q.alt, date, q.stepMin)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/export.stl")
def api_export_stl(p: ExportQuery):
    try:
        geom = geometry.generate(
            p.lat, p.lon, p.alt, p.radius, p.noonOffset, p.season
        )
        data = meshing.build_stl(geom, scale_mm=p.scaleMm)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    fname = f"sundial_{p.lat:.3f}_{p.lon:.3f}_{p.season}.stl"
    return Response(
        content=data,
        media_type="model/stl",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.get("/api/health")
def health():
    return {"ok": True}


app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
