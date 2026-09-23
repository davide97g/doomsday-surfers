// "You've been scrolling for N minutes. Keep going?" [YES] [yes]
// Pauses the run (main stops stepping the sim) until you agree.

import content from '../config/content.json';
import { fill } from '../content/templates';
import { TUNING } from '../sim/types';
import type { World } from '../sim/world';
import type { Sfx } from './sfx';

export class KeepGoing {
  paused = false;
  private played = 0;
  private next = TUNING.ui.keepGoingEvery;
  private readonly el: HTMLElement;
  private readonly title: HTMLElement;

  constructor(parent: HTMLElement, private readonly sfx: Sfx) {
    const c = content.keepGoing;
    this.el = document.createElement('div');
    this.el.className = 'overlay prompt hidden';
    this.el.innerHTML = `
      <div class="prompt-card" data-ui>
        <div class="prompt-title"></div>
        <div class="prompt-body">${c.body}</div>
        <div class="prompt-buttons">
          <button class="cta small" data-act="yes">${c.yes}</button>
          <button class="cta small alt" data-act="yes">${c.alsoYes}</button>
        </div>
      </div>`;
    this.title = this.el.querySelector('.prompt-title')!;
    this.el.addEventListener('click', (e) => {
      if ((e.target as HTMLElement).dataset.act !== 'yes') return;
      this.sfx.click();
      this.el.classList.add('hidden');
      this.paused = false;
    });
    parent.appendChild(this.el);
  }

  /** Counts real playing time across the whole session. */
  update(w: World, dt: number): void {
    if (this.paused || w.phase !== 'running') return;
    this.played += dt;
    if (this.played < this.next) return;
    this.next += TUNING.ui.keepGoingEvery;
    this.paused = true;
    this.title.textContent = fill(content.keepGoing.title, { m: Math.round(this.played / 60) });
    this.el.classList.remove('hidden');
    this.sfx.chime();
  }
}
