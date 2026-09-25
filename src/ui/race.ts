// A challenge run against a friend's ghost (sim/ghost.ts, ghostLink.ts). The
// lock-screen challenge card lives in title.ts; this owns what happens in the
// run: fake pushes when you overtake them or they ghost you, the "skill issue"
// push when you die first, the tag floating over the ghost (their name, then
// their grave), and the result the receipt prints.
// Pushes sit at the top edge, like every other notification: never over the track.

import { content } from '../content/content';
import { fill } from '../content/templates';
import type { GhostFrame, GhostTrack } from '../sim/ghost';
import { TUNING } from '../sim/types';
import type { World } from '../sim/world';
import { distanceText } from './daily';
import type { Sfx } from './sfx';

export interface RaceResult {
  name: string;
  won: boolean;
  /** Metres between you and them at the end, always positive. */
  by: number;
}

export class Race {
  track: GhostTrack | null = null;
  private readonly tag: HTMLElement;
  private readonly toast: HTMLElement;
  private readonly frame: GhostFrame = { d: 0, x: 0, y: 0, roll: false, air: false };
  /** -1 behind the ghost, 1 ahead, 0 not yet decided (the start). */
  private lead = 0;
  private passedGrave = false;
  private deathSeen = false;
  private toastLeft = 0;

  constructor(parent: HTMLElement, private readonly sfx: Sfx) {
    this.tag = document.createElement('div');
    this.tag.className = 'ghost-tag hidden';
    this.toast = document.createElement('div');
    this.toast.className = 'race-toast hidden';
    parent.append(this.tag, this.toast);
  }

  get name(): string {
    return this.track?.header.name ?? '';
  }

  start(track: GhostTrack): void {
    this.track = track;
    this.lead = 0;
    this.passedGrave = false;
    this.deathSeen = false;
  }

  clear(): void {
    this.track = null;
    this.tag.classList.add('hidden');
    this.toast.classList.add('hidden');
  }

  result(w: World): RaceResult | null {
    if (!this.track) return null;
    const by = w.d - this.track.finalD;
    return { name: this.name, won: by > 0, by: Math.abs(by) };
  }

  update(w: World, dt: number, tag: { x: number; y: number; on: boolean; grave: boolean }): void {
    const track = this.track;
    this.toastLeft -= dt;
    if (this.toastLeft <= 0) this.toast.classList.add('hidden');
    if (!track) return;
    const r = content.race;

    // Only while you're still scrolling: the death screens own the middle of the screen.
    const showTag = tag.on && (w.phase === 'running' || w.phase === 'fading');
    this.tag.classList.toggle('hidden', !showTag);
    if (showTag) {
      this.tag.classList.toggle('grave', tag.grave);
      this.tag.textContent = tag.grave ? fill(r.grave, { name: this.name, killer: track.header.killer }) : this.name;
      this.tag.style.transform = `translate(${tag.x}px, ${tag.y}px) translate(-50%, -100%)`;
    }

    if (w.phase === 'running' && w.gateT < 0) {
      const margin = TUNING.ghost.passMargin;
      if (w.time < track.duration) {
        const diff = w.d - track.at(w.time, this.frame).d;
        if (diff < -margin && this.lead >= 0) {
          if (this.lead === 1) this.push(fill(r.ghosted, { name: this.name }));
          this.lead = -1;
        } else if (diff > margin && this.lead <= 0) {
          if (this.lead === -1) this.push(fill(r.passed, { name: this.name }));
          this.lead = 1;
        }
      } else if (!this.passedGrave && w.d > track.finalD) {
        this.passedGrave = true;
        this.push(fill(r.passed, { name: this.name }));
      }
    }
    if (w.phase === 'dead' && !this.deathSeen) {
      this.deathSeen = true;
      if (w.d < track.finalD) this.push(fill(r.skillIssue, { name: this.name }));
    } else if (w.phase === 'running') this.deathSeen = false;
  }

  private push(text: string): void {
    this.toast.innerHTML = `<div class="rt-head"><b>${content.race.app}</b><span>now</span></div><div class="rt-text"></div>`;
    this.toast.querySelector('.rt-text')!.textContent = text;
    this.toast.classList.remove('hidden', 'in');
    // Restart the drop-in animation.
    void this.toast.offsetWidth;
    this.toast.classList.add('in');
    this.toastLeft = TUNING.ghost.toastSeconds;
    this.sfx.chime();
  }
}

/** Receipt lines for a finished race. */
export function raceLines(res: RaceResult): { big: string; small: string } {
  const r = content.race;
  return {
    big: fill(res.won ? r.won : r.lost, { name: res.name.toUpperCase() }),
    small: fill(r.by, { distance: distanceText(res.by).toUpperCase(), diff: res.won ? r.you : res.name.toUpperCase() }),
  };
}

/** First line of the share text after a race. */
export function raceShareLine(res: RaceResult): string {
  const r = content.race;
  return fill(res.won ? r.shareWon : r.shareLost, { name: res.name, distance: distanceText(res.by) });
}
