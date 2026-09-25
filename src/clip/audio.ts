// Listens to the game's master bus and keeps the last few seconds of PCM, on
// the same clock as the video (performance.now() seconds), so a clip segment
// can take its matching audio. ScriptProcessor is deprecated but it is the one
// tap that works everywhere without shipping a worklet file.

const BLOCK = 4096;

interface Block {
  t: number;
  l: Float32Array;
  r: Float32Array;
}

export class AudioTap {
  readonly sampleRate: number;
  private blocks: Block[] = [];
  /** performance.now()/1000 minus AudioContext time. */
  private readonly offset: number;

  constructor(ctx: AudioContext, node: AudioNode, private readonly keep: number) {
    this.sampleRate = ctx.sampleRate;
    this.offset = performance.now() / 1000 - ctx.currentTime;
    const sp = ctx.createScriptProcessor(BLOCK, 2, 2);
    const mute = ctx.createGain();
    mute.gain.value = 0;
    node.connect(sp);
    // A ScriptProcessor only runs while connected to the destination; muted so nothing doubles.
    sp.connect(mute).connect(ctx.destination);
    sp.onaudioprocess = (e) => {
      const b = e.inputBuffer;
      const t = e.playbackTime + this.offset;
      this.blocks.push({ t, l: b.getChannelData(0).slice(), r: (b.numberOfChannels > 1 ? b.getChannelData(1) : b.getChannelData(0)).slice() });
      this.trim(t);
    };
  }

  private held: { from: number; to: number }[] = [];

  /** Keep [from, to] around even after it falls out of the rolling window (a highlight). */
  hold(from: number, to: number): void {
    this.held.push({ from, to });
  }

  release(): void {
    this.held = [];
  }

  private trim(now: number): void {
    const dur = BLOCK / this.sampleRate;
    this.blocks = this.blocks.filter((b) => b.t + dur > now - this.keep || this.held.some((h) => b.t + dur > h.from && b.t < h.to));
  }

  /** Stereo PCM for [from, to] (clip clock), silence where nothing was captured. */
  slice(from: number, to: number): [Float32Array, Float32Array] {
    const n = Math.max(0, Math.round((to - from) * this.sampleRate));
    const l = new Float32Array(n);
    const r = new Float32Array(n);
    for (const b of this.blocks) {
      const start = Math.round((b.t - from) * this.sampleRate);
      for (let i = 0; i < b.l.length; i++) {
        const j = start + i;
        if (j < 0 || j >= n) continue;
        l[j] = b.l[i];
        r[j] = b.r[i];
      }
    }
    return [l, r];
  }
}
