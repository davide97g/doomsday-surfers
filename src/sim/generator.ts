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
// Later this is where "the Algorithm" plugs in: chunk weights and content
// types will be biased by what the player grabs.

import type { Course } from './course';
import { Rng } from './rng';
import { setPieceFor } from './setpiece';
import { TUNING, gateS, zoneLook, type Obstacle, type ObstacleKind, type Pad, type PadKind, type Pickup, type Tuning } from './types';

/** Habit rows start their pickup line this far before the habit. */
const HABIT_LEAD = 8;

type ChunkKind = 'barrierRow' | 'doubleBarrier' | 'postRow' | 'movingPost' | 'pickupRun' | 'habitRow' | 'thumb' | PadKind;

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

export class Generator {
  cursor: number;
  /** Gates the cursor has passed, i.e. the zone chunks are being built for. */
  private gate = 0;
  private readonly rng: Rng;
  private readonly t: Tuning;
  private pads: Pad[] = [];

  constructor(
    private readonly seed: number,
    private readonly course: Course,
    t: Tuning = TUNING,
  ) {
    this.rng = new Rng(seed);
    this.t = t;
    this.cursor = t.spawn.safeStart;
  }

  fill(untilS: number, ctx: GenContext, obstacles: Obstacle[], pickups: Pickup[], pads: Pad[]): void {
    this.pads = pads;
    while (this.cursor < untilS) {
      this.gate = this.gatesBefore(this.cursor);
      const zone = this.nextZone(this.cursor);
      if (this.cursor >= zone.from) {
        this.skip(zone, pickups);
        continue;
      }
      const o0 = obstacles.length;
      const p0 = pickups.length;
      const d0 = pads.length;
      this.chunk(ctx, obstacles, pickups);
      if (reach(obstacles, o0, pickups, p0, pads, d0) > zone.from) {
        obstacles.length = o0;
        pickups.length = p0;
        pads.length = d0;
        this.skip(zone, pickups);
      }
    }
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

  private skip(zone: Zone, pickups: Pickup[]): void {
    if (zone.ride && this.cursor < zone.ride[0]) this.pickupLine(pickups, this.rng.int(0, this.t.lanes.count - 1), zone.ride[0], zone.ride[1]);
    // Leave room for chunks that reach back behind the cursor (habit rows).
    this.cursor = Math.max(this.cursor, zone.to + HABIT_LEAD);
  }

  private gap(ctx: GenContext): number {
    const { gapSecondsMax, gapSecondsMin } = this.t.spawn;
    const secs = gapSecondsMax + (gapSecondsMin - gapSecondsMax) * ctx.difficulty;
    return ctx.speed * secs * this.rng.range(0.85, 1.15);
  }

  private obstacle(kind: ObstacleKind, lane: number, s: number, length = 0, speed = 0): Obstacle {
    return { id: nextId++, kind, lane, s, length, speed, active: false, variant: this.rng.int(0, 7), hit: false, age: 0 };
  }

  private contentType(): number {
    const g = this.t.gate;
    const favour = g.zoneFavour[zoneLook(this.gate, this.t)];
    if (favour >= 0 && this.rng.chance(g.favourChance)) return favour;
    return this.rng.int(0, this.t.content.types - 1);
  }

  private pickupLine(pickups: Pickup[], lane: number, from: number, to: number, type = this.contentType(), y = 0.9): void {
    const step = this.t.pickup.spacing;
    for (let s = from; s <= to; s += step) {
      pickups.push({ id: nextId++, lane, s, y, taken: false, type });
    }
  }

  private chunk(ctx: GenContext, obstacles: Obstacle[], pickups: Pickup[]): void {
    const d = ctx.difficulty;
    // The zone's set piece: the Thumb adds thumb drops, the Algorithm feeds you more content.
    const piece = setPieceFor(this.gate, this.seed);
    const sp = this.t.setPieces;
    const weights: Record<ChunkKind, number> = {
      barrierRow: 0.34,
      doubleBarrier: d > 0.25 ? 0.12 * d : 0,
      postRow: 0.34,
      movingPost: d >= this.t.movingPost.minDifficulty ? 0.06 + 0.12 * d : 0,
      pickupRun: 0.16 + (piece === 'algorithm' ? sp.algorithm.pickupBoost : 0),
      thumb: piece === 'thumb' ? sp.thumb.weight : 0,
      habitRow: this.t.habit.weight + this.t.habit.weightByDifficulty * d,
      ramp: this.t.pads.ramp.weight,
      bouncer: this.t.pads.bouncer.weight,
      autoplay: this.t.pads.autoplay.weight,
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
        const len = this.rng.range(this.t.post.minLength, this.t.post.maxLength);
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
          this.pickupLine(pickups, this.rng.pick(freeLanes), s, s + len);
        }
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
        this.pickupLine(pickups, other, s + 10, s0 + length);
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
        this.pickupLine(pickups, other, s + 10, s0 + th.length);
        this.cursor = s0 + th.length + this.gap(ctx);
        break;
      }
      case 'pickupRun': {
        const n = this.rng.int(6, 10);
        const end = s + n * this.t.pickup.spacing;
        const order = shuffle(range(lanes), this.rng);
        const first = this.contentType();
        this.pickupLine(pickups, order[0], s, end, first);
        if (this.rng.chance(0.5)) {
          // A second, different content type alongside: pick your fix.
          const second = (first + this.rng.int(1, this.t.content.types - 1)) % this.t.content.types;
          this.pickupLine(pickups, order[1], s, end, second);
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
        if (this.rng.chance(0.6)) this.pickupLine(pickups, order[n], s - HABIT_LEAD, s + HABIT_LEAD);
        this.cursor = s + this.gap(ctx);
        break;
      }
      case 'ramp':
      case 'bouncer': {
        // Take it and you fly over the next stretch through an arc of content.
        const pd = this.t.pads;
        const lane = this.rng.int(0, lanes - 1);
        const len = pd[kind].length;
        this.pads.push({ id: nextId++, kind, lane, s, length: len, used: false });
        const g = this.t.jump.gravity;
        const vy = pd[kind].launch;
        const flight = (2 * vy) / g;
        const type = this.contentType();
        for (let tt = 0.12; tt < flight - 0.1; tt += this.t.pickup.spacing / ctx.speed) {
          const y = vy * tt - 0.5 * g * tt * tt;
          pickups.push({ id: nextId++, lane, s: s + ctx.speed * tt, y: y + 0.9, taken: false, type });
        }
        // Skipping it is fine: a plain pickup line alongside.
        if (this.rng.chance(0.5)) {
          const other = (lane + this.rng.int(1, lanes - 1)) % lanes;
          this.pickupLine(pickups, other, s, s + ctx.speed * flight * 0.6);
        }
        this.cursor = s + ctx.speed * flight * pd.flightMargin + this.gap(ctx);
        break;
      }
      case 'autoplay': {
        const a = this.t.pads.autoplay;
        const lane = this.rng.int(0, lanes - 1);
        this.pads.push({ id: nextId++, kind, lane, s, length: a.length, used: false });
        this.pickupLine(pickups, lane, s + a.length + 2, s + a.length + 2 + ctx.speed * a.time * a.speed * 0.8);
        this.cursor = s + a.length + ctx.speed * a.time * a.speed + this.gap(ctx) * a.speed;
        break;
      }
    }
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

/** Furthest track distance touched by the obstacles/pickups/pads added since o0/p0/d0. */
function reach(obstacles: Obstacle[], o0: number, pickups: Pickup[], p0: number, pads: Pad[], d0: number): number {
  let max = -Infinity;
  for (let i = o0; i < obstacles.length; i++) max = Math.max(max, obstacles[i].s + obstacles[i].length);
  for (let i = p0; i < pickups.length; i++) max = Math.max(max, pickups[i].s);
  for (let i = d0; i < pads.length; i++) max = Math.max(max, pads[i].s + pads[i].length);
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
