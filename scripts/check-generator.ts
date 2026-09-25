// Headless fairness + soak test. Run with `bun run check:gen`.
// 1. Static check: at every distance at least one lane is free of posts, and
//    no healthy habit sits in a lane a post row left as the only way through.
// 2. Soak: the autopilot bot plays N seeds; reports how far and how long it
//    lasts and what ended the run (a rough read on the dopamine balance).
//    The bot is dumb, so deaths are OK, but a bot that dies very early on
//    many seeds hints at unfair patterns.
// 3. Gates: nothing spawns in a checkpoint gate's clear stretch, and the run
//    comes out of every gate scan it enters.
// 4. Thrill rides: no obstacle or pad inside a loop/corkscrew/drop/airtime
//    stretch (pickups are fine: they ride through).
// 5. Today's Feed: day numbers count one per calendar day (DST included),
//    seeds don't repeat for years, and the same seed plays out identically.
// 6. Ghosts: a recorded bot run survives encode/decode within quantisation
//    (no drift over the whole run), and reports its link size.
// 7. Set pieces: every block of three zones plays each one once, thumbs only
//    spawn in Thumb zones, and the bot's runs report what killed it there.

import { deflateRawSync } from 'node:zlib';
import { Bot } from '../src/dev/bot';
import { dailySeed, dayNumber } from '../src/sim/daily';
import { GhostRecorder, GhostTrack, type GhostFrame } from '../src/sim/ghost';
import { setPieceFor } from '../src/sim/setpiece';
import { TUNING, gateS } from '../src/sim/types';
import { World } from '../src/sim/world';

const SEEDS = 40;
const MAX_DIST = 6000;
const DT = 1 / 120;

let blockedFailures = 0;
let habitFailures = 0;
let gateFailures = 0;
let rideFailures = 0;
const thrills: number[] = [];
const gatesCrossed: number[] = [];
const results: number[] = [];
const times: number[] = [];
const causes = { empty: 0, crash: 0 };

for (let seed = 1; seed <= SEEDS; seed++) {
  // --- static check on a pre-generated stretch ---
  const w = new World(seed);
  // Simulate a fast "virtual" run to force generation at increasing difficulty.
  const bot = new Bot();
  let steps = 0;
  const seenPosts = new Map<number, { lane: number; s0: number; s1: number }>();
  const seenHabits = new Map<number, { lane: number; s: number }>();
  // First-seen track span of every obstacle and pickup, for the gate clear check.
  const spans = new Map<number, [number, number]>();
  // Obstacles and pads only (no pickups), for the thrill-ride check.
  const solid = new Map<number, [number, number]>();
  while (w.phase !== 'dead' && w.d < MAX_DIST && steps < 120 * 60 * 10) {
    const actions = bot.think(w, DT);
    w.step(DT, actions);
    for (const o of w.obstacles) {
      if (o.kind === 'post') seenPosts.set(o.id, { lane: o.lane, s0: o.s, s1: o.s + o.length });
      if (o.kind === 'habit') seenHabits.set(o.id, { lane: o.lane, s: o.s });
      if (!spans.has(o.id)) spans.set(o.id, [o.s, o.s + o.length]);
      if (!solid.has(o.id)) solid.set(o.id, [o.s, o.s + o.length]);
    }
    for (const pd of w.pads) {
      if (!spans.has(pd.id)) spans.set(pd.id, [pd.s, pd.s + pd.length]);
      if (!solid.has(pd.id)) solid.set(pd.id, [pd.s, pd.s + pd.length]);
    }
    for (const pk of w.pickups) if (!spans.has(pk.id)) spans.set(pk.id, [pk.s, pk.s]);
    steps++;
  }
  results.push(w.d);
  gatesCrossed.push(w.zone);
  if (w.gateT >= 0 && w.phase !== 'running') {
    gateFailures++;
    console.log(`seed ${seed}: run ended mid gate scan`);
  }
  const g = w.t.gate;
  for (let k = 0; gateS(k) - g.clearBefore < w.d + w.t.spawn.ahead; k++) {
    const from = gateS(k) - g.clearBefore;
    const to = gateS(k) + g.clearAfter;
    const hit = [...spans.values()].find(([a, b]) => a < to && b > from);
    if (hit) {
      gateFailures++;
      console.log(`seed ${seed}: something spawned in gate ${k}'s clear stretch at s=${hit[0].toFixed(1)}`);
      break;
    }
  }
  for (let c = w.course.nextClear(w.t.spawn.safeStart); c && c.from < w.d; c = w.course.nextClear(c.to + 0.01)) {
    const hit = [...solid.values()].find(([a, b]) => a < c!.to && b > c!.from);
    if (hit) {
      rideFailures++;
      console.log(`seed ${seed}: something solid in the ${c.seg.kind} at s=${hit[0].toFixed(1)}`);
      break;
    }
  }
  thrills.push(w.thrills);
  times.push(w.time);
  if (w.cause) causes[w.cause]++;

  // Sweep: count distinct lanes covered at each post start (coverage can only
  // increase at a start point).
  const posts = [...seenPosts.values()].sort((a, b) => a.s0 - b.s0);
  for (const start of posts) {
    const s = start.s0 + 0.01;
    const blocked = new Set<number>();
    for (const p of posts) {
      if (p.s0 > s + 60) break;
      if (p.s0 <= s && s <= p.s1) blocked.add(p.lane);
    }
    if (blocked.size >= w.t.lanes.count) {
      blockedFailures++;
      console.log(`seed ${seed}: all lanes blocked at s=${s.toFixed(1)}`);
      break;
    }
  }
  for (const h of seenHabits.values()) {
    const blocked = new Set<number>([h.lane]);
    for (const p of posts) if (p.s0 <= h.s && h.s <= p.s1) blocked.add(p.lane);
    if (blocked.size >= w.t.lanes.count) {
      habitFailures++;
      console.log(`seed ${seed}: habit blocks the only free lane at s=${h.s.toFixed(1)}`);
      break;
    }
  }
}

results.sort((a, b) => a - b);
const median = results[Math.floor(results.length / 2)];
const reachedMax = results.filter((d) => d >= MAX_DIST).length;
// Revive sanity: after dying, a revive must not re-kill you straight away.
// Seeds where the bot outlives the time cap have nothing to revive from.
let reviveFailures = 0;
let revivesTested = 0;
for (let seed = 1; seed <= 30 && revivesTested < 10; seed++) {
  const w = new World(seed);
  const bot = new Bot();
  for (let i = 0; i < 120 * 600 && w.phase !== 'dead'; i++) w.step(DT, bot.think(w, DT));
  const phase: string = w.phase;
  if (phase !== 'dead') continue;
  revivesTested++;
  w.revive();
  for (let i = 0; i < 120 * 1.5; i++) w.step(DT, []);
  if (w.phase !== 'running') {
    reviveFailures++;
    console.log(`seed ${seed}: died within 1.5s of reviving (${w.cause})`);
  }
}

times.sort((a, b) => a - b);
const medianTime = times[Math.floor(times.length / 2)];
console.log(`all-lanes-blocked failures: ${blockedFailures}`);
console.log(`habit-in-only-lane failures: ${habitFailures}`);
console.log(`bot distance — min ${results[0].toFixed(0)}m, median ${median.toFixed(0)}m, max ${results[results.length - 1].toFixed(0)}m, reached ${MAX_DIST}m: ${reachedMax}/${SEEDS}`);
console.log(`bot run time — min ${times[0].toFixed(0)}s, median ${medianTime.toFixed(0)}s, max ${times[times.length - 1].toFixed(0)}s · ended by: empty ${causes.empty}, crash ${causes.crash}`);
console.log(`revive failures: ${reviveFailures}/${revivesTested}`);
gatesCrossed.sort((a, b) => a - b);
console.log(`gate failures: ${gateFailures} · gates crossed — median ${gatesCrossed[Math.floor(gatesCrossed.length / 2)]}, max ${gatesCrossed[gatesCrossed.length - 1]}`);
thrills.sort((a, b) => a - b);
console.log(`thrill-ride failures: ${rideFailures} · thrills per run — median ${thrills[Math.floor(thrills.length / 2)]}, max ${thrills[thrills.length - 1]}`);
// --- Today's Feed ---
let dailyFailures = 0;
const [ey, em, ed] = TUNING.daily.epoch;
if (dayNumber(new Date(ey, em - 1, ed, 23, 59)) !== 1) dailyFailures++;
const seeds = new Set<number>();
for (let i = 0; i < 3 * 366; i++) {
  // Noon avoids DST edges; the day number must still step by exactly one.
  const day = dayNumber(new Date(ey, em - 1, ed + i, 12));
  if (day !== i + 1) dailyFailures++;
  seeds.add(dailySeed(day));
}
if (seeds.size !== 3 * 366) dailyFailures++;
const replay = (): string => {
  const w = new World(dailySeed(1));
  const bot = new Bot();
  for (let i = 0; i < 120 * 60 && w.phase !== 'dead'; i++) w.step(DT, bot.think(w, DT));
  return `${w.d.toFixed(6)}|${w.dopamine.toFixed(6)}|${w.pickupsTaken}|${w.history.map((h) => h.toFixed(3)).join(',')}`;
};
if (replay() !== replay()) dailyFailures++;
console.log(`daily failures: ${dailyFailures}`);

// --- Ghosts ---
let ghostFailures = 0;
{
  const w = new World(7);
  const bot = new Bot();
  const rec = new GhostRecorder();
  const truth: { t: number; d: number; x: number; y: number }[] = [];
  for (let i = 0; i < 120 * 180 && w.phase !== 'dead'; i++) {
    w.step(DT, bot.think(w, DT));
    const before = rec.samples;
    rec.update(w);
    if (rec.samples > before) truth.push({ t: w.time, d: w.d, x: w.player.x, y: w.player.y });
  }
  const bytes = rec.encode({ v: 1, seed: 7, ch: 0, name: '@check', mode: 'personal', day: 0, dist: Math.round(w.d), killer: 'a check' });
  const track = GhostTrack.decode(bytes);
  if (!track) ghostFailures++;
  else {
    let worstD = 0;
    let worstX = 0;
    const f: GhostFrame = { d: 0, x: 0, y: 0, roll: false, air: false };
    truth.forEach((s, i) => {
      track.at(i * TUNING.ghost.sampleEvery, f);
      worstD = Math.max(worstD, Math.abs(f.d - s.d));
      worstX = Math.max(worstX, Math.abs(f.x - s.x));
    });
    if (worstD > 0.1 || worstX > 0.05) ghostFailures++;
    const packed = deflateRawSync(bytes);
    console.log(`ghost: ${truth.length} samples over ${w.time.toFixed(0)}s · ${bytes.length} B raw, ~${Math.ceil((packed.length * 4) / 3)} B in the link · worst error d ${worstD.toFixed(3)} m, x ${worstX.toFixed(3)} m`);
  }
}
console.log(`ghost failures: ${ghostFailures}`);

// --- Set pieces ---
let pieceFailures = 0;
for (let seed = 1; seed <= 200; seed++) {
  for (let block = 0; block < 4; block++) {
    const got = new Set([1, 2, 3].map((i) => setPieceFor(block * 3 + i, seed)));
    if (got.size !== 3) pieceFailures++;
  }
  if (setPieceFor(0, seed) !== null) pieceFailures++;
}
let thumbs = 0;
let thumbDeaths = 0;
for (let seed = 1; seed <= SEEDS; seed++) {
  const w = new World(seed);
  const bot = new Bot();
  const seen = new Set<number>();
  for (let i = 0; i < 120 * 60 * 5 && w.phase !== 'dead'; i++) {
    w.step(DT, bot.think(w, DT));
    for (const o of w.obstacles) {
      if (o.kind !== 'thumb' || seen.has(o.id)) continue;
      seen.add(o.id);
      thumbs++;
      // Zone the thumb's chunk belongs to: gates strictly behind where it was placed.
      let k = 0;
      while (gateS(k) < o.s) k++;
      if (setPieceFor(k, seed) !== 'thumb') {
        pieceFailures++;
        console.log(`seed ${seed}: a thumb outside a Thumb zone (zone ${k})`);
      }
    }
  }
  if (w.crashKind === 'thumb') thumbDeaths++;
}
console.log(`set pieces: ${thumbs} thumbs over ${SEEDS} bot runs, ${thumbDeaths} bot deaths by thumb · failures: ${pieceFailures}`);

if (blockedFailures > 0 || habitFailures > 0 || reviveFailures > 0 || gateFailures > 0 || rideFailures > 0 || dailyFailures > 0 || ghostFailures > 0 || pieceFailures > 0 || revivesTested < 5) process.exit(1);
