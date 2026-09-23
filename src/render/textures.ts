// Procedural canvas textures for the grey-box "feed world".
// Placeholder art: these get replaced by Blender assets later, but they already
// sell the idea that you're running on top of an endless feed.

import * as THREE from 'three';
import content from '../config/content.json';
import { fill, seeded } from '../content/templates';

const PALETTE = ['#ff2e88', '#7b2eff', '#00e1ff', '#ffcc00', '#ff5a1f', '#1fff8f', '#ff3b3b', '#4d7cff'];

const HANDLES = content.pools.handle;
const ADS = content.brands;

/** Feed posts live in one atlas so the ground and towers draw in one call each. */
export const FEED_ATLAS = { cols: 4, rows: 4, cellW: 256, cellH: 540 };

function canvas(w: number, h: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d')!;
  return [c, ctx];
}

function tex(c: HTMLCanvasElement): THREE.CanvasTexture {
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  t.generateMipmaps = true;
  t.minFilter = THREE.LinearMipmapLinearFilter;
  return t;
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

function heart(ctx: CanvasRenderingContext2D, x: number, y: number, s: number): void {
  ctx.beginPath();
  ctx.moveTo(x, y + s * 0.3);
  ctx.bezierCurveTo(x, y, x - s * 0.5, y, x - s * 0.5, y + s * 0.3);
  ctx.bezierCurveTo(x - s * 0.5, y + s * 0.6, x, y + s * 0.8, x, y + s);
  ctx.bezierCurveTo(x, y + s * 0.8, x + s * 0.5, y + s * 0.6, x + s * 0.5, y + s * 0.3);
  ctx.bezierCurveTo(x + s * 0.5, y, x, y, x, y + s * 0.3);
  ctx.fill();
}

/** All feed posts (ground tiles and tower faces), one per atlas cell, row-major from the top. */
export function makeFeedAtlas(): THREE.CanvasTexture {
  const { cols, rows, cellW, cellH } = FEED_ATLAS;
  const [c, ctx] = canvas(cols * cellW, rows * cellH);
  const rand = seeded(1234);
  for (let i = 0; i < cols * rows; i++) {
    ctx.save();
    ctx.translate((i % cols) * cellW, Math.floor(i / cols) * cellH);
    const caption = fill(content.feed.captions[i % content.feed.captions.length], {}, rand);
    drawFeedPost(ctx, i, HANDLES[i % HANDLES.length], caption);
    ctx.restore();
  }
  return tex(c);
}

function drawFeedPost(ctx: CanvasRenderingContext2D, i: number, handle: string, caption: string): void {
  const W = FEED_ATLAS.cellW;
  const H = FEED_ATLAS.cellH;
  const a = PALETTE[i % PALETTE.length];
  const b = PALETTE[(i * 3 + 2 + Math.floor(i / PALETTE.length)) % PALETTE.length];

  ctx.fillStyle = '#0d0b14';
  ctx.fillRect(0, 0, W, H);

  // Header: avatar + handle.
  ctx.fillStyle = a;
  ctx.beginPath();
  ctx.arc(30, 32, 16, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#e9e6f5';
  ctx.font = 'bold 17px system-ui, sans-serif';
  ctx.fillText(handle, 56, 38);

  // Media block with gradient + shapes.
  const g = ctx.createLinearGradient(0, 60, W, 400);
  g.addColorStop(0, a);
  g.addColorStop(1, b);
  ctx.fillStyle = g;
  roundRect(ctx, 10, 60, W - 20, 330, 14);
  ctx.fill();
  ctx.globalAlpha = 0.35;
  ctx.fillStyle = '#ffffff';
  for (let k = 0; k < 4; k++) {
    ctx.beginPath();
    ctx.arc(40 + ((i * 53 + k * 71) % 180), 110 + ((i * 37 + k * 89) % 240), 18 + ((i + k) % 4) * 14, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  // Play triangle.
  ctx.fillStyle = 'rgba(255,255,255,0.85)';
  ctx.beginPath();
  ctx.moveTo(W / 2 - 20, 200);
  ctx.lineTo(W / 2 + 26, 225);
  ctx.lineTo(W / 2 - 20, 250);
  ctx.fill();

  // Actions row.
  ctx.fillStyle = '#ff2e63';
  heart(ctx, 30, 406, 26);
  ctx.fillStyle = '#e9e6f5';
  ctx.font = 'bold 15px system-ui, sans-serif';
  ctx.fillText(`${(i * 97 + 13) % 999}K`, 52, 426);
  ctx.strokeStyle = '#e9e6f5';
  ctx.lineWidth = 3;
  roundRect(ctx, 110, 406, 26, 20, 6);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(180, 426);
  ctx.lineTo(200, 406);
  ctx.lineTo(210, 426);
  ctx.stroke();

  // Caption lines.
  ctx.fillStyle = '#c9c4dd';
  ctx.font = '16px system-ui, sans-serif';
  ctx.fillText(caption, 14, 466, W - 28);
  ctx.fillStyle = '#4a4560';
  roundRect(ctx, 14, 482, 170, 10, 5);
  ctx.fill();
  roundRect(ctx, 14, 502, 110, 10, 5);
  ctx.fill();
}

/** Low barrier: a fat notification pill lying across the lane. */
export function makeNotification(i: number): THREE.CanvasTexture {
  const [c, ctx] = canvas(512, 128);
  ctx.fillStyle = '#f4f2fa';
  roundRect(ctx, 0, 0, 512, 128, 40);
  ctx.fill();
  ctx.fillStyle = PALETTE[i % PALETTE.length];
  roundRect(ctx, 22, 24, 80, 80, 20);
  ctx.fill();
  ctx.fillStyle = '#16131f';
  ctx.font = 'bold 34px system-ui, sans-serif';
  const titles = content.feed.notificationTitles;
  ctx.fillText(titles[i % titles.length], 124, 62);
  ctx.fillStyle = '#6b6680';
  ctx.font = '26px system-ui, sans-serif';
  ctx.fillText('now · tap to see', 124, 100);
  ctx.fillStyle = '#ff2e3b';
  ctx.beginPath();
  ctx.arc(470, 64, 26, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#fff';
  ctx.font = 'bold 28px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(String(((i * 7) % 98) + 1), 470, 74);
  return tex(c);
}

/** High barrier: a hanging banner ad for an invented brand. */
export function makeAd(i: number): THREE.CanvasTexture {
  const ad = ADS[i % ADS.length];
  const [c, ctx] = canvas(512, 256);
  ctx.fillStyle = ad.bg;
  ctx.fillRect(0, 0, 512, 256);
  ctx.fillStyle = ad.fg;
  ctx.textAlign = 'center';
  ctx.font = `900 ${ad.name.length > 9 ? 62 : 78}px system-ui, sans-serif`;
  ctx.fillText(ad.name, 256, 130, 480);
  ctx.font = 'bold 30px system-ui, sans-serif';
  ctx.fillText(ad.line, 256, 186, 480);
  ctx.textAlign = 'left';
  ctx.fillStyle = 'rgba(0,0,0,0.55)';
  roundRect(ctx, 14, 14, 58, 30, 6);
  ctx.fill();
  ctx.fillStyle = '#fff';
  ctx.font = 'bold 20px system-ui, sans-serif';
  ctx.fillText('AD', 28, 36);
  ctx.fillStyle = 'rgba(0,0,0,0.55)';
  roundRect(ctx, 368, 206, 130, 36, 8);
  ctx.fill();
  ctx.fillStyle = '#fff';
  ctx.font = 'bold 20px system-ui, sans-serif';
  ctx.fillText('Skip in 5', 384, 231);
  return tex(c);
}

/** Posts: giant sliding reels. Side + front faces. */
export function makeReel(i: number): THREE.CanvasTexture {
  const [c, ctx] = canvas(512, 256);
  const a = PALETTE[(i + 1) % PALETTE.length];
  const b = PALETTE[(i + 4) % PALETTE.length];
  const g = ctx.createLinearGradient(0, 0, 512, 256);
  g.addColorStop(0, a);
  g.addColorStop(1, b);
  ctx.fillStyle = '#0d0b14';
  ctx.fillRect(0, 0, 512, 256);
  ctx.fillStyle = g;
  roundRect(ctx, 8, 8, 496, 240, 18);
  ctx.fill();
  ctx.fillStyle = 'rgba(0,0,0,0.35)';
  ctx.fillRect(8, 206, 496, 42);
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(8, 242, 60 + ((i * 131) % 380), 6);
  ctx.font = '900 44px system-ui, sans-serif';
  ctx.fillText(content.feed.reelTitles[i % content.feed.reelTitles.length], 26, 70);
  ctx.font = 'bold 22px system-ui, sans-serif';
  ctx.fillText(HANDLES[(i + 3) % HANDLES.length], 26, 234);
  return tex(c);
}

export function makeReelFront(i: number): THREE.CanvasTexture {
  const [c, ctx] = canvas(256, 256);
  const a = PALETTE[(i + 1) % PALETTE.length];
  ctx.fillStyle = '#0d0b14';
  ctx.fillRect(0, 0, 256, 256);
  ctx.fillStyle = a;
  roundRect(ctx, 10, 10, 236, 236, 26);
  ctx.fill();
  ctx.fillStyle = 'rgba(255,255,255,0.95)';
  ctx.beginPath();
  ctx.moveTo(98, 78);
  ctx.lineTo(178, 128);
  ctx.lineTo(98, 178);
  ctx.fill();
  return tex(c);
}

/** Pickup sprites, one per content type: like, notification, reel, outrage. */
export function makeContent(type: number): THREE.CanvasTexture {
  const [c, ctx] = canvas(128, 128);
  switch (type) {
    case 0: // like
      ctx.fillStyle = '#ff2e63';
      heart(ctx, 64, 18, 96);
      break;
    case 1: {
      // notification badge
      ctx.fillStyle = '#ff2e3b';
      ctx.beginPath();
      ctx.arc(64, 64, 52, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#ffffff';
      ctx.font = '900 64px system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('1', 64, 87);
      break;
    }
    case 2: {
      // reel
      ctx.fillStyle = '#00e1ff';
      roundRect(ctx, 14, 8, 100, 112, 22);
      ctx.fill();
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.moveTo(50, 36);
      ctx.lineTo(90, 64);
      ctx.lineTo(50, 92);
      ctx.fill();
      break;
    }
    default: {
      // outrage: an angry face
      ctx.fillStyle = '#ff7a1f';
      ctx.beginPath();
      ctx.arc(64, 64, 54, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = '#2a0c00';
      ctx.lineWidth = 9;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(30, 40);
      ctx.lineTo(56, 52);
      ctx.moveTo(98, 40);
      ctx.lineTo(72, 52);
      ctx.moveTo(40, 94);
      ctx.quadraticCurveTo(64, 74, 88, 94);
      ctx.stroke();
      ctx.fillStyle = '#2a0c00';
      ctx.beginPath();
      ctx.arc(46, 62, 6, 0, Math.PI * 2);
      ctx.arc(82, 62, 6, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  return tex(c);
}

/** Healthy habit: the upright phone showing an incoming call from Mum. */
export function makeMumCall(): THREE.CanvasTexture {
  const [c, ctx] = canvas(256, 512);
  const g = ctx.createLinearGradient(0, 0, 0, 512);
  g.addColorStop(0, '#3d5a4c');
  g.addColorStop(1, '#1d2b25');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 256, 512);
  ctx.fillStyle = '#d8d2c4';
  ctx.beginPath();
  ctx.arc(128, 150, 54, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#f2efe6';
  ctx.textAlign = 'center';
  ctx.font = '900 44px system-ui, sans-serif';
  ctx.fillText('Mum', 128, 256);
  ctx.font = '24px system-ui, sans-serif';
  ctx.fillText('calling…', 128, 292);
  ctx.fillStyle = '#e0473b';
  ctx.beginPath();
  ctx.arc(66, 426, 34, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#35b86b';
  ctx.beginPath();
  ctx.arc(190, 426, 34, 0, Math.PI * 2);
  ctx.fill();
  return tex(c);
}

/** Healthy habit: a book cover. */
export function makeBookCover(): THREE.CanvasTexture {
  const [c, ctx] = canvas(256, 256);
  ctx.fillStyle = '#6b4a36';
  ctx.fillRect(0, 0, 256, 256);
  ctx.fillStyle = '#e9dcc2';
  ctx.textAlign = 'center';
  ctx.font = 'bold 30px Georgia, serif';
  ctx.fillText('A Long', 128, 110);
  ctx.fillText('Novel', 128, 146);
  ctx.strokeStyle = '#e9dcc2';
  ctx.lineWidth = 3;
  ctx.strokeRect(22, 22, 212, 212);
  return tex(c);
}
