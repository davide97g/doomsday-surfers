// Headless fairness + soak test. Run with `npm run check:gen`.
// 1. Static check: at every distance at least one lane is free of posts.
// 2. Soak: the autopilot bot plays N seeds; reports how far it gets.
//    The bot is dumb, so deaths are OK, but a bot that dies very early on
//    many seeds hints at unfair patterns.

import { Bot } from '../src/dev/bot';
import { World } from '../src/sim/world';

const SEEDS = 40;
const MAX_DIST = 6000;
const DT = 1 / 120;

let blockedFailures = 0;
const results: number[] = [];

for (let seed = 1; seed <= SEEDS; seed++) {
  // --- static check on a pre-generated stretch ---
  const w = new World(seed);
  // Simulate a fast "virtual" run to force generation at increasing difficulty.
  const bot = new Bot();
  let steps = 0;
  const seenPosts = new Map<number, { lane: number; s0: number; s1: number }>();
  while (w.phase !== 'dead' && w.d < MAX_DIST && steps < 120 * 60 * 10) {
    const actions = bot.think(w, DT);
    w.step(DT, actions);
    for (const o of w.obstacles) {
      if (o.kind === 'post') seenPosts.set(o.id, { lane: o.lane, s0: o.s, s1: o.s + o.length });
    }
    steps++;
  }
  results.push(w.d);

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
}

results.sort((a, b) => a - b);
const median = results[Math.floor(results.length / 2)];
const reachedMax = results.filter((d) => d >= MAX_DIST).length;
console.log(`all-lanes-blocked failures: ${blockedFailures}`);
console.log(`bot distance — min ${results[0].toFixed(0)}m, median ${median.toFixed(0)}m, max ${results[results.length - 1].toFixed(0)}m, reached ${MAX_DIST}m: ${reachedMax}/${SEEDS}`);
if (blockedFailures > 0) process.exit(1);
