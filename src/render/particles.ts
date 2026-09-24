// Cheap juice: one instanced mesh of additive billboards for bursts, one for
// speed lines. Fading is done by darkening the colour (additive blending makes
// black invisible), so no per-instance alpha is needed.
// Particles live in track space: they scroll toward the camera with the run
// (and get bent onto the course with everything else).

import * as THREE from 'three';

const MAX = 384;
const LINES = 40;

interface P {
  x: number;
  y: number;
  z: number;
  vx: number;
  vy: number;
  vz: number;
  life: number;
  max: number;
  size: number;
  gravity: number;
  r: number;
  g: number;
  b: number;
}

interface Line {
  x: number;
  y: number;
  z: number;
  len: number;
}

function softDot(): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const ctx = c.getContext('2d')!;
  const g = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
  g.addColorStop(0, 'rgba(255,255,255,1)');
  g.addColorStop(0.35, 'rgba(255,255,255,0.7)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
}

export class Particles {
  private readonly mesh: THREE.InstancedMesh;
  private readonly lines: THREE.InstancedMesh;
  private readonly ps: P[] = [];
  private readonly ls: Line[] = [];
  private readonly dummy = new THREE.Object3D();
  private readonly color = new THREE.Color();

  constructor(scene: THREE.Scene) {
    const mat = new THREE.MeshBasicMaterial({ map: softDot(), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    this.mesh = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1), mat, MAX);
    this.mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(MAX * 3), 3);
    this.mesh.frustumCulled = false;
    this.mesh.count = 0;
    scene.add(this.mesh);

    const lineMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(1.2, 0.9, 1.8), transparent: true, opacity: 0.35, depthWrite: false, blending: THREE.AdditiveBlending });
    this.lines = new THREE.InstancedMesh(new THREE.PlaneGeometry(0.035, 1, 1, 4).rotateX(-Math.PI / 2), lineMat, LINES);
    this.lines.frustumCulled = false;
    this.lines.count = 0;
    scene.add(this.lines);
  }

  /** Radial burst. `hex` colour is multiplied by `bright` (>1 blooms). */
  burst(x: number, y: number, z: number, n: number, hex: string, opts: { speed?: number; size?: number; life?: number; gravity?: number; bright?: number; up?: number } = {}): void {
    const { speed = 4, size = 0.25, life = 0.5, gravity = 6, bright = 2, up = 1.5 } = opts;
    this.color.set(hex).multiplyScalar(bright);
    for (let i = 0; i < n && this.ps.length < MAX; i++) {
      const a = Math.random() * Math.PI * 2;
      const e = Math.random() * 2 - 1;
      const v = speed * (0.4 + Math.random() * 0.6);
      this.ps.push({
        x,
        y,
        z,
        vx: Math.cos(a) * v * Math.sqrt(1 - e * e),
        vy: e * v * 0.6 + up,
        vz: Math.sin(a) * v * Math.sqrt(1 - e * e),
        life: life * (0.6 + Math.random() * 0.4),
        max: life,
        size: size * (0.6 + Math.random() * 0.8),
        gravity,
        r: this.color.r,
        g: this.color.g,
        b: this.color.b,
      });
    }
  }

  /**
   * @param scroll how far the track moved toward the camera this frame (m)
   * @param speedLines 0..1 intensity of the speed lines
   */
  update(dt: number, scroll: number, camera: THREE.Camera, speedLines: number, runSpeed: number): void {
    const d = this.dummy;
    let n = 0;
    for (let i = this.ps.length - 1; i >= 0; i--) {
      const p = this.ps[i];
      p.life -= dt;
      if (p.life <= 0) {
        this.ps[i] = this.ps[this.ps.length - 1];
        this.ps.pop();
        continue;
      }
      p.vy -= p.gravity * dt;
      p.x += p.vx * dt;
      p.y = Math.max(0.02, p.y + p.vy * dt);
      p.z += p.vz * dt + scroll;
      const k = p.life / p.max;
      d.position.set(p.x, p.y, p.z);
      d.quaternion.copy(camera.quaternion);
      d.scale.setScalar(p.size * (0.4 + 0.6 * k));
      d.updateMatrix();
      this.mesh.setMatrixAt(n, d.matrix);
      this.color.setRGB(p.r * k, p.g * k, p.b * k);
      this.mesh.setColorAt(n++, this.color);
    }
    this.mesh.count = n;
    this.mesh.instanceMatrix.needsUpdate = true;
    if (this.mesh.instanceColor) this.mesh.instanceColor.needsUpdate = true;

    // Speed lines: streaks near the edges of the view, rushing past.
    const want = Math.round(LINES * speedLines);
    while (this.ls.length < want) this.ls.push(this.spawnLine(-60 - Math.random() * 40));
    if (this.ls.length > want) this.ls.length = want;
    let m = 0;
    for (let i = 0; i < this.ls.length; i++) {
      const l = this.ls[i];
      l.z += scroll * 1.8 + runSpeed * 0.6 * dt;
      if (l.z > 8) this.ls[i] = this.spawnLine(-70 - Math.random() * 30);
      const s = this.ls[i];
      d.position.set(s.x, s.y, s.z);
      d.quaternion.identity();
      d.scale.set(1, 1, s.len);
      d.updateMatrix();
      this.lines.setMatrixAt(m++, d.matrix);
    }
    this.lines.count = m;
    this.lines.instanceMatrix.needsUpdate = true;
  }

  private spawnLine(z: number): Line {
    const side = Math.random() < 0.5 ? -1 : 1;
    return { x: side * (3.8 + Math.random() * 2.5), y: 0.3 + Math.random() * 4.5, z, len: 3 + Math.random() * 5 };
  }
}
