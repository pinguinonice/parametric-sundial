// Shared viewer: sun position, the 3D stage, and the two explanatory figures.
// Used by the site (app.js) and inlined into the hosted preview.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import * as BufferGeometryUtils from 'three/addons/utils/BufferGeometryUtils.js';

export const DEG = Math.PI / 180;

// ---------- sun position (NOAA / Meeus), same formulas as the Python generator
export function sunGeometry(unix) {
  const T = ((unix - 946728000) / 86400) / 36525;
  const L0 = ((280.46646 + T * (36000.76983 + T * 0.0003032)) % 360 + 360) % 360;
  const M = (357.52911 + T * (35999.05029 - 0.0001537 * T)) * DEG;
  const e = 0.016708634 - T * (0.000042037 + 0.0000001267 * T);
  const C = Math.sin(M) * (1.914602 - T * (0.004817 + 0.000014 * T)) + Math.sin(2 * M) * (0.019993 - 0.000101 * T) + Math.sin(3 * M) * 0.000289;
  const omega = (125.04 - 1934.136 * T) * DEG;
  const appLong = (L0 + C - 0.00569 - 0.00478 * Math.sin(omega)) * DEG;
  const eps0 = 23 + (26 + (21.448 - T * (46.815 + T * (0.00059 - T * 0.001813))) / 60) / 60;
  const eps = (eps0 + 0.00256 * Math.cos(omega)) * DEG;
  const decl = Math.asin(Math.sin(eps) * Math.sin(appLong));
  const y = Math.tan(eps / 2) ** 2, L0r = L0 * DEG;
  const eot = y * Math.sin(2 * L0r) - 2 * e * Math.sin(M) + 4 * e * y * Math.sin(M) * Math.cos(2 * L0r) - 0.5 * y * y * Math.sin(4 * L0r) - 1.25 * e * e * Math.sin(2 * M);
  return { decl, eotMin: 4 * eot / DEG };
}
export function sunENU(unix, lat, lon) {
  const { decl } = sunGeometry(unix);
  const { eotMin } = sunGeometry(unix);
  const minutesUTC = (((unix % 86400) + 86400) % 86400) / 60;
  let H = (minutesUTC + eotMin + 4 * lon) / 4 - 180;
  H = ((H + 180) % 360 + 360) % 360 - 180;
  const h = H * DEG, p = lat * DEG;
  return [-Math.cos(decl) * Math.sin(h),
          Math.sin(decl) * Math.cos(p) - Math.cos(decl) * Math.cos(h) * Math.sin(p),
          Math.sin(decl) * Math.sin(p) + Math.cos(decl) * Math.cos(h) * Math.cos(p)];
}
export function zoneUnix(y, mo, d, hours, utcOffset) {
  return Date.UTC(y, mo - 1, d) / 1000 + (hours - utcOffset) * 3600;
}
export function sunriseMinutes(y, mo, d, params) {
  for (let m = 0; m < 1440; m += 2) {
    if (sunENU(zoneUnix(y, mo, d, m / 60, params.utc_offset_h), params.lat, params.lon)[2] > 0) return m;
  }
  return 720;
}
export const M4 = (rows) => new THREE.Matrix4().set(...rows.flat());
export const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// ---------- the stage ------------------------------------------------------
export function createStage(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  const camera = new THREE.PerspectiveCamera(34, 16 / 9, 1, 4000);
  camera.up.set(0, 0, 1);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true; controls.maxPolarAngle = Math.PI * 0.49; controls.minDistance = 120; controls.maxDistance = 900;
  scene.add(new THREE.HemisphereLight(0xfff8ee, 0xc9bda6, 0.75));   // sky and a warm ground bounce so undersides read
  const sun = new THREE.DirectionalLight(0xfff1d6, 2.6);
  sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -230, right: 230, top: 230, bottom: -230, near: 10, far: 1600 });
  sun.shadow.bias = -0.0002; sun.shadow.normalBias = 0.03; sun.shadow.radius = 3;
  scene.add(sun, sun.target);

  // ground: a stone disc with a soft radial gradient, receives the shadow
  const gc = document.createElement('canvas'); gc.width = gc.height = 512;
  const gx = gc.getContext('2d'); const grad = gx.createRadialGradient(256, 256, 40, 256, 256, 256);
  grad.addColorStop(0, '#e6dfd0'); grad.addColorStop(0.7, '#d7cfbd'); grad.addColorStop(1, '#c9c0ad');
  gx.fillStyle = grad; gx.fillRect(0, 0, 512, 512);
  const gtex = new THREE.CanvasTexture(gc); gtex.colorSpace = THREE.SRGBColorSpace;
  const ground = new THREE.Mesh(new THREE.CircleGeometry(520, 96), new THREE.MeshStandardMaterial({ map: gtex, roughness: 0.95, metalness: 0 }));
  ground.receiveShadow = true; ground.position.z = -0.05; scene.add(ground);
  const north = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0.3), new THREE.Vector3(0, 175, 0.3)]),
    new THREE.LineBasicMaterial({ color: 0xb4842a }));
  scene.add(north);
  const lc = document.createElement('canvas'); lc.width = 128; lc.height = 64; const lx = lc.getContext('2d');
  lx.font = 'bold 44px Georgia, serif'; lx.textAlign = 'center'; lx.fillStyle = '#b4842a'; lx.fillText('N', 64, 48);
  const nLabel = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(lc), transparent: true }));
  nLabel.scale.set(22, 11, 1); nLabel.position.set(0, 190, 2); scene.add(nLabel);
  const dot = new THREE.Mesh(new THREE.SphereGeometry(1.4, 16, 16), new THREE.MeshBasicMaterial({ color: 0xe0281a })); dot.visible = false; scene.add(dot);
  const sunBall = new THREE.Mesh(new THREE.SphereGeometry(7, 20, 20), new THREE.MeshBasicMaterial({ color: 0xffd36a })); sunBall.visible = false; scene.add(sunBall);

  const materials = {
    dial: () => new THREE.MeshStandardMaterial({ color: 0xd8d2c4, roughness: 0.62, metalness: 0.05 }),
    roller: () => new THREE.MeshStandardMaterial({ color: 0xc89b46, roughness: 0.32, metalness: 0.75 }),
    stand: () => new THREE.MeshStandardMaterial({ color: 0x4b4d52, roughness: 0.7, metalness: 0.15 }),
  };
  const parts = {};
  let info = null;

  function resize() {
    const w = canvas.clientWidth, h = Math.round(w * 9 / 16);
    if (w && (canvas.width !== w || canvas.height !== h)) { renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
  }
  (function loop() { resize(); controls.update(); renderer.render(scene, camera); requestAnimationFrame(loop); })();

  function addPart(name, geometry, rows) {
    if (parts[name]) { scene.remove(parts[name]); parts[name].geometry.dispose(); }
    // normals with a crease angle: flat faces and engraved edges stay crisp,
    // the dish and the roller stay smooth (plain vertex normals smear the
    // engraving across the big flat triangles of the base and the wings)
    if (geometry.index) geometry = geometry.toNonIndexed();
    geometry = BufferGeometryUtils.toCreasedNormals(geometry, Math.PI / 7);
    const kind = name.startsWith('roller') ? 'roller' : name;
    const mesh = new THREE.Mesh(geometry, materials[kind]());
    mesh.castShadow = mesh.receiveShadow = true;
    mesh.matrixAutoUpdate = false; mesh.userData.base = M4(rows); mesh.matrix.copy(mesh.userData.base);
    scene.add(mesh); parts[name] = mesh;
  }
  function setInfo(i) {
    info = i;
    const c = i.assembly.dial_centre_enu, R = i.design.outer_radius;
    controls.target.set(c[0], c[1], c[2] - 6);
    camera.position.set(c[0] + 2.1 * R, c[1] - 3.0 * R, c[2] + 1.6 * R);
    dot.visible = true;
  }
  function rollerForDate(mo, d) {
    return (mo < 6 || (mo === 6 && d < 21) || (mo === 12 && d >= 21)) ? 'roller_1' : 'roller_2';
  }
  // returns readout data
  function setTime(y, mo, d, mins, rollerChoice, explode) {
    if (!info) return null;
    const p = info.params, des = info.design;
    const unix = zoneUnix(y, mo, d, mins / 60, p.utc_offset_h);
    const v = sunENU(unix, p.lat, p.lon);
    const c = info.assembly.dial_centre_enu;
    sun.position.set(c[0] + v[0] * 700, c[1] + v[1] * 700, c[2] + v[2] * 700); sun.target.position.set(c[0], c[1], c[2]);
    sunBall.position.set(c[0] + v[0] * 420, c[1] + v[1] * 420, c[2] + v[2] * 420);
    const elev = Math.asin(v[2]) / DEG, az = (Math.atan2(v[0], v[1]) / DEG + 360) % 360;
    const up = elev > 0;
    sun.intensity = up ? 2.6 * Math.min(1, elev / 8) : 0; sunBall.visible = up;
    const roller = rollerChoice === 'auto' ? rollerForDate(mo, d) : rollerChoice;
    const axis = new THREE.Vector3(...info.assembly.dial_to_world.map((r) => r[2]).slice(0, 3));
    for (const [name, mesh] of Object.entries(parts)) {
      mesh.visible = !(name.startsWith('roller') && name !== roller);
      mesh.matrix.copy(mesh.userData.base);
      if (explode) { const k = name === 'dial' ? 1 : name.startsWith('roller') ? 2.2 : 0; mesh.matrix.premultiply(new THREE.Matrix4().makeTranslation(axis.x * 70 * k, axis.y * 70 * k, axis.z * 70 * k)); }
    }
    const psi = (des.psi_noon_deg + des.omega * 15 * (mins / 60 - 12)) * DEG;
    dot.position.set(des.scale_radius * Math.sin(psi), des.scale_radius * Math.cos(psi), 0).applyMatrix4(M4(info.assembly.dial_to_world));
    dot.visible = up;
    const { eotMin } = sunGeometry(unix);
    return { elev, az, up, roller, eotMin, inRange: mins / 60 >= des.hour_first && mins / 60 <= des.hour_last, wrongRoller: rollerChoice !== 'auto' && roller !== rollerForDate(mo, d) };
  }
  // scripted camera for the visual audit: azimuth from north clockwise,
  // elevation above the ground, distance in mm, target in ENU (default the
  // dial centre) plus an optional offset in the dial's own frame
  function setView({ az = 180, elev = 25, dist = 300, target = null, dialOffset = null } = {}) {
    let tgt = target ? new THREE.Vector3(...target) : (info ? new THREE.Vector3(...info.assembly.dial_centre_enu) : new THREE.Vector3(0, 0, 60));
    if (dialOffset && info) {
      const M = M4(info.assembly.dial_to_world);
      const o = new THREE.Vector3(...dialOffset).applyMatrix4(M).sub(new THREE.Vector3(...info.assembly.dial_centre_enu));
      tgt = tgt.add(o);
    }
    const a = az * DEG, e = elev * DEG;
    controls.maxPolarAngle = elev < 0 ? Math.PI : Math.PI * 0.49;
    controls.minDistance = 20;
    controls.target.copy(tgt);
    camera.position.set(tgt.x + dist * Math.sin(a) * Math.cos(e), tgt.y + dist * Math.cos(a) * Math.cos(e), tgt.z + dist * Math.sin(e));
    controls.update();
  }
  return { scene, camera, renderer, addPart, setInfo, setTime, setView, rollerForDate, get info() { return info; } };
}

// ---------- figures --------------------------------------------------------
function setupCanvas(canvas) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = canvas.clientWidth || 640, h = Math.round(w * (canvas.height / canvas.width || 0.875));
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr);
  return { ctx, w, h };
}
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function drawAnalemma(canvas, params, labels = {}) {
  const L = { axisEot: 'sun early  \u2190  equation of time  \u2192  sun late', axisDecl: 'height of the sun', locale: 'en', ...labels };
  const { ctx, w, h } = setupCanvas(canvas);
  const ink = cssVar('--ink') || '#222', muted = cssVar('--muted') || '#777', brass = cssVar('--brass') || '#b4842a', line = cssVar('--line') || '#ddd';
  const pad = { l: 46, r: 18, t: 22, b: 40 };
  const x = (e) => pad.l + (e + 18) / 36 * (w - pad.l - pad.r);
  const y = (dcl) => pad.t + (25 - dcl) / 50 * (h - pad.t - pad.b);
  ctx.clearRect(0, 0, w, h);
  ctx.font = '12px "Source Sans 3", system-ui, sans-serif'; ctx.fillStyle = muted; ctx.strokeStyle = line; ctx.lineWidth = 1;
  for (let e = -15; e <= 15; e += 5) { ctx.beginPath(); ctx.moveTo(x(e), pad.t); ctx.lineTo(x(e), h - pad.b); ctx.stroke(); ctx.textAlign = 'center'; ctx.fillText((e > 0 ? '+' : '') + e + ' min', x(e), h - pad.b + 16); }
  for (let dcl = -20; dcl <= 20; dcl += 10) { ctx.beginPath(); ctx.moveTo(pad.l, y(dcl)); ctx.lineTo(w - pad.r, y(dcl)); ctx.stroke(); ctx.textAlign = 'right'; ctx.fillText(dcl + '°', pad.l - 6, y(dcl) + 4); }
  ctx.fillStyle = muted; ctx.textAlign = 'center'; ctx.fillText(L.axisEot, w / 2, h - 6);
  ctx.save(); ctx.translate(12, h / 2); ctx.rotate(-Math.PI / 2); ctx.fillText(L.axisDecl, 0, 0); ctx.restore();
  const year = params.year || 2026;
  const pts = [];
  for (let day = 0; day < 366; day++) {
    const unix = Date.UTC(year, 0, 1) / 1000 + day * 86400 + (12 - params.utc_offset_h) * 3600;
    const g = sunGeometry(unix);
    pts.push({ x: x(-g.eotMin), y: y(g.decl / DEG), day });
  }
  ctx.beginPath(); pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y))); ctx.closePath();
  ctx.strokeStyle = brass; ctx.lineWidth = 2.2; ctx.stroke();
  ctx.fillStyle = ink; ctx.font = '600 12px "Source Sans 3", system-ui, sans-serif';
  for (let m = 0; m < 12; m++) {
    const day = Math.round((Date.UTC(year, m, 1) - Date.UTC(year, 0, 1)) / 86400000);
    const p = pts[day]; ctx.beginPath(); ctx.arc(p.x, p.y, 3, 0, 7); ctx.fill();
    const mn = new Date(Date.UTC(year, m, 1)).toLocaleDateString(L.locale, { month: 'short', timeZone: 'UTC' });
    ctx.textAlign = p.x > w / 2 ? 'left' : 'right'; ctx.fillText(mn, p.x + (p.x > w / 2 ? 7 : -7), p.y + 4);
  }
  ctx.strokeStyle = muted; ctx.setLineDash([3, 4]); ctx.beginPath(); ctx.moveTo(x(0), pad.t); ctx.lineTo(x(0), h - pad.b); ctx.stroke(); ctx.setLineDash([]);
}

export function drawProfiles(canvas, profiles, labels, words = {}) {
  const W = { empty: 'compute a dial to see its two rollers', scalePlane: 'scale plane', ...words };
  const { ctx, w, h } = setupCanvas(canvas);
  const ink = cssVar('--ink') || '#222', muted = cssVar('--muted') || '#777', brass = cssVar('--brass') || '#b4842a', line = cssVar('--line') || '#ddd';
  ctx.clearRect(0, 0, w, h);
  if (!profiles) {
    ctx.fillStyle = muted; ctx.font = 'italic 16px "Cormorant Garamond", Georgia, serif'; ctx.textAlign = 'center';
    ctx.fillText(W.empty, w / 2, h / 2); return;
  }
  const names = Object.keys(profiles);
  const zAll = names.flatMap((n) => profiles[n].z), rAll = names.flatMap((n) => profiles[n].r);
  const zMin = Math.min(...zAll), zMax = Math.max(...zAll), rMax = Math.max(...rAll);
  const pad = { t: 34, b: 34 };
  const scale = (h - pad.t - pad.b) / (zMax - zMin);
  const slot = w / names.length;
  names.forEach((n, k) => {
    const cx = slot * (k + 0.5);
    const pr = profiles[n];
    const Y = (z) => h - pad.b - (z - zMin) * scale;
    ctx.beginPath();
    pr.z.forEach((z, i) => { const X = cx + pr.r[i] * scale; i ? ctx.lineTo(X, Y(z)) : ctx.moveTo(X, Y(z)); });
    for (let i = pr.z.length - 1; i >= 0; i--) ctx.lineTo(cx - pr.r[i] * scale, Y(pr.z[i]));
    ctx.closePath();
    ctx.fillStyle = brass; ctx.globalAlpha = 0.85; ctx.fill(); ctx.globalAlpha = 1;
    ctx.strokeStyle = line; ctx.setLineDash([3, 4]); ctx.beginPath(); ctx.moveTo(cx, pad.t - 10); ctx.lineTo(cx, h - pad.b + 10); ctx.stroke(); ctx.setLineDash([]);
    ctx.strokeStyle = muted; ctx.beginPath(); ctx.moveTo(cx - rMax * scale - 14, Y(0)); ctx.lineTo(cx + rMax * scale + 14, Y(0)); ctx.stroke();
    ctx.fillStyle = ink; ctx.font = '600 20px "Cormorant Garamond", Georgia, serif'; ctx.textAlign = 'center';
    ctx.fillText(labels[n].name, cx, 22);
    ctx.font = '12px "Source Sans 3", system-ui, sans-serif'; ctx.fillStyle = muted;
    ctx.fillText(labels[n].top, cx, pad.t - 2); ctx.fillText(labels[n].bottom, cx, h - 8);
    ctx.textAlign = 'left'; ctx.fillText(W.scalePlane, cx + rMax * scale + 18, Y(0) + 4);
  });
}
