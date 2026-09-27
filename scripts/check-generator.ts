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
// 8. The second level and power-ups:
//    A. No traps: a runner on the ground facing a train always has a free lane
//       to reach (through lanes that are free long enough to cross).
//    B. Roof gaps are short enough that walking off one roof still catches
//       the next one's edge (the mantle).
//    C. Overhangs span every lane, stand alone, and sit far enough past any
//       roof or rail to drop down and roll.
//    D. Rail lanes are clean: no train, high barrier, thumb or pad under a rail.
//    E. Tunnels miss gates and thrill rides, and hold no bouncer, thumb or
//       Going Viral window.
//    F. Power-ups keep their spacing; Going Viral windows miss gates, loops
//       and corkscrews.
//    G. Soak: never flying during a gate scan, no crash while flying, heads
//       stay under tunnel ceilings, a grounded runner never sinks into a floor.

import { deflateRawSync } from 'node:zlib';
import { Bot } from '../src/dev/bot';
import { dailySeed, dayNumber } from '../src/sim/daily';
import { GHOST_VERSION, GhostRecorder, GhostTrack, type GhostFrame } from '../src/sim/ghost';
import { setPieceFor } from '../src/sim/setpiece';
import { TUNING, gateS, laneX, type Action } from '../src/sim/types';
import { World } from '../src/sim/world';

const SEEDS = 40;
const MAX_DIST = 6000;
const DT = 1 / 120;

let blockedFailures = 0;
let trapFailures = 0;
let gapFailures = 0;
let overhangFailures = 0;
let railFailures = 0;
let tunnelFailures = 0;
let powerFailures = 0;
let soakFailures = 0;
let powersTaken = 0;
let shieldsUsed = 0;
let grindMetres = 0;
let roofSeconds = 0;
const crashKinds: Record<string, number> = {};
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
  const seenPosts = new Map<number, { lane: number; s0: number; s1: number; ramp: number; v: number; moving: boolean }>();
  const seenHighs = new Map<number, { lane: number; s: number; wide: boolean; v: number }>();
  const seenOther = new Map<number, { kind: string; lane: number; s0: number; s1: number }>();
  const seenRails = new Map<number, { lane: number; s0: number; s1: number }>();
  const seenTunnels = new Map<number, { s0: number; s1: number }>();
  const seenPowers = new Map<number, { kind: string; s: number }>();
  const seenPads = new Map<number, { kind: string; lane: number; s0: number; s1: number }>();
  const seenHabits = new Map<number, { lane: number; s: number }>();
  // First-seen track span of every obstacle and pickup, for the gate clear check.
  const spans = new Map<number, [number, number]>();
  // Obstacles and pads only (no pickups), for the thrill-ride check.
  const solid = new Map<number, [number, number]>();
  while (w.phase !== 'dead' && w.d < MAX_DIST && steps < 120 * 60 * 10) {
    const actions = bot.think(w, DT);
    const wasFlying = w.flying;
    w.step(DT, actions);
    for (const e of w.drainEvents()) if (e.type === 'crash' && wasFlying) {
      soakFailures++;
      console.log(`seed ${seed}: crashed while flying at d=${w.d.toFixed(1)}`);
    }
    if (w.flying && w.gateT >= 0) {
      soakFailures++;
      console.log(`seed ${seed}: flying during a gate scan at d=${w.d.toFixed(1)}`);
    }
    const pl = w.player;
    const tu = w.tunnelAt(w.d);
    if (tu && pl.y + (pl.rollT > 0 ? w.t.player.rollHeight : w.t.player.height) > w.t.tunnel.ceiling + 1e-6) {
      soakFailures++;
      console.log(`seed ${seed}: head through a tunnel ceiling at d=${w.d.toFixed(1)}`);
    }
    if (pl.grounded && pl.y < pl.floor - w.t.support.eps - 1e-6) {
      soakFailures++;
      console.log(`seed ${seed}: grounded below the floor at d=${w.d.toFixed(1)}`);
    }
    for (const o of w.obstacles) {
      if ((o.kind === 'post' || o.kind === 'movingPost') && !seenPosts.has(o.id)) seenPosts.set(o.id, { lane: o.lane, s0: o.s, s1: o.s + o.length, ramp: o.ramp, v: w.speed, moving: o.kind === 'movingPost' });
      if (o.kind === 'high' && !seenHighs.has(o.id)) seenHighs.set(o.id, { lane: o.lane, s: o.s, wide: o.wide, v: w.speed });
      if (!seenOther.has(o.id)) seenOther.set(o.id, { kind: o.kind, lane: o.lane, s0: o.s - o.ramp, s1: o.s + o.length });
      if (o.kind === 'habit') seenHabits.set(o.id, { lane: o.lane, s: o.s });
      if (!spans.has(o.id)) spans.set(o.id, [o.s, o.s + o.length]);
      if (!solid.has(o.id)) solid.set(o.id, [o.s, o.s + o.length]);
    }
    for (const pd of w.pads) {
      if (!spans.has(pd.id)) spans.set(pd.id, [pd.s, pd.s + pd.length]);
      if (!solid.has(pd.id)) solid.set(pd.id, [pd.s, pd.s + pd.length]);
      if (!seenPads.has(pd.id)) seenPads.set(pd.id, { kind: pd.kind, lane: pd.lane, s0: pd.s, s1: pd.s + pd.length });
    }
    for (const r of w.rails) {
      const s0 = r.s - w.t.rail.ramp;
      if (!spans.has(r.id)) spans.set(r.id, [s0, r.s + r.length]);
      if (!solid.has(r.id)) solid.set(r.id, [s0, r.s + r.length]);
      if (!seenRails.has(r.id)) seenRails.set(r.id, { lane: r.lane, s0, s1: r.s + r.length });
    }
    for (const tn of w.tunnels) if (!seenTunnels.has(tn.id)) seenTunnels.set(tn.id, { s0: tn.s, s1: tn.s + tn.length });
    for (const pu of w.powerUps) {
      if (!spans.has(pu.id)) spans.set(pu.id, [pu.s, pu.s]);
      if (!seenPowers.has(pu.id)) seenPowers.set(pu.id, { kind: pu.kind, s: pu.s });
    }
    for (const pk of w.pickups) if (!spans.has(pk.id)) spans.set(pk.id, [pk.s, pk.s]);
    steps++;
  }
  powersTaken += w.powersTaken;
  shieldsUsed += w.shieldsUsed;
  grindMetres += w.grindDistance;
  roofSeconds += w.roofTime;
  if (w.crashKind) crashKinds[w.crashKind] = (crashKinds[w.crashKind] ?? 0) + 1;
  const tt = w.t;
  const seenUntil = w.d + tt.spawn.ahead - 1;

  // A. No traps (static trains only; stairs trains can be climbed, so their front isn't a wall).
  const statics = [...seenPosts.values()].filter((p) => !p.moving);
  const walls = (lane: number, a: number, b: number) => statics.some((p) => p.lane === lane && p.s0 - p.ramp < b && p.s1 > a);
  for (const m of statics) {
    if (m.ramp > 0 || m.s0 > seenUntil) continue;
    const v = m.v;
    let ok = false;
    for (let f = 0; f < tt.lanes.count && !ok; f++) {
      if (f === m.lane || walls(f, m.s0 - 0.45 * v, m.s0 + 1)) continue;
      let pathFree = true;
      for (let b = Math.min(f, m.lane) + 1; b < Math.max(f, m.lane); b++) if (walls(b, m.s0 - 0.6 * v, m.s0 - 0.3 * v)) pathFree = false;
      ok = pathFree;
    }
    if (!ok) {
      trapFailures++;
      console.log(`seed ${seed}: trapped by the train in lane ${m.lane} at s=${m.s0.toFixed(1)}`);
      break;
    }
  }
  // B. Roof gaps.
  for (let lane = 0; lane < tt.lanes.count; lane++) {
    const row = statics.filter((p) => p.lane === lane).sort((a, b) => a.s0 - b.s0);
    for (let i = 1; i < row.length; i++) {
      const g = row[i].s0 - row[i].ramp - row[i - 1].s1;
      const v = row[i].v;
      if (g > 0 && g < 0.72 * v && g > 0.66 * v * Math.sqrt((2 * tt.support.mantle) / tt.jump.gravity)) {
        gapFailures++;
        console.log(`seed ${seed}: roof gap of ${g.toFixed(1)} m in lane ${lane} at s=${row[i].s0.toFixed(1)} is too long to catch`);
      }
    }
  }
  // C. Overhangs.
  const wides = [...seenHighs.values()].filter((h) => h.wide && h.s < seenUntil);
  const byS = new Map<string, typeof wides>();
  for (const h of wides) byS.set(h.s.toFixed(3), [...(byS.get(h.s.toFixed(3)) ?? []), h]);
  for (const [, group] of byS) {
    const at = group[0].s;
    const v = group[0].v;
    if (group.length !== tt.lanes.count) {
      overhangFailures++;
      console.log(`seed ${seed}: an overhang at s=${at.toFixed(1)} doesn't span every lane`);
    }
    const near = [...seenOther.values()].some((o) => !(o.kind === 'high' && Math.abs(o.s0 - at) < 1e-3) && o.s0 < at + 2 && o.s1 > at - tt.overhang.approach * v);
    const padNear = [...seenPads.values()].some((pd) => pd.s0 < at + 2 && pd.s1 > at - tt.overhang.approach * v);
    const supportEnds = [...statics.map((p) => p.s1), ...[...seenRails.values()].map((r) => r.s1)].some((e) => e <= at && e > at - tt.overhang.afterSupport * v + 1e-6);
    if (near || padNear || supportEnds) {
      overhangFailures++;
      console.log(`seed ${seed}: something too close to the overhang at s=${at.toFixed(1)}`);
    }
  }
  // D. Rail lanes.
  for (const r of seenRails.values()) {
    const bad = [...seenOther.values()].some((o) => o.lane === r.lane && (o.kind === 'post' || o.kind === 'movingPost' || o.kind === 'high' || o.kind === 'thumb') && o.s0 < r.s1 + 2 && o.s1 > r.s0 - 2);
    const badPad = [...seenPads.values()].some((pd) => pd.lane === r.lane && pd.s0 < r.s1 + 2 && pd.s1 > r.s0 - 2);
    if (bad || badPad) {
      railFailures++;
      console.log(`seed ${seed}: something under the rail in lane ${r.lane} at s=${r.s0.toFixed(1)}`);
    }
  }
  // E. Tunnels.
  const vi = tt.power.viral;
  const viralWindows = [...seenPowers.values()].filter((pu) => pu.kind === 'viral').map((pu) => [pu.s - 5, pu.s + vi.distance + vi.margin] as const);
  for (const tn of seenTunnels.values()) {
    let why = '';
    for (let k = 0; gateS(k) - tt.gate.clearBefore < tn.s1; k++) if (gateS(k) + tt.gate.clearAfter > tn.s0) why = 'a gate';
    if (w.course.touches(tn.s0, tn.s1, ['drop', 'airtime', 'loop', 'corkscrew'])) why = 'a thrill ride';
    if ([...seenPads.values()].some((pd) => pd.kind === 'bouncer' && pd.s0 < tn.s1 && pd.s1 > tn.s0)) why = 'a bouncer';
    if ([...seenOther.values()].some((o) => o.kind === 'thumb' && o.s0 < tn.s1 && o.s1 > tn.s0)) why = 'a thumb';
    if (viralWindows.some(([a, b]) => a < tn.s1 && b > tn.s0)) why = 'a Going Viral flight';
    if (why) {
      tunnelFailures++;
      console.log(`seed ${seed}: ${why} in the tunnel at s=${tn.s0.toFixed(1)}`);
    }
  }
  // F. Power-ups.
  const powers = [...seenPowers.values()].sort((a, b) => a.s - b.s);
  for (let i = 1; i < powers.length; i++) {
    if (powers[i].s - powers[i - 1].s < tt.power.gapMin - 1e-6) {
      powerFailures++;
      console.log(`seed ${seed}: power-ups only ${(powers[i].s - powers[i - 1].s).toFixed(0)} m apart at s=${powers[i].s.toFixed(1)}`);
    }
  }
  for (const [a, b] of viralWindows) {
    let bad = w.course.touches(a - tt.course.sceneryMargin, b + tt.course.sceneryMargin, ['loop', 'corkscrew']);
    for (let k = 0; gateS(k) - tt.gate.clearBefore < b; k++) if (gateS(k) + tt.gate.clearAfter > a) bad = true;
    if (bad) {
      powerFailures++;
      console.log(`seed ${seed}: a Going Viral flight from s=${(a + 5).toFixed(1)} crosses a gate or a loop`);
    }
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
console.log(`traps: ${trapFailures} · roof gaps: ${gapFailures} · overhangs: ${overhangFailures} · rails: ${railFailures} · tunnels: ${tunnelFailures} · power-ups: ${powerFailures} · soak: ${soakFailures}`);
console.log(`power-ups taken: ${powersTaken} (${(powersTaken / SEEDS).toFixed(1)}/run) · screen protectors cracked: ${shieldsUsed} · grind ${Math.round(grindMetres / SEEDS)} m/run · roof ${Math.round(roofSeconds / SEEDS)} s/run · crashes by kind: ${JSON.stringify(crashKinds)}`);
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
  return `${w.d.toFixed(6)}|${w.dopamine.toFixed(6)}|${w.pickupsTaken}|${w.score}|${w.history.map((h) => h.toFixed(3)).join(',')}`;
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
  const bytes = rec.encode({ v: GHOST_VERSION, seed: 7, ch: 0, name: '@check', mode: 'personal', day: 0, dist: Math.round(w.d), killer: 'a check' });
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

// --- Roof riders: head for every stairs, ride the roofs to the end without
// jumping (walk off, catch the next edge), with power-ups handed out on the way.
// Nothing up there may kill you.
let roofRideFailures = 0;
let roofRideSeconds = 0;
for (let seed = 1; seed <= 30; seed++) {
  const w = new World(seed);
  const bot = new Bot();
  for (let i = 0; i < 120 * 200 && w.phase !== 'dead'; i++) {
    let actions: Action[] = bot.think(w, DT);
    const p = w.player;
    const stairs = w.obstacles.find((o) => o.kind === 'post' && o.ramp > 0 && o.s - o.ramp - w.d > 3 && o.s - o.ramp - w.d < 30);
    if (stairs && p.grounded && p.on === 'ground') {
      actions = actions.filter((a) => a !== 'left' && a !== 'right');
      if (Math.abs(p.x - laneX(p.lane)) < 0.05 && p.lane !== stairs.lane) actions.push(stairs.lane > p.lane ? 'right' : 'left');
    }
    const mine = w.obstacles.some((o) => o.kind === 'post' && o.ramp > 0 && o.lane === p.lane && o.s - o.ramp - w.d > -1 && o.s - o.ramp - w.d <= 3);
    if (mine || p.on === 'roof' || p.on === 'stairs' || (!p.grounded && p.perch > 2)) actions = actions.filter((a) => a !== 'left' && a !== 'right' && a !== 'up');
    if (i === 600) w.givePower(seed % 2 ? 'kicks' : 'magnet');
    if (i === 1200 && seed % 3 === 0) w.givePower('viral');
    const up = (p.grounded && (p.on === 'roof' || p.on === 'stairs')) || (!p.grounded && p.perch > 2);
    w.step(DT, actions);
    for (const e of w.drainEvents()) {
      if (e.type === 'crash' && up) {
        roofRideFailures++;
        console.log(`seed ${seed}: crashed into a ${e.kind} from a roof at d=${w.d.toFixed(1)}`);
      }
    }
  }
  roofRideSeconds += w.roofTime;
}
console.log(`roof riders: ${Math.round(roofRideSeconds)} s on roofs over 30 runs · failures: ${roofRideFailures}`);

const v2Failures = roofRideFailures + trapFailures + gapFailures + overhangFailures + railFailures + tunnelFailures + powerFailures + soakFailures;
if (v2Failures > 0 || blockedFailures > 0 || habitFailures > 0 || reviveFailures > 0 || gateFailures > 0 || rideFailures > 0 || dailyFailures > 0 || ghostFailures > 0 || pieceFailures > 0 || revivesTested < 5) process.exit(1);
