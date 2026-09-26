import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { createStage, drawAnalemma, drawProfiles, sunriseMinutes } from './viewer-core.js';
import { t, lang, pickLanguage, setLanguage, languageSelector } from './i18n.js';

const $ = (id) => document.getElementById(id);
const STATIC = document.documentElement.classList.contains('static');   // hosted preview: no server
const stage = createStage($('c'));
window.__sundialStage = stage;   // scripted camera for the visual audit
const state = { info: null, sweep: null };
const rollerLabels = () => { const f = (m, d) => new Date(Date.UTC(2026, m, d)).toLocaleDateString(lang(), { day: 'numeric', month: 'short', timeZone: 'UTC' }); return { roller_1: { name: 'I', top: f(5, 21), bottom: f(11, 21) }, roller_2: { name: 'II', top: f(5, 21), bottom: f(11, 21) } }; };

setLanguage(pickLanguage(), false);
languageSelector($('langBox'));
const fmtDeg = (v, pos, neg) => `${Math.abs(v).toFixed(2)}° ${v >= 0 ? pos : neg}`;

// ------------------------------------------------------------ location & map (generator only)
let map, marker;
function currentParams() {
  if (STATIC && state.info) return state.info.params;
  return { lat: +$('lat').value, lon: +$('lon').value, utc_offset_h: +$('utc').value, year: +$('year').value };
}
function redrawFigures() {
  const p = currentParams();
  drawAnalemma($('analemma'), p, { axisEot: t('axisEot'), axisDecl: t('axisDecl'), locale: lang() });
  $('analemmaCap').textContent = t('ch1cap', { lat: fmtDeg(p.lat, 'N', 'S'), lon: fmtDeg(p.lon, 'E', 'W') });
  if (state.info) {
    drawProfiles($('profileFig'), state.info.profiles, rollerLabels(), { empty: t('ch2capEmpty'), scalePlane: t('scalePlane') });
    const d = state.info.design;
    $('profileCap').textContent = t('ch2cap', { rmin: d.roller_r_min.toFixed(1), rmax: d.roller_r_max.toFixed(1), len: (d.roller_z_max - d.roller_z_min).toFixed(0) });
  } else {
    drawProfiles($('profileFig'), null, rollerLabels(), { empty: t('ch2capEmpty'), scalePlane: t('scalePlane') });
    $('profileCap').textContent = t('ch2capEmpty');
  }
}
if (!STATIC) {
  map = L.map('map', { zoomControl: false }).setView([48.7758, 9.1829], 5);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18, attribution: '&copy; OpenStreetMap' }).addTo(map);
  marker = L.marker([48.7758, 9.1829], { draggable: true }).addTo(map);
  marker.on('dragend', () => setLocation(marker.getLatLng().lat, marker.getLatLng().lng));
  map.on('click', (e) => setLocation(e.latlng.lat, e.latlng.lng));
  $('lat').addEventListener('change', () => setLocation(+$('lat').value, +$('lon').value, true));
  $('lon').addEventListener('change', () => setLocation(+$('lat').value, +$('lon').value, true));
  $('utc').addEventListener('change', redrawFigures);
  $('geoBtn').addEventListener('click', () => navigator.geolocation?.getCurrentPosition((p) => setLocation(p.coords.latitude, p.coords.longitude, true),
    () => { $('status').textContent = t('stNoGeo'); }));
  $('searchBtn').addEventListener('click', search);
  $('search').addEventListener('keydown', (e) => { if (e.key === 'Enter') search(); });
  $('dia').addEventListener('input', () => { $('diaLabel').textContent = t('dia', { mm: $('dia').value }); });
  $('autoHours').addEventListener('change', () => { const a = $('autoHours').checked; $('hFirst').disabled = a; $('hLast').disabled = a; });
  $('generate').addEventListener('click', generate);
}
async function setLocation(lat, lon, pan = false) {
  lat = Math.max(-89.9, Math.min(89.9, lat)); lon = ((lon + 540) % 360) - 180;
  $('lat').value = lat.toFixed(4); $('lon').value = lon.toFixed(4);
  marker.setLatLng([lat, lon]);
  if (pan) map.setView([lat, lon], Math.max(map.getZoom(), 7));
  try {
    const tz = await (await fetch(`/api/timezone?lat=${lat}&lon=${lon}`)).json();
    $('utc').value = tz.utc_offset_h; $('label').value = tz.label;
    state.tz = tz;
  } catch (e) { /* offline: keep manual values */ }
  tzHint(); redrawFigures();
}
function tzHint() {
  if (STATIC || !state.tz) return;
  const tz = state.tz;
  $('tzHint').textContent = t('tzZone', { tz: tz.tz || '?', off: (tz.utc_offset_h >= 0 ? '+' : '') + tz.utc_offset_h }) + (tz.dst ? t('tzDst') : t('tzNoDst'));
}
async function search() {
  const q = $('search').value.trim(); if (!q) return;
  $('status').textContent = t('stSearching');
  try {
    const res = await (await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(q)}`, { headers: { 'Accept-Language': lang() } })).json();
    if (!res.length) { $('status').textContent = t('stNothing'); return; }
    $('status').textContent = res[0].display_name; await setLocation(+res[0].lat, +res[0].lon, true);
  } catch (e) { $('status').textContent = t('stSearchFail'); }
}

// ------------------------------------------------------------ generation / static load
async function generate() {
  const btn = $('generate'); btn.disabled = true; $('status').textContent = t('stComputing');
  const body = {
    lat: +$('lat').value, lon: +$('lon').value, utc_offset_h: +$('utc').value, zone_label: $('label').value,
    year: +$('year').value, scale_radius: +$('dia').value / 2, min_roller_radius: +$('minr').value,
    hour_first: $('autoHours').checked ? null : +$('hFirst').value, hour_last: $('autoHours').checked ? null : +$('hLast').value,
  };
  try {
    const r = await fetch('/api/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    const info = await r.json();
    const loader = new STLLoader();
    const load = (url) => new Promise((res, rej) => loader.load(url, res, undefined, rej));
    const [gDial, gR1, gR2, gStand] = await Promise.all([load(info.files.dial), load(info.files.roller_1), load(info.files.roller_2), load(info.files.stand)]);
    stage.addPart('dial', gDial, info.assembly.dial_to_world);
    stage.addPart('roller_1', gR1, info.assembly.rollers_to_world.roller_1);
    stage.addPart('roller_2', gR2, info.assembly.rollers_to_world.roller_2);
    stage.addPart('stand', gStand, info.assembly.stand_to_world);
    afterLoad(info);
    $('downloads').classList.remove('hidden');
    $('dlZip').href = info.zip; $('dlDial').href = info.files.dial; $('dlR1').href = info.files.roller_1; $('dlR2').href = info.files.roller_2; $('dlStand').href = info.files.stand;
    $('status').textContent = t('stDone');
    document.querySelector('.stage').scrollIntoView({ behavior: 'smooth', block: 'center' });
  } catch (e) { $('status').textContent = t('stError', { e: e.message }); }
  finally { btn.disabled = false; }
}
async function loadStatic() {
  const info = await (await fetch('info.json')).json();
  const meshes = await (await fetch('meshes.json')).json();
  const loader = new GLTFLoader();
  const toBuffer = (b64) => { const bin = atob(b64); const u8 = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i); return u8.buffer; };
  const one = (name, rows) => new Promise((res, rej) => loader.parse(toBuffer(meshes[name]), '', (g) => {
    let geom = null; g.scene.traverse((o) => { if (o.isMesh && !geom) geom = o.geometry; });
    stage.addPart(name, geom, rows); res();
  }, rej));
  const a = info.assembly;
  await Promise.all([one('dial', a.dial_to_world), one('stand', a.stand_to_world), one('roller_1', a.rollers_to_world.roller_1), one('roller_2', a.rollers_to_world.roller_2)]);
  afterLoad(info);
}
function afterLoad(info) {
  stage.setInfo(info); state.info = info;
  const y = info.params.year;
  $('simDate').min = `${y}-01-01`; $('simDate').max = `${y}-12-31`;
  if (!$('simDate').value.startsWith(String(y))) $('simDate').value = `${y}-05-20`;
  fillInfo(); redrawFigures(); sweepIn();
}

// ------------------------------------------------------------ time of day
function dateParts() { return $('simDate').value.split('-').map(Number); }
function update() {
  const mins = +$('simTime').value, hh = Math.floor(mins / 60), mm = mins % 60;
  const tt = `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
  $('simTimeVal').textContent = tt;
  if (!state.info) return;
  const [y, mo, d] = dateParts();
  const r = stage.setTime(y, mo, d, mins, $('rollerSel').value, $('explode').checked);
  const dateTxt = new Date(Date.UTC(y, mo - 1, d)).toLocaleDateString(lang(), { day: 'numeric', month: 'long', timeZone: 'UTC' });
  const status = !r.up ? t('below') : !r.inRange ? t('outside') : t('inPlace', { n: r.roller === 'roller_1' ? 'I' : 'II' });
  const eot = r.eotMin >= 0 ? t('eotAhead', { x: r.eotMin.toFixed(1) }) : t('eotBehind', { x: (-r.eotMin).toFixed(1) });
  $('readout').innerHTML = `<span class="big">${tt}</span><span>${dateTxt}</span><span>${t('sunHigh', { x: r.elev.toFixed(0) })}</span><span>${eot}</span><span>${status}${r.wrongRoller ? ', ' + t('wrongRoller') : ''}</span>` +
    (r.up && r.inRange ? `<span class="dot"><i></i>${t('legendDot')}</span>` : '');
}
function sweepIn() {
  if (state.sweep) cancelAnimationFrame(state.sweep);
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const [y, mo, d] = dateParts();
  const end = +$('simTime').value, start = sunriseMinutes(y, mo, d, state.info.params);
  if (reduce || end <= start) { update(); return; }
  const t0 = performance.now(), dur = 2600;
  const tick = (now) => {
    const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 3);
    $('simTime').value = Math.round(start + (end - start) * e); update();
    if (k < 1) state.sweep = requestAnimationFrame(tick); else state.sweep = null;
  };
  state.sweep = requestAnimationFrame(tick);
}
for (const id of ['simTime', 'simDate', 'rollerSel', 'explode']) $(id).addEventListener('input', update);
for (const b of document.querySelectorAll('.chip')) b.addEventListener('click', () => {
  const year = state.info ? state.info.params.year : (STATIC ? 2026 : +$('year').value);
  $('simDate').value = `${year}-${b.dataset.date}`; $('simTime').value = b.dataset.min; update();
});

function fillInfo() {
  const info = state.info; if (!info) return;
  const d = info.design, p = info.params;
  const fmt = (h) => `${String(Math.floor(h)).padStart(2, '0')}:${String(Math.round((h % 1) * 60)).padStart(2, '0')}`;
  const rows = [
    [t('fPlace'), `${d.location_text || (p.lat.toFixed(4) + '°, ' + p.lon.toFixed(4) + '°')}, ${p.zone_label || 'UTC' + p.utc_offset_h}`],
    [t('fHours'), t('fHoursV', { a: d.hour_first, b: d.hour_last, t: d.minute_ticks ? t('tick1') : t('tick5') })],
    [t('fDay'), t('fDayV', { a: fmt(d.sunrise_earliest), b: fmt(d.sunset_latest) })],
    [t('fRoller'), t('fRollerV', { a: d.roller_r_min.toFixed(1), b: d.roller_r_max.toFixed(1) })],
    [t('fStand'), t('fStandV', { t: d.tilt_deg.toFixed(1), d: (2 * (d.base_radius || 58)).toFixed(0) })],
  ];
  if (info.bounds) rows.push([t('fFoot'), `${(info.bounds.dial[1][0] - info.bounds.dial[0][0]).toFixed(0)} × ${(info.bounds.dial[1][1] - info.bounds.dial[0][1]).toFixed(0)} × ${(info.bounds.dial[1][2] - info.bounds.dial[0][2]).toFixed(0)} mm`]);
  else rows.push([t('fDish'), t('fDishV', { d: d.dish_depth.toFixed(0) })]);
  const acc = (info.accuracy || []).map((a) => t('accItem', { from: a.from, to: a.to, m: Math.abs(a.max_error_min).toFixed(1), sign: t(a.sign) })).join('; ');
  rows.push([t('fAcc'), acc ? t('fAccExc', { x: acc }) : t('fAccAll')]);
  const sh = (info.shadowed || []).map((x) => t('shItem', { from: x.from, to: x.to, h: x.hours })).join('; ');
  rows.push([t('fShadow'), sh || t('never')]);
  $('infoList').innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');
  $('warnings').innerHTML = (info.warnings || []).map((w) => `<li>${w}</li>`).join('');
}

// ------------------------------------------------------------ start & language changes
function onLanguage() {
  if (!STATIC) { $('diaLabel').textContent = t('dia', { mm: $('dia').value }); tzHint(); }
  redrawFigures(); fillInfo(); update();
}
document.addEventListener('languagechange', onLanguage);
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', redrawFigures);
if (STATIC) {
  loadStatic().catch((e) => { $('readout').innerHTML = `<span class="big">!</span><span>${e.message}</span>`; });
} else {
  setLocation(48.7758, 9.1829);
}
onLanguage();
