// Today's Feed: one course per calendar day, the same for everyone.
// Pure (no DOM): the day number comes from the local date, the seed from the
// day number, so every player on the same date scrolls the same feed.

import { TUNING, type Tuning } from './types';

const DAY = 864e5;

/** Day number of `date` (local calendar), #1 on `daily.epoch`. */
export function dayNumber(date: Date, t: Tuning = TUNING): number {
  const [y, m, d] = t.daily.epoch;
  const epoch = new Date(y, m - 1, d).getTime();
  const today = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  // Round, not floor: a DST day is 23 or 25 hours long.
  return Math.round((today - epoch) / DAY) + 1;
}

/** Course seed for day `n`. */
export function dailySeed(n: number): number {
  let h = Math.imul(n ^ 0x5eed, 0x9e3779b1);
  h ^= h >>> 16;
  h = Math.imul(h, 0x85ebca6b);
  h ^= h >>> 13;
  return (h >>> 0) || 1;
}

/** Milliseconds until the next local midnight (the next feed). */
export function msToNextDay(date: Date): number {
  const next = new Date(date.getFullYear(), date.getMonth(), date.getDate() + 1).getTime();
  return next - date.getTime();
}
