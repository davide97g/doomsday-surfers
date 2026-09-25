// Title screen, dressed as the lock screen of the phone you're about to
// doomscroll on: date, clock, a lock-screen notification, the character
// select as a widget, and "swipe up" to unlock (start an endless run).
// The notification is Today's Feed (daily.ts): "⚠️ Time to Doom. ⚠️" with a
// parody live counter and the streak nag; tap it to scroll today's feed. Once
// played it turns into the result with a countdown to the next feed. It comes
// back every time the lock screen does (a nag, on purpose).
// Opened from a challenge link, the notification is the challenge instead
// (race.ts): accept to race their ghost, as often as you like.
// A Focus pill above the clock switches Personal / Work mode (content.ts):
// it flashes the iOS-style "Work Focus on" banner, then restarts the app.
// The character select (select.ts) mounts in `slot`. The streak (days you
// played the Daily) lives in localStorage, a per-device convenience.

import { content, mode, switchMode, work } from '../content/content';
import { fill } from '../content/templates';
import type { Phase } from '../sim/types';
import { countdown, liveCount, loadToday, today } from './daily';
import type { Sfx } from './sfx';

const KEY = 'ds.streak';

interface Streak {
  last: string;
  n: number;
}

function day(offsetDays = 0): string {
  return new Date(Date.now() + offsetDays * 864e5).toLocaleDateString('en-CA');
}

/** Whole days from local date `a` to `b` (both YYYY-MM-DD). */
function daysBetween(a: string, b: string): number {
  return Math.round((new Date(`${b}T00:00`).getTime() - new Date(`${a}T00:00`).getTime()) / 864e5);
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

  onDaily: () => void = () => {};
  onShare: (text: string) => void = () => {};
  onChallenge: () => void = () => {};
  onChallengeDecline: () => void = () => {};
  private challenge: { name: string; distance: string; daily: boolean } | null = null;
  private readonly note: { app: HTMLElement; title: HTMLElement; text: HTMLElement; primary: HTMLElement; decline: HTMLElement };
  private cardDay = 0;
  private cardDone = false;
  private cardChallenge = false;
  private shownSec = -1;

  constructor(parent: HTMLElement, private readonly sfx: Sfx) {
    this.el = document.createElement('div');
    this.el.className = 'lock';
    this.el.innerHTML = `
      <header class="lock-top">
        <button class="focus" data-ui aria-label="Switch Focus">
          <span class="focus-glyph"></span><span class="focus-label">${mode === 'work' ? work.focus.work : work.focus.personal}</span>
        </button>
        <div class="lock-date"></div>
        <div class="lock-time"></div>
        <h1 class="lock-brand">Doomsday Surfers</h1>
      </header>
      <div class="lock-note" data-ui>
        <div class="note-icon"><span class="flame"></span></div>
        <div class="note-body">
          <div class="note-head"><b class="note-app"></b><span>now</span></div>
          <div class="note-title"></div>
          <div class="note-text"></div>
          <div class="note-actions">
            <button class="note-claim" data-act="primary"></button>
            <button class="note-decline" data-act="decline"></button>
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
    const q = (sel: string) => this.card.querySelector<HTMLElement>(sel)!;
    this.note = { app: q('.note-app'), title: q('.note-title'), text: q('.note-text'), primary: q('.note-claim'), decline: q('.note-decline') };
    this.renderCard();
    this.slot = this.el.querySelector('.lock-slot')!;
    this.time = this.el.querySelector('.lock-time')!;
    this.date = this.el.querySelector('.lock-date')!;
    this.tick();
    const focus = this.el.querySelector<HTMLButtonElement>('.focus')!;
    focus.addEventListener('click', () => {
      const next = mode === 'work' ? 'personal' : 'work';
      this.sfx.click();
      const flash = document.createElement('div');
      flash.className = `focus-flash to-${next}`;
      flash.textContent = fill(work.focus.on, { name: next === 'work' ? work.focus.work : work.focus.personal });
      this.el.append(flash);
      focus.disabled = true;
      setTimeout(() => switchMode(next), 650);
    });
    this.card.addEventListener('click', (e) => {
      const act = (e.target as HTMLElement).dataset.act;
      if (this.cardChallenge) {
        this.sfx.click();
        if (act === 'decline') this.onChallengeDecline();
        else this.onChallenge();
        return;
      }
      if (act === 'decline') {
        if (this.cardDone) {
          // "Claim nothing"
          this.sfx.reward();
          this.note.text.textContent = content.streak.claimed;
          setTimeout(() => this.card.classList.add('hidden'), 1200);
        } else {
          this.sfx.click();
          this.card.classList.add('hidden');
        }
      } else if (!this.cardDone) {
        // Tapping the notification anywhere opens it, like a real one.
        this.sfx.click();
        this.onDaily();
      } else if (act === 'primary') {
        const line = loadToday()?.result?.line;
        if (!line) return;
        this.sfx.click();
        this.onShare(line);
      }
    });
  }

  update(phase: Phase): void {
    if (phase === 'ready') {
      this.tick();
      this.tickCard();
    }
    if (phase === this.phase) return;
    // Back on the lock screen: the notification is back too.
    if (phase === 'ready') this.renderCard();
    this.phase = phase;
    this.el.classList.toggle('hidden', phase !== 'ready');
  }

  /** The streak nag, escalating with the days you've missed (Duolingo energy). */
  private streakLine(): string {
    const s = content.streak;
    const st = load();
    if (!st) return s.first;
    const gap = daysBetween(st.last, day());
    if (gap <= 0) return fill(s.safe, { n: st.n });
    if (gap === 1) return fill(s.danger, { n: st.n });
    return fill(s.escalation[Math.min(gap - 2, s.escalation.length - 1)], { n: st.n });
  }

  /** A friend's challenge takes over the notification (null: back to Today's Feed). */
  setChallenge(c: { name: string; distance: string; daily: boolean } | null): void {
    this.challenge = c;
    this.renderCard();
  }

  /** The challenge, Today's Feed invite, or today's result once played. Numbers tick in tickCard. */
  private renderCard(): void {
    const d = content.daily;
    const s = content.streak;
    const n = today();
    const name = fill(d.name, { n });
    const rec = loadToday();
    this.cardDay = n;
    this.cardDone = !!rec;
    this.cardChallenge = !!this.challenge;
    this.shownSec = -1;
    const n$ = this.note;
    if (this.challenge) {
      // The name comes from a link someone sent: text only, never HTML.
      const r = content.race;
      const c = this.challenge;
      n$.app.textContent = r.app;
      n$.title.textContent = fill(r.title, { name: c.name });
      n$.text.textContent = fill(c.daily ? r.daily : r.text, { distance: c.distance });
      n$.primary.textContent = r.accept;
      n$.primary.classList.remove('hidden');
      n$.decline.textContent = r.decline;
    } else if (!rec) {
      n$.app.textContent = d.app;
      n$.title.textContent = d.title;
      n$.text.innerHTML = `${fill(d.live, { name, count: '<span class="note-num"></span>' })} ${this.streakLine()}`;
      n$.primary.textContent = d.cta;
      n$.primary.classList.remove('hidden');
      n$.decline.textContent = d.decline;
    } else {
      const st = load();
      n$.app.textContent = s.app;
      n$.title.textContent = rec.result
        ? fill(d.done, { name, distance: rec.result.distance, emoji: rec.result.emoji })
        : fill(d.abandoned, { name });
      n$.text.innerHTML = `${fill(d.next, { time: '<span class="note-num"></span>' })} ${fill(s.safe, { n: st?.n ?? 1 })} ${fill(s.reward, { n: st?.n ?? 1 })}`;
      n$.primary.textContent = d.share;
      n$.primary.classList.toggle('hidden', !rec.result);
      n$.decline.textContent = s.claim;
    }
    this.card.classList.remove('hidden');
    this.tickCard();
  }

  /** Once a second: the live counter or the countdown, and a new card at midnight. */
  private tickCard(): void {
    const now = new Date();
    const sec = Math.floor(now.getTime() / 1000);
    if (sec === this.shownSec) return;
    this.shownSec = sec;
    if (today() !== this.cardDay) {
      this.renderCard();
      return;
    }
    const num = this.card.querySelector('.note-num');
    if (num) num.textContent = this.cardDone ? countdown(now) : liveCount(now).toLocaleString('en-US');
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

  /** A Daily run started: keep (or restart) the streak. */
  onRunStart(): void {
    const s = load();
    if (s?.last === day()) return;
    save({ last: day(), n: s && s.last === day(-1) ? s.n + 1 : 1 });
  }
}
