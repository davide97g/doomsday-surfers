// Work mode desk: every card you open docks its app window (apps.ts) in a
// side column, left and right, two high, inside the top 60% of the screen.
// Windows never close by themselves and can't be closed: only a checkpoint
// gate (or the end of the run) clears the desk. When all slots are full the
// oldest window gets replaced. Windows ignore pointers, so swipes still reach
// the track; each open window drips dopamine in the sim (world.setOpenWindows).

import { TUNING } from '../sim/types';
import type { World } from '../sim/world';
import { makeWindow } from './apps';
import type { AppWindow } from './meeting';

const SLOTS = ['l0', 'r0', 'l1', 'r1'].slice(0, TUNING.work.windows.max);
const LEAVE_MS = 300;

interface Docked {
  win: AppWindow;
  slot: string;
}

export class Desk {
  /** Called with the number of open windows whenever it changes. */
  onChange: (n: number) => void = () => {};
  private readonly el: HTMLElement;
  private readonly docked: Docked[] = [];

  constructor(parent: HTMLElement) {
    this.el = document.createElement('div');
    this.el.className = 'desk';
    parent.append(this.el);
  }

  get count(): number {
    return this.docked.length;
  }

  open(kind: string, who: string, text: string): void {
    const used = new Set(this.docked.map((d) => d.slot));
    let slot = SLOTS.find((s) => !used.has(s));
    if (!slot) {
      const oldest = this.docked.shift()!;
      slot = oldest.slot;
      this.leave(oldest.win);
    }
    const win = makeWindow(kind, who, text);
    win.el.classList.add(`slot-${slot}`, slot[0] === 'l' ? 'from-left' : 'from-right');
    this.el.append(win.el);
    this.docked.push({ win, slot });
    this.onChange(this.docked.length);
  }

  update(w: World, dt: number, paused: boolean): void {
    if (this.docked.length === 0) return;
    if (w.phase !== 'running') {
      this.clear();
      return;
    }
    if (paused) return;
    for (const d of this.docked) d.win.update(dt);
  }

  /** Close everything (a gate, or the run ended). */
  clear(): void {
    if (this.docked.length === 0) return;
    for (const d of this.docked) this.leave(d.win);
    this.docked.length = 0;
    this.onChange(0);
  }

  private leave(win: AppWindow): void {
    win.el.classList.add('leaving');
    setTimeout(() => win.el.remove(), LEAVE_MS);
  }
}
