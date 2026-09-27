// A set of instanced meshes drawn together: one InstancedMesh per part of a
// model (a kit node can have several materials), all placed by one matrix per
// instance. Used for anything repeated along the track: decks, scenery,
// tunnel modules, rail modules, pickups.

import * as THREE from 'three';
import type { KitPart } from './assets';
import type { Bend } from './bend';

export class PartSet {
  readonly meshes: THREE.InstancedMesh[] = [];
  private readonly parts: KitPart[];
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

  /** Add an instance at `matrix`; false once full. */
  add(matrix: THREE.Matrix4): boolean {
    if (this.n >= this.max) return false;
    for (let i = 0; i < this.parts.length; i++) {
      this.meshes[i].setMatrixAt(this.n, this.tmp.multiplyMatrices(matrix, this.parts[i].matrix));
    }
    this.n++;
    return true;
  }

  end(): void {
    for (const m of this.meshes) {
      m.count = this.n;
      m.instanceMatrix.needsUpdate = true;
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
