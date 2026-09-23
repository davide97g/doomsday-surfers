// Title screen, dressed as the lock screen of the phone you're about to
// doomscroll on: date, clock, the streak nag as a lock-screen notification,
// the character select as a widget, and "swipe up" to unlock (start the run).
// The character select (select.ts) mounts in `slot`. The streak lives in localStorage (a per-device
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
  /** Where the character select sits, above the unlock prompt. */
  readonly slot: HTMLElement;
  private readonly time: HTMLElement;
  private readonly date: HTMLElement;
  private shownTime = '';
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
    this.el.className = 'lock';
    this.el.innerHTML = `
      <header class="lock-top">
        <div class="lock-date"></div>
        <div class="lock-time"></div>
        <h1 class="lock-brand">Doomsday Surfers</h1>
      </header>
      <div class="lock-note" data-ui>
        <div class="note-icon"><span class="flame"></span></div>
        <div class="note-body">
          <div class="note-head"><b>${s.app}</b><span>now</span></div>
          <div class="note-title">${line}</div>
          <div class="note-text">${fill(s.reward, { n: rewardDay })}</div>
          <div class="note-actions">
            <button class="note-claim" data-act="claim">${s.claim}</button>
            <button class="note-decline" data-act="decline">${s.decline}</button>
          </div>
        </div>
      </div>
      <footer class="lock-bottom">
        <div class="lock-slot"></div>
        <div class="unlock">
          <span class="unlock-label">${content.select.unlock}</span>
          <span class="home-bar"></span>
        </div>
        <div class="keys"><span>&larr; &rarr; pick</span><span>&uarr; start, jump</span><span>&darr; roll</span></div>
      </footer>
    `;
    parent.appendChild(this.el);
    this.card = this.el.querySelector('.lock-note')!;
    this.slot = this.el.querySelector('.lock-slot')!;
    this.time = this.el.querySelector('.lock-time')!;
    this.date = this.el.querySelector('.lock-date')!;
    this.tick();
    this.card.addEventListener('click', (e) => {
      const act = (e.target as HTMLElement).dataset.act;
      if (act === 'claim') {
        this.sfx.reward();
        this.card.querySelector('.note-text')!.textContent = 'Claimed. You now have nothing.';
        setTimeout(() => this.card.classList.add('hidden'), 1200);
      } else if (act === 'decline') {
        this.sfx.click();
        this.card.classList.add('hidden');
      }
    });
  }

  update(phase: Phase): void {
    if (phase === 'ready') this.tick();
    if (phase === this.phase) return;
    // The card is a first-launch thing; after the first run it stays gone.
    if (this.phase === 'ready' && phase === 'running') this.card.classList.add('hidden');
    this.phase = phase;
    this.el.classList.toggle('hidden', phase !== 'ready');
  }

  /** The lock-screen clock shows the real time: it's later than you think. */
  private tick(): void {
    const now = new Date();
    // Lock-screen style: no AM/PM, whatever the locale's clock.
    const time = new Intl.DateTimeFormat([], { hour: 'numeric', minute: '2-digit' })
      .formatToParts(now)
      .filter((p) => p.type !== 'dayPeriod')
      .map((p) => p.value)
      .join('')
      .trim();
    if (time === this.shownTime) return;
    this.shownTime = time;
    this.time.textContent = time;
    this.date.textContent = now.toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' });
  }

  /** A run started: keep (or restart) the streak. */
  onRunStart(): void {
    const s = load();
    if (s?.last === day()) return;
    save({ last: day(), n: s && s.last === day(-1) ? s.n + 1 : 1 });
  }
}
