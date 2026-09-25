import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { createStage, drawAnalemma, drawProfiles, sunriseMinutes, zoneUnix, sunENU } from './viewer-core.js';

const $ = (id) => document.getElementById(id);
const stage = createStage($('c'));
const state = { info: null, sweep: null };
const ROLLER_LABELS = { roller_1: { name: 'I', top: '21 June', bottom: '21 December' }, roller_2: { name: 'II', top: '21 June', bottom: '21 December' } };

// ------------------------------------------------------------ location & map
const map = L.map('map', { zoomControl: false, attributionControl: true }).setView([48.7758, 9.1829], 5);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18, attribution: '&copy; OpenStreetMap' }).addTo(map);
const marker = L.marker([48.7758, 9.1829], { draggable: true }).addTo(map);
marker.on('dragend', () => setLocation(marker.getLatLng().lat, marker.getLatLng().lng));
map.on('click', (e) => setLocation(e.latlng.lat, e.latlng.lng));

function currentParams() {
  return { lat: +$('lat').value, lon: +$('lon').value, utc_offset_h: +$('utc').value, year: +$('year').value };
}
async function setLocation(lat, lon, pan = false) {
  lat = Math.max(-89.9, Math.min(89.9, lat)); lon = ((lon + 540) % 360) - 180;
  $('lat').value = lat.toFixed(4); $('lon').value = lon.toFixed(4);
  marker.setLatLng([lat, lon]);
  if (pan) map.setView([lat, lon], Math.max(map.getZoom(), 7));
  try {
    const tz = await (await fetch(`/api/timezone?lat=${lat}&lon=${lon}`)).json();
    $('utc').value = tz.utc_offset_h; $('label').value = tz.label;
    $('tzHint').textContent = (tz.tz ? `Zone ${tz.tz}, ` : '') + `standard offset UTC${tz.utc_offset_h >= 0 ? '+' : ''}${tz.utc_offset_h}` +
      (tz.dst ? '. This zone has summer time: the dial shows standard time, add one hour in summer.' : '. No summer time here.');
  } catch (e) { /* offline: keep manual values */ }
  drawAnalemma($('analemma'), currentParams());
  $('analemmaCap').textContent = `Analemma at ${lat.toFixed(2)}°, ${lon.toFixed(2)}°: equation of time against declination, one dot per month`;
}
$('lat').addEventListener('change', () => setLocation(+$('lat').value, +$('lon').value, true));
$('lon').addEventListener('change', () => setLocation(+$('lat').value, +$('lon').value, true));
$('utc').addEventListener('change', () => drawAnalemma($('analemma'), currentParams()));
$('geoBtn').addEventListener('click', () => navigator.geolocation?.getCurrentPosition((p) => setLocation(p.coords.latitude, p.coords.longitude, true),
  () => { $('status').textContent = 'Your browser did not share a location.'; }));
async function search() {
  const q = $('search').value.trim(); if (!q) return;
  $('status').textContent = 'Searching…';
  try {
    const res = await (await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(q)}`, { headers: { 'Accept-Language': 'en' } })).json();
    if (!res.length) { $('status').textContent = 'Nothing found for that name.'; return; }
    $('status').textContent = res[0].display_name; await setLocation(+res[0].lat, +res[0].lon, true);
  } catch (e) { $('status').textContent = 'The place search did not answer.'; }
}
$('searchBtn').addEventListener('click', search);
$('search').addEventListener('keydown', (e) => { if (e.key === 'Enter') search(); });
$('dia').addEventListener('input', () => { $('diaVal').textContent = $('dia').value; });
$('autoHours').addEventListener('change', () => { const a = $('autoHours').checked; $('hFirst').disabled = a; $('hLast').disabled = a; });

// ------------------------------------------------------------ generation
$('generate').addEventListener('click', generate);
async function generate() {
  const btn = $('generate'); btn.disabled = true; $('status').textContent = 'Tracing a year of sunlight and carving the parts… a few seconds.';
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
    stage.setInfo(info); state.info = info;
    $('simDate').min = `${body.year}-01-01`; $('simDate').max = `${body.year}-12-31`;
    if (!$('simDate').value.startsWith(String(body.year))) $('simDate').value = `${body.year}-05-20`;
    fillInfo(info);
    drawProfiles($('profileFig'), info.profiles, ROLLER_LABELS);
    $('profileCap').textContent = `Your two rollers, to scale: ${info.design.roller_r_min.toFixed(1)} to ${info.design.roller_r_max.toFixed(1)} mm radius over ${(info.design.roller_z_max - info.design.roller_z_min).toFixed(0)} mm`;
    $('status').textContent = 'Done. The preview at the top now shows your dial.';
    sweepIn();
    document.querySelector('.stage').scrollIntoView({ behavior: 'smooth', block: 'center' });
  } catch (e) { $('status').textContent = 'Could not generate: ' + e.message; }
  finally { btn.disabled = false; }
}

// ------------------------------------------------------------ time of day
function dateParts() { return $('simDate').value.split('-').map(Number); }
function update() {
  const mins = +$('simTime').value, hh = Math.floor(mins / 60), mm = mins % 60;
  const t = `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
  $('simTimeVal').textContent = t;
  if (!state.info) return;
  const [y, mo, d] = dateParts();
  const r = stage.setTime(y, mo, d, mins, $('rollerSel').value, $('explode').checked);
  const p = state.info.params;
  const dateTxt = new Date(Date.UTC(y, mo - 1, d)).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', timeZone: 'UTC' });
  const status = !r.up ? 'the sun is below the horizon' : !r.inRange ? 'outside the engraved hours' : `roller ${r.roller === 'roller_1' ? 'I' : 'II'} in place`;
  $('readout').innerHTML = `<span class="big">${t}</span><span>${dateTxt}</span><span>sun ${r.elev.toFixed(0)}° high</span><span>equation of time ${r.eotMin >= 0 ? '+' : ''}${r.eotMin.toFixed(1)} min</span><span>${status}${r.wrongRoller ? ', wrong roller for this date' : ''}</span>` +
    (r.up && r.inRange ? '<span class="dot"><i></i>expected reading</span>' : '');
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
  const year = state.info ? state.info.params.year : +$('year').value;
  $('simDate').value = `${year}-${b.dataset.date}`; $('simTime').value = b.dataset.min; update();
});

function fillInfo(info) {
  const d = info.design, p = info.params;
  const fmt = (h) => `${String(Math.floor(h)).padStart(2, '0')}:${String(Math.round((h % 1) * 60)).padStart(2, '0')}`;
  const rows = [
    ['Place', `${p.lat.toFixed(4)}°, ${p.lon.toFixed(4)}°, ${p.zone_label || 'UTC' + p.utc_offset_h}`],
    ['Engraved hours', `${d.hour_first} to ${d.hour_last}, ${d.minute_ticks ? 'minute' : 'five-minute'} ticks`],
    ['Longest day', `${fmt(d.sunrise_earliest)} to ${fmt(d.sunset_latest)}`],
    ['Roller', `${d.roller_r_min.toFixed(1)} to ${d.roller_r_max.toFixed(1)} mm radius`],
    ['Stand', `tilted ${d.tilt_deg.toFixed(1)}°, base Ø ${(2 * d.base_radius).toFixed(0)} mm`],
    ['Dial footprint', `${(info.bounds.dial[1][0] - info.bounds.dial[0][0]).toFixed(0)} × ${(info.bounds.dial[1][1] - info.bounds.dial[0][1]).toFixed(0)} × ${(info.bounds.dial[1][2] - info.bounds.dial[0][2]).toFixed(0)} mm`],
  ];
  const acc = (info.accuracy || []).map((a) => `${a.from} to ${a.to} up to ${Math.abs(a.max_error_min).toFixed(1)} min ${a.sign}`).join('; ');
  rows.push(['Reads within a minute', acc ? `all year except ${acc}` : 'all year']);
  const sh = (info.shadowed || []).map((x) => `${x.from} to ${x.to} (${x.hours})`).join('; ');
  rows.push(['Wing shadows the scale', sh || 'never']);
  $('infoList').innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');
  $('warnings').innerHTML = info.warnings.map((w) => `<li>${w}</li>`).join('');
  $('downloads').classList.remove('hidden');
  $('dlZip').href = info.zip; $('dlDial').href = info.files.dial; $('dlR1').href = info.files.roller_1; $('dlR2').href = info.files.roller_2; $('dlStand').href = info.files.stand;
}

// ------------------------------------------------------------ start
setLocation(48.7758, 9.1829);
drawProfiles($('profileFig'), null, ROLLER_LABELS);
update();
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { drawAnalemma($('analemma'), currentParams()); drawProfiles($('profileFig'), state.info ? state.info.profiles : null, ROLLER_LABELS); });
