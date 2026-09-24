// After the fade to grey:
//   offer  -> "Watch a short ad to feel something again?" (once per run)
//   ad     -> unskippable fake ad, then the sim revives
//   final  -> "You are present. … Disgusting." + screen-time report + [SCROLL AGAIN]
// Everything in `final` is revealed on a timer, and the button only works once
// it is visible, so a panicked swipe can't skip the moment.

import content from '../config/content.json';
import { fill, pick } from '../content/templates';
import { TUNING } from '../sim/types';
import type { World } from '../sim/world';
import type { Nags } from './nags';
import type { Sfx } from './sfx';

type State = 'hidden' | 'offer' | 'ad' | 'final';

const LINE1_AT = 0.4;
const LINE2_AT = 2.0;
const REPORT_AT = 3.0;
const ROW_EVERY = 0.25;

function duration(s: number): string {
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return m > 0 ? `${m}m ${r}s` : `${r}s`;
}

export class Death {
  onRevive: () => void = () => {};
  onRestart: () => void = () => {};
  private state: State = 'hidden';
  private readonly offer: HTMLElement;
  private readonly ad: HTMLElement;
  private readonly adCount: HTMLElement;
  private readonly adSkip: HTMLElement;
  private readonly final: HTMLElement;
  private readonly rows: HTMLElement;
  private reveal: { el: HTMLElement; at: number; tick: boolean }[] = [];
  private finalT = 0;
  private adLeft = 0;
  private buttonLive = false;
  private world: World | null = null;
  private nags: Nags | null = null;

  constructor(parent: HTMLElement, private readonly sfx: Sfx) {
    const r = content.revive;
    const d = content.death;
    this.offer = document.createElement('div');
    this.offer.className = 'overlay dead offer hidden';
    this.offer.innerHTML = `
      <div class="prompt-card" data-ui>
        <div class="prompt-title">${r.title}</div>
        <div class="prompt-body">${r.body}</div>
        <button class="cta" data-act="watch">${r.cta}</button>
        <button class="decline" data-act="decline">${r.decline}</button>
      </div>`;
    this.offer.addEventListener('click', (e) => {
      const act = (e.target as HTMLElement).dataset.act;
      this.sfx.click();
      if (act === 'watch') this.show('ad');
      else if (act === 'decline') this.show('final');
    });

    this.ad = document.createElement('div');
    this.ad.className = 'overlay fake-ad hidden';
    this.ad.dataset.ui = '';
    this.ad.innerHTML = `
      <span class="banner-tag">${content.banner.tag}</span>
      <div class="ad-count"></div>
      <div class="ad-product"></div>
      <div class="ad-brand"></div>
      <div class="ad-line"></div>
      <button class="ad-skip">${r.skip}</button>`;
    this.adCount = this.ad.querySelector('.ad-count')!;
    this.adSkip = this.ad.querySelector('.ad-skip')!;
    this.adSkip.addEventListener('click', () => {
      this.sfx.click();
      this.adSkip.textContent = r.skipDenied;
    });

    this.final = document.createElement('div');
    this.final.className = 'overlay dead final hidden';
    this.final.innerHTML = `
      <div class="dead-line" data-at="${LINE1_AT}">${d.line1}</div>
      <div class="dead-line" data-at="${LINE2_AT}">${d.line2}</div>
      <div class="report">
        <div class="report-title" data-at="${REPORT_AT}">${content.report.title}</div>
        <div class="report-rows"></div>
      </div>
      <button class="cta" id="again" data-ui>${d.cta}</button>`;
    this.rows = this.final.querySelector('.report-rows')!;
    this.final.querySelector('#again')!.addEventListener('click', () => {
      if (!this.buttonLive) return;
      this.sfx.click();
      this.onRestart();
    });

    parent.append(this.offer, this.ad, this.final);
  }

  update(w: World, dt: number, nags: Nags): void {
    this.world = w;
    this.nags = nags;
    if (w.phase !== 'dead') {
      if (this.state !== 'hidden') this.show('hidden');
      return;
    }
    if (this.state === 'hidden') this.show(w.revivesLeft > 0 ? 'offer' : 'final');
    if (this.state === 'ad') {
      this.adLeft -= dt;
      this.adCount.textContent = fill(content.revive.countdown, { n: Math.max(1, Math.ceil(this.adLeft)) });
      if (this.adLeft <= 0) {
        this.adLeft = Infinity;
        this.sfx.reward();
        this.onRevive();
      }
    }
    if (this.state === 'final') {
      this.finalT += dt;
      for (const r of this.reveal) {
        if (r.at > this.finalT || r.el.classList.contains('on')) continue;
        r.el.classList.add('on');
        if (r.tick) this.sfx.tick();
        if (r.el.id === 'again') this.buttonLive = true;
      }
    }
  }

  private show(state: State): void {
    if (state === 'final') this.buildReport();
    this.state = state;
    this.offer.classList.toggle('hidden', state !== 'offer');
    this.ad.classList.toggle('hidden', state !== 'ad');
    this.final.classList.toggle('hidden', state !== 'final');
    if (state === 'ad') this.startAd();
    if (state === 'final') {
      this.finalT = 0;
      this.buttonLive = false;
      for (const r of this.reveal) r.el.classList.remove('on');
    }
  }

  private startAd(): void {
    const brand = pick(content.brands);
    this.ad.style.setProperty('--ad-bg', brand.bg);
    this.ad.style.setProperty('--ad-fg', brand.fg);
    this.ad.querySelector('.ad-brand')!.textContent = brand.name;
    this.ad.querySelector('.ad-line')!.textContent = brand.line;
    this.adSkip.textContent = content.revive.skip;
    this.adLeft = TUNING.revive.adSeconds;
    this.adCount.textContent = fill(content.revive.countdown, { n: this.adLeft });
    this.sfx.jingle(brand.jingle);
  }

  private buildReport(): void {
    const w = this.world!;
    const nags = this.nags!;
    const [likes, notifications, reels, outrage] = w.takenByType;
    let numbest = 0;
    w.tolerance.forEach((t, i) => {
      if (t < w.tolerance[numbest]) numbest = i;
    });
    const vars = {
      time: duration(w.time),
      likes,
      notifications: notifications + w.notificationsOpened,
      opened: w.notificationsOpened,
      received: nags.notificationsShown,
      smashed: w.smashed,
      reels,
      outrage,
      numbest: content.contentTypes[numbest].name,
      numbestPct: Math.round(w.tolerance[numbest] * 100),
      dodged: w.habitsDodged,
      mum: w.mumIgnored,
      span: Math.max(0.4, 8 * Math.pow(0.985, w.pickupsTaken)).toFixed(1),
      ads: w.adsPassed + nags.bannersShown,
      rank: Math.min(99, Math.max(1, Math.round(100 * (1 - Math.exp(-w.d / 1500))))),
    };
    this.rows.innerHTML = content.report.rows.map((row) => `<div class="report-row">${fill(row, vars)}</div>`).join('');

    this.reveal = [];
    for (const el of this.final.querySelectorAll<HTMLElement>('[data-at]')) {
      this.reveal.push({ el, at: Number(el.dataset.at), tick: false });
    }
    const rows = [...this.rows.children] as HTMLElement[];
    rows.forEach((el, i) => this.reveal.push({ el, at: REPORT_AT + 0.3 + i * ROW_EVERY, tick: true }));
    const button = this.final.querySelector<HTMLElement>('#again')!;
    this.reveal.push({ el: button, at: REPORT_AT + 0.7 + rows.length * ROW_EVERY, tick: false });
  }
}
