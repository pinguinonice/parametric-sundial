import { SundialScene } from "./scene.js";

const $ = (id) => document.getElementById(id);
const api = (path, body) =>
  fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(async (r) => {
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  });

const scene = new SundialScene($("view"));

const state = {
  sunPath: null,     // { samples: [{minute, enu, elevation}] }
  playing: false,
  haveDial: false,
};

// ---- helpers ----
const params = () => ({
  lat: parseFloat($("lat").value),
  lon: parseFloat($("lon").value),
  alt: parseFloat($("alt").value) || 0,
  radius: (parseFloat($("radius").value) || 100) / 1000, // mm -> m
  noonOffset: parseFloat($("noonOffset").value) || 0,
  season: $("season").value,
});

const fmtDeg = (d) => `${d.toFixed(1)}°`;
const hhmm = (min) =>
  `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(Math.round(min) % 60).padStart(2, "0")}`;

function setStatus(el, msg, isErr = false) {
  el.textContent = msg;
  el.classList.toggle("err", isErr);
}

function lerpEnu(a, b, f) {
  return [0, 1, 2].map((i) => a[i] + (b[i] - a[i]) * f);
}

// interpolate the sun path at a LOCAL minute-of-day (samples are indexed in UTC)
function sunAt(localMinute) {
  const s = state.sunPath?.samples;
  if (!s || !s.length) return null;
  const step = state.sunPath.stepMin;
  const off = state.sunPath.utcOffsetMin || 0;
  const utc = (((localMinute - off) % 1440) + 1440) % 1440;
  const i = Math.min(s.length - 1, Math.floor(utc / step));
  const j = i + 1 >= s.length ? 0 : i + 1; // wrap across midnight
  const f = (utc - i * step) / step;
  return {
    enu: lerpEnu(s[i].enu, s[j].enu, f),
    elevation: s[i].elevation + (s[j].elevation - s[i].elevation) * f,
  };
}

// ---- render pipeline ----
function applySun() {
  const minute = parseFloat($("time").value);
  $("timeVal").textContent = hhmm(minute);
  const sun = sunAt(minute);
  if (!sun) return;
  scene.setSun(sun.enu, sun.elevation);
  $("rElev").textContent = fmtDeg(sun.elevation);
  const azi = ((Math.atan2(sun.enu[0], sun.enu[1]) * 180) / Math.PI + 360) % 360;
  $("rAzi").textContent = sun.elevation > 0 ? fmtDeg(azi) : "— (night)";
  $("rTime").textContent = scene.reading ? `${scene.reading} local` : "— (night)";
}

async function refreshSunPath() {
  const p = params();
  if (Number.isNaN(p.lat) || Number.isNaN(p.lon)) return;
  state.sunPath = await api("/api/sunpath", {
    lat: p.lat, lon: p.lon, alt: p.alt, date: $("date").value || undefined, stepMin: 5,
  });
  applySun();
}

async function generate() {
  const p = params();
  if (Number.isNaN(p.lat) || Number.isNaN(p.lon)) {
    setStatus($("genStatus"), "Enter a latitude and longitude first.", true);
    return;
  }
  $("generate").disabled = true;
  $("spinner").hidden = false;
  setStatus($("genStatus"), "");
  try {
    const [dial] = await Promise.all([api("/api/generate", p), refreshSunPath()]);
    scene.setDial(dial);
    state.haveDial = true;
    $("hint").hidden = true;
    $("stl").disabled = false;
    const note = dial.gnomonGrid ? "" : " (roller grid unavailable for these inputs)";
    setStatus($("genStatus"), `Dial ready${note}.`);
    applySun();
  } catch (e) {
    setStatus($("genStatus"), `Failed: ${e.message}`, true);
  } finally {
    $("generate").disabled = false;
    $("spinner").hidden = true;
  }
}

async function downloadStl() {
  const p = params();
  $("stl").disabled = true;
  const old = $("stl").textContent;
  $("stl").textContent = "Building…";
  try {
    const r = await fetch("/api/export.stl", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...p, scaleMm: 1000 }),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `sundial_${p.lat.toFixed(3)}_${p.lon.toFixed(3)}_${p.season}.stl`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    setStatus($("genStatus"), `STL failed: ${e.message}`, true);
  } finally {
    $("stl").disabled = false;
    $("stl").textContent = old;
  }
}

// ---- animation ----
let raf = 0, last = 0;
function tick(ts) {
  if (!state.playing) return;
  if (last) {
    let m = parseFloat($("time").value) + ((ts - last) / 1000) * 120; // 2 min/s
    if (m >= 1435) m = 0;
    $("time").value = m;
    applySun();
  }
  last = ts;
  raf = requestAnimationFrame(tick);
}
function togglePlay() {
  state.playing = !state.playing;
  $("play").textContent = state.playing ? "⏸ Pause" : "▶ Animate day";
  last = 0;
  if (state.playing) raf = requestAnimationFrame(tick);
  else cancelAnimationFrame(raf);
}

// ---- geolocation ----
function useMyLocation() {
  if (!navigator.geolocation) {
    setStatus($("geoStatus"), "Geolocation not supported by this browser.", true);
    return;
  }
  setStatus($("geoStatus"), "Locating…");
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      $("lat").value = pos.coords.latitude.toFixed(4);
      $("lon").value = pos.coords.longitude.toFixed(4);
      if (pos.coords.altitude != null) $("alt").value = Math.round(pos.coords.altitude);
      setStatus($("geoStatus"), `Got ${$("lat").value}, ${$("lon").value}.`);
      generate();
    },
    (err) => setStatus($("geoStatus"), `Location denied: ${err.message}`, true),
    { enableHighAccuracy: true, timeout: 10000 }
  );
}

// ---- wiring ----
const _t = new Date();
$("date").value = `${_t.getFullYear()}-${String(_t.getMonth() + 1).padStart(2, "0")}-${String(_t.getDate()).padStart(2, "0")}`;
$("time").value = _t.getHours() * 60 + _t.getMinutes();
$("stl").disabled = true;

$("geo").onclick = useMyLocation;
$("generate").onclick = generate;
$("stl").onclick = downloadStl;
$("play").onclick = togglePlay;
$("nowBtn").onclick = () => {
  const now = new Date(); // local wall clock
  $("date").value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  $("time").value = now.getHours() * 60 + now.getMinutes();
  refreshSunPath();
};
$("time").oninput = applySun;
$("noonOffset").oninput = () => ($("noonVal").textContent = `${$("noonOffset").value}°`);
$("date").onchange = () => state.haveDial && refreshSunPath();
["lat", "lon", "alt"].forEach((id) => ($(id).onchange = () => state.haveDial && refreshSunPath()));
