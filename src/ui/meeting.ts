// A Meet-style call window for the Work mode desk (desk.ts): accepting a call
// docks one of these, and several calls can run at once. It's a 2×2 grid of
// camera-off tiles (initial avatars, no faces: the caller, two coworkers, and
// you, muted), live captions typing out meeting clichés, and the control bar
// with the red hang-up pill. It stays until a checkpoint gate clears the desk.

import { fill, pick } from '../content/templates';
import { work } from '../content/content';
import { ICON } from './icons';
import { appLogo } from './logos';

const M = work.meeting;
const CAPTION_EVERY = 1.25;
const TYPE_CPS = 38;

export function initials(name: string): string {
  const words = name.replace(/\(.*?\)/g, '').replace(/[^A-Za-z' ]/g, '').trim().split(/\s+/);
  const w = words.filter((x) => x && x.toLowerCase() !== 'the' && x.toLowerCase() !== 'your');
  const pickFrom = w.length ? w : words;
  return (pickFrom.length > 1 ? pickFrom[0][0] + pickFrom[1][0] : (pickFrom[0] ?? '?').slice(0, 2)).toUpperCase();
}

/** A stable avatar colour per name. */
export function hue(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % 360;
  return h;
}

/** What the desk needs from any docked app window. */
export interface AppWindow {
  readonly el: HTMLElement;
  update(dt: number): void;
}

export class MeetWindow implements AppWindow {
  readonly el: HTMLElement;
  private readonly caption: HTMLElement;
  private readonly clock: HTMLElement;
  private readonly tiles: HTMLElement[];
  private capIn = 0;
  private capText = '';
  private capWho = '';
  private capShown = 0;
  private speaker = 0;
  private lastCaption = -1;
  private clockIn = 0;

  constructor(caller: string) {
    this.el = document.createElement('div');
    this.el.className = 'win meeting';
    const names = [caller];
    while (names.length < 3) {
      const n = fill('{coworker}');
      if (!names.includes(n)) names.push(n);
    }
    const tile = (n: string) =>
      `<div class="mt-tile" style="--h:${hue(n)}"><div class="mt-av">${initials(n)}</div><span class="mt-name">${n}</span><i class="mt-wave"><b></b><b></b><b></b></i></div>`;
    this.el.innerHTML = `
      <div class="mt-top">${appLogo('meeting')}<b>${pick(M.titles)} · ${pick(M.codes)}</b><span class="rec"></span></div>
      <div class="mt-grid">${names.map(tile).join('')}<div class="mt-tile you" style="--h:210"><div class="mt-av">ME</div><span class="mt-name">${M.you}</span><i class="mt-mic">${ICON.micOff}</i></div></div>
      <div class="mt-cap"></div>
      <div class="mt-bar">
        <span class="mt-clock"></span>
        <div class="mt-btns"><i class="off">${ICON.micOff}</i><i class="off">${ICON.video}</i><i>${ICON.present}</i><i>${ICON.hand}</i><i class="end">${ICON.end}</i></div>
      </div>`;
    this.caption = this.el.querySelector('.mt-cap')!;
    this.clock = this.el.querySelector('.mt-clock')!;
    this.tiles = [...this.el.querySelectorAll<HTMLElement>('.mt-tile')];
    this.nextCaption();
  }

  update(dt: number): void {
    this.clockIn -= dt;
    if (this.clockIn <= 0) {
      this.clockIn = 5;
      const now = new Date();
      this.clock.textContent = `${now.getHours()}:${String(now.getMinutes()).padStart(2, '0')}`;
    }
    // Captions type out, then the next person talks over them.
    const shown = Math.floor(this.capShown);
    this.capShown = Math.min(this.capText.length, this.capShown + dt * TYPE_CPS);
    if (Math.floor(this.capShown) !== shown) this.caption.innerHTML = `<b>${this.capWho}</b>${this.capText.slice(0, Math.floor(this.capShown))}`;
    this.capIn -= dt;
    if (this.capIn <= 0) this.nextCaption();
  }

  private nextCaption(): void {
    this.capIn = CAPTION_EVERY * (0.8 + Math.random() * 0.5);
    let i = Math.floor(Math.random() * M.captions.length);
    if (i === this.lastCaption) i = (i + 1) % M.captions.length;
    this.lastCaption = i;
    // Never you: you're muted.
    this.speaker = (this.speaker + 1 + Math.floor(Math.random() * 2)) % 3;
    this.tiles.forEach((t, k) => t.classList.toggle('talking', k === this.speaker));
    const who = this.tiles[this.speaker]?.querySelector('.mt-name')?.textContent ?? '';
    this.capWho = who.replace(/\s*\(.*\)/, '');
    this.capText = M.captions[i];
    this.capShown = 0;
  }
}
