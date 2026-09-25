// Auto-clip. Every run is encoded as it's played: a 9:16 H.264 stream
// (WebCodecs, hardware) of the composed frame (compose.ts) into a rolling
// buffer of the last few seconds. The run's best moments (a gate orbit, a
// loop, a ghost overtake) are copied out as highlights. At death it cuts a
// ~15 s montage: highlights (loops, drops and air in slow motion), the last
// seconds into grey, then an end slate with the death line and the receipt.
// Audio comes from the AudioTap where AudioEncoder exists (iOS 26+, Chrome);
// otherwise the clip is silent. Muxed to MP4 by Mediabunny, no re-encoding:
// every segment starts on a keyframe, and slow motion is just longer frame
// durations. No WebCodecs at all: no clip, the receipt still shares.

import type { BufferTarget } from 'mediabunny';
import { content } from '../content/content';
import { fill, pick } from '../content/templates';
import { TUNING } from '../sim/types';
import type { World } from '../sim/world';
import { AudioTap } from './audio';
import { Compositor } from './compose';

const C = TUNING.clip;
const CODECS = ['avc1.640028', 'avc1.4d0028', 'avc1.42e028', 'avc1.42e01f'];
const SLATE_FPS = 30;

export type HighlightKind = keyof typeof C.highlights;

interface Frame {
  chunk: EncodedVideoChunk;
  /** Capture time, performance.now() seconds. */
  t: number;
  key: boolean;
}

interface Segment {
  frames: Frame[];
  speed: number;
  audio: boolean;
}

interface Highlight {
  priority: number;
  t: number;
  seg: Segment;
}

const now = () => performance.now() / 1000;

export class ClipRecorder {
  /** False until WebCodecs is confirmed, and forever where it's missing. */
  ready = false;
  /** Set when the game can't hold its frame rate: capture at half rate from then on. */
  lowPower = false;
  private encoder: VideoEncoder | null = null;
  private decoderConfig: VideoDecoderConfig | null = null;
  private frames: Frame[] = [];
  /** Where encoder output goes: the rolling buffer, or the slate being built. */
  private sink: Frame[] | null = null;
  private highlights: Highlight[] = [];
  private pending: { kind: HighlightKind; t: number }[] = [];
  private readonly compose = new Compositor();
  private tap: AudioTap | null = null;
  private recording = false;
  private lastCapture = -1;
  private sinceKey = Infinity;
  private deathAt = 0;
  private readonly last = document.createElement('canvas');
  private cache: Promise<Blob | null> | null = null;

  constructor() {
    this.last.width = C.width;
    this.last.height = C.height;
    void this.init();
  }

  private async init(): Promise<void> {
    if (typeof VideoEncoder === 'undefined' || typeof VideoFrame === 'undefined') return;
    for (const codec of CODECS) {
      const config: VideoEncoderConfig = {
        codec,
        width: C.width,
        height: C.height,
        bitrate: C.bitrate,
        framerate: C.fps,
        latencyMode: 'realtime',
        avc: { format: 'avc' },
      };
      try {
        if (!(await VideoEncoder.isConfigSupported(config)).supported) continue;
        this.encoder = new VideoEncoder({
          output: (chunk, meta) => {
            if (meta?.decoderConfig) this.decoderConfig = meta.decoderConfig;
            const f = { chunk, t: chunk.timestamp / 1e6, key: chunk.type === 'key' };
            (this.sink ?? this.frames).push(f);
          },
          error: (e) => {
            console.warn('clip encoder failed, clips off', e);
            this.ready = false;
          },
        });
        this.encoder.configure(config);
        this.ready = true;
        return;
      } catch {
        // Try the next profile.
      }
    }
  }

  /** Hook the game's audio once it exists (it starts on the first gesture). */
  listen(out: { ctx: AudioContext; node: AudioNode } | null): void {
    if (!this.tap && out && typeof AudioEncoder !== 'undefined') this.tap = new AudioTap(out.ctx, out.node, C.keep);
  }

  /** A new run: empty buffers, a new caption. */
  startRun(handle: string): void {
    this.frames = [];
    this.highlights = [];
    this.pending = [];
    this.cache = null;
    this.tap?.release();
    this.sinceKey = Infinity;
    this.compose.caption = fill(pick(content.clip.captions));
    this.compose.handle = handle;
    this.recording = this.ready;
  }

  /** Revived: keep everything, carry on recording. */
  resume(): void {
    this.cache = null;
    this.sinceKey = Infinity;
    this.recording = this.ready;
  }

  /** The run ended (the fade into grey is already in the buffer). */
  stop(): void {
    if (!this.recording) return;
    this.recording = false;
    this.deathAt = now();
    this.last.getContext('2d')!.drawImage(this.compose.canvas, 0, 0);
  }

  mark(kind: HighlightKind): void {
    if (this.recording) this.pending.push({ kind, t: now() });
  }

  /** Call right after the WebGL render, in the same task (the drawing buffer is still valid). */
  capture(game: HTMLCanvasElement, w: World): void {
    const enc = this.encoder;
    if (!this.recording || !enc || enc.state !== 'configured') return;
    const t = now();
    const fps = this.lowPower ? C.fps / 2 : C.fps;
    if (t - this.lastCapture < 1 / fps - 0.002) return;
    // A slow device: drop frames rather than queue them.
    if (enc.encodeQueueSize > 3) return;
    this.lastCapture = t;
    this.compose.frame(game, w, w.revivesLeft < w.t.revive.perRun);
    const key = this.sinceKey >= C.keyEvery;
    this.sinceKey = key ? 0 : this.sinceKey + 1 / fps;
    const vf = new VideoFrame(this.compose.canvas, { timestamp: Math.round(t * 1e6) });
    enc.encode(vf, { keyFrame: key });
    vf.close();
    this.harvest(t);
  }

  /** Copy finished highlight windows out of the rolling buffer, then trim it. */
  private harvest(t: number): void {
    this.pending = this.pending.filter((p) => {
      const h = C.highlights[p.kind];
      if (t < p.t + h.after + 0.1) return true;
      const seg = this.cut(p.t - h.before, p.t + h.after, h.speed);
      if (seg) this.keep({ priority: h.priority, t: p.t, seg });
      return false;
    });
    const oldest = Math.min(t - C.keep, ...this.pending.map((p) => p.t - C.highlights[p.kind].before - 1));
    let i = 0;
    while (i < this.frames.length && this.frames[i].t < oldest) i++;
    // Never start the buffer on a delta frame.
    while (i > 0 && !this.frames[i]?.key) i--;
    if (i > 0) this.frames.splice(0, i);
  }

  private keep(h: Highlight): void {
    this.highlights.push(h);
    this.highlights.sort((a, b) => b.priority - a.priority || b.t - a.t);
    this.highlights.length = Math.min(this.highlights.length, C.maxHighlights);
    const f = h.seg.frames;
    this.tap?.hold(f[0].t, f[f.length - 1].t + 0.1);
  }

  /** Frames from the last keyframe at or before `from` up to `to`. */
  private cut(from: number, to: number, speed: number): Segment | null {
    const fr = this.frames;
    let i = fr.findIndex((f) => f.t > from);
    if (i < 0) return null;
    while (i > 0 && !fr[i].key) i--;
    if (!fr[i].key) i = fr.findIndex((f, j) => j >= i && f.key);
    if (i < 0) return null;
    const frames: Frame[] = [];
    for (let j = i; j < fr.length && fr[j].t <= to; j++) frames.push(fr[j]);
    return frames.length > 1 ? { frames, speed, audio: true } : null;
  }

  /** The montage as an MP4 (cached per death). Start it as soon as the death screen shows. */
  build(receipt: HTMLCanvasElement, handle: string): Promise<Blob | null> {
    this.cache ??= this.render(receipt, handle).catch((e) => {
      console.warn('clip render failed', e);
      return null;
    });
    return this.cache;
  }

  private async render(receipt: HTMLCanvasElement, handle: string): Promise<Blob | null> {
    const enc = this.encoder;
    if (!enc || !this.ready || this.recording) return null;
    await enc.flush();
    if (!this.decoderConfig) return null;
    const finalFrom = this.deathAt - C.finalSeconds;
    const final = this.cut(finalFrom, this.deathAt + 0.05, 1);
    if (!final) return null;
    const segs = this.highlights
      .filter((h) => h.seg.frames[h.seg.frames.length - 1].t < final.frames[0].t)
      .sort((a, b) => a.t - b.t)
      .map((h) => h.seg);
    segs.push(final, await this.slate(receipt, handle));

    // The muxer only loads when a clip is actually cut.
    const { BufferTarget, EncodedAudioPacketSource, EncodedPacket, EncodedVideoPacketSource, Mp4OutputFormat, Output } = await import('mediabunny');
    const output = new Output({ format: new Mp4OutputFormat({ fastStart: 'in-memory' }), target: new BufferTarget() });
    const video = new EncodedVideoPacketSource('avc');
    output.addVideoTrack(video, { frameRate: C.fps });
    const audio = this.tap ? await this.encodeAudio(segs) : null;
    const audioSrc = audio ? new EncodedAudioPacketSource('aac') : null;
    if (audioSrc) output.addAudioTrack(audioSrc);
    await output.start();

    let cursor = 0;
    let first = true;
    for (const seg of segs) {
      const f = seg.frames;
      for (let i = 0; i < f.length; i++) {
        const dur = this.frameDur(seg, i);
        const pkt = EncodedPacket.fromEncodedChunk(f[i].chunk).clone({ timestamp: cursor, duration: dur });
        await video.add(pkt, first ? { decoderConfig: this.decoderConfig } : undefined);
        first = false;
        cursor += dur;
      }
    }
    if (audio && audioSrc) {
      for (let i = 0; i < audio.chunks.length; i++) {
        await audioSrc.add(EncodedPacket.fromEncodedChunk(audio.chunks[i]), i === 0 ? { decoderConfig: audio.config } : undefined);
      }
    }
    await output.finalize();
    const buf = (output.target as BufferTarget).buffer;
    return buf ? new Blob([buf], { type: 'video/mp4' }) : null;
  }

  /** How long frame `i` of `seg` plays, slow motion included. */
  private frameDur(seg: Segment, i: number): number {
    const f = seg.frames;
    const gap = i + 1 < f.length ? f[i + 1].t - f[i].t : 1 / (seg.audio ? C.fps : SLATE_FPS);
    return Math.min(0.1, Math.max(1 / 240, gap)) / seg.speed;
  }

  /** The end slate, encoded after the run's frames (same encoder, later timestamps). */
  private async slate(receipt: HTMLCanvasElement, handle: string): Promise<Segment> {
    const enc = this.encoder!;
    const out: Frame[] = [];
    this.sink = out;
    const t0 = this.deathAt + 1;
    const n = Math.round(C.slateSeconds * SLATE_FPS);
    for (let i = 0; i < n; i++) {
      this.compose.slate(i / SLATE_FPS, { last: this.last, receipt, handle });
      const vf = new VideoFrame(this.compose.canvas, { timestamp: Math.round((t0 + i / SLATE_FPS) * 1e6) });
      enc.encode(vf, { keyFrame: i === 0 });
      vf.close();
      // Let the encoder breathe so the queue doesn't balloon.
      if (enc.encodeQueueSize > 8) await new Promise((r) => setTimeout(r, 0));
    }
    await enc.flush();
    this.sink = null;
    return { frames: out, speed: 1, audio: false };
  }

  /** One AAC track matching the video timeline: segment audio (slowed with the video, so pitched down), silence for the slate. */
  private async encodeAudio(segs: Segment[]): Promise<{ chunks: EncodedAudioChunk[]; config: AudioDecoderConfig } | null> {
    const tap = this.tap!;
    const sr = tap.sampleRate;
    const config: AudioEncoderConfig = { codec: 'mp4a.40.2', sampleRate: sr, numberOfChannels: 2, bitrate: 128000 };
    try {
      if (!(await AudioEncoder.isConfigSupported(config)).supported) return null;
    } catch {
      return null;
    }
    const parts: [Float32Array, Float32Array][] = [];
    let total = 0;
    for (const seg of segs) {
      const f = seg.frames;
      let dur = 0;
      for (let i = 0; i < f.length; i++) dur += this.frameDur(seg, i);
      const n = Math.round(dur * sr);
      const out: [Float32Array, Float32Array] = [new Float32Array(n), new Float32Array(n)];
      if (seg.audio) {
        const from = f[0].t;
        const [l, r] = tap.slice(from, from + dur * seg.speed + 0.05);
        // Stretch by 1/speed with linear interpolation: slow motion, lower pitch.
        for (let i = 0; i < n; i++) {
          const x = i * seg.speed;
          const i0 = Math.floor(x);
          const k = x - i0;
          out[0][i] = (l[i0] ?? 0) * (1 - k) + (l[i0 + 1] ?? 0) * k;
          out[1][i] = (r[i0] ?? 0) * (1 - k) + (r[i0 + 1] ?? 0) * k;
        }
      }
      parts.push(out);
      total += n;
    }
    const chunks: EncodedAudioChunk[] = [];
    let decoderConfig: AudioDecoderConfig | null = null;
    const encoder = new AudioEncoder({
      output: (chunk, meta) => {
        if (meta?.decoderConfig) decoderConfig = meta.decoderConfig;
        chunks.push(chunk);
      },
      error: (e) => console.warn('clip audio failed', e),
    });
    encoder.configure(config);
    const BLOCK = 4096;
    const l = new Float32Array(total);
    const r = new Float32Array(total);
    let o = 0;
    for (const [pl, pr] of parts) {
      l.set(pl, o);
      r.set(pr, o);
      o += pl.length;
    }
    for (let i = 0; i < total; i += BLOCK) {
      const n = Math.min(BLOCK, total - i);
      const data = new Float32Array(n * 2);
      data.set(l.subarray(i, i + n), 0);
      data.set(r.subarray(i, i + n), n);
      const ad = new AudioData({ format: 'f32-planar', sampleRate: sr, numberOfFrames: n, numberOfChannels: 2, timestamp: Math.round((i / sr) * 1e6), data });
      encoder.encode(ad);
      ad.close();
    }
    await encoder.flush();
    encoder.close();
    return decoderConfig ? { chunks, config: decoderConfig } : null;
  }
}
