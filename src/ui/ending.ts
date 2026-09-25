// The hidden ending. Stay untouched on the final death screen and the feed
// tries to lure you back (30 / 45 / 55 s). Hold out to 60 s and the screen goes
// truly black, silence, "Screen off." Your reflection appears in the glass:
// the faceless runner, lit from below by the phone. They lower it; the glow
// leaves the face; daylight bleeds in with wind and birds. "This is the only
// ending." Then a secret receipt and [SCROLL AGAIN], which stays greyed out
// for a while and comes back as "scroll again?".
// Any touch before the last line cancels it: you lose the ending, the feed wins.
// Death (death.ts) owns the idle clock and the cancelling.

import { content } from '../content/content';
import { fill } from '../content/templates';
import { TUNING } from '../sim/types';
import type { World } from '../sim/world';
import { buildSecretReceipt, drawReceipt, shareCard, type Paper } from './receipt';
import type { Sfx } from './sfx';
import { shareFiles } from './share';

const E = TUNING.ending;

const FIGURE = `
<svg class="end-figure" viewBox="0 0 200 260" aria-hidden="true">
  <defs>
    <radialGradient id="end-glow" cx="50%" cy="80%" r="55%">
      <stop offset="0" stop-color="#8fe9ff" stop-opacity=".5"/>
      <stop offset="1" stop-color="#8fe9ff" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <path class="fig-body" d="M14 260 C 18 194, 56 164, 100 164 C 144 164, 182 194, 186 260 Z"/>
  <path class="fig-hood" d="M100 38 C 56 38, 42 78, 44 114 C 46 150, 64 180, 100 184 C 136 180, 154 150, 156 114 C 158 78, 144 38, 100 38 Z"/>
  <ellipse class="fig-void" cx="100" cy="120" rx="31" ry="40"/>
  <ellipse class="fig-glow" cx="100" cy="150" rx="72" ry="64" fill="url(#end-glow)"/>
  <rect class="fig-phone" x="84" y="198" width="32" height="54" rx="6"/>
</svg>`;

export class Ending {
  onRestart: () => void = () => {};
  /** Wind, birds and silence live in GameAudio. */
  onAmbience: (mode: 'off' | 'silent' | 'outside') => void = () => {};
  private readonly el: HTMLElement;
  private readonly toast: HTMLElement;
  private readonly strip: HTMLElement;
  private readonly again: HTMLButtonElement;
  private stage = 0;
  private lures = 0;
  private toastLeft = 0;
  private paper: Paper | null = null;
  private sharing = false;

  constructor(parent: HTMLElement, private readonly sfx: Sfx) {
    const e = content.ending;
    this.el = document.createElement('div');
    this.el.className = 'ending hidden';
    this.el.innerHTML = `
      <div class="end-sky"></div>
      ${FIGURE}
      <div class="end-glare"></div>
      <div class="end-off">${e.off}</div>
      <div class="end-line">${e.line}</div>
      <div class="end-receipt"></div>
      <div class="end-buttons">
        <button class="cta receipt-cta" data-ui data-act="proof">${content.report.cta}</button>
        <button class="cta" data-ui data-act="again" disabled>${content.death.cta}</button>
      </div>`;
    this.strip = this.el.querySelector('.end-receipt')!;
    this.again = this.el.querySelector('[data-act="again"]')!;
    this.el.addEventListener('click', (ev) => {
      const act = (ev.target as HTMLElement).dataset.act;
      if (act === 'again' && !this.again.disabled) {
        this.sfx.click();
        this.onRestart();
      } else if (act === 'proof') {
        this.sfx.click();
        void this.share();
      }
    });
    this.toast = document.createElement('div');
    this.toast.className = 'race-toast hidden';
    parent.append(this.el, this.toast);
  }

  /** Past the last line: the ending is found, touches no longer cancel it. */
  get found(): boolean {
    return this.stage >= 6;
  }

  /** `idle`: seconds untouched on the final death screen. */
  update(idle: number, dt: number, w: World): void {
    this.toastLeft -= dt;
    if (this.toastLeft <= 0) this.toast.classList.add('hidden');
    while (this.lures < E.lures.length && idle >= E.lures[this.lures]) this.lure(this.lures++);

    const at = [E.black, E.off, E.reflection, E.lower, E.daylight, E.line, E.buttons, E.buttons + E.lock];
    while (this.stage < at.length && idle >= at[this.stage]) this.enter(++this.stage, w);
  }

  private enter(stage: number, w: World): void {
    const el = this.el;
    switch (stage) {
      case 1: // black, silence
        el.classList.remove('hidden');
        this.toast.classList.add('hidden');
        this.onAmbience('silent');
        break;
      case 2:
        el.classList.add('s-off');
        break;
      case 3:
        el.classList.add('s-reflect');
        break;
      case 4:
        el.classList.add('s-lower');
        break;
      case 5:
        el.classList.add('s-day');
        this.onAmbience('outside');
        break;
      case 6:
        el.classList.add('s-line');
        break;
      case 7: {
        this.paper = drawReceipt(buildSecretReceipt(w));
        const c = this.paper.canvas;
        c.style.width = `${Math.min(260, window.innerWidth * 0.64)}px`;
        c.style.height = 'auto';
        this.strip.replaceChildren(c);
        el.classList.add('s-buttons');
        break;
      }
      case 8:
        this.again.disabled = false;
        this.again.textContent = content.ending.again;
        break;
    }
  }

  private lure(i: number): void {
    this.toast.innerHTML = `<div class="rt-head"><b>${content.notifications.app}</b><span>now</span></div><div class="rt-text"></div>`;
    this.toast.querySelector('.rt-text')!.textContent = fill(content.ending.lures[i]);
    this.toast.classList.remove('hidden', 'in');
    void this.toast.offsetWidth;
    this.toast.classList.add('in');
    this.toastLeft = TUNING.ghost.toastSeconds;
    this.sfx.chime();
  }

  /** Back to the plain death screen (a touch, or leaving it). */
  cancel(): void {
    if (this.stage === 0 && this.lures === 0) return;
    this.stage = 0;
    this.lures = 0;
    this.el.className = 'ending hidden';
    this.toast.classList.add('hidden');
    this.again.disabled = true;
    this.again.textContent = content.death.cta;
    this.onAmbience('off');
  }

  private async share(): Promise<void> {
    if (this.sharing || !this.paper) return;
    this.sharing = true;
    try {
      const card = await shareCard(this.paper, [content.ending.line, '']);
      await shareFiles([{ blob: card, name: 'the-only-ending.png' }], content.report.shareTitle, content.ending.shareText);
    } finally {
      this.sharing = false;
    }
  }
}
