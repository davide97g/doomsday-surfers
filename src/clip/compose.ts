// Draws the clip's frames on a 9:16 canvas: the WebGL frame, cropped to fill,
// plus our own redraws of what lives in HTML (pop-ups, the reel panel, the
// HUD), the reel-style caption, "PART 2 →", and the @handle watermark. The end
// slate is drawn here too, frame by frame, from the death copy and the receipt.

import { content } from '../content/content';
import { TUNING } from '../sim/types';
import type { World } from '../sim/world';

const C = TUNING.clip;
const SANS = 'system-ui, -apple-system, "SF Pro Rounded", sans-serif';

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

function wrap(ctx: CanvasRenderingContext2D, text: string, width: number): string[] {
  const out: string[] = [];
  for (const para of text.split('\n')) {
    let cur = '';
    for (const word of para.split(' ')) {
      const next = cur ? `${cur} ${word}` : word;
      if (cur && ctx.measureText(next).width > width) {
        out.push(cur);
        cur = word;
      } else cur = next;
    }
    out.push(cur);
  }
  return out;
}

export interface SlateInput {
  /** The last gameplay frame (already grey: the run ended in reality). */
  last: HTMLCanvasElement;
  receipt: HTMLCanvasElement;
  handle: string;
}

export class Compositor {
  readonly canvas = document.createElement('canvas');
  private readonly ctx: CanvasRenderingContext2D;
  caption = '';
  handle = '';

  constructor() {
    this.canvas.width = C.width;
    this.canvas.height = C.height;
    this.ctx = this.canvas.getContext('2d')!;
  }

  /** One gameplay frame. Call right after the WebGL render, in the same task. */
  frame(game: HTMLCanvasElement, w: World, part2: boolean): void {
    const ctx = this.ctx;
    const W = C.width;
    const H = C.height;
    // Fill the frame: the phone screen is taller than 9:16, so crop top and bottom.
    const s = Math.max(W / game.width, H / game.height);
    const dw = game.width * s;
    const dh = game.height * s;
    const ox = (W - dw) / 2;
    const oy = (H - dh) / 2;
    ctx.drawImage(game, ox, oy, dw, dh);
    // CSS px -> clip px (the game canvas fills the viewport).
    const k = dw / game.clientWidth;
    this.popups(k, ox, oy);
    this.hud(w);
    this.captionBox();
    if (part2) this.tag(content.clip.part2, W - 16, 150, 'right');
    this.watermark();
  }

  private popups(k: number, ox: number, oy: number): void {
    const ctx = this.ctx;
    const reel = document.querySelector<HTMLElement>('.reel:not(.hidden)');
    const video = reel?.querySelector('video');
    if (reel && video && video.readyState >= 2) {
      const r = reel.getBoundingClientRect();
      ctx.save();
      roundRect(ctx, ox + r.left * k, oy + r.top * k, r.width * k, r.height * k, 14);
      ctx.clip();
      ctx.drawImage(video, ox + r.left * k, oy + r.top * k, r.width * k, r.height * k);
      ctx.restore();
    }
    for (const el of document.querySelectorAll<HTMLElement>('.notif:not(.leaving)')) {
      const r = el.getBoundingClientRect();
      if (r.width === 0) continue;
      const x = ox + r.left * k;
      const y = oy + r.top * k;
      const w = r.width * k;
      const h = r.height * k;
      ctx.fillStyle = 'rgba(28,24,38,0.92)';
      roundRect(ctx, x, y, w, h, 16);
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,46,136,0.8)';
      ctx.lineWidth = 2;
      ctx.stroke();
      const app = el.querySelector('b')?.textContent ?? '';
      const text = (el.querySelector('.notif-text, .wc-text, .wc-body, .wc-msg')?.textContent ?? el.textContent ?? '').trim();
      ctx.fillStyle = 'rgba(244,242,250,0.65)';
      ctx.font = `600 13px ${SANS}`;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      ctx.fillText(app, x + 14, y + 10, w - 28);
      ctx.fillStyle = '#fff';
      ctx.font = `800 17px ${SANS}`;
      wrap(ctx, text, w - 28)
        .slice(0, Math.max(1, Math.floor((h - 36) / 21)))
        .forEach((line, i) => ctx.fillText(line, x + 14, y + 30 + i * 21, w - 28));
    }
  }

  /** Distance and the dopamine battery, redrawn (the real HUD is HTML). */
  private hud(w: World): void {
    const ctx = this.ctx;
    const W = C.width;
    ctx.textBaseline = 'top';
    ctx.textAlign = 'left';
    ctx.fillStyle = '#fff';
    ctx.font = `900 30px ${SANS}`;
    ctx.fillText(`${Math.floor(w.d)}m`, 18, 20);
    const pct = Math.max(0, Math.min(1, w.dopamine / w.t.dopamine.max));
    const bw = 64;
    const bx = W / 2 - bw / 2 - 20;
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2.5;
    roundRect(ctx, bx, 24, bw, 26, 7);
    ctx.stroke();
    ctx.fillStyle = pct > 0.25 ? '#00e1ff' : '#ff2e3b';
    roundRect(ctx, bx + 4, 28, (bw - 8) * pct, 18, 4);
    ctx.fill();
    ctx.fillStyle = '#fff';
    ctx.font = `800 20px ${SANS}`;
    ctx.fillText(`${Math.round(pct * 100)}%`, bx + bw + 10, 27);
  }

  /** TikTok's classic text label: black on a white box, top third. */
  private captionBox(): void {
    if (!this.caption) return;
    const ctx = this.ctx;
    const W = C.width;
    ctx.font = `800 26px ${SANS}`;
    const lines = wrap(ctx, this.caption, W - 120);
    const lh = 34;
    const top = 96;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    lines.forEach((line, i) => {
      const tw = ctx.measureText(line).width;
      ctx.fillStyle = '#fff';
      roundRect(ctx, W / 2 - tw / 2 - 12, top + i * lh - 4, tw + 24, lh + 2, 8);
      ctx.fill();
      ctx.fillStyle = '#111';
      ctx.fillText(line, W / 2, top + i * lh);
    });
  }

  private tag(text: string, x: number, y: number, align: CanvasTextAlign): void {
    const ctx = this.ctx;
    ctx.font = `900 22px ${SANS}`;
    ctx.textAlign = align;
    ctx.textBaseline = 'top';
    ctx.lineWidth = 5;
    ctx.strokeStyle = '#000';
    ctx.strokeText(text, x, y);
    ctx.fillStyle = '#fff';
    ctx.fillText(text, x, y);
  }

  private watermark(): void {
    const ctx = this.ctx;
    ctx.globalAlpha = 0.75;
    this.tag(`${this.handle} · ${content.report.game}`, 16, C.height - 44, 'left');
    ctx.globalAlpha = 1;
  }

  /** End slate frame `t` seconds in: the death line, then the receipt, then the call to action. */
  slate(t: number, s: SlateInput): void {
    const ctx = this.ctx;
    const W = C.width;
    const H = C.height;
    ctx.drawImage(s.last, 0, 0, W, H);
    ctx.fillStyle = `rgba(12,12,14,${Math.min(0.78, 0.3 + t * 0.6)})`;
    ctx.fillRect(0, 0, W, H);
    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
    ctx.fillStyle = '#d9d9de';
    ctx.font = `900 40px ${SANS}`;
    const fade = (from: number) => Math.max(0, Math.min(1, (t - from) / 0.35));
    ctx.globalAlpha = fade(0.15);
    ctx.fillText(content.death.line1, W / 2, 118);
    ctx.globalAlpha = fade(0.9);
    ctx.fillText(content.death.line2, W / 2, 170);
    // The receipt slides up into place.
    const k = fade(1.4);
    if (k > 0) {
      const r = s.receipt;
      const boxH = H - 340;
      const sc = Math.min((W - 90) / r.width, boxH / r.height);
      const rw = r.width * sc;
      const rh = r.height * sc;
      ctx.globalAlpha = k;
      ctx.save();
      ctx.translate(W / 2, 200 + rh / 2 + (1 - k) * 80);
      ctx.rotate((-1.6 * Math.PI) / 180);
      ctx.shadowColor = 'rgba(0,0,0,0.6)';
      ctx.shadowBlur = 30;
      ctx.drawImage(r, -rw / 2, -rh / 2, rw, rh);
      ctx.restore();
    }
    ctx.globalAlpha = fade(2.3);
    this.tag(`${content.clip.cta} · ${s.handle}`, W / 2, H - 112, 'center');
    this.tag(`${content.report.game} · ${content.report.hashtag}`, W / 2, H - 76, 'center');
    ctx.globalAlpha = 1;
  }
}
