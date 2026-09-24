// Work mode's reel: accepting a call opens a video meeting in a top corner
// (within the top 35% of the screen) for notify.reelTime seconds, laid out
// like a Meet call: a 2×2 grid of camera-off tiles (initial avatars, no faces:
// the caller, two coworkers, and you, muted), live captions typing out meeting
// clichés, and the control bar with the red hang-up pill. Like the reel, it outlasts the boost on
// purpose, and it ignores pointers so swipes still reach the track.

import { fill, pick } from '../content/templates';
import { work } from '../content/content';
import { ICON } from './icons';
import { appLogo } from './logos';
import { TUNING } from '../sim/types';
import type { World } from '../sim/world';

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

export class Meeting {
  private readonly el: HTMLElement;
  private readonly title: HTMLElement;
  private readonly grid: HTMLElement;
  private readonly caption: HTMLElement;
  private readonly bar: HTMLElement;
  private tiles: HTMLElement[] = [];
  private left = 0;
  private capIn = 0;
  private capText = '';
  private capWho = '';
  private capShown = 0;
  private speaker = 0;
  private lastCaption = -1;

  constructor(parent: HTMLElement) {
    this.el = document.createElement('div');
    this.el.className = 'meeting hidden';
    this.el.innerHTML = `
      <div class="mt-top">${appLogo('meeting')}<b></b><span class="rec"></span></div>
      <div class="mt-grid"></div>
      <div class="mt-cap"></div>
      <div class="mt-bar">
        <span class="mt-clock">10:32</span>
        <div class="mt-btns"><i class="off">${ICON.micOff}</i><i class="off">${ICON.video}</i><i>${ICON.present}</i><i>${ICON.hand}</i><i class="end">${ICON.end}</i></div>
      </div>
      <div class="reel-bar"></div>`;
    this.title = this.el.querySelector('.mt-top b')!;
    this.grid = this.el.querySelector('.mt-grid')!;
    this.caption = this.el.querySelector('.mt-cap')!;
    this.bar = this.el.querySelector('.reel-bar')!;
    parent.append(this.el);
  }

  get playing(): boolean {
    return this.left > 0;
  }

  play(caller: string): void {
    this.el.classList.remove('hidden', 'left', 'right');
    this.el.classList.add(Math.random() < 0.5 ? 'left' : 'right');
    this.el.style.animation = 'none';
    void this.el.offsetWidth;
    this.el.style.animation = '';
    this.title.textContent = `${pick(M.titles)} · ${pick(M.codes)}`;
    const names = [caller];
    while (names.length < 3) {
      const n = fill('{coworker}');
      if (!names.includes(n)) names.push(n);
    }
    this.grid.innerHTML =
      names
        .map(
          (n) =>
            `<div class="mt-tile" style="--h:${hue(n)}"><div class="mt-av">${initials(n)}</div><span class="mt-name">${n}</span><i class="mt-wave"><b></b><b></b><b></b></i></div>`,
        )
        .join('') + `<div class="mt-tile you" style="--h:210"><div class="mt-av">ME</div><span class="mt-name">${M.you}</span><i class="mt-mic">${ICON.micOff}</i></div>`;
    this.tiles = [...this.grid.querySelectorAll<HTMLElement>('.mt-tile')];
    this.speaker = 0;
    this.nextCaption();
    this.left = TUNING.notify.reelTime;
    this.bar.style.transform = 'scaleX(0)';
  }

  update(w: World, dt: number, paused: boolean): void {
    if (this.left <= 0) return;
    if (w.phase !== 'running' || w.gateT >= 0) {
      this.hide();
      return;
    }
    if (paused) return;
    this.left -= dt;
    const total = TUNING.notify.reelTime;
    this.bar.style.transform = `scaleX(${1 - Math.max(0, this.left) / total})`;
    const now = new Date();
    this.el.querySelector('.mt-clock')!.textContent = `${now.getHours()}:${String(now.getMinutes()).padStart(2, '0')}`;
    // Captions type out, then the next person talks over them.
    this.capShown = Math.min(this.capText.length, this.capShown + dt * TYPE_CPS);
    this.caption.innerHTML = `<b>${this.capWho}</b>${this.capText.slice(0, Math.floor(this.capShown))}`;
    this.capIn -= dt;
    if (this.capIn <= 0) this.nextCaption();
    if (this.left <= 0) this.hide();
  }

  hide(): void {
    this.left = 0;
    this.el.classList.add('hidden');
  }

  private nextCaption(): void {
    this.capIn = CAPTION_EVERY;
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
