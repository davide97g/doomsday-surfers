// The game simulation. Runs at a fixed timestep, knows nothing about rendering.
// Coordinates: `s` is distance along the track (forward = +s), `x` is lateral,
// `y` is height. The player sits at s = world.d.

import { Generator } from './generator';
import {
  TUNING,
  laneX,
  type Action,
  type Obstacle,
  type Phase,
  type Pickup,
  type PlayerState,
  type SimEvent,
  type Tuning,
} from './types';

interface Box {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
  s0: number;
  s1: number;
}

export class World {
  readonly t: Tuning;
  seed: number;
  phase: Phase = 'ready';
  /** Distance travelled (m). */
  d = 0;
  speed: number;
  time = 0;
  pickupsTaken = 0;
  obstacles: Obstacle[] = [];
  pickups: Pickup[] = [];
  player: PlayerState;
  events: SimEvent[] = [];
  private gen: Generator;

  constructor(seed = Date.now(), t: Tuning = TUNING) {
    this.t = t;
    this.seed = seed;
    this.speed = t.speed.start;
    this.player = World.freshPlayer(t);
    this.gen = new Generator(seed, t);
    this.gen.fill(t.spawn.ahead, { speed: this.speed, difficulty: 0 }, this.obstacles, this.pickups);
  }

  static freshPlayer(t: Tuning): PlayerState {
    const mid = Math.floor(t.lanes.count / 2);
    return { lane: mid, prevLane: mid, x: laneX(mid, t), y: 0, vy: 0, grounded: true, rollT: 0, rollQueued: false, stumbleT: 0 };
  }

  reset(seed = Date.now()): void {
    this.seed = seed;
    this.phase = 'ready';
    this.d = 0;
    this.time = 0;
    this.speed = this.t.speed.start;
    this.pickupsTaken = 0;
    this.obstacles = [];
    this.pickups = [];
    this.player = World.freshPlayer(this.t);
    this.gen = new Generator(seed, this.t);
    this.gen.fill(this.t.spawn.ahead, { speed: this.speed, difficulty: 0 }, this.obstacles, this.pickups);
  }

  get difficulty(): number {
    return Math.min(1, this.d / this.t.spawn.difficultyDistance);
  }

  get score(): number {
    return Math.floor(this.d) + this.pickupsTaken * this.t.pickup.value;
  }

  get rolling(): boolean {
    return this.player.rollT > 0;
  }

  step(dt: number, actions: readonly Action[]): void {
    if (this.phase === 'ready') {
      if (actions.length > 0) {
        this.phase = 'running';
        this.events.push({ type: 'start' });
      }
      return;
    }
    if (this.phase === 'dead') return;

    const t = this.t;
    const p = this.player;
    this.time += dt;
    this.speed = Math.min(t.speed.max, this.speed + t.speed.accel * dt);

    for (const a of actions) this.applyAction(a);

    // Lateral: move toward the target lane at constant rate.
    const targetX = laneX(p.lane, t);
    const rate = t.lanes.width / t.laneSwitchTime;
    const dx = targetX - p.x;
    p.x += Math.sign(dx) * Math.min(Math.abs(dx), rate * dt);

    // Vertical.
    if (!p.grounded) {
      p.vy -= t.jump.gravity * dt;
      p.y += p.vy * dt;
      if (p.y <= 0) {
        p.y = 0;
        p.vy = 0;
        p.grounded = true;
        this.events.push({ type: 'land' });
        if (p.rollQueued) {
          p.rollQueued = false;
          p.rollT = t.roll.duration;
          this.events.push({ type: 'roll' });
        }
      }
    }
    p.rollT = Math.max(0, p.rollT - dt);
    p.stumbleT = Math.max(0, p.stumbleT - dt);

    const prevBox = this.playerBox();
    this.d += this.speed * dt;

    for (const o of this.obstacles) {
      if (o.speed > 0) {
        if (!o.active && o.s - this.d < t.movingPost.trigger) o.active = true;
        if (o.active) o.s -= o.speed * dt;
      }
    }

    this.collide(prevBox);
    this.collect();

    this.gen.fill(this.d + t.spawn.ahead, { speed: this.speed, difficulty: this.difficulty }, this.obstacles, this.pickups);
    const behind = this.d - 20;
    this.obstacles = this.obstacles.filter((o) => o.s + o.length > behind);
    this.pickups = this.pickups.filter((pk) => !pk.taken && pk.s > behind);
  }

  private applyAction(a: Action): void {
    const t = this.t;
    const p = this.player;
    switch (a) {
      case 'left':
      case 'right': {
        const dir = a === 'left' ? -1 : 1;
        const next = p.lane + dir;
        if (next < 0 || next >= t.lanes.count) {
          this.events.push({ type: 'edge', dir });
          return;
        }
        p.prevLane = p.lane;
        p.lane = next;
        this.events.push({ type: 'lane', dir });
        return;
      }
      case 'up': {
        if (!p.grounded) return;
        p.grounded = false;
        p.vy = t.jump.velocity;
        p.rollT = 0;
        this.events.push({ type: 'jump' });
        return;
      }
      case 'down': {
        if (!p.grounded) {
          p.vy = Math.min(p.vy, -t.jump.fastFall);
          p.rollQueued = true;
          return;
        }
        p.rollT = t.roll.duration;
        this.events.push({ type: 'roll' });
        return;
      }
      case 'tap':
        return;
    }
  }

  playerBox(): Box {
    const t = this.t;
    const p = this.player;
    const h = p.rollT > 0 ? t.player.rollHeight : t.player.height;
    return {
      x0: p.x - t.player.halfWidth,
      x1: p.x + t.player.halfWidth,
      y0: p.y,
      y1: p.y + h,
      s0: this.d - t.player.halfDepth,
      s1: this.d + t.player.halfDepth,
    };
  }

  obstacleBox(o: Obstacle): Box {
    const t = this.t;
    const cx = laneX(o.lane, t);
    switch (o.kind) {
      case 'low':
        return { x0: cx - t.barrier.halfWidth, x1: cx + t.barrier.halfWidth, y0: 0, y1: t.barrier.lowTop, s0: o.s - t.barrier.halfDepth, s1: o.s + t.barrier.halfDepth };
      case 'high':
        return { x0: cx - t.barrier.halfWidth, x1: cx + t.barrier.halfWidth, y0: t.barrier.highBottom, y1: t.barrier.highTop, s0: o.s - t.barrier.halfDepth, s1: o.s + t.barrier.halfDepth };
      case 'post':
      case 'movingPost':
        return { x0: cx - t.post.halfWidth, x1: cx + t.post.halfWidth, y0: 0, y1: t.post.height, s0: o.s, s1: o.s + o.length };
    }
  }

  private collide(prev: Box): void {
    const pb = this.playerBox();
    for (const o of this.obstacles) {
      const ob = this.obstacleBox(o);
      if (!overlaps(pb, ob)) continue;

      const isPost = o.kind === 'post' || o.kind === 'movingPost';
      // Side hit: we were already alongside the post last tick, and only the
      // lateral axis started overlapping. That's a stumble, not a crash.
      const wasAlongside = prev.s1 > ob.s0 + 0.05 && prev.s0 < ob.s1;
      const xWasClear = prev.x1 <= ob.x0 || prev.x0 >= ob.x1;
      if (isPost && wasAlongside && xWasClear) {
        this.stumble();
        return;
      }
      this.phase = 'dead';
      this.events.push({ type: 'crash', kind: o.kind });
      return;
    }
  }

  private stumble(): void {
    const p = this.player;
    const t = this.t;
    const back = p.prevLane;
    p.prevLane = p.lane;
    p.lane = back;
    // Snap back just outside the post so we don't re-trigger next tick.
    const dir = Math.sign(laneX(back, t) - p.x);
    p.x += dir * 0.12;
    p.stumbleT = t.stumble.duration;
    this.events.push({ type: 'stumble' });
  }

  private collect(): void {
    const t = this.t;
    const p = this.player;
    const h = p.rollT > 0 ? t.player.rollHeight : t.player.height;
    const r = t.pickup.radius;
    for (const pk of this.pickups) {
      if (pk.taken) continue;
      if (Math.abs(pk.s - this.d) > r) continue;
      if (Math.abs(laneX(pk.lane, t) - p.x) > r + t.player.halfWidth) continue;
      if (pk.y + r < p.y || pk.y - r > p.y + h) continue;
      pk.taken = true;
      this.pickupsTaken++;
      this.events.push({ type: 'pickup', id: pk.id });
    }
  }

  drainEvents(): SimEvent[] {
    const e = this.events;
    this.events = [];
    return e;
  }
}

function overlaps(a: Box, b: Box): boolean {
  return a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0 && a.s0 < b.s1 && a.s1 > b.s0;
}
