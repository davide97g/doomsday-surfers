// Mid-run distractions: fake push notifications at the top and banner ads at
// the bottom. Purely cosmetic: they never block swipes on the track (the
// notification ignores pointers; the banner sits below the runner).

import content from '../config/content.json';
import { TUNING } from '../sim/types';
import type { World } from '../sim/world';
import { fill, pick } from '../content/templates';
import type { Sfx } from './sfx';

const UI = TUNING.ui;

function rand(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

export class Nags {
  notificationsShown = 0;
  bannersShown = 0;
  private readonly note: HTMLElement;
  private readonly noteText: HTMLElement;
  private readonly banner: HTMLElement;
  private readonly bannerClose: HTMLElement;
  private notifyIn = rand(UI.notifyMin, UI.notifyMax);
  private noteLeft = 0;
  private bannerIn = UI.bannerEvery;
  private bannerLeft = 0;
  private bannerAge = 0;
  private running = false;

  constructor(parent: HTMLElement, private readonly sfx: Sfx) {
    this.note = document.createElement('div');
    this.note.className = 'notif hidden';
    this.note.innerHTML = `
      <div class="notif-icon"></div>
      <div class="notif-body">
        <div class="notif-head"><b>${content.notifications.app}</b><span>now</span></div>
        <div class="notif-text"></div>
      </div>`;
    this.noteText = this.note.querySelector('.notif-text')!;

    this.banner = document.createElement('div');
    this.banner.className = 'banner hidden';
    this.banner.dataset.ui = '';
    this.banner.innerHTML = `
      <span class="banner-tag">${content.banner.tag}</span>
      <div class="banner-copy"><b></b><span></span></div>
      <button class="banner-x hidden" aria-label="Close ad">&times;</button>`;
    this.bannerClose = this.banner.querySelector('.banner-x')!;
    this.banner.addEventListener('click', (e) => {
      if (e.target === this.bannerClose) {
        this.sfx.click();
        this.hideBanner();
        return;
      }
      // Clicking the ad itself "works".
      this.sfx.chime();
      this.banner.querySelector('.banner-copy span')!.textContent = content.banner.clicked;
    });

    parent.append(this.note, this.banner);
  }

  update(w: World, dt: number, paused: boolean): void {
    const running = w.phase === 'running';
    if (running !== this.running) {
      this.running = running;
      if (!running) {
        this.note.classList.add('hidden');
        this.hideBanner();
      }
      if (w.phase === 'ready') {
        this.notifyIn = rand(UI.notifyMin, UI.notifyMax);
        this.bannerIn = UI.bannerEvery;
      }
    }
    if (!running || paused) return;

    this.notifyIn -= dt;
    if (this.notifyIn <= 0) {
      this.notifyIn = rand(UI.notifyMin, UI.notifyMax);
      this.noteText.textContent = fill(pick(content.notifications.lines));
      this.note.classList.remove('hidden');
      restartAnimation(this.note);
      this.noteLeft = UI.notifyShow;
      this.notificationsShown++;
      this.sfx.chime();
    }
    if (this.noteLeft > 0) {
      this.noteLeft -= dt;
      if (this.noteLeft <= 0) this.note.classList.add('hidden');
    }

    this.bannerIn -= dt;
    if (this.bannerIn <= 0) {
      this.bannerIn = UI.bannerEvery;
      this.showBanner();
    }
    if (this.bannerLeft > 0) {
      this.bannerLeft -= dt;
      this.bannerAge += dt;
      // The close button turns up late, and small. Industry standard.
      if (this.bannerAge >= UI.bannerCloseAfter) this.bannerClose.classList.remove('hidden');
      if (this.bannerLeft <= 0) this.hideBanner();
    }
  }

  /** Clear whatever is on screen (the gate scan wants it). */
  hideAll(): void {
    this.note.classList.add('hidden');
    this.noteLeft = 0;
    this.hideBanner();
  }

  private showBanner(): void {
    const brand = pick(content.brands);
    this.banner.style.setProperty('--ad-bg', brand.bg);
    this.banner.style.setProperty('--ad-fg', brand.fg);
    this.banner.querySelector('.banner-copy b')!.textContent = brand.name;
    this.banner.querySelector('.banner-copy span')!.textContent = brand.line;
    this.bannerClose.classList.add('hidden');
    this.banner.classList.remove('hidden');
    restartAnimation(this.banner);
    this.bannerLeft = UI.bannerShow;
    this.bannerAge = 0;
    this.bannersShown++;
    this.sfx.jingle(brand.jingle);
  }

  private hideBanner(): void {
    this.banner.classList.add('hidden');
    this.bannerLeft = 0;
  }
}

export function restartAnimation(el: HTMLElement): void {
  el.style.animation = 'none';
  void el.offsetWidth;
  el.style.animation = '';
}
