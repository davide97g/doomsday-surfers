// Character select on the title screen. Swipe left/right (or the arrows) to
// switch doomscroller; the renderer turns the chosen one on a turntable.
// Only the current mode's cast is on the turntable (Work mode has its own).
// The pick is remembered per mode in localStorage (a per-device convenience).

import { content, mode } from '../content/content';
import { fill } from '../content/templates';
import { TUNING, type Action } from '../sim/types';
import { restartAnimation } from './nags';
import type { Sfx } from './sfx';

const KEY = mode === 'work' ? 'ds.character.work' : 'ds.character';
/** Character indices (into tuning and content characters) playable in this mode. */
const ROSTER = content.characters
  .map((c: { mode?: string }, i) => ((c.mode ?? 'personal') === mode && i < TUNING.characters.count ? i : -1))
  .filter((i) => i >= 0);

function load(): number {
  try {
    const n = Number(localStorage.getItem(KEY));
    return ROSTER.includes(n) && localStorage.getItem(KEY) !== null ? n : ROSTER[0];
  } catch {
    return ROSTER[0];
  }
}

function save(n: number): void {
  try {
    localStorage.setItem(KEY, String(n));
  } catch {
    // Blocked storage: you just pick again next time.
  }
}

export class Select {
  index = load();
  onChange: (index: number) => void = () => {};
  private readonly el: HTMLElement;

  constructor(parent: HTMLElement, private readonly sfx: Sfx) {
    this.el = document.createElement('div');
    this.el.className = 'select';
    this.el.innerHTML = `
      <div class="select-row">
        <button class="select-arrow" data-ui data-dir="-1" aria-label="Previous">&lsaquo;</button>
        <div class="select-name"></div>
        <button class="select-arrow" data-ui data-dir="1" aria-label="Next">&rsaquo;</button>
      </div>
      <div class="select-card">
        <div class="select-bio"></div>
        <div class="select-stats"></div>
        <div class="select-craving"></div>
      </div>
      <div class="select-dots"></div>`;
    this.el.addEventListener('click', (e) => {
      const dir = Number((e.target as HTMLElement).dataset.dir);
      if (dir) this.step(dir);
    });
    parent.appendChild(this.el);
    this.render();
  }

  /** Title-screen input: left/right switch character, anything else passes through. */
  filter(actions: Action[]): Action[] {
    return actions.filter((a) => {
      if (a !== 'left' && a !== 'right') return true;
      this.step(a === 'left' ? -1 : 1);
      return false;
    });
  }

  private step(dir: number): void {
    const at = ROSTER.indexOf(this.index);
    this.index = ROSTER[(at + dir + ROSTER.length) % ROSTER.length];
    save(this.index);
    this.sfx.click();
    this.render();
    // Slide the new profile in from the side you swiped toward.
    this.el.dataset.dir = dir > 0 ? 'next' : 'prev';
    restartAnimation(this.el.querySelector('.select-card')!);
    restartAnimation(this.el.querySelector('.select-name')!);
    this.onChange(this.index);
  }

  private render(): void {
    const c: { name: string; bio: string; stats: string[]; perk?: string } = content.characters[this.index];
    const fav = TUNING.characters.favourite[this.index];
    this.el.querySelector('.select-name')!.textContent = c.name;
    this.el.querySelector('.select-bio')!.textContent = c.bio;
    this.el.querySelector('.select-stats')!.innerHTML = c.stats.map((s) => `<div>${s}</div>`).join('');
    this.el.querySelector('.select-craving')!.textContent = c.perk ?? fill(content.select.craving, { type: content.contentTypes[fav].name });
    this.el.querySelector('.select-dots')!.innerHTML = ROSTER.map((i) => `<i class="${i === this.index ? 'on' : ''}"></i>`).join('');
  }
}
