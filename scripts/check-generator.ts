// Headless fairness + soak test. Run with `npm run check:gen`.
// 1. Static check: at every distance at least one lane is free of posts, and
//    no healthy habit sits in a lane a post row left as the only way through.
// 2. Soak: the autopilot bot plays N seeds; reports how far and how long it
//    lasts and what ended the run (a rough read on the dopamine balance).
//    The bot is dumb, so deaths are OK, but a bot that dies very early on
//    many seeds hints at unfair patterns.
// 3. Gates: nothing spawns in a checkpoint gate's clear stretch, and the run
//    comes out of every gate scan it enters.

import { Bot } from '../src/dev/bot';
import { gateS } from '../src/sim/types';
import { World } from '../src/sim/world';

const SEEDS = 40;
const MAX_DIST = 6000;
const DT = 1 / 120;

let blockedFailures = 0;
let habitFailures = 0;
let gateFailures = 0;
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
  while (w.phase !== 'dead' && w.d < MAX_DIST && steps < 120 * 60 * 10) {
    const actions = bot.think(w, DT);
    w.step(DT, actions);
    for (const o of w.obstacles) {
      if (o.kind === 'post') seenPosts.set(o.id, { lane: o.lane, s0: o.s, s1: o.s + o.length });
      if (o.kind === 'habit') seenHabits.set(o.id, { lane: o.lane, s: o.s });
      if (!spans.has(o.id)) spans.set(o.id, [o.s, o.s + o.length]);
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
let reviveFailures = 0;
for (let seed = 1; seed <= 10; seed++) {
  const w = new World(seed);
  const bot = new Bot();
  for (let i = 0; i < 120 * 600 && w.phase !== 'dead'; i++) w.step(DT, bot.think(w, DT));
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
console.log(`revive failures: ${reviveFailures}`);
gatesCrossed.sort((a, b) => a - b);
console.log(`gate failures: ${gateFailures} · gates crossed — median ${gatesCrossed[Math.floor(gatesCrossed.length / 2)]}, max ${gatesCrossed[gatesCrossed.length - 1]}`);
if (blockedFailures > 0 || habitFailures > 0 || reviveFailures > 0 || gateFailures > 0) process.exit(1);
