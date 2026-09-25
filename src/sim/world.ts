// The game simulation. Runs at a fixed timestep, knows nothing about rendering.
// Coordinates: `s` is distance along the track (forward = +s), `x` is lateral,
// `y` is height. The player sits at s = world.d.
//
// Dopamine never drains on its own: only healthy habits take it away (and slow
// you down). Content pickups refill it, but each content type gives less every
// time you take it (tolerance, never recovers within a run). Push notifications
// (driven by the UI) bump it when they land; opening one gives a big hit with its
// own tolerance plus a super boost: faster, and you smash through everything.
// At zero, or on a crash, the run enters `fading`: you slow to a stop in grey
// reality, then `dead`.
//
// Each character has a signature craving: its favourite content type gives
// more (characters.cravingGain) but builds tolerance faster (cravingDecay).
// A character with no favourite (-1) has a habit perk instead (habitCost).
//
// Checkpoint gates sit at fixed distances (gateS). Crossing one starts a
// bullet-time scan (`gateT` counts real seconds): the sim runs slowed by
// `timeScale`, input is ignored, and the feed moves to the
// next zone. The generator keeps the stretch around each gate empty.
//
// The track is a rollercoaster (see Course): downhill builds a speed rush,
// crests make you float and the steep ones throw you into the air, and loops,
// corkscrews, drops and big air give a thrill: a dopamine hit with its own
// tolerance, shared by every kind of thrill. Pads on the track launch you
// (ramps, bouncers) or give a short speed burst (autoplay strips).

import { Course } from './course';
import { Generator } from './generator';
import { setPieceFor, type SetPiece } from './setpiece';
import {
  TUNING,
  gateS,
  laneX,
  type Action,
  type DeathCause,
  type Obstacle,
  type ObstacleKind,
  type Pad,
  type Phase,
  type Pickup,
  type PlayerState,
  type SimEvent,
  type ThrillKind,
  type Tuning,
} from './types';

/** Habit type index of "Mum calling" (content.json habits[3]). */
const MUM = 3;

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
  /** Base forward speed; the actual speed also includes habit slow-down (see runSpeed). */
  speed: number;
  time = 0;
  pickupsTaken = 0;
  habitsHit = 0;
  // Run stats for the end-of-run report.
  takenByType: number[];
  habitsDodged = 0;
  mumIgnored = 0;
  adsPassed = 0;
  notificationsOpened = 0;
  smashed = 0;
  thrills = 0;
  revivesLeft: number;
  dopamine: number;
  /** Per content type multiplier on gain, 1 = fresh. */
  tolerance: number[];
  /** Multiplier on an opened notification's gain, 1 = fresh. */
  notifyTolerance = 1;
  /** Work mode app windows open on screen (reported by the UI); each drips dopamine. */
  openWindows = 0;
  /** Multiplier on the window trickle, 1 = fresh; drops with every window opened. */
  windowTolerance = 1;
  /** Seconds left of the notification super boost. */
  boostT = 0;
  /** Seconds left of the habit slow-down. */
  slowT = 0;
  /** Extra speed fraction built up going downhill (negative uphill). */
  rush = 0;
  /** Seconds left of an autoplay strip's speed burst. */
  autoplayT = 0;
  /** Seconds in the air so far this hop. */
  airT = 0;
  /** Multiplier on thrill gains, 1 = fresh. */
  thrillTolerance = 1;
  cause: DeathCause | null = null;
  /** What you crashed into (cause 'crash'). */
  crashKind: ObstacleKind | null = null;
  /** Habit type of the last healthy habit walked into, -1 if none (the usual killer on 'empty'). */
  lastHabit = -1;
  /** Doomscroll flicks: quick repeated swipes up build a combo (speed + dopamine, own tolerance). */
  combo = 0;
  scrolls = 0;
  scrollTolerance = 1;
  private lastUp = -1;
  private scrollT = 0;
  /** Algorithm zone: seconds the eye stays turned away after you hit a habit. */
  sulkT = 0;
  /** Average dopamine over each `daily.sampleEvery` s of sim time (the Daily's share grid). */
  history: number[] = [];
  private sampleSum = 0;
  private sampleT = 0;
  /** Seconds into the fade to reality. */
  fadeT = 0;
  /** Selected character (index into tuning characters / content characters). */
  character = 0;
  /** Feed zone: goes up by one per gate crossed. */
  zone = 0;
  /** Index of the next gate ahead. */
  nextGate = 0;
  /** Real seconds into the current gate scan, -1 when not scanning. */
  gateT = -1;
  obstacles: Obstacle[] = [];
  pickups: Pickup[] = [];
  pads: Pad[] = [];
  course: Course;
  player: PlayerState;
  events: SimEvent[] = [];
  private gen: Generator;
  private fadeFrom = 0;

  constructor(seed = Date.now(), t: Tuning = TUNING) {
    this.t = t;
    this.seed = seed;
    this.speed = t.speed.start;
    this.dopamine = t.dopamine.start;
    this.tolerance = new Array(t.content.types).fill(1);
    this.takenByType = new Array(t.content.types).fill(0);
    this.revivesLeft = t.revive.perRun;
    this.player = World.freshPlayer(t);
    this.course = new Course(seed, t);
    this.gen = new Generator(seed, this.course, t);
    this.gen.fill(t.spawn.ahead, { speed: this.speed, difficulty: 0 }, this.obstacles, this.pickups, this.pads);
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
    this.habitsHit = 0;
    this.takenByType.fill(0);
    this.habitsDodged = 0;
    this.mumIgnored = 0;
    this.adsPassed = 0;
    this.notificationsOpened = 0;
    this.smashed = 0;
    this.thrills = 0;
    this.thrillTolerance = 1;
    this.rush = 0;
    this.autoplayT = 0;
    this.airT = 0;
    this.notifyTolerance = 1;
    this.openWindows = 0;
    this.windowTolerance = 1;
    this.boostT = 0;
    this.revivesLeft = this.t.revive.perRun;
    this.dopamine = this.t.dopamine.start;
    this.tolerance.fill(1);
    this.slowT = 0;
    this.cause = null;
    this.crashKind = null;
    this.lastHabit = -1;
    this.history = [];
    this.sulkT = 0;
    this.combo = 0;
    this.scrolls = 0;
    this.scrollTolerance = 1;
    this.lastUp = -1;
    this.scrollT = 0;
    this.sampleSum = 0;
    this.sampleT = 0;
    this.fadeT = 0;
    this.zone = 0;
    this.nextGate = 0;
    this.gateT = -1;
    this.obstacles = [];
    this.pickups = [];
    this.pads = [];
    this.player = World.freshPlayer(this.t);
    this.course = new Course(seed, this.t);
    this.gen = new Generator(seed, this.course, this.t);
    this.gen.fill(this.t.spawn.ahead, { speed: this.speed, difficulty: 0 }, this.obstacles, this.pickups, this.pads);
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

  /** 0..1 strength of the super boost (eases out over its last boostRamp seconds). */
  get boost(): number {
    return Math.min(1, this.boostT / this.t.notify.boostRamp);
  }

  /** Forward speed actually applied this tick (m/s). */
  get runSpeed(): number {
    if (this.phase === 'fading') {
      const k = Math.min(1, this.fadeT / this.t.reality.fadeTime);
      return this.fadeFrom * (1 - k) * (1 - k);
    }
    if (this.phase !== 'running') return 0;
    const h = this.t.habit;
    const slow = this.slowT > 0 ? 1 - (1 - h.slowFactor) * (this.slowT / h.slowTime) : 1;
    const a = this.t.pads.autoplay;
    const autoplay = 1 + (a.speed - 1) * Math.min(1, this.autoplayT / a.ramp);
    const sc = this.t.scroll;
    const scroll = 1 + sc.speedPerCombo * this.combo * Math.min(1, this.scrollT / sc.burst);
    return this.speed * slow * (1 + this.rush) * autoplay * scroll * (1 + (this.t.notify.boostSpeed - 1) * this.boost);
  }

  /** Sim speed multiplier: dips to gate.timeScale during a gate scan. */
  get timeScale(): number {
    if (this.gateT < 0) return 1;
    const g = this.t.gate;
    const k = Math.min(smooth(this.gateT / g.easeIn), smooth((g.duration - this.gateT) / g.easeOut));
    return 1 + (g.timeScale - 1) * k;
  }

  /** The selected character's favourite content type, -1 for none. */
  get favourite(): number {
    return this.t.characters.favourite[this.character];
  }

  /** Pick a character. Only on the title screen: a run keeps who it started with. */
  setCharacter(i: number): void {
    if (this.phase === 'ready') this.character = i;
  }

  /** Gain the next pickup of this content type would give. */
  /** The current zone's set piece (null before the first gate). */
  get setPiece(): SetPiece | null {
    return setPieceFor(this.zone, this.seed);
  }

  /** Algorithm zone, and the eye is on you: content hits harder. */
  get watching(): boolean {
    return this.sulkT <= 0 && this.setPiece === 'algorithm';
  }

  gainFor(type: number): number {
    const craving = type === this.favourite ? this.t.characters.cravingGain : 1;
    const watched = this.watching ? 1 + this.t.setPieces.algorithm.bonus : 1;
    return this.t.content.gain * this.tolerance[type] * craving * watched;
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
    if (this.phase === 'fading') {
      this.stepFade(dt);
      return;
    }

    const t = this.t;
    if (this.gateT >= 0) {
      // The scan holds you: swipes are dropped until it lets go.
      actions = [];
      this.gateT += dt;
      if (this.gateT >= t.gate.duration) this.endGate();
    }
    // Everything below runs on sim time, which a gate scan slows down.
    dt *= this.timeScale;
    this.time += dt;
    this.sample(dt);
    this.speed = Math.min(t.speed.max, this.speed + t.speed.accel * dt);

    for (const a of actions) this.applyAction(a);
    this.movePlayer(dt);

    const prevBox = this.playerBox();
    const prevD = this.d;
    this.d += this.runSpeed * dt;
    this.slowT = Math.max(0, this.slowT - dt);
    this.boostT = Math.max(0, this.boostT - dt);
    this.autoplayT = Math.max(0, this.autoplayT - dt);
    this.updateRush(dt);
    if (this.openWindows > 0 && this.phase === 'running') {
      const tw = t.work.windows;
      this.dopamine = Math.min(t.dopamine.max, this.dopamine + tw.trickle * this.openWindows * this.windowTolerance * dt);
    }
    const ride = this.course.finished(prevD, this.d);
    if (ride && (ride.kind === 'loop' || ride.kind === 'corkscrew' || ride.kind === 'drop')) this.thrill(ride.kind);

    this.scrollT = Math.max(0, this.scrollT - dt);
    if (this.combo > 0 && this.time - this.lastUp > this.t.scroll.reset) this.combo = 0;
    if (this.sulkT > 0) {
      this.sulkT -= dt;
      if (this.sulkT <= 0 && this.setPiece === 'algorithm') this.events.push({ type: 'algorithm', watching: true });
    }

    for (const o of this.obstacles) {
      if (o.kind === 'thumb') {
        this.stepThumb(o, dt);
        continue;
      }
      if (o.speed > 0) {
        if (!o.active && o.s - this.d < t.movingPost.trigger) o.active = true;
        if (o.active) o.s -= o.speed * dt;
      }
    }

    if (this.gateT < 0 && this.d >= gateS(this.nextGate, t)) this.startGate();
    this.collide(prevBox);
    if (this.phase === 'running') this.touchPads();
    if (this.phase === 'running') this.collect();
    if (this.phase === 'running' && this.dopamine <= 0) this.lose('empty');

    this.gen.fill(this.d + t.spawn.ahead, { speed: this.speed, difficulty: this.difficulty }, this.obstacles, this.pickups, this.pads);
    this.course.trim(this.d);
    const behind = this.d - 20;
    this.obstacles = this.obstacles.filter((o) => {
      if (o.s + o.length > behind) return true;
      if (o.kind === 'habit' && !o.hit) {
        this.habitsDodged++;
        if (o.variant === MUM) this.mumIgnored++;
      }
      if (o.kind === 'high') this.adsPassed++;
      return false;
    });
    this.pickups = this.pickups.filter((pk) => !pk.taken && pk.s > behind);
    this.pads = this.pads.filter((pd) => pd.s + pd.length > behind);
  }

  /** A push notification landed on screen. Looking at it is enough for a little hit. */
  notificationArrived(): void {
    if (this.phase !== 'running') return;
    const gain = this.t.notify.bump;
    this.dopamine = Math.min(this.t.dopamine.max, this.dopamine + gain);
    this.events.push({ type: 'notified', gain });
  }

  /** Opened a notification: the more distracted the better. */
  openNotification(): void {
    if (this.phase !== 'running') return;
    const n = this.t.notify;
    const gain = n.tapGain * this.notifyTolerance;
    this.notificationsOpened++;
    this.dopamine = Math.min(this.t.dopamine.max, this.dopamine + gain);
    this.notifyTolerance = Math.max(n.toleranceFloor, this.notifyTolerance * n.toleranceDecay);
    this.boostT = n.boostTime;
    this.slowT = 0;
    this.events.push({ type: 'boost', gain, tolerance: this.notifyTolerance });
  }

  /** Work mode: how many app windows are open. The UI owns them (a gate clears them). */
  setOpenWindows(n: number): void {
    this.openWindows = Math.max(0, Math.min(this.t.work.windows.max, n));
  }

  /** Work mode: a new app window opened. Each one numbs the trickle a little more. */
  windowOpened(): void {
    const tw = this.t.work.windows;
    this.windowTolerance = Math.max(tw.toleranceFloor, this.windowTolerance * tw.toleranceDecay);
  }

  /** Watched the revive ad: back into the feed with some dopamine. Tolerance stays. */
  revive(): void {
    if (this.phase !== 'dead' || this.revivesLeft <= 0) return;
    const t = this.t;
    this.revivesLeft--;
    this.phase = 'running';
    this.cause = null;
    this.crashKind = null;
    this.combo = 0;
    this.scrollT = 0;
    this.fadeT = 0;
    this.slowT = 0;
    this.boostT = 0;
    this.rush = 0;
    this.autoplayT = 0;
    this.dopamine = t.revive.dopamine;
    // Clear whatever killed you and the stretch right ahead, so the revive isn't an instant re-death.
    // Downhill rush can make that stretch go by fast, so it scales with speed.
    const clearTo = this.d + Math.max(t.revive.clearAhead, this.speed * (1 + t.slope.downGain) * t.revive.clearSeconds);
    this.obstacles = this.obstacles.filter((o) => o.s + o.length < this.d - 1 || o.s > clearTo);
    this.pads = this.pads.filter((pd) => pd.s + pd.length < this.d - 1 || pd.s > clearTo);
    const p = this.player;
    p.x = laneX(p.lane, t);
    p.prevLane = p.lane;
    p.y = 0;
    p.vy = 0;
    p.grounded = true;
    p.rollT = 0;
    p.rollQueued = false;
    p.stumbleT = 0;
    this.airT = 0;
    this.events.push({ type: 'revive' });
  }

  private startGate(): void {
    this.nextGate++;
    this.zone++;
    this.gateT = 0;
    this.events.push({ type: 'gate', zone: this.zone });
  }

  private endGate(): void {
    this.gateT = -1;
    this.speed = Math.min(this.t.speed.max, this.speed + this.t.gate.speedStep);
    this.events.push({ type: 'gateEnd', zone: this.zone });
  }

  /** Slowing into reality: no input, no collisions, the feed stops moving. */
  private stepFade(dt: number): void {
    this.movePlayer(dt);
    this.d += this.runSpeed * dt;
    this.fadeT += dt;
    if (this.fadeT >= this.t.reality.fadeTime) {
      this.phase = 'dead';
      this.events.push({ type: 'dead', cause: this.cause ?? 'empty' });
    }
  }

  private sample(dt: number): void {
    this.sampleSum += this.dopamine * dt;
    this.sampleT += dt;
    if (this.sampleT < this.t.daily.sampleEvery) return;
    this.history.push(this.sampleSum / this.sampleT);
    this.sampleSum = 0;
    this.sampleT = 0;
  }

  private lose(cause: DeathCause): void {
    // Keep the last partial sample if it's long enough to mean something.
    if (this.sampleT >= this.t.daily.sampleEvery * 0.3) this.history.push(this.sampleSum / this.sampleT);
    this.sampleSum = 0;
    this.sampleT = 0;
    this.cause = cause;
    this.dopamine = 0;
    this.boostT = 0;
    this.fadeFrom = cause === 'crash' ? 0 : this.runSpeed;
    this.fadeT = 0;
    this.phase = 'fading';
    if (cause === 'empty') this.events.push({ type: 'empty' });
  }

  private movePlayer(dt: number): void {
    const t = this.t;
    const p = this.player;
    // Lateral: move toward the target lane at constant rate.
    const targetX = laneX(p.lane, t);
    const rate = t.lanes.width / t.laneSwitchTime;
    const dx = targetX - p.x;
    p.x += Math.sign(dx) * Math.min(Math.abs(dx), rate * dt);

    // Vertical. Over a crest the track falls away under you, so gravity
    // (relative to the track) weakens; on a steep enough one it lets go.
    const sl = t.slope;
    const v = this.runSpeed;
    const lifts = this.course.lifts(this.d);
    const g = t.jump.gravity - sl.crestGain * v * v * this.course.crest(this.d);
    if (p.grounded && lifts && g < 0 && this.phase === 'running') {
      p.grounded = false;
      p.vy = 0;
      p.rollT = 0;
      this.airT = 0;
      this.events.push({ type: 'lift' });
    }
    if (!p.grounded) {
      this.airT += dt;
      p.vy -= Math.max(g, t.jump.gravity * (lifts ? sl.liftFloat : sl.floatMin)) * dt;
      p.y += p.vy * dt;
      if (p.y <= 0) {
        p.y = 0;
        p.vy = 0;
        p.grounded = true;
        this.events.push({ type: 'land' });
        if (this.airT >= t.thrill.airMin && this.phase === 'running') this.thrill('air');
        this.airT = 0;
        if (p.rollQueued && this.phase === 'running') {
          p.rollQueued = false;
          p.rollT = t.roll.duration;
          this.events.push({ type: 'roll' });
        }
      }
    }
    p.rollT = Math.max(0, p.rollT - dt);
    p.stumbleT = Math.max(0, p.stumbleT - dt);
  }

  /** The doomscroll gesture: a swipe up within `scroll.window` of the last one is a flick. */
  private flick(): void {
    const sc = this.t.scroll;
    if (this.time - this.lastUp <= sc.window) {
      this.combo = Math.min(sc.maxCombo, Math.max(2, this.combo + 1));
      this.scrolls++;
      const gain = sc.gain * this.scrollTolerance;
      this.dopamine = Math.min(this.t.dopamine.max, this.dopamine + gain);
      this.scrollTolerance = Math.max(sc.toleranceFloor, this.scrollTolerance * sc.toleranceDecay);
      this.scrollT = sc.burst;
      this.events.push({ type: 'scroll', combo: this.combo, gain });
    }
    this.lastUp = this.time;
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
        this.flick();
        if (!p.grounded) return;
        p.grounded = false;
        p.vy = t.jump.velocity;
        p.rollT = 0;
        this.airT = 0;
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
      case 'thumb': {
        const th = t.setPieces.thumb;
        return { x0: cx - th.halfWidth, x1: cx + th.halfWidth, y0: 0, y1: th.height, s0: o.s, s1: o.s + o.length };
      }
      case 'habit':
        return { x0: cx - t.habit.halfWidth, x1: cx + t.habit.halfWidth, y0: 0, y1: t.habit.height, s0: o.s - t.habit.halfDepth, s1: o.s + t.habit.halfDepth };
    }
  }

  private collide(prev: Box): void {
    const pb = this.playerBox();
    for (const o of this.obstacles) {
      if (o.hit || (o.kind === 'thumb' && !this.thumbDown(o))) continue;
      const ob = this.obstacleBox(o);
      if (!overlaps(pb, ob)) continue;

      if (this.boostT > 0) {
        // Boosted: nothing real can stop you.
        o.hit = true;
        this.smashed++;
        this.events.push({ type: 'smash', id: o.id, kind: o.kind, lane: o.lane });
        continue;
      }
      if (o.kind === 'habit') {
        this.hitHabit(o);
        continue;
      }
      const isPost = o.kind === 'post' || o.kind === 'movingPost' || o.kind === 'thumb';
      // Side hit: we were already alongside the post last tick, and only the
      // lateral axis started overlapping. That's a stumble, not a crash.
      const wasAlongside = prev.s1 > ob.s0 + 0.05 && prev.s0 < ob.s1;
      const xWasClear = prev.x1 <= ob.x0 || prev.x0 >= ob.x1;
      if (isPost && wasAlongside && xWasClear) {
        this.stumble();
        return;
      }
      this.events.push({ type: 'crash', kind: o.kind });
      this.crashKind = o.kind;
      this.lose('crash');
      return;
    }
  }

  /** The Thumb drops once you're `lead` seconds away, lands, drags toward you, then lets go. */
  private stepThumb(o: Obstacle, dt: number): void {
    const th = this.t.setPieces.thumb;
    if (!o.active) {
      if (o.s - this.d < this.speed * th.lead) {
        o.active = true;
        o.age = 0;
        this.events.push({ type: 'thumb', stage: 'warn', lane: o.lane });
      }
      return;
    }
    const before = o.age;
    o.age += dt;
    const up = th.descend + th.drag;
    if (before < th.descend && o.age >= th.descend) this.events.push({ type: 'thumb', stage: 'slam', lane: o.lane });
    if (this.thumbDown(o)) o.s -= th.speed * dt;
    if (before < up && o.age >= up) this.events.push({ type: 'thumb', stage: 'lift', lane: o.lane });
  }

  /** On the track (solid): between landing and letting go. */
  thumbDown(o: Obstacle): boolean {
    const th = this.t.setPieces.thumb;
    return o.active && o.age >= th.descend && o.age < th.descend + th.drag;
  }

  private hitHabit(o: Obstacle): void {
    const h = this.t.habit;
    const cost = h.cost * this.t.characters.habitCost[this.character];
    o.hit = true;
    this.habitsHit++;
    this.lastHabit = o.variant;
    // The Algorithm loses interest in someone drinking water.
    if (this.setPiece === 'algorithm') {
      if (this.sulkT <= 0) this.events.push({ type: 'algorithm', watching: false });
      this.sulkT = this.t.setPieces.algorithm.sulk;
    }
    this.dopamine -= cost;
    this.slowT = h.slowTime;
    this.events.push({ type: 'habit', id: o.id, habit: o.variant, cost });
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

  /** Downhill builds a rush of extra speed (fast); it bleeds off slowly after. */
  private updateRush(dt: number): void {
    const sl = this.t.slope;
    const grade = this.course.grade(this.d);
    const target = grade < 0 ? -grade * sl.downGain : -grade * sl.upLoss;
    const rate = target > this.rush ? sl.rise : sl.decay;
    this.rush += (target - this.rush) * (1 - Math.exp(-rate * dt));
  }

  private thrill(kind: ThrillKind): void {
    const th = this.t.thrill;
    const gain = th.gain * th.weight[kind] * this.thrillTolerance;
    this.thrills++;
    this.dopamine = Math.min(this.t.dopamine.max, this.dopamine + gain);
    this.thrillTolerance = Math.max(th.toleranceFloor, this.thrillTolerance * th.toleranceDecay);
    this.events.push({ type: 'thrill', kind, gain, tolerance: this.thrillTolerance });
  }

  /** Ramps and bouncers launch you, autoplay strips speed you up. Each works once. */
  private touchPads(): void {
    const t = this.t;
    const p = this.player;
    for (const pad of this.pads) {
      if (pad.used) continue;
      if (this.d + t.player.halfDepth < pad.s || this.d - t.player.halfDepth > pad.s + pad.length) continue;
      if (Math.abs(p.x - laneX(pad.lane, t)) > t.pads.halfWidth + t.player.halfWidth - 0.2) continue;
      if (pad.kind === 'autoplay') {
        if (!p.grounded) continue;
        this.autoplayT = t.pads.autoplay.time;
      } else {
        // A ramp catches you anywhere under its slope; a bouncer only at deck level.
        const into = Math.max(0, this.d - pad.s) / pad.length;
        const top = pad.kind === 'ramp' ? t.pads.ramp.height * into + 0.4 : 0.3;
        if (p.y > top) continue;
        p.grounded = false;
        p.vy = t.pads[pad.kind].launch;
        p.rollT = 0;
        p.rollQueued = false;
        this.airT = 0;
      }
      pad.used = true;
      this.events.push({ type: 'pad', kind: pad.kind, lane: pad.lane });
    }
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
      this.takenByType[pk.type]++;
      const gain = this.gainFor(pk.type);
      this.dopamine = Math.min(t.dopamine.max, this.dopamine + gain);
      const decay = pk.type === this.favourite ? t.characters.cravingDecay : t.content.toleranceDecay;
      this.tolerance[pk.type] = Math.max(t.content.toleranceFloor, this.tolerance[pk.type] * decay);
      this.events.push({ type: 'pickup', id: pk.id, content: pk.type, gain, tolerance: this.tolerance[pk.type] });
    }
  }

  drainEvents(): SimEvent[] {
    const e = this.events;
    this.events = [];
    return e;
  }
}

function smooth(x: number): number {
  const k = Math.min(1, Math.max(0, x));
  return k * k * (3 - 2 * k);
}

function overlaps(a: Box, b: Box): boolean {
  return a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0 && a.s0 < b.s1 && a.s1 > b.s0;
}
