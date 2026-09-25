import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';

const $ = (id) => document.getElementById(id);
const state = { info: null, sun: null, meshes: {}, sunDateKey: null };

// ---------------------------------------------------------------- map
const map = L.map('map', { zoomControl: true }).setView([48.7758, 9.1829], 5);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 18, attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
const marker = L.marker([48.7758, 9.1829], { draggable: true }).addTo(map);
marker.on('dragend', () => setLocation(marker.getLatLng().lat, marker.getLatLng().lng));
map.on('click', (e) => setLocation(e.latlng.lat, e.latlng.lng));

async function setLocation(lat, lon, pan = false) {
  lat = Math.max(-89.9, Math.min(89.9, lat));
  lon = ((lon + 540) % 360) - 180;
  $('lat').value = lat.toFixed(4);
  $('lon').value = lon.toFixed(4);
  marker.setLatLng([lat, lon]);
  if (pan) map.setView([lat, lon], Math.max(map.getZoom(), 8));
  try {
    const r = await fetch(`/api/timezone?lat=${lat}&lon=${lon}`);
    const tz = await r.json();
    $('utc').value = tz.utc_offset_h;
    $('label').value = tz.label;
    $('tzHint').innerHTML = `Zone <strong>${tz.tz || 'unknown'}</strong>, standard offset UTC${tz.utc_offset_h >= 0 ? '+' : ''}${tz.utc_offset_h}` +
      (tz.dst ? '. This zone uses daylight-saving time: the dial shows <strong>standard time</strong>, add one hour in summer (engraved on the dial too).' : '. No daylight-saving time in this zone.');
  } catch (e) { /* offline: keep manual values */ }
}
$('lat').addEventListener('change', () => setLocation(+$('lat').value, +$('lon').value, true));
$('lon').addEventListener('change', () => setLocation(+$('lat').value, +$('lon').value, true));
$('geoBtn').addEventListener('click', () => {
  navigator.geolocation?.getCurrentPosition((p) => setLocation(p.coords.latitude, p.coords.longitude, true),
    () => { $('status').textContent = 'Browser location not available.'; });
});
async function search() {
  const q = $('search').value.trim();
  if (!q) return;
  $('status').textContent = 'Searching…';
  try {
    const r = await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(q)}`,
      { headers: { 'Accept-Language': 'en' } });
    const res = await r.json();
    if (!res.length) { $('status').textContent = 'Nothing found.'; return; }
    $('status').textContent = res[0].display_name;
    await setLocation(+res[0].lat, +res[0].lon, true);
  } catch (e) { $('status').textContent = 'Search failed (network).'; }
}
$('searchBtn').addEventListener('click', search);
$('search').addEventListener('keydown', (e) => { if (e.key === 'Enter') search(); });

$('dia').addEventListener('input', () => { $('diaVal').textContent = $('dia').value; });
$('autoHours').addEventListener('change', () => {
  const a = $('autoHours').checked; $('hFirst').disabled = a; $('hLast').disabled = a;
});

// ---------------------------------------------------------------- three.js
const canvas = $('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(38, 4 / 3, 1, 5000);
camera.up.set(0, 0, 1);
camera.position.set(220, -260, 190);
const controls = new OrbitControls(camera, canvas);
controls.target.set(0, 40, 60);
controls.enableDamping = true;

const hemi = new THREE.HemisphereLight(0xffffff, 0x8b7d66, 0.55);
scene.add(hemi);
const sunLight = new THREE.DirectionalLight(0xfff4e0, 2.2);
sunLight.castShadow = true;
sunLight.shadow.mapSize.set(4096, 4096);
sunLight.shadow.camera.left = -220; sunLight.shadow.camera.right = 220;
sunLight.shadow.camera.top = 220; sunLight.shadow.camera.bottom = -220;
sunLight.shadow.camera.near = 10; sunLight.shadow.camera.far = 1500;
sunLight.shadow.bias = -0.00015;
sunLight.shadow.normalBias = 0.02;
scene.add(sunLight); scene.add(sunLight.target);
const fill = new THREE.DirectionalLight(0xffffff, 0.25); fill.position.set(-200, -100, 300); scene.add(fill);

const ground = new THREE.Mesh(new THREE.CircleGeometry(600, 96),
  new THREE.MeshStandardMaterial({ color: 0xd9d3c4, roughness: 1 }));
ground.receiveShadow = true; ground.position.z = -0.05; scene.add(ground);
// compass rose
const rose = new THREE.Group();
const arrow = (dir, color, text) => {
  const g = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0.3), dir.clone().multiplyScalar(150).setZ(0.3)]);
  rose.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color })));
};
arrow(new THREE.Vector3(0, 1, 0), 0xc0392b); arrow(new THREE.Vector3(1, 0, 0), 0x7f8c8d);
arrow(new THREE.Vector3(0, -1, 0), 0x7f8c8d); arrow(new THREE.Vector3(-1, 0, 0), 0x7f8c8d);
scene.add(rose);
const northLabel = makeLabel('N', 0xc0392b); northLabel.position.set(0, 165, 2); scene.add(northLabel);

const partsGroup = new THREE.Group(); scene.add(partsGroup);
const markDot = new THREE.Mesh(new THREE.SphereGeometry(1.2, 16, 16), new THREE.MeshBasicMaterial({ color: 0xe0281a }));
markDot.visible = false; scene.add(markDot);
const sunBall = new THREE.Mesh(new THREE.SphereGeometry(6, 16, 16), new THREE.MeshBasicMaterial({ color: 0xffc23a }));
sunBall.visible = false; scene.add(sunBall);

function makeLabel(text, color) {
  const c = document.createElement('canvas'); c.width = 128; c.height = 64;
  const ctx = c.getContext('2d'); ctx.font = 'bold 44px sans-serif'; ctx.textAlign = 'center';
  ctx.fillStyle = '#' + color.toString(16).padStart(6, '0'); ctx.fillText(text, 64, 48);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), transparent: true }));
  s.scale.set(24, 12, 1); return s;
}

function resize() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (canvas.width !== w || canvas.height !== h) {
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  }
}
function animate() { resize(); controls.update(); renderer.render(scene, camera); requestAnimationFrame(animate); }
animate();

const mat = (color) => new THREE.MeshStandardMaterial({ color, roughness: 0.55, metalness: 0.15, flatShading: false });
const loader = new STLLoader();
function loadSTL(url) {
  return new Promise((res, rej) => loader.load(url, (g) => { g.computeVertexNormals(); res(g); }, undefined, rej));
}
function matrixFromRows(rows) { const m = new THREE.Matrix4(); m.set(...rows.flat()); return m; }

// ---------------------------------------------------------------- generate
$('generate').addEventListener('click', generate);
async function generate() {
  const btn = $('generate'); btn.disabled = true; $('status').textContent = 'Computing sun positions and building meshes… (a few seconds)';
  const body = {
    lat: +$('lat').value, lon: +$('lon').value, utc_offset_h: +$('utc').value, zone_label: $('label').value,
    year: +$('year').value, scale_radius: +$('dia').value / 2, min_roller_radius: +$('minr').value,
    hour_first: $('autoHours').checked ? null : +$('hFirst').value,
    hour_last: $('autoHours').checked ? null : +$('hLast').value,
  };
  try {
    const r = await fetch('/api/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    const info = await r.json();
    state.info = info;
    await showParts(info);
    fillInfo(info);
    $('status').textContent = 'Done. Drag to orbit, scroll to zoom.';
    $('simDate').min = `${body.year}-01-01`; $('simDate').max = `${body.year}-12-31`;
    if (!$('simDate').value.startsWith(String(body.year))) $('simDate').value = `${body.year}-05-20`;
    state.sunDateKey = null; await updateSun();
  } catch (e) {
    $('status').textContent = 'Error: ' + e.message;
  } finally { btn.disabled = false; }
}

async function showParts(info) {
  partsGroup.clear(); state.meshes = {};
  const [gDial, gR1, gR2, gStand] = await Promise.all([
    loadSTL(info.files.dial), loadSTL(info.files.roller_1), loadSTL(info.files.roller_2), loadSTL(info.files.stand)]);
  const add = (name, geom, color, rows) => {
    const m = new THREE.Mesh(geom, mat(color)); m.castShadow = true; m.receiveShadow = true;
    m.matrixAutoUpdate = false; m.userData.base = matrixFromRows(rows); m.matrix.copy(m.userData.base);
    partsGroup.add(m); state.meshes[name] = m; return m;
  };
  add('dial', gDial, 0xbfc3c9, info.assembly.dial_to_world);
  add('roller_1', gR1, 0x8fa6c4, info.assembly.rollers_to_world.roller_1);
  add('roller_2', gR2, 0xc4a68f, info.assembly.rollers_to_world.roller_2);
  add('stand', gStand, 0x9a9da3, info.assembly.stand_to_world);
  const c = info.assembly.dial_centre_enu;
  controls.target.set(c[0], c[1], c[2]);
  const R = info.design.outer_radius;
  camera.position.set(c[0] + 2.2 * R, c[1] - 3.0 * R, c[2] + 2.0 * R);
  applyViewOptions();
  $('downloads').classList.remove('hidden');
  $('dlZip').href = info.zip; $('dlDial').href = info.files.dial; $('dlR1').href = info.files.roller_1;
  $('dlR2').href = info.files.roller_2; $('dlStand').href = info.files.stand;
}

function applyViewOptions() {
  if (!state.info) return;
  const sel = $('rollerSel').value; const explode = $('explode').checked;
  const axis = new THREE.Vector3(...state.info.assembly.dial_to_world.map((r) => r[2]).slice(0, 3));
  for (const [name, m] of Object.entries(state.meshes)) {
    m.visible = !(name.startsWith('roller') && name !== sel);
    m.matrix.copy(m.userData.base);
    if (explode) {
      const k = name === 'dial' ? 1.0 : name.startsWith('roller') ? 2.2 : 0;
      const t = new THREE.Matrix4().makeTranslation(axis.x * 70 * k, axis.y * 70 * k, axis.z * 70 * k);
      m.matrix.premultiply(t);
    }
  }
}
$('rollerSel').addEventListener('change', () => { applyViewOptions(); updateSun(); });
$('explode').addEventListener('change', applyViewOptions);
$('shadow').addEventListener('change', updateSun);
$('simDate').addEventListener('change', () => { state.sunDateKey = null; updateSun(); });
$('simTime').addEventListener('input', updateSun);

async function updateSun() {
  const on = $('shadow').checked;
  sunLight.visible = on; sunBall.visible = on && !!state.info; markDot.visible = on && !!state.info;
  const mins = +$('simTime').value; const hh = Math.floor(mins / 60), mm = mins % 60;
  $('simTimeVal').textContent = `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
  if (!on) { $('overlay').textContent = ''; return; }
  const lat = +$('lat').value, lon = +$('lon').value, utc = +$('utc').value;
  const date = $('simDate').value; if (!date) return;
  const [y, mo, d] = date.split('-').map(Number);
  const key = `${lat},${lon},${utc},${date}`;
  if (state.sunDateKey !== key) {
    const r = await fetch(`/api/sun?lat=${lat}&lon=${lon}&utc_offset_h=${utc}&year=${y}&month=${mo}&day=${d}&step_min=2`);
    state.sun = await r.json(); state.sunDateKey = key;
  }
  const i = Math.min(state.sun.hours.length - 1, Math.round((mins / 60) / (state.sun.hours[1] - state.sun.hours[0])));
  const v = state.sun.enu[i];
  const c = state.info ? state.info.assembly.dial_centre_enu : [0, 0, 60];
  const dist = 700;
  sunLight.position.set(c[0] + v[0] * dist, c[1] + v[1] * dist, c[2] + v[2] * dist);
  sunLight.target.position.set(c[0], c[1], c[2]);
  sunBall.position.set(c[0] + v[0] * 380, c[1] + v[1] * 380, c[2] + v[2] * 380);
  const elev = Math.asin(v[2]) * 180 / Math.PI;
  const az = (Math.atan2(v[0], v[1]) * 180 / Math.PI + 360) % 360;
  sunLight.intensity = elev > 0 ? 2.2 : 0.0;
  let txt = `${date} ${$('simTimeVal').textContent} standard time\nsun elevation ${elev.toFixed(1)}°, azimuth ${az.toFixed(1)}°`;
  if (state.info) {
    // red dot: where the leading shadow edge should cross the reading circle now
    const des = state.info.design;
    const psi = (des.psi_noon_deg + des.omega * 15 * (mins / 60 - 12)) * Math.PI / 180;
    const R = des.scale_radius;
    const p = new THREE.Vector3(R * Math.sin(psi), R * Math.cos(psi), 0).applyMatrix4(matrixFromRows(state.info.assembly.dial_to_world));
    markDot.position.copy(p);
    const inRange = mins / 60 >= des.hour_first && mins / 60 <= des.hour_last;
    const half = (mo < 6 || (mo === 6 && d < 21) || (mo === 12 && d >= 21)) ? 'roller_1' : 'roller_2';
    txt += elev <= 0 ? '\nsun below horizon' : `\nred dot = expected reading${inRange ? '' : ' (outside scale)'}` +
      (half !== $('rollerSel').value ? `\n⚠ this date needs ${half === 'roller_1' ? 'roller I' : 'roller II'}` : '');
  }
  $('overlay').textContent = txt;
}

function fillInfo(info) {
  const d = info.design; const p = info.params;
  const rows = [
    ['Location', `${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}`],
    ['Zone', `${p.zone_label || ''} (UTC${p.utc_offset_h >= 0 ? '+' : ''}${p.utc_offset_h})`],
    ['Scale', `hours ${d.hour_first}–${d.hour_last}, ${d.minute_ticks ? 'minute' : '5-minute'} ticks, Ø ${(2 * d.scale_radius).toFixed(0)} mm`],
    ['Earliest sunrise / latest sunset', `${fmtH(d.sunrise_earliest)} / ${fmtH(d.sunset_latest)} standard time`],
    ['Roller', `radius ${d.roller_r_min.toFixed(1)}–${d.roller_r_max.toFixed(1)} mm, length ${(d.roller_z_max - d.roller_z_min).toFixed(0)} mm profile`],
    ['Noon mark offset', `${d.psi_noon_deg.toFixed(2)}° (longitude + equation of time + roller thickness)`],
    ['Stand', `tilt ${d.tilt_deg.toFixed(1)}°, base Ø ${(2 * d.base_radius).toFixed(0)} mm`],
    ['Dial footprint', `${(info.bounds.dial[1][0] - info.bounds.dial[0][0]).toFixed(0)} × ${(info.bounds.dial[1][1] - info.bounds.dial[0][1]).toFixed(0)} × ${(info.bounds.dial[1][2] - info.bounds.dial[0][2]).toFixed(0)} mm`],
  ];
  const acc = (info.accuracy || []).map((a) => `${a.from}–${a.to}: up to ${Math.abs(a.max_error_min).toFixed(1)} min ${a.sign}`);
  rows.push(['Accuracy', acc.length ? `better than 0.5 min, except ${acc.join('; ')} (solstice limit of any roller dial)` : 'better than 0.5 min all year']);
  const sh = (info.shadowed || []).map((x) => `${x.from}–${x.to} (${x.hours})`);
  rows.push(['Shadowed by the wings', sh.length ? sh.join('; ') + ' — low sun skims the opposite wing tip' : 'never']);
  $('infoList').innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');
  $('warnings').innerHTML = info.warnings.map((w) => `<li>${w}</li>`).join('');
  $('info').classList.remove('hidden');
}
function fmtH(h) { const hh = Math.floor(h), mm = Math.round((h - hh) * 60); return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`; }

setLocation(48.7758, 9.1829);
