// The end-of-run receipt ("Proof of Doom"): what you consumed, priced in life.
// One layout feeds both the death screen (printed out line by line) and the
// shared 9:16 image, so what you see is exactly what you post.

import { content } from '../content/content';
import { fill, pick, seeded } from '../content/templates';
import { TUNING, zoneLook } from '../sim/types';
import type { World } from '../sim/world';
import type { Nags } from './nags';
import { raceLines, type RaceResult } from './race';

type Line =
  | { k: 'row'; l: string; r: string }
  | { k: 'text'; t: string; size?: 'big' | 'small' }
  | { k: 'rule' }
  | { k: 'gap' }
  | { k: 'barcode' };

export interface Receipt {
  lines: Line[];
  seed: number;
  killer: string;
  distance: number;
}

export interface Paper {
  canvas: HTMLCanvasElement;
  /** Bottom edge of each printed line, in canvas pixels. */
  stops: number[];
}

type Item = { label: string; prices: string[] };

const R = content.report;
const T = TUNING.report;

const W = 720;
const PAD = 48;
const TOOTH = 12;
const LH = 1.4;
const FONT = 'ui-monospace, "SF Mono", Menlo, "Courier New", monospace';
const SIZE = { big: 38, normal: 28, small: 22 } as const;
const INK = '#1c1b1f';

function p2(n: number): string {
  return String(n).padStart(2, '0');
}

function life(sec: number): string {
  const m = Math.max(1, Math.round(sec * T.lifeScale));
  return fill(R.life, { life: m >= 60 ? `${Math.floor(m / 60)} H ${m % 60} MIN` : `${m} MIN` });
}

export function topPct(d: number): string {
  const p = Math.max(0.01, 100 * Math.exp(-d / T.topScale));
  return p >= 10 ? p.toFixed(0) : p >= 1 ? p.toFixed(1) : p.toFixed(2);
}

/** What killed you, in receipt caps ("A GLASS OF WATER"). */
export function killerText(w: World): string {
  const k = R.killers;
  if (w.cause === 'crash' && w.crashKind && w.crashKind !== 'habit') return k.crash[w.crashKind];
  return k.habits[w.lastHabit] ?? k.none;
}

function aura(w: World): string {
  const a = T.aura;
  const n =
    w.thrills * a.thrill +
    w.zone * a.gate +
    w.notificationsOpened * a.opened +
    w.smashed * a.smashed +
    w.habitsHit * a.habit +
    (w.cause === 'crash' ? a.crash : a.empty);
  return `${n > 0 ? '+' : n < 0 ? '-' : ''}${Math.abs(n).toLocaleString('en-US')}`;
}

export function brainAge(w: World): number {
  const b = T.brainAge;
  const numb = 1 - w.tolerance.reduce((s, t) => s + t, 0) / w.tolerance.length;
  return Math.min(b.max, Math.round(b.base + w.pickupsTaken * b.perPickup + numb * b.numbness));
}

function item(it: Item, n: number, per: number): Line {
  const k = Math.max(1, Math.round(n / per));
  const plural = { k, s: k === 1 ? '' : 'S', e: k === 1 ? '' : 'E' };
  return { k: 'row', l: fill(it.label, { n }), r: fill(pick(it.prices), plural) };
}

/** `daily` is today's feed number when this was the Daily run; `race` the result against a ghost. */
export function buildReceipt(w: World, nags: Nags, daily: number | null = null, race: RaceResult | null = null, now = new Date()): Receipt {
  const types = content.contentTypes;
  const by = (id: string) => w.takenByType[types.findIndex((c) => c.id === id)] ?? 0;
  const per = T.pricePer;
  const it = R.items;
  const counts: [Item, number, number][] = [
    [it.scrolls, w.scrolls, per.scrolls],
    [it.reel, by('reel'), per.reel],
    [it.like, by('like'), per.like],
    [it.outrage, by('outrage'), per.outrage],
    [it.notification, by('notification') + w.notificationsOpened, per.notification],
    [it.thrill, w.thrills, per.thrill],
    [it.ads, w.adsPassed + nags.bannersShown, per.ads],
    [it.dodged, w.habitsDodged, per.dodged],
    [it.mum, w.mumIgnored, 1],
  ];

  let top = -1;
  w.takenByType.forEach((n, i) => {
    if (n > 0 && (top < 0 || n > w.takenByType[top])) top = i;
  });
  let tier = 0;
  T.tierAt.forEach((d, i) => {
    if (w.d >= d) tier = i;
  });
  const diag = R.tiers[tier];
  const kill = killerText(w);
  const span = Math.max(0.4, 8 * Math.pow(0.985, w.pickupsTaken)).toFixed(1);

  const zone = content.zones[zoneLook(w.zone)].name;
  const lines: Line[] = [
    { k: 'text', t: R.store, size: 'big' },
    {
      k: 'text',
      t:
        daily === null
          ? fill(R.storeLine, { store: String(w.seed % 10000).padStart(4, '0'), zone })
          : fill(content.daily.storeLine, { n: daily, zone }),
      size: 'small',
    },
    { k: 'text', t: fill(R.customer, { character: content.characters[w.character].name }), size: 'small' },
    { k: 'row', l: `${p2(now.getDate())}.${p2(now.getMonth() + 1)}.${String(now.getFullYear()).slice(2)}`, r: `${p2(now.getHours())}:${p2(now.getMinutes())}` },
    { k: 'rule' },
    ...counts.filter(([, n]) => n > 0).map(([i, n, p]) => item(i, n, p)),
    { k: 'rule' },
    { k: 'row', l: R.subtotal, r: life(w.time) },
    { k: 'row', l: R.aura, r: aura(w) },
    { k: 'row', l: R.span, r: `${span} s` },
    { k: 'row', l: R.brainAge, r: String(brainAge(w)) },
    { k: 'rule' },
    { k: 'text', t: top < 0 ? R.topNone : fill(R.top, { pct: topPct(w.d), craving: types[top].name.toUpperCase() }) },
    { k: 'text', t: fill(R.diagnosis, { tier: diag.name }), size: 'big' },
    { k: 'text', t: `“${diag.line}”`, size: 'small' },
    { k: 'gap' },
    { k: 'text', t: fill(R.killedBy, { killer: kill }), size: 'big' },
    { k: 'gap' },
    ...(race ? raceReceipt(race) : []),
    { k: 'barcode' },
    { k: 'text', t: R.thanks },
    { k: 'text', t: R.noRefunds, size: 'small' },
    { k: 'gap' },
    { k: 'text', t: `${R.game} · ${R.hashtag}`, size: 'small' },
  ];
  return { lines, seed: w.seed, killer: kill, distance: Math.round(w.d) };
}

function raceReceipt(race: RaceResult): Line[] {
  const l = raceLines(race);
  return [{ k: 'rule' }, { k: 'text', t: l.big, size: 'big' }, { k: 'text', t: l.small, size: 'small' }, { k: 'gap' }];
}

/** The hidden ending's receipt: nothing bought, nothing lost. */
export function buildSecretReceipt(w: World, now = new Date()): Receipt {
  const e = content.ending.receipt;
  const lines: Line[] = [
    { k: 'text', t: R.store, size: 'big' },
    { k: 'text', t: e.storeLine, size: 'small' },
    { k: 'text', t: fill(R.customer, { character: content.characters[w.character].name }), size: 'small' },
    { k: 'row', l: `${p2(now.getDate())}.${p2(now.getMonth() + 1)}.${String(now.getFullYear()).slice(2)}`, r: `${p2(now.getHours())}:${p2(now.getMinutes())}` },
    { k: 'rule' },
    ...e.items.map(([l, r]): Line => ({ k: 'row', l, r })),
    { k: 'rule' },
    ...e.totals.map(([l, r]): Line => ({ k: 'row', l, r })),
    { k: 'rule' },
    { k: 'text', t: e.top },
    { k: 'text', t: e.diagnosis, size: 'big' },
    { k: 'text', t: e.quote, size: 'small' },
    { k: 'gap' },
    { k: 'text', t: e.killedBy, size: 'big' },
    { k: 'gap' },
    { k: 'barcode' },
    { k: 'text', t: e.thanks },
    { k: 'text', t: e.footer, size: 'small' },
    { k: 'gap' },
    { k: 'text', t: `${R.game} · ${R.hashtag}`, size: 'small' },
  ];
  return { lines, seed: w.seed ^ 0x60, killer: 'NOTHING', distance: Math.round(w.d) };
}

function font(size: 'big' | 'normal' | 'small'): string {
  return `${size === 'big' ? 800 : 600} ${SIZE[size]}px ${FONT}`;
}

function wrap(ctx: CanvasRenderingContext2D, text: string, width: number): string[] {
  const out: string[] = [];
  let cur = '';
  for (const word of text.split(' ')) {
    const next = cur ? `${cur} ${word}` : word;
    if (cur && ctx.measureText(next).width > width) {
      out.push(cur);
      cur = word;
    } else cur = next;
  }
  if (cur) out.push(cur);
  return out;
}

interface Placed {
  line: Line;
  y: number;
  rows: string[];
  split: boolean;
}

/** Renders the receipt as a torn strip of thermal paper. `scale` is canvas px per layout px. */
export function drawReceipt(r: Receipt, scale = 1.5): Paper {
  const inner = W - PAD * 2;
  const m = document.createElement('canvas').getContext('2d')!;
  const placed: Placed[] = [];
  const stops: number[] = [];
  let y = TOOTH + 40;
  for (const line of r.lines) {
    let h: number;
    let rows: string[] = [];
    let split = false;
    if (line.k === 'text') {
      const size = line.size ?? 'normal';
      m.font = font(size);
      rows = wrap(m, line.t, inner);
      h = rows.length * SIZE[size] * LH;
    } else if (line.k === 'row') {
      m.font = font('normal');
      split = m.measureText(line.l).width + m.measureText(line.r).width + 24 > inner;
      h = (split ? 2 : 1) * SIZE.normal * LH;
    } else if (line.k === 'rule') h = 30;
    else if (line.k === 'gap') h = 16;
    else h = 96;
    placed.push({ line, y, rows, split });
    y += h;
    stops.push(y * scale);
  }
  const H = Math.ceil(y + 40 + TOOTH);

  const c = document.createElement('canvas');
  c.width = W * scale;
  c.height = H * scale;
  const ctx = c.getContext('2d')!;
  ctx.scale(scale, scale);

  // Torn edges, top and bottom.
  ctx.beginPath();
  ctx.moveTo(0, TOOTH);
  for (let x = 0; x < W; x += TOOTH * 2) {
    ctx.lineTo(x + TOOTH, 0);
    ctx.lineTo(x + TOOTH * 2, TOOTH);
  }
  ctx.lineTo(W, H - TOOTH);
  for (let x = W; x > 0; x -= TOOTH * 2) {
    ctx.lineTo(x - TOOTH, H);
    ctx.lineTo(x - TOOTH * 2, H - TOOTH);
  }
  ctx.closePath();
  const paper = ctx.createLinearGradient(0, 0, 0, H);
  paper.addColorStop(0, '#f6f3ec');
  paper.addColorStop(1, '#e9e5da');
  ctx.fillStyle = paper;
  ctx.fill();

  ctx.fillStyle = INK;
  ctx.strokeStyle = INK;
  ctx.textBaseline = 'top';
  const rand = seeded(r.seed);
  for (const { line, y: top, rows, split } of placed) {
    if (line.k === 'text') {
      const size = line.size ?? 'normal';
      ctx.font = font(size);
      ctx.textAlign = 'center';
      rows.forEach((t, i) => ctx.fillText(t, W / 2, top + i * SIZE[size] * LH));
    } else if (line.k === 'row') {
      ctx.font = font('normal');
      ctx.textAlign = 'left';
      ctx.fillText(line.l, PAD, top);
      ctx.textAlign = 'right';
      ctx.fillText(line.r, W - PAD, top + (split ? SIZE.normal * LH : 0));
    } else if (line.k === 'rule') {
      ctx.setLineDash([10, 8]);
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(PAD, top + 15);
      ctx.lineTo(W - PAD, top + 15);
      ctx.stroke();
      ctx.setLineDash([]);
    } else if (line.k === 'barcode') {
      for (let x = PAD + 60; x < W - PAD - 60; ) {
        const bw = 2 + Math.floor(rand() * 5);
        ctx.fillRect(x, top + 8, bw, 76);
        x += bw + 2 + Math.floor(rand() * 4);
      }
    }
  }

  // Thermal print fades in streaks.
  ctx.fillStyle = 'rgba(246,243,236,0.28)';
  for (let i = 0; i < 7; i++) ctx.fillRect(0, rand() * H, W, 2 + rand() * 7);

  return { canvas: c, stops };
}

/** The 9:16 image people post: grey reality, the death line (or `header`), the receipt slightly askew. */
export function shareCard(paper: Paper, header: [string, string] = [content.death.line1, content.death.line2]): Promise<Blob> {
  const CW = 1080;
  const CH = 1920;
  const c = document.createElement('canvas');
  c.width = CW;
  c.height = CH;
  const ctx = c.getContext('2d')!;
  const bg = ctx.createRadialGradient(CW / 2, CH * 0.45, 100, CW / 2, CH * 0.45, CH * 0.75);
  bg.addColorStop(0, '#3a3a3f');
  bg.addColorStop(1, '#101012');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, CW, CH);

  ctx.fillStyle = '#d9d9de';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'alphabetic';
  ctx.font = '900 66px system-ui, -apple-system, sans-serif';
  ctx.fillText(header[0], CW / 2, 190);
  ctx.fillText(header[1], CW / 2, 276);

  const boxTop = 350;
  const boxW = 860;
  const boxH = CH - boxTop - 90;
  const p = paper.canvas;
  const s = Math.min(boxW / p.width, boxH / p.height);
  ctx.save();
  ctx.translate(CW / 2, boxTop + boxH / 2);
  ctx.rotate((-1.6 * Math.PI) / 180);
  ctx.shadowColor = 'rgba(0,0,0,0.6)';
  ctx.shadowBlur = 60;
  ctx.shadowOffsetY = 24;
  ctx.drawImage(p, (-p.width * s) / 2, (-p.height * s) / 2, p.width * s, p.height * s);
  ctx.restore();

  return new Promise((resolve, reject) => c.toBlob((b) => (b ? resolve(b) : reject(new Error('toBlob failed'))), 'image/png'));
}
