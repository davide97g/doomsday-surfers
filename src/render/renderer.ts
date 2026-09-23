// Three.js view of the simulation. Reads World state every frame; never
// mutates it. Everything here is grey-box placeholder art built from
// primitives + canvas textures, to be swapped for Blender .glb assets later.

import * as THREE from 'three';
import { laneX, type ObstacleKind, type SimEvent } from '../sim/types';
import type { World } from '../sim/world';
import { Hero } from './hero';
import { Particles } from './particles';
import { Post } from './post';
import { FEED_ATLAS, makeAd, makeBookCover, makeContent, makeFeedAtlas, makeMumCall, makeNotification, makeReel, makeReelFront } from './textures';

const VARIANTS = 8;
const CONTENT_COLOURS = ['#ff2e63', '#ff2e3b', '#00e1ff', '#ff7a1f']; // like, notification, reel, outrage
const FEED_CELLS = FEED_ATLAS.cols * FEED_ATLAS.rows;
const TILE_LEN = 4.4;
const TOWER_STEP = 3.6;
const CELL_W = 2.2; // along track
const CELL_H = CELL_W * 2.1;

export interface RenderSettings {
  pixelRatio: number;
}

/** Basic material that samples one atlas cell per instance (the `cell` attribute). */
function atlasMaterial(map: THREE.Texture, color: THREE.Color): THREE.MeshBasicMaterial {
  const { cols, rows } = FEED_ATLAS;
  const m = new THREE.MeshBasicMaterial({ map, color });
  m.onBeforeCompile = (sh) => {
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nattribute float cell;')
      .replace(
        '#include <uv_vertex>',
        `#include <uv_vertex>
        vMapUv = (vMapUv + vec2(mod(cell, ${cols}.0), ${rows - 1}.0 - floor(cell / ${cols}.0))) / vec2(${cols}.0, ${rows}.0);`,
      );
  };
  return m;
}

function cellAttribute(geo: THREE.BufferGeometry, count: number): THREE.InstancedBufferAttribute {
  const attr = new THREE.InstancedBufferAttribute(new Float32Array(count), 1);
  attr.setUsage(THREE.DynamicDrawUsage);
  geo.setAttribute('cell', attr);
  return attr;
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
  private readonly particles: Particles;
  /** Blender hero runner; the grey-box rig stands in until it has loaded. */
  private hero: Hero | null = null;
  settings: RenderSettings;

  private readonly dummy = new THREE.Object3D();
  private readonly tileScreens: THREE.InstancedMesh;
  private readonly tileCells: THREE.InstancedBufferAttribute;
  private readonly tileBezels: THREE.InstancedMesh;
  private readonly towerCells: THREE.InstancedMesh;
  private readonly towerCellIds: THREE.InstancedBufferAttribute;
  private readonly towerBacks: THREE.InstancedMesh;
  private readonly pickupMeshes: THREE.InstancedMesh[] = [];
  private readonly phoneMat: THREE.MeshBasicMaterial;
  private readonly player = new THREE.Group();
  private readonly playerParts: {
    body: THREE.Mesh;
    head: THREE.Mesh;
    legL: THREE.Object3D;
    legR: THREE.Object3D;
    armL: THREE.Object3D;
    armR: THREE.Object3D;
    phone: THREE.Mesh;
    rig: THREE.Group;
  };
  private readonly shadow: THREE.Mesh;

  private readonly pools = new Map<ObstacleKind, THREE.Object3D[]>();
  private readonly active = new Map<number, { kind: ObstacleKind; obj: THREE.Object3D }>();
  private readonly obstacleBuilders: Record<ObstacleKind, (variant: number) => THREE.Object3D>;

  private readonly mats: {
    feed: THREE.MeshBasicMaterial;
    tower: THREE.MeshBasicMaterial;
    notif: THREE.MeshStandardMaterial[];
    ad: THREE.MeshBasicMaterial[];
    reel: THREE.MeshBasicMaterial[];
    reelFront: THREE.MeshBasicMaterial[];
    dark: THREE.MeshStandardMaterial;
    white: THREE.MeshStandardMaterial;
    pole: THREE.MeshStandardMaterial;
    warn: THREE.MeshBasicMaterial;
  };
  // Healthy habits: matte, warm, un-neon. They should look boring.
  private readonly habitMats: {
    glass: THREE.MeshStandardMaterial;
    water: THREE.MeshStandardMaterial;
    books: THREE.MeshStandardMaterial[];
    cover: THREE.MeshStandardMaterial;
    sole: THREE.MeshStandardMaterial;
    upper: THREE.MeshStandardMaterial;
    call: THREE.MeshStandardMaterial;
  };

  private runPhase = 0;
  private camX = 0;
  private camY = 0;
  private shake = 0;
  private crashT = -1;
  private rollSpin = 0;
  /** Smoothed dopamine level driving the colour grade (1 = neon, 0 = grey). */
  private level = 1;
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
    const feedAtlas = makeFeedAtlas();
    this.mats = {
      // Ground screens are dimmer than towers and obstacles so hazards pop.
      feed: atlasMaterial(feedAtlas, new THREE.Color(0.55, 0.55, 0.6)),
      tower: atlasMaterial(feedAtlas, new THREE.Color(0.8, 0.8, 0.85)),
      notif: Array.from({ length: VARIANTS }, (_, i) => new THREE.MeshStandardMaterial({ map: makeNotification(i), emissiveMap: null, roughness: 0.4, emissive: new THREE.Color('#ffffff'), emissiveIntensity: 0.15 })),
      ad: Array.from({ length: VARIANTS }, (_, i) => new THREE.MeshBasicMaterial({ map: makeAd(i), color: new THREE.Color(1.0, 1.0, 1.0) })),
      reel: Array.from({ length: VARIANTS }, (_, i) => new THREE.MeshBasicMaterial({ map: makeReel(i), color: new THREE.Color(0.8, 0.8, 0.8) })),
      reelFront: Array.from({ length: VARIANTS }, (_, i) => new THREE.MeshBasicMaterial({ map: makeReelFront(i), color: new THREE.Color(0.95, 0.95, 0.95) })),
      dark: new THREE.MeshStandardMaterial({ color: '#15121d', roughness: 0.55, metalness: 0.3 }),
      white: new THREE.MeshStandardMaterial({ color: '#f4f2fa', roughness: 0.35 }),
      pole: new THREE.MeshStandardMaterial({ color: '#2a2535', roughness: 0.5, metalness: 0.6 }),
      warn: new THREE.MeshBasicMaterial({ color: new THREE.Color(3, 0.25, 0.3) }),
    };
    const matte = (color: string, extra: THREE.MeshStandardMaterialParameters = {}) =>
      new THREE.MeshStandardMaterial({ color, roughness: 0.85, emissive: new THREE.Color(color), emissiveIntensity: 0.22, ...extra });
    this.habitMats = {
      glass: matte('#cfe6ee', { transparent: true, opacity: 0.35, depthWrite: false, side: THREE.DoubleSide }),
      water: matte('#6fb4d2', { transparent: true, opacity: 0.8 }),
      books: [matte('#7d5a44'), matte('#4f6b58'), matte('#8a7a5c')],
      cover: new THREE.MeshStandardMaterial({ map: makeBookCover(), roughness: 0.9, emissive: new THREE.Color('#6b4a36'), emissiveIntensity: 0.25 }),
      sole: matte('#e6e1d6'),
      upper: matte('#5f8a74'),
      call: new THREE.MeshStandardMaterial({ map: makeMumCall(), roughness: 0.6, emissive: new THREE.Color('#ffffff'), emissiveMap: null, emissiveIntensity: 0.12 }),
    };

    // --- track tiles (the ground is a feed of giant phone screens) ---
    const lanes = 3;
    const tilesPerLane = Math.ceil((visibleAhead + 30) / TILE_LEN) + 2;
    const maxTiles = lanes * tilesPerLane;
    const screenGeo = new THREE.PlaneGeometry(1.92, TILE_LEN - 0.34).rotateX(-Math.PI / 2);
    this.tileCells = cellAttribute(screenGeo, maxTiles);
    this.tileScreens = new THREE.InstancedMesh(screenGeo, this.mats.feed, maxTiles);
    this.tileScreens.frustumCulled = false;
    this.scene.add(this.tileScreens);
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
    this.towerCellIds = cellAttribute(cellGeo, maxCells);
    this.towerCells = new THREE.InstancedMesh(cellGeo, this.mats.tower, maxCells);
    this.towerCells.frustumCulled = false;
    this.scene.add(this.towerCells);
    this.towerBacks = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), this.mats.dark, towerSlots);
    this.towerBacks.frustumCulled = false;
    this.scene.add(this.towerBacks);

    // --- pickups: one instanced mesh per content type; brightness follows tolerance ---
    const pickupGeo = new THREE.PlaneGeometry(0.85, 0.85);
    for (let type = 0; type < 4; type++) {
      const mat = new THREE.MeshBasicMaterial({ map: makeContent(type), transparent: true, alphaTest: 0.3, side: THREE.DoubleSide });
      const m = new THREE.InstancedMesh(pickupGeo, mat, 128);
      m.frustumCulled = false;
      this.pickupMeshes.push(m);
      this.scene.add(m);
    }

    // --- obstacles ---
    this.obstacleBuilders = {
      low: (v) => this.buildLow(v),
      high: (v) => this.buildHigh(v),
      post: (v) => this.buildPost(v, false),
      movingPost: (v) => this.buildPost(v, true),
      habit: (v) => this.buildHabit(v),
    };

    // --- player: faceless hoodie lit by their phone ---
    const hoodie = new THREE.MeshStandardMaterial({ color: '#6d6488', roughness: 0.7, emissive: new THREE.Color('#2a2140') });
    const skin = new THREE.MeshStandardMaterial({ color: '#2a2535', roughness: 0.9 });
    const rig = new THREE.Group();
    const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.3, 0.55, 4, 10), hoodie);
    body.position.y = 1.0;
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.25, 14, 10), skin);
    head.position.set(0, 1.58, -0.06);
    this.phoneMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(2.4, 2.8, 3.2) });
    const phone = new THREE.Mesh(new THREE.BoxGeometry(0.17, 0.3, 0.02), this.phoneMat);
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
    this.playerParts = { body, head, legL, legR, armL, armR, phone, rig };

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

    this.particles = new Particles(this.scene);
    Hero.load(`${import.meta.env.BASE_URL}assets/runner.glb`)
      .then((hero) => {
        this.hero = hero;
        this.player.remove(this.playerParts.rig);
        this.player.add(hero.root);
      })
      .catch((err) => console.warn('runner.glb failed to load, keeping grey box', err));
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

  private buildHabit(v: number): THREE.Object3D {
    const g = new THREE.Group();
    const m = this.habitMats;
    switch (v % 4) {
      case 0: {
        // A giant glass of water.
        const glass = new THREE.Mesh(new THREE.CylinderGeometry(0.44, 0.36, 1.0, 18, 1, true), m.glass);
        glass.position.y = 0.5;
        const water = new THREE.Mesh(new THREE.CylinderGeometry(0.4, 0.35, 0.7, 18), m.water);
        water.position.y = 0.37;
        g.add(water, glass);
        break;
      }
      case 1: {
        // A stack of books.
        const geo = new THREE.BoxGeometry(1.1, 0.3, 0.8);
        const rot = [0.1, -0.08, 0.16];
        for (let i = 0; i < 3; i++) {
          const b = m.books[i];
          const mats = i === 2 ? [b, b, m.cover, b, b, b] : b;
          const book = new THREE.Mesh(geo, mats);
          book.position.y = 0.15 + i * 0.3;
          book.rotation.y = rot[i];
          g.add(book);
        }
        break;
      }
      case 2: {
        // A running shoe, side on.
        const sole = new THREE.Mesh(new THREE.BoxGeometry(1.15, 0.16, 0.46), m.sole);
        sole.position.y = 0.08;
        const upper = new THREE.Mesh(new THREE.BoxGeometry(0.66, 0.5, 0.42), m.upper);
        upper.position.set(-0.2, 0.41, 0);
        const toe = new THREE.Mesh(new THREE.BoxGeometry(0.46, 0.26, 0.42), m.upper);
        toe.position.set(0.33, 0.29, 0);
        const laces = new THREE.Mesh(new THREE.BoxGeometry(0.36, 0.05, 0.3), m.sole);
        laces.position.set(0.05, 0.45, 0);
        laces.rotation.z = -0.35;
        g.add(sole, upper, toe, laces);
        g.scale.setScalar(1.15);
        break;
      }
      default: {
        // Mum is calling. The phone stands up and rings.
        const d = this.mats.dark;
        const phone = new THREE.Mesh(new THREE.BoxGeometry(0.62, 1.0, 0.08), [d, d, d, d, m.call, d]);
        phone.position.y = 0.5;
        phone.name = 'ring';
        g.add(phone);
      }
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

  handleEvents(events: SimEvent[], w: World): void {
    const p = w.player;
    const fx = this.particles;
    for (const e of events) {
      if (e.type === 'pickup') {
        const t = e.tolerance;
        fx.burst(p.x, p.y + 0.9, -0.4, Math.round(3 + 9 * t), CONTENT_COLOURS[e.content], { size: 0.18 + 0.2 * t, bright: 0.8 + 1.8 * t });
      }
      if (e.type === 'habit') fx.burst(p.x, 0.5, -0.6, 14, '#8a8a8a', { speed: 2.5, size: 0.5, life: 0.8, gravity: 0.5, bright: 0.5, up: 0.8 });
      if (e.type === 'crash') fx.burst(p.x, 1.2, -0.7, 44, '#bfe9ff', { speed: 7, size: 0.16, life: 1, gravity: 14, bright: 2.2, up: 3 });
      if (e.type === 'revive') fx.burst(p.x, 1, 0, 36, '#ff2e88', { speed: 5, size: 0.3, life: 0.8, gravity: 2, bright: 2.5, up: 2 });
      if (e.type === 'stumble') this.shake = Math.max(this.shake, 0.6);
      if (e.type === 'edge') this.shake = Math.max(this.shake, 0.15);
      if (e.type === 'crash') {
        this.shake = 1.2;
        this.crashT = 0;
      }
      if (e.type === 'start' || e.type === 'revive') this.crashT = -1;
      if (e.type === 'roll') this.rollSpin = 0;
    }
  }

  render(w: World, dt: number): void {
    const d = w.d;
    const time = performance.now() / 1000;
    const target = Math.min(1, Math.max(0, w.dopamine / w.t.dopamine.fullColourAt));
    this.level += (target - this.level) * (1 - Math.exp(-dt * 3));
    this.syncTrack(d);
    this.syncTowers(d);
    this.syncObstacles(w);
    this.syncPickups(w, time);
    this.syncPlayer(w, dt);
    this.syncCamera(w, dt);

    const lines = w.phase === 'running' ? Math.min(1, Math.max(0, (this.level - 0.6) / 0.4)) * Math.min(1, 0.3 + (w.speed - w.t.speed.start) / 10) : 0;
    this.particles.update(dt, w.runSpeed * dt, this.camera, lines, w.runSpeed);
    this.post.grade.uniforms.dopamine.value = this.level;
    this.post.bloom.strength = 0.6 * (0.2 + 0.8 * this.level);
    this.post.grade.uniforms.time.value = time;
    this.post.grade.uniforms.shake.value = this.shake;
    this.shake = Math.max(0, this.shake - dt * 2.5);
    this.post.apply();
    this.post.render(dt);
  }

  private syncTrack(d: number): void {
    const first = Math.floor((d - 12) / TILE_LEN);
    const last = Math.floor((d + this.visibleAhead) / TILE_LEN);
    let n = 0;
    for (let i = first; i <= last; i++) {
      const z = -(i * TILE_LEN + TILE_LEN / 2 - d);
      for (let lane = 0; lane < 3; lane++) {
        const x = laneX(lane);
        this.dummy.position.set(x, 0.011, z);
        this.dummy.rotation.set(0, 0, 0);
        this.dummy.scale.set(1, 1, 1);
        this.dummy.updateMatrix();
        this.tileScreens.setMatrixAt(n, this.dummy.matrix);
        this.tileCells.setX(n, Math.floor(hash(i, lane) * FEED_CELLS));
        this.dummy.position.y = -0.07;
        this.dummy.updateMatrix();
        this.tileBezels.setMatrixAt(n++, this.dummy.matrix);
      }
    }
    this.tileScreens.count = n;
    this.tileScreens.instanceMatrix.needsUpdate = true;
    this.tileCells.needsUpdate = true;
    this.tileBezels.count = n;
    this.tileBezels.instanceMatrix.needsUpdate = true;
  }

  private syncTowers(d: number): void {
    const first = Math.floor((d - 12) / TOWER_STEP);
    const last = Math.floor((d + this.visibleAhead) / TOWER_STEP);
    let n = 0;
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
          this.dummy.position.set(xFace, c * CELL_H + CELL_H / 2, z);
          this.dummy.updateMatrix();
          this.towerCells.setMatrixAt(n, this.dummy.matrix);
          this.towerCellIds.setX(n++, Math.floor(hash(i * 13 + c, side) * FEED_CELLS));
        }
      }
    }
    this.towerCells.count = n;
    this.towerCells.instanceMatrix.needsUpdate = true;
    this.towerCellIds.needsUpdate = true;
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
      } else if (o.kind === 'habit') {
        obj.visible = !o.hit;
        obj.position.set(x, 0, -(o.s - w.d));
        const ring = obj.getObjectByName('ring');
        if (ring) {
          const t = performance.now() / 1000;
          ring.rotation.z = Math.floor(t * 1.6) % 2 === 0 ? Math.sin(t * 55) * 0.07 : 0;
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
    const counts = [0, 0, 0, 0];
    for (const p of w.pickups) {
      if (p.taken || p.s - w.d > this.visibleAhead || counts[p.type] >= 128) continue;
      this.dummy.position.set(laneX(p.lane), p.y + Math.sin(time * 4 + p.s) * 0.08, -(p.s - w.d));
      this.dummy.rotation.set(0, time * 2.5 + p.s * 0.3, 0);
      this.dummy.scale.set(1, 1, 1);
      this.dummy.updateMatrix();
      this.pickupMeshes[p.type].setMatrixAt(counts[p.type]++, this.dummy.matrix);
    }
    this.pickupMeshes.forEach((m, type) => {
      m.count = counts[type];
      m.instanceMatrix.needsUpdate = true;
      // Tolerance made visible: content you've had too much of stops glowing.
      (m.material as THREE.MeshBasicMaterial).color.setScalar(0.45 + 1.35 * w.tolerance[type]);
    });
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

    if (this.hero) {
      const root = this.hero.root;
      if (w.cause === 'crash') {
        if (this.crashT >= 0) this.crashT += dt;
        const k = Math.min(1, Math.max(0, this.crashT) * 3);
        root.rotation.x = -k * 1.35;
        root.position.y = -k * 0.25;
      } else {
        root.rotation.x = 0;
        root.position.y = 0;
      }
      this.hero.update(w, dt);
      return;
    }

    // Dopamine ran out: the arms drop, the phone goes dark.
    const present = w.cause === 'empty' ? Math.min(1, w.fadeT / w.t.reality.fadeTime) : 0;
    this.phoneMat.color.setRGB(2.4, 2.8, 3.2).multiplyScalar(1 - 0.97 * present);
    parts.armL.rotation.x = parts.armR.rotation.x = THREE.MathUtils.lerp(-1.25, -0.12, present);
    parts.phone.position.set(0, THREE.MathUtils.lerp(1.32, 0.78, present), THREE.MathUtils.lerp(-0.38, -0.3, present));
    parts.phone.rotation.x = THREE.MathUtils.lerp(-0.7, 0, present);

    if (w.cause === 'crash') {
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
    const v = w.runSpeed;
    const moving = Math.min(1, v / 6);
    this.runPhase += dt * (6 + v * 0.32) * moving;
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
      const amp = w.phase === 'ready' ? 0.08 : 0.85 * moving;
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
