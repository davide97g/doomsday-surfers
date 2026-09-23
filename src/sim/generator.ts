// Procedural track generator.
//
// The track is built from "chunks" laid out along the distance axis. Each chunk
// reserves a span of track, so chunks never overlap. This gives two guarantees
// the fairness check (scripts/check-generator.ts) verifies:
//   1. At every distance at least one lane is not blocked by a post.
//   2. Posts in the same chunk start together, so the free lane(s) only change
//      at chunk boundaries, with a speed-scaled gap to react.
//
// Later (day 2+) this is where "the Algorithm" plugs in: chunk weights and
// content types will be biased by what the player grabs.

import { Rng } from './rng';
import { TUNING, type Obstacle, type ObstacleKind, type Pickup, type Tuning } from './types';

type ChunkKind = 'barrierRow' | 'doubleBarrier' | 'postRow' | 'movingPost' | 'pickupRun';

export interface GenContext {
  speed: number;
  difficulty: number; // 0..1
}

export class Generator {
  cursor: number;
  private nextId = 1;
  private readonly rng: Rng;
  private readonly t: Tuning;

  constructor(seed: number, t: Tuning = TUNING) {
    this.rng = new Rng(seed);
    this.t = t;
    this.cursor = t.spawn.safeStart;
  }

  fill(untilS: number, ctx: GenContext, obstacles: Obstacle[], pickups: Pickup[]): void {
    while (this.cursor < untilS) {
      this.chunk(ctx, obstacles, pickups);
    }
  }

  private gap(ctx: GenContext): number {
    const { gapSecondsMax, gapSecondsMin } = this.t.spawn;
    const secs = gapSecondsMax + (gapSecondsMin - gapSecondsMax) * ctx.difficulty;
    return ctx.speed * secs * this.rng.range(0.85, 1.15);
  }

  private obstacle(kind: ObstacleKind, lane: number, s: number, length = 0, speed = 0): Obstacle {
    return { id: this.nextId++, kind, lane, s, length, speed, active: false, variant: this.rng.int(0, 7) };
  }

  private pickupLine(pickups: Pickup[], lane: number, from: number, to: number, y = 0.9): void {
    const step = this.t.pickup.spacing;
    for (let s = from; s <= to; s += step) {
      pickups.push({ id: this.nextId++, lane, s, y, taken: false, variant: this.rng.int(0, 3) });
    }
  }

  private chunk(ctx: GenContext, obstacles: Obstacle[], pickups: Pickup[]): void {
    const d = ctx.difficulty;
    const weights: Record<ChunkKind, number> = {
      barrierRow: 0.34,
      doubleBarrier: d > 0.25 ? 0.12 * d : 0,
      postRow: 0.34,
      movingPost: d >= this.t.movingPost.minDifficulty ? 0.06 + 0.12 * d : 0,
      pickupRun: 0.16,
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
      case 'pickupRun': {
        const lane = this.rng.int(0, lanes - 1);
        const n = this.rng.int(6, 10);
        const end = s + n * this.t.pickup.spacing;
        this.pickupLine(pickups, lane, s, end);
        this.cursor = end + this.gap(ctx) * 0.5;
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
