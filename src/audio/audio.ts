// Procedural Web Audio: a looping feed-beat plus event blips, no audio files.
// Like the renderer, it reads sim state and reacts to SimEvents, never mutates.
//   - Music brightness (low-pass cutoff), volume and pitch follow dopamine.
//   - Pickup blips drop in pitch as that content type's tolerance builds.
//   - Grey reality: the music fades out, leaving a faint room hum.
// iOS only allows audio to start inside a user gesture, so the context is
// created on the first touch or key press.

import type { SimEvent } from '../sim/types';
import type { World } from '../sim/world';

const BPM = 124;
const STEP = 60 / BPM / 4; // sixteenth note
const LOOKAHEAD = 0.12;
// Four-bar progression (root notes, Hz): A minor, F, C, G.
const ROOTS = [110, 87.31, 130.81, 98];
const ARP = [1, 1.5, 2, 2.4, 3, 2.4, 2, 1.5];
const BLIP_BASE = [880, 1318.5, 659.3, 440]; // like, notification, reel, outrage

export class GameAudio {
  private ctx: AudioContext | null = null;
  private master!: GainNode;
  private musicFilter!: BiquadFilterNode;
  private musicGain!: GainNode;
  private humGain!: GainNode;
  private noise!: AudioBuffer;
  private nextNote = 0;
  private stepIdx = 0;
  private level = 1;
  private pitch = 1;

  constructor() {
    const unlock = () => {
      this.start();
      if (this.ctx?.state === 'running') {
        window.removeEventListener('pointerdown', unlock);
        window.removeEventListener('touchend', unlock);
        window.removeEventListener('keydown', unlock);
      }
    };
    window.addEventListener('pointerdown', unlock);
    window.addEventListener('touchend', unlock);
    window.addEventListener('keydown', unlock);
  }

  private start(): void {
    if (this.ctx) {
      void this.ctx.resume();
      return;
    }
    const ctx = new AudioContext();
    this.ctx = ctx;
    this.master = ctx.createGain();
    this.master.gain.value = 0.8;
    this.master.connect(ctx.destination);

    this.musicFilter = ctx.createBiquadFilter();
    this.musicFilter.type = 'lowpass';
    this.musicFilter.Q.value = 0.8;
    this.musicGain = ctx.createGain();
    this.musicGain.gain.value = 0;
    this.musicFilter.connect(this.musicGain).connect(this.master);

    this.noise = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
    const data = this.noise.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;

    // Room tone for grey reality: a low hum and a whisper of filtered noise.
    this.humGain = ctx.createGain();
    this.humGain.gain.value = 0;
    this.humGain.connect(this.master);
    const hum = ctx.createOscillator();
    hum.frequency.value = 55;
    const humLevel = ctx.createGain();
    humLevel.gain.value = 0.5;
    hum.connect(humLevel).connect(this.humGain);
    hum.start();
    const air = ctx.createBufferSource();
    air.buffer = this.noise;
    air.loop = true;
    const airFilter = ctx.createBiquadFilter();
    airFilter.type = 'lowpass';
    airFilter.frequency.value = 400;
    air.connect(airFilter).connect(this.humGain);
    air.start();

    this.nextNote = ctx.currentTime + 0.05;
    void ctx.resume();
  }

  /** Call once per frame, after the sim has stepped. */
  update(w: World, dt: number): void {
    const ctx = this.ctx;
    if (!ctx || ctx.state !== 'running') return;
    const target = Math.min(1, Math.max(0, w.dopamine / w.t.dopamine.fullColourAt));
    this.level += (target - this.level) * (1 - Math.exp(-dt * 3));
    const gone = w.phase === 'fading' || w.phase === 'dead';
    // Tape-stop feel: pitch sags as the run slows into reality.
    const pitchTarget = w.phase === 'fading' && w.speed > 0 ? 0.7 + 0.3 * (w.runSpeed / Math.max(1, w.speed)) : 1;
    this.pitch += (pitchTarget - this.pitch) * (1 - Math.exp(-dt * 4));

    const now = ctx.currentTime;
    const l = this.level;
    const musicTarget = w.phase === 'dead' ? 0 : w.phase === 'ready' ? 0.18 : 0.08 + 0.3 * l;
    this.musicGain.gain.setTargetAtTime(musicTarget, now, gone ? 0.5 : 0.15);
    this.musicFilter.frequency.setTargetAtTime(250 + 11000 * l * l, now, 0.1);
    this.humGain.gain.setTargetAtTime(gone ? 0.05 : 0, now, 0.8);

    while (this.nextNote < now + LOOKAHEAD) {
      this.scheduleStep(this.nextNote, this.stepIdx);
      this.nextNote += STEP;
      this.stepIdx = (this.stepIdx + 1) % 64;
    }
  }

  handle(events: readonly SimEvent[]): void {
    if (!this.ctx || this.ctx.state !== 'running') return;
    for (const e of events) {
      switch (e.type) {
        case 'pickup':
          this.blip(e.content, e.tolerance);
          break;
        case 'habit':
          this.thud();
          break;
        case 'crash':
          this.crash();
          break;
        case 'stumble':
          this.noiseHit(0.08, 900, 0.25);
          break;
        case 'jump':
          this.tone(320, 520, 0.09, 'triangle', 0.06);
          break;
        case 'empty':
          this.tone(440, 110, 1.6, 'sawtooth', 0.12);
          break;
        default:
          break;
      }
    }
  }

  // ---------- UI sounds (called by the comedy layer) ----------

  private get ready(): boolean {
    return !!this.ctx && this.ctx.state === 'running';
  }

  /** Fake push notification: the two-note ping everyone's nervous system knows. */
  chime(): void {
    if (!this.ready) return;
    this.tone(1568, 1568, 0.09, 'sine', 0.12);
    this.tone(2093, 2093, 0.16, 'sine', 0.1, 0.1);
  }

  /** A brand's four-note sting (semitones above C5). */
  jingle(notes: readonly number[]): void {
    if (!this.ready) return;
    notes.forEach((n, i) => {
      const f = 523.25 * Math.pow(2, n / 12);
      this.tone(f, f, 0.22, 'square', 0.05, i * 0.16);
      this.tone(f / 2, f / 2, 0.22, 'triangle', 0.08, i * 0.16);
    });
  }

  /** Report row reveal. */
  tick(): void {
    if (!this.ready) return;
    this.tone(2400, 1800, 0.03, 'square', 0.04);
  }

  click(): void {
    if (!this.ready) return;
    this.tone(900, 600, 0.05, 'triangle', 0.08);
  }

  /** Revive granted: a cheap slot-machine sparkle. */
  reward(): void {
    if (!this.ready) return;
    [0, 4, 7, 12, 16].forEach((n, i) => {
      const f = 659.25 * Math.pow(2, n / 12);
      this.tone(f, f * 1.01, 0.12, 'square', 0.05, i * 0.06);
    });
  }

  // ---------- music ----------

  private scheduleStep(t: number, i: number): void {
    const bar = Math.floor(i / 16);
    const s = i % 16;
    const root = ROOTS[bar] * this.pitch;
    if (s % 4 === 0) this.kick(t);
    if (s % 4 === 2) this.hat(t);
    if (s % 2 === 0) this.note(t, root, STEP * 1.8, 'sawtooth', 0.16);
    this.note(t, root * 2 * ARP[s % ARP.length], STEP * 0.9, 'square', 0.035);
  }

  private note(t: number, freq: number, dur: number, type: OscillatorType, vol: number): void {
    const ctx = this.ctx!;
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = type;
    o.frequency.value = freq;
    g.gain.setValueAtTime(vol, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(this.musicFilter);
    o.start(t);
    o.stop(t + dur + 0.02);
  }

  private kick(t: number): void {
    const ctx = this.ctx!;
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.frequency.setValueAtTime(140 * this.pitch, t);
    o.frequency.exponentialRampToValueAtTime(42 * this.pitch, t + 0.12);
    g.gain.setValueAtTime(0.7, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.25);
    o.connect(g).connect(this.musicFilter);
    o.start(t);
    o.stop(t + 0.27);
  }

  private hat(t: number): void {
    const ctx = this.ctx!;
    const src = ctx.createBufferSource();
    src.buffer = this.noise;
    const f = ctx.createBiquadFilter();
    f.type = 'highpass';
    f.frequency.value = 7000;
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.12, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.05);
    src.connect(f).connect(g).connect(this.musicFilter);
    src.start(t, Math.random() * 0.5, 0.06);
  }

  // ---------- sfx ----------

  private blip(type: number, tolerance: number): void {
    // Fresh content sings; content you're used to barely registers.
    const f = BLIP_BASE[type] * (0.5 + 0.5 * tolerance);
    const vol = 0.05 + 0.1 * tolerance;
    if (type === 1) {
      this.tone(f, f, 0.06, 'sine', vol);
      this.tone(f * 1.5, f * 1.5, 0.08, 'sine', vol, 0.07);
    } else if (type === 2) {
      this.tone(f, f * 1.5, 0.1, 'triangle', vol);
    } else if (type === 3) {
      this.tone(f, f * 0.8, 0.1, 'square', vol * 0.6);
    } else {
      this.tone(f, f * 1.2, 0.08, 'sine', vol);
    }
  }

  private thud(): void {
    this.tone(160, 50, 0.35, 'sine', 0.5);
    this.tone(330, 180, 0.5, 'triangle', 0.08, 0.05);
  }

  private crash(): void {
    this.noiseHit(0.5, 1800, 0.6);
    this.tone(220, 40, 0.6, 'sawtooth', 0.2);
  }

  private tone(from: number, to: number, dur: number, type: OscillatorType, vol: number, delay = 0): void {
    const ctx = this.ctx!;
    const t = ctx.currentTime + delay;
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = type;
    o.frequency.setValueAtTime(from, t);
    o.frequency.exponentialRampToValueAtTime(to, t + dur);
    g.gain.setValueAtTime(vol, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(this.master);
    o.start(t);
    o.stop(t + dur + 0.02);
  }

  private noiseHit(dur: number, cutoff: number, vol: number): void {
    const ctx = this.ctx!;
    const t = ctx.currentTime;
    const src = ctx.createBufferSource();
    src.buffer = this.noise;
    const f = ctx.createBiquadFilter();
    f.type = 'lowpass';
    f.frequency.setValueAtTime(cutoff, t);
    f.frequency.exponentialRampToValueAtTime(120, t + dur);
    const g = ctx.createGain();
    g.gain.setValueAtTime(vol, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    src.connect(f).connect(g).connect(this.master);
    src.start(t, 0, dur + 0.05);
  }
}
