// Loading the Blender-built .glb assets (docs/assets-v2.md is the contract).
// One shared GLTFLoader with the meshopt geometry decoder and the KTX2 texture
// transcoder (basis files copied into public/libs/basis/). Kits are .glb files
// of named top-level meshes; a Kit hands out clones that share geometry and
// materials, so a hundred street lamps are one upload.

import * as THREE from 'three';
import { GLTFLoader, type GLTF } from 'three/addons/loaders/GLTFLoader.js';
import { KTX2Loader } from 'three/addons/loaders/KTX2Loader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';

const base = import.meta.env.BASE_URL;
let loader: GLTFLoader | null = null;

/** Call once with the renderer (KTX2 picks the GPU's compressed format). */
export function initAssets(renderer: THREE.WebGLRenderer): void {
  const ktx2 = new KTX2Loader().setTranscoderPath(`${base}libs/basis/`).detectSupport(renderer);
  loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).setKTX2Loader(ktx2);
}

function gltfLoader(): GLTFLoader {
  if (!loader) loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder);
  return loader;
}

export function loadGltf(path: string): Promise<GLTF> {
  return gltfLoader().loadAsync(`${base}${path}`);
}

/** A mesh piece of a kit node: geometry and material in the node's own frame. */
export interface KitPart {
  geometry: THREE.BufferGeometry;
  material: THREE.Material;
  /** The part's transform relative to its kit node. */
  matrix: THREE.Matrix4;
}

export class Kit {
  /** Top-level nodes by name. */
  private readonly nodes = new Map<string, THREE.Object3D>();
  private readonly partsCache = new Map<string, KitPart[]>();

  constructor(readonly name: string, gltf: GLTF) {
    for (const child of gltf.scene.children) this.nodes.set(child.name, child);
  }

  has(name: string): boolean {
    return this.nodes.has(name);
  }

  names(prefix = ''): string[] {
    return [...this.nodes.keys()].filter((n) => n.startsWith(prefix));
  }

  /** Custom properties the Blender script put on the node (glTF extras). */
  extras(name: string): Record<string, unknown> {
    return (this.nodes.get(name)?.userData ?? {}) as Record<string, unknown>;
  }

  /** A clone of the node (geometry and materials shared). Its own transform is reset:
   *  the kit's layout in Blender doesn't matter, only each piece's origin. */
  clone(name: string): THREE.Object3D | null {
    const node = this.nodes.get(name);
    if (!node) return null;
    const c = node.clone(true);
    c.position.set(0, 0, 0);
    c.quaternion.identity();
    c.scale.set(1, 1, 1);
    return c;
  }

  /** Every mesh under the node, flattened into the node's frame (for instancing). */
  parts(name: string): KitPart[] {
    const hit = this.partsCache.get(name);
    if (hit) return hit;
    const node = this.nodes.get(name);
    const out: KitPart[] = [];
    if (node) {
      node.updateMatrixWorld(true);
      const inv = new THREE.Matrix4().copy(node.matrixWorld).invert();
      node.traverse((o) => {
        const mesh = o as THREE.Mesh;
        if (!mesh.isMesh) return;
        const matrix = new THREE.Matrix4().multiplyMatrices(inv, mesh.matrixWorld);
        const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
        if (mats.length === 1) out.push({ geometry: mesh.geometry, material: mats[0], matrix });
        else {
          // Multi-material meshes: one part per group.
          for (const g of mesh.geometry.groups) {
            const geo = mesh.geometry.clone();
            geo.clearGroups();
            geo.setDrawRange(g.start, g.count);
            out.push({ geometry: geo, material: mats[g.materialIndex ?? 0], matrix });
          }
        }
      });
    }
    this.partsCache.set(name, out);
    return out;
  }

  /** Every material in the kit with this name. */
  materials(name: string): THREE.Material[] {
    const out = new Set<THREE.Material>();
    for (const node of this.nodes.values()) {
      node.traverse((o) => {
        const mesh = o as THREE.Mesh;
        if (!mesh.isMesh) return;
        for (const m of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) if (m.name === name) out.add(m);
      });
    }
    return [...out];
  }
}

const kits = new Map<string, Promise<Kit | null>>();

/** `public/assets/kits/<name>.glb`, cached. Resolves null if missing (the renderer keeps its grey box). */
export function loadKit(name: string): Promise<Kit | null> {
  let p = kits.get(name);
  if (!p) {
    p = loadGltf(`assets/kits/${name}.glb`)
      .then((g) => new Kit(name, g))
      .catch((err) => {
        console.warn(`kit ${name} not loaded, keeping the grey box`, err);
        return null;
      });
    kits.set(name, p);
  }
  return p;
}

/** A texture from public/, sRGB (for colour maps and the sky), or null if missing. */
export function loadTexture(path: string): Promise<THREE.Texture | null> {
  return new THREE.TextureLoader()
    .loadAsync(`${base}${path}`)
    .then((t) => {
      t.colorSpace = THREE.SRGBColorSpace;
      return t;
    })
    .catch(() => null);
}
