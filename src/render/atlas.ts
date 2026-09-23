// Feed-atlas helpers shared by the track, the towers and the checkpoint gate.

import * as THREE from 'three';
import { FEED_ATLAS } from './textures';

/** Basic material that samples one atlas cell per instance (the `cell` attribute). */
export function atlasMaterial(map: THREE.Texture, color: THREE.Color): THREE.MeshBasicMaterial {
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

export function cellAttribute(geo: THREE.BufferGeometry, count: number): THREE.InstancedBufferAttribute {
  const attr = new THREE.InstancedBufferAttribute(new Float32Array(count), 1);
  attr.setUsage(THREE.DynamicDrawUsage);
  geo.setAttribute('cell', attr);
  return attr;
}

export function hash(a: number, b: number): number {
  let h = Math.imul(a ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul(b + 0x632be5ab, 0xc2b2ae35);
  h ^= h >>> 13;
  h = Math.imul(h, 0x27d4eb2f);
  h ^= h >>> 15;
  return (h >>> 0) / 4294967296;
}
