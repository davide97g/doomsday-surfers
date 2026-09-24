// Mid-run distractions: fake push notifications and banner ads at the bottom.
// Notifications are big and pile up (one per slot, up to ui.notifyMaxOnScreen),
// but only at the top or bottom edge: they never cover the track ahead (the
// reel they open does). Each one bumps dopamine just by arriving;
// tapping it opens it for the super boost. About half are reel shares ("a friend
// sent you a reel"): opening one also plays the clip (see reel.ts). A swipe that
// starts on a card flings it away and still steers the runner, so a nag never
// eats a dodge.
// Work mode swaps the feed notification for office app cards (chat, mail,
// calendar, ticket, Humbl) and incoming calls: a call rings until it's gone,
// Accept (or a tap) opens the meeting panel (meeting.ts), Decline dismisses it.

import { content, mode, work } from '../content/content';
import { SWIPE_PX } from '../input/input';
import { TUNING, type Action } from '../sim/types';
import type { World } from '../sim/world';
import { fill, pick } from '../content/templates';
import { hue, initials } from './meeting';
import { reelSrc } from './reel';
import type { Sfx } from './sfx';

const UI = TUNING.ui;
const N = content.notifications;
/** Where a card can land: under the HUD, or above the banner ad. */
const SLOTS = ['top', 'bottom'];
const LEAVE_MS = 260;
const TOAST_MS = 1600;
const CARDS = work.cards;
type CardKind = 'chat' | 'mail' | 'calendar' | 'ticket' | 'humbl';
const KINDS: CardKind[] = ['chat', 'mail', 'calendar', 'ticket', 'humbl'];
const KIND_WEIGHT = KINDS.reduce((s, k) => s + CARDS[k].weight, 0);

function pickKind(): CardKind {
  let r = Math.random() * KIND_WEIGHT;
  for (const k of KINDS) {
    r -= CARDS[k].weight;
    if (r < 0) return k;
  }
  return 'chat';
}

function avatar(name: string): string {
  return `<div class="wc-avatar" style="--h:${hue(name)}">${initials(name)}</div>`;
}

function rand(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

/** A reel a "friend" sent: which clip, and who to blame. */
export interface ReelShare {
  clip: number;
  friend: string;
}

interface Note {
  el: HTMLElement;
  reel: ReelShare | null;
  /** Work mode incoming call: who's calling. */
  call: string | null;
  bar: HTMLElement;
  /** Seconds on screen in total (calls ring longer). */
  show: number;
  slot: number;
  left: number;
  /** Leaving (opened, flung or expired): no more input, removed shortly. */
  gone: boolean;
}

export class Nags {
  notificationsShown = 0;
  bannersShown = 0;
  onArrive: () => void = () => {};
  onOpen: (reel: ReelShare | null, call: string | null) => void = () => {};
  onSwipe: (a: Action) => void = () => {};
  /** A reel is playing in the top slot's space: new cards go to the bottom. */
  topBlocked = false;
  private readonly notes: Note[] = [];
  private readonly layer: HTMLElement;
  private readonly banner: HTMLElement;
  private readonly bannerClose: HTMLElement;
  private notifyIn = rand(UI.notifyMin, UI.notifyMax);
  private bannerIn = UI.bannerEvery;
  private bannerLeft = 0;
  private bannerAge = 0;
  private running = false;
  private ringing = false;
  private lastClip = -1;

  constructor(parent: HTMLElement, private readonly sfx: Sfx) {
    this.layer = document.createElement('div');
    this.layer.className = 'notifs';

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

    parent.append(this.layer, this.banner);
  }

  update(w: World, dt: number, paused: boolean): void {
    const running = w.phase === 'running';
    if (running !== this.running) {
      this.running = running;
      if (!running) this.hideAll();
      if (w.phase === 'ready') {
        this.notifyIn = rand(UI.notifyMin, UI.notifyMax);
        this.bannerIn = UI.bannerEvery;
      }
    }
    // A call rings while its card is up, and goes quiet while the run is paused.
    const ringing = running && !paused && this.notes.some((n) => n.call !== null && !n.gone);
    if (ringing !== this.ringing) {
      this.ringing = ringing;
      this.sfx.ring(ringing);
    }
    if (!running || paused) return;

    this.notifyIn -= dt;
    if (this.notifyIn <= 0) {
      this.notifyIn = rand(UI.notifyMin, UI.notifyMax);
      this.showNote();
    }
    for (const n of this.notes) {
      if (n.gone) continue;
      n.left -= dt;
      n.bar.style.transform = `scaleX(${Math.max(0, n.left / n.show)})`;
      if (n.left <= 0) this.dismiss(n, 'expired');
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
    for (const n of this.notes) n.el.remove();
    this.notes.length = 0;
    this.hideBanner();
  }

  private showNote(): void {
    const taken = new Set(this.notes.filter((n) => !n.gone).map((n) => n.slot));
    if (this.topBlocked) taken.add(SLOTS.indexOf('top'));
    const free = SLOTS.map((_, i) => i).filter((i) => !taken.has(i));
    if (free.length === 0 || taken.size >= UI.notifyMaxOnScreen) return;
    const slot = free[Math.floor(Math.random() * free.length)];
    this.notificationsShown++;

    const el = document.createElement('div');
    el.className = `notif slot-${SLOTS[slot]}`;
    el.dataset.ui = '';
    el.style.setProperty('--tilt', `${rand(-3, 3).toFixed(1)}deg`);
    const { reel, call, kind } = mode === 'work' ? this.fillWork(el) : this.fillFeed(el);
    const show = call ? UI.callShow : UI.notifyShow;
    const note: Note = { el, reel, call, bar: el.querySelector('.notif-bar')!, show, slot, left: show, gone: false };
    this.bindPointer(note);
    this.layer.append(el);
    this.notes.push(note);
    if (mode === 'work') this.sfx.notify(kind);
    else this.sfx.chime();
    this.onArrive();
  }

  /** Personal mode: a feed push notification, about half of them reel shares. */
  private fillFeed(el: HTMLElement): { reel: ReelShare | null; call: null; kind: string } {
    el.innerHTML = `
      <div class="notif-icon"><span class="notif-badge"></span></div>
      <div class="notif-body">
        <div class="notif-head"><b>${N.app}</b><span>now</span></div>
        <div class="notif-text"></div>
        <div class="notif-cta"><b>${N.cta}</b><span></span></div>
      </div>
      <div class="notif-bar"></div>`;
    el.querySelector('.notif-badge')!.textContent = String(this.notificationsShown);
    el.querySelector('.notif-cta span')!.textContent = pick(N.ctaLines);
    let reel: ReelShare | null = null;
    if (Math.random() < UI.reelChance) {
      const clips = N.reel.clips.length;
      let clip = Math.floor(Math.random() * clips);
      if (clip === this.lastClip) clip = (clip + 1) % clips;
      this.lastClip = clip;
      reel = { clip, friend: fill('{handle}') };
      el.classList.add('is-reel');
      el.querySelector<HTMLElement>('.notif-icon')!.style.backgroundImage = `url(${reelSrc(clip, 'jpg')})`;
      el.querySelector('.notif-text')!.textContent = fill(pick(N.reel.lines), { friend: reel.friend });
      el.querySelector('.notif-cta b')!.textContent = N.reel.cta;
    } else {
      el.querySelector('.notif-text')!.textContent = fill(pick(N.lines));
    }
    return { reel, call: null, kind: 'feed' };
  }

  /** Work mode: an office app card, or (one call at a time) an incoming call. */
  private fillWork(el: HTMLElement): { reel: null; call: string | null; kind: string } {
    const C = CARDS.call;
    if (Math.random() < UI.callChance && !this.notes.some((n) => n.call !== null && !n.gone)) {
      const caller = fill(pick(C.callers));
      el.classList.add('work', 'kind-call');
      el.innerHTML = `
        <div class="wc-head"><span class="wc-glyph"></span><b>${C.app}</b><span class="wc-meta">${work.suite}</span></div>
        <div class="wc-row">${avatar(caller)}<div class="wc-body"><b class="wc-from"></b><div class="wc-text">${C.ringing}</div></div></div>
        <div class="wc-actions"><button data-act="decline">${C.decline}</button><button data-act="accept">${C.accept}</button></div>
        <div class="notif-bar"></div>`;
      el.querySelector('.wc-from')!.textContent = caller;
      return { reel: null, call: caller, kind: 'call' };
    }
    const kind = pickKind();
    const card = CARDS[kind];
    const line = pick(card.lines);
    const from = fill(line.from);
    el.classList.add('work', `kind-${kind}`);
    el.innerHTML = `
      <div class="wc-head"><span class="wc-glyph"></span><b>${card.app}</b><span class="wc-meta"></span><span class="wc-now">now</span></div>
      <div class="wc-row">${avatar(from)}<div class="wc-body"><b class="wc-from"></b><div class="wc-text"></div></div></div>
      <div class="notif-cta"><b>${card.cta}</b><span></span></div>
      <div class="notif-bar"></div>`;
    el.querySelector('.wc-meta')!.textContent = `· ${pick(card.meta)}`;
    el.querySelector('.wc-from')!.textContent = from;
    el.querySelector('.wc-text')!.textContent = fill(line.text);
    el.querySelector('.notif-cta span')!.textContent = pick(N.ctaLines);
    return { reel: null, call: null, kind };
  }

  /** Tap opens (boost); a swipe flings the card away and steers the runner. */
  private bindPointer(n: Note): void {
    let id = -1;
    let x0 = 0;
    let y0 = 0;
    let swiped = false;
    let act = '';
    n.el.addEventListener('pointerdown', (e) => {
      if (n.gone || id !== -1) return;
      e.preventDefault();
      act = (e.target as HTMLElement).closest<HTMLElement>('[data-act]')?.dataset.act ?? '';
      id = e.pointerId;
      x0 = e.clientX;
      y0 = e.clientY;
      swiped = false;
      n.el.setPointerCapture(id);
      n.el.classList.add('pressed');
    });
    n.el.addEventListener('pointermove', (e) => {
      if (e.pointerId !== id || swiped || n.gone) return;
      const dx = e.clientX - x0;
      const dy = e.clientY - y0;
      if (Math.max(Math.abs(dx), Math.abs(dy)) < SWIPE_PX) return;
      swiped = true;
      const a: Action = Math.abs(dx) > Math.abs(dy) ? (dx < 0 ? 'left' : 'right') : dy < 0 ? 'up' : 'down';
      this.onSwipe(a);
      this.dismiss(n, `fling-${a}`);
    });
    const up = (e: PointerEvent) => {
      if (e.pointerId !== id) return;
      id = -1;
      n.el.classList.remove('pressed');
      if (swiped || n.gone || e.type === 'pointercancel') return;
      if (act === 'decline' && n.call) {
        this.sfx.click();
        this.toast(fill(CARDS.call.declined, { caller: n.call }));
        this.dismiss(n, 'fling-right');
        return;
      }
      this.sfx.reward();
      this.onOpen(n.reel, n.call);
      this.dismiss(n, 'opened');
    };
    n.el.addEventListener('pointerup', up);
    n.el.addEventListener('pointercancel', up);
  }

  private dismiss(n: Note, how: string): void {
    n.gone = true;
    n.el.classList.add('leaving', how);
    setTimeout(() => {
      n.el.remove();
      const i = this.notes.indexOf(n);
      if (i >= 0) this.notes.splice(i, 1);
    }, LEAVE_MS);
  }

  private toast(text: string): void {
    const t = document.createElement('div');
    t.className = 'toast work-toast';
    t.textContent = text;
    this.layer.append(t);
    setTimeout(() => t.remove(), TOAST_MS);
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
