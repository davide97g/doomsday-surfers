// Procedural Web Audio: a looping feed-beat plus event blips, no audio files.
// Like the renderer, it reads sim state and reacts to SimEvents, never mutates.
//   - Music brightness (low-pass cutoff), volume and pitch follow dopamine.
//   - Pickup blips drop in pitch as that content type's tolerance builds.
//   - Grey reality: the music fades out, leaving a faint room hum.
//   - Gate bullet time: the music sags in pitch and goes muffled.
// iOS only allows audio to start inside a user gesture, so the context is
// created on the first touch or key press.
// Work mode swaps the beat for hold music and adds the office sounds. Chat,
// Teams-style chat, mail, the call ring loop and the hang-up are community
// sounds from Freesound and Pixabay (public/assets/sfx, CREDITS.md), never recordings of
// the real apps; calendar, ticket and Humbl (and anything not loaded yet) use
// the synthesized fallbacks below.

import { mode } from '../content/content';
import type { SimEvent } from '../sim/types';
import type { World } from '../sim/world';

const BPM = 124;
const STEP = 60 / BPM / 4; // sixteenth note
const LOOKAHEAD = 0.12;
// Four-bar progression (root notes, Hz): A minor, F, C, G.
const ROOTS = [110, 87.31, 130.81, 98];
const ARP = [1, 1.5, 2, 2.4, 3, 2.4, 2, 1.5];
const BLIP_BASE = [880, 1318.5, 659.3, 440]; // like, notification, reel, outrage

// Work mode hold music: slower, jazzier, no kick. Cmaj7, Am7, Dm7, G7.
const WORK = mode === 'work';
const HOLD_STEP = 60 / 96 / 4;
const HOLD_ROOTS = [65.41, 55, 73.42, 49];
const HOLD_CHORDS = [
  [1, 1.26, 1.5, 1.89],
  [1, 1.19, 1.5, 1.78],
  [1, 1.19, 1.5, 1.78],
  [1, 1.26, 1.5, 1.78],
];
// Vibraphone line: [step in bar, chord tone, octave multiplier].
const HOLD_MELODY: [number, number, number][] = [[0, 2, 8], [3, 3, 8], [6, 1, 8], [10, 2, 8], [12, 0, 16]];
// The call ring: our own bouncy pentatonic phrase (semitones above C5, seconds).
const RING_CYCLE = 2;
const SAMPLES = ['chat', 'sync', 'mail', 'ring', 'decline'] as const;
const SAMPLE_VOL: Record<string, number> = { chat: 0.55, sync: 0.5, mail: 0.45, ring: 0.5, decline: 0.45 };
const RING_NOTES: [number, number][] = [[0, 0], [7, 0.13], [4, 0.26], [9, 0.39], [7, 0.62], [12, 0.75], [9, 0.88], [14, 1.01]];

export class GameAudio {
  private ctx: AudioContext | null = null;
  private master!: GainNode;
  private musicFilter!: BiquadFilterNode;
  private musicGain!: GainNode;
  private humGain!: GainNode;
  private noise!: AudioBuffer;
  // Hidden ending: 'silent' cuts even the room tone, 'outside' is wind and birds.
  private ending: 'off' | 'silent' | 'outside' = 'off';
  private windGain: GainNode | null = null;
  private nextChirp = 0;
  private nextNote = 0;
  private stepIdx = 0;
  private level = 1;
  private pitch = 1;
  private readonly step = WORK ? HOLD_STEP : STEP;
  private ringBus: GainNode | null = null;
  private ringSrc: AudioBufferSourceNode | null = null;
  private nextRing = 0;
  private readonly samples = new Map<string, AudioBuffer>();

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

  /** The mixed output, for the clip recorder to listen to (null until the first gesture starts audio). */
  get output(): { ctx: AudioContext; node: AudioNode } | null {
    return this.ctx ? { ctx: this.ctx, node: this.master } : null;
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
    if (WORK) this.loadSamples(ctx);
    void ctx.resume();
  }

  /** The hidden ending's soundscape (see ui/ending.ts). */
  setEnding(mode: 'off' | 'silent' | 'outside'): void {
    this.ending = mode;
    const ctx = this.ctx;
    if (mode !== 'outside' || !ctx || this.windGain) return;
    // Wind: noise through a slowly wandering low-pass.
    this.windGain = ctx.createGain();
    this.windGain.gain.value = 0;
    this.windGain.connect(this.master);
    const src = ctx.createBufferSource();
    src.buffer = this.noise;
    src.loop = true;
    const f = ctx.createBiquadFilter();
    f.type = 'lowpass';
    f.frequency.value = 520;
    const lfo = ctx.createOscillator();
    lfo.frequency.value = 0.13;
    const depth = ctx.createGain();
    depth.gain.value = 260;
    lfo.connect(depth).connect(f.frequency);
    src.connect(f).connect(this.windGain);
    src.start();
    lfo.start();
    this.nextChirp = ctx.currentTime + 1.5;
  }

  /** A small bird: two or three quick upward whistles. */
  private chirp(t: number): void {
    const ctx = this.ctx!;
    const base = 2400 + Math.random() * 1400;
    const n = 2 + Math.floor(Math.random() * 2);
    for (let i = 0; i < n; i++) {
      const at = t + i * 0.11;
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.frequency.setValueAtTime(base, at);
      o.frequency.exponentialRampToValueAtTime(base * 1.5, at + 0.07);
      g.gain.setValueAtTime(0, at);
      g.gain.linearRampToValueAtTime(0.035, at + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0005, at + 0.09);
      o.connect(g).connect(this.master);
      o.start(at);
      o.stop(at + 0.1);
    }
  }

  /** Call once per frame, after the sim has stepped. */
  update(w: World, dt: number): void {
    const ctx = this.ctx;
    if (!ctx || ctx.state !== 'running') return;
    const target = Math.min(1, Math.max(0, w.dopamine / w.t.dopamine.fullColourAt));
    this.level += (target - this.level) * (1 - Math.exp(-dt * 3));
    const gone = w.phase === 'fading' || w.phase === 'dead';
    // Tape-stop feel: pitch sags as the run slows into reality.
    const slowMo = w.timeScale;
    const pitchTarget = (w.phase === 'fading' && w.speed > 0 ? 0.7 + 0.3 * (w.runSpeed / Math.max(1, w.speed)) : 1) * (0.6 + 0.4 * slowMo);
    this.pitch += (pitchTarget - this.pitch) * (1 - Math.exp(-dt * 4));

    const now = ctx.currentTime;
    const l = this.level;
    const musicTarget = w.phase === 'dead' ? 0 : w.phase === 'ready' ? 0.18 : 0.08 + 0.3 * l;
    this.musicGain.gain.setTargetAtTime(musicTarget, now, gone ? 0.5 : 0.15);
    this.musicFilter.frequency.setTargetAtTime((250 + 11000 * l * l) * (0.15 + 0.85 * slowMo), now, 0.1);
    this.humGain.gain.setTargetAtTime(gone && this.ending === 'off' ? 0.05 : 0, now, this.ending === 'off' ? 0.8 : 0.3);
    this.windGain?.gain.setTargetAtTime(this.ending === 'outside' ? 0.12 : 0, now, 2.5);
    if (this.ending === 'outside' && now >= this.nextChirp) {
      this.chirp(now);
      this.nextChirp = now + 1.2 + Math.random() * 3;
    }

    while (this.nextNote < now + LOOKAHEAD) {
      if (WORK) this.scheduleHold(this.nextNote, this.stepIdx);
      else this.scheduleStep(this.nextNote, this.stepIdx);
      this.nextNote += this.step;
      this.stepIdx = (this.stepIdx + 1) % 64;
    }
    while (this.ringBus && this.nextRing < now + LOOKAHEAD) {
      this.ringPhrase(this.ringBus, this.nextRing);
      this.nextRing += RING_CYCLE;
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
        case 'boost':
          this.tone(220, 1320, 0.45, 'sawtooth', 0.09);
          this.tone(440, 2640, 0.6, 'square', 0.04, 0.08);
          break;
        case 'smash':
          this.noiseHit(0.18, 2600, 0.3);
          break;
        case 'jump':
          this.tone(320, 520, 0.09, 'triangle', 0.06);
          break;
        case 'pad':
          if (e.kind === 'autoplay') {
            this.tone(660, 1320, 0.25, 'square', 0.05);
          } else {
            // Boing up, whoosh.
            this.tone(140, e.kind === 'bouncer' ? 900 : 620, 0.35, 'triangle', 0.1);
            this.noiseHit(0.5, 1800, 0.15);
          }
          break;
        case 'lift':
          this.tone(500, 900, 0.3, 'sine', 0.05);
          break;
        case 'thrill':
          // Rising arpeggio; quieter as the thrill wears off.
          this.tone(523, 1047, 0.4, 'sawtooth', 0.04 + 0.06 * e.tolerance);
          this.tone(784, 1568, 0.5, 'square', 0.02 + 0.04 * e.tolerance, 0.12);
          break;
        case 'empty':
          this.tone(440, 110, 1.6, 'sawtooth', 0.12);
          break;
        case 'gate':
          // Time drops out, then the scanner hums up the body.
          this.noiseHit(0.7, 2400, 0.35);
          this.tone(900, 90, 0.7, 'sawtooth', 0.1);
          this.tone(220, 1760, 2.2, 'sine', 0.05, 0.5);
          break;
        case 'gateEnd':
          this.noiseHit(0.3, 3200, 0.25);
          this.tone(140, 880, 0.35, 'sawtooth', 0.08);
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

  /** Work card arrival, one sound per app (and 'decline' for a hung-up call). */
  notify(kind: string): void {
    if (!this.ready) return;
    if (this.play(kind) !== null) return;
    const t = this.ctx!.currentTime;
    switch (kind) {
      case 'decline':
        this.tone(660, 330, 0.3, 'sine', 0.12);
        break;
      case 'chat':
        // Two dry wooden knocks, the second softer.
        this.knock(t, 1);
        this.knock(t + 0.075, 0.65);
        break;
      case 'sync':
        // Soft rising two-note pop.
        this.mallet(this.master, t, 740, 0.1);
        this.mallet(this.master, t + 0.09, 1108.7, 0.08);
        break;
      case 'mail':
        this.sweep(t, 0.28, 450, 3200, 0.22);
        this.tone(2200, 2200, 0.05, 'sine', 0.04, 0.26);
        break;
      case 'calendar':
        this.mallet(this.master, t, 1318.5, 0.1);
        this.mallet(this.master, t + 0.16, 987.8, 0.09);
        break;
      case 'ticket':
        this.tone(294, 294, 0.12, 'triangle', 0.16);
        break;
      case 'humbl':
        [0, 4, 9].forEach((n, i) => {
          const f = 659.25 * Math.pow(2, n / 12);
          this.tone(f, f * 1.03, 0.08, 'sine', 0.1, i * 0.07);
        });
        break;
      default:
        this.chime();
    }
  }

  /** Start or stop the incoming-call ring loop (Work mode). */
  ring(on: boolean): void {
    if (!this.ready) return;
    const ctx = this.ctx!;
    if (on && !this.ringBus) {
      this.ringBus = ctx.createGain();
      this.ringBus.gain.value = 1;
      this.ringBus.connect(this.master);
      // The sampled ringtone loops by itself; the synth phrase is the fallback.
      this.ringSrc = this.play('ring', this.ringBus, true);
      this.nextRing = this.ringSrc ? Infinity : ctx.currentTime + 0.02;
    } else if (!on && this.ringBus) {
      // Phrases are scheduled ahead: fade the bus instead of waiting them out.
      const bus = this.ringBus;
      const src = this.ringSrc;
      this.ringBus = null;
      this.ringSrc = null;
      bus.gain.setTargetAtTime(0, ctx.currentTime, 0.02);
      setTimeout(() => {
        src?.stop();
        bus.disconnect();
      }, 400);
    }
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

  /** Work mode: elevator hold music. Soft chord pad, walking bass, a vibraphone line. */
  private scheduleHold(t: number, i: number): void {
    const bar = Math.floor(i / 16);
    const s = i % 16;
    const root = HOLD_ROOTS[bar] * this.pitch;
    const chord = HOLD_CHORDS[bar];
    if (s === 0) for (const r of chord) this.note(t, root * 4 * r, this.step * 15, 'triangle', 0.022);
    if (s % 8 === 0) this.note(t, root * 2, this.step * 5, 'sine', 0.16);
    if (s % 8 === 4) this.note(t, root * 3, this.step * 3, 'sine', 0.1);
    if (s % 4 === 2) this.hat(t, 0.035);
    for (const [at, tone, oct] of HOLD_MELODY) {
      if (at === s) this.note(t, root * oct * chord[tone] / 2, this.step * 3, 'sine', 0.05);
    }
  }

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

  private hat(t: number, vol = 0.12): void {
    const ctx = this.ctx!;
    const src = ctx.createBufferSource();
    src.buffer = this.noise;
    const f = ctx.createBiquadFilter();
    f.type = 'highpass';
    f.frequency.value = 7000;
    const g = ctx.createGain();
    g.gain.setValueAtTime(vol, t);
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

  // ---------- office sounds (Work mode) ----------

  private loadSamples(ctx: AudioContext): void {
    for (const name of SAMPLES) {
      fetch(`${import.meta.env.BASE_URL}assets/sfx/${name}.mp3`)
        .then((r) => r.arrayBuffer())
        .then((b) => ctx.decodeAudioData(b))
        .then((buf) => this.samples.set(name, buf))
        .catch(() => {
          // Missing or undecodable: the synth fallback plays instead.
        });
    }
  }

  /** Play a loaded sample; false if it isn't loaded (or isn't a sample). */
  private play(name: string, out: AudioNode = this.master, loop = false): AudioBufferSourceNode | null {
    const buf = this.samples.get(name);
    if (!buf) return null;
    const ctx = this.ctx!;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.loop = loop;
    const g = ctx.createGain();
    g.gain.value = SAMPLE_VOL[name] ?? 0.5;
    src.connect(g).connect(out);
    src.start();
    return src;
  }

  /** One wooden knock: a pitched-down thump plus a band-passed click. */
  private knock(t: number, vol: number): void {
    const ctx = this.ctx!;
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.frequency.setValueAtTime(210, t);
    o.frequency.exponentialRampToValueAtTime(120, t + 0.06);
    g.gain.setValueAtTime(0.45 * vol, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.07);
    o.connect(g).connect(this.master);
    o.start(t);
    o.stop(t + 0.09);
    const src = ctx.createBufferSource();
    src.buffer = this.noise;
    const f = ctx.createBiquadFilter();
    f.type = 'bandpass';
    f.frequency.value = 1900;
    f.Q.value = 3;
    const gn = ctx.createGain();
    gn.gain.setValueAtTime(0.5 * vol, t);
    gn.gain.exponentialRampToValueAtTime(0.0001, t + 0.03);
    src.connect(f).connect(gn).connect(this.master);
    src.start(t, Math.random() * 0.5, 0.04);
  }

  /** Band-passed noise swept from `from` to `to` Hz: the sent/received whoosh. */
  private sweep(t: number, dur: number, from: number, to: number, vol: number): void {
    const ctx = this.ctx!;
    const src = ctx.createBufferSource();
    src.buffer = this.noise;
    const f = ctx.createBiquadFilter();
    f.type = 'bandpass';
    f.Q.value = 2.5;
    f.frequency.setValueAtTime(from, t);
    f.frequency.exponentialRampToValueAtTime(to, t + dur);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(vol, t + dur * 0.6);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    src.connect(f).connect(g).connect(this.master);
    src.start(t, Math.random() * 0.5, dur + 0.05);
  }

  /** Marimba-ish struck note: fundamental, a quiet 4x partial and a mallet tick. */
  private mallet(out: AudioNode, t: number, f: number, vol: number): void {
    const ctx = this.ctx!;
    const parts: [number, number, number][] = [[1, 1, 0.45], [4, 0.22, 0.12], [9.2, 0.08, 0.03]];
    for (const [mul, amp, dur] of parts) {
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.frequency.value = f * mul;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(vol * amp, t + 0.005);
      g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      o.connect(g).connect(out);
      o.start(t);
      o.stop(t + dur + 0.02);
    }
  }

  private ringPhrase(out: AudioNode, t: number): void {
    for (const [n, at] of RING_NOTES) this.mallet(out, t + at, 523.25 * Math.pow(2, n / 12), 0.16);
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
