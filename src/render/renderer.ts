// Three.js view of the simulation. Reads World state every frame; never
// mutates it. Everything here is grey-box placeholder art built from
// primitives + canvas textures, to be swapped for Blender .glb assets later.

import * as THREE from 'three';
import { laneX, type ObstacleKind, type SimEvent } from '../sim/types';
import type { World } from '../sim/world';
import { Post } from './post';
import { makeAd, makeFeedPost, makeHeart, makeNotification, makeReel, makeReelFront } from './textures';

const VARIANTS = 8;
const TILE_LEN = 4.4;
const TOWER_STEP = 3.6;
const CELL_W = 2.2; // along track
const CELL_H = CELL_W * 2.1;

export interface RenderSettings {
  pixelRatio: number;
}

function hash(a: number, b: number): number {
  let h = Math.imul(a ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul(b + 0x632be5ab, 0xc2b2ae35);
  h ^= h >>> 13;
  h = Math.imul(h, 0x27d4eb2f);
  h ^= h >>> 15;
  return (h >>> 0) / 4294967296;
}

export class GameRenderer {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera: THREE.PerspectiveCamera;
  readonly post: Post;
  settings: RenderSettings;

  private readonly dummy = new THREE.Object3D();
  private readonly tileScreens: THREE.InstancedMesh[] = [];
  private readonly tileBezels: THREE.InstancedMesh;
  private readonly towerCells: THREE.InstancedMesh[] = [];
  private readonly towerBacks: THREE.InstancedMesh;
  private readonly pickupMesh: THREE.InstancedMesh;
  private readonly player = new THREE.Group();
  private readonly playerParts: {
    body: THREE.Mesh;
    head: THREE.Mesh;
    legL: THREE.Object3D;
    legR: THREE.Object3D;
    armL: THREE.Object3D;
    armR: THREE.Object3D;
    rig: THREE.Group;
  };
  private readonly shadow: THREE.Mesh;

  private readonly pools = new Map<ObstacleKind, THREE.Object3D[]>();
  private readonly active = new Map<number, { kind: ObstacleKind; obj: THREE.Object3D }>();
  private readonly obstacleBuilders: Record<ObstacleKind, (variant: number) => THREE.Object3D>;

  private readonly mats: {
    feed: THREE.MeshBasicMaterial[];
    tower: THREE.MeshBasicMaterial[];
    notif: THREE.MeshStandardMaterial[];
    ad: THREE.MeshBasicMaterial[];
    reel: THREE.MeshBasicMaterial[];
    reelFront: THREE.MeshBasicMaterial[];
    dark: THREE.MeshStandardMaterial;
    white: THREE.MeshStandardMaterial;
    pole: THREE.MeshStandardMaterial;
    warn: THREE.MeshBasicMaterial;
  };

  private runPhase = 0;
  private camX = 0;
  private camY = 0;
  private shake = 0;
  private crashT = -1;
  private rollSpin = 0;
  private readonly visibleAhead: number;

  constructor(container: HTMLElement, visibleAhead: number) {
    this.visibleAhead = visibleAhead;
    this.renderer = new THREE.WebGLRenderer({ antialias: false, powerPreference: 'high-performance', stencil: false });
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.appendChild(this.renderer.domElement);
    this.settings = { pixelRatio: Math.min(window.devicePixelRatio || 1, 2) };

    this.camera = new THREE.PerspectiveCamera(66, 1, 0.1, 220);
    this.scene.background = new THREE.Color('#07040f');
    this.scene.fog = new THREE.Fog('#07040f', 45, visibleAhead);

    this.scene.add(new THREE.HemisphereLight('#a58cff', '#150a24', 1.3));
    const sun = new THREE.DirectionalLight('#ffffff', 1.6);
    sun.position.set(4, 10, 6);
    this.scene.add(sun);

    // --- materials ---
    const feedTex = Array.from({ length: VARIANTS }, (_, i) => makeFeedPost(i));
    this.mats = {
      // Ground screens are dimmer than towers and obstacles so hazards pop.
      feed: feedTex.map((t) => new THREE.MeshBasicMaterial({ map: t, color: new THREE.Color(0.55, 0.55, 0.6) })),
      tower: feedTex.map((t) => new THREE.MeshBasicMaterial({ map: t, color: new THREE.Color(0.8, 0.8, 0.85) })),
      notif: Array.from({ length: VARIANTS }, (_, i) => new THREE.MeshStandardMaterial({ map: makeNotification(i), emissiveMap: null, roughness: 0.4, emissive: new THREE.Color('#ffffff'), emissiveIntensity: 0.15 })),
      ad: Array.from({ length: VARIANTS }, (_, i) => new THREE.MeshBasicMaterial({ map: makeAd(i), color: new THREE.Color(1.0, 1.0, 1.0) })),
      reel: Array.from({ length: VARIANTS }, (_, i) => new THREE.MeshBasicMaterial({ map: makeReel(i), color: new THREE.Color(0.8, 0.8, 0.8) })),
      reelFront: Array.from({ length: VARIANTS }, (_, i) => new THREE.MeshBasicMaterial({ map: makeReelFront(i), color: new THREE.Color(0.95, 0.95, 0.95) })),
      dark: new THREE.MeshStandardMaterial({ color: '#15121d', roughness: 0.55, metalness: 0.3 }),
      white: new THREE.MeshStandardMaterial({ color: '#f4f2fa', roughness: 0.35 }),
      pole: new THREE.MeshStandardMaterial({ color: '#2a2535', roughness: 0.5, metalness: 0.6 }),
      warn: new THREE.MeshBasicMaterial({ color: new THREE.Color(3, 0.25, 0.3) }),
    };

    // --- track tiles (the ground is a feed of giant phone screens) ---
    const lanes = 3;
    const tilesPerLane = Math.ceil((visibleAhead + 30) / TILE_LEN) + 2;
    const maxTiles = lanes * tilesPerLane;
    const screenGeo = new THREE.PlaneGeometry(1.92, TILE_LEN - 0.34).rotateX(-Math.PI / 2);
    for (let v = 0; v < VARIANTS; v++) {
      const m = new THREE.InstancedMesh(screenGeo, this.mats.feed[v], maxTiles);
      m.frustumCulled = false;
      this.tileScreens.push(m);
      this.scene.add(m);
    }
    this.tileBezels = new THREE.InstancedMesh(new THREE.BoxGeometry(2.1, 0.16, TILE_LEN - 0.14), this.mats.dark, maxTiles);
    this.tileBezels.frustumCulled = false;
    this.scene.add(this.tileBezels);

    // Floor under everything + glowing lane seams.
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(200, 400).rotateX(-Math.PI / 2), new THREE.MeshStandardMaterial({ color: '#0b0812', roughness: 0.9 }));
    floor.position.set(0, -0.15, -150);
    this.scene.add(floor);
    const seamMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(0.6, 0.25, 1.6) });
    for (const x of [-3.3, -1.1, 1.1, 3.3]) {
      const seam = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.02, 400), seamMat);
      seam.position.set(x, 0.03, -170);
      this.scene.add(seam);
    }

    // --- towers: walls of vertical feeds on both sides ---
    const towerSlots = 2 * (Math.ceil((visibleAhead + 30) / TOWER_STEP) + 2);
    const maxCells = towerSlots * 6;
    const cellGeo = new THREE.PlaneGeometry(CELL_W - 0.25, CELL_H - 0.3);
    for (let v = 0; v < VARIANTS; v++) {
      const m = new THREE.InstancedMesh(cellGeo, this.mats.tower[v], maxCells);
      m.frustumCulled = false;
      this.towerCells.push(m);
      this.scene.add(m);
    }
    this.towerBacks = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), this.mats.dark, towerSlots);
    this.towerBacks.frustumCulled = false;
    this.scene.add(this.towerBacks);

    // --- pickups ---
    const heartMat = new THREE.MeshBasicMaterial({ map: makeHeart(), transparent: true, alphaTest: 0.3, color: new THREE.Color(2.2, 1.2, 1.6), side: THREE.DoubleSide });
    this.pickupMesh = new THREE.InstancedMesh(new THREE.PlaneGeometry(0.85, 0.85), heartMat, 128);
    this.pickupMesh.frustumCulled = false;
    this.scene.add(this.pickupMesh);

    // --- obstacles ---
    this.obstacleBuilders = {
      low: (v) => this.buildLow(v),
      high: (v) => this.buildHigh(v),
      post: (v) => this.buildPost(v, false),
      movingPost: (v) => this.buildPost(v, true),
    };

    // --- player: faceless hoodie lit by their phone ---
    const hoodie = new THREE.MeshStandardMaterial({ color: '#6d6488', roughness: 0.7, emissive: new THREE.Color('#2a2140') });
    const skin = new THREE.MeshStandardMaterial({ color: '#2a2535', roughness: 0.9 });
    const rig = new THREE.Group();
    const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.3, 0.55, 4, 10), hoodie);
    body.position.y = 1.0;
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.25, 14, 10), skin);
    head.position.set(0, 1.58, -0.06);
    const phone = new THREE.Mesh(new THREE.BoxGeometry(0.17, 0.3, 0.02), new THREE.MeshBasicMaterial({ color: new THREE.Color(2.4, 2.8, 3.2) }));
    phone.position.set(0, 1.32, -0.38);
    phone.rotation.x = -0.7;
    const limb = (len: number, r: number): THREE.Object3D => {
      const pivot = new THREE.Group();
      const m = new THREE.Mesh(new THREE.CapsuleGeometry(r, len, 3, 6), hoodie);
      m.position.y = -len / 2 - r;
      pivot.add(m);
      return pivot;
    };
    const legL = limb(0.5, 0.11);
    const legR = limb(0.5, 0.11);
    legL.position.set(-0.14, 0.72, 0);
    legR.position.set(0.14, 0.72, 0);
    const armL = limb(0.34, 0.08);
    const armR = limb(0.34, 0.08);
    armL.position.set(-0.3, 1.3, 0);
    armR.position.set(0.3, 1.3, 0);
    armL.rotation.set(-1.25, 0, -0.35);
    armR.rotation.set(-1.25, 0, 0.35);
    rig.add(body, head, phone, legL, legR, armL, armR);
    this.player.add(rig);
    this.scene.add(this.player);
    this.playerParts = { body, head, legL, legR, armL, armR, rig };

    const shadowTex = (() => {
      const c = document.createElement('canvas');
      c.width = c.height = 64;
      const ctx = c.getContext('2d')!;
      const g = ctx.createRadialGradient(32, 32, 2, 32, 32, 32);
      g.addColorStop(0, 'rgba(0,0,0,0.75)');
      g.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, 64, 64);
      return new THREE.CanvasTexture(c);
    })();
    this.shadow = new THREE.Mesh(new THREE.PlaneGeometry(1.1, 1.1).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ map: shadowTex, transparent: true, depthWrite: false }));
    this.shadow.position.y = 0.04;
    this.scene.add(this.shadow);

    this.post = new Post(this.renderer, this.scene, this.camera);
    this.resize();
    window.addEventListener('resize', () => this.resize());
  }

  // ---------- obstacle builders ----------

  private buildLow(v: number): THREE.Object3D {
    const g = new THREE.Group();
    const side = this.mats.white;
    const face = this.mats.notif[v];
    const pill = new THREE.Mesh(new THREE.BoxGeometry(1.9, 0.62, 0.3), [side, side, side, side, face, side]);
    pill.position.y = 0.52;
    const stand = new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.22, 0.2), this.mats.pole);
    stand.position.y = 0.11;
    g.add(pill, stand);
    return g;
  }

  private buildHigh(v: number): THREE.Object3D {
    const g = new THREE.Group();
    const poleGeo = new THREE.CylinderGeometry(0.06, 0.06, 3.3, 6);
    const p1 = new THREE.Mesh(poleGeo, this.mats.pole);
    const p2 = new THREE.Mesh(poleGeo, this.mats.pole);
    p1.position.set(-1.02, 1.65, 0);
    p2.position.set(1.02, 1.65, 0);
    const ad = this.mats.ad[v];
    const d = this.mats.dark;
    const banner = new THREE.Mesh(new THREE.BoxGeometry(2.0, 1.05, 0.12), [d, d, d, d, ad, ad]);
    banner.position.y = 1.72;
    const top = new THREE.Mesh(new THREE.BoxGeometry(2.1, 0.9, 0.14), d);
    top.position.y = 2.72;
    g.add(p1, p2, banner, top);
    return g;
  }

  private buildPost(v: number, moving: boolean): THREE.Object3D {
    const g = new THREE.Group();
    const side = this.mats.reel[v];
    const front = this.mats.reelFront[v];
    const d = this.mats.dark;
    // Unit length along z; scaled to the obstacle's length on sync.
    const body = new THREE.Mesh(new THREE.BoxGeometry(2.0, 2.8, 1), [side, side, d, d, front, d]);
    body.position.y = 1.4;
    body.name = 'body';
    g.add(body);
    if (moving) {
      const bar = new THREE.Mesh(new THREE.BoxGeometry(1.7, 0.16, 0.08), this.mats.warn);
      bar.name = 'warn';
      bar.position.set(0, 2.95, 0);
      g.add(bar);
    }
    return g;
  }

  private acquire(kind: ObstacleKind, variant: number): THREE.Object3D {
    const pool = this.pools.get(kind) ?? [];
    this.pools.set(kind, pool);
    const idx = pool.findIndex((o) => o.userData.variant === variant);
    const obj = idx >= 0 ? pool.splice(idx, 1)[0] : this.obstacleBuilders[kind](variant);
    obj.userData.variant = variant;
    obj.visible = true;
    if (!obj.parent) this.scene.add(obj);
    return obj;
  }

  private release(kind: ObstacleKind, obj: THREE.Object3D): void {
    obj.visible = false;
    this.pools.get(kind)!.push(obj);
  }

  // ---------- frame ----------

  resize(): void {
    const w = window.innerWidth;
    const h = window.innerHeight;
    this.renderer.setPixelRatio(this.settings.pixelRatio);
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.fov = w / h < 1 ? 70 : 55;
    this.camera.updateProjectionMatrix();
    this.post.setSize(w, h, this.settings.pixelRatio);
  }

  handleEvents(events: SimEvent[]): void {
    for (const e of events) {
      if (e.type === 'stumble') this.shake = Math.max(this.shake, 0.6);
      if (e.type === 'edge') this.shake = Math.max(this.shake, 0.15);
      if (e.type === 'crash') {
        this.shake = 1.2;
        this.crashT = 0;
      }
      if (e.type === 'start') this.crashT = -1;
      if (e.type === 'roll') this.rollSpin = 0;
    }
  }

  render(w: World, dt: number): void {
    const d = w.d;
    const time = performance.now() / 1000;
    this.syncTrack(d);
    this.syncTowers(d);
    this.syncObstacles(w);
    this.syncPickups(w, time);
    this.syncPlayer(w, dt);
    this.syncCamera(w, dt);

    this.post.grade.uniforms.time.value = time;
    this.post.grade.uniforms.shake.value = this.shake;
    this.shake = Math.max(0, this.shake - dt * 2.5);
    this.post.apply();
    this.post.render(dt);
  }

  private syncTrack(d: number): void {
    const first = Math.floor((d - 12) / TILE_LEN);
    const last = Math.floor((d + this.visibleAhead) / TILE_LEN);
    const counts = new Array(VARIANTS).fill(0);
    let bezels = 0;
    for (let i = first; i <= last; i++) {
      const z = -(i * TILE_LEN + TILE_LEN / 2 - d);
      for (let lane = 0; lane < 3; lane++) {
        const x = laneX(lane);
        const v = Math.floor(hash(i, lane) * VARIANTS);
        this.dummy.position.set(x, 0.011, z);
        this.dummy.rotation.set(0, 0, 0);
        this.dummy.scale.set(1, 1, 1);
        this.dummy.updateMatrix();
        this.tileScreens[v].setMatrixAt(counts[v]++, this.dummy.matrix);
        this.dummy.position.y = -0.07;
        this.dummy.updateMatrix();
        this.tileBezels.setMatrixAt(bezels++, this.dummy.matrix);
      }
    }
    this.tileScreens.forEach((m, v) => {
      m.count = counts[v];
      m.instanceMatrix.needsUpdate = true;
    });
    this.tileBezels.count = bezels;
    this.tileBezels.instanceMatrix.needsUpdate = true;
  }

  private syncTowers(d: number): void {
    const first = Math.floor((d - 12) / TOWER_STEP);
    const last = Math.floor((d + this.visibleAhead) / TOWER_STEP);
    const counts = new Array(VARIANTS).fill(0);
    let backs = 0;
    for (let i = first; i <= last; i++) {
      for (const side of [-1, 1]) {
        const r = hash(i, side + 7);
        if (r < 0.12) continue; // gaps in the skyline
        const cells = 1 + Math.floor(hash(i, side + 11) * 5);
        const xFace = side * (4.6 + hash(i, side + 13) * 2.2);
        const z = -(i * TOWER_STEP - d);
        const depth = 1.2;
        const height = cells * CELL_H;
        this.dummy.rotation.set(0, 0, 0);
        this.dummy.position.set(xFace + side * (depth / 2 + 0.02), height / 2, z);
        this.dummy.scale.set(depth, height, CELL_W);
        this.dummy.updateMatrix();
        this.towerBacks.setMatrixAt(backs++, this.dummy.matrix);
        this.dummy.scale.set(1, 1, 1);
        this.dummy.rotation.set(0, side < 0 ? Math.PI / 2 : -Math.PI / 2, 0);
        for (let c = 0; c < cells; c++) {
          const v = Math.floor(hash(i * 13 + c, side) * VARIANTS);
          this.dummy.position.set(xFace, c * CELL_H + CELL_H / 2, z);
          this.dummy.updateMatrix();
          this.towerCells[v].setMatrixAt(counts[v]++, this.dummy.matrix);
        }
      }
    }
    this.towerCells.forEach((m, v) => {
      m.count = counts[v];
      m.instanceMatrix.needsUpdate = true;
    });
    this.towerBacks.count = backs;
    this.towerBacks.instanceMatrix.needsUpdate = true;
  }

  private syncObstacles(w: World): void {
    const seen = new Set<number>();
    for (const o of w.obstacles) {
      if (o.s - w.d > this.visibleAhead) continue;
      seen.add(o.id);
      let entry = this.active.get(o.id);
      if (!entry) {
        entry = { kind: o.kind, obj: this.acquire(o.kind, o.variant) };
        this.active.set(o.id, entry);
      }
      const obj = entry.obj;
      const x = laneX(o.lane);
      if (o.kind === 'post' || o.kind === 'movingPost') {
        const body = obj.getObjectByName('body')!;
        body.scale.z = o.length;
        obj.position.set(x, 0, -(o.s + o.length / 2 - w.d));
        const warn = obj.getObjectByName('warn');
        if (warn) {
          warn.position.z = o.length / 2 - 0.1;
          warn.visible = !o.active || Math.floor(performance.now() / 120) % 2 === 0;
        }
      } else {
        obj.position.set(x, 0, -(o.s - w.d));
      }
    }
    for (const [id, entry] of this.active) {
      if (!seen.has(id)) {
        this.release(entry.kind, entry.obj);
        this.active.delete(id);
      }
    }
  }

  private syncPickups(w: World, time: number): void {
    let n = 0;
    for (const p of w.pickups) {
      if (p.taken || p.s - w.d > this.visibleAhead || n >= 128) continue;
      this.dummy.position.set(laneX(p.lane), p.y + Math.sin(time * 4 + p.s) * 0.08, -(p.s - w.d));
      this.dummy.rotation.set(0, time * 2.5 + p.s * 0.3, 0);
      this.dummy.scale.set(1, 1, 1);
      this.dummy.updateMatrix();
      this.pickupMesh.setMatrixAt(n++, this.dummy.matrix);
    }
    this.pickupMesh.count = n;
    this.pickupMesh.instanceMatrix.needsUpdate = true;
  }

  private syncPlayer(w: World, dt: number): void {
    const p = w.player;
    const parts = this.playerParts;
    this.player.position.set(p.x, p.y, 0);
    this.shadow.position.x = p.x;
    const sh = Math.max(0.35, 1 - p.y * 0.25);
    this.shadow.scale.set(sh, 1, sh);

    const targetX = laneX(p.lane);
    this.player.rotation.z = THREE.MathUtils.lerp(this.player.rotation.z, (p.x - targetX) * 0.18, 0.3);

    if (w.phase === 'dead') {
      // Faceplant.
      if (this.crashT >= 0) this.crashT += dt;
      const k = Math.min(1, Math.max(0, this.crashT) * 3);
      parts.rig.rotation.x = -k * 1.35;
      parts.rig.position.y = -k * 0.25;
      return;
    }
    parts.rig.position.y = 0;
    parts.rig.rotation.x = 0;

    const rolling = p.rollT > 0;
    if (w.phase === 'running') this.runPhase += dt * (6 + w.speed * 0.32);
    const s = Math.sin(this.runPhase);
    if (rolling) {
      this.rollSpin += dt * 14;
      parts.rig.scale.set(1.05, 0.5, 1.05);
      parts.rig.rotation.x = -0.5;
      parts.legL.rotation.x = -1.6;
      parts.legR.rotation.x = -1.6;
    } else if (!p.grounded) {
      parts.rig.scale.set(1, 1, 1);
      parts.legL.rotation.x = -0.9;
      parts.legR.rotation.x = 0.4;
    } else {
      parts.rig.scale.set(1, 1, 1);
      const amp = w.phase === 'running' ? 0.85 : 0.08;
      parts.legL.rotation.x = s * amp;
      parts.legR.rotation.x = -s * amp;
      parts.body.position.y = 1.0 + Math.abs(Math.cos(this.runPhase)) * 0.06;
    }
    parts.head.position.y = parts.body.position.y + 0.58;
  }

  private syncCamera(w: World, dt: number): void {
    const p = w.player;
    const k = 1 - Math.pow(0.0008, dt);
    this.camX = THREE.MathUtils.lerp(this.camX, p.x * 0.65, k);
    this.camY = THREE.MathUtils.lerp(this.camY, p.y * 0.35, 1 - Math.pow(0.02, dt));
    const shake = this.shake * this.shake;
    const jx = (Math.random() - 0.5) * shake * 0.5;
    const jy = (Math.random() - 0.5) * shake * 0.5;
    this.camera.position.set(this.camX + jx, 3.5 + this.camY + jy, 6.4);
    this.camera.lookAt(this.camX * 1.1, 1.1 + this.camY * 0.5, -9);
  }

  stats(): { calls: number; tris: number } {
    return { calls: this.renderer.info.render.calls, tris: this.renderer.info.render.triangles };
  }
}
