// Procedural canvas textures for the grey-box "feed world".
// Placeholder art: these get replaced by Blender assets later, but they already
// sell the idea that you're running on top of an endless feed.
// Work mode draws an office suite instead (see the "Work mode" section):
// spreadsheets, slides, Calendar Tetris and mail threads, invented brands only.

import * as THREE from 'three';
import { content, mode, work } from '../content/content';
import { fill, seeded } from '../content/templates';

const PALETTE = ['#ff2e88', '#7b2eff', '#00e1ff', '#ffcc00', '#ff5a1f', '#1fff8f', '#ff3b3b', '#4d7cff'];

const HANDLES = content.pools.handle;
const ADS = content.brands;
const WORK = mode === 'work';
// Office-app accents (our own, matching the Work mode cards).
const OFFICE = ['#3b82f6', '#22a755', '#f59e0b', '#d9486c', '#2bb5a4', '#8b5cf6', '#ef4444', '#64748b'];

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
    if (WORK) drawOfficeCell(ctx, i, caption, rand);
    else drawFeedPost(ctx, i, HANDLES[i % HANDLES.length], caption);
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
  if (WORK) return makeMailSlab(i);
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
  roundRect(ctx, 14, 14, WORK ? 142 : 58, 30, 6);
  ctx.fill();
  ctx.fillStyle = '#fff';
  ctx.font = 'bold 20px system-ui, sans-serif';
  ctx.fillText(WORK ? 'SPONSORED' : 'AD', 28, 36);
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
  if (WORK) return makeDeck(i);
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
  if (WORK) return makeDeckFront(i);
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
  if (WORK) return makeOfficeContent(type);
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
  ctx.fillText(WORK ? 'Home' : 'Mum', 128, 256);
  ctx.font = '24px system-ui, sans-serif';
  ctx.fillText(WORK ? 'calling (again)…' : 'calling…', 128, 292);
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
  if (WORK) return makePtoForm();
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

/** The checkpoint gate's sign: a long thin strip of cold white type on black. */
export function makeGateSign(text: string): THREE.CanvasTexture {
  const [c, ctx] = canvas(1024, 96);
  ctx.fillStyle = '#05030a';
  ctx.fillRect(0, 0, 1024, 96);
  ctx.strokeStyle = 'rgba(255,255,255,0.35)';
  ctx.lineWidth = 3;
  ctx.strokeRect(6, 6, 1012, 84);
  ctx.fillStyle = '#f4f2fa';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.font = '800 46px ui-monospace, Menlo, monospace';
  ctx.fillText(text, 512, 50);
  return tex(c);
}

/** "Swipe up" ramp deck: stacked up-chevrons and the gesture hint, read from behind. */
export function makeRampFace(): THREE.CanvasTexture {
  const [c, ctx] = canvas(256, 512);
  const g = ctx.createLinearGradient(0, 512, 0, 0);
  g.addColorStop(0, '#12091f');
  g.addColorStop(1, '#2a0d3d');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 256, 512);
  ctx.strokeStyle = WORK ? '#ef4444' : '#ff2e88';
  ctx.lineWidth = 16;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  for (let i = 0; i < 4; i++) {
    const y = 150 + i * 90;
    ctx.globalAlpha = 1 - i * 0.2;
    ctx.beginPath();
    ctx.moveTo(58, y + 34);
    ctx.lineTo(128, y - 30);
    ctx.lineTo(198, y + 34);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
  ctx.fillStyle = '#f4f2fa';
  ctx.textAlign = 'center';
  ctx.font = '900 38px system-ui, sans-serif';
  ctx.fillText(WORK ? 'ESCALATE' : 'SWIPE UP', 128, 62);
  ctx.strokeStyle = 'rgba(255,255,255,0.35)';
  ctx.lineWidth = 4;
  ctx.strokeRect(8, 8, 240, 496);
  return tex(c);
}

/** Pull-to-refresh bouncer top: the spinner arrow everyone keeps dragging down. */
export function makeBouncerTop(): THREE.CanvasTexture {
  const [c, ctx] = canvas(256, 256);
  ctx.fillStyle = '#0d0b14';
  ctx.fillRect(0, 0, 256, 256);
  ctx.strokeStyle = '#00e1ff';
  ctx.lineWidth = 22;
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.arc(128, 128, 72, -Math.PI * 0.35, Math.PI * 1.35);
  ctx.stroke();
  // Arrow head at the start of the arc.
  const a = -Math.PI * 0.35;
  const hx = 128 + Math.cos(a) * 72;
  const hy = 128 + Math.sin(a) * 72;
  ctx.fillStyle = '#00e1ff';
  ctx.beginPath();
  ctx.moveTo(hx + 34, hy + 6);
  ctx.lineTo(hx - 12, hy - 30);
  ctx.lineTo(hx - 16, hy + 26);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = 'rgba(0,225,255,0.4)';
  ctx.lineWidth = 6;
  ctx.beginPath();
  ctx.arc(128, 128, 118, 0, Math.PI * 2);
  ctx.stroke();
  return tex(c);
}

/** Autoplay strip: forward chevrons with "Autoplay next", tiled along the lane. */
export function makeAutoplay(): THREE.CanvasTexture {
  const [c, ctx] = canvas(128, 256);
  ctx.fillStyle = '#000000';
  ctx.fillRect(0, 0, 128, 256);
  ctx.strokeStyle = '#ffffff';
  ctx.lineWidth = 14;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  for (let i = 0; i < 2; i++) {
    const y = 70 + i * 128;
    ctx.beginPath();
    ctx.moveTo(22, y + 28);
    ctx.lineTo(64, y - 22);
    ctx.lineTo(106, y + 28);
    ctx.stroke();
  }
  const t = tex(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}

// ---------- Work mode: the office suite ----------

function bars(ctx: CanvasRenderingContext2D, x: number, y: number, widths: number[], colour: string, h = 9, gap = 18): void {
  ctx.fillStyle = colour;
  widths.forEach((w, k) => {
    roundRect(ctx, x, y + k * gap, w, h, h / 2);
    ctx.fill();
  });
}

/** One atlas cell: a spreadsheet, a slide, a Calendar Tetris day or a mail thread. */
function drawOfficeCell(ctx: CanvasRenderingContext2D, i: number, caption: string, rand: () => number): void {
  const W = FEED_ATLAS.cellW;
  const H = FEED_ATLAS.cellH;
  const a = OFFICE[i % OFFICE.length];
  ctx.fillStyle = '#16171c';
  ctx.fillRect(0, 0, W, H);
  // Window title bar.
  ctx.fillStyle = '#23252c';
  ctx.fillRect(0, 0, W, 34);
  ctx.fillStyle = a;
  roundRect(ctx, 10, 9, 16, 16, 4);
  ctx.fill();
  ctx.fillStyle = '#c9ccd6';
  ctx.font = 'bold 14px system-ui, sans-serif';
  const kind = i % 4;
  const names = ['Budget_FINAL_v9.xlsx', 'Q3_Strategy_v7(2).pptx', 'Calendar · This week', `${work.cards.mail.app} · Focused`];
  ctx.fillText(names[kind], 34, 22, W - 44);

  if (kind === 0) {
    // Spreadsheet: a header row, a grid, numbers, a yellow highlight and a #REF!.
    const cw = 58;
    const ch = 26;
    ctx.fillStyle = '#1f6f45';
    ctx.fillRect(0, 34, W, ch);
    ctx.fillStyle = '#e8f5ec';
    ctx.font = 'bold 13px system-ui, sans-serif';
    ['A', 'B', 'C', 'D'].forEach((l, k) => ctx.fillText(l, 30 + k * cw, 52));
    ctx.font = '13px ui-monospace, Menlo, monospace';
    const err = Math.floor(rand() * 16);
    for (let r = 0; r < 18; r++) {
      const y = 34 + ch * (r + 1);
      if (r === 3 + (i % 5)) {
        ctx.fillStyle = 'rgba(245,200,40,0.35)';
        ctx.fillRect(22, y, W - 22, ch);
      }
      ctx.fillStyle = '#6b7080';
      ctx.fillText(String(r + 1), 4, y + 18);
      for (let k = 0; k < 4; k++) {
        const x = 22 + k * cw;
        ctx.fillStyle = r * 4 + k === err ? '#ff5a5a' : '#c9ccd6';
        const v = r * 4 + k === err ? '#REF!' : String(Math.floor(rand() * 9000 + 100));
        ctx.fillText(v, x + 6, y + 18, cw - 8);
      }
    }
    ctx.strokeStyle = '#2c2f38';
    ctx.lineWidth = 1;
    for (let r = 0; r <= 19; r++) {
      ctx.beginPath();
      ctx.moveTo(0, 34 + ch * r + 0.5);
      ctx.lineTo(W, 34 + ch * r + 0.5);
      ctx.stroke();
    }
    for (let k = 0; k <= 4; k++) {
      ctx.beginPath();
      ctx.moveTo(22 + k * cw + 0.5, 34);
      ctx.lineTo(22 + k * cw + 0.5, H);
      ctx.stroke();
    }
    ctx.fillStyle = '#e8f5ec';
    ctx.font = 'bold 14px ui-monospace, Menlo, monospace';
    ctx.fillText('=SUM(B2:B19)', 26, H - 12);
  } else if (kind === 1) {
    // Slide: coloured title band, bullets, a chart that proves nothing.
    ctx.fillStyle = '#f1f2f5';
    roundRect(ctx, 12, 48, W - 24, 300, 8);
    ctx.fill();
    ctx.fillStyle = a;
    ctx.fillRect(12, 48, W - 24, 58);
    ctx.fillStyle = '#ffffff';
    ctx.font = '900 20px system-ui, sans-serif';
    ctx.fillText(caption, 24, 84, W - 48);
    bars(ctx, 30, 126, [150, 120, 170, 90], '#9aa0ad');
    ctx.fillStyle = '#2b2f3a';
    for (let k = 0; k < 4; k++) {
      ctx.beginPath();
      ctx.arc(22, 130 + k * 18, 3, 0, Math.PI * 2);
      ctx.fill();
    }
    for (let k = 0; k < 5; k++) {
      const h = 30 + ((i * 17 + k * 29) % 90);
      ctx.fillStyle = OFFICE[(i + k) % OFFICE.length];
      ctx.fillRect(34 + k * 38, 330 - h, 26, h);
    }
    ctx.fillStyle = '#9aa0ad';
    ctx.font = 'bold 13px system-ui, sans-serif';
    ctx.fillText(`Slide ${3 + (i % 9)} of 94`, 16, 374);
    bars(ctx, 16, 400, [200, 160, 120], '#3a3d48', 10, 22);
  } else if (kind === 2) {
    // Calendar Tetris: overlapping meeting blocks, no gap for lunch.
    ctx.fillStyle = '#6b7080';
    ctx.font = '12px system-ui, sans-serif';
    for (let h = 0; h < 10; h++) {
      const y = 50 + h * 48;
      ctx.fillText(`${((h + 8) % 12) + 1}${h + 8 < 12 ? 'am' : 'pm'}`, 4, y + 4);
      ctx.fillStyle = '#2c2f38';
      ctx.fillRect(36, y, W - 40, 1);
      ctx.fillStyle = '#6b7080';
    }
    const titles = work.meeting.titles;
    let y = 52;
    let k = 0;
    while (y < H - 30) {
      const h = 40 + Math.floor(rand() * 3) * 24;
      const x = 40 + (k % 2) * 60;
      const col = OFFICE[(i + k) % OFFICE.length];
      ctx.fillStyle = col;
      ctx.globalAlpha = 0.85;
      roundRect(ctx, x, y, W - x - 8, h - 4, 6);
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.fillStyle = '#ffffff';
      ctx.font = 'bold 13px system-ui, sans-serif';
      ctx.fillText(titles[(i + k) % titles.length], x + 8, y + 18, W - x - 24);
      y += h - (k % 3 === 1 ? 18 : 0);
      k++;
    }
  } else {
    // Mail thread: unread rows, RE: RE: FW:, one flagged in red.
    const lines = work.cards.mail.lines;
    for (let r = 0; r < 9; r++) {
      const y = 44 + r * 54;
      ctx.fillStyle = r % 3 === 0 ? '#1d2230' : '#16171c';
      ctx.fillRect(0, y, W, 54);
      ctx.fillStyle = OFFICE[(i + r) % OFFICE.length];
      ctx.beginPath();
      ctx.arc(22, y + 26, 13, 0, Math.PI * 2);
      ctx.fill();
      if (r % 3 === 0) {
        ctx.fillStyle = '#3b82f6';
        ctx.fillRect(0, y, 4, 54);
      }
      ctx.fillStyle = '#e6e8ee';
      ctx.font = `${r % 3 === 0 ? 'bold ' : ''}14px system-ui, sans-serif`;
      ctx.fillText(fill(lines[(i + r) % lines.length].text, {}, rand), 44, y + 22, W - 54);
      bars(ctx, 44, y + 32, [120 + ((r * 37) % 60)], '#3a3d48', 8);
      if (r === (i % 7) + 1) {
        ctx.fillStyle = '#ef4444';
        ctx.font = 'bold 16px system-ui, sans-serif';
        ctx.fillText('!', W - 18, y + 22);
      }
    }
  }
}

/** Low barrier (Work): a fat mail pill, RE: RE: FW: and an unread count. */
function makeMailSlab(i: number): THREE.CanvasTexture {
  const [c, ctx] = canvas(512, 128);
  ctx.fillStyle = '#f4f5f8';
  roundRect(ctx, 0, 0, 512, 128, 28);
  ctx.fill();
  ctx.fillStyle = OFFICE[i % OFFICE.length];
  roundRect(ctx, 22, 24, 80, 80, 14);
  ctx.fill();
  ctx.fillStyle = '#ffffff';
  ctx.font = '900 46px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('@', 62, 80);
  ctx.textAlign = 'left';
  ctx.fillStyle = '#16131f';
  ctx.font = 'bold 34px system-ui, sans-serif';
  const titles = content.feed.notificationTitles;
  ctx.fillText(titles[i % titles.length], 124, 62, 300);
  ctx.fillStyle = '#6b6680';
  ctx.font = '24px system-ui, sans-serif';
  ctx.fillText('now · reply needed', 124, 100);
  ctx.fillStyle = '#ef4444';
  ctx.beginPath();
  ctx.arc(470, 64, 26, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#fff';
  ctx.font = 'bold 26px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(String(((i * 37) % 890) + 9), 470, 73, 46);
  return tex(c);
}

/** Posts (Work): sliding slide decks, a file name and a slide counter. */
function makeDeck(i: number): THREE.CanvasTexture {
  const [c, ctx] = canvas(512, 256);
  const a = OFFICE[(i + 1) % OFFICE.length];
  ctx.fillStyle = '#16171c';
  ctx.fillRect(0, 0, 512, 256);
  ctx.fillStyle = '#f1f2f5';
  roundRect(ctx, 8, 8, 496, 240, 12);
  ctx.fill();
  ctx.fillStyle = a;
  ctx.fillRect(8, 8, 496, 76);
  ctx.fillStyle = '#ffffff';
  ctx.font = '900 40px system-ui, sans-serif';
  ctx.fillText(`${content.feed.reelTitles[i % content.feed.reelTitles.length]}.pptx`, 24, 62, 464);
  bars(ctx, 30, 110, [300, 240, 330, 180], '#9aa0ad', 12, 26);
  ctx.fillStyle = '#2b2f3a';
  ctx.font = 'bold 20px system-ui, sans-serif';
  ctx.fillText(`Slide ${2 + (i % 7)} of 94 · Presenting`, 24, 234);
  return tex(c);
}

function makeDeckFront(i: number): THREE.CanvasTexture {
  const [c, ctx] = canvas(256, 256);
  ctx.fillStyle = '#16171c';
  ctx.fillRect(0, 0, 256, 256);
  ctx.fillStyle = OFFICE[(i + 1) % OFFICE.length];
  roundRect(ctx, 10, 10, 236, 236, 20);
  ctx.fill();
  // A pie chart that is 100% "synergy".
  ctx.fillStyle = 'rgba(255,255,255,0.95)';
  ctx.beginPath();
  ctx.moveTo(128, 128);
  ctx.arc(128, 128, 76, -Math.PI / 2, Math.PI * 1.1);
  ctx.fill();
  ctx.fillStyle = 'rgba(255,255,255,0.45)';
  ctx.beginPath();
  ctx.moveTo(128, 128);
  ctx.arc(128, 128, 76, Math.PI * 1.1, Math.PI * 1.5);
  ctx.fill();
  return tex(c);
}

/** Pickups (Work): a thumbs-up reaction, a ping badge, a calendar block, a reply-all arrow. */
function makeOfficeContent(type: number): THREE.CanvasTexture {
  const [c, ctx] = canvas(128, 128);
  ctx.textAlign = 'center';
  switch (type) {
    case 0: {
      ctx.fillStyle = '#f59e0b';
      roundRect(ctx, 10, 20, 108, 88, 44);
      ctx.fill();
      ctx.font = '64px system-ui, sans-serif';
      ctx.fillText('👍', 64, 88);
      break;
    }
    case 1: {
      ctx.fillStyle = '#d9486c';
      ctx.beginPath();
      ctx.arc(64, 64, 52, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#ffffff';
      ctx.font = '900 70px system-ui, sans-serif';
      ctx.fillText('@', 64, 88);
      break;
    }
    case 2: {
      ctx.fillStyle = '#2bb5a4';
      roundRect(ctx, 14, 14, 100, 100, 16);
      ctx.fill();
      ctx.fillStyle = '#0d3b35';
      ctx.fillRect(14, 14, 100, 26);
      ctx.fillStyle = '#ffffff';
      ctx.font = '900 50px system-ui, sans-serif';
      ctx.fillText('31', 64, 96);
      break;
    }
    default: {
      // Reply-all: two stacked back arrows.
      ctx.fillStyle = '#ef4444';
      ctx.beginPath();
      ctx.arc(64, 64, 54, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 9;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      for (const dx of [0, 18]) {
        ctx.beginPath();
        ctx.moveTo(52 + dx, 40);
        ctx.lineTo(30 + dx, 60);
        ctx.lineTo(52 + dx, 80);
        ctx.stroke();
      }
      ctx.beginPath();
      ctx.moveTo(34, 60);
      ctx.quadraticCurveTo(96, 56, 96, 94);
      ctx.stroke();
    }
  }
  return tex(c);
}

/** Healthy habit (Work): the PTO request form on top of the paper stack. */
function makePtoForm(): THREE.CanvasTexture {
  const [c, ctx] = canvas(256, 256);
  ctx.fillStyle = '#e7e3d8';
  ctx.fillRect(0, 0, 256, 256);
  ctx.fillStyle = '#3a3a3a';
  ctx.textAlign = 'center';
  ctx.font = 'bold 26px Georgia, serif';
  ctx.fillText('OUT OF', 128, 84);
  ctx.fillText('OFFICE', 128, 116);
  ctx.font = '15px Georgia, serif';
  ctx.fillText('Leave request form', 128, 144);
  ctx.strokeStyle = '#7a7a7a';
  ctx.lineWidth = 2;
  for (let k = 0; k < 3; k++) {
    ctx.beginPath();
    ctx.moveTo(40, 170 + k * 22);
    ctx.lineTo(216, 170 + k * 22);
    ctx.stroke();
  }
  ctx.strokeStyle = '#3a3a3a';
  ctx.lineWidth = 3;
  ctx.strokeRect(22, 22, 212, 212);
  return tex(c);
}

// ---------- set pieces ----------

/** A hand with six fingers: the AI-slop signature (people count them in the comments). */
function slopHand(ctx: CanvasRenderingContext2D, cx: number, cy: number, s: number, rand: () => number): void {
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate((rand() - 0.5) * 0.5);
  const skin = ctx.createRadialGradient(-s * 0.2, -s * 0.3, s * 0.1, 0, 0, s * 1.3);
  skin.addColorStop(0, '#ffe2cf');
  skin.addColorStop(1, '#d99a78');
  ctx.fillStyle = skin;
  for (let f = 0; f < 6; f++) {
    const a = -Math.PI / 2 + (f - 2.5) * 0.3;
    const len = s * (0.9 + 0.25 * Math.sin(f * 1.7));
    ctx.save();
    ctx.rotate(a + Math.PI / 2);
    ctx.beginPath();
    ctx.roundRect(-s * 0.1, -s * 0.35 - len, s * 0.2, len, s * 0.1);
    ctx.fill();
    ctx.restore();
  }
  ctx.beginPath();
  ctx.ellipse(0, 0, s * 0.62, s * 0.52, 0, 0, Math.PI * 2);
  ctx.fill();
  // Too-perfect gloss.
  ctx.fillStyle = 'rgba(255,255,255,0.35)';
  ctx.beginPath();
  ctx.ellipse(-s * 0.2, -s * 0.18, s * 0.22, s * 0.1, -0.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

/** Everything drips a little, the way slop does. */
function melt(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, rand: () => number): void {
  for (let i = 0; i < 16; i++) {
    const sx = x + rand() * w;
    const sw = 4 + rand() * 12;
    const drop = 6 + rand() * 26;
    ctx.globalAlpha = 0.55;
    ctx.drawImage(ctx.canvas, sx, y, sw, h, sx, y + drop, sw, h);
  }
  ctx.globalAlpha = 1;
}

/** The Slop zone's feed: six-fingered hands, engagement bait, typos, melting captions. */
export function makeSlopAtlas(): THREE.CanvasTexture {
  const { cols, rows, cellW: W, cellH: H } = FEED_ATLAS;
  const [c, ctx] = canvas(cols * W, rows * H);
  const rand = seeded(606);
  const captions = content.setPieces.slop.captions;
  for (let i = 0; i < cols * rows; i++) {
    const ox = (i % cols) * W;
    const oy = Math.floor(i / cols) * H;
    ctx.save();
    ctx.translate(ox, oy);
    ctx.fillStyle = '#0d0b14';
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = PALETTE[(i * 5) % PALETTE.length];
    ctx.beginPath();
    ctx.arc(30, 32, 16, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#e9e6f5';
    ctx.font = 'bold 17px system-ui, sans-serif';
    ctx.fillText(HANDLES[(i * 7 + 3) % HANDLES.length], 56, 38);
    // Oversaturated dreamy gradient, then the hand.
    const g = ctx.createLinearGradient(0, 60, W, 390);
    g.addColorStop(0, ['#ffb3e6', '#b3f0ff', '#ffe08a', '#c7b3ff'][i % 4]);
    g.addColorStop(1, ['#8affc1', '#ff9ab3', '#9ab8ff', '#ffc38a'][i % 4]);
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.roundRect(10, 60, W - 20, 330, 14);
    ctx.fill();
    slopHand(ctx, W / 2 + (rand() - 0.5) * 30, 250, 70 + rand() * 20, rand);
    ctx.fillStyle = '#ff2e63';
    ctx.font = 'bold 22px system-ui, sans-serif';
    ctx.fillText(`♥ ${400 + Math.floor(rand() * 599)}K`, 14, 430);
    ctx.fillStyle = '#f1eefb';
    ctx.font = 'bold 17px system-ui, sans-serif';
    const cap = captions[i % captions.length];
    const words = cap.split(' ');
    let line = '';
    let y = 468;
    for (const w of words) {
      if (ctx.measureText(`${line} ${w}`).width > W - 28 && line) {
        ctx.fillText(line, 14, y);
        line = w;
        y += 22;
      } else line = line ? `${line} ${w}` : w;
    }
    ctx.fillText(line, 14, y);
    ctx.restore();
    melt(ctx, ox + 12, oy + 300, W - 24, 200, rand);
  }
  return tex(c);
}

/** Reality leaking in at low dopamine: a sunset, a park bench, a friend waving, a dog that wants a walk. */
export function makeReality(i: number): THREE.CanvasTexture {
  const W = 512;
  const H = 720;
  const [c, ctx] = canvas(W, H);
  const rand = seeded(900 + i);
  const sky = ctx.createLinearGradient(0, 0, 0, H * 0.62);
  switch (i % 4) {
    case 0: {
      sky.addColorStop(0, '#3b2a5c');
      sky.addColorStop(0.55, '#e0785a');
      sky.addColorStop(1, '#f7c07a');
      ctx.fillStyle = sky;
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = '#ffe3a8';
      ctx.beginPath();
      ctx.arc(W * 0.55, H * 0.56, 70, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#2a1f33';
      ctx.fillRect(0, H * 0.6, W, H * 0.4);
      ctx.strokeStyle = 'rgba(255,214,150,0.5)';
      for (let k = 0; k < 14; k++) {
        ctx.lineWidth = 2 + rand() * 3;
        const y = H * 0.63 + k * 16;
        ctx.beginPath();
        ctx.moveTo(W * 0.55 - 80 + rand() * 30, y);
        ctx.lineTo(W * 0.55 + 80 - rand() * 30, y);
        ctx.stroke();
      }
      break;
    }
    case 1: {
      sky.addColorStop(0, '#7fb3de');
      sky.addColorStop(1, '#d6ecf5');
      ctx.fillStyle = sky;
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = '#5f8f4e';
      ctx.fillRect(0, H * 0.58, W, H * 0.42);
      ctx.fillStyle = '#5a4332';
      ctx.fillRect(W * 0.72, H * 0.18, 28, H * 0.45);
      ctx.fillStyle = '#3f6e3a';
      for (let k = 0; k < 7; k++) {
        ctx.beginPath();
        ctx.arc(W * 0.74 + (rand() - 0.5) * 180, H * 0.18 + (rand() - 0.5) * 120, 60 + rand() * 40, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.fillStyle = '#7a5638';
      for (let k = 0; k < 3; k++) ctx.fillRect(W * 0.14, H * 0.6 + k * 26, W * 0.5, 16);
      ctx.fillRect(W * 0.18, H * 0.6, 14, 120);
      ctx.fillRect(W * 0.56, H * 0.6, 14, 120);
      break;
    }
    case 2: {
      sky.addColorStop(0, '#9cc9e8');
      sky.addColorStop(1, '#f2e6d0');
      ctx.fillStyle = sky;
      ctx.fillRect(0, 0, W, H);
      for (let k = 0; k < 4; k++) {
        ctx.fillStyle = ['#c9a98a', '#b3876b', '#d8c3a5', '#a07a60'][k];
        ctx.fillRect(k * 130 - 10, H * 0.2 + (k % 2) * 40, 140, H * 0.5);
      }
      ctx.fillStyle = '#b8b2a6';
      ctx.fillRect(0, H * 0.68, W, H * 0.32);
      // A friend, faceless like everyone here, waving at you.
      ctx.fillStyle = '#3b3f4a';
      ctx.beginPath();
      ctx.arc(W / 2, H * 0.42, 34, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.roundRect(W / 2 - 46, H * 0.47, 92, 170, 30);
      ctx.fill();
      ctx.save();
      ctx.translate(W / 2 + 40, H * 0.5);
      ctx.rotate(-0.9);
      ctx.beginPath();
      ctx.roundRect(0, -12, 110, 24, 12);
      ctx.fill();
      ctx.restore();
      break;
    }
    default: {
      sky.addColorStop(0, '#a9cfe6');
      sky.addColorStop(1, '#e8f1f2');
      ctx.fillStyle = sky;
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = '#6f9a58';
      ctx.fillRect(0, H * 0.55, W, H * 0.45);
      ctx.fillStyle = '#8a5f3c';
      ctx.beginPath();
      ctx.ellipse(W / 2, H * 0.66, 110, 55, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.ellipse(W / 2 + 110, H * 0.56, 48, 42, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.ellipse(W / 2 + 128, H * 0.5, 16, 30, 0.4, 0, Math.PI * 2);
      ctx.fill();
      for (const lx of [-70, -30, 40, 80]) ctx.fillRect(W / 2 + lx, H * 0.68, 18, 70);
      ctx.save();
      ctx.translate(W / 2 - 104, H * 0.62);
      ctx.rotate(-0.9);
      ctx.fillRect(0, -7, 60, 14);
      ctx.restore();
      // The leash goes up, out of frame: someone is waiting to take it for a walk.
      ctx.strokeStyle = '#c23a2a';
      ctx.lineWidth = 5;
      ctx.beginPath();
      ctx.moveTo(W / 2 + 104, H * 0.6);
      ctx.bezierCurveTo(W / 2 + 60, H * 0.35, W / 2 + 20, H * 0.2, W / 2 - 20, 0);
      ctx.stroke();
    }
  }
  // Photo feel: grain and a soft vignette.
  const img = ctx.getImageData(0, 0, W, H);
  for (let p = 0; p < img.data.length; p += 4) {
    const n = (rand() - 0.5) * 22;
    img.data[p] += n;
    img.data[p + 1] += n;
    img.data[p + 2] += n;
  }
  ctx.putImageData(img, 0, 0);
  const v = ctx.createRadialGradient(W / 2, H / 2, H * 0.3, W / 2, H / 2, H * 0.75);
  v.addColorStop(0, 'rgba(0,0,0,0)');
  v.addColorStop(1, 'rgba(0,0,0,0.55)');
  ctx.fillStyle = v;
  ctx.fillRect(0, 0, W, H);
  ctx.strokeStyle = '#f4f1ea';
  ctx.lineWidth = 14;
  ctx.strokeRect(7, 7, W - 14, H - 14);
  return tex(c);
}
