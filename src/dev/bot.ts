// A simple autopilot that reads the sim state and plays. Used for automated
// fairness/soak tests (?bot=1) and later as an attract mode on the title screen.

import { laneX, type Action } from '../sim/types';
import type { World } from '../sim/world';

export class Bot {
  private cooldown = 0;

  think(w: World, dt: number): Action[] {
    if (w.phase !== 'running') return w.phase === 'ready' ? ['tap'] : [];
    this.cooldown = Math.max(0, this.cooldown - dt);
    const t = w.t;
    const p = w.player;
    const v = w.speed;
    const lanes = t.lanes.count;

    // How far until each lane is blocked by a post (0 = blocked right now).
    const clearance = (lane: number): number => {
      let best = Infinity;
      for (const o of w.obstacles) {
        if (o.lane !== lane || (o.kind !== 'post' && o.kind !== 'movingPost' && o.kind !== 'thumb')) continue;
        if (o.s + o.length < w.d - 0.5) continue;
        if (o.s <= w.d + 0.6) return 0;
        let dist = o.s - w.d;
        if (o.kind === 'movingPost' || o.kind === 'thumb') dist *= v / (v + o.speed);
        best = Math.min(best, dist);
      }
      return best;
    };

    const actions: Action[] = [];
    const cur = p.lane;
    const settled = Math.abs(p.x - laneX(cur, t)) < 0.05;

    if (settled && this.cooldown === 0) {
      const scores = Array.from({ length: lanes }, (_, l) => clearance(l));
      const safe = v * 1.6;
      if (scores[cur] >= safe) {
        // Safe: drift toward the adjacent lane with the juiciest content ahead.
        const juice = (lane: number): number => {
          let sum = 0;
          for (const pk of w.pickups) {
            const ahead = pk.s - w.d;
            if (pk.lane === lane && !pk.taken && ahead > 2 && ahead < 30) sum += w.tolerance[pk.type];
          }
          return sum;
        };
        let target = cur;
        let best = juice(cur) + 0.5;
        for (const l of [cur - 1, cur + 1]) {
          if (l < 0 || l >= lanes || scores[l] < safe) continue;
          const j = juice(l);
          if (j > best) {
            best = j;
            target = l;
          }
        }
        if (target !== cur) {
          actions.push(target > cur ? 'right' : 'left');
          this.cooldown = t.laneSwitchTime + 0.02;
        }
      } else {
        let target = cur;
        let bestScore = scores[cur];
        for (let l = 0; l < lanes; l++) {
          if (l === cur) continue;
          const path = l > cur ? 1 : -1;
          let reachable = true;
          for (let m = cur + path; m !== l; m += path) if (scores[m] < 1) reachable = false;
          const s = scores[l] - Math.abs(l - cur) * 2;
          if (reachable && s > bestScore) {
            bestScore = s;
            target = l;
          }
        }
        if (target !== cur) {
          const next = cur + (target > cur ? 1 : -1);
          if (clearance(next) > v * 0.3) {
            actions.push(target > cur ? 'right' : 'left');
            this.cooldown = t.laneSwitchTime + 0.02;
          }
        }
      }
    }

    // Barriers and habits in the current lane.
    for (const o of w.obstacles) {
      if (o.lane !== p.lane || (o.kind !== 'low' && o.kind !== 'high' && o.kind !== 'habit') || o.hit) continue;
      const dist = o.s - w.d;
      if (dist < 0) continue;
      const tti = dist / v;
      if ((o.kind === 'low' || o.kind === 'habit') && p.grounded && tti < 0.3 && tti > 0.08) actions.push('up');
      if (o.kind === 'high' && p.rollT <= 0.05 && tti < 0.25) actions.push('down');
    }
    return actions;
  }
}
