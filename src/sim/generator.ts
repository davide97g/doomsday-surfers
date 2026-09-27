// Procedural track generator.
//
// The track is built from "chunks" laid out along the distance axis. Each chunk
// reserves a span of track, so chunks never overlap. This gives two guarantees
// the fairness check (scripts/check-generator.ts) verifies:
//   1. At every distance at least one lane is not blocked by a post.
//   2. Posts in the same chunk start together, so the free lane(s) only change
//      at chunk boundaries, with a speed-scaled gap to react.
//
// Healthy habits get their own chunks, so they never sit in the only lane a
// post row leaves free. Each pickup line is one content type; parallel lines of
// different types make tolerance a lane choice.
//
// Checkpoint gates get an empty stretch (gate.clearBefore .. gate.clearAfter),
// and so do the course's thrill rides (loops, corkscrews, drops, airtime
// hills). A chunk that would reach into one is thrown away and the cursor
// jumps past it; loops and corkscrews get a pickup line to ride through.
// Past each gate the new zone leans on its favourite content type.
//
// Pad chunks (ramp, bouncer, autoplay) reserve their whole flight, at well
// above the current speed, so a boosted launch still lands on empty track.
//
// The second level: a roof run is a reel train with stairs up to its roof and
// one or two more trains after it, with jumpable gaps (short enough that a
// runner who walks off one roof still catches the next one's edge). Followers
// stay in their lane or step toward the middle, and one lane is never used, so
// a runner on the ground always has a free lane next to them. A grind rail
// runs along one lane (the fast lane). An overhang spans every lane: roll.
// Tunnels are an overlay on a stretch of chunks (more posts and overhangs, no
// bouncers, thumbs or jetpacks inside).
//
// Power-ups come every power.gapMin..gapMax metres at the end of a pickup line.
// Going Viral only goes where its whole flight misses gates, loops and
// corkscrews, and no tunnel starts under it.
//
// Each zone is a biome (zone % 5) that leans on some chunk kinds
// (biomes.weights).

import type { Course } from './course';
import { Rng } from './rng';
import { setPieceFor } from './setpiece';
import {
  TUNING,
  gateS,
  zoneLook,
  type Obstacle,
  type ObstacleKind,
  type Pad,
  type PadKind,
  type Pickup,
  type PowerKind,
  type PowerUp,
  type Rail,
  type Tunnel,
  type Tuning,
} from './types';

/** Habit rows start their pickup line this far before the habit. */
const HABIT_LEAD = 8;

type ChunkKind = 'barrierRow' | 'doubleBarrier' | 'postRow' | 'movingPost' | 'pickupRun' | 'habitRow' | 'thumb' | 'roofRun' | 'rail' | 'overhang' | PadKind;

/** Everything the generator adds to the world. */
export interface Spawn {
  obstacles: Obstacle[];
  pickups: Pickup[];
  pads: Pad[];
  powerUps: PowerUp[];
  rails: Rail[];
  tunnels: Tunnel[];
}

type Marks = Record<keyof Spawn, number>;

interface Zone {
  from: number;
  to: number;
  /** Where a ride-through pickup line goes (loops and corkscrews), if any. */
  ride: [number, number] | null;
}

export interface GenContext {
  speed: number;
  difficulty: number; // 0..1
}

/** Ids are unique across generators (not per run), so after a reset the renderer
 *  never mistakes a new obstacle for an old one it is still showing. */
let nextId = 1;

export function newId(): number {
  return nextId++;
}

export class Generator {
  cursor: number;
  /** Gates the cursor has passed, i.e. the zone chunks are being built for. */
  private gate = 0;
  private readonly rng: Rng;
  private readonly t: Tuning;
  private out: Spawn = { obstacles: [], pickups: [], pads: [], powerUps: [], rails: [], tunnels: [] };
  /** Track distance of the next forced power-up. */
  private nextPower: number;
  /** End of the tunnel the cursor is in (or last was in). */
  private tunnelEnd = -Infinity;
  /** No tunnel may start before this (a Going Viral flight is over it). */
  private noTunnelUntil = -Infinity;
  /** Where the last roof or rail ended: overhangs keep their distance. */
  private supportEnd = -Infinity;

  /** `origin` is where the run starts (0, or later for a dev start in another zone). */
  constructor(
    private readonly seed: number,
    private readonly course: Course,
    t: Tuning = TUNING,
    origin = 0,
  ) {
    this.rng = new Rng(seed);
    this.t = t;
    this.cursor = origin + t.spawn.safeStart;
    this.nextPower = origin + t.power.first;
  }

  fill(untilS: number, ctx: GenContext, out: Spawn): void {
    this.out = out;
    while (this.cursor < untilS) {
      this.gate = this.gatesBefore(this.cursor);
      const zone = this.nextZone(this.cursor);
      if (this.cursor >= zone.from) {
        this.skip(zone);
        continue;
      }
      const marks = mark(out);
      const state = [this.tunnelEnd, this.noTunnelUntil, this.supportEnd, this.nextPower] as const;
      this.maybeTunnel(zone.from);
      if (this.cursor >= this.nextPower) this.powerChunk(ctx);
      else this.chunk(ctx);
      if (reach(out, marks) > zone.from) {
        rollback(out, marks);
        [this.tunnelEnd, this.noTunnelUntil, this.supportEnd, this.nextPower] = state;
        this.skip(zone);
      }
    }
  }

  /** This zone's biome weight for a chunk kind (1 if the biome doesn't lean on it). */
  private biome(kind: string): number {
    const w = (this.t.biomes.weights as Record<string, number[]>)[kind];
    return w ? (w[zoneLook(this.gate, this.t)] ?? 1) : 1;
  }

  private get inTunnel(): boolean {
    return this.cursor < this.tunnelEnd;
  }

  /** Maybe start a tunnel over the next stretch (never into a gate's or a thrill ride's). */
  private maybeTunnel(until: number): void {
    if (this.inTunnel || this.cursor < this.noTunnelUntil) return;
    const tu = this.t.tunnel;
    if (!this.rng.chance(tu.weight * this.biome('tunnel'))) return;
    const length = Math.min(this.rng.range(tu.lengthMin, tu.lengthMax), until - tu.margin - this.cursor);
    if (length < tu.lengthMin) return;
    this.out.tunnels.push({ id: nextId++, s: this.cursor, length });
    this.tunnelEnd = this.cursor + length;
  }

  /** Post lengths come in whole train modules. */
  private postLength(min: number, max: number): number {
    const m = this.t.roof.module;
    return m * Math.round(this.rng.range(min, max) / m);
  }

  /** Gates strictly behind `s` (the zone index chunks at `s` belong to). */
  private gatesBefore(s: number): number {
    let k = 0;
    while (gateS(k, this.t) < s) k++;
    return k;
  }

  /** The next stretch that must stay empty: a gate's or a thrill ride's. */
  private nextZone(s: number): Zone {
    const g = this.t.gate;
    let k = 0;
    while (gateS(k, this.t) + g.clearAfter <= s) k++;
    const gate: Zone = { from: gateS(k, this.t) - g.clearBefore, to: gateS(k, this.t) + g.clearAfter, ride: null };
    const c = this.course.nextClear(s);
    if (!c || c.from >= gate.from) return gate;
    const rides = c.seg.kind === 'loop' || c.seg.kind === 'corkscrew';
    return { from: c.from, to: c.to, ride: rides ? [c.seg.s0 + 2, c.seg.s1 - 2] : null };
  }

  private skip(zone: Zone): void {
    if (zone.ride && this.cursor < zone.ride[0]) this.pickupLine(this.rng.int(0, this.t.lanes.count - 1), zone.ride[0], zone.ride[1]);
    // Leave room for chunks that reach back behind the cursor (habit rows).
    this.cursor = Math.max(this.cursor, zone.to + HABIT_LEAD);
  }

  private gap(ctx: GenContext): number {
    const { gapSecondsMax, gapSecondsMin } = this.t.spawn;
    const secs = gapSecondsMax + (gapSecondsMin - gapSecondsMax) * ctx.difficulty;
    return ctx.speed * secs * this.rng.range(0.85, 1.15);
  }

  private obstacle(kind: ObstacleKind, lane: number, s: number, length = 0, speed = 0): Obstacle {
    return { id: nextId++, kind, lane, s, length, speed, active: false, variant: this.rng.int(0, 7), hit: false, age: 0, ramp: 0, wide: false };
  }

  private contentType(): number {
    const g = this.t.gate;
    const favour = g.zoneFavour[zoneLook(this.gate, this.t)];
    if (favour >= 0 && this.rng.chance(g.favourChance)) return favour;
    return this.rng.int(0, this.t.content.types - 1);
  }

  private pickupLine(lane: number, from: number, to: number, type = this.contentType(), y = 0.9): void {
    const step = this.t.pickup.spacing;
    for (let s = from; s <= to; s += step) this.pickup(lane, s, y, type);
  }

  private pickup(lane: number, s: number, y: number, type: number): void {
    this.out.pickups.push({ id: nextId++, lane, s, y, taken: false, type, pullAt: -1 });
  }

  /** Whether a Going Viral flight taken at `s` would miss every gate, loop, corkscrew and tunnel. */
  private viralFits(s: number): boolean {
    const v = this.t.power.viral;
    const g = this.t.gate;
    const from = s - 5;
    const to = s + v.distance + v.margin;
    for (let k = 0; gateS(k, this.t) - g.clearBefore < to; k++) {
      if (gateS(k, this.t) + g.clearAfter > from) return false;
    }
    const m = this.t.course.sceneryMargin;
    if (this.course.touches(from - m, to + m, ['loop', 'corkscrew'])) return false;
    return !this.out.tunnels.some((tu) => tu.s < to && tu.s + tu.length > from);
  }

  /** A short pickup line leading to a power-up. */
  private powerChunk(ctx: GenContext): void {
    const pw = this.t.power;
    const s = this.cursor;
    const lane = this.rng.int(0, this.t.lanes.count - 1);
    const n = this.rng.int(4, 6);
    const at = s + (n + 1) * this.t.pickup.spacing;
    const weights: Record<PowerKind, number> = { ...pw.weights };
    if (this.inTunnel) {
      weights.viral = 0;
      weights.kicks = 0;
    }
    if (weights.viral > 0 && !this.viralFits(at)) weights.viral = 0;
    const kind = this.rng.weighted(weights);
    this.pickupLine(lane, s, s + n * this.t.pickup.spacing);
    this.out.powerUps.push({ id: nextId++, kind, lane, s: at, y: 0.9, taken: false, seed: this.rng.int(1, 0x7fffffff) });
    if (kind === 'viral') this.noTunnelUntil = at + pw.viral.distance + pw.viral.margin;
    this.nextPower = at + this.rng.range(pw.gapMin, pw.gapMax);
    this.cursor = at + this.gap(ctx) * 0.6;
  }

  private chunk(ctx: GenContext): void {
    const { obstacles } = this.out;
    const d = ctx.difficulty;
    // The zone's set piece: the Thumb adds thumb drops, the Algorithm feeds you more content.
    const piece = setPieceFor(this.gate, this.seed);
    const sp = this.t.setPieces;
    const tunnel = this.inTunnel;
    const weights: Record<ChunkKind, number> = {
      barrierRow: 0.34,
      doubleBarrier: d > 0.25 ? 0.12 * d : 0,
      postRow: 0.34 * (tunnel ? 1.3 : 1),
      movingPost: d >= this.t.movingPost.minDifficulty ? 0.06 + 0.12 * d : 0,
      pickupRun: 0.16 + (piece === 'algorithm' ? sp.algorithm.pickupBoost : 0),
      thumb: piece === 'thumb' && !tunnel ? sp.thumb.weight : 0,
      habitRow: this.t.habit.weight + this.t.habit.weightByDifficulty * d,
      roofRun: d >= this.t.roof.minDifficulty ? this.t.roof.weight * this.biome('roofRun') : 0,
      rail: this.t.rail.weight * this.biome('rail'),
      overhang: d >= this.t.overhang.minDifficulty ? this.t.overhang.weight * this.biome('overhang') * (tunnel ? 2 : 1) : 0,
      ramp: this.t.pads.ramp.weight,
      bouncer: tunnel ? 0 : this.t.pads.bouncer.weight * this.biome('bouncer'),
      autoplay: this.t.pads.autoplay.weight * this.biome('autoplay'),
    };
    const kind = this.rng.weighted(weights);
    const lanes = this.t.lanes.count;
    const s = this.cursor;

    switch (kind) {
      case 'barrierRow': {
        this.barrierRow(s, d, obstacles);
        this.cursor = s + this.gap(ctx);
        break;
      }
      case 'doubleBarrier': {
        // Low then high (or vice versa) close together: jump, then roll.
        const second = s + ctx.speed * this.rng.range(0.55, 0.75);
        this.barrierRow(s, d, obstacles);
        this.barrierRow(second, d, obstacles);
        this.cursor = second + this.gap(ctx);
        break;
      }
      case 'postRow': {
        const len = this.postLength(this.t.post.minLength, this.t.post.maxLength);
        const nPosts = this.rng.chance(0.4 + 0.35 * d) ? 2 : 1;
        const order = shuffle(range(lanes), this.rng);
        const postLanes = order.slice(0, nPosts);
        const freeLanes = order.slice(nPosts);
        for (const lane of postLanes) obstacles.push(this.obstacle('post', lane, s, len));
        if (nPosts === 2 && this.rng.chance(0.35 + 0.3 * d)) {
          // Force a jump/roll inside the only free corridor.
          const kind: ObstacleKind = this.rng.chance(0.5) ? 'low' : 'high';
          obstacles.push(this.obstacle(kind, freeLanes[0], s + len * this.rng.range(0.35, 0.65)));
        } else {
          this.pickupLine(this.rng.pick(freeLanes), s, s + len);
        }
        this.supportEnd = s + len;
        this.cursor = s + len + this.gap(ctx);
        break;
      }
      case 'movingPost': {
        // Reserve the trigger distance in front of it so nothing else can be
        // placed where the player and the oncoming post meet.
        const { trigger, length, speed } = this.t.movingPost;
        const lane = this.rng.int(0, lanes - 1);
        const s0 = s + trigger;
        obstacles.push(this.obstacle('movingPost', lane, s0, length, speed));
        const other = shuffle(range(lanes).filter((l) => l !== lane), this.rng)[0];
        this.pickupLine(other, s + 10, s0 + length);
        this.supportEnd = s0 + length;
        this.cursor = s0 + length + this.gap(ctx);
        break;
      }
      case 'thumb': {
        // Like a moving post: reserve the stretch where it drops, drags toward
        // you and lets go, with room for the fastest approach. One lane only.
        const th = this.t.setPieces.thumb;
        const lane = this.rng.int(0, lanes - 1);
        const s0 = s + ctx.speed * (th.lead + 0.6);
        obstacles.push(this.obstacle('thumb', lane, s0, th.length, th.speed));
        const other = shuffle(range(lanes).filter((l) => l !== lane), this.rng)[0];
        this.pickupLine(other, s + 10, s0 + th.length);
        this.cursor = s0 + th.length + this.gap(ctx);
        break;
      }
      case 'pickupRun': {
        const n = this.rng.int(6, 10);
        const end = s + n * this.t.pickup.spacing;
        const order = shuffle(range(lanes), this.rng);
        const first = this.contentType();
        this.pickupLine(order[0], s, end, first);
        if (this.rng.chance(0.5)) {
          // A second, different content type alongside: pick your fix.
          const second = (first + this.rng.int(1, this.t.content.types - 1)) % this.t.content.types;
          this.pickupLine(order[1], s, end, second);
        }
        this.cursor = end + this.gap(ctx) * 0.5;
        break;
      }
      case 'habitRow': {
        const n = this.rng.chance(0.25 + 0.4 * d) ? 2 : 1;
        const order = shuffle(range(lanes), this.rng);
        for (const lane of order.slice(0, n)) {
          const o = this.obstacle('habit', lane, s);
          o.variant = this.rng.int(0, this.t.habit.types - 1);
          obstacles.push(o);
        }
        if (this.rng.chance(0.6)) this.pickupLine(order[n], s - HABIT_LEAD, s + HABIT_LEAD);
        this.cursor = s + this.gap(ctx);
        break;
      }
      case 'ramp':
      case 'bouncer': {
        // Take it and you fly over the next stretch through an arc of content.
        const pd = this.t.pads;
        const lane = this.rng.int(0, lanes - 1);
        const len = pd[kind].length;
        this.out.pads.push({ id: nextId++, kind, lane, s, length: len, used: false });
        const g = this.t.jump.gravity;
        const vy = pd[kind].launch;
        const flight = (2 * vy) / g;
        const type = this.contentType();
        for (let tt = 0.12; tt < flight - 0.1; tt += this.t.pickup.spacing / ctx.speed) {
          const y = vy * tt - 0.5 * g * tt * tt;
          this.pickup(lane, s + ctx.speed * tt, y + 0.9, type);
        }
        // Skipping it is fine: a plain pickup line alongside.
        if (this.rng.chance(0.5)) {
          const other = (lane + this.rng.int(1, lanes - 1)) % lanes;
          this.pickupLine(other, s, s + ctx.speed * flight * 0.6);
        }
        this.cursor = s + ctx.speed * flight * pd.flightMargin + this.gap(ctx);
        break;
      }
      case 'autoplay': {
        const a = this.t.pads.autoplay;
        const lane = this.rng.int(0, lanes - 1);
        this.out.pads.push({ id: nextId++, kind, lane, s, length: a.length, used: false });
        this.pickupLine(lane, s + a.length + 2, s + a.length + 2 + ctx.speed * a.time * a.speed * 0.8);
        this.cursor = s + a.length + ctx.speed * a.time * a.speed + this.gap(ctx) * a.speed;
        break;
      }
      case 'roofRun':
        this.roofRun(ctx);
        break;
      case 'rail': {
        // A grind rail down one lane (the fast lane); sometimes a train alongside.
        const rl = this.t.rail;
        const lane = this.rng.int(0, lanes - 1);
        const length = this.rng.range(rl.lengthMin, rl.lengthMax);
        const start = s + rl.ramp;
        this.out.rails.push({ id: nextId++, lane, s: start, length });
        this.pickupLine(lane, start + 2, start + length - 2, this.contentType(), rl.pickupY);
        if (this.rng.chance(0.5)) {
          const other = shuffle(range(lanes).filter((l) => l !== lane), this.rng)[0];
          const len = Math.min(this.postLength(this.t.post.minLength, this.t.post.maxLength), this.t.roof.module * Math.floor(length / this.t.roof.module));
          obstacles.push(this.obstacle('post', other, start + this.rng.range(0, Math.max(0, length - len)), len));
        }
        this.supportEnd = start + length;
        this.cursor = start + length + this.gap(ctx);
        break;
      }
      case 'overhang': {
        // Something fell across every lane: roll under it. Nothing else near it,
        // and far enough past any roof or rail to drop down and roll.
        const ov = this.t.overhang;
        const at = Math.max(s + ctx.speed * ov.approach, this.supportEnd + ctx.speed * ov.afterSupport);
        const variant = this.rng.int(0, 7);
        for (let lane = 0; lane < lanes; lane++) {
          const o = this.obstacle('high', lane, at);
          o.variant = variant;
          o.wide = true;
          obstacles.push(o);
        }
        this.pickupLine(this.rng.int(0, lanes - 1), at - 6, at + 6, this.contentType(), 0.5);
        this.cursor = at + 2 + this.gap(ctx);
        break;
      }
    }
  }

  /** Stairs up onto a reel train's roof, then one or two more trains to hop along. */
  private roofRun(ctx: GenContext): void {
    const r = this.t.roof;
    const lanes = this.t.lanes.count;
    const mid = (lanes - 1) / 2;
    const v = ctx.speed;
    const s = this.cursor;
    const type = this.contentType();
    let lane = this.rng.int(0, lanes - 1);
    const first = this.obstacle('post', lane, s + r.stairs, this.postLength(r.lengthMin, r.lengthMax));
    first.ramp = r.stairs;
    const posts = [first];
    const used = new Set([lane]);
    // Content up the stairs.
    for (let ss = s + 1; ss < first.s; ss += this.t.pickup.spacing) this.pickup(lane, ss, 0.9 + this.t.post.height * ((ss - s) / r.stairs), type);
    const followers = this.rng.int(1, 2);
    for (let i = 0; i < followers; i++) {
      const last = posts[posts.length - 1];
      const end = last.s + last.length;
      const toward = lane < mid ? 1 : lane > mid ? -1 : 0;
      const step = toward !== 0 && this.rng.chance(0.5) ? toward : 0;
      const len = this.postLength(r.lengthMin, r.lengthMax);
      let start: number;
      if (step !== 0 && this.rng.chance(0.5)) {
        // Side hop: the next roof starts alongside this one's end.
        start = Math.max(last.s + 2, end - this.rng.range(r.overlapMin, r.overlapMin + 4));
      } else {
        // A gap to jump. Short enough that walking off still catches the next edge.
        const gap = Math.min(v * r.gapSecMax, Math.max(r.gapMin, v * this.rng.range(r.gapSecMin, r.gapSecMax)));
        start = end + gap;
        // Content arcs over the gap.
        const top = this.t.post.height + 0.9;
        for (let k = 1; k <= 2; k++) this.pickup(lane + step, end + (gap * k) / 3, top + 0.7, type);
      }
      lane += step;
      used.add(lane);
      posts.push(this.obstacle('post', lane, start, len));
    }
    let end = 0;
    for (const o of posts) {
      this.out.obstacles.push(o);
      this.pickupLine(o.lane, o.s + 1, o.s + o.length - 1, type, r.trailY);
      end = Math.max(end, o.s + o.length);
    }
    // The lane no train uses: a plain line on the ground, sometimes.
    const free = range(lanes).filter((l) => !used.has(l));
    if (free.length > 0 && this.rng.chance(0.5)) this.pickupLine(this.rng.pick(free), s + 4, end - 4);
    this.supportEnd = end;
    this.cursor = end + v * 0.45 + this.gap(ctx);
  }

  private barrierRow(s: number, d: number, obstacles: Obstacle[]): void {
    const lanes = this.t.lanes.count;
    let placed = 0;
    const kinds: (ObstacleKind | null)[] = [];
    for (let lane = 0; lane < lanes; lane++) {
      const r = this.rng.next();
      const k: ObstacleKind | null = r < 0.36 ? 'low' : r < 0.62 + 0.1 * d ? 'high' : null;
      kinds.push(k);
      if (k) placed++;
    }
    if (placed === 0) kinds[this.rng.int(0, lanes - 1)] = this.rng.chance(0.5) ? 'low' : 'high';
    kinds.forEach((k, lane) => {
      if (k) obstacles.push(this.obstacle(k, lane, s));
    });
  }
}

function mark(out: Spawn): Marks {
  return {
    obstacles: out.obstacles.length,
    pickups: out.pickups.length,
    pads: out.pads.length,
    powerUps: out.powerUps.length,
    rails: out.rails.length,
    tunnels: out.tunnels.length,
  };
}

function rollback(out: Spawn, m: Marks): void {
  out.obstacles.length = m.obstacles;
  out.pickups.length = m.pickups;
  out.pads.length = m.pads;
  out.powerUps.length = m.powerUps;
  out.rails.length = m.rails;
  out.tunnels.length = m.tunnels;
}

/** Furthest track distance touched by anything added since the marks. */
function reach(out: Spawn, m: Marks): number {
  let max = -Infinity;
  for (let i = m.obstacles; i < out.obstacles.length; i++) max = Math.max(max, out.obstacles[i].s + out.obstacles[i].length);
  for (let i = m.pickups; i < out.pickups.length; i++) max = Math.max(max, out.pickups[i].s);
  for (let i = m.pads; i < out.pads.length; i++) max = Math.max(max, out.pads[i].s + out.pads[i].length);
  for (let i = m.powerUps; i < out.powerUps.length; i++) max = Math.max(max, out.powerUps[i].s);
  for (let i = m.rails; i < out.rails.length; i++) max = Math.max(max, out.rails[i].s + out.rails[i].length);
  for (let i = m.tunnels; i < out.tunnels.length; i++) max = Math.max(max, out.tunnels[i].s + out.tunnels[i].length);
  return max;
}

function range(n: number): number[] {
  return Array.from({ length: n }, (_, i) => i);
}

function shuffle<T>(arr: T[], rng: Rng): T[] {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(rng.next() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}
