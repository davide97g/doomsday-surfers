// The five biomes (zone % 5): Feed City, Group Chat Canyon, Comment Section
// Sewer, 3 AM Bedroom, Infinite Mall. The lanes are always giant phone screens;
// a biome changes what they show (its own feed atlas), the deck they sit in,
// the scenery beside the track, the tunnel and rail skins, the sky (a Blender
// panorama that also lights reflections) and the light, fog and exposure.
//
// Biome kits (public/assets/kits/<name>.glb, docs/assets-v2.md) load on demand
// for the zone you're in and the next one. Until a kit arrives the renderer's
// procedural deck and towers stand in. Scenery is placed deterministically from
// each piece's glTF extras (slot, every, chance, side), so a seed always looks
// the same. Each row of track takes the biome of the zone it lies in, so the
// next biome is already there past the gate.

import * as THREE from 'three';
import { content, mode } from '../content/content';
import { TUNING, zoneLook } from '../sim/types';
import type { World } from '../sim/world';
import { loadKit, loadTexture, type Kit, type KitPart } from './assets';
import { atlasGlass, atlasMaterial, cellAttribute, hash } from './atlas';
import type { Bend } from './bend';
import { PartSet } from './instanced';
import { biomeAtS, type Structures } from './structures';
import { FEED_ATLAS, makeFeedAtlas } from './textures';

export const BIOMES = TUNING.biomes.names;
const FEED_CELLS = FEED_ATLAS.cols * FEED_ATLAS.rows;
const WORK = mode === 'work';

/** How a biome is lit. Missing fields fall back to Feed City's night. */
export interface BiomeLook {
  fogNear: number;
  fogFar: number;
  hemi: number;
  sun: THREE.Color;
  sunI: number;
  exposure: number;
  env: number;
}

type ZoneJson = { look?: Partial<{ fog: number[]; hemi: number; sun: string; sunI: number; exposure: number; env: number }> };

export const LOOKS: BiomeLook[] = content.zones.map((z) => {
  const l = (z as ZoneJson).look ?? {};
  return {
    fogNear: l.fog?.[0] ?? 45,
    fogFar: l.fog?.[1] ?? 160,
    hemi: l.hemi ?? 1.3,
    sun: new THREE.Color(l.sun ?? '#ffffff'),
    sunI: l.sunI ?? 1.6,
    exposure: l.exposure ?? 1,
    env: l.env ?? 0.6,
  };
});

const SLOTS: Record<string, [number, number]> = { wall: [4.6, 7], mid: [8, 20], far: [20, 60] };

interface Scenery {
  set: PartSet;
  index: number;
  slot: [number, number];
  every: number;
  chance: number;
  sides: number[];
  jitter: boolean;
}

interface Loaded {
  kit: Kit;
  deck: PartSet | null;
  seam: PartSet | null;
  scenery: Scenery[];
}

export class BiomeView {
  private readonly requested = new Set<number>();
  private readonly loaded = new Map<number, Loaded>();
  private readonly atlases = new Map<number, THREE.Texture>();
  private readonly tiles = new Map<number, { mesh: THREE.InstancedMesh; cells: THREE.InstancedBufferAttribute; flat: THREE.MeshBasicMaterial; glass: THREE.MeshStandardMaterial }>();
  /** Quality: glass screens, and how much of the scenery is placed. */
  glass = true;
  density = 1;
  private readonly skies = new Map<number, THREE.Texture>();
  private readonly envs = new Map<number, THREE.Texture>();
  private readonly pmrem: THREE.PMREMGenerator;
  private readonly m = new THREE.Matrix4();
  private readonly q = new THREE.Quaternion();
  private readonly v = new THREE.Vector3();
  private readonly sc = new THREE.Vector3();
  private readonly up = new THREE.Vector3(0, 1, 0);
  private slop: THREE.Texture | null = null;
  /** Callbacks for kit pieces other systems draw (rails, tunnels, overhangs). */
  onKit: (biome: number, kit: Kit) => void = () => {};

  constructor(
    private readonly scene: THREE.Scene,
    private readonly bend: Bend,
    renderer: THREE.WebGLRenderer,
    private readonly structures: Structures,
    private readonly seamMat: THREE.Material,
    private readonly maxTiles: number,
    private readonly feedAtlas: THREE.Texture,
  ) {
    this.pmrem = new THREE.PMREMGenerator(renderer);
    this.atlases.set(0, feedAtlas);
  }

  /** The kit for this biome has its own deck (the renderer skips its stand-in). */
  hasDeck(b: number): boolean {
    return !!this.loaded.get(b)?.deck;
  }

  hasScenery(b: number): boolean {
    return (this.loaded.get(b)?.scenery.length ?? 0) > 0;
  }

  kit(b: number): Kit | null {
    return this.loaded.get(b)?.kit ?? null;
  }

  sky(b: number): THREE.Texture | null {
    return this.skies.get(b) ?? null;
  }

  env(b: number): THREE.Texture | null {
    return this.envs.get(b) ?? null;
  }

  /** Start loading a biome's kit, sky and feed atlas (idempotent). */
  request(b: number): void {
    if (this.requested.has(b)) return;
    this.requested.add(b);
    const name = BIOMES[b];
    // The atlas is a big canvas: draw it off the frame that asked for it.
    if (!this.atlases.has(b)) setTimeout(() => this.atlases.set(b, WORK ? this.feedAtlas : makeFeedAtlas(b)), 0);
    void loadTexture(`assets/kits/${name}-sky.jpg`).then((t) => {
      if (!t) return;
      t.mapping = THREE.EquirectangularReflectionMapping;
      this.skies.set(b, t);
      this.envs.set(b, this.pmrem.fromEquirectangular(t).texture);
    });
    // Work mode keeps its office look on the Feed City kit (see docs/v2-gameplay.md).
    if (WORK && b !== 0) return;
    void loadKit(name).then((kit) => {
      if (kit) this.install(b, kit);
    });
  }

  private install(b: number, kit: Kit): void {
    const rows = Math.ceil(this.maxTiles / 3) + 2;
    const deckParts = kit.parts('deck');
    const seamParts = kit.parts('deck_seam').map((p): KitPart => ({ ...p, material: this.seamMat }));
    const scenery: Scenery[] = [];
    kit.names('side_').forEach((name, index) => {
      const x = kit.extras(name);
      const every = Math.max(2, Number(x.every ?? 12));
      const side = String(x.side ?? 'both');
      const slot = SLOTS[String(x.slot ?? 'wall')] ?? SLOTS.wall;
      const max = Math.ceil((this.maxTiles / 3) * 4.4 / every) * 2 + 6;
      scenery.push({
        set: new PartSet(this.scene, this.bend, kit.parts(name), max),
        index,
        slot,
        every,
        chance: Math.min(1, Math.max(0, Number(x.chance ?? 0.6))),
        sides: side === 'left' ? [-1] : side === 'right' ? [1] : [-1, 1],
        jitter: String(x.slot ?? 'wall') !== 'wall',
      });
    });
    this.loaded.set(b, {
      kit,
      deck: deckParts.length ? new PartSet(this.scene, this.bend, deckParts, rows) : null,
      seam: seamParts.length ? new PartSet(this.scene, this.bend, seamParts, rows) : null,
      scenery,
    });
    const tunnel = kit.parts('tunnel');
    if (tunnel.length) this.structures.setTunnel(b, tunnel);
    const railName = kit.names('rail_')[0];
    if (railName) this.structures.setRail(b, kit.parts(railName), kit.parts('rail_end'));
    this.onKit(b, kit);
  }

  /** Lane screens, decks and scenery for every row in view. `slop`: the Slop set piece has the feed. */
  update(w: World, behind: number, visibleAhead: number, tileLen: number, slop: boolean): void {
    const d = w.d;
    const here = zoneLook(w.zone);
    this.request(here);
    this.request(zoneLook(w.zone + 1));

    for (const t of this.tiles.values()) t.mesh.count = 0;
    for (const l of this.loaded.values()) {
      l.deck?.begin();
      l.seam?.begin();
      for (const s of l.scenery) s.set.begin();
    }

    const counts = new Map<number, number>();
    const first = Math.floor((d - behind) / tileLen);
    const last = Math.floor((d + visibleAhead) / tileLen);
    for (let i = first; i <= last; i++) {
      const s = i * tileLen + tileLen / 2;
      const b = biomeAtS(s);
      const z = -(s - d);
      const tile = this.tileMesh(b, slop);
      let n = counts.get(b) ?? 0;
      for (let lane = 0; lane < 3; lane++) {
        this.m.makeTranslation((lane - 1) * TUNING.lanes.width, 0.011, z);
        tile.mesh.setMatrixAt(n, this.m);
        tile.cells.setX(n++, Math.floor(hash(i, lane) * FEED_CELLS));
      }
      counts.set(b, n);
      const l = this.loaded.get(b);
      if (l?.deck) {
        this.m.makeTranslation(0, 0, z);
        l.deck.add(this.m);
        l.seam?.add(this.m);
      }
    }
    for (const [b, n] of counts) {
      const t = this.tiles.get(b)!;
      t.mesh.count = n;
      t.mesh.instanceMatrix.needsUpdate = true;
      t.cells.needsUpdate = true;
    }

    for (const [b, l] of this.loaded) {
      for (const e of l.scenery) this.place(w, b, e, behind, visibleAhead);
      l.deck?.end();
      l.seam?.end();
      for (const s of l.scenery) s.set.end();
    }
  }

  /** Slop set piece: every biome's screens show AI slop. */
  setSlop(tex: THREE.Texture | null): void {
    this.slop = tex;
  }

  private tileMesh(b: number, slop: boolean) {
    let t = this.tiles.get(b);
    if (!t) {
      const geo = new THREE.PlaneGeometry(1.92, 4.4 - 0.34, 1, 4).rotateX(-Math.PI / 2);
      const cells = cellAttribute(geo, this.maxTiles);
      const atlas = this.atlases.get(b) ?? this.feedAtlas;
      const flat = atlasMaterial(atlas, new THREE.Color(0.55, 0.55, 0.6));
      const glass = atlasGlass(atlas, new THREE.Color(0.62, 0.62, 0.68));
      this.bend.patch(flat);
      this.bend.patch(glass);
      const mesh = new THREE.InstancedMesh(geo, this.glass ? glass : flat, this.maxTiles);
      mesh.frustumCulled = false;
      mesh.count = 0;
      this.bend.patchTree(mesh);
      this.scene.add(mesh);
      t = { mesh, cells, flat, glass };
      this.tiles.set(b, t);
    }
    const mat = this.glass ? t.glass : t.flat;
    if (t.mesh.material !== mat) t.mesh.material = mat;
    const map = slop && this.slop ? this.slop : (this.atlases.get(b) ?? this.feedAtlas);
    if (t.flat.map !== map) {
      t.flat.map = map;
      t.flat.needsUpdate = true;
    }
    if (t.glass.emissiveMap !== map) {
      t.glass.emissiveMap = map;
      t.glass.needsUpdate = true;
    }
    return t;
  }

  private place(w: World, b: number, e: Scenery, behind: number, ahead: number): void {
    const d = w.d;
    const first = Math.floor((d - behind - 10) / e.every);
    const last = Math.floor((d + ahead) / e.every);
    for (let i = first; i <= last; i++) {
      const s0 = i * e.every;
      if (biomeAtS(s0) !== b || !w.course.scenery(s0) || w.tunnelAt(s0)) continue;
      for (const side of e.sides) {
        const salt = e.index * 37 + side + 5;
        if (hash(i, salt) >= e.chance * this.density) continue;
        const s = s0 + (hash(i, salt + 1) - 0.5) * e.every * 0.6;
        const x = side * THREE.MathUtils.lerp(e.slot[0], e.slot[1], hash(i, salt + 2));
        const yaw = (side > 0 ? 0 : Math.PI) + (e.jitter ? (hash(i, salt + 3) - 0.5) * 0.5 : 0);
        const k = e.jitter ? 0.85 + 0.35 * hash(i, salt + 4) : 1;
        this.q.setFromAxisAngle(this.up, yaw);
        this.m.compose(this.v.set(x, 0, -(s - d)), this.q, this.sc.set(k, k, k));
        if (!e.set.add(this.m)) break;
      }
    }
  }
}
