// The track's shape: a rollercoaster laid out from the seed. Pure math, no
// rendering. The sim still plays in track coordinates (lane, s, y); the course
// only says where that track sits in the world and a few things the sim cares
// about: the grade (downhill speeds you up), the crest (going over one makes
// you float, some launch you into airtime) and which stretches must stay empty
// (loops, corkscrews, drops and airtime hills are thrill rides, not obstacles).
//
// The course is a contiguous list of segments along s. Each one bends the
// track by its own function of u = 0..1 (heading, pitch, roll, sideways shift),
// so the orientation at any s is exact; the position is integrated on a
// SAMPLE_STEP grid. Angles follow a yaw (about +y), pitch (about +x, positive =
// nose up), roll (about the forward axis, positive = right side up) order;
// forward is -z at yaw 0, matching the renderer's straight track.
//
// Checkpoint gates always sit on flat straight track so their camera works.

import { Rng } from './rng';
import { TUNING, gateS, type Tuning } from './types';

export type SegmentKind = 'straight' | 'curve' | 'roller' | 'climb' | 'drop' | 'airtime' | 'loop' | 'corkscrew';

/** Kinds that keep their stretch free of obstacles (thrill rides). */
const CLEAR: ReadonlySet<SegmentKind> = new Set(['drop', 'airtime', 'loop', 'corkscrew']);
/** Kinds whose crest can lift you off the track by itself. */
const LIFT: ReadonlySet<SegmentKind> = new Set(['drop', 'airtime']);
/** Kinds with no side towers: they turn the world upside down. */
const NO_SCENERY: ReadonlySet<SegmentKind> = new Set(['loop', 'corkscrew']);

export interface Segment {
  kind: SegmentKind;
  s0: number;
  s1: number;
  /** Heading on entry (rad). */
  yaw0: number;
  /** Total heading change (curves). */
  turn: number;
  /** Pitch amplitude (rad); sign picks hill or valley for rollers. */
  pitch: number;
  /** -1 or 1: which way a loop shifts or a corkscrew rolls. */
  dir: number;
}

export interface CourseSample {
  x: number;
  y: number;
  z: number;
  yaw: number;
  pitch: number;
  roll: number;
}

export interface ClearZone {
  from: number;
  to: number;
  seg: Segment;
}

interface Angles {
  yaw: number;
  pitch: number;
  roll: number;
  /** Sideways shift built up so far within the segment (loops). */
  lat: number;
  /** d(pitch)/ds; negative over a crest. Only for grade-carrying kinds. */
  bend: number;
}

const TAU = Math.PI * 2;

function smoother(u: number): number {
  const k = Math.min(1, Math.max(0, u));
  return k * k * k * (k * (k * 6 - 15) + 10);
}

export class Course {
  readonly t: Tuning;
  /** Integrated centreline at s = (base + i) * step. */
  private xs: number[] = [0];
  private ys: number[] = [0];
  private zs: number[] = [0];
  private base = 0;
  private segs: Segment[] = [];
  private readonly rng: Rng;
  private readonly step: number;
  private readonly a: Angles = { yaw: 0, pitch: 0, roll: 0, lat: 0, bend: 0 };
  private readonly b: Angles = { yaw: 0, pitch: 0, roll: 0, lat: 0, bend: 0 };

  constructor(seed: number, t: Tuning = TUNING) {
    this.t = t;
    this.step = t.course.sampleStep;
    // Separate stream so the layout doesn't shift the obstacle generator's rolls.
    this.rng = new Rng((seed ^ 0x5bd1e995) >>> 0);
    this.segs.push({ kind: 'straight', s0: -Infinity, s1: t.course.startStraight, yaw0: 0, turn: 0, pitch: 0, dir: 1 });
  }

  /** Lay out segments and integrate the centreline at least up to `s`. */
  extend(s: number): void {
    while (this.end < s + this.step * 2) this.addSegment();
    const need = Math.ceil(s / this.step) + 1;
    while (this.base + this.xs.length <= need) this.integrate();
  }

  /** Drop what's far behind `s` (keeps memory flat on long runs). */
  trim(s: number): void {
    const keepFrom = Math.floor((s - 200) / this.step) - this.base;
    if (keepFrom > 2000) {
      this.xs.splice(0, keepFrom);
      this.ys.splice(0, keepFrom);
      this.zs.splice(0, keepFrom);
      this.base += keepFrom;
    }
    let drop = 0;
    while (drop < this.segs.length - 1 && this.segs[drop].s1 < s - 200) drop++;
    if (drop > 16) this.segs.splice(0, drop);
  }

  private get end(): number {
    return this.segs[this.segs.length - 1].s1;
  }

  /** Where the track is and how it's turned at `s`. */
  sample(s: number, out: CourseSample): CourseSample {
    const seg = this.segmentAt(s);
    const a = this.angles(seg, s, this.a);
    out.yaw = a.yaw;
    out.pitch = a.pitch;
    out.roll = a.roll;
    if (s <= 0) {
      out.x = 0;
      out.y = 0;
      out.z = -s;
    } else {
      this.extend(s);
      const f = s / this.step - this.base;
      const i = Math.max(0, Math.min(this.xs.length - 2, Math.floor(f)));
      const k = f - i;
      out.x = this.xs[i] + (this.xs[i + 1] - this.xs[i]) * k;
      out.y = this.ys[i] + (this.ys[i + 1] - this.ys[i]) * k;
      out.z = this.zs[i] + (this.zs[i + 1] - this.zs[i]) * k;
    }
    if (seg.kind === 'corkscrew' && a.roll !== 0) {
      // Heartline roll: spin round an axis at rider height, not the rails.
      const h = this.t.course.corkscrew.heartline;
      const sp = Math.sin(a.pitch);
      const cp = Math.cos(a.pitch);
      const sy = Math.sin(a.yaw);
      const cy = Math.cos(a.yaw);
      const sr = Math.sin(a.roll);
      const cr = Math.cos(a.roll);
      // up without roll minus up with roll.
      out.x += h * (sp * sy - (-sr * cy + cr * sp * sy));
      out.y += h * (cp - cr * cp);
      out.z += h * (sp * cy - (sr * sy + cr * sp * cy));
    }
    return out;
  }

  /** sin(pitch) of rideable slopes: > 0 uphill. Loops and corkscrews count as flat. */
  grade(s: number): number {
    const seg = this.segmentAt(s);
    if (seg.kind === 'loop' || seg.kind === 'corkscrew') return 0;
    return Math.sin(this.angles(seg, s, this.a).pitch);
  }

  /** How sharply the track falls away (1/m, >= 0); what makes a crest floaty. */
  crest(s: number): number {
    const seg = this.segmentAt(s);
    if (seg.kind === 'loop' || seg.kind === 'corkscrew') return 0;
    return Math.max(0, -this.angles(seg, s, this.a).bend);
  }

  /** Whether a crest here may lift a grounded runner into the air. */
  lifts(s: number): boolean {
    return LIFT.has(this.segmentAt(s).kind);
  }

  /** False where side towers would end up upside down. */
  scenery(s: number): boolean {
    const m = this.t.course.sceneryMargin;
    return !NO_SCENERY.has(this.segmentAt(s - m).kind) && !NO_SCENERY.has(this.segmentAt(s).kind) && !NO_SCENERY.has(this.segmentAt(s + m).kind);
  }

  segmentAt(s: number): Segment {
    const segs = this.segs;
    while (s >= this.end) this.addSegment();
    let lo = 0;
    let hi = segs.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (segs[mid].s1 <= s) lo = mid + 1;
      else hi = mid;
    }
    return segs[lo];
  }

  /** The first thrill stretch (plus its approach and run-out) ending after `s`. */
  nextClear(s: number): ClearZone | null {
    const c = this.t.course;
    this.extend(s + c.lookahead);
    for (const seg of this.segs) {
      if (!CLEAR.has(seg.kind)) continue;
      const to = seg.s1 + c.clearAfter;
      if (to > s) return { from: seg.s0 - c.clearBefore, to, seg };
    }
    return null;
  }

  /** Thrill segments that finish between s0 (exclusive) and s1 (inclusive). */
  finished(s0: number, s1: number): Segment | null {
    const seg = this.segmentAt(s0);
    return CLEAR.has(seg.kind) && seg.kind !== 'airtime' && seg.s1 > s0 && seg.s1 <= s1 ? seg : null;
  }

  private angles(seg: Segment, s: number, out: Angles): Angles {
    const L = seg.s1 - seg.s0;
    const u = Number.isFinite(L) ? Math.min(1, Math.max(0, (s - seg.s0) / L)) : 0;
    out.yaw = seg.yaw0;
    out.pitch = 0;
    out.roll = 0;
    out.lat = 0;
    out.bend = 0;
    switch (seg.kind) {
      case 'curve': {
        out.yaw += seg.turn * smoother(u);
        // Banked into the turn, hardest mid-curve where it turns fastest.
        out.roll = this.t.course.curve.bank * seg.turn * 16 * u * u * (1 - u) * (1 - u);
        break;
      }
      case 'roller':
      case 'airtime': {
        out.pitch = seg.pitch * Math.sin(TAU * u);
        out.bend = (seg.pitch * TAU * Math.cos(TAU * u)) / L;
        break;
      }
      case 'climb':
      case 'drop': {
        const sgn = seg.kind === 'drop' ? -1 : 1;
        const sn = Math.sin(Math.PI * u);
        out.pitch = sgn * seg.pitch * sn * sn;
        out.bend = (sgn * seg.pitch * Math.PI * Math.sin(TAU * u)) / L;
        break;
      }
      case 'loop': {
        // Teardrop: gentle in, tight over the top, gentle out.
        out.pitch = TAU * u - Math.sin(TAU * u);
        out.lat = seg.dir * this.t.course.loop.shift * smoother(u);
        break;
      }
      case 'corkscrew': {
        out.roll = seg.dir * TAU * smoother(u);
        break;
      }
      case 'straight':
        break;
    }
    return out;
  }

  /** Add the next centreline sample (trapezoid rule on the forward vector). */
  private integrate(): void {
    const i = this.xs.length - 1;
    const s0 = (this.base + i) * this.step;
    const s1 = s0 + this.step;
    const seg = this.segmentAt((s0 + s1) / 2);
    const a = this.angles(seg, s0, this.a);
    const b = this.angles(seg, s1, this.b);
    const h = this.step / 2;
    const fx = -Math.cos(a.pitch) * Math.sin(a.yaw) - Math.cos(b.pitch) * Math.sin(b.yaw);
    const fy = Math.sin(a.pitch) + Math.sin(b.pitch);
    const fz = -Math.cos(a.pitch) * Math.cos(a.yaw) - Math.cos(b.pitch) * Math.cos(b.yaw);
    // A loop's sideways shift moves the whole track over (so the exit misses the entry).
    const dl = b.lat - a.lat;
    const ym = (a.yaw + b.yaw) / 2;
    this.xs.push(this.xs[i] + fx * h + Math.cos(ym) * dl);
    this.ys.push(this.ys[i] + fy * h);
    this.zs.push(this.zs[i] + fz * h - Math.sin(ym) * dl);
  }

  private addSegment(): void {
    const c = this.t.course;
    const g = this.t.gate;
    const r = this.rng;
    const last = this.segs[this.segs.length - 1];
    const s0 = last.s1;
    const yaw0 = last.yaw0 + last.turn;
    const push = (kind: SegmentKind, len: number, extra: Partial<Segment> = {}): void => {
      this.segs.push({ kind, s0, s1: s0 + len, yaw0, turn: 0, pitch: 0, dir: 1, ...extra });
    };

    // After anything that isn't a straight, breathe a little.
    if (last.kind !== 'straight') {
      push('straight', r.range(c.gapMin, c.gapMax));
      return;
    }

    const kind = r.weighted(c.weights as Record<Exclude<SegmentKind, 'straight'>, number>);
    let len: number;
    const extra: Partial<Segment> = { dir: r.chance(0.5) ? 1 : -1 };
    switch (kind) {
      case 'curve':
        len = r.range(c.curve.lengthMin, c.curve.lengthMax);
        extra.turn = extra.dir! * r.range(c.curve.angleMin, c.curve.angleMax);
        break;
      case 'roller':
        len = r.range(c.roller.lengthMin, c.roller.lengthMax);
        extra.pitch = extra.dir! * c.roller.pitch * r.range(0.6, 1);
        break;
      case 'climb':
        len = r.range(c.climb.lengthMin, c.climb.lengthMax);
        extra.pitch = c.climb.pitch * r.range(0.7, 1);
        break;
      case 'drop':
        len = r.range(c.drop.lengthMin, c.drop.lengthMax);
        extra.pitch = c.drop.pitch * r.range(0.75, 1);
        break;
      case 'airtime':
        len = r.range(c.airtime.lengthMin, c.airtime.lengthMax);
        extra.pitch = c.airtime.pitch * r.range(0.8, 1);
        break;
      case 'loop':
        len = c.loop.length;
        break;
      case 'corkscrew':
        len = c.corkscrew.length;
        break;
    }

    // Keep every gate on flat straight track: if this would reach into a
    // gate's stretch, run straight past the gate instead.
    let k = 0;
    while (gateS(k, this.t) + g.clearAfter + c.gateMargin <= s0) k++;
    const gFrom = gateS(k, this.t) - g.clearBefore - c.gateMargin;
    const gTo = gateS(k, this.t) + g.clearAfter + c.gateMargin;
    if (s0 + len > gFrom) {
      push('straight', gTo - s0);
      return;
    }
    push(kind, len, extra);
  }
}
