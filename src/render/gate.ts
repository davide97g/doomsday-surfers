// The checkpoint gate: a giant foldable phone hung across the track.
//
//   approach  folded shut (you see its dark back), then the lower half swings
//             down on its hinge, column by column, into one big screen.
//   scan      the twelve screen panels tear off, barrel-roll and lock into a
//             halo around the runner; a rail lights up (the camera rides it,
//             see GameRenderer.syncCamera), a laser ring sweeps the body.
//   exit      the halo spirals up and away. The empty frame stays behind.
//
// Everything is driven by World.gateT / nextGate; nothing here mutates the sim.

import * as THREE from 'three';
import content from '../config/content.json';
import { gateS } from '../sim/types';
import type { World } from '../sim/world';
import { atlasMaterial, cellAttribute } from './atlas';
import { FEED_ATLAS, makeGateSign } from './textures';

const PANELS = 12;
const COLS = 6;
const PW = 1.4;
const PH = 1.3;
const HINGE_Y = 5.0;
const PYLON_X = 4.3;
// High enough that no panel crosses the camera's line to the runner.
const HALO_R = 4.0;
const HALO_Y = 5.0;
const HALO_TILT = 0.42;
const RAIL_Y = HALO_Y + PH / 2 + 0.2;
const FLY = 0.55; // seconds for a panel to fly from the frame into the halo
const EXIT = 0.6; // seconds before the end of the scan the halo leaves

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const ease = (x: number) => {
  const k = clamp01(x);
  return k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
};

export class Gate {
  private readonly root = new THREE.Group();
  private readonly frame = new THREE.Group();
  private readonly screens: THREE.InstancedMesh;
  private readonly backs: THREE.InstancedMesh;
  private readonly rail: THREE.Mesh;
  private readonly scanRing: THREE.Mesh;
  private readonly lasers: THREE.LineSegments;
  private readonly laserPos: THREE.BufferAttribute;
  private readonly laserMat: THREE.LineBasicMaterial;
  private readonly scanMat: THREE.MeshBasicMaterial;
  private readonly dummy = new THREE.Object3D();
  private readonly qa = new THREE.Quaternion();
  private readonly qb = new THREE.Quaternion();
  private readonly qs = new THREE.Quaternion();
  private readonly foldEuler = new THREE.Euler();
  private readonly haloEuler = new THREE.Euler(0, 0, 0, 'YXZ');
  private readonly a = new THREE.Vector3();
  private readonly b = new THREE.Vector3();
  private readonly zAxis = new THREE.Vector3(0, 0, 1);

  /** `glow` is the zone-tinted seam material, so the gate re-colours with the feed. */
  constructor(scene: THREE.Scene, feedAtlas: THREE.Texture, dark: THREE.Material, glow: THREE.Material, private readonly visibleAhead: number) {
    // --- the frame: two pylons, a beam with a sign, a glowing hinge line ---
    const pylonGeo = new THREE.BoxGeometry(0.5, 7.0, 0.6);
    const stripGeo = new THREE.BoxGeometry(0.08, 6.6, 0.64);
    for (const side of [-1, 1]) {
      const pylon = new THREE.Mesh(pylonGeo, dark);
      pylon.position.set(side * PYLON_X, 3.5, 0);
      const strip = new THREE.Mesh(stripGeo, glow);
      strip.position.set(side * (PYLON_X - 0.26), 3.4, 0);
      this.frame.add(pylon, strip);
    }
    const beamY = HINGE_Y + PH + 0.3;
    const beam = new THREE.Mesh(new THREE.BoxGeometry(2 * PYLON_X + 0.5, 0.5, 0.5), dark);
    beam.position.y = beamY;
    const sign = new THREE.Mesh(new THREE.PlaneGeometry(5.4, 0.5), new THREE.MeshBasicMaterial({ map: makeGateSign(content.gate.tag), color: new THREE.Color(1.4, 1.4, 1.5) }));
    sign.position.set(0, beamY + 0.55, 0);
    const hinge = new THREE.Mesh(new THREE.BoxGeometry(COLS * (PW + 0.04), 0.07, 0.07), glow);
    hinge.position.set(0, HINGE_Y, -0.06);
    this.frame.add(beam, sign, hinge);
    this.root.add(this.frame);

    // --- the twelve panels: a feed screen on the front, a dark slab behind ---
    const screenGeo = new THREE.PlaneGeometry(PW - 0.08, PH - 0.08).translate(0, 0, 0.051);
    const cells = cellAttribute(screenGeo, PANELS);
    for (let i = 0; i < PANELS; i++) cells.setX(i, (i * 5 + 3) % (FEED_ATLAS.cols * FEED_ATLAS.rows));
    this.screens = new THREE.InstancedMesh(screenGeo, atlasMaterial(feedAtlas, new THREE.Color(1.15, 1.15, 1.25)), PANELS);
    this.backs = new THREE.InstancedMesh(new THREE.BoxGeometry(PW, PH, 0.1), dark, PANELS);
    this.screens.frustumCulled = false;
    this.backs.frustumCulled = false;
    this.root.add(this.screens, this.backs);

    // --- scan rig: the rail the camera rides, a laser ring, laser lines ---
    this.rail = new THREE.Mesh(new THREE.TorusGeometry(HALO_R, 0.05, 6, 64).rotateX(Math.PI / 2), glow);
    this.scanMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(0.4, 2.6, 3.2), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide });
    this.scanRing = new THREE.Mesh(new THREE.RingGeometry(0.62, 0.74, 40).rotateX(-Math.PI / 2), this.scanMat);
    this.laserPos = new THREE.BufferAttribute(new Float32Array(PANELS * 2 * 3), 3);
    this.laserPos.setUsage(THREE.DynamicDrawUsage);
    const laserGeo = new THREE.BufferGeometry();
    laserGeo.setAttribute('position', this.laserPos);
    this.laserMat = new THREE.LineBasicMaterial({ color: new THREE.Color(2.4, 0.4, 1.6), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false });
    this.lasers = new THREE.LineSegments(laserGeo, this.laserMat);
    this.lasers.frustumCulled = false;
    this.root.add(this.rail, this.scanRing, this.lasers);

    scene.add(this.root);
  }

  update(w: World, time: number): void {
    const g = w.t.gate;
    const t = w.gateT;
    const scanning = t >= 0;
    const k = scanning ? w.nextGate - 1 : w.nextGate;
    const ahead = gateS(k, w.t) - w.d;
    this.root.visible = scanning || (ahead < this.visibleAhead && ahead > -10);
    if (!this.root.visible) return;

    const zg = -ahead;
    const px = w.player.x;
    this.frame.position.z = zg;
    // The fold opens as you close in; fully open by the time you're under it.
    const hinge = scanning ? 1 : clamp01((60 - ahead) / 38);
    const leave = scanning ? clamp01((t - (g.duration - EXIT)) / 0.45) : 0;
    const d = this.dummy;

    for (let i = 0; i < PANELS; i++) {
      const col = i % COLS;
      const top = i < COLS;
      const x = (col - (COLS - 1) / 2) * (PW + 0.04);

      // Pose in the frame.
      let angle = 0;
      if (top) {
        this.a.set(x, HINGE_Y + PH / 2, zg + 0.06);
      } else {
        // Folded up behind the top row (angle π), swinging down to hang below it.
        angle = Math.PI * (1 - ease(hinge * 1.5 - col * 0.08));
        this.a.set(x, HINGE_Y - (PH / 2) * Math.cos(angle), zg - 0.06 - (PH / 2) * Math.sin(angle));
      }
      this.qa.setFromEuler(this.foldEuler.set(angle, 0, 0));
      let scale = 1;

      if (scanning) {
        // Pose in the halo, which slowly turns against the camera's orbit.
        const e = clamp01((t - (g.duration - EXIT) - i * 0.02) / 0.45);
        const phi = (i / PANELS) * Math.PI * 2 + Math.PI / PANELS - 0.35 * t + 2.5 * e;
        const r = HALO_R * (1 + 0.6 * e);
        this.b.set(px + Math.sin(phi) * r, HALO_Y + 22 * e * e, Math.cos(phi) * r);
        this.qb.setFromEuler(this.haloEuler.set(HALO_TILT, phi + Math.PI, 0));
        const f = ease((t - i * 0.035) / FLY);
        this.a.lerp(this.b, f);
        this.a.y += 1.6 * Math.sin(Math.PI * f);
        this.qa.slerp(this.qb, f);
        // A barrel roll on the way in, alternating direction per panel.
        this.qs.setFromAxisAngle(this.zAxis, Math.PI * 2 * f * (i % 2 ? 1 : -1));
        this.qa.multiply(this.qs);
        scale = 1 - 0.7 * e;
      }

      d.position.copy(this.a);
      d.quaternion.copy(this.qa);
      d.scale.setScalar(scale);
      d.updateMatrix();
      this.screens.setMatrixAt(i, d.matrix);
      this.backs.setMatrixAt(i, d.matrix);
      if (scanning) {
        this.laserPos.setXYZ(i * 2, this.a.x, this.a.y - 0.4, this.a.z);
      }
    }
    this.screens.instanceMatrix.needsUpdate = true;
    this.backs.instanceMatrix.needsUpdate = true;

    // Scan rig: in once the halo has formed, out as it leaves.
    const rig = scanning ? ease(t / 0.5) * (1 - leave) : 0;
    this.rail.visible = rig > 0.01;
    this.rail.position.set(px, RAIL_Y, 0);
    this.rail.scale.setScalar(Math.max(0.01, rig));
    const beam = scanning ? clamp01((t - FLY) / 0.2) * (1 - clamp01((t - (g.duration - EXIT - 0.2)) / 0.2)) : 0;
    this.scanRing.visible = this.lasers.visible = beam > 0.01;
    if (beam > 0.01) {
      const y = w.player.y + 0.95 - 0.85 * Math.cos((t - FLY) * 4.2);
      this.scanRing.position.set(px, y, 0);
      this.scanMat.opacity = beam;
      this.laserMat.opacity = beam * (0.55 + 0.45 * Math.sin(time * 47));
      for (let i = 0; i < PANELS; i++) this.laserPos.setXYZ(i * 2 + 1, px, y, 0);
      this.laserPos.needsUpdate = true;
    }
  }
}
