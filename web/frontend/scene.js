import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

// Model coords are ENU (x=East, y=North, z=Up). Three.js is Y-up.
const enu = (v) => new THREE.Vector3(v[0], v[2], -v[1]);

function labelSprite(text) {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d");
  g.fillStyle = "#f2b134";
  g.font = "bold 68px system-ui, sans-serif";
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText(text, 64, 68);
  const tex = new THREE.CanvasTexture(c);
  tex.anisotropy = 4;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthWrite: false }));
  return s;
}

export class SundialScene {
  constructor(canvas) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0e1116);

    this.camera = new THREE.PerspectiveCamera(45, 1, 0.001, 100);
    this.camera.position.set(0.35, 0.28, 0.42);

    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.target.set(0, 0.03, 0);

    this.hemi = new THREE.HemisphereLight(0x9fc4ff, 0x30251a, 0.55);
    this.scene.add(this.hemi);
    this.sunLight = new THREE.DirectionalLight(0xfff2d8, 2.4);
    this.sunLight.castShadow = true;
    this.sunLight.shadow.mapSize.set(2048, 2048);
    const sc = this.sunLight.shadow.camera;
    sc.near = 0.01; sc.far = 12;
    sc.left = sc.bottom = -0.4; sc.right = sc.top = 0.4;
    this.scene.add(this.sunLight, this.sunLight.target);

    this.sunBall = new THREE.Mesh(
      new THREE.SphereGeometry(0.012, 24, 16),
      new THREE.MeshBasicMaterial({ color: 0xffe08a })
    );
    this.scene.add(this.sunBall);

    // horizon
    const grid = new THREE.GridHelper(1.2, 24, 0x2a323d, 0x1c232c);
    grid.position.y = -0.0002;
    this.scene.add(grid);
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(1.4, 1.4),
      new THREE.ShadowMaterial({ opacity: 0.32 })
    );
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    this.scene.add(ground);

    this.dialGroup = new THREE.Group();
    this.scene.add(this.dialGroup);

    this._reading = null;
    this._resize();
    window.addEventListener("resize", () => this._resize());
    this._loop();
  }

  _resize() {
    const w = this.canvas.clientWidth || 1;
    const h = this.canvas.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  _loop() {
    requestAnimationFrame(() => this._loop());
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  clearDial() {
    this.dialGroup.clear();
  }

  setDial(payload) {
    this.clearDial();
    this.data = payload;

    // ---- scale ring (minute ticks) ----
    const minPts = payload.minScale.map(enu);
    const ring = new THREE.LineLoop(
      new THREE.BufferGeometry().setFromPoints(minPts),
      new THREE.LineBasicMaterial({ color: 0x5a6572 })
    );
    this.dialGroup.add(ring);

    // ---- hour ticks + labels ----
    payload.hourScale.forEach((p, j) => {
      const v = enu(p);
      const dot = new THREE.Mesh(
        new THREE.SphereGeometry(0.004, 12, 10),
        new THREE.MeshBasicMaterial({ color: 0xf2b134 })
      );
      dot.position.copy(v);
      this.dialGroup.add(dot);
      const hour = ((Math.round((1439 - j * 60) / 60) % 24) + 24) % 24;
      const lab = labelSprite(String(hour).padStart(2, "0"));
      lab.scale.setScalar(0.03);
      lab.position.copy(v.clone().multiplyScalar(1.12));
      this.dialGroup.add(lab);
    });

    // noon tick
    const noon = new THREE.Mesh(
      new THREE.SphereGeometry(0.006, 16, 12),
      new THREE.MeshBasicMaterial({ color: 0x4a90d9 })
    );
    noon.position.copy(enu(payload.noonTick));
    this.dialGroup.add(noon);

    // ---- gnomon axis rod ----
    const [a0, a1] = payload.gnomonAxis.map(enu);
    const rod = new THREE.Mesh(
      new THREE.CylinderGeometry(0.0016, 0.0016, a0.distanceTo(a1), 16),
      new THREE.MeshStandardMaterial({ color: 0xc9d2dd, metalness: 0.6, roughness: 0.35 })
    );
    rod.position.copy(a0.clone().lerp(a1, 0.5));
    rod.quaternion.setFromUnitVectors(
      new THREE.Vector3(0, 1, 0), a1.clone().sub(a0).normalize()
    );
    rod.castShadow = true;
    this.dialGroup.add(rod);
    this._axis = { p0: a0, p1: a1 };

    // ---- gnomon roller surface ----
    if (payload.gnomonGrid) {
      const G = payload.gnomonGrid;              // [H][S][3]
      const H = G.length, S = G[0].length;
      const pos = new Float32Array(H * S * 3);
      for (let h = 0; h < H; h++)
        for (let s = 0; s < S; s++) {
          const v = enu(G[h][s]);
          const i = (h * S + s) * 3;
          pos[i] = v.x; pos[i + 1] = v.y; pos[i + 2] = v.z;
        }
      const idx = [];
      for (let h = 0; h < H; h++) {
        const h2 = (h + 1) % H;
        for (let s = 0; s < S - 1; s++) {
          const a = h * S + s, b = h2 * S + s, c = h2 * S + s + 1, d = h * S + s + 1;
          idx.push(a, b, c, a, c, d);
        }
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      geo.setIndex(idx);
      geo.computeVertexNormals();
      const roller = new THREE.Mesh(
        geo,
        new THREE.MeshStandardMaterial({
          color: 0xb8792e, metalness: 0.15, roughness: 0.75,
          side: THREE.DoubleSide, flatShading: false,
        })
      );
      roller.castShadow = true;
      roller.receiveShadow = true;
      this.dialGroup.add(roller);
    }

    // reading marker
    this._marker = new THREE.Mesh(
      new THREE.SphereGeometry(0.007, 16, 12),
      new THREE.MeshBasicMaterial({ color: 0xff5252 })
    );
    this._marker.visible = false;
    this.dialGroup.add(this._marker);
    this._markerLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
      new THREE.LineBasicMaterial({ color: 0xff5252 })
    );
    this._markerLine.visible = false;
    this.dialGroup.add(this._markerLine);

    this._ringCenter = minPts
      .reduce((s, p) => s.add(p), new THREE.Vector3())
      .multiplyScalar(1 / minPts.length);
    this._ringRadius = minPts[0].distanceTo(this._ringCenter);
    this._minPts = minPts;

    this.frameAll();
  }

  frameAll() {
    const box = new THREE.Box3().setFromObject(this.dialGroup);
    if (box.isEmpty()) return;
    const c = box.getCenter(new THREE.Vector3());
    const r = box.getBoundingSphere(new THREE.Sphere()).radius || 0.2;
    this.controls.target.copy(c);
    this.camera.position.copy(c).add(new THREE.Vector3(1, 0.75, 1.1).setLength(r * 2.6));
    this.camera.near = r / 100; this.camera.far = r * 100;
    this.camera.updateProjectionMatrix();
    const sc = this.sunLight.shadow.camera;
    sc.left = sc.bottom = -r * 1.6; sc.right = sc.top = r * 1.6; sc.far = r * 40;
    sc.updateProjectionMatrix();
  }

  /** dir: ENU unit vector toward the sun; elevationDeg for day/night feel. */
  setSun(dir, elevationDeg) {
    const d = enu(dir).normalize();
    const dist = (this._ringRadius || 0.15) * 6;
    this.sunLight.position.copy(d.clone().multiplyScalar(dist));
    this.sunLight.target.position.set(0, 0, 0);
    this.sunBall.position.copy(d.clone().multiplyScalar(dist * 0.9));

    const day = elevationDeg > 0;
    const t = THREE.MathUtils.clamp(elevationDeg / 12, 0, 1);
    this.sunLight.intensity = day ? 1.1 + 2.2 * t : 0.0;
    this.hemi.intensity = day ? 0.35 + 0.35 * t : 0.12;
    this.scene.background.setHSL(0.6, 0.25, day ? 0.05 + 0.06 * t : 0.03);
    this.sunBall.visible = elevationDeg > -3;

    this._updateReading(dir, elevationDeg);
  }

  _updateReading(dirEnu, elevationDeg) {
    if (!this._axis || !this._minPts) return;
    if (elevationDeg <= 0) {
      this._marker.visible = this._markerLine.visible = false;
      this._reading = null;
      return;
    }
    const S = enu(dirEnu).normalize();
    const axis = this._axis.p1.clone().sub(this._axis.p0).normalize();
    // component of the sun direction perpendicular to the polar axis;
    // the rod's shadow on the ring points the opposite way.
    const perp = S.clone().sub(axis.clone().multiplyScalar(S.dot(axis)));
    if (perp.lengthSq() < 1e-9) {
      this._marker.visible = this._markerLine.visible = false;
      this._reading = null;
      return;
    }
    const shadowDir = perp.normalize().multiplyScalar(-1);
    const aim = this._ringCenter.clone().add(shadowDir.multiplyScalar(this._ringRadius));

    let best = 0, bd = Infinity;
    for (let k = 0; k < this._minPts.length; k++) {
      const dd = this._minPts[k].distanceToSquared(aim);
      if (dd < bd) { bd = dd; best = k; }
    }
    const minute = (1439 - best + 1440) % 1440;
    const hh = String(Math.floor(minute / 60)).padStart(2, "0");
    const mm = String(minute % 60).padStart(2, "0");
    this._reading = `${hh}:${mm}`;

    const p = this._minPts[best];
    this._marker.position.copy(p);
    this._marker.visible = true;
    this._markerLine.geometry.setFromPoints([this._axisMid(), p]);
    this._markerLine.visible = true;
  }

  _axisMid() {
    return this._axis.p0.clone().lerp(this._axis.p1, 0.5);
  }

  get reading() { return this._reading; }
}
