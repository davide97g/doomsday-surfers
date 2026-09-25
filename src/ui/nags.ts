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
import type { SetPiece } from '../sim/setpiece';
import { TUNING, type Action } from '../sim/types';
import type { World } from '../sim/world';
import { fill, pick } from '../content/templates';
import { ICON } from './icons';
import { appLogo, appName, type AppKind } from './logos';
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
type CardKind = 'chat' | 'sync' | 'mail' | 'calendar' | 'ticket' | 'humbl';
const KINDS: CardKind[] = ['chat', 'sync', 'mail', 'calendar', 'ticket', 'humbl'];
/** Which real toast each card copies: the macOS banner (Slack, Jira, LinkedIn
 *  pushes), the Teams toast, or the Windows 11 Outlook toast. */
const STYLE: Record<CardKind, 'banner' | 'teams' | 'win'> = {
  chat: 'banner',
  ticket: 'banner',
  humbl: 'banner',
  sync: 'teams',
  mail: 'win',
  calendar: 'win',
};

const KIND_WEIGHT = KINDS.reduce((s, k) => s + CARDS[k].weight, 0);

function pickKind(): CardKind {
  let r = Math.random() * KIND_WEIGHT;
  for (const k of KINDS) {
    r -= CARDS[k].weight;
    if (r < 0) return k;
  }
  return 'chat';
}

function avatar(name: string, cls = ''): string {
  return `<div class="wc-avatar ${cls}" style="--h:${hue(name)}">${initials(name)}</div>`;
}

/** Title row of a Teams / Windows toast: logo, app name, overflow and close. */
function toastHead(kind: AppKind): string {
  return `<div class="tw-head">${appLogo(kind)}<span>${appName(kind)}</span><i class="tw-more">···</i><i class="tw-x">${ICON.close}</i></div>`;
}

function rand(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

/** A reel a "friend" sent: which clip, and who to blame. */
export interface ReelShare {
  clip: number;
  friend: string;
}

/** A Work card's app, docked on the desk when the card is opened. */
export interface OpenedApp {
  kind: string;
  who: string;
  text: string;
}

interface Note {
  el: HTMLElement;
  reel: ReelShare | null;
  /** Work mode incoming call: who's calling. */
  call: string | null;
  /** Work mode: the app this card opens on the desk. */
  app: OpenedApp | null;
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
  onOpen: (reel: ReelShare | null, app: OpenedApp | null) => void = () => {};
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
  /** Next Work card kind, forced (console/testing: game.nags.demo('call')). */
  private force: string | null = null;
  private piece: SetPiece | null = null;

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
    this.piece = w.setPiece;
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

  /** Testing: show a Work card of this kind now ('call', 'chat', 'sync', 'mail', ...). */
  demo(kind: string): void {
    this.force = kind;
    this.showNote();
    this.force = null;
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
    const { reel, call, kind, app } = mode === 'work' ? this.fillWork(el) : this.fillFeed(el);
    const show = call ? UI.callShow : UI.notifyShow;
    const note: Note = { el, reel, call, app, bar: el.querySelector('.notif-bar')!, show, slot, left: show, gone: false };
    this.bindPointer(note);
    this.layer.append(el);
    this.notes.push(note);
    if (mode === 'work') this.sfx.notify(kind);
    else this.sfx.chime();
    this.onArrive();
  }

  /** Personal mode: a feed push notification, about half of them reel shares. */
  private fillFeed(el: HTMLElement): { reel: ReelShare | null; call: null; kind: string; app: null } {
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
      // The Algorithm and Slop zones talk in their own voice most of the time.
      const zoneLines = this.piece === 'algorithm' || this.piece === 'slop' ? content.setPieces[this.piece].lines : null;
      el.querySelector('.notif-text')!.textContent = fill(pick(zoneLines && Math.random() < 0.65 ? zoneLines : N.lines));
    }
    return { reel, call: null, kind: 'feed', app: null };
  }

  /** Work mode: an office app toast, or (one call at a time) an incoming call. */
  private fillWork(el: HTMLElement): { reel: null; call: string | null; kind: string; app: OpenedApp } {
    const C = CARDS.call;
    el.style.setProperty('--tilt', '0deg');
    const forced = this.force;
    const callNow = forced ? forced === 'call' : Math.random() < UI.callChance && !this.notes.some((n) => n.call !== null && !n.gone);
    if (callNow) {
      const caller = fill(pick(C.callers));
      el.classList.add('work', 'tw', 'kind-call');
      el.innerHTML = `
        ${toastHead('call')}
        <div class="tw-row">${avatar(caller, 'lg')}<div class="tw-body"><b class="tw-from"></b><div class="tw-sub">${C.ringing}</div></div></div>
        <div class="tw-call">
          <button class="rb video" data-act="accept" aria-label="Accept with video">${ICON.video}</button>
          <button class="rb audio" data-act="accept" aria-label="${C.accept}">${ICON.call}</button>
          <button class="rb decline" data-act="decline" aria-label="${C.decline}">${ICON.end}</button>
        </div>
        <div class="notif-bar"></div>`;
      el.querySelector('.tw-from')!.textContent = caller;
      return { reel: null, call: caller, kind: 'call', app: { kind: 'call', who: caller, text: '' } };
    }
    const kind = forced && forced in CARDS && forced !== 'call' ? (forced as CardKind) : pickKind();
    const card = CARDS[kind];
    const line = pick(card.lines);
    const from = fill(line.from);
    const text = fill(line.text);
    const meta = pick(card.meta);
    const style = STYLE[kind];
    el.classList.add('work', style === 'banner' ? 'bn' : 'tw', `kind-${kind}`);
    if (style === 'banner') {
      // macOS banner: app icon, bold title + time, subtitle, body, sender photo.
      // Slack: sender, "in #channel", message. Jira / LinkedIn: app, context, "who did what".
      const who = from.replace(/\s*\(.*\)/, '');
      const chat = kind === 'chat';
      const title = chat ? from : appName(kind);
      const sub = chat ? (meta.startsWith('#') ? `in ${meta}` : meta) : meta;
      const body = chat ? text : kind === 'humbl' ? `${who} ${text}` : `${who}: ${text}`;
      el.innerHTML = `
        <div class="bn-icon">${appLogo(kind)}</div>
        <div class="bn-main">
          <div class="bn-top"><b></b><span>now</span></div>
          <div class="bn-sub"></div>
          <div class="bn-text"></div>
        </div>
        ${avatar(from, 'bn-photo')}
        <div class="notif-bar"></div>`;
      el.querySelector('.bn-top b')!.textContent = title;
      el.querySelector('.bn-sub')!.textContent = sub;
      el.querySelector('.bn-text')!.textContent = body;
    } else if (kind === 'sync') {
      // Teams chat toast: avatar with presence, name, message, quick reply box.
      el.innerHTML = `
        ${toastHead('sync')}
        <div class="tw-row">${avatar(from)}<div class="tw-body"><b class="tw-from"></b><div class="tw-text"></div></div></div>
        <div class="tw-reply"><span>${CARDS.sync.reply}</span>${ICON.chat}</div>
        <div class="notif-bar"></div>`;
      el.querySelector('.tw-from')!.textContent = from;
      el.querySelector('.tw-text')!.textContent = text;
    } else {
      // Windows 11 Outlook toast: sender, subject, preview, action buttons.
      const mail = kind === 'mail';
      const actions = mail ? CARDS.mail.actions : CARDS.calendar.actions;
      el.innerHTML = `
        ${toastHead(kind)}
        <div class="tw-row">${mail ? avatar(from, 'lg') : `<div class="tw-cal">${ICON.event}</div>`}<div class="tw-body">
          <b class="tw-from"></b><div class="tw-subject"></div><div class="tw-sub"></div>
        </div></div>
        <div class="tw-actions">${actions.map((a, i) => `<span class="${!mail && i === 0 ? 'primary' : ''}">${a}</span>`).join('')}</div>
        <div class="notif-bar"></div>`;
      el.querySelector('.tw-from')!.textContent = mail ? from : text;
      el.querySelector('.tw-subject')!.textContent = mail ? text : meta;
      el.querySelector('.tw-sub')!.textContent = mail ? pick(CARDS.mail.preview) : `${from} · ${appName('calendar')}`;
    }
    return { reel: null, call: null, kind, app: { kind, who: from, text } };
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
        this.sfx.notify('decline');
        this.toast(fill(CARDS.call.declined, { caller: n.call }));
        this.dismiss(n, 'fling-right');
        return;
      }
      this.sfx.reward();
      this.onOpen(n.reel, n.app);
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
