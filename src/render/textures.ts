// Procedural canvas textures for the grey-box "feed world".
// Placeholder art: these get replaced by Blender assets later, but they already
// sell the idea that you're running on top of an endless feed.

import * as THREE from 'three';

const PALETTE = ['#ff2e88', '#7b2eff', '#00e1ff', '#ffcc00', '#ff5a1f', '#1fff8f', '#ff3b3b', '#4d7cff'];

const HANDLES = ['@grindset.guru', '@pov_you_exist', '@slop.daily', '@ai_bae_9000', '@ragebait.hq', '@just1more', '@cortisol.cafe', '@link.in.bio'];
const CAPTIONS = [
  'POV: you have 4 min of battery',
  'WAIT FOR IT',
  'only 1% can watch this',
  'this changed my life (not clickbait)',
  'part 47',
  'you won’t believe #3',
  'morning routine (5am) (cold)',
  'sound on \u{1F50A}',
];

const ADS = [
  { brand: 'SlopCola', line: 'Taste the Content', bg: '#ff2e2e', fg: '#fff5c2' },
  { brand: 'GrindsetGPT', line: 'Hustle while you sleep', bg: '#111111', fg: '#ffcc00' },
  { brand: 'DopaMint', line: 'Now 40% more mint', bg: '#1fff8f', fg: '#0a2a1a' },
  { brand: 'FOMOfone', line: 'You are missing out', bg: '#7b2eff', fg: '#ffffff' },
];

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

/** A vertical social post (the ground tiles and tower faces). */
export function makeFeedPost(i: number): THREE.CanvasTexture {
  const W = 256;
  const H = 540;
  const [c, ctx] = canvas(W, H);
  const a = PALETTE[i % PALETTE.length];
  const b = PALETTE[(i * 3 + 2) % PALETTE.length];

  ctx.fillStyle = '#0d0b14';
  ctx.fillRect(0, 0, W, H);

  // Header: avatar + handle.
  ctx.fillStyle = a;
  ctx.beginPath();
  ctx.arc(30, 32, 16, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#e9e6f5';
  ctx.font = 'bold 17px system-ui, sans-serif';
  ctx.fillText(HANDLES[i % HANDLES.length], 56, 38);

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
  ctx.fillText(CAPTIONS[i % CAPTIONS.length], 14, 466);
  ctx.fillStyle = '#4a4560';
  roundRect(ctx, 14, 482, 170, 10, 5);
  ctx.fill();
  roundRect(ctx, 14, 502, 110, 10, 5);
  ctx.fill();

  return tex(c);
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
  const titles = ['New follower', '3 new likes', 'Someone replied', 'You were tagged', 'Streak ending!', 'Trending now'];
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
  ctx.font = '900 78px system-ui, sans-serif';
  ctx.fillText(ad.brand, 256, 130);
  ctx.font = 'bold 30px system-ui, sans-serif';
  ctx.fillText(ad.line, 256, 186);
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
  ctx.fillText(['WATCH TILL THE END', 'POV:', 'PART 2 →', 'WAIT...', 'NO WAY', 'STORYTIME'][i % 6], 26, 70);
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

/** Pickup sprite: a like / heart glyph. */
export function makeHeart(): THREE.CanvasTexture {
  const [c, ctx] = canvas(128, 128);
  ctx.fillStyle = '#ff2e63';
  heart(ctx, 64, 18, 96);
  return tex(c);
}
