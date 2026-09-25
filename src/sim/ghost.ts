// Ghost runs for challenge links. Pure (no DOM, no Three.js).
//
// A replay of inputs alone isn't safe across devices: Math.sin/exp may differ
// in the last bits between JavaScriptCore and V8, and a run would drift. So a
// ghost is recorded positions: every `ghost.sampleEvery` s of sim time we keep
// distance, lateral x, height and a roll/air flag. Playback interpolates them
// against the *viewer's* sim time, so a gate's bullet time slows both alike.
//
// Wire format (before the UI deflates and base64s it): a u16 header length,
// the header as UTF-8 JSON, then the samples as struct-of-arrays bytes
// (distance deltas, x, y, flags), which compresses far better than
// interleaved. Distance deltas carry their rounding error forward, so the
// quantised track never drifts from the real one.

import { TUNING, type Tuning } from './types';
import type { World } from './world';

const DQ = 0.06; // m per distance-delta step (u8: up to ~15 m per sample)
const XQ = 0.04; // m per x step (i8: ±5 m)
const YQ = 0.1; // m per y step (u8: up to 25 m)
const ROLL = 1;
const AIR = 2;

export interface GhostHeader {
  v: 1;
  /** Course seed. */
  seed: number;
  /** Character index (tuning/content characters). */
  ch: number;
  /** The sender's handle, e.g. "@hoodie.goblin.4312". */
  name: string;
  mode: 'personal' | 'work';
  /** Today's Feed number if this was a Daily run, else 0. */
  day: number;
  /** Final distance (m). */
  dist: number;
  /** What killed them, lower case, for the grave tag ("a glass of water"). */
  killer: string;
}

export interface GhostFrame {
  d: number;
  x: number;
  y: number;
  roll: boolean;
  air: boolean;
}

export class GhostRecorder {
  private d: number[] = [];
  private x: number[] = [];
  private y: number[] = [];
  private f: number[] = [];
  private next = 0;

  constructor(private readonly t: Tuning = TUNING) {}

  reset(): void {
    this.d = [];
    this.x = [];
    this.y = [];
    this.f = [];
    this.next = 0;
  }

  get samples(): number {
    return this.d.length;
  }

  /** Call after every sim step. */
  update(w: World): void {
    if (w.phase !== 'running' || w.time < this.next) return;
    if (this.d.length * this.t.ghost.sampleEvery >= this.t.ghost.maxSeconds) return;
    this.next = (this.d.length + 1) * this.t.ghost.sampleEvery;
    const p = w.player;
    this.d.push(w.d);
    this.x.push(p.x);
    this.y.push(p.y);
    this.f.push((p.rollT > 0 ? ROLL : 0) | (p.grounded ? 0 : AIR));
  }

  encode(header: GhostHeader): Uint8Array {
    const n = this.d.length;
    const head = new TextEncoder().encode(JSON.stringify(header));
    const out = new Uint8Array(2 + head.length + n * 4);
    out[0] = head.length >> 8;
    out[1] = head.length & 255;
    out.set(head, 2);
    const o = 2 + head.length;
    let recon = 0;
    for (let i = 0; i < n; i++) {
      const q = Math.max(0, Math.min(255, Math.round((this.d[i] - recon) / DQ)));
      recon += q * DQ;
      out[o + i] = q;
      out[o + n + i] = Math.max(-127, Math.min(127, Math.round(this.x[i] / XQ))) & 255;
      out[o + 2 * n + i] = Math.max(0, Math.min(255, Math.round(this.y[i] / YQ)));
      out[o + 3 * n + i] = this.f[i];
    }
    return out;
  }
}

/** Links come from strangers: check every field before anything uses it. */
function validHeader(h: GhostHeader): boolean {
  const int = (v: unknown, lo: number, hi: number) => Number.isInteger(v) && (v as number) >= lo && (v as number) <= hi;
  const str = (v: unknown, max: number) => typeof v === 'string' && v.length <= max;
  return (
    h?.v === 1 &&
    int(h.seed, 0, 2 ** 53) &&
    int(h.ch, 0, TUNING.characters.count - 1) &&
    str(h.name, 32) &&
    (h.mode === 'personal' || h.mode === 'work') &&
    int(h.day, 0, 1e6) &&
    int(h.dist, 0, 1e7) &&
    str(h.killer, 64)
  );
}

export class GhostTrack {
  readonly header: GhostHeader;
  private readonly d: Float32Array;
  private readonly x: Float32Array;
  private readonly y: Float32Array;
  private readonly f: Uint8Array;

  private constructor(header: GhostHeader, d: Float32Array, x: Float32Array, y: Float32Array, f: Uint8Array) {
    this.header = header;
    this.d = d;
    this.x = x;
    this.y = y;
    this.f = f;
  }

  /** Null if the bytes aren't a ghost we understand. */
  static decode(bytes: Uint8Array): GhostTrack | null {
    try {
      const hl = (bytes[0] << 8) | bytes[1];
      const header = JSON.parse(new TextDecoder().decode(bytes.subarray(2, 2 + hl))) as GhostHeader;
      if (!validHeader(header)) return null;
      const body = bytes.subarray(2 + hl);
      if (body.length % 4 !== 0 || body.length === 0) return null;
      const n = body.length / 4;
      const d = new Float32Array(n);
      const x = new Float32Array(n);
      const y = new Float32Array(n);
      const f = new Uint8Array(n);
      let acc = 0;
      for (let i = 0; i < n; i++) {
        acc += body[i] * DQ;
        d[i] = acc;
        x[i] = ((body[n + i] << 24) >> 24) * XQ;
        y[i] = body[2 * n + i] * YQ;
        f[i] = body[3 * n + i];
      }
      return new GhostTrack(header, d, x, y, f);
    } catch {
      return null;
    }
  }

  /** Sim seconds the ghost lasted. */
  get duration(): number {
    return (this.d.length - 1) * TUNING.ghost.sampleEvery;
  }

  get finalD(): number {
    return this.d[this.d.length - 1];
  }

  /** Where the ghost is at sim time `time`; clamps to its end (the grave). */
  at(time: number, out: GhostFrame): GhostFrame {
    const n = this.d.length;
    const f = Math.min(n - 1, Math.max(0, time / TUNING.ghost.sampleEvery));
    const i = Math.min(n - 2, Math.floor(f));
    const k = n < 2 ? 0 : f - i;
    const j = Math.max(0, i);
    const j1 = Math.min(n - 1, j + 1);
    out.d = this.d[j] + (this.d[j1] - this.d[j]) * k;
    out.x = this.x[j] + (this.x[j1] - this.x[j]) * k;
    out.y = this.y[j] + (this.y[j1] - this.y[j]) * k;
    const flags = this.f[k < 0.5 ? j : j1];
    out.roll = (flags & ROLL) !== 0;
    out.air = (flags & AIR) !== 0;
    return out;
  }
}
