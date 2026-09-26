import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { createStage, drawAnalemma, drawProfiles, drawSunPath, sunriseMinutes, sunENU, zoneUnix, zoneNow, wallClock, nextLightMoment, autoHours, renderPartStill, createPartStage } from './viewer-core.js';
import { t, lang, pickLanguage, setLanguage, languageSelector } from './i18n.js';

const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const STATIC = document.documentElement.classList.contains('static');   // hosted preview: no server
const stage = createStage($('c'));
window.__sundialStage = stage;   // scripted camera for the visual audit
const DEFAULTS = { lat: 48.7758, lon: 9.1829, dia: 150, year: new Date().getFullYear(), minr: 4 };
const state = { hero: null, heroLoop: null, info: null, design: null, tz: null, place: null, geoms: null, sweep: null, job: null, when: 'now', moment: null, whyTimer: null, partStage: null };
const STAGE_KEYS = { queued: 'stQueued', design: 'stDesign', dial: 'stDial', roller_1: 'stR1', roller_2: 'stR2', stand: 'stStand', export: 'stExport' };

setLanguage(pickLanguage(), false);
languageSelector($('langBox'));
const fmtDeg = (v, pos, neg) => `${Math.abs(v).toFixed(2)}° ${v >= 0 ? pos : neg}`;
const fmtHM = (h) => `${String(Math.floor(h)).padStart(2, '0')}:${String(Math.round((h % 1) * 60)).padStart(2, '0')}`;
const fmtMins = (m) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
const fmtDate = (y, mo, d, opts = { day: 'numeric', month: 'long' }) => new Date(Date.UTC(y, mo - 1, d)).toLocaleDateString(lang(), { ...opts, timeZone: 'UTC' });
const rollerLabels = () => { const f = (m, d) => new Date(Date.UTC(2026, m, d)).toLocaleDateString(lang(), { day: 'numeric', month: 'short', timeZone: 'UTC' }); return { roller_1: { name: 'I', top: f(5, 21), bottom: f(11, 21) }, roller_2: { name: 'II', top: f(5, 21), bottom: f(11, 21) } }; };
const store = { get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* blocked */ } } };
const SESSION_ID = (() => { let id = store.get('sundial-session'); if (!id) { id = Array.from(crypto.getRandomValues(new Uint8Array(8)), (b) => b.toString(16).padStart(2, '0')).join(''); store.set('sundial-session', id); } return id; })();
const session = { get(k) { try { return JSON.parse(sessionStorage.getItem(k)); } catch (e) { return null; } }, set(k, v) { try { v == null ? sessionStorage.removeItem(k) : sessionStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* blocked */ } } };

// Leaflet only when a map is opened
let leafletReady = null;
function ensureLeaflet() {
  if (window.L) return Promise.resolve();
  if (!leafletReady) leafletReady = new Promise((res, rej) => {
    const css = document.createElement('link'); css.rel = 'stylesheet'; css.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'; css.crossOrigin = ''; document.head.appendChild(css);
    const js = document.createElement('script'); js.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'; js.crossOrigin = ''; js.onload = res; js.onerror = rej; document.head.appendChild(js);
  });
  return leafletReady;
}
// the four part geometries: one small GLB when the server made one, else the STLs
async function loadGeometries(info) {
  if (info.files.glb) {
    const gltf = await new Promise((res, rej) => new GLTFLoader().load(info.files.glb, res, undefined, rej));
    const out = {};
    gltf.scene.traverse((o) => { if (o.isMesh) { const n = (o.name || o.parent?.name || '').replace(/\.\d+$/, ''); for (const k of ['dial', 'roller_1', 'roller_2', 'stand']) if (n === k || n.startsWith(k)) out[k] = o.geometry; } });
    if (['dial', 'roller_1', 'roller_2', 'stand'].every((k) => out[k])) return out;
  }
  const loader = new STLLoader();
  const load = (url) => new Promise((res, rej) => loader.load(url, res, undefined, rej));
  const [dial, roller_1, roller_2, stand] = await Promise.all([load(info.files.dial), load(info.files.roller_1), load(info.files.roller_2), load(info.files.stand)]);
  return { dial, roller_1, roller_2, stand };
}
function placeParts(info, g) {
  stage.addPart('dial', g.dial, info.assembly.dial_to_world);
  stage.addPart('roller_1', g.roller_1, info.assembly.rollers_to_world.roller_1);
  stage.addPart('roller_2', g.roller_2, info.assembly.rollers_to_world.roller_2);
  stage.addPart('stand', g.stand, info.assembly.stand_to_world);
  $('stage').classList.remove('loading');
}
function currentParams() {
  if (STATIC && state.info) return state.info.params;
  return { lat: +$('lat').value, lon: +$('lon').value, utc_offset_h: +$('utc').value, year: +$('year').value };
}
function showBeat(id, on) { $(id).hidden = !on; }

// ============================================================ 1 · where
let map, marker;
async function initMap() {
  if (map || STATIC) return;
  await ensureLeaflet();
  if (map) return;
  const p = currentParams();
  map = L.map('map', { zoomControl: false }).setView([p.lat, p.lon], 6);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18, attribution: '&copy; OpenStreetMap' }).addTo(map);
  marker = L.marker([p.lat, p.lon], { draggable: true }).addTo(map);
  marker.on('dragend', () => setLocation(marker.getLatLng().lat, marker.getLatLng().lng));
  map.on('click', (e) => setLocation(e.latlng.lat, e.latlng.lng));
}
function parseCoords(q) {
  const m = q.match(/^\s*(-?\d+(?:[.,]\d+)?)\s*°?\s*([NS])?\s*[,;\s]\s*(-?\d+(?:[.,]\d+)?)\s*°?\s*([EW])?\s*$/i);
  if (!m) return null;
  let lat = parseFloat(m[1].replace(',', '.')), lon = parseFloat(m[3].replace(',', '.'));
  if (m[2] && m[2].toUpperCase() === 'S') lat = -Math.abs(lat);
  if (m[4] && m[4].toUpperCase() === 'W') lon = -Math.abs(lon);
  return Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? { lat, lon } : null;
}
async function reverseName(lat, lon) {
  try {
    const r = await (await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&zoom=10&lat=${lat}&lon=${lon}`, { headers: { 'Accept-Language': lang() } })).json();
    const a = r.address || {};
    const town = a.city || a.town || a.village || a.municipality || a.county || a.state || '';
    return [town, a.country].filter(Boolean).join(', ') || r.display_name || '';
  } catch (e) { return ''; }
}
async function setLocation(lat, lon, { name = '', pan = false, lookupName = true } = {}) {
  lat = Math.max(-89.9, Math.min(89.9, lat)); lon = ((lon + 540) % 360) - 180;
  $('lat').value = lat.toFixed(4); $('lon').value = lon.toFixed(4);
  state.place = { lat, lon, name };
  if (marker) { marker.setLatLng([lat, lon]); if (pan) map.setView([lat, lon], Math.max(map.getZoom(), 7)); }
  $('placeCoords').textContent = `${fmtDeg(lat, 'N', 'S')} · ${fmtDeg(lon, 'E', 'W')}`;
  $('placeName').textContent = name || t('placeLooking');
  hints();
  const tzReq = fetch(`/api/timezone?lat=${lat}&lon=${lon}`).then((r) => r.json()).catch(() => null);
  const nameReq = !name && lookupName ? reverseName(lat, lon) : Promise.resolve(name);
  const [tz, found] = await Promise.all([tzReq, nameReq]);
  if (state.place.lat !== lat || state.place.lon !== lon) return;   // superseded
  if (tz) { $('utc').value = tz.utc_offset_h; $('label').value = tz.label; $('summer').value = tz.summer_label || ''; state.tz = tz; }
  state.place.name = found || name || t('placeGeo');
  $('placeName').textContent = state.place.name;
  store.set('sundial-place', state.place);
  hints(); redrawFigures();
}
function zoneWords() {
  const tz = state.tz; if (!tz) return '';
  const abbr = tz.abbr || tz.label || `UTC${tz.utc_offset_h >= 0 ? '+' : ''}${tz.utc_offset_h}`;
  return tz.dst ? t('zoneWords', { abbr, summer: tz.summer_label || '' }) : t('zoneWordsNo', { abbr });
}
function hints() {
  if (STATIC) return;
  const p = currentParams();
  $('placeZone').textContent = zoneWords();
  $('hintTilt').textContent = `${Math.abs(p.lat).toFixed(1)}°`;
  const ah = $('autoHours').checked ? autoHours(p) : { first: +$('hFirst').value, last: +$('hLast').value };
  $('hintHours').textContent = t('hHoursV', { a: ah.first, b: ah.last });
  $('hintSummer').textContent = state.tz ? (state.tz.dst ? t('summerYes', { s: state.tz.summer_label || '' }) : t('summerNo')) : '–';
  const a = Math.abs(p.lat);
  const w = a < 27 ? t('warnLow') : a < 35 ? t('warnLowish') : a > 66 ? t('warnPolar') : '';
  $('placeWarn').textContent = w; $('placeWarn').hidden = !w;
  $('sizeLine').textContent = t('sizeLine', { mm: $('dia').value, y: $('year').value });
  $('diaLabel').textContent = t('dia', { mm: $('dia').value });
  $('diaNote').textContent = t('diaNote', { mm: $('dia').value, bed: bedFor(+$('dia').value) });
}
const bedFor = (dia) => [180, 220, 250, 300, 350, 400].find((b) => b >= dia * 1.55 + 10) || 400;
async function search() {
  const q = $('search').value.trim(); if (!q) return;
  const c = parseCoords(q);
  if (c) { closeResults(); await setLocation(c.lat, c.lon, { pan: true }); return; }
  $('status').textContent = t('stSearching');
  try {
    const res = await (await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=5&q=${encodeURIComponent(q)}`, { headers: { 'Accept-Language': lang() } })).json();
    $('status').textContent = '';
    if (!res.length) { $('status').textContent = t('stNothing'); return; }
    const ul = $('searchResults'); ul.innerHTML = '';
    const seen = new Set();
    for (const r of res) {
      if (seen.has(r.display_name)) continue; seen.add(r.display_name);
      const li = document.createElement('li'); li.tabIndex = 0;
      const parts = r.display_name.split(', ');
      li.innerHTML = `${esc(parts[0])}<small>${esc(parts.slice(1).join(', '))}</small>`;
      const pick = () => { closeResults(); $('search').value = parts[0]; setLocation(+r.lat, +r.lon, { name: `${parts[0]}, ${parts[parts.length - 1]}`, pan: true }); };
      li.addEventListener('click', pick); li.addEventListener('keydown', (e) => { if (e.key === 'Enter') pick(); });
      ul.appendChild(li);
    }
    ul.hidden = false;
  } catch (e) { $('status').textContent = t('stSearchFail'); }
}
function closeResults() { $('searchResults').hidden = true; }
function compactWhere(on) {
  $('where').hidden = on && !STATIC;
  $('againWrap').hidden = !on;
  $('againBtn').textContent = t('anotherPlace');
}

// the page's own shadows follow the sun of the moment shown in the viewer
function sunShadow(r) {
  const root = document.documentElement.style;
  if (!r || !r.up) { root.setProperty('--sx', '0px'); root.setProperty('--sy', '8px'); root.setProperty('--sblur', '30px'); root.setProperty('--salpha', '0.10'); return; }
  const elev = Math.max(3, r.elev) * Math.PI / 180, az = r.az * Math.PI / 180;
  const len = Math.min(34, 5 / Math.tan(elev));                      // long shadows at low sun
  const sx = -Math.sin(az) * len, sy = Math.cos(az) * len;           // north is up on the page; the shadow falls away from the sun
  root.setProperty('--sx', `${sx.toFixed(1)}px`); root.setProperty('--sy', `${sy.toFixed(1)}px`);
  root.setProperty('--sblur', `${(18 + len * 1.2).toFixed(0)}px`); root.setProperty('--salpha', (0.14 + 0.16 * Math.min(1, r.elev / 45)).toFixed(2));
}

// the last dial anyone made, as the opening picture; the sun loops through its day
async function loadHero(attempt = 0) {
  try {
    const r = await fetch('/api/latest');
    if (r.status === 404 && attempt < 6) { setTimeout(() => loadHero(attempt + 1), 20000); return; }   // a fresh server is still making its first dial
    if (!r.ok) return;
    const { age_s, info } = await r.json();
    if (state.info) return;   // the visitor's own dial arrived first
    $('heroSlot').prepend($('stage')); $('heroSlot').hidden = false;
    const g = await loadGeometries(info);
    if (state.info) return;
    placeParts(info, g);
    stage.setInfo(info); state.hero = { info, age_s, at: performance.now() };
    heroCaption(); heroLoop();
  } catch (e) { /* no hero: the card stands alone */ }
}
function heroCaption() {
  const h = state.hero; if (!h) return;
  const age = h.age_s + (performance.now() - h.at) / 1000;
  const ago = age < 90 ? t('agoNow') : age < 3600 ? t('agoMin', { n: Math.round(age / 60) }) : age < 86400 ? t('agoH', { n: Math.round(age / 3600) }) : t('agoD', { n: Math.round(age / 86400) });
  const p = h.info.params, now = zoneNow(p);
  $('heroText').textContent = t('heroText', { place: p.place_name || `${fmtDeg(p.lat, 'N', 'S')}, ${fmtDeg(p.lon, 'E', 'W')}`, ago, t: wallClock(p.tz_name) || fmtMins(now.mins) });
}
function heroLoop() {
  cancelAnimationFrame(state.heroLoop);
  const p = state.hero.info.params, now = zoneNow(p);
  const y = p.year, mo = now.mo, d = now.d;
  const start = sunriseMinutes(y, mo, d, p);
  let end = start; for (let m = 1439; m > start; m -= 2) { if (sunENU(zoneUnix(y, mo, d, m / 60, p.utc_offset_h), p.lat, p.lon)[2] > 0) { end = m; break; } }
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const dur = 24000, t0 = performance.now();
  const tick = (ts) => {
    if (!state.hero) return;
    const k = reduce ? 0.5 : ((ts - t0) % dur) / dur;
    sunShadow(stage.setTime(y, mo, d, Math.round(start + (end - start) * k), 'auto', false));
    state.heroLoop = requestAnimationFrame(tick);
  };
  state.heroLoop = requestAnimationFrame(tick);
}
function endHero() {
  cancelAnimationFrame(state.heroLoop); state.hero = null;
  $('today').insertBefore($('stage'), $('readout')); $('heroSlot').hidden = true;
}

// ============================================================ 2 · making
function requestBody() {
  return {
    lat: +$('lat').value, lon: +$('lon').value, utc_offset_h: +$('utc').value, zone_label: $('label').value, summer_label: $('summer').value,
    year: +$('year').value, scale_radius: +$('dia').value / 2, min_roller_radius: +$('minr').value,
    hour_first: $('autoHours').checked ? null : +$('hFirst').value, hour_last: $('autoHours').checked ? null : +$('hLast').value,
    place_name: state.place?.name || '', tz_name: state.tz?.tz || '',
  };
}
function stageList(stages, done, current, ahead) {
  const ol = $('stages'); ol.innerHTML = '';
  const items = ahead > 0 ? ['queued', ...stages] : stages;
  for (const st of items) {
    const li = document.createElement('li');
    li.className = done.includes(st) ? 'done' : st === current ? 'doing' : '';
    li.innerHTML = `<span class="mark"></span><span>${st === 'queued' ? t('stQueued', { n: ahead }) : t(STAGE_KEYS[st])}</span>`;
    ol.appendChild(li);
  }
}
function startMaking(body) {
  $('makingPlace').textContent = state.place?.name || `${fmtDeg(body.lat, 'N', 'S')}, ${fmtDeg(body.lon, 'E', 'W')}`;
  showBeat('making', true); showBeat('today', false); showBeat('home', false);
  $('failBox').hidden = true; $('barFill').style.width = '0%'; $('stageNote').textContent = '';
  $('stages').hidden = false; document.querySelector('#making .bar').hidden = false;
  $('makingFacts').innerHTML = '';
  $('making').scrollIntoView({ behavior: 'smooth', block: 'start' });
  // facts and figures come from the fast design call while the meshes build
  const q = new URLSearchParams({ lat: body.lat, lon: body.lon, utc_offset_h: body.utc_offset_h, year: body.year, scale_radius: body.scale_radius, min_roller_radius: body.min_roller_radius });
  if (body.hour_first != null) { q.set('hour_first', body.hour_first); q.set('hour_last', body.hour_last); }
  const ah = autoHours(body);
  makingFacts({ sunrise_earliest: ah.earliest, sunset_latest: ah.latest, hour_first: body.hour_first ?? ah.first, hour_last: body.hour_last ?? ah.last,
    minute_ticks: body.scale_radius * Math.PI / 720 >= 0.7, tilt_deg: Math.abs(body.lat) }, body);
  fetch(`/api/design?${q}`).then((r) => r.json()).then((d) => { state.design = d; makingFacts(d, body, true); redrawFigures(); animateProfiles(); }).catch(() => {});
  animateAnalemma();
  const now = zoneNow(body);
  drawSunPath($('sunPath'), body, now.y, now.mo, now.d, now.mins, { hours: (h) => fmtMins(h * 60) });
  $('sunPathCap').textContent = t('sunPathCap', { place: state.place?.name || '' });
  rotateWhy();
}
function makingFacts(d, body, full = false) {
  const rows = [
    [t('fDay'), t('fDayV', { a: fmtHM(d.sunrise_earliest), b: fmtHM(d.sunset_latest) })],
    [t('fHours'), t('fHoursV', { a: d.hour_first, b: d.hour_last, t: d.minute_ticks ? t('tick1') : t('tick5') })],
    [t('fTilt'), `${d.tilt_deg.toFixed(1)}°`],
    [t('fSummerRow'), body.summer_label ? t('yesLabel', { s: body.summer_label }) : t('noSummerRow')],
    [t('fRoller'), full ? t('fRollerV', { a: d.roller_r_min.toFixed(1), b: d.roller_r_max.toFixed(1) }) : '…'],
  ];
  const dl = $('makingFacts');
  if (full && dl.children.length === 10) { dl.lastElementChild.textContent = rows[4][1]; dl.lastElementChild.classList.add('in'); return; }
  dl.innerHTML = '';
  rows.forEach(([k, v], i) => {
    const dt = document.createElement('dt'), dd = document.createElement('dd');
    dt.textContent = k; dd.textContent = v; dt.className = dd.className = 'in'; dt.style.animationDelay = dd.style.animationDelay = `${i * 0.35}s`;
    dl.append(dt, dd);
  });
}
function animateAnalemma() {
  const p = currentParams();
  const labels = { axisEot: t('axisEot'), axisDecl: t('axisDecl'), locale: lang() };
  $('analemmaCap').textContent = t('ch1cap', { lat: fmtDeg(p.lat, 'N', 'S'), lon: fmtDeg(p.lon, 'E', 'W') });
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce) { drawAnalemma($('analemma'), p, labels, 1); return; }
  const t0 = performance.now(), dur = 2500;
  const tick = (now) => { const k = Math.min(1, (now - t0) / dur); drawAnalemma($('analemma'), p, labels, k); if (k < 1) requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
}
function animateProfiles() {
  const src = state.design; if (!src) return;
  const words = { empty: t('ch2capEmpty'), scalePlane: t('scalePlane') };
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce || !$('profileFig').clientWidth) return;
  const t0 = performance.now(), dur = 1800;
  const tick = (now) => { const k = Math.min(1, (now - t0) / dur); drawProfiles($('profileFig'), src.profiles, rollerLabels(), words, 1 - Math.pow(1 - k, 2)); if (k < 1) requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
}
function rotateWhy() {
  clearInterval(state.whyTimer);
  let i = 0;
  const show = () => { $('whyCardH').textContent = t(`wc${i + 1}h`); $('whyCardP').textContent = t(`wc${i + 1}p`); i = (i + 1) % 3; };
  show(); state.whyTimer = setInterval(show, 8000);
}
async function generate(bodyOverride) {
  const btn = $('generate'); btn.disabled = true; $('status').textContent = '';
  const body = bodyOverride || requestBody();
  startMaking(body);
  try {
    const r = await fetch('/api/generate', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Sundial-Session': SESSION_ID }, body: JSON.stringify(body) });
    if (r.status === 429) { const e = new Error(t('stBusy', { e: (await r.json()).detail })); e.plain = true; throw e; }
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    const start = await r.json();
    if (start.cached) {
      stageList(['design', 'dial', 'roller_1', 'roller_2', 'stand', 'export'], ['design', 'dial', 'roller_1', 'roller_2', 'stand', 'export'], null, 0);
      $('barFill').style.width = '100%'; $('stageNote').textContent = t('stCached');
      await new Promise((res) => setTimeout(res, 1000));
      await onResult(start.info);
    } else {
      session.set('sundial-job', { id: start.job, body });
      await followJob(start.job, start.estimates, start.stages, body);
    }
  } catch (e) { fail(e.message, body, e.plain); }
  finally { btn.disabled = false; }
}
function followJob(jid, estimates, stages, body) {
  return new Promise((resolve) => {
    let view = null, timer = null, es = null, finished = false;
    const total = stages.reduce((s, st) => s + (estimates[st] || 5), 0);
    const paint = () => {
      if (!view) return;
      const done = view.done_stages || [];
      stageList(stages, done, view.status === 'queued' ? 'queued' : view.stage, view.ahead);
      let secs = done.reduce((s, st) => s + (estimates[st] || 5), 0);
      const cur = view.stage, est = estimates[cur] || 5;
      const elapsed = view.stage_elapsed + (performance.now() - view.at) / 1000;
      if (cur) secs += Math.min(est * 0.95, elapsed);
      const frac = view.status === 'done' ? 1 : Math.min(0.97, secs / total);
      $('barFill').style.width = `${(frac * 100).toFixed(1)}%`;
      const left = Math.max(2, Math.round(total - secs));
      $('stageNote').textContent = view.status === 'queued' ? t('stQueuedNote') : view.status === 'done' ? t('stLoading') : t('toGo', { s: left });
    };
    const finish = async (v) => {
      if (finished) return; finished = true;
      clearInterval(timer); if (es) es.close();
      session.set('sundial-job', null);
      if (v.status === 'done') { view = v; view.at = performance.now(); paint(); await onResult(v.info); }
      else fail(v.error || 'failed', body);
      resolve();
    };
    const take = (v) => { view = v; view.at = performance.now(); paint(); if (v.status === 'done' || v.status === 'failed') finish(v); };
    timer = setInterval(paint, 250);
    if ('EventSource' in window) {
      es = new EventSource(`/api/jobs/${jid}/events`);
      es.onmessage = (ev) => take(JSON.parse(ev.data));
      es.addEventListener('gone', () => finish({ status: 'failed', error: t('stGone') }));
      es.onerror = () => { es.close(); es = null; poll(); };
    } else poll();
    async function poll() {
      while (!finished) {
        try { const r = await fetch(`/api/jobs/${jid}`); if (r.status === 404) return finish({ status: 'failed', error: t('stGone') }); take(await r.json()); }
        catch (e) { /* network blip: keep polling */ }
        await new Promise((res) => setTimeout(res, 1500));
      }
    }
  });
}
function fail(msg, body, plain = false) {
  $('failText').textContent = plain ? msg : t('stError', { e: msg.replace(/^generation failed:\s*/i, '') });
  const started = $('stages').children.length > 0;
  $('stages').hidden = !started; document.querySelector('#making .bar').hidden = !started;
  $('failBox').hidden = false; $('stageNote').textContent = '';
  $('retryBtn').onclick = () => generate(body);
  $('smallerBtn').onclick = () => { $('dia').value = Math.max(80, Math.round(body.scale_radius * 2 * 0.8 / 5) * 5); hints(); generate(); };
}

// ============================================================ 3 · today
async function onResult(info) {
  const g = await loadGeometries(info);
  state.geoms = g;
  if (state.hero) endHero();
  placeParts(info, g);
  clearInterval(state.whyTimer);
  afterLoad(info);
  showBeat('making', false); showBeat('today', true); showBeat('home', true);
  compactWhere(true);
  downloads(info);
  $('today').scrollIntoView({ behavior: 'smooth', block: 'start' });
}
function afterLoad(info) {
  stage.setInfo(info); state.info = info;
  const y = info.params.year;
  $('simDate').min = `${y}-01-01`; $('simDate').max = `${y}-12-31`;
  $('todayPlace').textContent = info.params.place_name || state.place?.name || `${fmtDeg(info.params.lat, 'N', 'S')}, ${fmtDeg(info.params.lon, 'E', 'W')}`;
  fillInfo(); accuracyLine(); redrawFigures();
  goTo('now'); sweepIn();
}
// choose the moment the viewer shows: now, or the next first light
function goTo(when) {
  const info = state.info; if (!info) return;
  state.when = when;
  const p = info.params, y = p.year;
  let m;
  if (when === 'now' || when === 'tomorrow') {
    const now = zoneNow(p);
    const nowInYear = { ...now, y };                      // the dial is engraved for one year: show that year's date
    m = when === 'now' ? { ...nowInYear, today: true } : nextLightMoment(p, info.design, { ...nowInYear, mins: 1440 });
    if (when === 'now') { const nl = nextLightMoment(p, info.design, nowInYear); if (!nl.today) { m = nl; state.when = 'tomorrow'; } }
  } else if (when === 'noon') { const now = zoneNow(p); m = { y, mo: now.mo, d: now.d, mins: 720, today: true }; }
  state.moment = m;
  $('simDate').value = `${m.y}-${String(m.mo).padStart(2, '0')}-${String(m.d).padStart(2, '0')}`;
  $('simTime').value = m.mins;
  $('todayEyebrow').textContent = t(state.when === 'now' ? 'todayEyebrow' : m.daysAhead > 1 ? 'laterEyebrow' : 'tomorrowEyebrow');
  update();
}
function dateParts() { return $('simDate').value.split('-').map(Number); }
function update() {
  const mins = +$('simTime').value;
  const tt = fmtMins(mins);
  $('simTimeVal').textContent = tt;
  if (!state.info) return;
  const [y, mo, d] = dateParts();
  const r = stage.setTime(y, mo, d, mins, $('rollerSel').value, $('explode').checked);
  sunShadow(r);
  const p = state.info.params;
  const dateTxt = fmtDate(y, mo, d);
  const status = !r.up ? t('below') : !r.inRange ? t('outside') : t('inPlace', { n: r.roller === 'roller_1' ? 'I' : 'II' });
  const eot = r.eotMin >= 0 ? t('eotAhead', { x: r.eotMin.toFixed(1) }) : t('eotBehind', { x: (-r.eotMin).toFixed(1) });
  const m = state.moment, atMoment = m && m.mins === mins && m.mo === mo && m.d === d;
  let lead = '';
  if (atMoment && state.when === 'now') { const wc = wallClock(p.tz_name); lead = t('readNow') + (wc && wc !== tt ? ` · ${t('clocksShow', { t: wc })}` : ''); }
  else if (atMoment && state.when === 'tomorrow') lead = (m.daysAhead > 1 ? '' : t('readTomorrow') + ' · ') + t('readFirstLight');
  for (const b of document.querySelectorAll('#chips .chip')) b.classList.toggle('on', atMoment && b.dataset.when === state.when);
  $('readout').innerHTML = `<span class="big">${tt}</span>${lead ? `<span>${lead}</span>` : ''}<span>${dateTxt}</span><span>${t('sunHigh', { x: r.elev.toFixed(0) })}</span><span>${eot}</span><span>${status}${r.wrongRoller ? ', ' + t('wrongRoller') : ''}</span>` +
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
for (const id of ['simTime', 'simDate', 'rollerSel', 'explode']) $(id).addEventListener('input', () => { if (id !== 'explode' && id !== 'rollerSel') state.moment = null; update(); });
for (const b of document.querySelectorAll('#chips .chip')) b.addEventListener('click', () => {
  if (b.dataset.when) { goTo(b.dataset.when); return; }
  const year = state.info ? state.info.params.year : +$('year').value;
  state.moment = null; $('simDate').value = `${year}-${b.dataset.date}`; $('simTime').value = b.dataset.min; update();
});
function accuracyLine() {
  const info = state.info; if (!info) return;
  const acc = (info.accuracy || []).map((a) => t('accItemShort', { from: a.from, to: a.to, m: Math.abs(a.max_error_min).toFixed(1) })).join('; ');
  const sh = (info.shadowed || []).map((x) => t('shItem', { from: x.from, to: x.to, h: x.hours })).join('; ');
  $('accLine').textContent = (acc ? t('accExc', { x: acc }) : t('accAll')) + (sh ? ' ' + t('shLine', { x: sh }) : '');
  $('warnings').innerHTML = (info.warnings || []).map((w) => `<li>${esc(w)}</li>`).join('');
}
function fillInfo() {
  const info = state.info; if (!info) return;
  const d = info.design, p = info.params;
  const rows = [
    [t('fPlace'), `${esc(p.place_name || d.location_text || (p.lat.toFixed(4) + '°, ' + p.lon.toFixed(4) + '°'))}, ${esc(p.zone_label || 'UTC' + p.utc_offset_h)}`],
    [t('fHours'), t('fHoursV', { a: d.hour_first, b: d.hour_last, t: d.minute_ticks ? t('tick1') : t('tick5') })],
    [t('fDay'), t('fDayV', { a: fmtHM(d.sunrise_earliest), b: fmtHM(d.sunset_latest) })],
    [t('fRoller'), t('fRollerV', { a: d.roller_r_min.toFixed(1), b: d.roller_r_max.toFixed(1) })],
    [t('fStand'), t('fStandV', { t: d.tilt_deg.toFixed(1), w: d.plate_bounds ? (d.plate_bounds[2] - d.plate_bounds[0]).toFixed(0) : '?', l: d.plate_bounds ? (d.plate_bounds[3] - d.plate_bounds[1]).toFixed(0) : '?' })],
  ];
  if (info.bounds) rows.push([t('fFoot'), `${(info.bounds.dial[1][0] - info.bounds.dial[0][0]).toFixed(0)} × ${(info.bounds.dial[1][1] - info.bounds.dial[0][1]).toFixed(0)} × ${(info.bounds.dial[1][2] - info.bounds.dial[0][2]).toFixed(0)} mm`]);
  const acc = (info.accuracy || []).map((a) => t('accItem', { from: a.from, to: a.to, m: Math.abs(a.max_error_min).toFixed(1), sign: t(a.sign) })).join('; ');
  rows.push([t('fAcc'), acc ? t('fAccExc', { x: acc }) : t('fAccAll')]);
  const sh = (info.shadowed || []).map((x) => t('shItem', { from: x.from, to: x.to, h: x.hours })).join('; ');
  rows.push([t('fShadow'), sh || t('never')]);
  if (info.stability) rows.push([t('fTip'), t('fTipV', { a: info.stability.tip_angle_deg.toFixed(0) })]);
  if (d.thread) rows.push([t('fThread'), t('fThreadV', { p: d.thread.pitch.toFixed(1), c: d.thread.clearance.toFixed(1) })]);
  $('infoList').innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');
}
function redrawFigures() {
  const p = currentParams();
  const labels = { axisEot: t('axisEot'), axisDecl: t('axisDecl'), locale: lang() };
  const cap = t('ch1cap', { lat: fmtDeg(p.lat, 'N', 'S'), lon: fmtDeg(p.lon, 'E', 'W') });
  for (const [c, capId] of [['analemma2', 'analemmaCap2'], ['analemma3', 'analemmaCap3']]) { if ($(c).clientWidth) drawAnalemma($(c), p, labels); $(capId).textContent = cap; }
  const src = state.info || state.design;
  const words = { empty: t('ch2capEmpty'), scalePlane: t('scalePlane') };
  const d = state.info ? state.info.design : state.design;
  const pcap = src ? t('ch2cap', { rmin: d.roller_r_min.toFixed(1), rmax: d.roller_r_max.toFixed(1), len: (d.roller_z_max - d.roller_z_min).toFixed(0) }) : t('ch2capEmpty');
  for (const [c, capId] of [['profileFig', 'profileCap'], ['profileFig2', 'profileCap2'], ['profileFig3', 'profileCap3']]) { if ($(c).clientWidth) drawProfiles($(c), src ? src.profiles : null, rollerLabels(), words); $(capId).textContent = pcap; }
}

// ============================================================ 4 · home
const PART_META = { dial: { name: 'partDial', sup: 'supDial', kind: 'dial' }, roller_1: { name: 'partR1', sup: 'supRoller', kind: 'roller' }, roller_2: { name: 'partR2', sup: 'supRoller', kind: 'roller' }, stand: { name: 'partStand', sup: 'supStand', kind: 'stand' } };
function fileUrl(info, key, name) { return `${info.files[key]}?download_name=${encodeURIComponent(name)}`; }
async function downloads(info) {
  if (STATIC) return;
  const slug = info.zip_name.replace(/\.zip$/, '');
  $('dlZip').href = `${info.zip}?download_name=${encodeURIComponent(info.zip_name)}`; $('dlZip').download = info.zip_name;
  const mb = (n) => t('dlZipSub', { mb: n ? (n / 1048576).toFixed(1) : '?' });
  $('dlZipSub').textContent = mb(info.zip_bytes);
  if (!info.zip_bytes) fetch(info.zip, { method: 'HEAD' }).then((r) => { $('dlZipSub').textContent = mb(+r.headers.get('content-length')); }).catch(() => {});
  $('dlNote').textContent = t('dlNote', { bed: info.bed_mm });
  $('thanks').hidden = true;
  const box = $('parts'); box.innerHTML = '';
  for (const key of ['dial', 'roller_1', 'roller_2', 'stand']) {
    const f = info.parts[key], meta = PART_META[key];
    const el = document.createElement('div'); el.className = 'part'; el.tabIndex = 0;
    const [x, y, z] = f.size_mm.map((v) => v.toFixed(0));
    el.innerHTML = `<canvas data-part="${key}"></canvas><div class="pname">${t(meta.name)}</div><div class="pfacts">${t('pSize', { x, y, z })}<br>${t('pWeight', { v: f.volume_cm3.toFixed(0), g: f.weight_g })}</div><div class="psup">${t(meta.sup)}</div><a href="${fileUrl(info, key, slug + '-' + key)}" download="${slug}-${key}.stl">${t('dlThis')} ↓</a>`;
    el.querySelector('a').addEventListener('click', (e) => e.stopPropagation());
    const open = () => openPart(key, info, slug);
    el.addEventListener('click', open); el.addEventListener('keydown', (e) => { if (e.key === 'Enter') open(); });
    box.appendChild(el);
  }
  state.partsDrawn = false;
  if ($('partsBox').open) drawParts();
}
function drawParts() {
  if (state.partsDrawn || !state.geoms) return;
  state.partsDrawn = true;
  for (const c of document.querySelectorAll('#parts canvas')) renderPartStill(c, state.geoms[c.dataset.part].clone(), PART_META[c.dataset.part].kind);
}
$('partsBox').addEventListener('toggle', () => { if ($('partsBox').open) drawParts(); });
function openPart(key, info, slug) {
  const dlg = $('partView'), f = info.parts[key], meta = PART_META[key];
  $('partViewH').textContent = t(meta.name);
  const [x, y, z] = f.size_mm.map((v) => v.toFixed(0));
  $('partViewNote').textContent = `${t('pSize', { x, y, z })} · ${t('pWeight', { v: f.volume_cm3.toFixed(0), g: f.weight_g })} · ${t(meta.sup)}`;
  $('partViewDl').href = fileUrl(info, key, `${slug}-${key}`); $('partViewDl').download = `${slug}-${key}.stl`;
  dlg.showModal();
  if (state.partStage) state.partStage();
  state.partStage = createPartStage($('partCanvas'), state.geoms[key].clone(), meta.kind);
}
$('partView').addEventListener('close', () => { if (state.partStage) { state.partStage(); state.partStage = null; } });
$('dlZip').addEventListener('click', () => { $('thanks').hidden = false; });
$('donate').addEventListener('click', () => $('coffee').showModal());
let historyMap = null;
async function openHistory() {
  $('history').showModal();
  try {
    const [h] = await Promise.all([(await fetch('/api/history')).json(), ensureLeaflet()]);
    $('historyCount').textContent = h.count ? t('historyCount', { n: h.count, p: h.places }) : t('historyEmpty');
    if (!historyMap) {
      historyMap = L.map('historyMap', { zoomControl: false, worldCopyJump: true }).setView([20, 0], 1);
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 12, attribution: '&copy; OpenStreetMap' }).addTo(historyMap);
      historyMap.dots = L.layerGroup().addTo(historyMap);
    }
    historyMap.dots.clearLayers();
    const byPlace = new Map();
    for (const it of h.items) { const k = `${it.lat},${it.lon}`; const e = byPlace.get(k) || { ...it, n: 0 }; e.n++; e.t = Math.max(e.t, it.t); if (it.place) e.place = it.place; byPlace.set(k, e); }
    const list = $('historyList'); list.innerHTML = '';
    for (const e of [...byPlace.values()].sort((a, b) => b.t - a.t)) {
      const when = new Date(e.t * 1000).toLocaleDateString(lang(), { day: 'numeric', month: 'short' });
      L.circleMarker([e.lat, e.lon], { radius: 5 + Math.min(6, Math.sqrt(e.n) * 2), color: '#B4842A', fillColor: '#B4842A', fillOpacity: 0.55, weight: 1 })
        .bindPopup(`${esc(e.place || `${e.lat}, ${e.lon}`)}<br>${e.n > 1 ? e.n + ' · ' : ''}${e.mm ? e.mm + ' mm · ' : ''}${when}`).addTo(historyMap.dots);
      const li = document.createElement('li'); li.innerHTML = `<span>${esc(e.place || `${e.lat}°, ${e.lon}°`)}${e.n > 1 ? ` ×${e.n}` : ''}</span><span>${when}</span>`; list.appendChild(li);
    }
    const pts = [...byPlace.values()].map((e) => [e.lat, e.lon]);
    setTimeout(() => { historyMap.invalidateSize(); if (pts.length) historyMap.fitBounds(L.latLngBounds(pts).pad(0.6), { maxZoom: 4 }); }, 80);
  } catch (e) { $('historyCount').textContent = t('stSearchFail'); }
}
$('historyBtn').addEventListener('click', openHistory);
$('shareBtn').addEventListener('click', async () => {
  const p = state.info ? state.info.params : requestBody();
  const url = `${location.origin}${location.pathname}#at=${p.lat.toFixed(4)},${p.lon.toFixed(4)},${Math.round(p.scale_radius * 2)},${p.year},${encodeURIComponent(p.place_name || '')}`;
  try { await navigator.clipboard.writeText(url); $('shareDone').textContent = t('shared'); }
  catch (e) { $('shareDone').textContent = url; }
});

// ============================================================ sheets
function openSettings() { hints(); $('settings').showModal(); }
$('openSettings').addEventListener('click', openSettings);
$('openSettings2').addEventListener('click', openSettings);
$('settings').addEventListener('close', () => { if ($('settings').returnValue === 'regen' || state.regen) { state.regen = false; generate(); } });
$('regenBtn').addEventListener('click', () => { state.regen = true; });
$('resetBtn').addEventListener('click', () => {
  $('dia').value = DEFAULTS.dia; $('year').value = DEFAULTS.year; $('minr').value = DEFAULTS.minr; $('autoHours').checked = true; $('hFirst').disabled = $('hLast').disabled = true;
  if (state.tz) { $('utc').value = state.tz.utc_offset_h; $('label').value = state.tz.label; $('summer').value = state.tz.summer_label || ''; }
  hints();
});
$('openDetails').addEventListener('click', () => { $('details').showModal(); fillInfo(); redrawFigures(); });
$('dia').addEventListener('input', hints);
$('year').addEventListener('change', hints);
$('autoHours').addEventListener('change', () => { const a = $('autoHours').checked; $('hFirst').disabled = a; $('hLast').disabled = a; hints(); });
for (const id of ['hFirst', 'hLast']) $(id).addEventListener('change', hints);
$('lat').addEventListener('change', () => setLocation(+$('lat').value, +$('lon').value, { pan: true }));
$('lon').addEventListener('change', () => setLocation(+$('lat').value, +$('lon').value, { pan: true }));
$('utc').addEventListener('change', () => { redrawFigures(); hints(); });

// ============================================================ static preview
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
  $('stage').classList.remove('loading');
  showBeat('today', true);
  afterLoad(info);
}

// ============================================================ start
function onLanguage() {
  hints(); redrawFigures(); fillInfo(); accuracyLine(); update();
  if (state.place) { $('placeName').textContent = state.place.name || t('placeGeo'); }
  heroCaption();
  if (state.info) { $('todayEyebrow').textContent = t(state.when === 'now' ? 'todayEyebrow' : 'tomorrowEyebrow'); if (!STATIC) downloads(state.info); }
  compactWhere(!!state.info);
  if (!STATIC && !$('making').hidden) rotateWhy();
}
document.addEventListener('languagechange', onLanguage);
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', redrawFigures);
if (STATIC) {
  loadStatic().catch((e) => { $('readout').innerHTML = `<span class="big">!</span><span>${e.message}</span>`; });
} else {
  $('geoBtn').addEventListener('click', () => {
    $('status').textContent = t('stLocating');
    if (!navigator.geolocation) { $('status').textContent = t('stNoGeo'); return; }
    navigator.geolocation.getCurrentPosition((p) => { $('status').textContent = ''; setLocation(p.coords.latitude, p.coords.longitude, { pan: true }); },
      () => { $('status').textContent = t('stNoGeo'); }, { timeout: 12000 });
  });
  $('searchBtn').addEventListener('click', search);
  $('search').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); search(); } if (e.key === 'Escape') closeResults(); });
  document.addEventListener('click', (e) => { if (!e.target.closest('.search-wrap')) closeResults(); });
  $('mapToggle').addEventListener('click', async () => { const b = $('mapBox'); b.hidden = !b.hidden; if (!b.hidden) { await initMap(); setTimeout(() => map.invalidateSize(), 50); } });
  $('generate').addEventListener('click', () => generate());
  $('againBtn').addEventListener('click', () => { compactWhere(false); $('where').scrollIntoView({ behavior: 'smooth' }); });
  loadHero();
  // where to start: a shared link, a job left running, the last place, or Stuttgart
  const at = (location.hash.match(/#at=([^&]+)/) || [])[1];
  const pending = session.get('sundial-job');
  const last = store.get('sundial-place');
  (async () => {
    if (at) {
      const [lat, lon, dia, year, name] = at.split(',');
      $('dia').value = +dia || DEFAULTS.dia; $('year').value = +year || DEFAULTS.year;
      await setLocation(+lat, +lon, { name: decodeURIComponent(name || '') });
      generate();
    } else if (pending) {
      const r = await fetch(`/api/jobs/${pending.id}`).catch(() => null);
      if (r && r.ok) {
        const b = pending.body;
        await setLocation(b.lat, b.lon, { name: b.place_name });
        $('dia').value = Math.round(b.scale_radius * 2); $('year').value = b.year;
        startMaking(b);
        const start = await (await fetch('/api/generate', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Sundial-Session': SESSION_ID }, body: JSON.stringify(b) })).json();
        if (start.cached) onResult(start.info); else followJob(start.job, start.estimates, start.stages, b);
      } else { session.set('sundial-job', null); await setLocation(DEFAULTS.lat, DEFAULTS.lon, { name: 'Stuttgart, Deutschland' }); }
    } else if (last && Number.isFinite(last.lat)) {
      await setLocation(last.lat, last.lon, { name: last.name });
    } else {
      await setLocation(DEFAULTS.lat, DEFAULTS.lon, { name: 'Stuttgart, Deutschland' });
    }
    if (window.matchMedia('(min-width: 900px)').matches) { $('mapBox').hidden = false; initMap(); }
  })();
}
onLanguage();
