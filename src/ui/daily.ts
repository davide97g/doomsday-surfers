// Today's Feed on the UI side: whether today's feed was played (localStorage,
// per device and per mode), the Wordle-style share line, and the lock-screen
// numbers (the parody live counter and the countdown to the next feed).
// One shot a day: the Daily locks the moment its run starts.

import { content, mode } from '../content/content';
import { fill, seeded } from '../content/templates';
import { dailySeed, dayNumber, msToNextDay } from '../sim/daily';
import { TUNING } from '../sim/types';
import type { World } from '../sim/world';
import { brainAge, topPct } from './receipt';

const KEY = `ds.daily.${mode}`;

export interface DailyRecord {
  day: number;
  /** Absent while the run is going, or forever if the app died mid-run (abandoned). */
  result?: { distance: string; emoji: string; line: string };
}

export function today(): number {
  return dayNumber(new Date());
}

/** Each mode has its own feed, so playing one doesn't spoil the other's course. */
export function seedFor(day: number): number {
  return mode === 'work' ? (dailySeed(day) ^ 0x3017) >>> 0 || 1 : dailySeed(day);
}

/** Today's record, or null if today's feed hasn't been touched. */
export function loadToday(): DailyRecord | null {
  try {
    const raw = localStorage.getItem(KEY);
    const r = raw ? (JSON.parse(raw) as DailyRecord) : null;
    return r && r.day === today() ? r : null;
  } catch {
    return null;
  }
}

export function saveDaily(r: DailyRecord): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(r));
  } catch {
    // Blocked storage: the Daily just isn't locked on this device.
  }
}

export function distanceText(d: number): string {
  return d < 1000 ? `${Math.round(d)} m` : `${(d / 1000).toFixed(1)} km`;
}

export function killerEmoji(w: World): string {
  const k = content.daily.killers;
  if (w.cause === 'crash' && w.crashKind && w.crashKind !== 'habit') return k.crash[w.crashKind];
  return k.habits[w.lastHabit] ?? k.none;
}

/** The dopamine curve as coloured squares, one per `daily.sampleEvery` s, ending in the death square. */
export function grid(history: readonly number[]): string {
  const t = TUNING.daily;
  const c = content.daily;
  const sq = history.slice(0, t.maxSquares).map((v) => {
    const i = t.squares.findIndex((min) => v >= min);
    return c.squares[i < 0 ? c.squares.length - 1 : i];
  });
  if (history.length > t.maxSquares) sq.push(c.more);
  sq.push(c.dead);
  const rows: string[] = [];
  for (let i = 0; i < sq.length; i += t.perRow) rows.push(sq.slice(i, i + t.perRow).join(''));
  return rows.join('\n');
}

export function shareLine(w: World, day: number): string {
  const c = content.daily;
  const lines = [
    fill(c.lineHead, { n: day }),
    grid(w.history),
    fill(c.lineStats, { distance: distanceText(w.d), emoji: killerEmoji(w) }),
    fill(c.lineMore, { age: brainAge(w), pct: topPct(w.d) }),
  ];
  if (w.revivesLeft < TUNING.revive.perRun) lines.push(c.lineRevive);
  lines.push(c.hashtag);
  return lines.join('\n');
}

/** Parody social proof: peaks at 3 AM, dips mid-afternoon, wobbles every minute. */
export function liveCount(now = new Date()): number {
  const l = TUNING.daily.live;
  const h = now.getHours() + now.getMinutes() / 60;
  const curve = Math.cos(((h - l.peakHour) / 24) * 2 * Math.PI);
  const jitter = (seeded(Math.floor(now.getTime() / 60000))() - 0.5) * 2 * l.jitter;
  return Math.round(l.base + l.swing * curve + jitter + now.getSeconds() * 37);
}

export function countdown(now = new Date()): string {
  const s = Math.floor(msToNextDay(now) / 1000);
  const p2 = (n: number) => String(n).padStart(2, '0');
  return `${p2(Math.floor(s / 3600))}:${p2(Math.floor(s / 60) % 60)}:${p2(s % 60)}`;
}
