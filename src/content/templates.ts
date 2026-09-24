// Tiny template filler for the content bank. `{handle}`, `{thing}` etc. are
// drawn from `pools` in content.json; any other `{key}` comes from `vars`.
// Pure (no DOM), so textures, UI and a future port can all share it.

import { content } from './content';

type Pools = Record<string, string[]>;
const POOLS: Pools = content.pools;

export function fill(template: string, vars: Record<string, string | number> = {}, rand: () => number = Math.random): string {
  return template.replace(/\{(\w+)\}/g, (whole, key: string) => {
    if (key in vars) return String(vars[key]);
    const pool = POOLS[key];
    return pool ? pool[Math.floor(rand() * pool.length)] : whole;
  });
}

export function pick<T>(items: readonly T[], rand: () => number = Math.random): T {
  return items[Math.floor(rand() * items.length)];
}

/** Deterministic random source for build-time content (textures). */
export function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    let t = (a = (a + 0x6d2b79f5) >>> 0);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
