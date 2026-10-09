// A set of instanced meshes drawn together: one InstancedMesh per part of a
// model (a kit node can have several materials), all placed by one matrix per
// instance. Used for anything repeated along the track: decks, scenery,
// tunnel modules, rail modules, pickups.

import * as THREE from 'three';
import type { KitPart } from './assets';
import { atlasMaterial, cellAttribute, hash } from './atlas';
import type { Bend } from './bend';
import { FEED_ATLAS } from './textures';

const FEED_CELLS = FEED_ATLAS.cols * FEED_ATLAS.rows;

/** Parts whose material is `ScreenFeed` (docs/assets-v2.md) show the in-game feed:
 *  their own geometry copy, the atlas material, one random cell per instance. */
export function feedScreens(parts: KitPart[], atlas: THREE.Texture): KitPart[] {
  return parts.map((p) =>
    p.material.name === 'ScreenFeed'
      ? { ...p, geometry: p.geometry.clone(), material: Object.assign(atlasMaterial(atlas, new THREE.Color(0.9, 0.9, 0.95)), { name: 'ScreenFeedLive' }) }
      : p,
  );
}

export class PartSet {
  readonly meshes: THREE.InstancedMesh[] = [];
  private readonly parts: KitPart[];
  private readonly cells: (THREE.InstancedBufferAttribute | null)[] = [];
  private n = 0;
  private readonly tmp = new THREE.Matrix4();

  constructor(
    private readonly scene: THREE.Object3D,
    bend: Bend | null,
    parts: KitPart[],
    readonly max: number,
  ) {
    this.parts = parts;
    for (const part of parts) {
      this.cells.push(part.material.name === 'ScreenFeedLive' ? cellAttribute(part.geometry, max) : null);
      const m = new THREE.InstancedMesh(part.geometry, part.material, max);
      m.frustumCulled = false;
      m.count = 0;
      if (bend) bend.patchTree(m);
      scene.add(m);
      this.meshes.push(m);
    }
  }

  get count(): number {
    return this.n;
  }

  begin(): void {
    this.n = 0;
  }

  /** Add an instance at `matrix`; false once full. `seed` picks its feed cells (live screens). */
  add(matrix: THREE.Matrix4, seed = 0): boolean {
    if (this.n >= this.max) return false;
    for (let i = 0; i < this.parts.length; i++) {
      this.meshes[i].setMatrixAt(this.n, this.tmp.multiplyMatrices(matrix, this.parts[i].matrix));
      this.cells[i]?.setX(this.n, Math.floor(hash(seed, i) * FEED_CELLS));
    }
    this.n++;
    return true;
  }

  end(): void {
    for (let i = 0; i < this.meshes.length; i++) {
      const m = this.meshes[i];
      m.count = this.n;
      m.instanceMatrix.needsUpdate = true;
      const c = this.cells[i];
      if (c) c.needsUpdate = true;
    }
  }

  set visible(v: boolean) {
    for (const m of this.meshes) m.visible = v;
  }

  /** Take it out of the scene (geometry and materials belong to the kit, not us). */
  remove(): void {
    for (const m of this.meshes) {
      this.scene.remove(m);
      m.dispose();
    }
    this.meshes.length = 0;
  }
}

/** A procedural stand-in part (geometry + material, identity matrix). */
export function part(geometry: THREE.BufferGeometry, material: THREE.Material, matrix = new THREE.Matrix4()): KitPart {
  return { geometry, material, matrix };
}
