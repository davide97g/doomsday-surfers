// The second level's fixed pieces: grind rails (giant charger cables) and
// tunnels. Both are instanced modules laid along the track: rails in 1 m
// pieces with a sloped start, tunnels in 4.4 m rows. Each biome can skin them
// (a kit's `rail_*` / `tunnel` nodes); until a kit loads, procedural stand-ins.

import * as THREE from 'three';
import { TUNING, laneX, zoneLook } from '../sim/types';
import type { World } from '../sim/world';
import type { KitPart } from './assets';
import type { Bend } from './bend';
import { PartSet, part } from './instanced';

const TUNNEL_ROW = 4.4;
const MAX_RAIL = 420;
const MAX_TUNNEL = 60;

/** Zone (and so biome) that track distance `s` belongs to: gates crossed before it. */
export function zoneAtS(s: number): number {
  const g = TUNING.gate;
  return s < g.first ? 0 : Math.floor((s - g.first) / g.every) + 1;
}

export function biomeAtS(s: number): number {
  return zoneLook(zoneAtS(s));
}

interface Skin {
  module: PartSet;
  end: PartSet;
}

export class Structures {
  private readonly rails = new Map<number, Skin>();
  private readonly tunnels = new Map<number, PartSet>();
  private readonly fallbackRail: Skin;
  private readonly fallbackTunnel: PartSet;
  private readonly m = new THREE.Matrix4();
  private readonly q = new THREE.Quaternion();
  private readonly v = new THREE.Vector3();
  private readonly one = new THREE.Vector3(1, 1, 1);

  constructor(
    private readonly scene: THREE.Scene,
    private readonly bend: Bend,
    private readonly visibleAhead: number,
    glow: THREE.Material,
  ) {
    this.fallbackRail = this.makeFallbackRail(glow);
    this.fallbackTunnel = new PartSet(scene, bend, fallbackTunnelParts(glow), MAX_TUNNEL);
  }

  /** Skin the rails in `biome` (or every biome without its own, for -1). */
  setRail(biome: number, module: KitPart[], end: KitPart[]): void {
    this.rails.get(biome)?.module.remove();
    this.rails.get(biome)?.end.remove();
    this.rails.set(biome, { module: new PartSet(this.scene, this.bend, module, MAX_RAIL), end: new PartSet(this.scene, this.bend, end, 16) });
  }

  setTunnel(biome: number, parts: KitPart[]): void {
    this.tunnels.get(biome)?.remove();
    this.tunnels.set(biome, new PartSet(this.scene, this.bend, parts, MAX_TUNNEL));
  }

  private railSkin(biome: number): Skin {
    return this.rails.get(biome) ?? this.rails.get(-1) ?? this.fallbackRail;
  }

  private tunnelSkin(biome: number): PartSet {
    return this.tunnels.get(biome) ?? this.fallbackTunnel;
  }

  update(w: World, behind: number): void {
    const d = w.d;
    const all = new Set<Skin | PartSet>([this.fallbackRail, this.fallbackTunnel, ...this.rails.values(), ...this.tunnels.values()]);
    for (const s of all) {
      if (s instanceof PartSet) s.begin();
      else {
        s.module.begin();
        s.end.begin();
      }
    }
    const rl = w.t.rail;
    for (const r of w.rails) {
      if (r.s - rl.ramp - d > this.visibleAhead || r.s + r.length < d - behind) continue;
      const skin = this.railSkin(biomeAtS(r.s));
      const x = laneX(r.lane);
      skin.end.add(this.place(x, 0, -(r.s - d)));
      const from = Math.max(0, Math.floor(d - behind - r.s));
      const to = Math.min(Math.ceil(r.length), Math.ceil(d + this.visibleAhead - r.s));
      for (let k = from; k < to; k++) {
        // The last module is squeezed to end exactly at the rail's end.
        const len = Math.min(1, r.length - k);
        this.m.compose(this.v.set(x, 0, -(r.s + k - d)), this.q.identity(), this.v2(1, 1, len));
        if (!skin.module.add(this.m)) break;
      }
    }
    for (const tu of w.tunnels) {
      if (tu.s - d > this.visibleAhead || tu.s + tu.length < d - behind) continue;
      const skin = this.tunnelSkin(biomeAtS(tu.s));
      const rows = Math.max(1, Math.round(tu.length / TUNNEL_ROW));
      const step = tu.length / rows;
      for (let i = 0; i < rows; i++) {
        const s = tu.s + (i + 0.5) * step;
        if (s - d > this.visibleAhead + 3 || s < d - behind - 3) continue;
        this.m.compose(this.v.set(0, 0, -(s - d)), this.q.identity(), this.v2(1, 1, step / TUNNEL_ROW));
        skin.add(this.m, tu.id * 31 + i);
      }
    }
    for (const s of all) {
      if (s instanceof PartSet) s.end();
      else {
        s.module.end();
        s.end.end();
      }
    }
  }

  private readonly scaleV = new THREE.Vector3();
  private v2(x: number, y: number, z: number): THREE.Vector3 {
    return this.scaleV.set(x, y, z);
  }

  private place(x: number, y: number, z: number): THREE.Matrix4 {
    return this.m.compose(this.v.set(x, y, z), this.q.identity(), this.one);
  }

  private makeFallbackRail(glow: THREE.Material): Skin {
    const h = TUNING.rail.height;
    const ramp = TUNING.rail.ramp;
    const cable = new THREE.MeshStandardMaterial({ color: '#f2f2f5', roughness: 0.35, metalness: 0.05 });
    const metal = new THREE.MeshStandardMaterial({ color: '#3a3848', roughness: 0.4, metalness: 0.8 });
    // One metre of cable along -z, with a little stand.
    const tube = new THREE.CylinderGeometry(0.09, 0.09, 1, 12, 2, true).rotateX(Math.PI / 2).translate(0, h, -0.5);
    const seam = new THREE.BoxGeometry(0.03, 0.03, 1, 1, 1, 2).translate(0, h + 0.085, -0.5);
    const stand = new THREE.BoxGeometry(0.07, h, 0.07).translate(0, h / 2, -0.5);
    const module = [part(tube, cable), part(seam, glow), part(stand, metal)];
    // The sloped start: from the track up to rail height over `ramp`, plus a USB-C plug head.
    const slope = Math.hypot(ramp, h);
    const up = new THREE.CylinderGeometry(0.09, 0.09, slope, 12, 3, true).rotateX(Math.atan2(h, ramp) - Math.PI / 2).translate(0, h / 2, ramp / 2);
    const plug = new THREE.BoxGeometry(0.26, 0.12, 0.5, 1, 1, 2).translate(0, 0.06, ramp + 0.2);
    const end = [part(up, cable), part(plug, metal)];
    return { module: new PartSet(this.scene, this.bend, module, MAX_RAIL), end: new PartSet(this.scene, this.bend, end, 16) };
  }
}

/** A tunnel row: two walls of dark screens, a ceiling with light strips. */
function fallbackTunnelParts(glow: THREE.Material): KitPart[] {
  const c = TUNING.tunnel.ceiling;
  const dark = new THREE.MeshStandardMaterial({ color: '#100c18', roughness: 0.6, metalness: 0.3 });
  const L = TUNNEL_ROW;
  const wallL = new THREE.BoxGeometry(0.6, c + 1, L, 1, 1, 8).translate(-5.9, (c + 1) / 2 - 0.5, 0);
  const wallR = new THREE.BoxGeometry(0.6, c + 1, L, 1, 1, 8).translate(5.9, (c + 1) / 2 - 0.5, 0);
  const roof = new THREE.BoxGeometry(12.4, 0.6, L, 1, 1, 8).translate(0, c + 0.3, 0);
  const rib = new THREE.BoxGeometry(12.2, 0.5, 0.35).translate(0, c - 0.2, L / 2 - 0.2);
  const stripL = new THREE.BoxGeometry(0.08, 0.08, L - 0.3, 1, 1, 8).translate(-2.4, c - 0.05, 0);
  const stripR = new THREE.BoxGeometry(0.08, 0.08, L - 0.3, 1, 1, 8).translate(2.4, c - 0.05, 0);
  return [part(wallL, dark), part(wallR, dark), part(roof, dark), part(rib, dark), part(stripL, glow), part(stripR, glow)];
}
