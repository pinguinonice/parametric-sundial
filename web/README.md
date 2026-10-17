# Sundial web app

A small website that builds a **Bernhardt-cylinder sundial** for your current
location and previews it in 3D with the live sun. It reuses the model in
`../sundial/src/sundial/sundial.py` unchanged.

```
web/
  backend/     FastAPI — wraps generateSundial(), serves geometry + STL
  frontend/    vanilla JS + Three.js — geolocation, controls, 3D preview
  run.sh       venv bootstrap + uvicorn
```

## Run

```bash
./web/run.sh            # http://localhost:8000
```

First launch creates `web/backend/.venv` and installs
`backend/requirements.txt`. Override with `PORT=... PYTHON=...`.

Manual:

```bash
cd web/backend
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn app:app --reload
```

## Use

1. **Use my location** (browser geolocation) or type lat/lon/alt.
2. Pick scale radius, season, noon offset → **Generate dial**.
3. Scrub **Time of day** or hit **Animate day** to watch the sun move; the red
   marker is where the gnomon shadow crosses the scale ("Dial reads").
4. **Download STL** — a watertight mesh in millimetres (roller + axis rod +
   scale ring). Ring diameter ≈ `2 × radius`.

## API

| Method + path        | Body                                          | Returns                          |
|----------------------|-----------------------------------------------|----------------------------------|
| `POST /api/generate` | `lat, lon, alt, radius(m), noonOffset, season`| dial geometry (ENU) as JSON      |
| `POST /api/sun`      | `lat, lon, alt, time?`                         | sun unit vector + elev/azimuth   |
| `POST /api/sunpath`  | `lat, lon, alt, date?, stepMin`               | sun track for one day            |
| `POST /api/export.stl`| generate body + `scaleMm`                     | `model/stl` attachment           |

## Notes

- `/api/generate` runs the original model (~4400 `pysolar` calls): a few
  seconds per new parameter set, ~10–15 s on the very first call while pysolar
  and the timezone DB warm up. Results are LRU-cached, so repeats and STL
  export off the same params are instant.
- The STL is preview/print quality. A couple of zero-area triangles at the end
  caps are harmless; run the slicer's mesh-fix if your tool is strict.
- Three.js loads from jsdelivr via an import map — needs internet on first load.
