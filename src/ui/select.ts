// Character select on the title screen. Swipe left/right (or the arrows) to
// switch doomscroller; the renderer turns the chosen one on a turntable.
// The pick is remembered in localStorage (a per-device convenience).

import content from '../config/content.json';
import { fill } from '../content/templates';
import { TUNING, type Action } from '../sim/types';
import { restartAnimation } from './nags';
import type { Sfx } from './sfx';

const KEY = 'ds.character';
const COUNT = TUNING.characters.count;

function load(): number {
  try {
    const n = Number(localStorage.getItem(KEY));
    return Number.isInteger(n) && n >= 0 && n < COUNT ? n : 0;
  } catch {
    return 0;
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
    this.index = (this.index + dir + COUNT) % COUNT;
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
    this.el.querySelector('.select-dots')!.innerHTML = Array.from({ length: COUNT }, (_, i) => `<i class="${i === this.index ? 'on' : ''}"></i>`).join('');
  }
}
