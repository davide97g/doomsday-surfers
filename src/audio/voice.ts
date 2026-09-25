// The game's two signature sounds, built from oscillators like the rest:
// - the system voice: a small formant synthesiser that says the death line's
//   last word ("Disgusting." / "Unprofessional.") flat and bored, from a phoneme
//   list in the content bank;
// - the ping logo: three notes that end unresolved. Every push plays it, and
//   every clip ends on it.
// Both schedule onto any BaseAudioContext, so they play live and render
// offline (for the clip's end slate) from the same code.

type Vowel = { f: [number, number, number]; nasal?: boolean };
type Noise = { band: number; q: number; gain: number };

// Formants (Hz) for a low, flat, male-ish synthetic voice.
const VOICED: Record<string, Vowel> = {
  ih: { f: [400, 1900, 2550] },
  uh: { f: [640, 1190, 2390] },
  eh: { f: [530, 1840, 2480] },
  ah: { f: [730, 1090, 2440] },
  ax: { f: [500, 1500, 2500] },
  l: { f: [360, 1300, 2700] },
  r: { f: [420, 1300, 1600] },
  n: { f: [250, 1700, 2600], nasal: true },
  ng: { f: [250, 1000, 2400], nasal: true },
  m: { f: [250, 1000, 2200], nasal: true },
};
const FRICATIVES: Record<string, Noise> = {
  s: { band: 6200, q: 0.9, gain: 0.5 },
  sh: { band: 2800, q: 1.1, gain: 0.55 },
  f: { band: 4000, q: 0.4, gain: 0.25 },
};
// Plosives: a closure (silence), then a short burst.
const PLOSIVES: Record<string, { closure: number; band: number; voiced: boolean }> = {
  p: { closure: 0.06, band: 1100, voiced: false },
  t: { closure: 0.05, band: 4200, voiced: false },
  d: { closure: 0.03, band: 3000, voiced: true },
  g: { closure: 0.04, band: 1800, voiced: true },
};

const BASE_PITCH = 98;

function noiseBuffer(ctx: BaseAudioContext): AudioBuffer {
  const b = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
  const d = b.getChannelData(0);
  for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
  return b;
}

/** Says `phonemes` (e.g. ["d","ih","s","g","uh:","s","t","ih","ng"]; ':' = stressed, longer) at `t`. Returns its length. */
export function scheduleWord(ctx: BaseAudioContext, out: AudioNode, t: number, phonemes: readonly string[], vol = 0.5): number {
  // Voice source: a buzzy pulse through three parallel formant filters.
  const src = ctx.createOscillator();
  src.type = 'sawtooth';
  const voiceGain = ctx.createGain();
  voiceGain.gain.value = 0;
  src.connect(voiceGain);
  const formants = [0, 1, 2].map((i) => {
    const bp = ctx.createBiquadFilter();
    bp.type = 'bandpass';
    bp.Q.value = [9, 12, 14][i];
    const g = ctx.createGain();
    g.gain.value = [1, 0.55, 0.3][i];
    voiceGain.connect(bp).connect(g).connect(out);
    return bp;
  });
  const hiss = ctx.createBufferSource();
  hiss.buffer = noiseBuffer(ctx);
  hiss.loop = true;
  const hissBand = ctx.createBiquadFilter();
  hissBand.type = 'bandpass';
  const hissGain = ctx.createGain();
  hissGain.gain.value = 0;
  hiss.connect(hissBand).connect(hissGain).connect(out);

  let at = t;
  const n = phonemes.length;
  phonemes.forEach((raw, i) => {
    const stressed = raw.endsWith(':');
    const ph = raw.replace(':', '');
    // Flat and bored: a monotone that sags at the end, a small lift on the stress.
    const pitch = (BASE_PITCH + (stressed ? 10 : 0)) * (1 - 0.18 * (i / Math.max(1, n - 1)));
    src.frequency.setTargetAtTime(pitch, at, 0.03);
    const v = VOICED[ph];
    const fr = FRICATIVES[ph];
    const pl = PLOSIVES[ph];
    if (v) {
      const dur = (v.nasal ? 0.12 : 0.1) * (stressed ? 1.7 : 1) * (i === n - 1 ? 1.8 : 1);
      formants.forEach((bp, k) => bp.frequency.setTargetAtTime(v.f[k], at, 0.025));
      voiceGain.gain.setTargetAtTime(vol * (v.nasal ? 0.45 : 1), at, 0.02);
      hissGain.gain.setTargetAtTime(0, at, 0.01);
      at += dur;
    } else if (fr) {
      voiceGain.gain.setTargetAtTime(0, at, 0.015);
      hissBand.frequency.setValueAtTime(fr.band, at);
      hissBand.Q.setValueAtTime(fr.q, at);
      hissGain.gain.setTargetAtTime(vol * fr.gain, at, 0.015);
      at += 0.13;
      hissGain.gain.setTargetAtTime(0, at, 0.015);
    } else if (pl) {
      voiceGain.gain.setTargetAtTime(0, at, 0.008);
      at += pl.closure;
      hissBand.frequency.setValueAtTime(pl.band, at);
      hissBand.Q.setValueAtTime(1.2, at);
      hissGain.gain.setValueAtTime(vol * 0.6, at);
      hissGain.gain.setTargetAtTime(0, at + 0.012, 0.01);
      if (pl.voiced) voiceGain.gain.setTargetAtTime(vol * 0.5, at, 0.01);
      at += 0.02;
    }
  });
  voiceGain.gain.setTargetAtTime(0, at, 0.05);
  hissGain.gain.setTargetAtTime(0, at, 0.02);
  src.start(t);
  hiss.start(t);
  src.stop(at + 0.4);
  hiss.stop(at + 0.4);
  return at - t;
}

/** The ping logo: B5, E6, then D#6, left hanging. */
export function schedulePing(ctx: BaseAudioContext, out: AudioNode, t: number, vol = 0.12): number {
  const notes: [number, number, number][] = [
    [987.8, 0, 0.08],
    [1318.5, 0.09, 0.08],
    [1244.5, 0.2, 0.3],
  ];
  for (const [f, dt, dur] of notes) {
    for (const [mul, amp] of [
      [1, 1],
      [2.76, 0.18],
    ]) {
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.frequency.value = f * mul;
      g.gain.setValueAtTime(0.0001, t + dt);
      g.gain.exponentialRampToValueAtTime(vol * amp, t + dt + 0.006);
      g.gain.exponentialRampToValueAtTime(0.0001, t + dt + dur);
      o.connect(g).connect(out);
      o.start(t + dt);
      o.stop(t + dt + dur + 0.02);
    }
  }
  return 0.5;
}

/** Offline render of either sound, stereo PCM at `sampleRate` (for the clip's audio track). */
export async function renderSound(sampleRate: number, draw: (ctx: BaseAudioContext, out: AudioNode) => number, seconds: number): Promise<[Float32Array, Float32Array]> {
  const ctx = new OfflineAudioContext(2, Math.ceil(seconds * sampleRate), sampleRate);
  draw(ctx, ctx.destination);
  const buf = await ctx.startRendering();
  return [buf.getChannelData(0), buf.getChannelData(1)];
}
