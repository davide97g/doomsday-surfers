// Title screen + streak guilt. The streak lives in localStorage (a per-device
// convenience, nothing depends on it) and the card shows once per session.

import content from '../config/content.json';
import { fill } from '../content/templates';
import type { Phase } from '../sim/types';
import type { Sfx } from './sfx';

const KEY = 'ds.streak';

interface Streak {
  last: string;
  n: number;
}

function day(offsetDays = 0): string {
  return new Date(Date.now() + offsetDays * 864e5).toLocaleDateString('en-CA');
}

function load(): Streak | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Streak) : null;
  } catch {
    return null;
  }
}

function save(s: Streak): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    // Private mode or blocked storage: the guilt just doesn't persist.
  }
}

export class Title {
  private readonly el: HTMLElement;
  private readonly card: HTMLElement;
  private phase: Phase | null = null;

  constructor(parent: HTMLElement, private readonly sfx: Sfx) {
    const s = content.streak;
    const streak = load();
    let line: string;
    let rewardDay: number;
    if (!streak) {
      line = s.first;
      rewardDay = 1;
    } else if (streak.last === day()) {
      line = fill(s.safe, { n: streak.n });
      rewardDay = streak.n;
    } else if (streak.last === day(-1)) {
      line = fill(s.danger, { n: streak.n });
      rewardDay = streak.n + 1;
    } else {
      line = fill(s.lost, { n: streak.n });
      rewardDay = 1;
    }

    this.el = document.createElement('div');
    this.el.className = 'overlay ready';
    this.el.innerHTML = `
      <div class="logo">DOOMSDAY<br>SURFERS</div>
      <div class="hint">swipe to start scrolling</div>
      <div class="controls">&larr; &rarr; switch &middot; &uarr; jump &middot; &darr; roll</div>
      <div class="streak" data-ui>
        <div class="streak-line"><span class="flame"></span>${line}</div>
        <div class="streak-reward">${fill(s.reward, { n: rewardDay })}</div>
        <button class="cta small" data-act="claim">${s.claim}</button>
        <button class="decline" data-act="decline">${s.decline}</button>
      </div>
    `;
    parent.appendChild(this.el);
    this.card = this.el.querySelector('.streak')!;
    this.card.addEventListener('click', (e) => {
      const act = (e.target as HTMLElement).dataset.act;
      if (act === 'claim') {
        this.sfx.reward();
        this.card.querySelector('.streak-reward')!.textContent = 'Claimed. You now have nothing.';
        setTimeout(() => this.card.classList.add('hidden'), 1200);
      } else if (act === 'decline') {
        this.sfx.click();
        this.card.classList.add('hidden');
      }
    });
  }

  update(phase: Phase): void {
    if (phase === this.phase) return;
    // The card is a first-launch thing; after the first run it stays gone.
    if (this.phase === 'ready' && phase === 'running') this.card.classList.add('hidden');
    this.phase = phase;
    this.el.classList.toggle('hidden', phase !== 'ready');
  }

  /** A run started: keep (or restart) the streak. */
  onRunStart(): void {
    const s = load();
    if (s?.last === day()) return;
    save({ last: day(), n: s && s.last === day(-1) ? s.n + 1 : 1 });
  }
}
