// A friend sent you a reel: opening a reel notification plays a short clip in
// a phone-shaped panel in the top-left or top-right corner (top 35% of the screen) for
// notify.reelTime seconds. It outlasts the super boost (notify.boostTime) on
// purpose: the last seconds you're still watching, and no longer immune. It
// ignores pointers so swipes still reach the track underneath.

import { content } from '../content/content';
import { fill } from '../content/templates';
import { TUNING } from '../sim/types';
import type { World } from '../sim/world';

const R = content.notifications.reel;
const LIKES_EVERY = 0.12;

export function reelSrc(clip: number, ext: 'mp4' | 'jpg'): string {
  return `${import.meta.env.BASE_URL}assets/reels/${R.clips[clip].file}.${ext}`;
}

function compact(n: number): string {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(n >= 1e5 ? 0 : 1)}K`;
  return String(Math.floor(n));
}

export class Reel {
  private readonly el: HTMLElement;
  private readonly video: HTMLVideoElement;
  private readonly sent: HTMLElement;
  private readonly handle: HTMLElement;
  private readonly caption: HTMLElement;
  private readonly likesEl: HTMLElement;
  private readonly bar: HTMLElement;
  private left = 0;
  private likes = 0;
  private likesIn = 0;

  constructor(parent: HTMLElement) {
    this.el = document.createElement('div');
    this.el.className = 'reel hidden';
    this.el.innerHTML = `
      <video muted playsinline loop preload="auto" disablepictureinpicture></video>
      <div class="reel-sent"></div>
      <div class="reel-likes"><span>&hearts;</span><b></b></div>
      <div class="reel-cap"><b></b><span></span></div>
      <div class="reel-bar"></div>`;
    this.video = this.el.querySelector('video')!;
    // iOS wants these as attributes and properties before it autoplays inline.
    this.video.muted = true;
    this.video.playsInline = true;
    this.sent = this.el.querySelector('.reel-sent')!;
    this.handle = this.el.querySelector('.reel-cap b')!;
    this.caption = this.el.querySelector('.reel-cap span')!;
    this.likesEl = this.el.querySelector('.reel-likes b')!;
    this.bar = this.el.querySelector('.reel-bar')!;
    parent.append(this.el);
  }

  get playing(): boolean {
    return this.left > 0;
  }

  /** Called from the tap that opened the notification, so play() runs inside a user gesture. */
  play(clip: number, friend: string): void {
    const c = R.clips[clip];
    this.el.classList.remove('hidden', 'left', 'right');
    this.el.classList.add(Math.random() < 0.5 ? 'left' : 'right');
    this.el.style.animation = 'none';
    void this.el.offsetWidth;
    this.el.style.animation = '';
    this.sent.textContent = fill(R.sentBy, { friend });
    this.handle.textContent = c.handle;
    this.caption.textContent = c.caption;
    this.likes = c.likes;
    this.likesEl.textContent = compact(this.likes);
    this.likesIn = LIKES_EVERY;
    this.video.poster = reelSrc(clip, 'jpg');
    this.video.src = reelSrc(clip, 'mp4');
    this.video.currentTime = 0;
    void this.video.play().catch(() => {});
    this.left = TUNING.notify.reelTime;
    this.bar.style.transform = 'scaleX(0)';
  }

  update(w: World, dt: number, paused: boolean): void {
    if (this.left <= 0) return;
    if (w.phase !== 'running' || w.gateT >= 0) {
      this.hide();
      return;
    }
    if (paused) {
      if (!this.video.paused) this.video.pause();
      return;
    }
    if (this.video.paused) void this.video.play().catch(() => {});
    this.left -= dt;
    this.bar.style.transform = `scaleX(${1 - Math.max(0, this.left) / TUNING.notify.reelTime})`;
    // Everyone else is watching too.
    this.likesIn -= dt;
    if (this.likesIn <= 0) {
      this.likesIn = LIKES_EVERY;
      this.likes += 1 + this.likes * 0.004 * Math.random();
      this.likesEl.textContent = compact(this.likes);
    }
    if (this.left <= 0) this.hide();
  }

  hide(): void {
    this.left = 0;
    this.el.classList.add('hidden');
    this.video.pause();
  }
}
