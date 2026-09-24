// Three.js view of the simulation. Reads World state every frame; never
// mutates it. Everything here is grey-box placeholder art built from
// primitives + canvas textures, to be swapped for Blender .glb assets later.
//
// Everything is laid out on a straight track (x lateral, y up, z = -(s - d))
// and bent onto the rollercoaster course by the vertex shader (see Bend).
// Long things are subdivided along z so they follow curves and loops. The
// runner stays unbent at the origin (the bend is identity there); the sky
// dome keeps the world's real orientation, so the horizon flips in a loop.

import * as THREE from 'three';
import content from '../config/content.json';
import { TUNING, laneX, zoneLook, type ObstacleKind, type PadKind, type SimEvent } from '../sim/types';
import type { World } from '../sim/world';
import { atlasMaterial, cellAttribute, hash } from './atlas';
import { Bend } from './bend';
import { Gate } from './gate';
import { Hero } from './hero';
import { Particles } from './particles';
import { Post } from './post';
import { FEED_ATLAS, makeAd, makeAutoplay, makeBookCover, makeBouncerTop, makeContent, makeFeedAtlas, makeMumCall, makeNotification, makeRampFace, makeReel, makeReelFront } from './textures';

const VARIANTS = 8;
const CONTENT_COLOURS = ['#ff2e63', '#ff2e3b', '#00e1ff', '#ff7a1f']; // like, notification, reel, outrage
const FEED_CELLS = FEED_ATLAS.cols * FEED_ATLAS.rows;
const TILE_LEN = 4.4;
const TOWER_STEP = 3.6;
const CELL_W = 2.2; // along track
const CELL_H = CELL_W * 2.1;
/** Track kept behind the runner: a little normally, more while the gate camera looks back. */
const BEHIND = 12;
const BEHIND_ORBIT = 45;
/** Length segments per track tile, so tiles bend round loops instead of kinking. */
const TILE_SEGS = 4;
/** Glowing "loading spinner" dashes lining each side of a loop or corkscrew. */
const SPINNER_DASHES = 18;
const SPINNER_X = 4.1;
const PAD_COLOURS: Record<PadKind, string> = { ramp: '#ff2e88', bouncer: '#00e1ff', autoplay: '#ffcc00' };

/** Seconds for the title turntable to swing round into the chase view. */
const INTRO = 0.9;

// Each doomscroller's Blender model (public/assets/characters/<model>.glb,
// built by `npm run assets`) and display scale. The hitbox doesn't change.
const CHARACTER_LOOKS: { model: string; scale: number }[] = [
  { model: 'goblin', scale: 1 },
  { model: 'bro', scale: 1 },
  { model: 'kid', scale: 0.72 },
  { model: 'uncle', scale: 1 },
  { model: 'influencer', scale: 0.97 },
  { model: 'wellness', scale: 0.95 },
  { model: 'doomer', scale: 1.02 },
];

interface ZoneLook {
  seam: THREE.Color;
  sky: THREE.Color;
  light: THREE.Color;
}
const ZONES: ZoneLook[] = content.zones.map((z) => ({
  seam: new THREE.Color(z.seam[0], z.seam[1], z.seam[2]),
  sky: new THREE.Color(z.sky),
  light: new THREE.Color(z.light),
}));

export interface RenderSettings {
  pixelRatio: number;
}

export class GameRenderer {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera: THREE.PerspectiveCamera;
  readonly post: Post;
  private readonly particles: Particles;
  /** The shown doomscroller; the grey-box rig stands in until it has loaded. */
  private hero: Hero | null = null;
  private readonly heroes = new Map<string, Promise<Hero | null>>();
  settings: RenderSettings;

  private readonly dummy = new THREE.Object3D();
  private readonly tileScreens: THREE.InstancedMesh;
  private readonly tileCells: THREE.InstancedBufferAttribute;
  private readonly tileBezels: THREE.InstancedMesh;
  private readonly towerCells: THREE.InstancedMesh;
  private readonly towerCellIds: THREE.InstancedBufferAttribute;
  private readonly towerBacks: THREE.InstancedMesh;
  private readonly deck: THREE.InstancedMesh;
  private readonly seams: THREE.InstancedMesh;
  private readonly spinner: THREE.InstancedMesh;
  private readonly sky: THREE.Mesh;
  private readonly skyUniforms: { top: THREE.IUniform<THREE.Color>; horizon: THREE.IUniform<THREE.Color>; bottom: THREE.IUniform<THREE.Color>; glow: THREE.IUniform<THREE.Color> };
  readonly bend = new Bend();
  private readonly padPools = new Map<PadKind, THREE.Object3D[]>();
  private readonly padActive = new Map<number, { kind: PadKind; obj: THREE.Object3D; t: number }>();
  private readonly autoplayTex: THREE.Texture;
  private readonly camUp = new THREE.Vector3(0, 1, 0);
  private readonly upV = new THREE.Vector3();
  private readonly colour = new THREE.Color();
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
  private readonly gate: Gate;
  private readonly seamMat: THREE.MeshBasicMaterial;
  private readonly hemi: THREE.HemisphereLight;
  private readonly skyColour = new THREE.Color();
  private readonly tmpV = new THREE.Vector3();
  private readonly lookV = new THREE.Vector3();
  private readonly tmpP = new THREE.Vector3();
  private readonly tmpQ = new THREE.Quaternion();

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
  private readonly padMats: {
    ramp: THREE.MeshBasicMaterial;
    bouncer: THREE.MeshBasicMaterial;
    autoplay: THREE.MeshBasicMaterial;
    glow: Record<PadKind, THREE.MeshBasicMaterial>;
  };
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
  /** Portrait/landscape field of view before the gate camera's zoom. */
  private baseFov = 70;
  private character = 0;
  /** Title turntable angle (radians round the runner, 0 = chase view). */
  private turn = Math.PI;
  /** Seconds into the swing from turntable to chase view; -1 when not swinging. */
  private introT = -1;
  private introFrom = 0;
  /** Seconds since the last gate crossing, for the camera's zoom kick. */
  private gateKick = 99;
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

    this.hemi = new THREE.HemisphereLight('#a58cff', '#150a24', 1.3);
    this.scene.add(this.hemi);
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
    const tilesPerLane = Math.ceil((visibleAhead + BEHIND_ORBIT + 20) / TILE_LEN) + 2;
    const maxTiles = lanes * tilesPerLane;
    const screenGeo = new THREE.PlaneGeometry(1.92, TILE_LEN - 0.34, 1, TILE_SEGS).rotateX(-Math.PI / 2);
    this.tileCells = cellAttribute(screenGeo, maxTiles);
    this.tileScreens = new THREE.InstancedMesh(screenGeo, this.mats.feed, maxTiles);
    this.tileScreens.frustumCulled = false;
    this.scene.add(this.tileScreens);
    this.tileBezels = new THREE.InstancedMesh(new THREE.BoxGeometry(2.1, 0.16, TILE_LEN - 0.14, 1, 1, TILE_SEGS), this.mats.dark, maxTiles);
    this.tileBezels.frustumCulled = false;
    this.scene.add(this.tileBezels);

    // A dark deck under the lanes (the track is a ribbon in the air now) and glowing lane seams.
    const rows = tilesPerLane;
    this.deck = new THREE.InstancedMesh(new THREE.BoxGeometry(9.6, 0.3, TILE_LEN, 1, 1, TILE_SEGS), new THREE.MeshStandardMaterial({ color: '#0b0812', roughness: 0.9 }), rows);
    this.deck.frustumCulled = false;
    this.scene.add(this.deck);
    this.seamMat = new THREE.MeshBasicMaterial({ color: ZONES[0].seam.clone() });
    this.seams = new THREE.InstancedMesh(new THREE.BoxGeometry(0.05, 0.02, TILE_LEN, 1, 1, TILE_SEGS), this.seamMat, rows * 4);
    this.seams.frustumCulled = false;
    this.scene.add(this.seams);

    // Loop and corkscrew dashes: a pull-to-refresh spinner you ride through.
    this.spinner = new THREE.InstancedMesh(new THREE.BoxGeometry(0.3, 0.3, 1, 1, 1, 3), new THREE.MeshBasicMaterial({ color: '#ffffff' }), SPINNER_DASHES * 2 * 6);
    this.spinner.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(this.spinner.count * 3), 3);
    this.spinner.frustumCulled = false;
    this.spinner.count = 0;
    this.scene.add(this.spinner);

    // Sky dome in the world's true orientation: the horizon is what tells you you're upside down.
    this.skyUniforms = { top: { value: new THREE.Color() }, horizon: { value: new THREE.Color() }, bottom: { value: new THREE.Color() }, glow: { value: new THREE.Color() } };
    this.sky = new THREE.Mesh(
      new THREE.SphereGeometry(150, 32, 20),
      new THREE.ShaderMaterial({
        uniforms: this.skyUniforms,
        side: THREE.BackSide,
        depthWrite: false,
        fog: false,
        vertexShader: /* glsl */ `
          varying vec3 vDir;
          void main() {
            vDir = position;
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
            gl_Position.z = gl_Position.w;
          }`,
        fragmentShader: /* glsl */ `
          uniform vec3 top;
          uniform vec3 horizon;
          uniform vec3 bottom;
          uniform vec3 glow;
          varying vec3 vDir;
          float h1(float n) { return fract(sin(n * 12.9898) * 43758.5453); }
          void main() {
            vec3 d = normalize(vDir);
            float e = d.y;
            vec3 c = mix(horizon, top, smoothstep(0.0, 0.55, e));
            c = mix(c, bottom, smoothstep(0.0, -0.35, e));
            // A far skyline of phone towers: something to see the horizon turn by.
            float az = atan(d.z, d.x) * 57.2958;
            float col = floor(az / 3.0);
            float hgt = 0.02 + 0.13 * h1(col) * h1(col + 7.0);
            if (e > -0.06 && e < hgt) {
              c = bottom * 0.7;
              vec2 w = vec2(fract(az / 0.75), fract(e * 90.0));
              float lit = step(0.55, h1(floor(az / 0.75) * 3.1 + floor(e * 90.0) * 17.0));
              if (w.x > 0.3 && w.x < 0.7 && w.y > 0.25 && w.y < 0.75) c += glow * lit * 0.8;
            }
            gl_FragColor = vec4(c, 1.0);
          }`,
      }),
    );
    this.sky.renderOrder = -1;
    this.sky.frustumCulled = false;
    this.scene.add(this.sky);

    // --- towers: walls of vertical feeds on both sides ---
    const towerSlots = 2 * (Math.ceil((visibleAhead + BEHIND_ORBIT + 20) / TOWER_STEP) + 2);
    const maxCells = towerSlots * 6;
    const cellGeo = new THREE.PlaneGeometry(CELL_W - 0.25, CELL_H - 0.3, 2, 1);
    this.towerCellIds = cellAttribute(cellGeo, maxCells);
    this.towerCells = new THREE.InstancedMesh(cellGeo, this.mats.tower, maxCells);
    this.towerCells.frustumCulled = false;
    this.scene.add(this.towerCells);
    this.towerBacks = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1, 1, 1, 2), this.mats.dark, towerSlots);
    this.towerBacks.frustumCulled = false;
    this.scene.add(this.towerBacks);

    this.gate = new Gate(this.scene, feedAtlas, this.mats.dark, this.seamMat, visibleAhead);

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
    this.autoplayTex = makeAutoplay();
    const glow = (hex: string) => new THREE.MeshBasicMaterial({ color: new THREE.Color(hex).multiplyScalar(2.2) });
    this.padMats = {
      ramp: new THREE.MeshBasicMaterial({ map: makeRampFace(), color: new THREE.Color(1.3, 1.3, 1.3) }),
      bouncer: new THREE.MeshBasicMaterial({ map: makeBouncerTop(), color: new THREE.Color(1.4, 1.4, 1.4) }),
      autoplay: new THREE.MeshBasicMaterial({ map: this.autoplayTex, color: new THREE.Color(2.4, 1.8, 0.2), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }),
      glow: { ramp: glow(PAD_COLOURS.ramp), bouncer: glow(PAD_COLOURS.bouncer), autoplay: glow(PAD_COLOURS.autoplay) },
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
    // Bend everything but the runner, their shadow and the sky.
    for (const o of this.scene.children) if (o !== this.player && o !== this.shadow && o !== this.sky) this.bend.patchTree(o);
    this.post = new Post(this.renderer, this.scene, this.camera);
    this.resize();
    window.addEventListener('resize', () => this.resize());
  }

  /** Show the chosen doomscroller, loading its model on first use. */
  setCharacter(i: number): void {
    this.character = i;
    const look = CHARACTER_LOOKS[i] ?? CHARACTER_LOOKS[0];
    void this.loadModel(look.model).then((hero) => {
      if (!hero || this.character !== i) return;
      this.player.remove(this.hero ? this.hero.root : this.playerParts.rig);
      this.hero = hero;
      this.player.add(hero.root);
      // Warm the rest so flicking through the select screen is instant.
      for (const l of CHARACTER_LOOKS) void this.loadModel(l.model);
    });
    this.player.scale.setScalar(look.scale);
  }

  private loadModel(model: string): Promise<Hero | null> {
    let p = this.heroes.get(model);
    if (!p) {
      p = Hero.load(`${import.meta.env.BASE_URL}assets/characters/${model}.glb`).catch((err) => {
        console.warn(`${model}.glb failed to load, keeping grey box`, err);
        return null;
      });
      this.heroes.set(model, p);
    }
    return p;
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
    const body = new THREE.Mesh(new THREE.BoxGeometry(2.0, 2.8, 1, 1, 1, 12), [side, side, d, d, front, d]);
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
    if (!obj.parent) {
      this.bend.patchTree(obj);
      this.scene.add(obj);
    }
    return obj;
  }

  // ---------- pads (built with their near edge at the origin, running toward -z) ----------

  private buildPad(kind: PadKind): THREE.Object3D {
    const g = new THREE.Group();
    const t = TUNING.pads;
    const m = this.padMats;
    const d = this.mats.dark;
    if (kind === 'ramp') {
      const { length: L, height: H } = t.ramp;
      const slope = Math.hypot(L, H);
      const tilt = new THREE.Group();
      tilt.rotation.x = Math.atan2(H, L);
      const deck = new THREE.Mesh(new THREE.PlaneGeometry(1.9, slope, 1, 4).rotateX(-Math.PI / 2).translate(0, 0.02, -slope / 2), m.ramp);
      const slab = new THREE.Mesh(new THREE.BoxGeometry(2.0, 0.14, slope, 1, 1, 4).translate(0, -0.06, -slope / 2), d);
      tilt.add(deck, slab);
      for (const side of [-1, 1]) {
        const rail = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.07, slope, 1, 1, 4).translate(side * 0.98, 0.05, -slope / 2), m.glow.ramp);
        tilt.add(rail);
      }
      const back = new THREE.Mesh(new THREE.BoxGeometry(2.0, H, 0.12), d);
      back.position.set(0, H / 2, -L + 0.06);
      g.add(tilt, back);
    } else if (kind === 'bouncer') {
      const L = t.bouncer.length;
      const r = L / 2;
      const top = new THREE.Group();
      top.name = 'top';
      const pad = new THREE.Mesh(new THREE.CylinderGeometry(r, r, 0.14, 28), [d, m.bouncer, d]);
      const ring = new THREE.Mesh(new THREE.TorusGeometry(r, 0.05, 6, 28).rotateX(Math.PI / 2), m.glow.bouncer);
      ring.position.y = 0.07;
      top.add(pad, ring);
      top.position.set(0, 0.32, -r);
      const spring = new THREE.Group();
      spring.name = 'spring';
      for (let i = 0; i < 3; i++) {
        const coil = new THREE.Mesh(new THREE.TorusGeometry(r * 0.55, 0.04, 5, 20).rotateX(Math.PI / 2), this.mats.pole);
        coil.position.y = 0.06 + i * 0.09;
        spring.add(coil);
      }
      spring.position.z = -r;
      g.add(top, spring);
    } else {
      const L = t.autoplay.length;
      const strip = new THREE.Mesh(new THREE.PlaneGeometry(1.8, L, 1, 6).rotateX(-Math.PI / 2).translate(0, 0.05, -L / 2), m.autoplay);
      g.add(strip);
      for (const side of [-1, 1]) {
        const edge = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.04, L, 1, 1, 6).translate(side * 0.93, 0.04, -L / 2), m.glow.autoplay);
        g.add(edge);
      }
    }
    return g;
  }

  private syncPads(w: World, dt: number): void {
    const seen = new Set<number>();
    for (const pd of w.pads) {
      if (pd.s - w.d > this.visibleAhead) continue;
      seen.add(pd.id);
      let entry = this.padActive.get(pd.id);
      if (!entry) {
        const pool = this.padPools.get(pd.kind) ?? [];
        this.padPools.set(pd.kind, pool);
        const obj = pool.pop() ?? this.buildPad(pd.kind);
        if (!obj.parent) {
          this.bend.patchTree(obj);
          this.scene.add(obj);
        }
        obj.visible = true;
        entry = { kind: pd.kind, obj, t: 0 };
        this.padActive.set(pd.id, entry);
      }
      entry.obj.position.set(laneX(pd.lane), 0, -(pd.s - w.d));
      if (pd.kind === 'bouncer') {
        // Squash on launch, then wobble back.
        if (pd.used) entry.t += dt;
        const k = pd.used ? Math.exp(-entry.t * 5) * Math.cos(entry.t * 30) : 0;
        entry.obj.getObjectByName('top')!.position.y = 0.32 - 0.22 * k;
        entry.obj.getObjectByName('spring')!.scale.y = 1 - 0.7 * k;
      }
    }
    for (const [id, entry] of this.padActive) {
      if (!seen.has(id)) {
        entry.obj.visible = false;
        this.padPools.get(entry.kind)!.push(entry.obj);
        this.padActive.delete(id);
      }
    }
    // Chevrons crawl forward, like the next video loading.
    this.autoplayTex.repeat.set(1, TUNING.pads.autoplay.length / 1.6);
    this.autoplayTex.offset.y -= dt * 2.2;
  }

  /** Spinner dashes along both sides of every loop and corkscrew in view. */
  private syncSpinner(w: World, behind: number, time: number): void {
    const course = w.course;
    let n = 0;
    let s = w.d - behind;
    while (s < w.d + this.visibleAhead && n + SPINNER_DASHES * 2 <= this.spinner.instanceMatrix.count) {
      const seg = course.segmentAt(s);
      if (seg.kind === 'loop' || seg.kind === 'corkscrew') {
        const L = seg.s1 - seg.s0;
        const step = L / SPINNER_DASHES;
        const head = (time * 9) % SPINNER_DASHES;
        for (let i = 0; i < SPINNER_DASHES; i++) {
          // Classic spinner: bright head, fading tail.
          const age = (head - i + SPINNER_DASHES) % SPINNER_DASHES;
          const b = 0.25 + 2.4 * Math.max(0, 1 - age / 7);
          this.colour.copy(this.seamMat.color).multiplyScalar(b);
          for (const side of [-1, 1]) {
            this.dummy.position.set(side * SPINNER_X, 0.25, -(seg.s0 + (i + 0.5) * step - w.d));
            this.dummy.rotation.set(0, 0, 0);
            this.dummy.scale.set(1, 1, step * 0.55);
            this.dummy.updateMatrix();
            this.spinner.setMatrixAt(n, this.dummy.matrix);
            this.spinner.setColorAt(n++, this.colour);
          }
        }
      }
      s = seg.s1 + 0.01;
    }
    this.spinner.count = n;
    this.spinner.instanceMatrix.needsUpdate = true;
    if (this.spinner.instanceColor) this.spinner.instanceColor.needsUpdate = true;
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
    this.baseFov = w / h < 1 ? 70 : 55;
    this.camera.fov = this.baseFov;
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
      if (e.type === 'boost') {
        this.shake = Math.max(this.shake, 0.5);
        fx.burst(p.x, 1.1, 0, 48, '#ff2e3b', { speed: 6, size: 0.26, life: 0.9, gravity: 1, bright: 2.6, up: 2 });
      }
      if (e.type === 'smash') {
        this.shake = Math.max(this.shake, 0.45);
        fx.burst(laneX(e.lane), 1, -1.2, 26, '#00e1ff', { speed: 8, size: 0.2, life: 0.7, gravity: 10, bright: 2.2, up: 3 });
      }
      if (e.type === 'edge') this.shake = Math.max(this.shake, 0.15);
      if (e.type === 'pad') {
        const launch = e.kind !== 'autoplay';
        this.shake = Math.max(this.shake, launch ? 0.4 : 0.2);
        fx.burst(laneX(e.lane), 0.3, -0.5, launch ? 30 : 18, PAD_COLOURS[e.kind], { speed: launch ? 5 : 3, size: 0.24, life: 0.7, gravity: 4, bright: 2.4, up: launch ? 3 : 1 });
      }
      if (e.type === 'lift') fx.burst(p.x, 0.1, 0, 14, '#ffffff', { speed: 2.5, size: 0.18, life: 0.5, gravity: 1, bright: 1.6, up: 0.4 });
      if (e.type === 'thrill') {
        this.shake = Math.max(this.shake, 0.3);
        fx.burst(p.x, 1.2, 0, Math.round(14 + 30 * e.tolerance), '#ffcc00', { speed: 6, size: 0.22 + 0.12 * e.tolerance, life: 1, gravity: 0.5, bright: 1.2 + 1.8 * e.tolerance, up: 1 });
      }
      if (e.type === 'crash') {
        this.shake = 1.2;
        this.crashT = 0;
      }
      if (e.type === 'start' || e.type === 'revive') this.crashT = -1;
      if (e.type === 'start') {
        this.introT = 0;
        this.introFrom = ((this.turn % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
      }
      if (e.type === 'roll') this.rollSpin = 0;
      if (e.type === 'gate') {
        this.gateKick = 0;
        this.shake = Math.max(this.shake, 0.35);
        fx.burst(p.x, 1.2, 0, 40, '#00e1ff', { speed: 6, size: 0.22, life: 1.2, gravity: 0, bright: 2.2, up: 0.5 });
      }
    }
  }

  render(w: World, dt: number): void {
    const d = w.d;
    const time = performance.now() / 1000;
    // Sim-time step: animation and particles slow down with the gate's bullet time.
    const sdt = dt * w.timeScale;
    const target = Math.min(1, Math.max(0, w.dopamine / w.t.dopamine.fullColourAt));
    this.level += (target - this.level) * (1 - Math.exp(-dt * 3));
    const orbiting = w.gateT >= 0 || w.phase === 'ready' || this.introT >= 0;
    const behind = orbiting ? BEHIND_ORBIT : BEHIND;
    this.bend.update(w.course, d);
    this.syncTrack(d, behind);
    this.syncTowers(w, behind);
    this.syncObstacles(w);
    this.syncPads(w, sdt);
    this.syncSpinner(w, behind, time);
    this.syncPickups(w, time);
    this.syncPlayer(w, sdt);
    this.gate.update(w, time);
    this.syncZone(w);
    this.syncCamera(w, dt);
    // The sky keeps the world's real orientation, centred on the camera.
    this.sky.position.copy(this.camera.position);
    this.sky.quaternion.copy(this.bend.runner).invert();

    const lines = w.phase === 'running' && w.gateT < 0 ? Math.min(1, Math.max(0, (this.level - 0.6) / 0.4)) * Math.min(1, Math.max(0, 0.3 + (w.speed - w.t.speed.start) / 10)) : 0;
    this.particles.update(sdt, w.runSpeed * sdt, this.camera, lines, w.runSpeed);
    this.post.grade.uniforms.dopamine.value = this.level;
    this.post.bloom.strength = 0.6 * (0.2 + 0.8 * this.level);
    this.post.grade.uniforms.time.value = time;
    this.post.grade.uniforms.shake.value = this.shake;
    this.shake = Math.max(0, this.shake - dt * 2.5);
    this.post.apply();
    this.post.render(dt);
  }

  private syncTrack(d: number, behind: number): void {
    const first = Math.floor((d - behind) / TILE_LEN);
    const last = Math.floor((d + this.visibleAhead) / TILE_LEN);
    let n = 0;
    let row = 0;
    for (let i = first; i <= last; i++) {
      const z = -(i * TILE_LEN + TILE_LEN / 2 - d);
      this.dummy.rotation.set(0, 0, 0);
      this.dummy.scale.set(1, 1, 1);
      this.dummy.position.set(0, -0.3, z);
      this.dummy.updateMatrix();
      this.deck.setMatrixAt(row, this.dummy.matrix);
      for (let k = 0; k < 4; k++) {
        this.dummy.position.set((k - 1.5) * 2.2, 0.03, z);
        this.dummy.updateMatrix();
        this.seams.setMatrixAt(row * 4 + k, this.dummy.matrix);
      }
      row++;
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
    this.deck.count = row;
    this.deck.instanceMatrix.needsUpdate = true;
    this.seams.count = row * 4;
    this.seams.instanceMatrix.needsUpdate = true;
  }

  private syncTowers(w: World, behind: number): void {
    const d = w.d;
    const first = Math.floor((d - behind) / TOWER_STEP);
    const last = Math.floor((d + this.visibleAhead) / TOWER_STEP);
    let n = 0;
    let backs = 0;
    for (let i = first; i <= last; i++) {
      // No towers where the track goes upside down.
      if (!w.course.scenery(i * TOWER_STEP)) continue;
      for (const side of [-1, 1]) {
        const r = hash(i, side + 7);
        if (r < 0.12) continue; // gaps in the skyline
        const cells = 1 + Math.floor(hash(i, side + 11) * 5);
        const xFace = side * (4.6 + hash(i, side + 13) * 2.2);
        const z = -(i * TOWER_STEP - d);
        const depth = 1.2;
        const height = cells * CELL_H;
        // Backs reach well below the deck so drops don't show where they stop.
        const below = 24;
        this.dummy.rotation.set(0, 0, 0);
        this.dummy.position.set(xFace + side * (depth / 2 + 0.02), (height - below) / 2, z);
        this.dummy.scale.set(depth, height + below, CELL_W);
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
      // Walked-into habits and anything smashed by a boost are gone.
      obj.visible = !o.hit;
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

  /** The feed re-skins to the new zone while the gate camera is round the front. */
  private syncZone(w: World): void {
    const to = ZONES[zoneLook(w.zone) % ZONES.length];
    const from = ZONES[zoneLook(Math.max(0, w.zone - 1)) % ZONES.length];
    const k = w.gateT >= 0 ? THREE.MathUtils.smoothstep(w.gateT / w.t.gate.duration, 0.3, 0.7) : 1;
    this.seamMat.color.copy(from.seam).lerp(to.seam, k);
    this.hemi.color.copy(from.light).lerp(to.light, k);
    this.skyColour.copy(from.sky).lerp(to.sky, k);
    (this.scene.background as THREE.Color).copy(this.skyColour);
    this.scene.fog!.color.copy(this.skyColour);
    const u = this.skyUniforms;
    u.horizon.value.copy(this.skyColour);
    u.top.value.copy(this.skyColour).multiplyScalar(0.35);
    u.bottom.value.copy(this.skyColour).multiplyScalar(0.25);
    u.glow.value.copy(this.seamMat.color);
  }

  private syncCamera(w: World, dt: number): void {
    const p = w.player;
    const k = 1 - Math.pow(0.0008, dt);
    this.camX = THREE.MathUtils.lerp(this.camX, p.x * 0.65, k);
    this.camY = THREE.MathUtils.lerp(this.camY, p.y * 0.35, 1 - Math.pow(0.02, dt));
    const shake = this.shake * this.shake;
    const jx = (Math.random() - 0.5) * shake * 0.5;
    const jy = (Math.random() - 0.5) * shake * 0.5;
    const cam = this.camera;
    cam.position.set(this.camX + jx, 3.5 + this.camY + jy, 6.4);
    const look = this.lookV.set(this.camX * 1.1, 1.1 + this.camY * 0.5, -9);
    let fov = this.baseFov;
    let roll = 0;

    if (w.phase === 'ready') {
      // Title turntable: a slow lap round the chosen doomscroller, framed high
      // so the select card below doesn't cover them.
      this.turn += dt * 0.45;
      this.introT = -1;
      cam.position.set(p.x + Math.sin(this.turn) * 3.6, 1.5, Math.cos(this.turn) * 3.6);
      look.set(p.x, 0.9, 0);
    } else if (this.introT >= 0) {
      // Run started: finish the lap into the chase view.
      this.introT += dt;
      const b = THREE.MathUtils.smootherstep(this.introT, 0, INTRO);
      const theta = THREE.MathUtils.lerp(this.introFrom, Math.PI * 2, b);
      const r = THREE.MathUtils.lerp(3.6, 6.4, b);
      cam.position.set(this.camX + Math.sin(theta) * r + jx, THREE.MathUtils.lerp(1.5, 3.5 + this.camY, b) + jy, Math.cos(theta) * r);
      look.lerp(this.tmpV.set(p.x, 0.9, 0), 1 - b);
      if (this.introT >= INTRO) this.introT = -1;
    } else if (w.gateT >= 0) {
      // Ride the gate's rail: one full turn round the runner, starting and
      // ending on the chase view, dipping lower and closer on the far side.
      const g = w.t.gate;
      const o = THREE.MathUtils.smootherstep(w.gateT, 0.2, g.duration - 0.5);
      const theta = o * Math.PI * 2;
      const bump = Math.sin(Math.PI * o);
      const r = 6.4 - 1.2 * bump;
      const focus = THREE.MathUtils.smoothstep(o, 0, 0.15) * (1 - THREE.MathUtils.smoothstep(o, 0.85, 1));
      // Orbit the runner, not the lagging chase-camera x.
      const ox = THREE.MathUtils.lerp(this.camX, p.x, focus);
      cam.position.set(ox + Math.sin(theta) * r + jx, 3.5 + this.camY - 1.2 * bump + jy, Math.cos(theta) * r);
      look.lerp(this.tmpV.set(ox, 1.0 + p.y * 0.6, 0), focus);
      fov -= 8 * bump;
      roll = 0.12 * bump * Math.sin(theta);
    }
    // Notification boost: the world stretches past you.
    fov += 14 * w.boost;
    // Zoom punch as the gate grabs you.
    this.gateKick += dt;
    fov += 10 * Math.exp(-this.gateKick * 5);

    // Where the track ahead twists hard (loops, corkscrews), aim closer and
    // widen the view so the runner stays in frame against the wall of track.
    this.bend.frame(-9, this.tmpP, this.tmpQ);
    const twist = THREE.MathUtils.smoothstep(2 * Math.acos(Math.min(1, Math.abs(this.tmpQ.w))), 0.25, 1.1);
    look.z = THREE.MathUtils.lerp(look.z, -2.5, twist);
    fov += 14 * twist;

    // Everything above was worked out on the straight track; ride it onto the coaster.
    this.bend.up(cam.position.z, this.upV);
    this.camUp.lerp(this.upV, 1 - Math.exp(-dt * 10)).normalize();
    this.bend.map(cam.position);
    // Aim mostly along the runner's own tangent: a fully bent aim point swings
    // out of frame over the top of a tight loop and loses the runner.
    look.lerp(this.bend.map(this.tmpV.copy(look)), 0.3);
    cam.up.copy(this.camUp);
    cam.lookAt(look);
    if (roll !== 0) cam.rotateZ(roll);
    if (Math.abs(cam.fov - fov) > 0.01) {
      cam.fov = fov;
      cam.updateProjectionMatrix();
    }
  }

  stats(): { calls: number; tris: number } {
    return { calls: this.renderer.info.render.calls, tris: this.renderer.info.render.triangles };
  }
}
